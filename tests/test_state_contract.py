"""Real engine projections: no model text or UI fixture may invent state."""
import asyncio
import copy
import json
import time

import pytest

from workbench.engine import CollaborationLimitError
from test_engine import ScriptClient, configured, reply, settled, start


async def test_assignments_are_real_stable_redacted_and_json_safe(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    engine.settings.secrets['local'] = 'synthetic-secret'
    try:
        run, pm = await start(engine, task='Original PM synthetic-secret', max_workers=1)
        result = await engine.execute_tool(run, pm, 'spawn_worker', {
            'role': 'pm', 'profile_id': 'local', 'task': 'Original worker synthetic-secret'})
        worker = engine.agents[result['agent_id']]
        await engine.human_message(pm.id, 'Follow-up, not a replacement brief')
        engine._mail(pm, worker, 'Peer data, not a replacement brief')
        state = engine.snapshot()
        encoded = json.dumps(state)
        assert 'synthetic-secret' not in encoded
        assert [a['assignment'] for a in state['agents']] == ['Original PM [redacted]', 'Original worker [redacted]']
        assert all('task' not in a and 'conversation' not in a and 'pending' not in a for a in state['agents'])
        assert worker.parent_id == pm.id  # Arbitrary worker role must not imply PM identity.
        assert pm.assignment == 'Original PM synthetic-secret'
    finally:
        await engine.close()


async def test_question_error_and_combined_wait_have_distinct_reasons(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([reply(calls=[('ask_user', {'question': 'Which source?'})])]))
    try:
        run, pm = await start(engine)
        await settled(engine)
        state = engine.snapshot()
        assert state['agents'][0]['status_reason'] == state['runs'][0]['status_reason'] == 'human_input'
        assert state['agents'][0]['message_eligibility']['allowed']
        run['max_auto_collaborations'] = 0
        with pytest.raises(CollaborationLimitError):
            engine._check_collaboration(run, pm)
        assert engine.snapshot()['runs'][0]['status_reason'] == 'needs_attention'
        assert engine.message_eligibility(pm)['allowed']
        await engine.stop_run(run['id'])
        state = engine.snapshot()
        assert state['agents'][0]['status_reason'] == state['runs'][0]['status_reason'] == 'stopped'
    finally:
        await engine.close()

    (tmp_path / 'error').mkdir()
    engine, _ = configured(tmp_path / 'error', ScriptClient([]))
    try:
        run, pm = await start(engine)
        await settled(engine)
        assert pm.status == 'error'
        assert engine.snapshot()['runs'][0]['status_reason'] == 'error'
        assert engine.message_eligibility(pm)['allowed']  # Provider errors may be retried.
    finally:
        await engine.close()


@pytest.mark.parametrize('reason', ['stopping', 'stopped', 'settings_changed', 'queue_full', 'turn_limit',
                                   'time_limit', 'model_limit', 'context_limit'])
async def test_admission_hint_matches_rejection_without_state_mutation(tmp_path, reason):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        pm.question = 'Keep this question'
        pm.last_error = 'Keep this error'
        run['status'] = 'waiting'
        if reason in {'stopping', 'stopped'}:
            run['status'] = reason
        elif reason == 'settings_changed':
            engine.settings.value['system_policy'] += '\nChanged'
        elif reason == 'queue_full':
            pm.pending.extend(('Pending', True) for _ in range(31))
        elif reason == 'turn_limit':
            pm.turns = run['_config']['limits']['max_turns_per_agent']
        elif reason == 'time_limit':
            run['created_at'] = time.time() - run['_config']['limits']['max_run_seconds'] - 1
        elif reason == 'model_limit':
            run['model_calls'] = run['_config']['limits']['max_model_calls']
        elif reason == 'context_limit':
            pm.conversation.append({'role': 'user', 'content': 'x' * run['_config']['limits']['max_context_chars']})
        before = copy.deepcopy((list(pm.pending), pm.question, pm.last_error, pm.status, run['status']))
        eligibility = engine.snapshot()['agents'][0]['message_eligibility']
        assert not eligibility['allowed'] and eligibility['reason'] == reason
        with pytest.raises(ValueError) as error:
            await engine.human_message(pm.id, 'Attempted retry')
        assert str(error.value) == eligibility['message']
        assert (list(pm.pending), pm.question, pm.last_error, pm.status, run['status']) == before
    finally:
        await engine.close()


async def test_human_followup_does_not_hide_in_flight_work(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def held(profile, messages):
        entered.set()
        await release.wait()
        return reply('First result')
    client = ScriptClient([held, reply('Follow-up result')])
    engine, _ = configured(tmp_path, client)
    try:
        run, pm = await start(engine)
        await entered.wait()
        assert pm.status == 'working'
        await engine.human_message(pm.id, 'Follow-up')
        assert pm.status == 'working' and len(pm.pending) == 1
        assert engine.snapshot()['agents'][0]['status_reason'] == 'working'
        release.set()
        await settled(engine)
        assert len(client.calls) == 2 and pm.status == 'done'
        assert run['status'] == 'done'
    finally:
        release.set()
        await engine.close()


async def test_tool_budget_can_still_accept_text_only_completion(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([reply('Text-only result')]))
    try:
        engine.kick = lambda agent: None
        run, pm = await start(engine)
        run['tool_calls'] = run['_config']['limits']['max_tool_calls']
        assert engine.message_eligibility(pm)['allowed']
        assert 'ツール' in engine.message_eligibility(pm)['message']
    finally:
        await engine.close()


async def test_idle_projection_follows_actual_children_without_inventing_waits(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=1)
        result = await engine.execute_tool(run, pm, 'spawn_worker', {
            'role': 'review', 'profile_id': 'local', 'task': 'Review'})
        worker = engine.agents[result['agent_id']]
        pm.status = 'idle'
        assert engine.agent_status_reason(pm) == 'teammates'
        worker.status = 'error'
        assert engine.agent_status_reason(pm) == 'teammate_error'
        worker.status = 'done'
        assert engine.agent_status_reason(pm) == 'idle'
    finally:
        await engine.close()
