"""Explicit HTTP adapters; only managed Copilot's validated JSON can request tools.

Ordinary prose is never interpreted as an executable tool command.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import email.utils
import ipaddress
import json
import random
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .resources import ResourceGate, integer, number, retry_settings
from .provider_observation import configure_observation, observation_phase, observed_provider_call
from .copilot_protocol import (
    enabled as copilot_json_enabled,
    normalize_reply as copilot_json_reply,
    request_parts as copilot_request_parts,
)

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOOL_ARGUMENT_BYTES = 256 * 1024
# Transient HTTP statuses that are safe to re-send: no tool ran and the
# provider produced no accepted reply. 529 is Anthropic "overloaded".
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 529})
# Cloud profiles cannot carry retry keys, so they need a built-in default.
# One transient 429/5xx must not permanently stop an agent.
CLOUD_DEFAULT_RETRIES = 3
CLOUD_DEFAULT_BACKOFF_SECONDS = 2
MAX_RETRY_DELAY_SECONDS = 60
# One in-provider retry after an explicit output-token limit doubles the limit,
# never past this cap, the validated maximum or the profile's own cap.
OUTPUT_LIMIT_RETRY_CAP = 32768
MAX_OUTPUT_TOKENS = 131072
# Connecting is bounded separately; request_timeout_seconds is the maximum
# silence between received bytes, not the total generation time.
CONNECT_TIMEOUT_SECONDS = 15
# A local server says nothing while it reads (prefills) a long prompt. A
# streamed Local request may wait longer for its first byte: the request
# timeout once more per ~32k estimated input tokens (4 bytes per token), up to
# 30 minutes (after hermes-agent's local stale-stream scaling). Later silence
# between chunks is still bounded by the request timeout.
LOCAL_FIRST_BYTE_CAP_SECONDS = 1800
LOCAL_PREFILL_TOKENS_PER_TIMEOUT = 32000
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:1234/v1"
# Wire formats are told apart by the endpoint suffix _endpoint() always adds.
_STREAM_FORMATS = (("/responses", "openai"), ("/messages", "anthropic"), ("/chat/completions", "local"))
# Stream error codes that, like HTTP 429/5xx, are safe to re-send.
_RETRYABLE_STREAM_ERRORS = frozenset({"overloaded_error", "api_error", "rate_limit_error", "server_error",
                                      "rate_limit_exceeded", "internal_error", "overloaded", "server_is_overloaded"})
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                          ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False,
                 retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


def retry_after_seconds(headers) -> float | None:
    """Parse server retry advice (retry-after-ms, Retry-After seconds or HTTP date)."""
    try:
        value = headers.get("retry-after-ms")
        if value is not None:
            seconds = float(value) / 1000
        else:
            value = headers.get("Retry-After")
            if value is None:
                return None
            value = value.strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", value):
                seconds = float(value)
            else:
                moment = email.utils.parsedate_to_datetime(value)
                seconds = moment.timestamp() - time.time()
    except (TypeError, ValueError, OverflowError, AttributeError):
        return None
    if seconds != seconds or seconds < 0:
        return 0.0 if seconds == seconds else None
    return min(float(MAX_RETRY_DELAY_SECONDS), seconds)


def retry_delay(exc: "ProviderError", attempt: int, backoff: float) -> float:
    """Honor server advice; otherwise exponential backoff with +/-10% jitter."""
    if exc.retry_after is not None:
        return min(float(MAX_RETRY_DELAY_SECONDS), exc.retry_after)
    base = min(float(MAX_RETRY_DELAY_SECONDS), backoff * 2 ** attempt)
    return base * random.uniform(0.9, 1.1)


class ProviderContextOverflowError(ProviderError):
    """The provider rejected the request as larger than the model's context."""


# Error-body classification (hermes-agent's error_classifier idea). Only these
# fixed codes and phrases are looked for; the body itself is never logged,
# returned or shown.
_QUOTA_CODES = frozenset({"insufficient_quota", "billing_hard_limit_reached", "billing_not_active",
                          "credit_balance_too_low", "quota_exceeded"})
_OVERFLOW_CODES = frozenset({"context_length_exceeded", "string_above_max_length", "request_too_large"})
_OVERFLOW_PHRASES = ("context length", "context_length", "maximum context", "context window", "prompt is too long",
                     "too many tokens", "exceeds the context", "exceed context", "n_ctx", "input is too long",
                     "maximum input length", "reduce the length")
_QUOTA_PHRASES = ("insufficient_quota", "credit balance is too low", "exceeded your current quota", "billing")
ERROR_BODY_PEEK_BYTES = 4096


def classify_error_body(status: int, body: bytes) -> str:
    """Return 'quota', 'context_overflow', or '' from a bounded error body."""
    text = body[:ERROR_BODY_PEEK_BYTES].decode("utf-8", "replace").lower()
    codes = set()
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        value = None
    if isinstance(value, dict):
        error = value.get("error")
        for item in (error if isinstance(error, dict) else {}, value):
            for key in ("code", "type"):
                if isinstance(item.get(key), str):
                    codes.add(item[key])
    if status in {402, 429} and (codes & _QUOTA_CODES or any(phrase in text for phrase in _QUOTA_PHRASES)):
        return "quota"
    if status in {400, 413, 422, 500} and (codes & _OVERFLOW_CODES or any(phrase in text for phrase in _OVERFLOW_PHRASES)):
        return "context_overflow"
    return ""


_STATUS_HINTS = {
    401: "authentication failed; check the API key",
    403: "access denied; check the API key permissions or organization access",
    404: "not found; check the model name and base URL",
}


class ProviderTimeoutError(ProviderError):
    """The provider HTTP deadline expired. Never retryable in the engine.

    ``streamed`` is true only when the request asked for a stream and no JSON
    (non-streamed) reply had started: closing such a request cancels generation
    on llama.cpp, vLLM and the cloud APIs, so the provider re-sends it once.
    A non-streamed request may still be generating and is never replayed.
    """

    def __init__(self, message: str, *, streamed: bool = False, **kwargs):
        super().__init__(message, **kwargs)
        self.streamed = streamed


