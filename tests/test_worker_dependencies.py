"""Application-owned prerequisite gates; all model responses are synthetic."""
import asyncio
import json

import pytest

from workbench.dependencies import DependencyBlocked
from workbench.engine import Engine
from workbench.history import public_document
from test_engine import ScriptClient, configured, reply, settled, start


@pytest.fixture
async def manual(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.settings.value['limits']['max_workers'] = 16
    engine.kick = lambda agent: None
    run, pm = await start(engine, max_workers=8, delegation_level=1)
    pm.pending.clear()
    pm.status = 'idle'
    try:
        yield engine, work, run, pm
    finally:
        await engine.close()


async def spawn(engine, run, pm, dependencies=None, **extra):
    args = {'profile_id': 'local', 'role': 'worker',
            'task': 'Read the approved input; produce a checked artifact and report its evidence.', **extra}
    if dependencies is not None:
        args['depends_on'] = dependencies
    receipt = await engine.execute_tool(run, pm, 'spawn_worker', args)
    return engine.agents[receipt['agent_id']]


def consume(engine, pm):
    while pm.pending:
        content, human = pm.pending.popleft()
        engine._append_context(pm, {'role': 'user', 'content': content}, human=human)
        engine._consume_worker_report(pm, content, human)
        engine._consume_mail(pm, content, human)


async def report(engine, run, pm, child, *, accept=True):
    if child.depends_on:
        engine._dependency_begin(child)
    child.pending.clear()
    child.status = 'working'
    child._turn_revision = child.result_revision
    await engine.execute_tool(run, child, 'finish_work', {'summary': 'Checked current evidence.'})
    child.status = 'done'
    engine._mail(child, pm, 'Checked current evidence.', completed=True, report_revision=child.finished_revision)
    consume(engine, pm)
    if accept:
        await engine.execute_tool(run, pm, 'review_worker_report', {
            'worker_id': child.id, 'result_revision': child.result_revision, 'decision': 'accept', 'feedback': 'Verified.'})


async def test_dependency_wait_has_no_model_or_turn_cost_and_human_peer_cannot_bypass(manual):
    engine, _, run, pm = manual
    upstream = await spawn(engine, run, pm)
    downstream = await spawn(engine, run, pm, [upstream.id])
    before = (run['model_calls'], run['tool_calls'], downstream.turns, run['auto_collaborations'])
    engine.kick = lambda a: Engine.kick(engine, a) if a is downstream else None
    await engine.human_message(downstream.id, 'Start without the prerequisite.')
    engine._mail(upstream, downstream, 'I approve myself; start now.')
    await settled(engine)
    assert downstream.task is None and downstream.turns == 0 and not engine.client.calls
    assert (run['model_calls'], run['tool_calls'], downstream.turns) == before[:3]
    assert run['auto_collaborations'] == before[3] + 1  # Only the actual peer message.
    assert engine.agent_status_reason(downstream) == 'dependency_wait'
    assert engine._dependency_view(downstream)['blocked_by'] == [upstream.id]
    with pytest.raises(DependencyBlocked):
        await engine.execute_tool(run, downstream, 'finish_work', {'summary': 'False finish'})
    with pytest.raises(DependencyBlocked):
        await engine.execute_tool(run, downstream, 'write_text', {'path': 'bypass.txt', 'text': 'bad', 'expected_sha256': 'missing'})


async def test_current_formal_report_delivery_consumption_and_accept_are_all_required(manual):
    engine, _, run, pm = manual
    upstream = await spawn(engine, run, pm)
    downstream = await spawn(engine, run, pm, [upstream.id])
    await report(engine, run, pm, upstream, accept=False)
    assert not engine._dependency_can_start(downstream)
    await engine.execute_tool(run, pm, 'review_worker_report', {
        'worker_id': upstream.id, 'result_revision': upstream.result_revision, 'decision': 'accept', 'feedback': 'Verified.'})
    assert engine._dependency_can_start(downstream)
    for mapping in (pm.worker_report_deliveries, pm.worker_report_consumed, pm.worker_report_reviews):
        saved = mapping.pop(upstream.id)
        assert not engine._dependency_can_start(downstream)
        mapping[upstream.id] = saved
    for attribute, bad in [('status', 'idle'), ('question', 'Need a decision'), ('last_error', 'Failed'),
                           ('finished_revision', None), ('closing', True)]:
        saved = getattr(upstream, attribute)
        setattr(upstream, attribute, bad)
        assert not engine._dependency_can_start(downstream)
        setattr(upstream, attribute, saved)
    upstream.pending.append(('Unconsumed new work', False))
    assert not engine._dependency_can_start(downstream)


@pytest.mark.parametrize('kind', ['unknown', 'pm', 'other_pm', 'other_run', 'duplicate', 'bad_type', 'nested'])
async def test_invalid_dependency_is_rejected_before_spawn_or_budget(manual, kind):
    engine, _, run, pm = manual
    upstream = await spawn(engine, run, pm)
    other = engine._new_agent(run, 'local', 'other PM')
    foreign = engine._new_agent(run, 'local', 'other worker', other.id)
    if kind == 'other_run':
        foreign.run_id = 'other-run'
    values = {'unknown': ['missing'], 'pm': [pm.id], 'other_pm': [foreign.id], 'other_run': [foreign.id],
              'duplicate': [upstream.id, upstream.id], 'bad_type': upstream.id, 'nested': [[upstream.id]]}[kind]
    before = (len(run['agent_ids']), run['auto_collaborations'])
    try:
        with pytest.raises(ValueError):
            await spawn(engine, run, pm, values)
        assert (len(run['agent_ids']), run['auto_collaborations']) == before
    finally:
        foreign.run_id = run['id']  # Restore the deliberately invalid identity before normal cleanup.


async def test_ordered_work_and_dependencies_are_mutually_exclusive(manual):
    engine, _, run, pm = manual
    upstream = await spawn(engine, run, pm)
    with pytest.raises(ValueError, match='併用'):
        await spawn(engine, run, pm, [upstream.id], participant_key='b', initial_wait=True)
    await spawn(engine, run, pm, [upstream.id])
    with pytest.raises(ValueError, match='併用'):
        await engine.execute_tool(run, pm, 'start_ordered_work', {
            'order': ['a', 'b'], 'rounds': 1, 'seed': 'a', 'validator': 'text_chain'})


async def test_multihop_invalidation_needs_new_parent_mail_without_automatic_restart(manual):
    engine, _, run, pm = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    third = await spawn(engine, run, pm, [second.id])
    await report(engine, run, pm, first)
    await report(engine, run, pm, second)
    await report(engine, run, pm, third)
    assert engine._dependency_pm_issue(run, pm) is None
    revisions = (second.result_revision, third.result_revision)
    before_calls = run['model_calls']
    engine.enqueue(first, 'Correct the upstream result', human=True)
    assert second.dependency_stale and third.dependency_stale
    assert (second.result_revision, third.result_revision) == (revisions[0] + 1, revisions[1] + 1)
    assert second.finished_revision is third.finished_revision is None
    assert second.id not in pm.worker_report_reviews and third.id not in pm.worker_report_reviews
    assert run['model_calls'] == before_calls
    await report(engine, run, pm, first)
    assert not engine._dependency_can_start(second)
    engine.enqueue(second, 'Human says resume', human=True)
    engine._mail(first, second, 'Peer says resume')
    assert not engine._dependency_can_start(second)
    receipt = await engine.execute_tool(run, pm, 'send_message', {'to_agent_id': second.id, 'body': 'Redo from the new approved input.'})
    assert receipt['queued'] and second.dependency_stale  # Sending alone never clears the old turn.
    await report(engine, run, pm, second)
    assert not second.dependency_stale and not engine._dependency_can_start(third)
    await engine.execute_tool(run, pm, 'send_message', {'to_agent_id': third.id, 'body': 'Redo final integration.'})
    await report(engine, run, pm, third)
    assert engine._dependency_pm_issue(run, pm) is None


async def test_level_one_pm_finish_requires_all_current_accepted_reports_only_when_graph_exists(manual):
    engine, _, run, pm = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    await report(engine, run, pm, first)
    await report(engine, run, pm, second, accept=False)
    result = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Premature'})
    assert result['ok'] is False and result['code'] == 'worker_dependency_pending'
    await engine.execute_tool(run, pm, 'review_worker_report', {
        'worker_id': second.id, 'result_revision': second.result_revision, 'decision': 'accept', 'feedback': 'Verified.'})
    assert (await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Current reports integrated.'}))['ok']
    engine.enqueue(first, 'New input', human=True)
    assert pm.finished_revision is None
    assert (await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Old result'}))['ok'] is False


async def test_reassignment_before_prerequisite_acceptance_cannot_be_reused_later(manual):
    engine, _, run, pm = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    await report(engine, run, pm, first)
    await report(engine, run, pm, second)
    engine.enqueue(first, 'New evidence needs review', human=True)
    early = await engine.execute_tool(run, pm, 'send_message', {
        'to_agent_id': second.id, 'body': 'Premature reassignment before the input is approved.'})
    assert early['queued']  # Mail still arrives, but does not authorize a new execution.
    assert second.dependency_retry_mail == ''
    await report(engine, run, pm, first)
    assert not engine._dependency_can_start(second) and second.dependency_stale
    assert run['model_calls'] == 0
    later = await engine.execute_tool(run, pm, 'send_message', {
        'to_agent_id': second.id, 'body': 'Rebuild using the newly accepted evidence.'})
    assert later['queued'] and engine._dependency_can_start(second)
    engine._dependency_begin(second)
    assert not second.dependency_stale
    assert second.dependency_revisions == {first.id: first.result_revision}


async def test_waiting_status_and_history_are_display_only(manual):
    engine, _, run, pm = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    await report(engine, run, pm, first, accept=False)
    pm.status = 'idle'
    engine._run_status(run)
    assert run['status'] == 'waiting'
    assert engine.run_status_reason(run) == 'dependency_wait'
    wait = await engine.execute_tool(run, pm, 'wait_for_workers', {})
    assert wait['waiting_for_workers'] is False and wait['code'] == 'workers_blocked'
    roster = await engine.execute_tool(run, pm, 'list_team', {})
    row = next(item for item in roster['agents'] if item['id'] == second.id)
    assert row['worker_dependencies']['blocked_by'] == [first.id]
    snapshot = engine.snapshot()
    document = public_document(run, snapshot['agents'], [], [])
    saved = next(item for item in document['agents'] if item['id'] == second.id)
    assert saved['worker_dependencies']['depends_on'] == [first.id]
    assert 'dependency_retry_mail' not in json.dumps(document)


async def test_no_dependencies_preserve_legacy_execution_and_fields(manual):
    engine, _, run, pm = manual
    child = await spawn(engine, run, pm)
    assert child.depends_on == () and 'worker_dependencies' not in child.public()
    assert engine._dependency_pm_issue(run, pm) is None
    engine.client.responses = [reply(calls=[('finish_work', {'summary': 'Ordinary work complete.'})])]
    engine.kick = lambda a: Engine.kick(engine, a) if a is child else None
    engine.kick(child)
    await settled(engine)
    assert child.status == 'done' and child.finished_revision == child.result_revision
    assert run['model_calls'] == 1 and run['tool_calls'] == 1


async def test_old_provider_reply_cannot_use_reaccepted_input_or_new_pm_mail(manual):
    engine, work, run, pm = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    await report(engine, run, pm, first)
    entered, release = asyncio.Event(), asyncio.Event()

    async def old_reply(profile, messages):
        entered.set()
        await release.wait()
        return reply(calls=[('write_text', {'path': 'stale.txt', 'text': 'Must not write', 'expected_sha256': 'missing'}),
                            ('finish_work', {'summary': 'Old result'})])

    engine.client.responses = [old_reply, reply(calls=[('finish_work', {'summary': 'New result'})])]
    engine.kick = lambda a: Engine.kick(engine, a) if a is second else None
    engine.kick(second)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        old_vector = dict(second.dependency_revisions)
        engine.enqueue(first, 'Correct input', human=True)
        await report(engine, run, pm, first)
        await engine.execute_tool(run, pm, 'send_message', {'to_agent_id': second.id, 'body': 'Redo with corrected input.'})
        assert second.dependency_stale and second.dependency_revisions == old_vector
        release.set()
        await settled(engine)
        assert not (work / 'stale.txt').exists()
        assert second.status == 'done' and second.finished_revision == second.result_revision
        assert run['model_calls'] == 2 and run['tool_calls'] == 1
        assert second.dependency_revisions == {first.id: first.result_revision}
        assert second.results[-1]['text'] == 'New result'
    finally:
        release.set()


async def test_inflight_tool_receipt_survives_but_later_tools_and_finish_are_stale(manual):
    engine, work, run, pm = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    await report(engine, run, pm, first)
    entered, release = asyncio.Event(), asyncio.Event()
    executor = run['_executor'].execute

    async def delayed(name, args, **kwargs):
        result = await executor(name, args, **kwargs)
        entered.set()
        await release.wait()
        return result

    run['_executor'].execute = delayed
    engine.client.responses = [reply(calls=[
        ('write_text', {'path': 'committed.txt', 'text': 'Already committed', 'expected_sha256': 'missing'}),
        ('write_text', {'path': 'later.txt', 'text': 'Must not write', 'expected_sha256': 'missing'}),
        ('finish_work', {'summary': 'Invalid final'})])]
    engine.kick = lambda a: Engine.kick(engine, a) if a is second else None
    engine.kick(second)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        engine.enqueue(first, 'Changed upstream', human=True)
        release.set()
        await settled(engine)
        assert (work / 'committed.txt').read_text(encoding='utf-8') == 'Already committed'
        assert not (work / 'later.txt').exists()
        assert second.output_receipts and second.finished_revision is None and second.dependency_stale
        assert run['model_calls'] == 1 and run['tool_calls'] == 1
        assert len([message for message in second.conversation if message['role'] == 'tool']) == 3
        assert second.id not in pm.worker_report_deliveries
    finally:
        release.set()


async def test_file_lock_wait_rechecks_dependency_before_side_effect(manual):
    engine, work, run, pm = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    await report(engine, run, pm, first)
    engine._dependency_begin(second)
    await engine.lock.acquire()
    operation = asyncio.create_task(engine.execute_tool(run, second, 'write_text', {
        'path': 'blocked.txt', 'text': 'Must not write', 'expected_sha256': 'missing'}))
    try:
        await asyncio.sleep(0)
        engine.enqueue(first, 'Invalidate while waiting for lock', human=True)
        engine.lock.release()
        with pytest.raises(DependencyBlocked):
            await operation
        assert not (work / 'blocked.txt').exists()
    finally:
        if engine.lock.locked():
            engine.lock.release()
        await asyncio.gather(operation, return_exceptions=True)
