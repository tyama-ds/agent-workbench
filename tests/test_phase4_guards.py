"""Phase 4 (after hermes-agent): classified provider errors, empty replies,
cut-off tool arguments, repeated calls, budget notices and the PM wrap-up."""
import json

import pytest
from aiohttp import web

import workbench.engine as engine_module
from workbench.engine import EMPTY_REPLY_NUDGE, WRAP_UP_NOTICE
from workbench.providers import (ProviderClient, ProviderContextOverflowError, ProviderError,
                                 ProviderOutputLimitError, _native_call, classify_error_body)
from test_context_compaction import seeded
from test_engine import ScriptClient, configured, reply, settled, start
from test_providers import fake_server


@pytest.mark.parametrize('status,body,kind', [
    (429, {'error': {'code': 'insufficient_quota', 'message': 'You exceeded your current quota'}}, 'quota'),
    (400, {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'prompt is too long: 210000 tokens'}}, 'context_overflow'),
    (400, {'error': {'code': 'context_length_exceeded'}}, 'context_overflow'),
    (500, {'error': 'the request exceeds the available context size (n_ctx)'}, 'context_overflow'),
    (429, {'error': {'code': 'rate_limit_exceeded'}}, ''),
    (400, {'error': {'message': 'bad schema'}}, ''),
])
def test_error_bodies_are_classified_by_code_and_fixed_phrases(status, body, kind):
    assert classify_error_body(status, json.dumps(body).encode()) == kind


@pytest.mark.asyncio
async def test_quota_exhaustion_stops_at_once_without_exposing_the_body():
    calls = []

    async def handler(request):
        calls.append(1)
        return web.json_response({'error': {'code': 'insufficient_quota', 'message': 'SECRET-BODY-DETAIL'}}, status=429)
    async with fake_server(handler) as url:
        with pytest.raises(ProviderError) as caught:
            await ProviderClient().complete(dict(kind='openai', base_url=url, model='m', api_key='k'), [], [], '', {})
    assert len(calls) == 1 and not caught.value.retryable
    assert 'quota' in str(caught.value) and 'SECRET-BODY-DETAIL' not in str(caught.value)


@pytest.mark.asyncio
async def test_context_overflow_is_typed_and_auth_errors_carry_a_hint():
    async def overflow(request):
        return web.json_response({'error': {'code': 'context_length_exceeded'}}, status=400)

    async def unauthorized(request):
        return web.json_response({'error': {'message': 'invalid key'}}, status=401)
    async with fake_server(overflow) as url:
        with pytest.raises(ProviderContextOverflowError):
            await ProviderClient().complete(dict(kind='openai', base_url=url, model='m', api_key='k'), [], [], '', {})
    async with fake_server(unauthorized) as url:
        with pytest.raises(ProviderError, match='check the API key'):
            await ProviderClient().complete(dict(kind='openai', base_url=url, model='m', api_key='k'), [], [], '', {})


def test_unterminated_tool_arguments_are_an_output_limit_not_bad_json():
    with pytest.raises(ProviderOutputLimitError):
        _native_call('c1', 'write_text', '{"path": "a.txt", "text": "cut', set())
    malformed = _native_call('c2', 'write_text', '{"path": oops}', set())
    assert 'error' in malformed


@pytest.mark.asyncio
async def test_provider_context_overflow_shortens_context_once_and_resends(tmp_path):
    attempts = []

    async def overflow_then_answer(profile, messages):
        attempts.append(len(messages))
        if len(attempts) == 1:
            raise ProviderContextOverflowError('Provider returned HTTP 400; the request exceeds the model context')
        return reply('answered after shortening')
    client = ScriptClient([overflow_then_answer, overflow_then_answer])
    engine, run, agent = await seeded(tmp_path, client, context=200000)
    try:
        engine.kick = engine_module.Engine.kick.__get__(engine, engine_module.Engine)
        await engine.human_message(agent.id, 'Continue please')
        await settled(engine)
        assert agent.status == 'done', agent.last_error
        assert len(attempts) == 2 and attempts[1] < attempts[0]
        assert agent.fallback_compactions == 1
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_empty_reply_is_nudged_once(tmp_path):
    client = ScriptClient([reply(''), reply('Here is the result.')])
    engine, _ = configured(tmp_path, client)
    try:
        run, agent = await start(engine)
        await settled(engine)
        assert agent.status == 'done' and len(client.calls) == 2
        assert client.calls[1][-1]['content'] == EMPTY_REPLY_NUDGE
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_identical_repeated_calls_get_a_notice_then_stop_the_turn(tmp_path):
    engine, work = configured(tmp_path, None)
    (work / 'same.txt').write_text('unchanged', encoding='utf-8')
    same = ('read_text', {'path': str(work / 'same.txt')})
    engine.client = ScriptClient([reply(calls=[same]) for _ in range(6)])
    try:
        run, agent = await start(engine)
        await settled(engine)
        results = [json.loads(row['content']) for row in agent.conversation if row['role'] == 'tool']
        assert len(results) == 5
        assert 'repeat_notice' not in results[1] and 'repeat_notice' in results[2]
        assert agent.status == 'error' and '5回続いた' in agent.last_error
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_budget_notice_is_sent_once_after_80_percent(tmp_path):
    engine, _ = configured(tmp_path, None)
    engine.settings.value['limits']['max_tool_calls'] = 5
    engine.client = ScriptClient([reply(calls=[('list_team', {})]) for _ in range(4)] + [reply('done')])
    try:
        run, agent = await start(engine)
        await settled(engine)
        notices = [json.loads(row['content']).get('budget_notice') for row in agent.conversation if row['role'] == 'tool']
        assert sum(1 for notice in notices if notice) == 1 and '80%' in next(n for n in notices if n)
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_last_model_call_is_reserved_for_the_pm_final_report(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([reply('Final report from verified results.')]))
    engine.kick = lambda agent: None
    engine.settings.value['limits']['max_model_calls'] = 20
    try:
        run, pm = await start(engine)
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'w', 'task': 'Work', 'profile_id': 'local'})
        worker = engine.agents[spawned['agent_id']]
        run['model_calls'] = 19
        await engine._agent_loop(worker)
        assert worker.status == 'error' and worker.stop_reason == 'model_limit'
        pm.pending.append(('Integrate and report.', True))
        await engine._agent_loop(pm)
        assert any(row.get('content') == WRAP_UP_NOTICE for row in pm.conversation)
        assert run['model_calls'] == 20
    finally:
        await engine.close()