class ProviderOutputLimitError(ProviderError):
    """Explicit provider output-token exhaustion, never a usable partial reply."""


@dataclass
class ModelReply:
    text: str = ""
    thinking: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def strict_json(value: str | bytes):
    return json.loads(value, parse_constant=_reject_constant, object_pairs_hook=_object_pairs)


def _arguments(value) -> dict:
    try:
        if isinstance(value, str):
            if len(value.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                raise ValueError
            result = strict_json(value)
        else:
            encoded = json.dumps(value, allow_nan=False)
            if len(encoded.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                raise ValueError
            result = copy.deepcopy(value)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ProviderError("Provider returned malformed tool arguments; no tools were executed") from None


def _call(call_id, name, arguments, seen: set[str]) -> dict:
    if (not isinstance(call_id, str) or not 1 <= len(call_id) <= 256 or call_id in seen
            or not isinstance(name, str) or not _NAME.fullmatch(name)):
        raise ProviderError("Provider returned an invalid or duplicate tool call")
    seen.add(call_id)
    return {"id": call_id, "name": name, "arguments": _arguments(arguments)}


def _native_call(call_id, name, arguments, seen: set[str]) -> dict:
    """Parse a provider-native tool call without discarding the whole reply.

    An invalid ID/name cannot be paired with a result and stays fatal. Bad
    arguments are kept as a call with an ``error`` that the engine returns to
    the model as a tool result, so the model can correct itself (Codex does
    the same) instead of the agent stopping. Such a call is never executed.
    """
    if (not isinstance(call_id, str) or not 1 <= len(call_id) <= 256 or call_id in seen
            or not isinstance(name, str) or not _NAME.fullmatch(name)):
        raise ProviderError("Provider returned an invalid or duplicate tool call")
    seen.add(call_id)
    if arguments is None or isinstance(arguments, str) and not arguments.strip():
        # Local servers often send "" for tools without parameters.
        arguments = {}
    try:
        return {"id": call_id, "name": name, "arguments": _arguments(arguments)}
    except ProviderError:
        if isinstance(arguments, str) and arguments.lstrip().startswith(("{", "[")) \
                and not arguments.rstrip().endswith(("}", "]")):
            # Unterminated JSON is a reply cut off by the output limit, even when
            # a server or router reports finish_reason "tool_calls" instead of
            # "length". Use the output-limit path (one larger retry, then the
            # existing recovery) rather than asking the model to re-type it.
            raise ProviderOutputLimitError("Tool call arguments were cut off by the output limit; "
                                           "no tools were executed") from None
        return {"id": call_id, "name": name, "arguments": {},
                "error": "Tool arguments were not one valid JSON object, so this tool was not executed. "
                         "Call it again with a single JSON object that matches the tool schema."}


def split_thinking(content: str) -> tuple[str, str]:
    """Separate only an explicit leading Qwen-style thinking block.

    An unclosed block is entirely thinking; it must not leak into tool parsing or
    be presented as a final answer. Tags quoted later in prose remain ordinary text.
    """
    leading = content.lstrip()
    if not leading.startswith("<think>"):
        return content, ""
    body = leading[len("<think>"):]
    if "</think>" not in body:
        return "", body
    thinking, answer = body.split("</think>", 1)
    return answer.lstrip("\r\n"), thinking


def local_host_kind(host: str) -> str | None:
    if host.lower() == "localhost":
        return "loopback"
    if "%" in host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if address.is_loopback:
        return "loopback"
    if any(address in network for network in _PRIVATE_NETWORKS):
        return "lan"
    return None


def _endpoint(base_url: str, suffix: str, *, allow_local_network: bool = False) -> str:
    try:
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or any(ord(c) < 33 for c in base_url)):
            raise ValueError
        parsed.port
        location = local_host_kind(parsed.hostname)
        if parsed.scheme == "http" and location != "loopback" and not (allow_local_network and location == "lan"):
            raise ProviderError("Non-loopback provider endpoints require HTTPS")
        path = parsed.path.rstrip("/")
        if not path.endswith(suffix):
            path += suffix
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    except (ValueError, TypeError, AttributeError):
        raise ProviderError("Invalid provider base URL") from None


def _native(message: dict, provider: str) -> dict | None:
    raw = message.get("provider_raw")
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("provider") != provider:
        raise ProviderError("Conversation belongs to a different provider; start a new conversation")
    return raw


def _proxy_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or any(ord(char) < 33 for char in value)):
            raise ValueError
        parsed.port
        return value.rstrip("/")
    except (ValueError, TypeError, AttributeError):
        raise ProviderError("Invalid proxy URL") from None


