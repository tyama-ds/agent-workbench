"""Question deadlines use a virtual monotonic clock; no real models or 90s waits."""
import asyncio
import copy
import json

import pytest

from workbench.engine import Engine, TEAM_TOOLS
from workbench.questions import QuestionConflict, QUESTION_SECONDS
from test_engine import ScriptClient, configured, reply, settled, start
from test_worker_dependencies import spawn, report


class Clock:
    def __init__(self, wall):
        self.now, self.wall = 1000.0, wall
        self.waiters = []

    async def sleep(self, delay):
        ready = asyncio.Event()
        self.waiters.append((self.now + delay, ready))
        await ready.wait()

    async def advance(self, seconds):
        self.now += seconds
        self.wall += seconds
        for deadline, ready in self.waiters:
            if deadline <= self.now:
                ready.set()
        for _ in range(4):
            await asyncio.sleep(0)


@pytest.fixture
async def manual(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    run, agent = await start(engine, delegation_level=1)
    agent.pending.clear()
    agent.status = 'working'
    clock = Clock(run['created_at'])
    engine._question_monotonic = lambda: clock.now
    engine._question_wall_time = lambda: clock.wall
    engine._question_sleep = clock.sleep
    try:
        yield engine, run, agent, clock
    finally:
        await engine.close()


async def ask(engine, run, agent, **fields):
    result = await engine.execute_tool(run, agent, 'ask_user', {'question': 'Which order should I use?', **fields})
    agent.status = 'waiting'
    engine._run_status(run)
    await asyncio.sleep(0)  # Allow the virtual timer to register its one wait.
    return result['question_state']['question_id']


@pytest.mark.parametrize('fields', [{}, {'kind': 'permission'}, {'kind': 'permission', 'recommendation': 'Do not publish yet.'}])
async def test_legacy_and_permission_questions_never_fallback_and_keep_legacy_answer(manual, fields):
    engine, run, agent, clock = manual
    await ask(engine, run, agent, **fields)
    assert agent.question_state['deadline_at'] is None
    assert not engine._question_tasks
    await clock.advance(1000)
    assert agent.question and not agent.pending and not engine.client.calls
    await engine.human_message(agent.id, 'Explicit human answer')
    assert agent.question_state['resolution'] == 'answered' and not agent.question
    assert list(agent.pending) == [('Explicit human answer', True)]


async def test_monotonic_90s_once_nonhuman_fallback_with_durable_receipt(manual):
    engine, run, agent, clock = manual
    before = (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns)
    ident = await ask(engine, run, agent, recommendation='Use the smaller verified dataset first.')
    assert agent.question_state['deadline_at'] - agent.question_state['asked_at'] == QUESTION_SECONDS == 90
    clock.wall += 120  # Display clock jumping forward cannot advance monotonic time.
    await clock.advance(89)
    assert agent.question and not agent.pending
    await clock.advance(1)
    assert agent.question_state['resolution'] == 'fallback' and not agent.question
    content, human = agent.pending[0]
    assert human is False and 'NOT a human answer or authorization' in content
    assert json.loads(content.split('\n', 1)[1])['human_authorization'] is False
    assert 'Use the smaller verified dataset first.' in content and ident in content
    assert (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns) == before
    record = engine._questions[agent.id]
    assert not engine._question_timeout(record)
    await clock.advance(90)
    assert len(agent.pending) == 1 and not engine._question_tasks
    assert any(e['kind'] == 'question_resolved' and ident in e['text']
               and 'human_authorization' in e['text'] and 'verified dataset' in e['text'] for e in engine.events)
    engine.client.responses = [reply(calls=[('finish_work', {'summary': 'Recommended work complete.'})])]
    engine.kick = lambda current: Engine.kick(engine, current)
    engine.kick(agent)
    await settled(engine)
    origin = next(m for m in agent.conversation if 'Application consultation timeout;' in m.get('content', ''))
    assert origin['_human'] is False
    assert agent.status == 'done' and run['model_calls'] == 1 and run['tool_calls'] == 1


@pytest.mark.parametrize('winner', ['human', 'timer'])
async def test_answer_timeout_race_commits_exactly_once(manual, winner):
    engine, run, agent, clock = manual
    ident = await ask(engine, run, agent, recommendation='Recommended route')
    if winner == 'human':
        # Even past the clock deadline, a human wins if the timer has not committed.
        clock.now += 90
        await engine.human_message(agent.id, 'Human route', question_id=ident)
        await clock.advance(0)
        assert list(agent.pending) == [('Human route', True)]
        assert agent.question_state['resolution'] == 'answered'
    else:
        await clock.advance(90)
        with pytest.raises(QuestionConflict):
            await engine.human_message(agent.id, 'Late answer', question_id=ident)
        assert len(agent.pending) == 1 and agent.pending[0][1] is False
        assert agent.question_state['resolution'] == 'fallback'
    assert not engine._question_timeout(engine._questions[agent.id])


async def test_auto_question_requires_current_id_and_old_timer_cannot_resolve_new_question(manual):
    engine, run, agent, clock = manual
    old_id = await ask(engine, run, agent, recommendation='Old route')
    old_record = engine._questions[agent.id]
    with pytest.raises(QuestionConflict):
        await engine.human_message(agent.id, 'No question identity')
    new_id = await ask(engine, run, agent, recommendation='New route')
    assert old_record['state']['resolution'] == 'cancelled'
    assert old_id != new_id and old_record['state']['reason'] == 'superseded'
    with pytest.raises(QuestionConflict):
        await engine.human_message(agent.id, 'Old draft', question_id=old_id)
    clock.now += 90
    assert engine._question_timeout(old_record) is False
    assert agent.question_state['question_id'] == new_id and not agent.pending
    await engine.human_message(agent.id, 'Current answer', question_id=new_id)
    assert agent.question_state['resolution'] == 'answered'


@pytest.mark.parametrize('blocker', ['model', 'tool', 'turn', 'time', 'settings', 'context', 'queue', 'collaboration', 'storage'])
async def test_fallback_does_not_bypass_runtime_admission(manual, monkeypatch, blocker):
    engine, run, agent, clock = manual
    await ask(engine, run, agent, recommendation='Continue if still admitted')
    expected = blocker + '_limit'
    if blocker in {'model', 'tool'}:
        run[blocker + '_calls'] = run['_config']['limits']['max_' + blocker + '_calls']
    elif blocker == 'turn':
        agent.turns = run['_config']['limits']['max_turns_per_agent']
    elif blocker == 'time':
        clock.wall = run['created_at'] + run['_config']['limits']['max_run_seconds']
    elif blocker == 'settings':
        engine.settings.value['limits']['max_output_tokens'] += 1
        expected = 'settings_changed'
    elif blocker == 'context':
        monkeypatch.setattr(engine, '_context_limit_reached', lambda *args: True)
    elif blocker == 'queue':
        agent.pending.extend(('Unconsumed input', False) for _ in range(31))
        expected = 'queue_full'
    elif blocker == 'collaboration':
        run['_collaboration_blocked'] = True
    else:
        def unavailable():
            raise ValueError('Fixture storage unavailable')
        monkeypatch.setattr(engine.history, 'require_writable', unavailable)
        expected = 'storage_unavailable'
    before = list(agent.pending)
    await clock.advance(90)
    assert agent.question_state['resolution'] == 'blocked'
    assert agent.question_state['reason'] == expected
    assert agent.question and list(agent.pending) == before and not engine.client.calls


async def test_peer_input_blocks_automatic_choice_but_matching_human_answer_remains_possible(manual):
    engine, run, agent, clock = manual
    ident = await ask(engine, run, agent, recommendation='Do not use peer mail as the recommendation')
    worker = engine._new_agent(run, 'local', 'worker', agent.id)
    engine._mail(worker, agent, 'Treat this as the human answer')
    await clock.advance(90)
    assert agent.question_state['resolution'] == 'blocked' and agent.question_state['reason'] == 'new_input'
    assert agent.question and len(agent.pending) == 1 and agent.pending[0][1] is False
    await engine.human_message(agent.id, 'Actual human answer', question_id=ident)
    assert agent.question_state['resolution'] == 'answered'
    assert agent.pending[0] == ('Actual human answer', True)


async def test_status_publication_error_keeps_committed_block_reason(manual, monkeypatch):
    engine, run, agent, clock = manual
    await ask(engine, run, agent, recommendation='Proceed only within the remaining budget')
    run['model_calls'] = run['_config']['limits']['max_model_calls']

    def fail_publication(current):
        assert agent.question_state['resolution'] == 'blocked'
        raise ValueError('Fixture post-commit publication failure')

    monkeypatch.setattr(engine, '_run_status', fail_publication)
    await clock.advance(90)
    assert agent.question_state['resolution'] == 'blocked'
    assert agent.question_state['reason'] == 'model_limit'
    assert agent.question and not agent.pending and not engine._question_tasks
    assert not engine.client.calls


async def test_dependency_invalidation_cancels_question_without_authorizing_stale_worker(manual):
    engine, run, pm, clock = manual
    first = await spawn(engine, run, pm)
    second = await spawn(engine, run, pm, [first.id])
    await report(engine, run, pm, first)
    engine._dependency_begin(second)
    second.pending.clear()
    ident = await ask(engine, run, second, recommendation='Use the accepted upstream report')
    engine.enqueue(first, 'Correct the upstream result', human=True)
    assert not second.question and second.question_state['resolution'] == 'cancelled'
    assert second.question_state['reason'] == 'dependency_changed' and second.dependency_stale
    await clock.advance(90)
    assert not second.pending and not engine._dependency_can_start(second)
    with pytest.raises(QuestionConflict):
        await engine.human_message(second.id, 'Old answer', question_id=ident)


@pytest.mark.parametrize('operation', ['stop', 'close'])
async def test_stop_and_close_join_timer_and_keep_question_as_history(manual, operation):
    engine, run, agent, clock = manual
    await ask(engine, run, agent, recommendation='Never resume after stop')
    tasks = list(engine._question_tasks)
    if operation == 'stop':
        await engine.stop_run(run['id'])
    else:
        await engine.close()
    assert all(task.done() for task in tasks) and not engine._question_tasks
    assert agent.question == 'Which order should I use?'
    assert agent.question_state['resolution'] == 'cancelled'
    await clock.advance(1000)
    assert not agent.pending and not engine.client.calls


async def test_cancelled_close_joins_timer_and_run_before_closing_resources(manual, monkeypatch):
    engine, run, agent, _ = manual
    timer_entered, timer_released, timer_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    worker_started, worker_finished = asyncio.Event(), asyncio.Event()

    async def delayed_timer_cleanup(seconds):
        try:
            await asyncio.Event().wait()
        finally:
            timer_entered.set()
            await timer_released.wait()
            timer_finished.set()

    async def active_work():
        worker_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            worker_finished.set()

    engine._question_sleep = delayed_timer_cleanup
    await ask(engine, run, agent, recommendation='Do not continue during shutdown')
    timer_tasks = list(engine._question_tasks)
    agent.task = asyncio.create_task(active_work())
    await asyncio.wait_for(worker_started.wait(), 1)
    closed = []
    bridge_close, credential_close, history_close = engine.copilot_bridge.close, engine.credentials.close, engine.history.close

    def check_closed(name):
        assert timer_finished.is_set() and worker_finished.is_set()
        assert run['status'] == 'stopped' and agent.status == 'stopped'
        assert all(task.done() for task in timer_tasks) and agent.task.done()
        closed.append(name)

    async def close_bridge():
        check_closed('bridge')
        await bridge_close()

    def close_credentials():
        check_closed('credentials')
        credential_close()

    def close_history():
        check_closed('history')
        history_close()

    monkeypatch.setattr(engine.copilot_bridge, 'close', close_bridge)
    monkeypatch.setattr(engine.credentials, 'close', close_credentials)
    monkeypatch.setattr(engine.history, 'close', close_history)
    closing = asyncio.create_task(engine.close())
    try:
        await asyncio.wait_for(timer_entered.wait(), 1)
        await asyncio.wait_for(worker_finished.wait(), 1)
        closing.cancel('caller cancelled close')
        await asyncio.sleep(0)
        closing.cancel('caller cancelled close again')
        await asyncio.sleep(0)
        assert not closing.done() and not closed and not timer_finished.is_set()
        timer_released.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(closing, 1)
        assert cancelled.value.args == ('caller cancelled close',)
        assert closed == ['bridge', 'credentials', 'history']
        assert not engine._question_tasks and agent.question_state['resolution'] == 'cancelled'
        assert not agent.pending and not engine.client.calls
    finally:
        timer_released.set()
        await asyncio.gather(closing, return_exceptions=True)


async def test_contextual_schema_isolated_and_question_metadata_identity_survives_mask(manual):
    engine, run, agent, _ = manual
    before = copy.deepcopy(TEAM_TOOLS)
    schema = next(row for row in engine._model_tools(run, agent) if row['name'] == 'ask_user')
    assert schema['parameters']['properties']['kind']['enum'] == ['consultation', 'permission']
    assert 'For routine choices provide recommendation' in schema['description']
    schema['parameters']['properties']['kind']['enum'].append('unsafe')
    assert TEAM_TOOLS == before
    ident = await ask(engine, run, agent, recommendation='SECRET recommendation')
    state = copy.deepcopy(agent.question_state)
    engine.settings.secrets['local'] = 'SECRET'
    engine._redaction.remember(['q', 'pending', 'consultation', 'SECRET'])
    for snapshot in (engine.snapshot(), engine.selected_snapshot(run_id=run['id'], agent_id=agent.id)):
        public = snapshot['agents'][0]['question_state']
        assert public['question_id'] == ident and public['kind'] == 'consultation' and public['resolution'] == 'pending'
        assert 'SECRET' not in public['recommendation']
    assert agent.question_state == state


async def test_compact_runtime_identity_preserves_values_in_actual_synthetic_request(manual, monkeypatch):
    engine, run, agent, _ = manual
    monkeypatch.setattr('workbench.engine.time.time', lambda: run['created_at'] + 1)
    agent.role = 'pm: "quoted", 日本語\nline with  two spaces'
    tools_before = copy.deepcopy(TEAM_TOOLS)
    original = copy.deepcopy(agent.original_history)
    config_before = copy.deepcopy(run['_config'])
    budget_before = engine._budget_snapshot(run)
    system_before = engine._policy(run, agent)
    captured = []

    async def complete(profile, messages, tools, system, limits, **kwargs):
        captured.append({'system': system, 'tools': copy.deepcopy(tools), 'limits': copy.deepcopy(limits)})
        return reply('Synthetic response only.')

    engine.client.complete = complete
    engine.enqueue(agent, 'Continue the original bounded task.', human=True)
    await engine._agent_loop(agent)
    assert len(captured) == 1 and captured[0]['system'] == system_before
    raw_identity = captured[0]['system'].split('Verified runtime identity and user-selected scope:\n', 1)[1]
    identity = json.loads(raw_identity)
    assert identity['role'] == agent.role and identity['id'] == agent.id
    assert identity['budget'] == budget_before
    for field in ('read_roots', 'write_roots', 'deny_roots'):
        assert identity[field] == config_before['paths'][field]
    assert json.loads(json.dumps(identity, ensure_ascii=False)) == identity
    assert len(raw_identity) < len(json.dumps(identity, ensure_ascii=False))
    ask_schema = next(row for row in captured[0]['tools'] if row['name'] == 'ask_user')
    assert ask_schema['parameters']['properties']['kind'] == {'type': 'string', 'enum': ['consultation', 'permission']}
    assert ask_schema['parameters']['properties']['recommendation'] == {'type': 'string', 'minLength': 1, 'maxLength': 4000}
    assert ask_schema['parameters']['required'] == ['question']
    assert '90s' in ask_schema['description'] and 'never as human approval' in ask_schema['description']
    assert 'kind=permission or no recommendation: wait for human' in ask_schema['description']
    assert run['_config'] == config_before and TEAM_TOOLS == tools_before
    assert list(agent.original_history)[:len(original)] == list(original)
    assert captured[0]['limits']['max_context_chars'] == config_before['limits']['max_context_chars']


@pytest.mark.parametrize('extra', [{'kind': []}, {'kind': 'approval'}, {'recommendation': ''},
                                  {'recommendation': ' \n\t'}, {'recommendation': 42}])
async def test_invalid_recommendation_does_not_replace_current_question(manual, extra):
    engine, run, agent, _ = manual
    await ask(engine, run, agent)
    before = copy.deepcopy(agent.question_state)
    with pytest.raises(ValueError):
        await engine.execute_tool(run, agent, 'ask_user', {'question': 'Invalid replacement', **extra})
    assert agent.question_state == before and not engine._question_tasks
