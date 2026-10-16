"""Conversation routing headers observed at real, loopback-only HTTP fixtures."""
import re

import pytest
from aiohttp import web

from workbench.providers import ProviderClient, ProviderError
from test_providers import TOOLS, assistant, fake_server


def local_reply():
    return web.json_response({"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": "Answer"}}]})


@pytest.mark.asyncio
async def test_local_conversation_header_does_not_change_payload_or_leak_to_later_calls():
    requests = []

    async def handler(request):
        requests.append((request.path, request.headers.copy(), await request.json()))
        return local_reply()

    async with fake_server(handler) as endpoint:
        client = ProviderClient()
        profile = dict(kind="local", model="local-test", base_url=endpoint,
                       api_key="fake-local-key", enable_thinking=False)
        messages = [{"role": "user", "content": "Read the allowed file"}]
        # The legacy positional call remains valid. No routing identity is
        # inferred from the profile or retained on this shared client.
        await client.complete(profile, messages, TOOLS, "Visible policy", {"max_output_tokens": 123})
        await client.complete(profile, messages, TOOLS, "Visible policy", {"max_output_tokens": 123},
                              conversation_id="run-42/agent_7")
        await client.complete(profile, messages, TOOLS, "Visible policy", {"max_output_tokens": 123})

    assert [headers.get("X-Conversation-Id") for _, headers, _ in requests] == [
        None, "run-42/agent_7", None]
    assert {path for path, _, _ in requests} == {"/v1/chat/completions"}
    assert all(headers["Authorization"] == "Bearer fake-local-key" for _, headers, _ in requests)
    assert all(headers["Content-Type"] == "application/json" for _, headers, _ in requests)
    assert requests[0][2] == requests[1][2] == requests[2][2] == {
        "model": "local-test",
        "messages": [{"role": "system", "content": "Visible policy"}, *messages],
        "max_tokens": 123,
        "stream": False,
        "tools": [{"type": "function", "function": TOOLS[0]}],
        "chat_template_kwargs": {"enable_thinking": False},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_id", [None, ""])
async def test_local_without_conversation_identity_has_no_header(conversation_id):
    received = []

    async def handler(request):
        received.append(request.headers.copy())
        return local_reply()

    async with fake_server(handler) as endpoint:
        await ProviderClient().complete(
            dict(kind="local", model="local-test", base_url=endpoint),
            [{"role": "user", "content": "Summarize this reference material"}], [], "",
            conversation_id=conversation_id)
    assert len(received) == 1
    assert "X-Conversation-Id" not in received[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("source,expected", [
    ("Run09_-./:AZaz/Agent19", "Run09_-./:AZaz/Agent19"),
    ("作業/担当", "__/__"),
    ("run\r\nX-Injected: true/agent\t\x00\x7f", "run__X-Injected:_true/agent___"),
    ("run?query=1#fragment\\agent+2@home", "run_query_1_fragment_agent_2_home"),
    ("run/é😀Ａ", "run/___"),
    (" run/agent ", "_run/agent_"),
    ("a" * 125 + "/b", "a" * 125 + "/b"),
    ("a" * 125 + "/bc", "a" * 125 + "/bc"),
    ("a" * 125 + "/bcd", "a" * 125 + "/bc"),
    ("作" * 130 + "/agent", "_" * 128),
])
async def test_local_conversation_id_is_safe_ascii_and_truncated_to_128(source, expected):
    received = []

    async def handler(request):
        received.append(request.headers.copy())
        return local_reply()

    async with fake_server(handler) as endpoint:
        await ProviderClient().complete(dict(kind="local", model="local-test", base_url=endpoint),
                                        [], [], "", conversation_id=source)
    assert len(received) == 1
    assert received[0]["X-Conversation-Id"] == expected
    assert re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", received[0]["X-Conversation-Id"])
    assert "X-Injected" not in received[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,path", [("openai", "/v1/responses"), ("anthropic", "/v1/messages")])
@pytest.mark.parametrize("conversation_id", ["run-42/agent_7", "作業\r\nX-Injected: true/担当"])
async def test_cloud_providers_never_receive_conversation_header(kind, path, conversation_id):
    requests = []

    async def handler(request):
        requests.append((request.path, request.headers.copy(), await request.json()))
        if kind == "openai":
            return web.json_response({"status": "completed", "output": []})
        return web.json_response({"stop_reason": "end_turn", "content": []})

    async with fake_server(handler) as endpoint:
        await ProviderClient().complete(dict(kind=kind, model="cloud-test", base_url=endpoint,
                                             api_key="fake-cloud-key"), [], [], "Visible policy",
                                        conversation_id=conversation_id)
    assert len(requests) == 1 and requests[0][0] == path
    headers, payload = requests[0][1:]
    assert "X-Conversation-Id" not in headers and "X-Injected" not in headers
    assert "conversation_id" not in payload
    if kind == "openai":
        assert headers["Authorization"] == "Bearer fake-cloud-key"
        assert payload["store"] is False
    else:
        assert headers["x-api-key"] == "fake-cloud-key"
        assert headers["anthropic-version"] == "2023-06-01"


@pytest.mark.asyncio
async def test_local_turns_keep_identity_and_other_agents_and_runs_are_separate():
    requests = []

    async def handler(request):
        requests.append((request.headers.get("X-Conversation-Id"), await request.json()))
        return local_reply()

    async with fake_server(handler) as endpoint:
        client = ProviderClient()
        profile = dict(kind="local", model="local-test", base_url=endpoint)
        messages = [{"role": "user", "content": "First turn"}]
        reply = await client.complete(profile, messages, [], "", conversation_id="run-1/agent-1")
        messages.extend([assistant(reply), {"role": "user", "content": "Continue"}])
        await client.complete(profile, messages, [], "", conversation_id="run-1/agent-1")
        # A replacement history still belongs to the same explicitly supplied
        # conversation. Its contents must not be used to derive a new ID.
        await client.complete(profile, [{"role": "user", "content": "Compacted reference"}], [], "",
                              conversation_id="run-1/agent-1")
        await client.complete(profile, messages, [], "", conversation_id="run-1/agent-2")
        await client.complete(profile, messages, [], "", conversation_id="run-2/agent-1")

    assert [identity for identity, _ in requests] == [
        "run-1/agent-1", "run-1/agent-1", "run-1/agent-1", "run-1/agent-2", "run-2/agent-1"]
    assert requests[0][1]["messages"] != requests[1][1]["messages"] != requests[2][1]["messages"]


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_status", [429, 503])
async def test_local_retry_preserves_header_and_payload_without_using_proxies(monkeypatch, retry_status):
    requests, proxy_calls = [], []

    async def proxy_handler(request):
        proxy_calls.append(request.path)
        return web.Response(status=500)

    async def handler(request):
        requests.append((request.headers.get("X-Conversation-Id"), await request.json()))
        if len(requests) == 1:
            return web.Response(status=retry_status)
        return local_reply()

    async with fake_server(proxy_handler) as proxy, fake_server(handler) as endpoint:
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            monkeypatch.setenv(name, proxy)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(name, "")
        reply = await ProviderClient().complete(
            dict(kind="local", model="local-test", base_url=endpoint, proxy_url=proxy),
            [{"role": "user", "content": "Same request on retry"}], [], "",
            {"local": {"max_retries": 1, "retry_backoff_seconds": 0}},
            conversation_id="run-42/agent_7")

    assert reply.text == "Answer" and len(requests) == 2
    assert requests[0] == requests[1]
    assert requests[0][0] == "run-42/agent_7"
    assert not proxy_calls


@pytest.mark.asyncio
async def test_conversation_header_does_not_relax_local_endpoint_restrictions(monkeypatch):
    async def unexpected_network(*args, **kwargs):
        pytest.fail("Disallowed Local endpoint must be rejected before any request")

    client = ProviderClient()
    monkeypatch.setattr(client, "_post", unexpected_network)
    with pytest.raises(ProviderError, match="loopback"):
        await client.complete(dict(kind="local", model="local-test", base_url="https://example.invalid/v1"),
                              [], [], "", conversation_id="run-42/agent_7")