def _content(message: dict) -> str:
    value = message.get("content", "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProviderError("Conversation content must be text")
    return value


def _openai_messages(messages: list[dict]) -> list[dict]:
    result = []
    for message in messages:
        role = message.get("role")
        raw = _native(message, "openai") if role == "assistant" else None
        if raw is not None:
            output = raw.get("output")
            if not isinstance(output, list):
                raise ProviderError("Invalid saved OpenAI conversation")
            result.extend(copy.deepcopy(output))
        elif role == "tool":
            result.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": _content(message)})
        elif role in {"user", "assistant", "system", "developer"}:
            text = _content(message)
            if text or role != "assistant":
                result.append({"role": role, "content": text})
            if role == "assistant":
                for call in message.get("tool_calls", []):
                    result.append({"type": "function_call", "call_id": call["id"], "name": call["name"],
                                   "arguments": json.dumps(_arguments(call["arguments"]), ensure_ascii=False)})
        else:
            raise ProviderError("Unsupported conversation role")
    return result


def _anthropic_messages(messages: list[dict]) -> list[dict]:
    result = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            role, blocks = "user", [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": _content(message)}]
        elif role == "assistant":
            raw = _native(message, "anthropic")
            if raw is not None:
                blocks = copy.deepcopy(raw.get("content"))
                if not isinstance(blocks, list):
                    raise ProviderError("Invalid saved Anthropic conversation")
            else:
                blocks = [{"type": "text", "text": _content(message)}] if _content(message) else []
                blocks += [{"type": "tool_use", "id": call["id"], "name": call["name"],
                            "input": _arguments(call["arguments"])} for call in message.get("tool_calls", [])]
        elif role == "user":
            blocks = [{"type": "text", "text": _content(message)}]
        else:
            raise ProviderError("Anthropic conversation supports user, assistant and tool roles")
        # Parallel tool results must appear together before the next assistant.
        if result and result[-1]["role"] == role:
            result[-1]["content"].extend(blocks)
        else:
            result.append({"role": role, "content": blocks})
    return result


def _local_messages(messages: list[dict], system: str) -> list[dict]:
    result = [{"role": "system", "content": system}] if system else []
    for message in messages:
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ProviderError("Unsupported local conversation role")
        raw = _native(message, "local") if role == "assistant" else None
        if raw is not None:
            if 'copilot_protocol' in raw:
                raise ProviderError("Copilot text history cannot be replayed as native Local history; start a new conversation")
            native = raw.get("message")
            if not isinstance(native, dict):
                raise ProviderError("Invalid saved local conversation")
            result.append(copy.deepcopy(native))
            continue
        entry = {"role": role, "content": _content(message)}
        if role == "tool":
            entry["tool_call_id"] = message["tool_call_id"]
        if role == "assistant" and message.get("tool_calls"):
            entry["tool_calls"] = [{"id": call["id"], "type": "function", "function": {
                "name": call["name"], "arguments": json.dumps(_arguments(call["arguments"]), ensure_ascii=False)}}
                for call in message["tool_calls"]]
        result.append(entry)
    return result


def _tools(tools: list[dict]) -> list[dict]:
    result, names = [], set()
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in names:
            raise ProviderError("Invalid or duplicate tool definition")
        parameters = tool.get("parameters", {"type": "object", "properties": {}})
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ProviderError("Tool parameters must be an object schema")
        names.add(name)
        result.append({"name": name, "description": str(tool.get("description", "")), "parameters": copy.deepcopy(parameters)})
    return result


def _request_headers(kind: str, profile: dict, conversation_id: str | None) -> dict:
    headers = {"Content-Type": "application/json"}
    if kind == "local" and conversation_id:
        headers["X-Conversation-Id"] = re.sub(r"[^A-Za-z0-9_./:-]", "_", conversation_id)[:128]
    key = profile.get("api_key", "")
    if not isinstance(key, str) or any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise ProviderError("Invalid API key value")
    if kind != "local" and not key:
        raise ProviderError("This provider requires an API key")
    if key:
        headers["x-api-key" if kind == "anthropic" else "Authorization"] = key if kind == "anthropic" else "Bearer " + key
    if kind == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    return headers


def _request_payload(kind: str, model: str, profile: dict, messages: list[dict],
                     definitions: list[dict], system: str, maximum: int) -> dict:
    if kind == "openai":
        payload = {"model": model, "instructions": system, "input": _openai_messages(messages),
                   "store": False, "include": ["reasoning.encrypted_content"], "max_output_tokens": maximum,
                   "tools": [{"type": "function", **tool, "strict": False} for tool in definitions],
                   "stream": True}
        if profile.get("reasoning_effort"):
            payload["reasoning"] = {"effort": profile["reasoning_effort"], "summary": "auto"}
    elif kind == "anthropic":
        payload = {"model": model, "system": system, "messages": _anthropic_messages(messages), "max_tokens": maximum,
                   "tools": [{"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"]} for tool in definitions],
                   "stream": True}
        if profile.get("thinking") is not None:
            thinking = profile["thinking"]
            if not isinstance(thinking, dict) or thinking.get("type") not in {"adaptive", "enabled", "disabled"}:
                raise ProviderError("Invalid Anthropic thinking configuration")
            payload["thinking"] = copy.deepcopy(thinking)
    else:
        text_mode = copilot_json_enabled(profile, definitions)
        if text_mode and profile.get("_live_note"):
            # The Copilot JSON envelope has no free message slot; it is not cached.
            system = system + "\n\n" + profile["_live_note"]
        parts = (copilot_request_parts(messages, definitions, system) if text_mode
                 else {"messages": _local_messages(messages, system),
                       "tools": [{"type": "function", "function": tool} for tool in definitions]})
        # The Copilot bridge (and its strict JSON text mode) stays one JSON
        # reply. stream_options is omitted: some local servers reject it.
        payload = {"model": model, **parts, "max_tokens": maximum,
                   "stream": not (text_mode or _copilot_bridge(profile))}
        if profile.get("enable_thinking") is not None:
            if not isinstance(profile["enable_thinking"], bool):
                raise ProviderError("enable_thinking must be true or false")
            payload["chat_template_kwargs"] = {"enable_thinking": profile["enable_thinking"]}
    if kind == "anthropic":
        # Breakpoints first, so the last cached block is the latest persisted
        # content and the per-request note stays after it.
        _anthropic_cache(payload)
    if profile.get("_live_note") and not (kind == "local" and copilot_json_enabled(profile, definitions)):
        _append_live_note(kind, payload, profile["_live_note"])
    return payload


_CACHEABLE_BLOCKS = frozenset({"text", "tool_result", "tool_use", "image"})


def _anthropic_cache(payload: dict) -> None:
    """Mark the stable prefix for Anthropic prompt caching.

    One breakpoint on the latest persisted block caches everything before it
    (tools, system prompt and history); the next call reads that prefix.
    """
    messages = payload["messages"]
    if messages and isinstance(messages[-1].get("content"), list) and messages[-1]["content"]:
        block = messages[-1]["content"][-1]
        if isinstance(block, dict) and block.get("type") in _CACHEABLE_BLOCKS:
            block["cache_control"] = {"type": "ephemeral"}


def _append_live_note(kind: str, payload: dict, note: str) -> None:
    """Add the per-request note after the history, leaving tool results intact.

    OpenAI gets its own user item. Anthropic gets a text block after the last
    user turn's blocks. Local servers get a separate user message after tool
    results; after a user message the note is appended to it, because strict
    chat templates reject two user turns in a row.
    """
    if kind == "openai":
        payload["input"].append({"role": "user", "content": note})
    elif kind == "anthropic":
        messages = payload["messages"]
        if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list):
            messages[-1]["content"].append({"type": "text", "text": note})
        else:
            messages.append({"role": "user", "content": [{"type": "text", "text": note}]})
    else:
        messages = payload["messages"]
        last = messages[-1] if messages else None
        if isinstance(last, dict) and last.get("role") == "user" and isinstance(last.get("content"), str):
            last["content"] += "\n\n" + note
        else:
            messages.append({"role": "user", "content": note})


