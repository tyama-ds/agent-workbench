"""Small explicit HTTP adapters; text is never interpreted as a tool command."""
from __future__ import annotations

import asyncio
import copy
import ipaddress
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .resources import ResourceGate, integer, number, retry_settings

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOOL_ARGUMENT_BYTES = 256 * 1024
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                          ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


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


class ProviderClient:
    def __init__(self, resource_gate: ResourceGate | None = None, *, gate: ResourceGate | None = None):
        self.resource_gate = resource_gate or gate or ResourceGate()

    async def complete(self, profile: dict, messages: list[dict], tools: list[dict],
                       system: str, limits: dict | None = None) -> ModelReply:
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
        defaults = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1", "local": "http://127.0.0.1:1234/v1"}
        suffix = {"openai": "/responses", "anthropic": "/messages", "local": "/chat/completions"}[kind]
        endpoint = _endpoint(profile.get("base_url") or defaults[kind], suffix, allow_local_network=kind == "local")
        if kind == "local":
            location = local_host_kind(urlsplit(endpoint).hostname)
            if location is None:
                raise ProviderError("Local inference requires loopback or a literal private LAN IP address")
            if location == "lan" and local.get("gpu_guard_enabled", False):
                raise ProviderError("GPU guard cannot monitor a remote inference server; use server-side GPU controls")
            local = {**local, "_remote_endpoint": location == "lan"}
        headers = {"Content-Type": "application/json"}
        key = profile.get("api_key", "")
        if not isinstance(key, str) or any(ord(c) < 32 or ord(c) == 127 for c in key):
            raise ProviderError("Invalid API key value")
        if kind != "local" and not key:
            raise ProviderError("This provider requires an API key")
        if key:
            headers["x-api-key" if kind == "anthropic" else "Authorization"] = key if kind == "anthropic" else "Bearer " + key
        if kind == "openai":
            payload = {"model": model, "instructions": system, "input": _openai_messages(messages),
                       "store": False, "include": ["reasoning.encrypted_content"], "max_output_tokens": maximum,
                       "tools": [{"type": "function", **tool, "strict": False} for tool in definitions]}
            if profile.get("reasoning_effort"):
                payload["reasoning"] = {"effort": profile["reasoning_effort"], "summary": "auto"}
        elif kind == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
            payload = {"model": model, "system": system, "messages": _anthropic_messages(messages), "max_tokens": maximum,
                       "tools": [{"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"]} for tool in definitions]}
            if profile.get("thinking") is not None:
                thinking = profile["thinking"]
                if not isinstance(thinking, dict) or thinking.get("type") not in {"adaptive", "enabled", "disabled"}:
                    raise ProviderError("Invalid Anthropic thinking configuration")
                payload["thinking"] = copy.deepcopy(thinking)
        else:
            payload = {"model": model, "messages": _local_messages(messages, system), "max_tokens": maximum,
                       "stream": False, "tools": [{"type": "function", "function": tool} for tool in definitions]}
            if profile.get("enable_thinking") is not None:
                if not isinstance(profile["enable_thinking"], bool):
                    raise ProviderError("enable_thinking must be true or false")
                payload["chat_template_kwargs"] = {"enable_thinking": profile["enable_thinking"]}
        proxy = None
        if kind != "local" and profile.get("proxy_url"):
            proxy = _proxy_url(profile["proxy_url"])
        retry_config = local if kind == "local" else {key: profile[key] for key in ("max_retries", "retry_backoff_seconds") if key in profile}
        retries, backoff = retry_settings(retry_config)
        for attempt in range(retries + 1):
            try:
                if kind == "local":
                    async with self.resource_gate.slot(retry_config):
                        response = await self._post(endpoint, payload, headers, timeout, None)
                else:
                    response = await self._post(endpoint, payload, headers, timeout, proxy)
                return self._parse(kind, model, response, {tool["name"] for tool in definitions})
            except ProviderError as exc:
                if not exc.retryable or attempt == retries:
                    raise
                await asyncio.sleep(min(60, backoff * 2 ** attempt))
        raise ProviderError("Provider request did not finish")

    async def _post(self, endpoint: str, payload: dict, headers: dict, timeout: float, proxy: str | None) -> dict:
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(endpoint, json=payload, headers=headers, proxy=proxy, allow_redirects=False) as response:
                    if response.status != 200:
                        raise ProviderError(f"Provider returned HTTP {response.status}; response body withheld",
                                            status=response.status, retryable=response.status in {429, 503})
                    parts, size = [], 0
                    async for part in response.content.iter_chunked(65536):
                        size += len(part)
                        if size > MAX_RESPONSE_BYTES:
                            raise ProviderError("Provider response exceeded the size limit")
                        parts.append(part)
                    parsed = strict_json(b"".join(parts))
                    if not isinstance(parsed, dict):
                        raise ValueError
                    return parsed
        except ProviderError:
            raise
        except asyncio.TimeoutError:
            raise ProviderError("Provider request timed out; no automatic retry") from None
        except aiohttp.ClientError:
            raise ProviderError("Provider connection failed; check the endpoint and network settings") from None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ProviderError("Provider returned invalid JSON") from None

    def _parse(self, kind: str, model: str, data: dict, allowed: set[str]) -> ModelReply:
        reply = ModelReply(usage=copy.deepcopy(data.get("usage", {})))
        seen = set()
        try:
            if kind == "openai":
                # The Responses status is optional. Its absence must not hide
                # explicit failure/incompletion evidence elsewhere in the reply.
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
                        reply.tool_calls.append(_call(item["call_id"], item["name"], item["arguments"], seen))
                    elif item["type"] == "message":
                        for block in item["content"]:
                            if block["type"] in {"output_text", "refusal"}:
                                reply.text += block.get("text", block.get("refusal", ""))
                    elif item["type"] == "reasoning":
                        reply.thinking += "\n".join(block["text"] for block in item.get("summary", []) if block.get("type") == "summary_text")
            elif kind == "anthropic":
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
                        reply.tool_calls.append(_call(block["id"], block["name"], block["input"], seen))
            else:
                choice = data["choices"][0]
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
                for call in message.get("tool_calls") or []:
                    if call.get("type", "function") != "function":
                        raise ValueError
                    reply.tool_calls.append(_call(call["id"], call["function"]["name"], call["function"]["arguments"], seen))
            if any(call["name"] not in allowed for call in reply.tool_calls):
                raise ProviderError("Provider requested an unknown tool; no tools were executed")
            if not isinstance(reply.text, str) or not isinstance(reply.thinking, str) or not isinstance(reply.usage, dict):
                raise ValueError
            return reply
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError("Provider response did not match the expected protocol") from None
