"""PM-directed output-limit recovery; every provider response is synthetic.

The HTTP regression exercises the real parser, mail, tool dispatch, Office tools
and formal-report gates. It never calls a real model or a weather service.
"""
import copy
import json
import time

import pytest
from aiohttp import web
from openpyxl import load_workbook

from workbench.engine import Engine
from workbench.history import HistoryError, archived_view, validate
from test_agent_hierarchy import activate, report, spawn
from test_engine import ScriptClient, start
from test_engine_integration import (
    api_server, configured_settings, local_reply, openai_reply, anthropic_reply, eventually,
)


TASK = 'Create weather.xlsx from the supplied Tokyo fixture data, read it back, and report the saved evidence.'
NEXT_TASK = 'Write only the two supplied cells to weather.xlsx, then read A1:B1 and report the actual saved result.'
LIMIT_ERROR = 'Local model output token limit reached; no tools were executed'


def failed(child):
    """Set an already-observed failure for admission-only tests; no inference."""
    child.pending.clear()
    child.status, child.stop_reason, child.last_error = 'error', 'provider_output_limit', LIMIT_ERROR
    child.output_limit_failures += 1


def recovery_args(child, action='split', **extra):
    return {'worker_id': child.id, 'failure_id': child.output_limit_failures,
            'action': action, 'task': NEXT_TASK, **extra}


@pytest.fixture
async def manual(tmp_path):
    settings, work = configured_settings(tmp_path, 'http://127.0.0.1:9/v1')
    settings.value['limits']['max_workers'] = 4
    engine = Engine(settings, ScriptClient([]))
    engine.kick = lambda agent: None
    run, pm = await start(engine, max_workers=4, delegation_level=1,
                          max_delegation_depth=3, worker_profiles=['local', 'anthropic'])
    activate(engine, pm)
    try:
        yield engine, work, run, pm
    finally:
        await engine.close()