def _copilot_bridge(profile: dict) -> bool:
    return profile.get('id') == 'copilot-agent' and profile.get('_copilot_agent') is True


def _larger_output_limit(maximum: int, profile: dict) -> int | None:
    """The single doubled output limit to retry with, or None when it cannot grow."""
    larger = min(maximum * 2, OUTPUT_LIMIT_RETRY_CAP, MAX_OUTPUT_TOKENS)
    if "max_output_tokens" in profile:
        # A profile value is that model's own cap; asking for more fails.
        larger = min(larger, integer(profile, "max_output_tokens", maximum, 1, MAX_OUTPUT_TOKENS))
    return larger if larger > maximum else None


class _StreamProtocolError(ValueError):
    """A stream event did not match its wire format."""


def _stream_closed() -> ProviderError:
    # Nothing was accepted or executed, so re-sending is as safe as after a 5xx.
    return ProviderError("Provider stream closed before completion; no tools were executed", retryable=True)


def _stream_error(code) -> ProviderError:
    return ProviderError("Provider reported an error during the stream; response body withheld",
                         retryable=isinstance(code, str) and code in _RETRYABLE_STREAM_ERRORS)


def _index(value, limit: int = 4096) -> int:
    if type(value) is not int or not 0 <= value < limit:
        raise _StreamProtocolError
    return value


