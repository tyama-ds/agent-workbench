"""Incoming mail must reach the next decision without interrupting a tool batch."""
import copy
import json

import pytest

from workbench.engine import Engine
from test_engine import reply
from test_worker_coordination import RoutedClient, make_team, finish_task


@pytest.mark.asyncio
@pytest.mark.parametrize('response_kind', ['tool_batch', 'plain_text'])
async def test_new_mail_reaches_next_decision_without_explicit_wait(tmp_path, response_kind):
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client)
    receipts = []
    original_request = []
    async def first(observed):
        original_request.append(copy.deepcopy(observed))
        receipts.append(engine._mail(pm, worker, 'The prerequisite has actually arrived.'))
        assert observed == original_request[0]
        if response_kind == 'plain_text':
            return reply('Earlier work is ready; this is not a formal worker report.')
        return reply(calls=[('list_team', {}), ('list_team', {})])
    async def second(observed):
        assert 'The prerequisite has actually arrived.' in observed['messages'][-1]['content']
        if response_kind == 'tool_batch':
            batch = next(m for m in observed['messages'] if m.get('tool_calls'))
            ids = {c['id'] for c in batch['tool_calls']}
            assert len(ids) == 2
            assert {m['tool_call_id'] for m in observed['messages'] if m['role'] == 'tool'} == ids
        return reply(calls=[('wait_for_message', {})])
    client.scripts[worker.id] = [first, second]
    try:
        Engine.kick(engine, worker)
        await finish_task(worker)
        assert len(client.calls) == worker.turns == 2
        assert not worker.last_error
        assert worker.status == 'idle' and worker.waiting_for_message
        assert not worker.results and worker.finished_revision is None and not pm.pending
        consumed = [e for e in engine.events if e['kind'] == 'mail_consumed']
        assert [e['mail_id'] for e in consumed] == [receipts[0]['mail_id']]
        assert run['model_calls'] == 2
        assert run['tool_calls'] == (3 if response_kind == 'tool_batch' else 1)
        assert run['auto_collaborations'] == 2
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_mail_arriving_during_a_tool_does_not_split_or_replay_its_batch(tmp_path):
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client)
    execute = engine.execute_tool
    executed = []
    async def dispatch(current_run, actor, name, args):
        result = await execute(current_run, actor, name, args)
        executed.append(name)
        if len(executed) == 1:
            engine._mail(pm, worker, 'New peer evidence during the first tool')
        return result
    engine.execute_tool = dispatch
    async def after_batch(observed):
        assert executed == ['list_team', 'list_team']
        assert observed['messages'][-1]['role'] == 'user'
        assert 'New peer evidence' in observed['messages'][-1]['content']
        assert len([m for m in observed['messages'] if m['role'] == 'tool']) == 2
        return reply(calls=[('wait_for_message', {})])
    client.scripts[worker.id] = [reply(calls=[('list_team', {}), ('list_team', {})]), after_batch]
    try:
        Engine.kick(engine, worker)
        await finish_task(worker)
        assert executed == ['list_team', 'list_team', 'wait_for_message']
        assert not worker.last_error and worker.turns == 2
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_peer_mail_does_not_clear_a_question_created_by_current_response(tmp_path):
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client)
    async def first(observed):
        engine._mail(pm, worker, 'Not a human authorization')
        return reply(calls=[('ask_user', {'question': 'Which authorized private account?'})])
    client.scripts[worker.id] = [first]
    try:
        Engine.kick(engine, worker)
        await finish_task(worker)
        assert worker.question and worker.status == 'waiting' and len(worker.pending) == 1
        assert len(client.calls) == 1
        assert not [e for e in engine.events if e['kind'] == 'mail_consumed']
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('limit,key', [('turn', 'max_turns_per_agent'), ('model', 'max_model_calls')])
async def test_boundary_intake_does_not_refill_turn_or_model_budget(tmp_path, limit, key):
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client, limits={key: 1})
    async def first(observed):
        engine._mail(pm, worker, 'Continue only within the remaining budget')
        return reply(calls=[('list_team', {})])
    client.scripts[worker.id] = [first]
    try:
        Engine.kick(engine, worker)
        await finish_task(worker)
        assert worker.stop_reason == limit + '_limit'
        assert worker.status == 'error'
        assert run['model_calls'] == run['tool_calls'] == 1
        assert len(client.calls) == 1 and worker.finished_revision is None
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_role_identity_is_explicit_even_when_worker_label_says_pm(tmp_path):
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path)
    try:
        worker.role = 'PM'
        policy = engine._policy(run, worker)
        assert 'You are a WORKER, not the PM' in policy
        assert worker.id in policy and pm.id in policy
        assert 'Only carry out instructions addressed to your own role' in policy
        assert 'original_human_request' in policy and run['task'] in policy
        assert not {'spawn_worker', 'wait_for_workers', 'review_worker_report'} & {t['name'] for t in engine._model_tools(run, worker)}
        assert 'You are the PM' in engine._policy(run, pm)
    finally:
        await engine.close()