@pytest.mark.parametrize('action', ['split', 'handoff'])
async def test_pm_recovers_truncated_local_response_and_accepts_actual_excel(tmp_path, action):
    requests, failures = [], []
    pm_stage, worker_stage = 0, 0
    truncated_limits = []
    worker_id = None
    revision = None
    path, forbidden = str(tmp_path / 'documents' / 'weather.xlsx'), str(tmp_path / 'documents' / 'truncated.xlsx')
    checkpoint = str(tmp_path / 'documents' / 'checkpoint.xlsx')

    async def handler(request):
        nonlocal pm_stage, worker_stage, worker_id, revision
        body = await request.json()
        requests.append((request.path, body))
        try:
            if request.path == '/v1/responses':
                mail = [json.loads(item['content'].split('\n', 1)[1]) for item in body['input']
                        if item.get('role') == 'user' and isinstance(item.get('content'), str)
                        and item['content'].startswith('Peer data;')]
                if pm_stage == 0:
                    pm_stage = 1
                    return openai_reply([('spawn', 'spawn_worker', {'profile_id': 'local',
                        'role': 'Excel writer', 'task': TASK})])
                if pm_stage == 1:
                    blocked = [item for item in mail if item['message_type'] == 'worker_error']
                    if not blocked:
                        return openai_reply([('wait-error', 'wait_for_workers', {})])
                    worker_id = blocked[-1]['sender']
                    pm_stage = 2
                    arguments = {'worker_id': worker_id, 'failure_id': 1, 'action': action, 'task': NEXT_TASK}
                    if action == 'handoff':
                        arguments['profile_id'] = 'anthropic'
                    return openai_reply([('recover', 'recover_worker', arguments)])
                if pm_stage == 2:
                    reports = [item for item in mail if item['message_type'] == 'worker_report']
                    if not reports:
                        return openai_reply([('wait-report', 'wait_for_workers', {})])
                    assert reports[-1]['sender'] == worker_id
                    revision = reports[-1]['result_revision']
                    pm_stage = 3
                    return openai_reply([('pm-read', 'xlsx_read', {'path': path, 'range': 'A1:B1'})])
                if pm_stage == 3:
                    read = next(json.loads(item['output']) for item in body['input']
                                if item.get('type') == 'function_call_output' and item.get('call_id') == 'pm-read')
                    assert [cell['value'] for cell in read['cells']] == ['Tokyo fixture', 20]
                    pm_stage = 4
                    return openai_reply([('review', 'review_worker_report', {'worker_id': worker_id,
                        'result_revision': revision, 'decision': 'accept',
                        'feedback': 'Read the actual workbook; the supplied two fixture values match.'})])
                assert pm_stage == 4
                reviewed = next(json.loads(item['output']) for item in body['input']
                                if item.get('type') == 'function_call_output' and item.get('call_id') == 'review')
                assert reviewed['accepted'] is True
                pm_stage = 5
                return openai_reply([('finish', 'finish_work', {'summary': 'Verified weather.xlsx and accepted the current worker report.'})])

            # Earlier tool success must survive the later output failure. Its
            # native local tool-call history cannot be replayed as Anthropic raw.
            if worker_stage == 2 and len(truncated_limits) == 1:
                # The provider retries a length-limited reply once with a doubled
                # output limit (one engine model call); it is truncated again.
                requests.pop()
                truncated_limits.append(body['max_tokens'])
                truncated = json.loads(local_reply([('truncated-retry', 'finish_work', {'summary': 'UNCONFIRMED'})]).body)
                truncated['choices'][0]['finish_reason'] = 'length'
                return web.json_response(truncated)
            worker_stage += 1
            if worker_stage == 1:
                assert request.path == '/v1/chat/completions'
                return local_reply([('checkpoint-reserve', 'reserve_paths', {'paths': [checkpoint]}),
                    ('checkpoint-save', 'xlsx_write', {'path': checkpoint, 'expected_sha256': 'missing',
                        'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': 'Committed earlier'}]})])
            # This response includes complete-looking calls. None are admissible
            # because the provider reports a truncated response.
            if worker_stage == 2:
                assert request.path == '/v1/chat/completions'
                truncated_limits.append(body['max_tokens'])
                truncated = json.loads(local_reply([
                    ('truncated-write', 'xlsx_write', {'path': forbidden, 'expected_sha256': 'missing',
                        'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': 'UNCONFIRMED'}]}),
                    ('truncated-finish', 'finish_work', {'summary': 'UNCONFIRMED'}),
                ]).body)
                truncated['choices'][0]['finish_reason'] = 'length'
                return web.json_response(truncated)
            wire = anthropic_reply if action == 'handoff' else local_reply
            assert request.path == ('/v1/messages' if action == 'handoff' else '/v1/chat/completions')
            assert 'UNCONFIRMED' not in json.dumps(body)
            if worker_stage == 3:
                assert NEXT_TASK in json.dumps(body)
                return wire([('reserve', 'reserve_paths', {'paths': [path]}),
                    ('save', 'xlsx_write', {'path': path, 'expected_sha256': 'missing', 'cells': [
                        {'sheet': 'Sheet', 'cell': 'A1', 'value': 'Tokyo fixture'},
                        {'sheet': 'Sheet', 'cell': 'B1', 'value': 20}]})])
            if worker_stage == 4:
                return wire([('read', 'xlsx_read', {'path': path, 'range': 'A1:B1'})])
            assert worker_stage == 5
            return wire([('report', 'finish_work', {'summary': 'Created weather.xlsx and read back the two supplied values.'})])
        except Exception as exc:
            failures.append(repr(exc))
            return web.json_response({'error': 'fixture failed'}, status=500)

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        engine = Engine(settings)
        try:
            run, pm = await start(engine, pm_profile='openai', worker_profiles=['local', 'anthropic'],
                                  max_workers=1, delegation_level=2, workers_per_pm=1, task=TASK)
            await eventually(lambda: run['status'] in {'done', 'waiting'} and
                             not any(agent.task and not agent.task.done() for agent in engine.agents.values()),
                             engine, progress_run=run)
            assert not failures
            assert pm_stage == 5 and worker_stage == 5, engine.snapshot()
            assert truncated_limits == [truncated_limits[0], min(2 * truncated_limits[0], 32768)]
            child = engine.agents[worker_id]
            assert run['status'] == pm.status == child.status == 'done'
            assert child.parent_id == pm.id and child.assignment == TASK
            assert child.profile_id == ('anthropic' if action == 'handoff' else 'local')
            assert len(run['agent_ids']) == 2 and child.recovery_attempts == run['worker_recoveries'] == 1
            assert child.output_limit_failures == 1 and child.finished_revision == child.result_revision == revision
            assert pm.worker_report_reviews[child.id] == {'result_revision': revision, 'decision': 'accept'}
            assert run['model_calls'] == len(requests)
            assert not (work / 'truncated.xlsx').exists()
            assert {item['path'] for item in child.output_receipts} == {path, checkpoint}
            prior = load_workbook(work / 'checkpoint.xlsx', read_only=True, data_only=True)
            try:
                assert list(prior.active.values) == [('Committed earlier',)]
            finally:
                prior.close()
            book = load_workbook(work / 'weather.xlsx', read_only=True, data_only=True)
            try:
                assert list(book.active.values) == [('Tokyo fixture', 20)]
            finally:
                book.close()
            assert all('UNCONFIRMED' not in json.dumps(item) for item in child.conversation)
        finally:
            await engine.close()