def _text(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _StreamProtocolError
    return value


class _ResponsesStream:
    """OpenAI Responses: the terminal event carries the complete response."""

    def __init__(self):
        self.result = None
        self.items = {}

    def feed(self, event: str | None, data: dict) -> bool:
        kind = data.get("type", event)
        if kind is not None and not isinstance(kind, str):
            raise _StreamProtocolError
        if kind in {"response.completed", "response.incomplete", "response.failed"}:
            response = data.get("response")
            if not isinstance(response, dict):
                raise _StreamProtocolError
            if not response.get("output") and self.items:
                # Some compatible servers send only per-item events in full.
                response = {**response, "output": [self.items[key] for key in sorted(self.items)]}
            self.result = response
            return True
        if kind == "response.output_item.done":
            item = data.get("item")
            if not isinstance(item, dict):
                raise _StreamProtocolError
            self.items[_index(data.get("output_index"))] = item
        elif kind == "error":
            error = data.get("error") if isinstance(data.get("error"), dict) else data
            raise _stream_error(error.get("code") or error.get("type"))
        return False

    def finish(self) -> dict:
        if self.result is None:
            raise _stream_closed()
        return self.result


class _MessagesStream:
    """Anthropic Messages: rebuild exactly the blocks a non-streamed reply holds."""

    def __init__(self):
        self.message = None
        self.blocks = {}
        self.partial = {}
        self.malformed = False
        self.done = False

    def feed(self, event: str | None, data: dict) -> bool:
        kind = data.get("type", event)
        if kind is not None and not isinstance(kind, str):
            raise _StreamProtocolError
        if kind == "error":
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            raise _stream_error(error.get("type"))
        if kind == "message_start":
            message = data.get("message")
            if self.message is not None or not isinstance(message, dict):
                raise _StreamProtocolError
            self.message = copy.deepcopy(message)
            self.message["content"] = []
            return False
        if kind not in {"content_block_start", "content_block_delta", "content_block_stop",
                        "message_delta", "message_stop"}:
            return False  # Unknown events are versioned additions, not content.
        if self.message is None:
            raise _StreamProtocolError
        if kind == "content_block_start":
            index, block = _index(data.get("index")), data.get("content_block")
            if index in self.blocks or not isinstance(block, dict) or not isinstance(block.get("type"), str):
                raise _StreamProtocolError
            self.blocks[index] = copy.deepcopy(block)
            if block["type"] == "tool_use":
                self.partial[index] = []
        elif kind == "content_block_delta":
            index, delta = _index(data.get("index")), data.get("delta")
            block = self.blocks.get(index)
            if block is None or not isinstance(delta, dict):
                raise _StreamProtocolError
            change = delta.get("type")
            if change == "text_delta":
                block["text"] = _text(block.get("text")) + _text(delta.get("text"))
            elif change == "thinking_delta":
                block["thinking"] = _text(block.get("thinking")) + _text(delta.get("thinking"))
            elif change == "signature_delta":
                block["signature"] = _text(block.get("signature")) + _text(delta.get("signature"))
            elif change == "input_json_delta":
                if index not in self.partial:
                    raise _StreamProtocolError
                self.partial[index].append(_text(delta.get("partial_json")))
            elif change == "citations_delta":
                citations = block.get("citations")
                block["citations"] = [*(citations if isinstance(citations, list) else []),
                                      copy.deepcopy(delta.get("citation"))]
        elif kind == "content_block_stop":
            index = _index(data.get("index"))
            if index not in self.blocks:
                raise _StreamProtocolError
            parts = self.partial.pop(index, None)
            if parts is not None and "".join(parts).strip():
                try:
                    value = strict_json("".join(parts))
                    if not isinstance(value, dict):
                        raise ValueError
                    self.blocks[index]["input"] = value
                except (ValueError, RecursionError):
                    # Deferred: an output-token limit explains truncated input.
                    self.malformed = True
        elif kind == "message_delta":
            delta = data.get("delta")
            if isinstance(delta, dict):
                for key in ("stop_reason", "stop_sequence"):
                    if key in delta:
                        self.message[key] = delta[key]
            usage = data.get("usage")
            if isinstance(usage, dict):
                merged = self.message.get("usage")
                self.message["usage"] = {**(merged if isinstance(merged, dict) else {}),
                                         **{key: value for key, value in usage.items() if value is not None}}
        elif kind == "message_stop":
            self.done = True
            return True
        return False

    def finish(self) -> dict:
        if self.message is None or not self.done:
            raise _stream_closed()
        if self.partial or sorted(self.blocks) != list(range(len(self.blocks))):
            raise _StreamProtocolError
        if self.malformed and self.message.get("stop_reason") != "max_tokens":
            raise ProviderError("Provider returned malformed tool arguments; no tools were executed")
        self.message["content"] = [self.blocks[index] for index in range(len(self.blocks))]
        return self.message


class _ChatStream:
    """OpenAI-compatible chat completions: merge choice 0 deltas into one message."""

    def __init__(self):
        self.role = None
        self.fields = {}
        self.calls = {}
        self.finish_reason = None
        self.usage = None
        self.chunks = 0

    def feed(self, event: str | None, data: dict | str) -> bool:
        if data == "[DONE]":
            return True
        if not isinstance(data, dict):
            raise _StreamProtocolError
        if data.get("error") is not None:
            error = data["error"] if isinstance(data["error"], dict) else {}
            code = error.get("code")
            raise _stream_error("server_error" if type(code) is int and code in RETRYABLE_STATUSES
                                else code or error.get("type"))
        self.chunks += 1
        if isinstance(data.get("usage"), dict):
            self.usage = copy.deepcopy(data["usage"])
        choices = data.get("choices") or []
        if not isinstance(choices, list):
            raise _StreamProtocolError
        for choice in choices:
            if not isinstance(choice, dict):
                raise _StreamProtocolError
            if choice.get("index", 0) != 0:
                continue  # Only one choice is requested and parsed.
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise _StreamProtocolError
            if isinstance(delta.get("role"), str) and self.role is None:
                self.role = delta["role"]
            for key in ("content", "reasoning_content", "reasoning", "refusal"):
                if delta.get(key) is not None:
                    self.fields.setdefault(key, []).append(_text(delta[key]))
            for position, fragment in enumerate(delta.get("tool_calls") or []):
                self._call(position, fragment)
            if choice.get("finish_reason") is not None:
                self.finish_reason = choice["finish_reason"]
        return False

    def _call(self, position: int, fragment) -> None:
        if not isinstance(fragment, dict):
            raise _StreamProtocolError
        index = fragment.get("index")
        if index is None:
            # Servers without indexes send each call whole or continue the last one.
            ident = fragment.get("id")
            known = [key for key, call in self.calls.items() if ident and call["id"] == ident]
            index = known[0] if known else (len(self.calls) if ident or not self.calls else max(self.calls))
        call = self.calls.setdefault(_index(index, 1024), {"id": None, "type": None, "name": None, "arguments": []})
        function = fragment.get("function") or {}
        if not isinstance(function, dict):
            raise _StreamProtocolError
        # Identity arrives once; servers that repeat it must not be concatenated.
        for key, value in (("id", fragment.get("id")), ("type", fragment.get("type")), ("name", function.get("name"))):
            if value is not None and call[key] is None:
                call[key] = _text(value)
        if function.get("arguments") is not None:
            arguments = function["arguments"]
            call["arguments"].append(arguments if isinstance(arguments, str) else json.dumps(arguments))

    def finish(self, done: bool) -> dict:
        if not done and self.finish_reason is None:
            raise _stream_closed()
        if not self.chunks:
            raise _StreamProtocolError
        message = {"role": self.role or "assistant"}
        content = "".join(self.fields["content"]) if "content" in self.fields else None
        message["content"] = content if content is not None or self.calls else ""
        for key in ("refusal", "reasoning_content", "reasoning"):
            if key in self.fields:
                message[key] = "".join(self.fields[key])
        if self.calls:
            if sorted(self.calls) != list(range(len(self.calls))):
                raise _StreamProtocolError
            message["tool_calls"] = [{"id": call["id"], "type": call["type"] or "function", "function": {
                "name": call["name"], "arguments": "".join(call["arguments"])}}
                for call in (self.calls[index] for index in range(len(self.calls)))]
        result = {"choices": [{"index": 0, "message": message, "finish_reason": self.finish_reason}]}
        if self.usage is not None:
            result["usage"] = self.usage
        return result


def first_byte_timeout(timeout: float, body_bytes: int, *, local: bool) -> float:
    """Seconds to wait for the response headers and first body chunk.

    Cloud requests and the non-streamed Copilot bridge wait ``timeout``. A
    streamed Local request scales it by the estimated prompt size (prefill),
    capped at LOCAL_FIRST_BYTE_CAP_SECONDS but never below ``timeout``.
    """
    if not local:
        return timeout
    estimated_tokens = max(0, body_bytes) / 4
    scaled = timeout * (1 + estimated_tokens / LOCAL_PREFILL_TOKENS_PER_TIMEOUT)
    return max(timeout, min(float(LOCAL_FIRST_BYTE_CAP_SECONDS), scaled))


async def _timed_parts(content, first_deadline: float, idle: float):
    """Yield body chunks: the first by ``first_deadline`` (loop time), each later
    one within ``idle`` seconds of the previous. The total is size-bounded."""
    size, first = 0, True
    while True:
        async with (asyncio.timeout_at(first_deadline) if first else asyncio.timeout(idle)):
            part = await content.readany()
        if not part:
            return
        first = False
        size += len(part)
        if size > MAX_RESPONSE_BYTES:
            raise ProviderError("Provider response exceeded the size limit")
        yield part


async def _read_event_stream(parts, wire: str) -> dict:
    """Parse text/event-stream chunks incrementally into the non-streamed reply shape."""
    state = {"openai": _ResponsesStream, "anthropic": _MessagesStream, "local": _ChatStream}[wire]()
    buffer, event, data, done = b"", None, [], False

    def dispatch() -> bool:
        nonlocal event, data
        name, lines = event, data
        event, data = None, []
        if not lines:
            return False
        text = "\n".join(lines)
        if wire == "local" and text.strip() == "[DONE]":
            return state.feed(name, "[DONE]")
        value = strict_json(text)
        if not isinstance(value, dict):
            raise _StreamProtocolError
        return state.feed(name, value)

    async for part in parts:
        buffer += part
        *lines, buffer = buffer.split(b"\n")
        for raw in lines:
            line = raw.rstrip(b"\r").decode("utf-8")
            if not line:
                if dispatch():
                    done = True
                    break
            elif line.startswith(":"):
                continue  # Comment or keep-alive.
            else:
                name, _, value = line.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if name == "data":
                    data.append(value)
                elif name == "event":
                    event = value
        if done:
            break
    if not done and buffer.strip():
        line = buffer.rstrip(b"\r").decode("utf-8")
        if line.startswith("data:"):
            data.append(line[6:] if line[5:6] == " " else line[5:])
    if not done and data:
        done = dispatch()
    return state.finish(done) if wire == "local" else state.finish()


class ProviderClient:
    def __init__(self, resource_gate: ResourceGate | None = None, *, gate: ResourceGate | None = None,
                 copilot_gate: ResourceGate | None = None):
        self.resource_gate = resource_gate or gate or ResourceGate()
        # Browser-backed Copilot requests do not consume local inference slots.
        # Its configured limit admits HTTP requests, not additional browser windows.
        self.copilot_resource_gate = copilot_gate if copilot_gate is not None else ResourceGate()

    async def local_context_window(self, profile: dict, limits: dict) -> int | None:
        """Probe a Local server's context window (see local_probe); never raises.

        A method of the real HTTP client, so engines running an injected or
        synthetic client never contact the configured URL directly.
        """
        from .local_probe import local_context_window
        return await local_context_window(profile, limits)

    def copilot_resource_snapshot(self) -> dict:
        return self.copilot_resource_gate.snapshot()

    @observed_provider_call
    async def complete(self, profile: dict, messages: list[dict], tools: list[dict],
                       system: str, limits: dict | None = None, *,
                       conversation_id: str | None = None) -> ModelReply:
        limits = limits or {}
        kind = profile.get("kind")
        if kind not in {"openai", "anthropic", "local"}:
            raise ProviderError("Unsupported provider kind")
        model = profile.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ProviderError("A model name is required")
        definitions = _tools(tools)
        local = limits.get("local", limits)
        settings = {**(local if kind == "local" else {}), **limits,
                    **{key: profile[key] for key in ("request_timeout_seconds",) if key in profile}}
        maximum = integer(limits, "max_output_tokens", 4096, 1, 131072)
        maximum = min(maximum, integer(profile, "max_output_tokens", maximum, 1, 131072))
        timeout = number(settings, "request_timeout_seconds", 120, 0.01, 3600)
        if kind == "local":
            timeout = min(timeout, number(local, "request_timeout_seconds", 120, 0.01, 3600))
        defaults = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1", "local": DEFAULT_LOCAL_BASE_URL}
        suffix = {"openai": "/responses", "anthropic": "/messages", "local": "/chat/completions"}[kind]
        endpoint = _endpoint(profile.get("base_url") or defaults[kind], suffix, allow_local_network=kind == "local")
        request_gate = self.resource_gate
        if kind == "local":
            location = local_host_kind(urlsplit(endpoint).hostname)
            if location is None:
                raise ProviderError("Local inference requires loopback or a literal private LAN IP address")
            if location == "lan" and local.get("gpu_guard_enabled", False):
                raise ProviderError("GPU guard cannot monitor a remote inference server; use server-side GPU controls")
            local = {**local, "_remote_endpoint": location == "lan"}
            if profile.get('id') == 'copilot-agent' and profile.get('_copilot_agent') is True:
                # The managed bridge runs a cloud-backed browser session, not
                # this machine's inference GPU. Keep ordinary queue/time limits,
                # using a separate admission limit, and never replay a UI request.
                if location != 'loopback':
                    raise ProviderError('Copilot Agent requires the local bridge')
                concurrent = profile.get('_copilot_max_concurrent_requests', 1)
                if type(concurrent) is not int or not 1 <= concurrent <= 16:
                    raise ProviderError('Copilot Agent concurrency must be an integer between 1 and 16')
                local = {**local, 'gpu_guard_enabled': False, 'max_retries': 0,
                         'max_concurrent_requests': concurrent}
                request_gate = self.copilot_resource_gate
        headers = _request_headers(kind, profile, conversation_id)
        payload = _request_payload(kind, model, profile, messages, definitions, system, maximum)
        proxy = None
        if kind != "local" and profile.get("proxy_url"):
            proxy = _proxy_url(profile["proxy_url"])
        retry_config = local if kind == "local" else {
            "max_retries": CLOUD_DEFAULT_RETRIES, "retry_backoff_seconds": CLOUD_DEFAULT_BACKOFF_SECONDS,
            **{key: profile[key] for key in ("max_retries", "retry_backoff_seconds") if key in profile}}
        retries, backoff = retry_settings(retry_config)
        configure_observation(provider_kind=kind,
            admission_kind=('copilot' if request_gate is self.copilot_resource_gate else 'local') if kind == 'local' else 'none',
            request_timeout_seconds=timeout,
            queue_timeout_seconds=retry_config.get('queue_timeout_seconds', 120) if kind == 'local' else None,
            attempt_limit=retries + 1)
        exchange = dict(kind=kind, model=model, profile=profile, definitions=definitions, endpoint=endpoint,
                        headers=headers, timeout=timeout, proxy=proxy, request_gate=request_gate,
                        retry_config=retry_config, retries=retries, backoff=backoff)
        try:
            return await self._exchange(payload=payload, **exchange)
        except ProviderOutputLimitError as exc:
            larger = _larger_output_limit(maximum, profile)
            if (larger is None or request_gate is self.copilot_resource_gate or _copilot_bridge(profile)
                    or copilot_json_enabled(profile, definitions)):
                raise
            # Retry once with room for the reply. Nothing was accepted or
            # executed, and only the output limit differs from the first request.
            observation_phase('error', error=exc)
            observation_phase('retry_wait', retry_after_seconds=0)
            field_name = "max_output_tokens" if kind == "openai" else "max_tokens"
            try:
                return await self._exchange(payload={**payload, field_name: larger}, **exchange)
            except ProviderOutputLimitError:
                raise
            except ProviderError as retry_exc:
                if retry_exc.status in {400, 413, 422}:
                    # The server refused the larger limit (for example, prompt
                    # plus output exceeds its context); the original typed
                    # failure keeps the engine's recovery flow available.
                    raise exc from None
                raise

    async def _exchange(self, *, kind: str, model: str, profile: dict, definitions: list[dict], endpoint: str,
                        payload: dict, headers: dict, timeout: float, proxy: str | None,
                        request_gate: ResourceGate, retry_config: dict, retries: int, backoff: float) -> ModelReply:
        # A timed-out streamed request is re-sent once (see ProviderTimeoutError);
        # that replay is a provider-level retry and does not use up `retries`.
        # The Copilot bridge (and its JSON text mode) is never replayed.
        replayable = not (_copilot_bridge(profile) or request_gate is self.copilot_resource_gate
                          or copilot_json_enabled(profile, definitions))
        attempt, replayed = 0, False
        while True:
            try:
                sent = attempt + 1 + replayed
                if kind == "local":
                    observation_phase('queue_wait', attempt=sent)
                    async with request_gate.slot(retry_config):
                        observation_phase('admitted')
                        # This is the _post boundary, not an exact socket-start
                        # or a measurement of GPU-only admission wait.
                        observation_phase('response_wait')
                        response = await self._post(endpoint, payload, headers, timeout, None)
                else:
                    observation_phase('response_wait', attempt=sent)
                    response = await self._post(endpoint, payload, headers, timeout, proxy)
                observation_phase('received')
                observation_phase('parse')
                text_mode = copilot_json_enabled(profile, definitions)
                if text_mode:
                    choices = response.get('choices') if isinstance(response, dict) else None
                    if (not isinstance(response, dict) or response.get('error') is not None
                            or not isinstance(choices, list) or len(choices) != 1
                            or not isinstance(choices[0], dict)):
                        raise ProviderError('Copilot bridge must return one successful choice; no tools were executed')
                reply = self._parse(kind, model, response, set() if text_mode else {tool["name"] for tool in definitions})
                if text_mode:
                    source_message = choices[0].get('message')
                    if isinstance(source_message, dict):
                        native_calls = source_message.get('tool_calls')
                        if (native_calls is not None and (not isinstance(native_calls, list) or native_calls)
                                or source_message.get('function_call') is not None):
                            raise ProviderError('Copilot JSON mode cannot accept native tool calls; no tools were executed')
                    return copilot_json_reply(reply, definitions, finish_reason=response['choices'][0].get('finish_reason'))
                return reply
            except ProviderTimeoutError as exc:
                # Only a streamed request is replayed: closing it cancelled the
                # generation, so nothing is left running. A non-streamed request
                # may still be generating, and a replay would duplicate the work.
                if not (exc.streamed and replayable):
                    raise
                if replayed:
                    raise ProviderTimeoutError("Provider request timed out again after one re-send; "
                                               "no automatic retry", streamed=True) from None
                replayed = True
                observation_phase('error', error=exc)
                observation_phase('retry_wait', retry_after_seconds=0)
            except ProviderError as exc:
                if not exc.retryable or attempt >= retries:
                    raise
                observation_phase('error', error=exc)
                delay = retry_delay(exc, attempt, backoff)
                observation_phase('retry_wait', retry_after_seconds=delay)
                await asyncio.sleep(delay)
                attempt += 1

    async def _post(self, endpoint: str, payload: dict, headers: dict, timeout: float, proxy: str | None) -> dict:
        # No total deadline: a long generation that keeps sending bytes may
        # continue (the engine enforces the run deadline). The response headers
        # and first body chunk must arrive within the first-byte timeout (longer
        # for a streamed Local prompt, which the server prefills silently); after
        # that, silence longer than the request timeout fails.
        connect = min(float(CONNECT_TIMEOUT_SECONDS), timeout)
        limits = aiohttp.ClientTimeout(total=None, connect=connect, sock_connect=connect, sock_read=None)
        path = urlsplit(endpoint).path
        wire = next((name for suffix, name in _STREAM_FORMATS if path.endswith(suffix)), None)
        streamed = wire is not None and payload.get("stream") is True
        try:
            body = json.dumps(payload).encode("utf-8")
            # Only Local requests use /chat/completions; the Copilot bridge is not streamed.
            first_wait = first_byte_timeout(timeout, len(body), local=streamed and wire == "local")
            first_deadline = asyncio.get_running_loop().time() + first_wait
            async with aiohttp.ClientSession(trust_env=False, timeout=limits) as session:
                async with asyncio.timeout_at(first_deadline):
                    response = await session.post(endpoint, data=body, headers=headers, proxy=proxy,
                                                  allow_redirects=False)
                async with response:
                    if response.status != 200:
                        message = f"Provider returned HTTP {response.status}; response body withheld"
                        try:
                            async with asyncio.timeout(timeout):
                                peek = await response.content.read(ERROR_BODY_PEEK_BYTES)
                            kind = classify_error_body(response.status, peek)
                        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError):
                            kind = ""
                        if kind == "quota":
                            raise ProviderError(message + "; the account quota or billing limit is exhausted, so this "
                                                "is not retried. Add credit or switch the profile.", status=response.status)
                        if kind == "context_overflow":
                            raise ProviderContextOverflowError(message + "; the request exceeds the model context",
                                                               status=response.status)
                        hint = _STATUS_HINTS.get(response.status)
                        raise ProviderError(message + (f"; {hint}" if hint else ""),
                                            status=response.status, retryable=response.status in RETRYABLE_STATUSES,
                                            retry_after=retry_after_seconds(response.headers))
                    async with contextlib.aclosing(_timed_parts(response.content, first_deadline, timeout)) as parts:
                        if wire is not None and response.content_type == "text/event-stream":
                            return await _read_event_stream(parts, wire)
                        # Servers (and fixtures) that ignore "stream" answer with JSON.
                        # Generation may be finished or still running server-side,
                        # so a timeout here is never replayed.
                        streamed = False
                        parsed = strict_json(b"".join([part async for part in parts]))
                    if not isinstance(parsed, dict):
                        raise ValueError
                    return parsed
        except ProviderError:
            raise
        except asyncio.TimeoutError:
            raise ProviderTimeoutError("Provider request timed out; no automatic retry", streamed=streamed) from None
        except aiohttp.ClientError:
            raise ProviderError("Provider connection failed; check the endpoint and network settings",
                                retryable=True) from None
        except (_StreamProtocolError, KeyError, AttributeError):
            raise ProviderError("Provider response did not match the expected protocol") from None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ProviderError("Provider returned invalid JSON") from None

    def _parse(self, kind: str, model: str, data: dict, allowed: set[str]) -> ModelReply:
        reply = ModelReply(usage=copy.deepcopy(data.get("usage", {})))
        seen = set()
        try:
            if kind == "openai":
                # The Responses status is optional. Its absence must not hide
                # explicit failure/incompletion evidence elsewhere in the reply.
                if (data.get("status") in {None, "incomplete"} and data.get("error") is None
                        and isinstance(data.get("incomplete_details"), dict)
                        and data["incomplete_details"].get("reason") == "max_output_tokens"):
                    raise ProviderOutputLimitError("OpenAI output token limit reached; no tools were executed")
                if (data.get("status") not in {None, "completed"}
                        or data.get("error") is not None or data.get("incomplete_details") is not None):
                    raise ProviderError("OpenAI response was incomplete or failed; no tools were executed")
                output = data["output"]
                if not isinstance(output, list):
                    raise ValueError
                reply.raw = {"provider": kind, "model": model, "output": copy.deepcopy(output)}
                for item in output:
                    if item.get("status") not in {None, "completed"}:
                        raise ProviderError("OpenAI output was incomplete or unconfirmed; no tools were executed")
                    if item["type"] == "function_call":
                        reply.tool_calls.append(_native_call(item["call_id"], item["name"], item["arguments"], seen))
                    elif item["type"] == "message":
                        for block in item["content"]:
                            if block["type"] in {"output_text", "refusal"}:
                                reply.text += block.get("text", block.get("refusal", ""))
                    elif item["type"] == "reasoning":
                        reply.thinking += "\n".join(block["text"] for block in item.get("summary", []) if block.get("type") == "summary_text")
            elif kind == "anthropic":
                if data.get("stop_reason") == "max_tokens" and data.get("error") is None:
                    raise ProviderOutputLimitError("Anthropic output token limit reached; no tools were executed")
                if data.get("stop_reason") not in {"end_turn", "tool_use", "stop_sequence"}:
                    raise ProviderError("Anthropic response was incomplete or unconfirmed; no tools were executed")
                content = data["content"]
                if not isinstance(content, list):
                    raise ValueError
                reply.raw = {"provider": kind, "model": model, "content": copy.deepcopy(content)}
                for block in content:
                    if block["type"] == "text":
                        reply.text += block["text"]
                    elif block["type"] == "thinking":
                        reply.thinking += block["thinking"]
                    elif block["type"] == "tool_use":
                        reply.tool_calls.append(_native_call(block["id"], block["name"], block["input"], seen))
            else:
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length" and data.get("error") is None:
                    raise ProviderOutputLimitError("Local model output token limit reached; no tools were executed")
                if choice.get("finish_reason") not in {"stop", "tool_calls"}:
                    raise ProviderError("Local model response was incomplete or unconfirmed; no tools were executed")
                message = choice["message"]
                if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
                    raise ValueError
                text = message.get("content") or ""
                if not isinstance(text, str):
                    raise ValueError
                refusal = message.get("refusal")
                if refusal is not None and not isinstance(refusal, str):
                    raise ValueError
                if refusal and (message.get("tool_calls") or choice["finish_reason"] == "tool_calls"):
                    raise ProviderError("Local model returned a refusal with tool calls; no tools were executed")
                reply.text, tagged = split_thinking(text)
                if refusal:
                    reply.text = "\n\n".join(part for part in (reply.text, refusal) if part)
                explicit = message.get("reasoning_content") or message.get("reasoning") or ""
                if not isinstance(explicit, str):
                    raise ValueError
                reply.thinking = explicit or tagged
                native = {key: copy.deepcopy(message[key]) for key in ("role", "content", "refusal", "tool_calls", "reasoning_content", "reasoning") if key in message}
                native.setdefault("role", "assistant")
                reply.raw = {"provider": kind, "model": model, "message": native}
                for index, call in enumerate(message.get("tool_calls") or []):
                    if call.get("type", "function") != "function":
                        raise ValueError
                    parsed = _native_call(call["id"], call["function"]["name"], call["function"]["arguments"], seen)
                    if "error" in parsed or not str(call["function"]["arguments"] or "").strip():
                        # Replay a well-formed object: some local servers re-parse
                        # history arguments and would reject the next request.
                        native["tool_calls"][index]["function"]["arguments"] = "{}"
                    reply.tool_calls.append(parsed)
            unknown = [call for call in reply.tool_calls if call["name"] not in allowed]
            if unknown and not allowed:
                raise ProviderError("Provider requested an unknown tool; no tools were executed")
            for call in unknown:
                # Not advertised in this turn: never execute it, but tell the
                # model instead of discarding its whole reply.
                call["error"] = (f"Unknown or currently unavailable tool: {call['name']}. It was not executed. "
                                 "Use only these tools: " + ", ".join(sorted(allowed))[:2000])
            if not isinstance(reply.text, str) or not isinstance(reply.thinking, str) or not isinstance(reply.usage, dict):
                raise ValueError
            return reply
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError("Provider response did not match the expected protocol") from None
