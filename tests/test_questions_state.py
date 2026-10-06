"""Reachable multi-run questions: read-only compact discovery and explicit recovery."""
import copy
from types import SimpleNamespace

import pytest

import workbench.engine as engine_module
from test_session_transitions import session, response


def paused(state):
    runs = {run['id']: run for run in state['runs']}
    return {agent['id'] for agent in state['agents']
            if runs[agent['run_id']]['status'] not in {'stopping', 'stopped'}
            and agent['status'] == 'waiting' and agent['status_reason'] == 'human_input'
            and agent['question'].strip()}


async def snapshot(case, run, agent):
    return await case.api('get', f'/api/state?view=selected&run_id={run["id"]}&agent_id={agent.id}')


async def test_other_running_team_question_is_visible_without_loading_its_history_or_resuming(tmp_path):
    async with session(tmp_path) as case:
        first, pm, initial = await case.start(workers=1)
        await case.finish(pm, initial, response(
            ('spawn_worker', {'task': 'Keep working', 'role': 'review', 'profile_id': 'local'}),
            ('ask_user', {'question': 'First team decision?'})))
        worker = case.engine.agents[first['agent_ids'][1]]
        held = await case.take(worker)
        second, other, initial = await case.start()
        await case.finish(other, initial, response(('ask_user', {'question': 'Other team decision?'})))
        assert first['status'] == 'running' and worker.status == 'working'
        before = copy.deepcopy(case.engine.snapshot())
        calls = len(case.provider.history)
        for run, agent in [(second, other), (first, worker), (second, other)]:
            state = await snapshot(case, run, agent)
            assert paused(state) == {pm.id, other.id}
            for item in state['agents']:
                assert ('logs' in item) == (item['id'] == agent.id)
                assert ('results' in item) == (item['id'] == agent.id)
        assert case.engine.snapshot() == before
        assert len(case.provider.history) == calls and case.provider.requested.empty()
        assert not held.future.done() and pm.question and other.question
        await case.stop(first)
        await case.stop(second)


async def test_deadline_blocks_reply_without_hiding_or_mutating_the_paused_question(tmp_path, monkeypatch):
    async with session(tmp_path) as case:
        run, pm, initial = await case.start()
        await case.finish(pm, initial, response(('ask_user', {'question': 'Keep this unanswered question'})))
        before = await snapshot(case, run, pm)
        assert before['agents'][0]['message_eligibility']['allowed']
        sequence = case.engine.sequence
        counters = (run['model_calls'], run['tool_calls'], run['auto_collaborations'], pm.result_revision)
        monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda:
            run['created_at'] + run['_config']['limits']['max_run_seconds'] + 1))
        after = await snapshot(case, run, pm)
        assert paused(after) == {pm.id}
        assert after['agents'][0]['message_eligibility']['reason'] == 'time_limit'
        state_before_rejection = case.engine.snapshot()
        await case.api('post', f'/api/agents/{pm.id}/message', {'text': 'Too late'}, status=400)
        assert case.engine.snapshot() == state_before_rejection
        assert case.engine.sequence == sequence
        assert (run['model_calls'], run['tool_calls'], run['auto_collaborations'], pm.result_revision) == counters
        assert case.provider.requested.empty()


@pytest.mark.parametrize('action', ['reply', 'stop'])
async def test_only_explicit_reply_or_stop_removes_its_question_and_never_refills_budgets(tmp_path, action):
    async with session(tmp_path, limits={'max_tool_calls': 1, 'max_auto_collaborations': 0}) as case:
        first, pm, initial = await case.start()
        await case.finish(pm, initial, response(('ask_user', {'question': 'Leave first question alone'})))
        second, other, initial = await case.start()
        await case.finish(other, initial, response(('ask_user', {'question': 'Second question'})))
        state = await snapshot(case, first, pm)
        assert paused(state) == {pm.id, other.id}
        item = next(agent for agent in state['agents'] if agent['id'] == other.id)
        assert item['message_eligibility']['allowed'] and 'ツール' in item['message_eligibility']['message']
        if action == 'reply':
            await case.api('post', f'/api/agents/{other.id}/message', {'text': '  Explicit answer\n  '})
            resumed = await case.take(other)
            assert resumed.messages[-1]['content'] == '  Explicit answer\n  '
            assert not other.question and pm.question
            await case.finish(other, resumed, response(text='Text-only continuation'))
            assert second['model_calls'] == 2 and other.results[-1]['text'] == 'Text-only continuation'
        else:
            await case.stop(second)
            assert other.question == 'Second question'  # Kept as history, not an active human pause.
            assert second['model_calls'] == 1
        assert paused(await snapshot(case, first, pm)) == {pm.id}
        assert second['tool_calls'] == 1 and second['auto_collaborations'] == 0
        assert first['model_calls'] == first['tool_calls'] == 1
        assert case.provider.requested.empty()
