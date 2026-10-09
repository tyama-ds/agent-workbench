"""Non-streaming completion evidence; every server here is a loopback fixture."""
import copy
import json

import pytest
from aiohttp import web

from workbench.engine import Engine
from workbench.providers import ProviderClient
from test_engine import settled, start
from test_engine_integration import (
    api_server, configured_settings, local_reply, openai_reply, anthropic_reply,
)


WIRE_REPLY = {'local': local_reply, 'openai': openai_reply, 'anthropic': anthropic_reply}
PRIVATE = 'PRIVATE-RESPONSE-EVIDENCE'
UNCONFIRMED = 'Unconfirmed response must not become a report.'
CALLS = [('write', 'write_text', {'path': 'must-not-exist.txt', 'text': PRIVATE,
                               'expected_sha256': 'missing'}),
         ('finish', 'finish_work', {'summary': UNCONFIRMED})]


def rejected_body(kind, evidence, mode):
    body = json.loads(WIRE_REPLY[kind](CALLS if mode == 'tools' else [], text=UNCONFIRMED).body)
    target = body['choices'][0] if kind == 'local' else body
    field = {'local': 'finish_reason', 'openai': 'status', 'anthropic': 'stop_reason'}[kind]
    if evidence == 'missing':
        target.pop(field)
    elif evidence == 'null':
        target[field] = None
    elif evidence == 'malformed':
        target[field] = {PRIVATE: []}
    elif evidence.startswith(('error:', 'details:', 'item:', 'reasoning:')):
        source, status = evidence.split(':')
        if status == 'missing':
            body.pop('status')
        elif status == 'null':
            body['status'] = None
        if source == 'error':
            body['error'] = {'code': 'server_error', 'message': PRIVATE}
        elif source == 'details':
            body['incomplete_details'] = {'reason': 'max_output_tokens', 'private': PRIVATE}
        elif source == 'item':
            body['output'][0]['status'] = 'incomplete'
        else:
            body['output'].append({'type': 'reasoning', 'status': 'in_progress',
                                   'summary': [{'type': 'summary_text', 'text': PRIVATE}]})
    elif evidence.startswith('refusal:'):
        value = evidence.split(':')[1]
        target['message']['refusal'] = {'malformed': {PRIVATE: True}, 'false': False,
                                      'zero': 0, 'list': [], 'calls': PRIVATE}[value]
        # Reject a refusal even when only the reason claims there are calls.
        if value == 'calls':
            target['finish_reason'] = 'tool_calls'
    else:
        target[field] = evidence
    return body


REJECTED = [
    *((kind, reason) for kind in ('local', 'anthropic')
      for reason in ('missing', 'null', 'malformed', PRIVATE)),
    *(('local', reason) for reason in ('length', 'content_filter')),
    *(('anthropic', reason) for reason in ('max_tokens', 'model_context_window_exceeded',
                                         'pause_turn', 'refusal')),
    *(('openai', reason) for reason in ('incomplete', 'failed', 'queued', 'in_progress',
                                      'cancelled', 'malformed', PRIVATE)),
    *(('openai', f'{source}:{status}') for source in ('error', 'details', 'item', 'reasoning')
      for status in ('missing', 'null', 'completed')),
    *(('local', 'refusal:' + value) for value in ('malformed', 'false', 'zero', 'list', 'calls')),
]


@pytest.mark.parametrize('kind,evidence', REJECTED)
@pytest.mark.parametrize('mode', ['text', 'tools'])
async def test_unconfirmed_response_cannot_admit_any_report_or_tool(tmp_path, kind, evidence, mode):
    requests = []
    body = rejected_body(kind, evidence, mode)

    async def handler(request):
        requests.append(await request.json())
        return web.json_response(body)

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        settings.value['local'].update(max_retries=2, retry_backoff_seconds=0)
        engine = Engine(settings)
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await settled(engine)
            assert len(requests) == run['model_calls'] == 1
            assert agent.status == 'error' and run['status'] == 'waiting'
            assert run['tool_calls'] == 0 and not list(work.iterdir())
            assert not agent.results and not agent.output_receipts
            assert all(item['role'] == 'user' for item in agent.conversation)
            state = engine.snapshot()
            assert state['agents'][0]['status_reason'] == state['runs'][0]['status_reason'] == 'error'
            assert PRIVATE not in json.dumps(state) and UNCONFIRMED not in json.dumps(state)
            assert engine.message_eligibility(agent)['allowed']
        finally:
            await engine.close()


@pytest.mark.parametrize('kind,evidence', [('local', 'null'), ('anthropic', 'missing'),
                                          ('openai', 'item:missing')])
