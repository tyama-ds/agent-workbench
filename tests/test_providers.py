import asyncio
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from workbench.providers import ProviderClient, ProviderError, split_thinking, local_host_kind
from workbench.resources import ResourceGate

TOOLS = [{"name": "read_file", "description": "Read one allowed file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}]


@asynccontextmanager
async def fake_server(handler):
    app = web.Application()
    app.router.add_post('/{path:.*}', handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    try:
        yield f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/v1'
    finally:
        await runner.cleanup()


def assistant(reply):
    return {"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls, "provider_raw": reply.raw}


@pytest.mark.asyncio
async def test_responses_preserves_all_output_encrypted_reasoning_and_tool_roundtrip():
    requests = []
    native = [{"type": "reasoning", "id": "rs1", "encrypted_content": "encrypted-test-only",
               "summary": [{"type": "summary_text", "text": "Checking file"}]},
              {"type": "function_call", "id": "fc1", "call_id": "call1", "name": "read_file", "arguments": '{"path":"a.txt"}'}]
    async def handler(request):
        body = await request.json()
        requests.append(body)
        assert request.path == '/v1/responses'
        assert request.headers['Authorization'] == 'Bearer fake-key'
        if len(requests) == 1:
            return web.json_response({"status": "completed", "output": native, "usage": {"input_tokens": 2}})
        return web.json_response({"status": "completed", "output": [{"type": "message", "role": "assistant",
            "phase": "final_answer", "content": [{"type": "output_text", "text": "Done"}]}]})
    async with fake_server(handler) as url:
        profile = dict(kind='openai', base_url=url, model='test-model', api_key='fake-key')
        client = ProviderClient()
        messages = [{"role": "user", "content": "Read a.txt"}]
        first = await client.complete(profile, messages, TOOLS, 'Visible policy', {})
        assert first.thinking == 'Checking file' and first.tool_calls[0]['arguments'] == {'path': 'a.txt'}
        messages += [assistant(first), {"role": "tool", "tool_call_id": "call1", "content": '{"text":"hello"}'}]
        second = await client.complete(profile, messages, TOOLS, 'Visible policy', {})
    assert second.text == 'Done' and first.usage['input_tokens'] == 2
    assert requests[0]['store'] is False and requests[1]['store'] is False
    assert requests[1]['input'][1:3] == native
    assert requests[1]['input'][-1] == {"type": "function_call_output", "call_id": "call1", "output": '{"text":"hello"}'}
    assert 'previous_response_id' not in requests[1]


@pytest.mark.asyncio
async def test_anthropic_preserves_signatures_redacted_thinking_and_parallel_results():
    requests = []
    blocks = [{"type": "thinking", "thinking": "Inspecting", "signature": "signed-test-only"},
              {"type": "redacted_thinking", "data": "encrypted-test-only"},
              {"type": "tool_use", "id": "a", "name": "read_file", "input": {"path": "a"}},
              {"type": "tool_use", "id": "b", "name": "read_file", "input": {"path": "b"}}]
    async def handler(request):
        assert request.headers['x-api-key'] == 'fake-anthropic-key'
        assert request.headers['anthropic-version'] == '2023-06-01'
        requests.append(await request.json())
        return web.json_response({"content": blocks if len(requests) == 1 else [{"type": "text", "text": "Finished"}],
                                  "stop_reason": "tool_use" if len(requests) == 1 else "end_turn"})
    async with fake_server(handler) as url:
        profile = dict(kind='anthropic', base_url=url, model='test-model', api_key='fake-anthropic-key')
        client = ProviderClient()
        messages = [{"role": "user", "content": "Read two files"}]
        first = await client.complete(profile, messages, TOOLS, 'policy', {})
        messages += [assistant(first), {"role": "tool", "tool_call_id": "a", "content": "A"},
                     {"role": "tool", "tool_call_id": "b", "content": "B"}]
        second = await client.complete(profile, messages, TOOLS, 'policy', {})
    assert first.thinking == 'Inspecting' and second.text == 'Finished'
    assert requests[1]['messages'][1]['content'] == blocks
    assert requests[1]['messages'][2] == {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'a', 'content': 'A'},
        {'type': 'tool_result', 'tool_use_id': 'b', 'content': 'B'}]}


@pytest.mark.asyncio
async def test_local_qwen_thinking_preserved_replay_and_no_environment_or_profile_proxy(monkeypatch):
    requests = []
    proxy_calls = []
    async def proxy_handler(request):
        proxy_calls.append(True)
        return web.Response(status=500)
    native = {"role": "assistant", "content": '<think>Check input</think>\nUse file tool', 'tool_calls': [
        {'id': 'local1', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"x"}'}}]}
    async def handler(request):
        requests.append(await request.json())
        return web.json_response({'choices': [{'message': native, 'finish_reason': 'tool_calls'}]})
    async with fake_server(proxy_handler) as proxy, fake_server(handler) as url:
        monkeypatch.setenv('HTTP_PROXY', proxy)
        monkeypatch.setenv('HTTPS_PROXY', proxy)
        monkeypatch.setenv('ALL_PROXY', proxy)
        monkeypatch.setenv('NO_PROXY', '')
        client = ProviderClient()
        profile = dict(kind='local', base_url=url, model='qwen-test', proxy_url=proxy, enable_thinking=True)
        first = await client.complete(profile, [{'role': 'user', 'content': 'task'}], TOOLS, 'policy', {})
        await client.complete(profile, [assistant(first), {'role': 'tool', 'tool_call_id': 'local1', 'content': 'ok'}], TOOLS, 'policy', {})
    assert not proxy_calls and len(requests) == 2
    assert first.thinking == 'Check input' and first.text == 'Use file tool'
    assert requests[1]['messages'][1] == native
    assert requests[0]['chat_template_kwargs'] == {'enable_thinking': True}


@pytest.mark.asyncio
async def test_redirects_never_forward_credentials_and_errors_do_not_echo_body():
    targets = []
    async def target(request):
        targets.append(True)
        return web.json_response({})
    async with fake_server(target) as other:
        async def redirect(request):
            return web.Response(status=307, headers={'Location': other}, text='fake-secret must never appear')
        async with fake_server(redirect) as url:
            with pytest.raises(ProviderError) as caught:
                await ProviderClient().complete(dict(kind='openai', base_url=url, model='test', api_key='fake-secret'), [], [], '', {})
    assert not targets and caught.value.status == 307
    assert 'fake-secret' not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', ['not json', '[1,2]', '{"x":NaN}', '{"x":1,"x":2}', '```json\n{}\n```'])
async def test_malformed_tool_arguments_are_never_interpreted(arguments):
    async def handler(request):
        return web.json_response({'choices': [{'message': {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'one', 'function': {'name': 'read_file', 'arguments': arguments}}]}, 'finish_reason': 'tool_calls'}]})
    async with fake_server(handler) as url:
        with pytest.raises(ProviderError, match='malformed tool arguments'):
            await ProviderClient().complete(dict(kind='local', base_url=url, model='test'), [], TOOLS, '', {})


@pytest.mark.asyncio
async def test_local_retry_bound_and_external_bypass_gpu_guard():
    requests = []
    async def no_gpu():
        pytest.fail('External API must not poll GPU')
    async def handler(request):
        requests.append(True)
        if len(requests) <= 2:
            return web.Response(status=503)
        return web.json_response({'output': [], 'status': 'completed'})
    async with fake_server(handler) as url:
        client = ProviderClient(ResourceGate(no_gpu))
        reply = await client.complete(dict(kind='openai', base_url=url, model='test', api_key='fake',
                                          max_retries=2, retry_backoff_seconds=0), [], [], '',
                                      {'local': {'gpu_guard_enabled': True}})
    assert len(requests) == 3 and reply.text == ''


@pytest.mark.asyncio
async def test_local_retry_limit_exhausted_and_unknown_tool_refused():
    calls = []
    async def handler(request):
        calls.append(True)
        return web.Response(status=429, text='sensitive upstream detail')
    async with fake_server(handler) as url:
        with pytest.raises(ProviderError) as caught:
            await ProviderClient().complete(dict(kind='local', base_url=url, model='test'), [], [], '',
                                            {'local': {'max_retries': 1, 'retry_backoff_seconds': 0}})
    assert len(calls) == 2 and caught.value.status == 429
    assert 'sensitive' not in str(caught.value)
    with pytest.raises(ProviderError, match='unknown tool'):
        ProviderClient()._parse('anthropic', 'test', {'content': [
            {'type': 'tool_use', 'id': 'one', 'name': 'execute_shell', 'input': {}}]}, {'read_file'})


@pytest.mark.asyncio
async def test_provider_mismatch_and_nonloopback_local_rejected_before_network():
    with pytest.raises(ProviderError, match='different provider'):
        await ProviderClient().complete(dict(kind='anthropic', model='test', api_key='fake'), [
            {'role': 'assistant', 'content': '', 'provider_raw': {'provider': 'openai', 'output': []}}], [], '', {})
    with pytest.raises(ProviderError, match='loopback'):
        await ProviderClient().complete(dict(kind='local', model='test', base_url='https://example.invalid/v1'), [], [], '', {})


@pytest.mark.asyncio
async def test_provider_response_limit_and_invalid_json_have_safe_errors(monkeypatch):
    import workbench.providers as providers
    monkeypatch.setattr(providers, 'MAX_RESPONSE_BYTES', 50)
    async def large(request):
        return web.Response(text='x' * 51)
    async with fake_server(large) as url:
        with pytest.raises(ProviderError, match='size limit'):
            await ProviderClient().complete(dict(kind='local', base_url=url, model='test'), [], [], '', {})
    async def invalid(request):
        return web.Response(text='secret invalid content')
    async with fake_server(invalid) as url:
        with pytest.raises(ProviderError, match='invalid JSON') as caught:
            await ProviderClient().complete(dict(kind='local', base_url=url, model='test'), [], [], '', {})
        assert 'secret' not in str(caught.value)


@pytest.mark.asyncio
async def test_timeout_is_not_retried_and_output_limit_is_global_cap():
    requests = []
    entered, release = asyncio.Event(), asyncio.Event()
    async def handler(request):
        body = await request.json()
        requests.append(body)
        entered.set()
        await release.wait()
        return web.json_response({'choices': []})
    async with fake_server(handler) as url:
        # A 20-ms total timeout could expire before a loaded Windows runner
        # dispatched anything. Observe real receipt, then hold the response until
        # the client's actual total timeout; never race two short sleeps.
        pending = asyncio.create_task(ProviderClient().complete(
            dict(kind='local', base_url=url, model='test', max_output_tokens=9999,
                 request_timeout_seconds=5), [], [], '',
            {'max_output_tokens': 100, 'local': {'max_retries': 3}}))
        try:
            await asyncio.wait_for(entered.wait(), 4)
            with pytest.raises(ProviderError, match='timed out'):
                await asyncio.wait_for(pending, 8)
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    assert len(requests) == 1 and requests[0]['max_tokens'] == 100


def test_thinking_unclosed_or_quoted_and_prose_never_creates_tools():
    assert split_thinking('<think>still working') == ('', 'still working')
    assert split_thinking('Example <think>literal</think>') == ('Example <think>literal</think>', '')
    reply = ProviderClient()._parse('local', 'test', {'choices': [{'message': {
        'content': 'Use read_file({"path":"secret"})', 'role': 'assistant'}}]}, {'read_file'})
    assert reply.tool_calls == []


@pytest.mark.parametrize('host,expected', [
    ('localhost', 'loopback'), ('127.0.0.2', 'loopback'), ('::1', 'loopback'),
    ('192.168.1.2', 'lan'), ('10.1.2.3', 'lan'), ('172.16.0.1', 'lan'), ('fd00::1', 'lan'),
    ('172.32.0.1', None), ('169.254.169.254', None), ('192.0.2.1', None),
    ('fe80::1', None), ('fd00::1%eth0', None), ('0.0.0.0', None), ('server.local', None)])
def test_local_endpoint_classification(host, expected):
    assert local_host_kind(host) == expected


@pytest.mark.asyncio
async def test_private_lan_local_has_no_proxy_and_cannot_use_this_pc_gpu_guard(monkeypatch):
    calls = []
    client = ProviderClient()
    async def post(endpoint, payload, headers, timeout, proxy):
        calls.append((endpoint, proxy))
        return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'ok'}}]}
    monkeypatch.setattr(client, '_post', post)
    profile = dict(kind='local', base_url='http://192.168.10.2:8080/v1', model='test', proxy_url='http://proxy.invalid:8888')
    with pytest.raises(ProviderError, match='cannot monitor'):
        await client.complete(profile, [], [], '', {'local': {'gpu_guard_enabled': True}})
    assert not calls
    reply = await client.complete(profile, [], [], '', {'local': {'gpu_guard_enabled': False}})
    assert reply.text == 'ok' and calls == [('http://192.168.10.2:8080/v1/chat/completions', None)]
    assert client.resource_gate.snapshot()['last_admission']['gpu_guard'] == 'remote_not_monitored'


@pytest.mark.asyncio
async def test_local_request_timeout_is_capped_by_both_profile_and_global(monkeypatch):
    observed = []
    client = ProviderClient()
    async def post(endpoint, payload, headers, timeout, proxy):
        observed.append(timeout)
        return {'choices': [{'message': {'role': 'assistant', 'content': ''}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr(client, '_post', post)
    profile = dict(kind='local', model='test', request_timeout_seconds=50)
    await client.complete(profile, [], [], '', {'local': {'request_timeout_seconds': 20}})
    profile['request_timeout_seconds'] = 10
    await client.complete(profile, [], [], '', {'local': {'request_timeout_seconds': 20}})
    assert observed == [20, 10]


@pytest.mark.parametrize('kind,data', [
    ('openai', {'status': 'incomplete', 'output': []}),
    ('anthropic', {'stop_reason': 'max_tokens', 'content': []}),
    ('local', {'choices': [{'finish_reason': 'length', 'message': {'content': ''}}]})])
def test_incomplete_responses_cannot_execute_partial_tools(kind, data):
    with pytest.raises(ProviderError):
        ProviderClient()._parse(kind, 'test', data, {'read_file'})
