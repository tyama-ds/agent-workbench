"""Streamed (text/event-stream) provider replies; every server is a loopback fixture."""
import asyncio
import json

import pytest
from aiohttp import web

import workbench.providers as providers
from workbench.providers import (ProviderClient, ProviderError, ProviderOutputLimitError,
                                 ProviderTimeoutError)
from test_providers import TOOLS, assistant, fake_server


def sse(*events, done=False):
    """Encode (event name or None, data dict) pairs as SSE frames."""
    frames = []
    for name, data in events:
        head = f'event: {name}\n' if name else ''
        frames.append(f'{head}data: {json.dumps(data)}\n\n'.encode())
    if done:
        frames.append(b'data: [DONE]\n\n')
    return frames


def streaming(frames_for, requests=None, delay=0.0, crlf=False):
    async def handler(request):
        body = await request.json()
        if requests is not None:
            requests.append(body)
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        frames = frames_for(body, len(requests or ()))
        for frame in frames:
            if crlf:
                frame = frame.replace(b'\n', b'\r\n')
            # Split frames mid-line to exercise incremental parsing.
            middle = len(frame) // 2
            for piece in (frame[:middle], frame[middle:]):
                await response.write(piece)
                if delay:
                    await asyncio.sleep(delay)
        await response.write_eof()
        return response
    return handler


def openai_events(response):
    return [('response.created', {'type': 'response.created', 'response': {'status': 'in_progress', 'output': []}}),
            ('response.output_text.delta', {'type': 'response.output_text.delta', 'delta': 'Do'}),
            ('response.completed', {'type': 'response.completed', 'response': response})]


async def test_openai_completed_event_supplies_the_full_response():
    requests = []
    native = [{'type': 'reasoning', 'id': 'rs1', 'encrypted_content': 'encrypted-test-only',
               'summary': [{'type': 'summary_text', 'text': 'Checking'}]},
              {'type': 'function_call', 'id': 'fc1', 'call_id': 'call1', 'name': 'read_file',
               'arguments': '{"path":"a.txt"}', 'status': 'completed'}]
    final = {'status': 'completed', 'output': native, 'usage': {'input_tokens': 3, 'output_tokens': 4}}
    async with fake_server(streaming(lambda body, n: sse(*openai_events(final)), requests)) as url:
        reply = await ProviderClient().complete(dict(kind='openai', base_url=url, model='m', api_key='fake-key'),
                                                [{'role': 'user', 'content': 'Read'}], TOOLS, 'policy', {})
    assert requests[0]['stream'] is True
    assert reply.tool_calls[0]['arguments'] == {'path': 'a.txt'} and reply.thinking == 'Checking'
    assert reply.raw['output'] == native and reply.usage == {'input_tokens': 3, 'output_tokens': 4}


async def test_openai_stream_closed_before_terminal_event_is_retryable():
    requests = []
    frames = lambda body, n: sse(*openai_events({'status': 'completed', 'output': []})[:2])
    async with fake_server(streaming(frames, requests)) as url:
        with pytest.raises(ProviderError, match='closed before completion') as caught:
            await ProviderClient().complete(dict(kind='openai', base_url=url, model='m', api_key='k',
                                                 max_retries=1, retry_backoff_seconds=0), [], [], '', {})
    assert caught.value.retryable and not isinstance(caught.value, ProviderTimeoutError)
    assert len(requests) == 2  # Retried like any transient failure.


