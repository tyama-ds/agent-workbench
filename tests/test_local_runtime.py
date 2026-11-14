"""Local runtime: first-byte patience, one streamed replay, context-window probe.

Every server is a loopback aiohttp fixture; nothing leaves this machine.
"""
import asyncio
import copy
import json
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

import workbench.local_probe as local_probe
import workbench.providers as providers
from workbench.local_probe import local_context_window, probe_context_window
from workbench.providers import ProviderClient, ProviderTimeoutError, first_byte_timeout
from test_engine import configured, reply, start
from test_provider_streaming import chat_chunk, sse


@pytest.fixture(autouse=True)
def fresh_probe_cache():
    local_probe.clear_cache()
    yield
    local_probe.clear_cache()


@asynccontextmanager
async def server(routes):
    """routes: [(method, path, handler)]; yields the origin URL."""
    app = web.Application()
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    try:
        yield f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
    finally:
        await runner.cleanup()


def chat(script, requests):
    """Streamed chat completion; script(n) -> (headers_delay, first_chunk_delay, mid_gap)."""
    async def handler(request):
        requests.append(await request.json())
        headers_delay, first_delay, gap = script(len(requests))
        await asyncio.sleep(headers_delay)
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        await asyncio.sleep(first_delay)
        frames = sse(chat_chunk({'content': 'Hel'}), chat_chunk({'content': 'lo'}), chat_chunk(finish='stop'), done=True)
        await response.write(frames[0])
        await asyncio.sleep(gap)
        for frame in frames[1:]:
            await response.write(frame)
        await response.write_eof()
        return response
    return handler


def local(url, timeout, **extra):
    return dict(kind='local', base_url=url + '/v1', model='m', request_timeout_seconds=timeout, **extra)


LONG_PROMPT = [{'role': 'user', 'content': 'x' * 16000}]  # ~4,000 estimated tokens


def test_first_byte_timeout_scales_only_local_and_is_capped():
    assert first_byte_timeout(10, 4 * 64000, local=False) == 10
    assert first_byte_timeout(10, 4 * 64000, local=True) == pytest.approx(30)  # 1 + 64k/32k
    assert first_byte_timeout(10, 0, local=True) == 10
    assert first_byte_timeout(600, 4 * 10_000_000, local=True) == 1800
    assert first_byte_timeout(3000, 4 * 10_000_000, local=True) == 3000  # Never below the request timeout.


@pytest.mark.parametrize('headers_first', [True, False])
async def test_slow_prefill_within_scaled_first_byte_timeout_succeeds_for_local(monkeypatch, headers_first):
    # 4,000 estimated tokens / 1,000 per timeout: first byte may take 5 x 0.4 s.
    monkeypatch.setattr(providers, 'LOCAL_PREFILL_TOKENS_PER_TIMEOUT', 1000)
    requests = []
    script = (lambda n: (0, 0.9, 0)) if headers_first else (lambda n: (0.9, 0, 0))
    async with server([('POST', '/{path:.*}', chat(script, requests))]) as url:
        reply_ = await ProviderClient().complete(local(url, 0.4), LONG_PROMPT, [], '', {})
    assert reply_.text == 'Hello' and len(requests) == 1 and requests[0]['stream'] is True


async def test_same_slow_first_byte_fails_for_cloud_after_one_replay(monkeypatch):
    monkeypatch.setattr(providers, 'LOCAL_PREFILL_TOKENS_PER_TIMEOUT', 1000)
    requests, release = [], asyncio.Event()

    async def silent(request):
        requests.append(await request.json())
        await release.wait()
        return web.json_response({})
    async with server([('POST', '/{path:.*}', silent)]) as url:
        try:
            with pytest.raises(ProviderTimeoutError, match='again after one re-send') as caught:
                await ProviderClient().complete(dict(kind='openai', base_url=url + '/v1', model='m', api_key='k',
                                                     request_timeout_seconds=0.4, max_retries=3),
                                                LONG_PROMPT, [], '', {})
        finally:
            release.set()
    assert not caught.value.retryable and len(requests) == 2 and requests[0]['stream'] is True


async def test_idle_gap_longer_than_timeout_mid_stream_fails(monkeypatch):
    monkeypatch.setattr(providers, 'LOCAL_PREFILL_TOKENS_PER_TIMEOUT', 1000)
    requests = []
    async with server([('POST', '/{path:.*}', chat(lambda n: (0, 0, 0.9), requests))]) as url:
        # The generous first-byte allowance does not extend later silence.
        with pytest.raises(ProviderTimeoutError, match='timed out') as caught:
            await ProviderClient().complete(local(url, 0.4), LONG_PROMPT, [], '', {'local': {'max_retries': 3}})
    assert caught.value.streamed and not caught.value.retryable
    assert len(requests) == 2  # One replay, never more, and not counted against max_retries.