async def test_caps_survive_model_changes_human_input_and_stale_replay(manual):
    engine, _, run, pm = manual
    child = await spawn(engine, run, pm, task=TASK)
    failed(child)
    activate(engine, pm)
    run['model_calls'], run['tool_calls'], child.turns = 7, 8, 3
    before_created, before_ids = run['created_at'], list(run['agent_ids'])
    original = copy.deepcopy(child.original_history)
    first_args = recovery_args(child)
    collaborations = run['auto_collaborations']
    first = await engine.execute_tool(run, pm, 'recover_worker', first_args)
    assert first['ok'] is True and child.status == 'queued' and len(child.pending) == 1
    assert child.recovery_attempts == run['worker_recoveries'] == 1
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'recover_worker', first_args)
    assert len(child.pending) == 1 and run['auto_collaborations'] == collaborations + 1
    failed(child)
    activate(engine, pm)
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'recover_worker', first_args)
    second = await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child, 'handoff', profile_id='anthropic'))
    assert second['ok'] is True and child.profile_id == 'anthropic'
    failed(child)
    activate(engine, pm)
    third_args = recovery_args(child, 'handoff', profile_id='local')
    exhausted = await engine.execute_tool(run, pm, 'recover_worker', third_args)
    assert exhausted['ok'] is False and exhausted['code'] == 'worker_recovery_limit' and exhausted['requires_human']
    assert child.status == 'error' and not child.pending
    await engine.human_message(child.id, 'Manually inspect the saved evidence; do not retry tools.')
    assert child.recovery_attempts == run['worker_recoveries'] == 2
    failed(child)
    activate(engine, pm)
    assert (await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child)))['code'] == 'worker_recovery_limit'
    assert (run['model_calls'], run['tool_calls'], child.turns) == (7, 8, 3)
    assert run['created_at'] == before_created and run['agent_ids'] == before_ids
    assert child.assignment == TASK and list(child.original_history)[:len(original)] == list(original)
    assert not engine.client.calls


async def test_shared_cap_blocks_another_worker_without_spending_or_restarting(manual):
    engine, _, run, pm = manual
    workers = [await spawn(engine, run, pm, task=TASK) for _ in range(3)]
    for child in workers[:2]:
        for _ in range(2):
            failed(child)
            activate(engine, pm)
            assert (await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child)))['ok']
    child = workers[2]
    failed(child)
    activate(engine, pm)
    before = (run['auto_collaborations'], run['model_calls'], run['tool_calls'])
    rejected = await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child))
    assert rejected['ok'] is False and rejected['code'] == 'worker_recovery_limit' and rejected['requires_human']
    assert run['worker_recoveries'] == 4 and child.recovery_attempts == 0
    assert child.status == 'error' and not child.pending
    assert before == (run['auto_collaborations'], run['model_calls'], run['tool_calls'])