def anthropic_frames(blocks_events, stop_reason='tool_use', usage=None):
    events = [('message_start', {'type': 'message_start', 'message': {
        'id': 'msg1', 'type': 'message', 'role': 'assistant', 'model': 'm', 'content': [],
        'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 10, 'output_tokens': 1}}}),
        ('ping', {'type': 'ping'})]
    events += blocks_events
    events += [('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': stop_reason, 'stop_sequence': None},
                                  'usage': usage or {'output_tokens': 42}}),
               ('message_stop', {'type': 'message_stop'})]
    return sse(*events)


def block_events(index, start, deltas):
    events = [('content_block_start', {'type': 'content_block_start', 'index': index, 'content_block': start})]
    events += [('content_block_delta', {'type': 'content_block_delta', 'index': index, 'delta': delta})
               for delta in deltas]
    events.append(('content_block_stop', {'type': 'content_block_stop', 'index': index}))
    return events


async def test_anthropic_stream_rebuilds_exact_non_streamed_blocks_and_replays_them():
    expected = [{'type': 'thinking', 'thinking': 'Inspecting the file', 'signature': 'signed-test-only'},
                {'type': 'redacted_thinking', 'data': 'encrypted-test-only'},
                {'type': 'text', 'text': 'Reading now'},
                {'type': 'tool_use', 'id': 'a', 'name': 'read_file', 'input': {'path': 'a', 'n': [1, 2]}}]
    blocks = (block_events(0, {'type': 'thinking', 'thinking': ''}, [
                  {'type': 'thinking_delta', 'thinking': 'Inspecting '},
                  {'type': 'thinking_delta', 'thinking': 'the file'},
                  {'type': 'signature_delta', 'signature': 'signed-test-only'}])
              + block_events(1, {'type': 'redacted_thinking', 'data': 'encrypted-test-only'}, [])
              + block_events(2, {'type': 'text', 'text': ''}, [
                  {'type': 'text_delta', 'text': 'Reading'}, {'type': 'text_delta', 'text': ' now'}])
              + block_events(3, {'type': 'tool_use', 'id': 'a', 'name': 'read_file', 'input': {}}, [
                  {'type': 'input_json_delta', 'partial_json': ''},
                  {'type': 'input_json_delta', 'partial_json': '{"path": "a", '},
                  {'type': 'input_json_delta', 'partial_json': '"n": [1, 2]}'}]))
    requests = []
    def frames(body, count):
        if count == 1:
            return anthropic_frames(blocks)
        return anthropic_frames(block_events(0, {'type': 'text', 'text': ''},
                                             [{'type': 'text_delta', 'text': 'Finished'}]), 'end_turn')
    async with fake_server(streaming(frames, requests, crlf=True)) as url:
        profile = dict(kind='anthropic', base_url=url, model='m', api_key='fake-key')
        client = ProviderClient()
        messages = [{'role': 'user', 'content': 'Read'}]
        first = await client.complete(profile, messages, TOOLS, 'policy', {})
        messages += [assistant(first), {'role': 'tool', 'tool_call_id': 'a', 'content': 'A'}]
        second = await client.complete(profile, messages, TOOLS, 'policy', {})
    # Exactly what ProviderClient()._parse yields for the non-streamed body.
    non_streamed = ProviderClient()._parse('anthropic', 'm', {
        'content': expected, 'stop_reason': 'tool_use',
        'usage': {'input_tokens': 10, 'output_tokens': 42}}, {'read_file'})
    assert first == non_streamed
    assert first.thinking == 'Inspecting the file' and first.text == 'Reading now'
    assert requests[0]['stream'] is True and requests[1]['messages'][1]['content'] == expected
    assert second.text == 'Finished'


@pytest.mark.parametrize('error_type,retryable', [('overloaded_error', True), ('invalid_request_error', False)])
async def test_anthropic_error_event_is_typed_and_withheld(error_type, retryable):
    requests = []
    frames = lambda body, n: sse(
        ('message_start', {'type': 'message_start', 'message': {'id': 'm', 'role': 'assistant', 'content': [],
                                                                 'stop_reason': None, 'usage': {}}}),
        ('error', {'type': 'error', 'error': {'type': error_type, 'message': 'fake-secret detail'}}))
    async with fake_server(streaming(frames, requests)) as url:
        with pytest.raises(ProviderError) as caught:
            await ProviderClient().complete(dict(kind='anthropic', base_url=url, model='m', api_key='fake-secret',
                                                 max_retries=1, retry_backoff_seconds=0), [], [], '', {})
    assert caught.value.retryable is retryable and len(requests) == (2 if retryable else 1)
    assert 'fake-secret' not in str(caught.value)


def chat_chunk(delta=None, finish=None, usage=None):
    chunk = {'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}
    if usage is not None:
        chunk['usage'] = usage
    return (None, chunk)


async def test_local_stream_merges_reasoning_and_two_split_tool_calls():
    requests = []
    frames = lambda body, n: sse(
        chat_chunk({'role': 'assistant', 'reasoning_content': 'Plan '}),
        chat_chunk({'reasoning_content': 'two reads'}),
        chat_chunk({'content': 'Reading both'}),
        chat_chunk({'tool_calls': [{'index': 0, 'id': 'c1', 'type': 'function',
                                    'function': {'name': 'read_file', 'arguments': '{"pa'}}]}),
        chat_chunk({'tool_calls': [{'index': 1, 'id': 'c2', 'type': 'function',
                                    'function': {'name': 'read_file', 'arguments': ''}}]}),
        chat_chunk({'tool_calls': [{'index': 0, 'function': {'arguments': 'th":"a"}'}},
                                   {'index': 1, 'function': {'arguments': '{"path":"b"}'}}]}),
        chat_chunk(finish='tool_calls'),
        (None, {'choices': [], 'usage': {'prompt_tokens': 5, 'completion_tokens': 9}}), done=True)
    async with fake_server(streaming(frames, requests)) as url:
        reply = await ProviderClient().complete(dict(kind='local', base_url=url, model='m'), [], TOOLS, 'policy', {})
    assert requests[0]['stream'] is True and 'stream_options' not in requests[0]
    assert [call['arguments'] for call in reply.tool_calls] == [{'path': 'a'}, {'path': 'b'}]
    assert [call['id'] for call in reply.tool_calls] == ['c1', 'c2']
    assert reply.thinking == 'Plan two reads' and reply.text == 'Reading both'
    assert reply.usage == {'prompt_tokens': 5, 'completion_tokens': 9}
    assert reply.raw['message'] == {'role': 'assistant', 'content': 'Reading both', 'reasoning_content': 'Plan two reads',
        'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"a"}'}},
                       {'id': 'c2', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"b"}'}}]}


async def test_local_done_ends_the_read_even_if_the_server_keeps_the_stream_open():
    hold = asyncio.Event()
    async def handler(request):
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        for frame in sse(chat_chunk({'role': 'assistant', 'content': 'Hi'}), chat_chunk(finish='stop'), done=True):
            await response.write(frame)
        await hold.wait()  # Never closes on its own; [DONE] must end the read.
        return response
    async with fake_server(handler) as url:
        try:
            reply = await asyncio.wait_for(ProviderClient().complete(
                dict(kind='local', base_url=url, model='m', request_timeout_seconds=30), [], [], '', {}), 5)
        finally:
            hold.set()
    assert reply.text == 'Hi' and reply.raw['message'] == {'role': 'assistant', 'content': 'Hi'}


async def test_local_done_without_finish_reason_is_unconfirmed_and_early_close_is_retryable():
    async with fake_server(streaming(lambda b, n: sse(chat_chunk({'content': 'Hi'}), done=True))) as url:
        with pytest.raises(ProviderError, match='incomplete or unconfirmed') as caught:
            await ProviderClient().complete(dict(kind='local', base_url=url, model='m'), [], [], '', {})
        assert not caught.value.retryable
    async with fake_server(streaming(lambda b, n: sse(chat_chunk({'content': 'partial'})))) as url:
        with pytest.raises(ProviderError, match='closed before completion') as caught:
            await ProviderClient().complete(dict(kind='local', base_url=url, model='m'), [], [], '', {})
    assert caught.value.retryable


async def test_slow_steady_stream_outlives_timeout_but_silence_does_not():
    chunks = [chat_chunk({'content': f'{index} '}) for index in range(6)] + [chat_chunk(finish='stop')]
    async with fake_server(streaming(lambda b, n: sse(*chunks, done=True), delay=0.1)) as url:
        started = asyncio.get_running_loop().time()
        reply = await ProviderClient().complete(
            dict(kind='local', base_url=url, model='m', request_timeout_seconds=0.6), [], [], '', {})
        assert asyncio.get_running_loop().time() - started > 0.6  # Longer than the request timeout.
    assert reply.text == '0 1 2 3 4 5 '
    requests, hold = [], asyncio.Event()
    async def silent(request):
        requests.append(True)
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        await response.write(sse(chat_chunk({'content': 'start'}))[0])
        await hold.wait()  # Silent for longer than the request timeout.
        return response
    async with fake_server(silent) as url:
        try:
            with pytest.raises(ProviderTimeoutError, match='timed out') as caught:
                await ProviderClient().complete(
                    dict(kind='local', base_url=url, model='m', request_timeout_seconds=0.4),
                    [], [], '', {'local': {'max_retries': 3, 'retry_backoff_seconds': 0}})
        finally:
            hold.set()
    assert not caught.value.retryable and len(requests) == 1


async def test_stream_size_limit_is_enforced_on_raw_bytes(monkeypatch):
    monkeypatch.setattr(providers, 'MAX_RESPONSE_BYTES', 4096)
    frames = lambda b, n: [b': keep-alive padding ' + b'x' * 2000 + b'\n'] * 4 + sse(chat_chunk(finish='stop'), done=True)
    async with fake_server(streaming(frames)) as url:
        with pytest.raises(ProviderError, match='size limit'):
            await ProviderClient().complete(dict(kind='local', base_url=url, model='m'), [], [], '', {})


@pytest.mark.parametrize('kind', ['local', 'anthropic', 'openai'])
async def test_output_limit_retries_once_with_doubled_limit(kind):
    requests = []
    field = {'openai': 'max_output_tokens', 'anthropic': 'max_tokens', 'local': 'max_tokens'}[kind]
    def limited():
        if kind == 'local':
            return sse(chat_chunk({'content': 'partial'}, finish='length'), done=True)
        if kind == 'anthropic':
            return anthropic_frames(block_events(0, {'type': 'text', 'text': ''},
                                                 [{'type': 'text_delta', 'text': 'partial'}]), 'max_tokens')
        return sse(('response.incomplete', {'type': 'response.incomplete', 'response': {
            'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}, 'output': []}}))
    def complete():
        if kind == 'local':
            return sse(chat_chunk({'content': 'whole'}, finish='stop'), done=True)
        if kind == 'anthropic':
            return anthropic_frames(block_events(0, {'type': 'text', 'text': ''},
                                                 [{'type': 'text_delta', 'text': 'whole'}]), 'end_turn')
        return sse(*openai_events({'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                                   'content': [{'type': 'output_text', 'text': 'whole'}]}]}))
    profile = dict(kind=kind, model='m', api_key='k')
    async with fake_server(streaming(lambda body, n: limited() if n == 1 else complete(), requests)) as url:
        reply = await ProviderClient().complete({**profile, 'base_url': url}, [], [], '', {'max_output_tokens': 3000})
    assert reply.text == 'whole' and [body[field] for body in requests] == [3000, 6000]
    assert {**requests[1], field: 0} == {**requests[0], field: 0}  # Only the limit changed.

    requests.clear()
    async with fake_server(streaming(lambda body, n: limited(), requests)) as url:
        with pytest.raises(ProviderOutputLimitError):
            await ProviderClient().complete({**profile, 'base_url': url}, [], [], '', {'max_output_tokens': 20000})
    assert [body[field] for body in requests] == [20000, 32768]  # Once, capped.

    requests.clear()
    async with fake_server(streaming(lambda body, n: limited(), requests)) as url:
        with pytest.raises(ProviderOutputLimitError):
            await ProviderClient().complete({**profile, 'base_url': url, 'max_output_tokens': 3000}, [], [], '',
                                            {'max_output_tokens': 3000})
    assert [body[field] for body in requests] == [3000]  # The profile's own cap is never exceeded.


async def test_output_limit_retry_rejected_by_server_keeps_typed_failure():
    requests = []
    async def handler(request):
        requests.append(await request.json())
        if len(requests) == 1:
            return web.json_response({'choices': [{'finish_reason': 'length',
                                                   'message': {'role': 'assistant', 'content': 'x'}}]})
        return web.json_response({'error': 'max_tokens exceeds context'}, status=400)
    async with fake_server(handler) as url:
        with pytest.raises(ProviderOutputLimitError):
            await ProviderClient().complete(dict(kind='local', base_url=url, model='m'), [], [], '',
                                            {'max_output_tokens': 1000})
    assert [body['max_tokens'] for body in requests] == [1000, 2000]


async def test_copilot_bridge_stays_non_streamed_without_output_limit_retry():
    requests = []
    async def handler(request):
        requests.append(await request.json())
        return web.json_response({'choices': [{'finish_reason': 'length',
                                               'message': {'role': 'assistant', 'content': 'x'}}]})
    async with fake_server(handler) as url:
        profile = dict(kind='local', id='copilot-agent', _copilot_agent=True, base_url=url, model='copilot')
        with pytest.raises(ProviderOutputLimitError):
            await ProviderClient().complete(profile, [{'role': 'user', 'content': 'hi'}], [], '', {})
        with pytest.raises(ProviderOutputLimitError):
            await ProviderClient().complete(profile, [{'role': 'user', 'content': 'hi'}], TOOLS, '', {})
    assert len(requests) == 2 and all(body['stream'] is False for body in requests)