async def test_one_replay_after_streamed_timeout_then_success():
    requests = []
    async with server([('POST', '/{path:.*}', chat(lambda n: (0, 0, 0.9 if n == 1 else 0), requests))]) as url:
        reply_ = await ProviderClient().complete(local(url, 0.4), [], [], '', {'local': {'max_retries': 0}})
    assert reply_.text == 'Hello' and len(requests) == 2 and requests[0] == requests[1]


async def test_json_reply_path_never_replays():
    requests, hold = [], asyncio.Event()

    async def partial_json(request):
        requests.append(await request.json())
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        await response.prepare(request)
        await response.write(b'{"choices": [')
        await hold.wait()  # The server ignored "stream" and may still be generating.
        return response
    async with server([('POST', '/{path:.*}', partial_json)]) as url:
        try:
            with pytest.raises(ProviderTimeoutError, match='no automatic retry') as caught:
                await ProviderClient().complete(local(url, 0.4), [], [], '', {'local': {'max_retries': 3}})
        finally:
            hold.set()
    assert caught.value.streamed is False and len(requests) == 1


async def test_copilot_bridge_is_not_streamed_scaled_or_replayed(monkeypatch):
    monkeypatch.setattr(providers, 'LOCAL_PREFILL_TOKENS_PER_TIMEOUT', 1)  # Would allow minutes if applied.
    requests, release = [], asyncio.Event()

    async def silent(request):
        requests.append(await request.json())
        await release.wait()
        return web.json_response({})
    async with server([('POST', '/{path:.*}', silent)]) as url:
        profile = local(url, 0.4, id='copilot-agent', _copilot_agent=True)
        started = asyncio.get_running_loop().time()
        try:
            with pytest.raises(ProviderTimeoutError, match='no automatic retry') as caught:
                await ProviderClient().complete(profile, LONG_PROMPT, [], '', {'local': {'max_retries': 3}})
        finally:
            release.set()
        assert asyncio.get_running_loop().time() - started < 3
    assert caught.value.streamed is False and len(requests) == 1 and requests[0]['stream'] is False


async def test_stream_size_limit_still_applies(monkeypatch):
    monkeypatch.setattr(providers, 'MAX_RESPONSE_BYTES', 64)
    async with server([('POST', '/{path:.*}', chat(lambda n: (0, 0, 0), []))]) as url:
        with pytest.raises(providers.ProviderError, match='size limit'):
            await ProviderClient().complete(local(url, 5), [], [], '', {})


# --- context window probe -------------------------------------------------

def counted(routes):
    hits = []
    def wrap(method, path, body):
        async def handler(request):
            hits.append((method, request.path, await request.json() if method == 'POST' else None))
            if callable(body):
                return await body(request)
            return web.json_response(body)
        return method, path, handler
    return [wrap(*route) for route in routes], hits


async def test_llamacpp_props_is_parsed_and_cached():
    routes, hits = counted([('GET', '/props', {'default_generation_settings': {'n_ctx': 8192}, 'total_slots': 1})])
    async with server(routes) as url:
        assert await probe_context_window(url + '/v1', 'm') == 8192
        assert await probe_context_window(url + '/v1/', 'm') == 8192
    assert len(hits) == 1


async def test_llamacpp_top_level_n_ctx():
    routes, _ = counted([('GET', '/props', {'n_ctx': 4096})])
    async with server(routes) as url:
        assert await probe_context_window(url, 'm') == 4096


@pytest.mark.parametrize('parameters, expected', [('stop "<|im_end|>"\nnum_ctx 16384\n', 16384),
                                                  ('stop "<|im_end|>"', 131072), (None, 131072)])
async def test_ollama_show_prefers_num_ctx_then_context_length(parameters, expected):
    show = {'model_info': {'general.architecture': 'llama', 'llama.context_length': 131072,
                           'llama.embedding_length': 4096}, 'license': 'text'}
    if parameters is not None:
        show['parameters'] = parameters
    routes, hits = counted([('GET', '/api/version', {'version': '0.6.0'}), ('POST', '/api/show', show)])
    async with server(routes) as url:
        assert await probe_context_window(url + '/v1', 'qwen3:8b') == expected
    assert hits[-1] == ('POST', '/api/show', {'model': 'qwen3:8b'})


async def test_unknown_server_is_never_posted_to():
    routes, hits = counted([('POST', '/{path:.*}', {'choices': []})])
    async with server(routes) as url:
        assert await probe_context_window(url + '/v1', 'm') is None
    assert hits == []


@pytest.mark.parametrize('base_url', ['https://api.openai.com/v1', 'http://8.8.8.8:1234/v1',
                                      'http://user:pw@127.0.0.1:1/v1', 'not a url', None])