async def test_only_immediate_coordinator_can_recover_a_nested_worker(manual):
    engine, _, run, pm = manual
    coordinator = await spawn(engine, run, pm)
    child = await spawn(engine, run, coordinator, task=TASK)
    failed(child)
    activate(engine, pm)
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child))
    assert child.recovery_attempts == 0 and child.status == 'error'
    activate(engine, coordinator)
    result = await engine.execute_tool(run, coordinator, 'recover_worker', recovery_args(child))
    assert result['ok'] is True and child.recovery_attempts == 1
    assert child.parent_id == coordinator.id and len(run['agent_ids']) == 3


@pytest.mark.parametrize('case', ['unrelated_parent', 'self', 'different_error', 'worker_question', 'pending_human',
    'parent_question', 'stopped', 'settings_changed', 'turn_cap', 'model_cap', 'tool_cap',
    'time_cap', 'collaboration_cap', 'unknown_profile', 'same_profile', 'split_profile', 'ordered'])
async def test_recovery_admission_cannot_relax_authority_or_existing_limits(manual, case):
    engine, _, run, pm = manual
    child = await spawn(engine, run, pm, task=TASK)
    failed(child)
    activate(engine, pm)
    actor, args = pm, recovery_args(child)
    if case == 'unrelated_parent':
        actor = engine._new_agent(run, 'local', 'Other PM')
        actor.status = 'working'
    elif case == 'self':
        actor = child
    elif case == 'different_error':
        child.stop_reason = 'provider_timeout'
    elif case == 'worker_question':
        child.question = 'Permission needed'
    elif case == 'pending_human':
        child.pending.append(('Stop recovery and inspect my correction first.', True))
    elif case == 'parent_question':
        pm.question = 'Permission needed'
    elif case == 'stopped':
        run['status'] = 'stopped'
    elif case == 'settings_changed':
        engine.settings.value['paths']['write_roots'] = []
    elif case == 'turn_cap':
        child.turns = run['_config']['limits']['max_turns_per_agent']
    elif case == 'model_cap':
        run['model_calls'] = run['_config']['limits']['max_model_calls']
    elif case == 'tool_cap':
        run['tool_calls'] = run['_config']['limits']['max_tool_calls']
    elif case == 'time_cap':
        run['created_at'] = time.time() - run['_config']['limits']['max_run_seconds'] - 1
    elif case == 'collaboration_cap':
        run['auto_collaborations'] = run['max_auto_collaborations']
    elif case in {'unknown_profile', 'same_profile', 'split_profile'}:
        args.update(action='split' if case == 'split_profile' else 'handoff',
                    profile_id='missing' if case == 'unknown_profile' else 'local')
    elif case == 'ordered':
        run['_ordered_reference'] = {'test_fixture': True}
    before = (child.profile_id, child.assignment, child.result_revision, child.output_limit_failures,
              run['auto_collaborations'], run['model_calls'], run['tool_calls'])
    pending_before = list(child.pending)
    with pytest.raises(ValueError):
        await engine.execute_tool(run, actor, 'recover_worker', args)
    assert list(child.pending) == pending_before and child.status == 'error' and child.recovery_attempts == 0
    assert run.get('worker_recoveries', 0) == 0
    assert before == (child.profile_id, child.assignment, child.result_revision, child.output_limit_failures,
                      run['auto_collaborations'], run['model_calls'], run['tool_calls'])


