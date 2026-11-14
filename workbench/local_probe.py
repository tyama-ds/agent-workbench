"""Ask a loopback/LAN inference server for its context window.

After NousResearch/hermes-agent (model_metadata_llamacpp.py,
agent_init_ollama.py). Used only when a Local profile has no
``context_window_tokens``; the result is applied to one dispatch's profile
copy and never saved. Only loopback and literal private-LAN addresses are
contacted, without a proxy, environment settings or redirects, and with a
small response limit. Nothing here raises (except task cancellation).

- llama.cpp: ``GET /props`` -> ``default_generation_settings.n_ctx`` (older
  builds: top-level ``n_ctx``).
- Ollama: ``GET /api/version`` identifies the server; only then
  ``POST /api/show {"model": ...}``. ``parameters`` ``num_ctx`` is preferred
  (what Ollama allocates); otherwise ``model_info`` ``<arch>.context_length``.
  An unknown server is never sent a POST.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from urllib.parse import urlsplit

import aiohttp

from .providers import DEFAULT_LOCAL_BASE_URL, _copilot_bridge, local_host_kind

PROBE_TIMEOUT_SECONDS = 3.0
MAX_PROBE_RESPONSE_BYTES = 64 * 1024
# A failed probe is retried after this long, so a server started later is
# still detected, without spending the probe time on every model call.
NEGATIVE_CACHE_SECONDS = 60.0
MAX_CACHE_ENTRIES = 256
MIN_WINDOW_TOKENS = 256
MAX_WINDOW_TOKENS = 2_000_000  # The configured context_window_tokens maximum.
_NUM_CTX = re.compile(r"^\s*num_ctx\s+(\d{1,9})\s*$", re.MULTILINE)

_cache: dict[tuple[str, str], tuple[int | None, float]] = {}


def clear_cache() -> None:
    _cache.clear()


def _origin(base_url) -> str | None:
    """scheme://host[:port] of a loopback or private-LAN base URL, else None."""
    try:
        if not isinstance(base_url, str) or any(ord(char) < 33 for char in base_url):
            return None
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            return None
        parsed.port  # Raises ValueError for an invalid port.
        if local_host_kind(parsed.hostname) is None:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"
    except (ValueError, TypeError, AttributeError):
        return None


def _window(value) -> int | None:
    if type(value) is not int or value < MIN_WINDOW_TOKENS:
        return None
    return min(value, MAX_WINDOW_TOKENS)


def llamacpp_window(props) -> int | None:
    if not isinstance(props, dict):
        return None
    settings = props.get("default_generation_settings")
    nested = _window(settings.get("n_ctx")) if isinstance(settings, dict) else None
    return nested or _window(props.get("n_ctx"))


def ollama_window(show) -> int | None:
    if not isinstance(show, dict):
        return None
    parameters = show.get("parameters")
    if isinstance(parameters, str):
        match = _NUM_CTX.search(parameters)
        if match and _window(int(match.group(1))):
            return _window(int(match.group(1)))
    info = show.get("model_info")
    if not isinstance(info, dict):
        return None
    architecture = info.get("general.architecture")
    if isinstance(architecture, str) and _window(info.get(f"{architecture}.context_length")):
        return _window(info[f"{architecture}.context_length"])
    for key, value in info.items():
        if isinstance(key, str) and key.endswith(".context_length") and _window(value):
            return _window(value)
    return None


async def _json(session, method: str, url: str, **kwargs):
    """A bounded 200 JSON object, or None."""
    try:
        async with session.request(method, url, allow_redirects=False, proxy=None, **kwargs) as response:
            if response.status != 200:
                return None
            if response.content_length is not None and response.content_length > MAX_PROBE_RESPONSE_BYTES:
                return None
            body = b""
            while True:
                part = await response.content.readany()
                if not part:
                    break
                body += part
                if len(body) > MAX_PROBE_RESPONSE_BYTES:
                    return None
        value = json.loads(body)
        return value if isinstance(value, dict) else None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, UnicodeError, RecursionError):
        return None


async def _probe(origin: str, model: str, timeout: float) -> int | None:
    limits = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(trust_env=False, timeout=limits) as session:
        window = llamacpp_window(await _json(session, "GET", origin + "/props"))
        if window:
            return window
        version = await _json(session, "GET", origin + "/api/version")
        if version is None or not isinstance(version.get("version"), str):
            return None
        return ollama_window(await _json(session, "POST", origin + "/api/show", json={"model": model}))


async def probe_context_window(base_url: str, model: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> int | None:
    """The server's context window in tokens, or None. Cached per (origin, model)."""
    try:
        origin = _origin(base_url)
        if origin is None or not isinstance(model, str) or not model.strip() or len(model) > 200:
            return None
        key, now = (origin, model), time.monotonic()
        cached = _cache.get(key)
        if cached is not None and (cached[0] is not None or now - cached[1] < NEGATIVE_CACHE_SECONDS):
            return cached[0]
        try:
            async with asyncio.timeout(timeout):
                window = await _probe(origin, model, timeout)
        except Exception:  # Includes the probe deadline (TimeoutError).
            window = None
        if len(_cache) >= MAX_CACHE_ENTRIES and key not in _cache:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (window, now)
        return window
    except Exception:
        return None


async def local_context_window(profile: dict, limits: dict) -> int | None:
    """The probed window for a Local profile that has none, or None.

    Never the Copilot bridge. A window the configuration would reject (not
    larger than max_output_tokens + context_reserve_tokens) is ignored, so a
    small server default cannot stop a run that previously proceeded.
    """
    try:
        if profile.get("kind") != "local" or profile.get("context_window_tokens") or _copilot_bridge(profile):
            return None
        window = await probe_context_window(profile.get("base_url") or DEFAULT_LOCAL_BASE_URL, profile.get("model"))
        floor = int(limits.get("max_output_tokens", 0)) + int(limits.get("context_reserve_tokens", 0))
        return window if window and window > floor else None
    except Exception:
        return None