async def test_non_local_or_invalid_hosts_are_not_contacted(monkeypatch, base_url):
    def forbidden(*args, **kwargs):
        raise AssertionError('no network for a non-local host')
    monkeypatch.setattr(local_probe.aiohttp, 'ClientSession', forbidden)
    assert await probe_context_window(base_url, 'm') is None


async def test_errors_and_oversized_responses_return_none(monkeypatch):
    async def broken(request):
        return web.Response(status=200, text='{not json', content_type='application/json')
    big = {'default_generation_settings': {'n_ctx': 8192}, 'padding': 'x' * (70 * 1024)}

    async def chunked_big(request):
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        await response.prepare(request)  # No Content-Length: the read itself is bounded.
        await response.write(json.dumps(big).encode())
        await response.write_eof()
        return response

    async def failing(request):
        return web.json_response({'error': 'x'}, status=500)

    async def redirect(request):
        raise web.HTTPFound('/elsewhere')
    for routes in ([('GET', '/props', broken)], [('GET', '/props', big)], [('GET', '/props', chunked_big)],
                   [('GET', '/props', failing)], [('GET', '/props', redirect), ('GET', '/elsewhere', {'n_ctx': 8192})],
                   [('GET', '/props', {'default_generation_settings': {'n_ctx': 'large'}})],
                   [('GET', '/api/version', {'version': '0.6'}), ('POST', '/api/show', failing)]):
        local_probe.clear_cache()
        routes, _ = counted(routes)
        async with server(routes) as url:
            assert await probe_context_window(url, 'm') is None
    assert await probe_context_window('http://127.0.0.1:9/v1', 'm') is None  # Nothing listens.


async def test_slow_server_is_bounded_and_failure_is_briefly_cached(monkeypatch):
    async def slow(request):
        await asyncio.sleep(2)
        return web.json_response({'n_ctx': 8192})
    routes, hits = counted([('GET', '/props', slow)])
    async with server(routes) as url:
        started = asyncio.get_running_loop().time()
        assert await probe_context_window(url, 'm', timeout=0.3) is None
        assert asyncio.get_running_loop().time() - started < 1.5
        assert await probe_context_window(url, 'm', timeout=0.3) is None
        assert len(hits) == 1  # Negative result cached for NEGATIVE_CACHE_SECONDS.
        monkeypatch.setattr(local_probe, 'NEGATIVE_CACHE_SECONDS', 0)
        await probe_context_window(url, 'm', timeout=0.3)
        assert len(hits) == 2


async def test_profile_helper_skips_bridge_configured_and_unusable_windows(monkeypatch):
    calls = []

    async def probe(base_url, model, **kwargs):
        calls.append((base_url, model))
        return 6000
    monkeypatch.setattr(local_probe, 'probe_context_window', probe)
    limits = {'max_output_tokens': 4096, 'context_reserve_tokens': 1024}
    assert await local_context_window({'kind': 'local', 'model': 'm'}, limits) == 6000
    assert calls == [('http://127.0.0.1:1234/v1', 'm')]
    assert await local_context_window({'kind': 'local', 'model': 'm'}, {**limits, 'max_output_tokens': 8192}) is None
    for profile in ({'kind': 'openai', 'model': 'm'}, {'kind': 'local', 'model': 'm', 'context_window_tokens': 9000},
                    {'kind': 'local', 'model': 'm', 'id': 'copilot-agent', '_copilot_agent': True}):
        assert await local_context_window(profile, limits) is None
    assert len(calls) == 2


class ProfileCapture:
    def __init__(self):
        self.profiles = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        self.profiles.append(copy.deepcopy(profile))
        return reply('Done')


async def test_engine_applies_probed_window_to_the_dispatch_copy_only(tmp_path):
    seen = []

    async def probed(profile, limits):
        seen.append(profile.get('context_window_tokens'))
        return 50000
    client = ProfileCapture()
    client.local_context_window = probed
    engine, _ = configured(tmp_path, client)
    engine.kick = lambda agent: None
    try:
        run, agent = await start(engine, delegation_level=0)
        await engine._agent_loop(agent)
        assert seen and seen[0] in (0, None)
        assert client.profiles and client.profiles[0]['context_window_tokens'] == 50000
        configured_profile = next(p for p in run['_config']['providers'] if p['id'] == agent.profile_id)
        assert not configured_profile.get('context_window_tokens')
        assert not any(p.get('context_window_tokens') for p in engine.settings.value['providers'])
    finally:
        await engine.close()


async def test_injected_client_without_probe_never_triggers_direct_http(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('direct probe must not run for an injected client')
    monkeypatch.setattr('workbench.local_probe.probe_context_window', forbidden)
    client = ProfileCapture()
    engine, _ = configured(tmp_path, client)
    engine.kick = lambda agent: None
    try:
        run, agent = await start(engine, delegation_level=0)
        await engine._agent_loop(agent)
        assert client.profiles and not client.profiles[0].get('context_window_tokens')
    finally:
        await engine.close()