async def test_rejection_keeps_prior_receipts_and_budgets_until_explicit_continuation(tmp_path, kind, evidence):
    requests = []

    async def handler(request):
        requests.append(await request.json())
        if len(requests) == 1:
            return WIRE_REPLY[kind]([('saved', 'write_text', {
                'path': 'saved.txt', 'text': 'Earlier committed output', 'expected_sha256': 'missing'})])
        if len(requests) == 2:
            return WIRE_REPLY[kind](text='Earlier complete response')
        if len(requests) == 3:
            return web.json_response(rejected_body(kind, evidence, 'tools'))
        assert len(requests) == 4
        return WIRE_REPLY[kind](text='Human-directed response without re-executing a tool')

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        engine = Engine(settings)
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await settled(engine)
            receipts, results = copy.deepcopy(list(agent.output_receipts)), copy.deepcopy(list(agent.results))
            assert agent.status == 'done' and run['model_calls'] == 2 and run['tool_calls'] == 1
            await engine.human_message(agent.id, 'Continue the work')
            await settled(engine)
            assert agent.status == 'error' and run['status'] == 'waiting' and len(requests) == 3
            assert run['model_calls'] == 3 and run['tool_calls'] == 1 and agent.turns == 2
            assert list(agent.output_receipts) == receipts and list(agent.results) == results
            assert (work / 'saved.txt').read_text() == 'Earlier committed output'
            assert not (work / 'must-not-exist.txt').exists()
            assert UNCONFIRMED not in json.dumps(agent.conversation)
            await engine.human_message(agent.id, 'Do not retry tools. Explain the retained outcome.')
            await settled(engine)
            assert agent.status == run['status'] == 'done' and len(requests) == 4
            assert run['model_calls'] == 4 and run['tool_calls'] == 1 and agent.turns == 3
            assert list(agent.output_receipts) == receipts and len(agent.results) == len(results) + 1
            assert UNCONFIRMED not in json.dumps(requests[-1])
        finally:
            await engine.close()


@pytest.mark.parametrize('content', [None, 'Visible context', '<think>Private reasoning</think>'])
async def test_local_refusal_is_visible_redacted_and_replayed_exactly(tmp_path, content):
    requests = []
    refusal = 'Cannot comply with test-openai-secret.'
    native = {'role': 'assistant', 'content': content, 'refusal': refusal}

    async def handler(request):
        requests.append(await request.json())
        if len(requests) == 1:
            return web.json_response({'choices': [{'finish_reason': 'stop', 'message': native}]})
        return local_reply(text='Response to the explicit follow-up')

    async with api_server(handler) as endpoint:
        settings, _ = configured_settings(tmp_path, endpoint)
        engine = Engine(settings)
        try:
            run, agent = await start(engine, max_workers=0)
            await settled(engine)
            assert agent.status == run['status'] == 'done' and len(agent.results) == 1
            result = agent.results[0]
            assert result['source'] == 'assistant_response'
            assert 'Cannot comply with [redacted].' in result['text']
            assert ('Visible context' in result['text']) == (content == 'Visible context')
            assert 'Private reasoning' not in result['text']
            assert 'test-openai-secret' not in json.dumps(engine.snapshot())
            assert run['tool_calls'] == 0 and not agent.output_receipts
            await engine.human_message(agent.id, 'Please explain the limitation')
            await settled(engine)
            assert len(requests) == 2
            assistants = [item for item in requests[1]['messages'] if item['role'] == 'assistant']
            assert assistants == [native]
        finally:
            await engine.close()


@pytest.mark.parametrize('response_status', ['missing', None, 'completed'])
@pytest.mark.parametrize('item_status', ['missing', None, 'completed'])
def test_openai_optional_statuses_and_null_details_remain_compatible(response_status, item_status):
    body = json.loads(openai_reply([('read', 'read_file', {'path': 'a.txt'})], text='Complete').body)
    body.update(error=None, incomplete_details=None)
    if response_status == 'missing':
        body.pop('status')
    else:
        body['status'] = response_status
    if item_status != 'missing':
        for item in body['output']:
            item['status'] = item_status
    reply = ProviderClient()._parse('openai', 'fixture', body, {'read_file'})
    assert reply.text == 'Complete' and reply.tool_calls[0]['arguments'] == {'path': 'a.txt'}
    assert reply.raw['output'] == body['output']


@pytest.mark.parametrize('kind,body', [
    ('local', {'choices': [{'finish_reason': 'stop', 'message': {'content': None, 'refusal': None}}]}),
    ('local', {'choices': [{'finish_reason': 'stop', 'message': {'content': '', 'refusal': ''}}]}),
    ('openai', {'status': 'completed', 'output': []}),
    ('anthropic', {'stop_reason': 'end_turn', 'content': []}),
    ('anthropic', {'stop_reason': 'stop_sequence', 'content': []}),
])
def test_recognized_empty_terminal_responses_remain_supported(kind, body):
    reply = ProviderClient()._parse(kind, 'fixture', body, set())
    assert reply.text == '' and reply.tool_calls == []


@pytest.mark.parametrize('kind', ['local', 'openai'])
async def test_truncated_second_call_arguments_reject_the_whole_batch(tmp_path, kind):
    body = json.loads(WIRE_REPLY[kind](CALLS, text=UNCONFIRMED).body)
    target = body['choices'][0]['message']['tool_calls'][1]['function'] if kind == 'local' else body['output'][1]
    target['arguments'] = '{"summary":"truncated'
    requests = []

    async def handler(request):
        requests.append(await request.json())
        return web.json_response(body)

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        engine = Engine(settings)
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await settled(engine)
            assert agent.status == 'error' and run['status'] == 'waiting' and len(requests) == 1
            assert run['tool_calls'] == 0 and not list(work.iterdir())
            assert not agent.results and not agent.output_receipts
        finally:
            await engine.close()