async def test_peer_mail_does_not_restart_error_and_recovery_keeps_dependency_gate(manual):
    engine, _, run, pm = manual
    upstream = await spawn(engine, run, pm)
    child = await spawn(engine, run, pm, dependencies=[upstream.id], task=TASK)
    await report(engine, run, upstream)
    activate(engine, child)
    failed(child)
    engine.enqueue(upstream, 'Refresh the prerequisite source.')
    activate(engine, pm)
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child))
    assert child.status == 'error' and child.recovery_attempts == 0
    await report(engine, run, upstream)
    activate(engine, pm)
    before = child.recovery_attempts
    await engine.execute_tool(run, pm, 'send_message', {'to_agent_id': child.id, 'body': NEXT_TASK})
    assert child.status == 'error' and child.recovery_attempts == before
    # Normal PM mail may authorize the new prerequisite revision, but must not
    # itself clear an output-limit failure or spend/refill the recovery budget.
    assert child.dependency_retry_mail
    activate(engine, pm)
    await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child))
    assert child.depends_on == (upstream.id,)
    assert child.recovery_attempts == 1 and engine._dependency_can_start(child)


async def test_handoff_retains_native_originals_and_saved_receipts_without_cross_provider_replay(manual):
    engine, _, run, pm = manual
    child = await spawn(engine, run, pm, task=TASK)
    engine._append_context(child, {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': 'prior-read', 'name': 'list_directory', 'arguments': {'path': '.'}}],
        'provider_raw': {'provider': 'local', 'model': 'qwen-fixture', 'message': {
            'role': 'assistant', 'content': '', 'reasoning_content': 'PRIVATE-PROVIDER-REPLAY',
            'tool_calls': [{'id': 'prior-read', 'type': 'function', 'function': {
                'name': 'list_directory', 'arguments': '{"path":"."}'}}]}}})
    engine._append_context(child, {'role': 'tool', 'tool_call_id': 'prior-read',
                                  'name': 'list_directory', 'content': '{"files":[]}'} )
    child.output_receipts.append({'path': 'prior.xlsx', 'sha256': 'a' * 64})
    original, receipts = copy.deepcopy(child.original_history), copy.deepcopy(child.output_receipts)
    failed(child)
    activate(engine, pm)
    await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child, 'handoff', profile_id='anthropic'))
    assert child.original_history == original and child.output_receipts == receipts
    assert child.parent_id == pm.id and child.profile_id == 'anthropic' and child.assignment == TASK
    assert 'PRIVATE-PROVIDER-REPLAY' not in json.dumps(child.conversation)
    assert all('provider_raw' not in item for item in child.conversation)
    assert any(item.get('tool_call_id') == 'prior-read' for item in child.conversation)


async def test_accepted_recovery_with_notification_failure_is_not_retried(manual, monkeypatch):
    engine, _, run, pm = manual
    child = await spawn(engine, run, pm, task=TASK)
    failed(child)
    activate(engine, pm)
    args = recovery_args(child)

    def broken_notice(*args, **kwargs):
        raise OSError('Synthetic notification failure after delivery')

    monkeypatch.setattr(engine, 'log', broken_notice)
    result = await engine.execute_tool(run, pm, 'recover_worker', args)
    assert result['ok'] is True and result['queued'] is True and result.get('warning')
    assert child.recovery_attempts == run['worker_recoveries'] == 1
    assert len(child.pending) == 1
    collaborations = run['auto_collaborations']
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'recover_worker', args)
    assert run['auto_collaborations'] == collaborations and len(child.pending) == 1


async def test_recovery_history_remains_redacted_read_only_and_count_consistent(manual):
    engine, _, run, pm = manual
    child = await spawn(engine, run, pm, task=TASK)
    failed(child)
    child.last_error += ' test-openai-secret'
    activate(engine, pm)
    await engine.execute_tool(run, pm, 'recover_worker', recovery_args(child))
    engine._persist_run(run['id'])
    stored, at = engine.history.read(run['id'])
    assert 'test-openai-secret' not in json.dumps(stored)
    archived = archived_view(stored, at)
    saved_child = next(row for row in archived['agents'] if row['id'] == child.id)
    assert saved_child['read_only'] and not saved_child['message_eligibility']['allowed']
    assert saved_child['recovery']['attempts'] == stored['run']['worker_recoveries'] == 1
    assert saved_child['recovery']['failure_id'] == 1
    assert '[redacted]' in saved_child['recovery']['history'][0]['error']
    bad = copy.deepcopy(stored)
    bad['run']['worker_recoveries'] = 0
    with pytest.raises(HistoryError):
        validate(bad)
