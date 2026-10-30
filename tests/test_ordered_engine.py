"""Ordered workflow integration: real Engine boundaries, synthetic providers only.

These fixed text fixtures exercise the protocol; they are not a real-model
shiritori result or a semantic judgment supplied by the application.
"""
import asyncio
import copy
import json
import time

import pytest

from workbench.config import DEFAULT, Settings
from workbench.engine import Engine
from test_engine import configured, reply


pytestmark = pytest.mark.asyncio

SEED = 'りんご'
VALUES = ('ごま', 'まめ', 'めだか', 'からす', 'すし', 'しお')
TASK = 'Three independent participants take two turns each. Audit each contribution; do not invent another participant\'s work.'


@pytest.fixture(autouse=True)
def no_operator_credentials(monkeypatch):
    for profile in [*DEFAULT['providers'], DEFAULT['search']]:
        if profile['api_key_env']:
            monkeypatch.delenv(profile['api_key_env'], raising=False)


class ObservedClient:
    """No network and no implicit fallback response for an unplanned actor."""
    def __init__(self):
        self.handlers = {}
        self.calls = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        observed = copy.deepcopy({'profile': profile, 'messages': messages, 'tools': tools,
                                  'system': system, 'limits': limits,
                                  'conversation_id': conversation_id})
        self.calls.append(observed)
        assert len(self.calls) <= 24, 'Synthetic fixture exceeded the unchanged shared model budget'
        ident = conversation_id.rsplit('/', 1)[1]
        assert ident in self.handlers, 'An unplanned participant was scheduled'
        return await self.handlers[ident](observed)


async def team(tmp_path, *, count=3, creation_order=('C', 'A', 'B')):
    client = ObservedClient()
    engine, work = configured(tmp_path, client)
    engine.settings.value['limits'].update(max_model_calls=24, max_tool_calls=60,
        max_auto_collaborations=24, max_run_seconds=3600, max_output_tokens=2048,
        max_turns_per_agent=20)
    # Scheduling is stepped by the test, but real Engine.kick/_agent_loop are
    # used after setup. No consumed grant, dispatch token or report is seeded.
    engine.kick = lambda agent: None
    started = await engine.start_run({'task': TASK, 'pm_profile': 'local',
        'worker_profiles': ['local'], 'max_workers': count,
        'delegation_level': 2, 'workers_per_pm': count})
    run = engine.runs[started['run']['id']]
    pm = engine.agents[run['pm_agent_ids'][0]]
    pm.pending.clear()
    pm.status = 'idle'
    workers = {}
    for key in creation_order:
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'independent contributor',
            'task': f'Participant {key}: supply only your own contribution when granted a turn.',
            'participant_key': key, 'initial_wait': True})
        workers[key] = engine.agents[spawned['agent_id']]
    return engine, run, pm, workers, client, work


async def view(engine, run, pm):
    roster = await engine.execute_tool(run, pm, 'list_team', {})
    # An ordinary/unstarted run has no workflow; starting cannot be simulated by
    # creating a test-owned private flow or grant.
    return copy.deepcopy(roster.get('ordered_work'))


async def begin(engine, run, pm, *, order=('A', 'B', 'C'), rounds=2):
    return await engine.execute_tool(run, pm, 'start_ordered_work', {
        'order': list(order), 'rounds': rounds, 'seed': SEED, 'validator': 'text_chain'})


async def drive(agent):
    Engine.kick(agent._test_engine, agent)
    task = agent.task
    assert task is not None
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        await asyncio.wait_for(asyncio.shield(task), 10)
    except TimeoutError as exc:
        try:
            observed = getattr(agent, '_provider_observation', {}) or {}
            task_error = task.exception() if task.done() and not task.cancelled() else None
            def label(value):
                return value[:64] if isinstance(value, str) else None
            diagnostic = {
                'elapsed_seconds': loop.time() - started,
                'task_done': task.done(), 'task_cancelled': task.cancelled(),
                'task_error_type': type(task_error).__name__[:80] if task_error is not None else None,
                'same_task_error': task_error is exc,
                'agent_status': label(agent.status), 'stop_reason': label(agent.stop_reason),
                'has_error': bool(agent.last_error), 'has_question': bool(agent.question),
                'pending_count': len(agent.pending),
                'provider_phase': label(observed.get('phase')), 'provider_purpose': label(observed.get('purpose')),
                'stack': [{'file': frame.f_code.co_filename.replace('\\', '/').rsplit('/', 1)[-1][:120],
                           'function': frame.f_code.co_name[:80], 'line': frame.f_lineno}
                          for frame in task.get_stack(limit=6)],
            }
            exc.add_note('drive timeout observation (no locals/content): ' + json.dumps(diagnostic))
        except Exception as observation_error:
            exc.add_note('drive timeout observation failed: ' + type(observation_error).__name__[:80])
        raise
    await asyncio.sleep(0)


def bind_driver(engine):
    for agent in engine.agents.values():
        agent._test_engine = engine


async def wait_reply(observed):
    return reply(calls=[('wait_for_message', {})])


def tool_results(agent, name):
    return [json.loads(message['content']) for message in agent.conversation
            if message['role'] == 'tool' and message.get('name') == name]


def mail_events(engine, kind='mail'):
    return [event for event in engine.events if event['kind'] == kind]


async def effects(engine, run, pm):
    return {'view': await view(engine, run, pm),
        'auto': run['auto_collaborations'], 'events': copy.deepcopy(list(engine.events)),
        'agents': {ident: {'pending': list(agent.pending), 'revision': agent.result_revision,
                          'finished': agent.finished_revision,
                          'reviews': copy.deepcopy(agent.worker_report_reviews)}
                   for ident, agent in engine.agents.items()}}


async def rejected(engine, run, actor, name, args):
    try:
        result = await engine.execute_tool(run, actor, name, args)
    except ValueError as exc:
        assert str(exc)
        return
    assert isinstance(result, dict) and result.get('ok') is False, result


def assert_real_consumption_before_request(engine, actor, observed):
    inference = [event for event in engine.events
                 if event['kind'] == 'inference' and event['agent_id'] == actor.id][-1]
    consumed = [event for event in mail_events(engine, 'mail_consumed')
                if event['to_agent_id'] == actor.id and event['id'] < inference['id']]
    assert consumed
    latest = consumed[-1]
    queued = next(event for event in mail_events(engine) if event['mail_id'] == latest['mail_id'])
    assert queued['id'] < latest['id'] < inference['id']
    assert any(latest['mail_id'] in message.get('content', '')
               for message in observed['messages'] if message['role'] == 'user')


async def install_accepting_scripts(engine, run, pm, workers, client, *, finish=True):
    async def contribute(observed):
        actor = engine.agents[observed['conversation_id'].rsplit('/', 1)[1]]
        current = (await view(engine, run, pm))['current']
        assert current['actor_id'] == actor.id
        assert 'send_message' in {tool['name'] for tool in observed['tools']}
        assert_real_consumption_before_request(engine, actor, observed)
        assert 'Ordered-work report contract' in observed['system']
        assert 'and use finish_work to send a current completion report' not in observed['system']
        assert 'Workers must use finish_work for a completed report.' not in observed['system']
        shared_marker = 'Shared original human request (copied by the application, not paraphrased by the PM):\n'
        shared, _ = json.JSONDecoder().raw_decode(observed['system'].split(shared_marker, 1)[1])
        assert shared == {'original_human_request': TASK, 'pm_assignment': actor.assignment}
        return reply(calls=[('submit_work_step', {
            'value': VALUES[current['step'] - 1], 'summary': f'Synthetic contribution {current["step"]}.'})])

    async def audit(observed):
        state = await view(engine, run, pm)
        assert_real_consumption_before_request(engine, pm, observed)
        ready = all(child.finished_revision == child.result_revision
                    and pm.worker_report_consumed.get(child.id) == child.result_revision
                    and pm.worker_report_deliveries.get(child.id) == child.result_revision
                    for child in workers.values())
        final_tools = [*[( 'review_worker_report', {
            'worker_id': child.id, 'result_revision': child.result_revision,
            'decision': 'accept', 'feedback': 'Checked the current synthetic report.'})
            for child in workers.values()],
            ('finish_work', {'summary': 'All synthetic contributions were audited and current reports accepted.'})]
        if state['phase'] == 'pending_review':
            last = state['pending']['step'] == len(state['order']) * state['rounds']
            return reply(calls=[('review_work_step', {
                'decision': 'accept', 'feedback': 'The synthetic fixture contribution matches the stated constraint.'}),
                *(final_tools if finish and last and ready else [('wait_for_message', {})])])
        if finish and state['complete'] and ready:
            return reply(calls=final_tools)
        return await wait_reply(observed)

    client.handlers[pm.id] = audit
    for child in workers.values():
        client.handlers[child.id] = contribute
    bind_driver(engine)


async def advance(engine, run, pm, workers, *, steps):
    for _ in range(steps):
        state = await view(engine, run, pm)
        assert state['phase'] == 'ready'
        actor = engine.agents[state['current']['actor_id']]
        await drive(actor)
        assert not actor.last_error
        assert (await view(engine, run, pm))['phase'] == 'pending_review'
        await drive(pm)
        assert not pm.last_error


async def test_initial_wait_keeps_assignment_without_scheduling_or_pretending_completion(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    try:
        bind_driver(engine)
        for key, worker in workers.items():
            Engine.kick(engine, worker)
            assert worker.task is None
            assert worker.assignment.startswith(f'Participant {key}:')
            assert not worker.pending and not worker.results
            assert worker.finished_revision is None and worker.status != 'done'
            assert worker.id in engine._policy(run, worker)
            assert TASK in engine._policy(run, worker)
        assert not client.calls and run['model_calls'] == run['tool_calls'] == 0
        assert run['auto_collaborations'] == 3
        assert not mail_events(engine)
    finally:
        await engine.close()


async def test_unselected_ordinary_spawn_preserves_the_existing_immediate_task_queue(tmp_path):
    engine, run, pm, _, client, _ = await team(tmp_path, count=1, creation_order=())
    try:
        result = await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'ordinary worker', 'task': 'Use the ordinary independent workflow.'})
        worker = engine.agents[result['agent_id']]
        assert list(worker.pending) == [('Use the ordinary independent workflow.', False)]
        assert not worker.waiting_for_message and worker.finished_revision is None
        assert not client.calls and run['auto_collaborations'] == 1
    finally:
        await engine.close()


@pytest.mark.parametrize('args', [
    {'participant_key': ''}, {'participant_key': 'A A'}, {'participant_key': 'A' * 25},
    {'participant_key': 'A', 'initial_wait': 'true'}, {'participant_key': 'A', 'initial_wait': 1},
])
async def test_registration_rejects_invalid_key_or_nonboolean_wait_before_creating_worker(tmp_path, args):
    engine, run, pm, _, _, _ = await team(tmp_path, count=1, creation_order=())
    try:
        before = (list(run['agent_ids']), run['auto_collaborations'])
        await rejected(engine, run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'contributor', 'task': 'Independent work.',
            'participant_key': 'A', 'initial_wait': True, **args})
        assert before == (run['agent_ids'], run['auto_collaborations'])
    finally:
        await engine.close()


@pytest.mark.parametrize('change', [
    {'order': ['A', 'A', 'C']}, {'order': ['A', 'B', 'missing']},
    {'rounds': True}, {'rounds': 0}, {'validator': 'invented'}, {'seed': ''},
])
async def test_invalid_start_is_atomic_and_does_not_send_a_grant(tmp_path, change):
    engine, run, pm, _, _, _ = await team(tmp_path)
    try:
        before = await effects(engine, run, pm)
        await rejected(engine, run, pm, 'start_ordered_work', {
            'order': ['A', 'B', 'C'], 'rounds': 2, 'seed': SEED,
            'validator': 'text_chain', **change})
        assert await effects(engine, run, pm) == before
    finally:
        await engine.close()


async def test_only_own_pm_can_start_and_start_cannot_reset_an_existing_workflow(tmp_path):
    engine, run, pm, workers, _, _ = await team(tmp_path)
    try:
        args = {'order': ['A', 'B', 'C'], 'rounds': 2, 'seed': SEED, 'validator': 'text_chain'}
        before = await effects(engine, run, pm)
        await rejected(engine, run, workers['A'], 'start_ordered_work', args)
        assert await effects(engine, run, pm) == before
        await begin(engine, run, pm)
        started = await effects(engine, run, pm)
        assert started['view']['current']['actor_id'] == workers['A'].id
        assert len(workers['A'].pending) == 1
        assert not workers['B'].pending and not workers['C'].pending
        await rejected(engine, run, pm, 'start_ordered_work', args)
        assert await effects(engine, run, pm) == started
    finally:
        await engine.close()


async def test_unconsumed_grant_or_candidate_text_does_not_authorize_direct_tool_execution(tmp_path):
    engine, run, pm, workers, _, _ = await team(tmp_path)
    try:
        await begin(engine, run, pm)
        before = await effects(engine, run, pm)
        await rejected(engine, run, workers['A'], 'submit_work_step', {'value': VALUES[0], 'summary': 'Not consumed.'})
        await rejected(engine, run, workers['B'], 'submit_work_step', {'value': VALUES[0], 'summary': 'Wrong participant.'})
        await rejected(engine, run, pm, 'review_work_step', {'decision': 'accept', 'feedback': 'No candidate was consumed.'})
        assert await effects(engine, run, pm) == before
    finally:
        await engine.close()


async def test_six_real_loop_handoffs_require_each_pm_audit_and_current_formal_reports(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    try:
        await install_accepting_scripts(engine, run, pm, workers, client)
        await begin(engine, run, pm)
        await advance(engine, run, pm, workers, steps=6)
        state = await view(engine, run, pm)
        assert state['complete'] and state['phase'] == 'complete' and state['current'] is None
        assert [row['participant_key'] for row in state['accepted']] == ['A', 'B', 'C', 'A', 'B', 'C']
        assert [row['value'] for row in state['accepted']] == list(VALUES)
        assert [row['step'] for row in state['accepted']] == list(range(1, 7))
        for previous, current in zip(state['accepted'], state['accepted'][1:]):
            assert current['dependency_receipt'] == previous['id']
            assert current['dependency_sha256'] == previous['sha256']
        assert all(row['checks']['semantic_status'] == 'unchecked' for row in state['accepted'])
        assert run['status'] == pm.status == 'done'
        for worker in workers.values():
            assert worker.status == 'done' and not worker.pending
            assert worker.finished_revision == worker.result_revision
            assert any(row['source'] == 'submit_work_step' for row in worker.results)
            assert pm.worker_report_consumed[worker.id] == worker.result_revision
            assert pm.worker_report_reviews[worker.id] == {'result_revision': worker.result_revision, 'decision': 'accept'}
        assert engine._delegation_issue(run, pm, finishing=True) is None
        assert any(row['source'] == 'finish_work' for row in pm.results)
        assert len(tool_results(pm, 'review_work_step')) == 6
        assert len(tool_results(pm, 'review_worker_report')) == 3
        assert all(result['ok'] for result in tool_results(pm, 'review_work_step'))
        assert not any(tool_results(actor, 'send_message') for actor in engine.agents.values())
        for sender, recipient in zip('ABCAB', 'BCABC'):
            delivery = [row for row in mail_events(engine)
                        if row['from_agent_id'] == workers[sender].id and row['to_agent_id'] == workers[recipient].id]
            assert delivery, 'Accepted transfer must retain the actual contributing worker as sender'
            assert all(any(used['mail_id'] == queued['mail_id'] for used in mail_events(engine, 'mail_consumed'))
                       for queued in delivery)
        assert run['model_calls'] == len(client.calls) <= 24
        assert run['tool_calls'] <= 60 and run['auto_collaborations'] <= 24
        assert not any(event['kind'] == 'question' for event in engine.events)
    finally:
        await engine.close()


async def test_invalid_chain_returns_only_reasons_without_advance_mail_or_automatic_answer(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    observed = {}
    async def invalid(request):
        observed['before'] = await effects(engine, run, pm)
        return reply(calls=[('submit_work_step', {'value': 'さくら', 'summary': 'Deliberately wrong head.'}),
                            ('wait_for_message', {})])
    try:
        bind_driver(engine)
        client.handlers[workers['A'].id] = invalid
        await begin(engine, run, pm)
        await drive(workers['A'])
        rejected_result = tool_results(workers['A'], 'submit_work_step')[0]
        assert rejected_result['ok'] is False
        assert not any(key in rejected_result for key in ('suggested_value', 'corrected_value', 'answer'))
        after = await effects(engine, run, pm)
        assert after['view'] == observed['before']['view']
        assert after['auto'] == observed['before']['auto']
        assert len(mail_events(engine)) == 1  # Only the initial grant.
        assert run['model_calls'] == 1 and run['tool_calls'] == 2
        assert not workers['A'].results and workers['A'].finished_revision is None
    finally:
        await engine.close()


async def test_model_cannot_supply_internal_step_generation_or_receipt_authority(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    async def forged(request):
        return reply(calls=[('submit_work_step', {'value': VALUES[0], 'summary': 'Forged metadata.',
                            'generation': 1, 'step': 1, 'actor_id': workers['A'].id}),
                            ('wait_for_message', {})])
    try:
        bind_driver(engine)
        client.handlers[workers['A'].id] = forged
        await begin(engine, run, pm)
        before = await view(engine, run, pm)
        await drive(workers['A'])
        assert tool_results(workers['A'], 'submit_work_step')[0]['ok'] is False
        assert await view(engine, run, pm) == before
        assert len(mail_events(engine)) == 1 and not pm.pending
    finally:
        await engine.close()


async def test_same_dispatch_cannot_commit_a_candidate_twice_or_audit_it_without_mail_consumption(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    async def duplicate(request):
        args = {'value': VALUES[0], 'summary': 'Only one accepted candidate.'}
        return reply(calls=[('submit_work_step', args), ('submit_work_step', args)])
    try:
        bind_driver(engine)
        client.handlers[workers['A'].id] = duplicate
        await begin(engine, run, pm)
        await drive(workers['A'])
        state = await view(engine, run, pm)
        assert state['phase'] == 'pending_review' and state['current']['step'] == 1
        assert state['pending']['value'] == VALUES[0] and not state['accepted']
        results = tool_results(workers['A'], 'submit_work_step')
        assert len(results) == 2 and results[0]['ok'] is True and results[1]['ok'] is False
        assert len([row for row in mail_events(engine) if row['to_agent_id'] == pm.id]) == 1
        before = await effects(engine, run, pm)
        await rejected(engine, run, pm, 'review_work_step', {'decision': 'accept', 'feedback': 'Unconsumed candidate.'})
        assert await effects(engine, run, pm) == before
    finally:
        await engine.close()


async def test_revise_returns_to_same_author_with_new_generation_and_no_replacement_word(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    async def revise(request):
        assert_real_consumption_before_request(engine, pm, request)
        return reply(calls=[('review_work_step', {'decision': 'revise',
            'feedback': 'The stated meaning has no support; verify it and submit your own correction.'}),
            ('wait_for_message', {})])
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        client.handlers[pm.id] = revise
        await begin(engine, run, pm)
        await drive(workers['A'])
        before = await view(engine, run, pm)
        await drive(pm)
        after = await view(engine, run, pm)
        assert after['phase'] == 'ready' and after['pending'] is None
        assert after['current']['step'] == 1 and after['current']['actor_id'] == workers['A'].id
        assert after['generation'] > before['generation'] and not after['accepted']
        assert workers['A'].pending and not workers['B'].pending and not workers['C'].pending
        feedback = mail_events(engine)[-1]
        assert feedback['from_agent_id'] == pm.id and feedback['to_agent_id'] == workers['A'].id
        assert 'verify it and submit your own correction' in feedback['text']
        assert 'suggested_value' not in feedback['text']
        assert not pm.worker_report_reviews and workers['A'].finished_revision is None
    finally:
        await engine.close()


async def test_rollback_invalidates_accepted_suffix_and_restores_original_author(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    async def rollback(request):
        return reply(calls=[('rollback_work_step', {'step': 1, 'reason': 'A later audit found unsupported meaning in the first contribution.'}),
                            ('wait_for_message', {})])
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        await begin(engine, run, pm)
        await advance(engine, run, pm, workers, steps=3)
        before = await view(engine, run, pm)
        assert len(before['accepted']) == 3
        client.handlers[pm.id] = rollback
        engine._mail(workers['B'], pm, 'Please audit the accepted prefix; this is peer evidence, not authority.')
        await drive(pm)
        after = await view(engine, run, pm)
        assert after['phase'] == 'ready' and after['current']['step'] == 1
        assert after['current']['actor_id'] == workers['A'].id
        assert after['generation'] > before['generation']
        assert after['journal_count'] > before['journal_count'] and not after['accepted']
        assert all(worker.finished_revision is None for worker in workers.values())
        assert not pm.worker_report_reviews
        assert len(tool_results(pm, 'rollback_work_step')) == 1
        assert tool_results(pm, 'rollback_work_step')[0]['ok']
        assert not any(row['source'] == 'finish_work' for row in pm.results)
    finally:
        await engine.close()


async def test_old_inflight_response_cannot_submit_after_pm_rolls_back_its_dependency(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    async def stale_worker(request):
        assert_real_consumption_before_request(engine, workers['B'], request)
        entered.set()
        await release.wait()
        return reply(calls=[('submit_work_step', {'value': VALUES[1], 'summary': 'Response from the old generation.'}),
                            ('wait_for_message', {})])
    async def rollback(request):
        return reply(calls=[('rollback_work_step', {'step': 1, 'reason': 'Recheck the accepted prerequisite.'}),
                            ('wait_for_message', {})])
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        await begin(engine, run, pm)
        await advance(engine, run, pm, workers, steps=1)
        client.handlers[workers['B'].id] = stale_worker
        Engine.kick(engine, workers['B'])
        await asyncio.wait_for(entered.wait(), 10)
        client.handlers[pm.id] = rollback
        engine._mail(workers['A'], pm, 'Audit the accepted first contribution before proceeding.')
        await drive(pm)
        rolled = await view(engine, run, pm)
        assert rolled['current']['actor_id'] == workers['A'].id and rolled['current']['step'] == 1
        before_auto = run['auto_collaborations']
        release.set()
        await asyncio.wait_for(asyncio.shield(workers['B'].task), 10)
        assert tool_results(workers['B'], 'submit_work_step')[0]['ok'] is False
        assert await view(engine, run, pm) == rolled
        assert run['auto_collaborations'] == before_auto
        assert not workers['B'].results and workers['B'].finished_revision is None
    finally:
        release.set()
        await engine.close()


@pytest.mark.parametrize('blocked', ['queue', 'auto'])
async def test_start_delivery_rejection_preserves_workflow_and_budget(tmp_path, blocked):
    engine, run, pm, workers, _, _ = await team(tmp_path)
    try:
        if blocked == 'queue':
            for _ in range(31):
                engine.enqueue(workers['A'], 'Already queued ordinary peer data')
        else:
            run['auto_collaborations'] = 24
        before = await view(engine, run, pm)
        agent_ids = list(run['agent_ids'])
        auto, queued = run['auto_collaborations'], list(workers['A'].pending)
        await rejected(engine, run, pm, 'start_ordered_work', {
            'order': ['A', 'B', 'C'], 'rounds': 2, 'seed': SEED, 'validator': 'text_chain'})
        assert await view(engine, run, pm) == before
        assert run['agent_ids'] == agent_ids and run['auto_collaborations'] == auto
        assert list(workers['A'].pending) == queued and not mail_events(engine)
    finally:
        await engine.close()


async def test_bare_tool_name_is_never_executed_or_promoted_to_formal_completion(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    async def bare(request):
        return reply('wait_for_message')
    try:
        bind_driver(engine)
        client.handlers[workers['A'].id] = bare
        await begin(engine, run, pm)
        before = await view(engine, run, pm)
        initial_wait_events = [event['id'] for event in engine.events if event['kind'] == 'message_wait']
        await drive(workers['A'])
        assert len(client.calls) == run['model_calls'] == 3  # Original response plus at most two explicit repair prompts.
        assert run['tool_calls'] == 0
        assert workers['A'].status == 'error' and workers['A'].finished_revision is None
        assert not workers['A'].results and not pm.worker_report_deliveries
        assert not tool_results(workers['A'], 'wait_for_message')
        assert await view(engine, run, pm) == before
        assert [event['id'] for event in engine.events if event['kind'] == 'message_wait'] == initial_wait_events
    finally:
        await engine.close()


@pytest.mark.parametrize('limit', ['model', 'tool', 'time'])
async def test_ordered_work_never_refills_or_bypasses_existing_hard_budget(tmp_path, limit):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    async def one(request):
        return reply(calls=[('submit_work_step', {'value': VALUES[0], 'summary': 'Budget-limited proposal.'})])
    try:
        bind_driver(engine)
        client.handlers[workers['A'].id] = one
        await begin(engine, run, pm)
        if limit == 'model':
            run['model_calls'] = 24
        elif limit == 'tool':
            run['tool_calls'] = 60
        else:
            run['created_at'] = time.time() - 3601
        before = await view(engine, run, pm)
        await drive(workers['A'])
        assert workers['A'].status == 'error' and workers['A'].stop_reason == limit + '_limit'
        assert await view(engine, run, pm) == before
        assert len(client.calls) == (1 if limit == 'tool' else 0)
        assert not workers['A'].results and workers['A'].finished_revision is None
        assert run['model_calls'] <= 24 and run['tool_calls'] <= 60
    finally:
        await engine.close()


async def test_archive_retains_audit_but_does_not_restore_live_workflow_authority(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        await begin(engine, run, pm)
        await advance(engine, run, pm, workers, steps=1)
        saved, _ = engine.history.read(run['id'], engine.redact)
        assert any(event['kind'] == 'mail' for event in saved['events'])
        assert any(event['kind'] == 'mail_consumed' for event in saved['events'])
        assert any('submit_work_step' in log['text'] for agent in saved['agents'] for log in agent['logs'])
    finally:
        await engine.close()
    restored_client = ObservedClient()
    restored = Engine(Settings(tmp_path / 'state'), restored_client)
    try:
        assert not restored.runs and not restored.agents and not restored_client.calls
        archived = next(item for item in restored.snapshot()['runs'] if item['id'] == run['id'])
        assert archived['archived'] is True and archived['read_only'] is True
        with pytest.raises(ValueError):
            await restored.human_message(workers['A'].id, 'Do not resume an archived turn')
        assert not restored_client.calls
    finally:
        await restored.close()


async def test_duplicate_participant_key_is_rejected_before_agent_or_budget_creation(tmp_path):
    engine, run, pm, workers, _, _ = await team(tmp_path, count=3, creation_order=('A', 'B'))
    try:
        before = (list(run['agent_ids']), run['auto_collaborations'])
        await rejected(engine, run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'different label', 'task': 'This does not replace the existing participant.',
            'participant_key': 'A', 'initial_wait': True})
        assert (run['agent_ids'], run['auto_collaborations']) == before
        assert engine.agents[workers['A'].id].assignment.startswith('Participant A:')
    finally:
        await engine.close()


async def test_multi_pm_ordered_start_is_rejected_before_blocking_other_pm_delegation(tmp_path):
    client = ObservedClient()
    engine, _ = configured(tmp_path, client)
    engine.kick = lambda agent: None
    try:
        started = await engine.start_run({'task': 'Two independent PMs; preserve their own delegation.',
            'pm_profiles': ['local', 'local'], 'worker_profiles': ['local'], 'max_workers': 2,
            'delegation_level': 2, 'workers_per_pm': 1})
        run = engine.runs[started['run']['id']]
        first, second = [engine.agents[ident] for ident in run['pm_agent_ids']]
        for pm in (first, second):
            pm.pending.clear()
            pm.status = 'idle'
        await engine.execute_tool(run, first, 'spawn_worker', {
            'profile_id': 'local', 'role': 'first PM contributor', 'task': 'Wait for your own PM.',
            'participant_key': 'A', 'initial_wait': True})
        before = await effects(engine, run, first)
        await rejected(engine, run, first, 'start_ordered_work', {
            'order': ['A'], 'rounds': 2, 'seed': SEED, 'validator': 'text_chain'})
        assert await effects(engine, run, first) == before
        spawned = await engine.execute_tool(run, second, 'spawn_worker', {
            'profile_id': 'local', 'role': 'ordinary second PM worker',
            'task': 'Continue ordinary work under the second PM.'})
        child = engine.agents[spawned['agent_id']]
        assert child.parent_id == second.id and child.pending
        assert not client.calls and not mail_events(engine)
    finally:
        await engine.close()


async def test_foreign_run_pm_cannot_start_another_teams_registered_participants(tmp_path):
    engine, run, pm, _, _, _ = await team(tmp_path)
    try:
        other_started = await engine.start_run({'task': 'Separate run; no cross-run authority.',
            'pm_profile': 'local', 'worker_profiles': ['local'], 'max_workers': 0,
            'delegation_level': 0})
        other_run = engine.runs[other_started['run']['id']]
        other_pm = engine.agents[other_run['pm_agent_ids'][0]]
        before = await effects(engine, run, pm)
        await rejected(engine, run, other_pm, 'start_ordered_work', {
            'order': ['A', 'B', 'C'], 'rounds': 2, 'seed': SEED, 'validator': 'text_chain'})
        assert await effects(engine, run, pm) == before
    finally:
        await engine.close()


@pytest.mark.parametrize('arrival', ['human', 'peer'])
@pytest.mark.parametrize('operation', ['accept', 'rollback'])
async def test_new_input_during_pm_request_invalidates_old_audit_response(tmp_path, arrival, operation):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    calls = 0
    async def stale_audit(request):
        nonlocal calls
        calls += 1
        if calls != 1:
            return await wait_reply(request)
        # complete() has been entered: the provider's request and dispatch token
        # precede this actual new mailbox input.
        if arrival == 'human':
            engine.enqueue(pm, 'New human evidence requires a fresh audit.', human=True)
        else:
            engine._mail(workers['C'], pm, 'New peer evidence requires a fresh audit.')
        call = ('review_work_step', {'decision': 'accept', 'feedback': 'This decision used the superseded request.'})
        if operation == 'rollback':
            call = ('rollback_work_step', {'step': 1, 'reason': 'This rollback used the superseded request.'})
        return reply(calls=[call, ('wait_for_message', {})])
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        await begin(engine, run, pm)
        if operation == 'rollback':
            await advance(engine, run, pm, workers, steps=1)
            engine._mail(workers['A'], pm, 'Inspect the accepted prefix.')
        else:
            await drive(workers['A'])
        before = await view(engine, run, pm)
        client.handlers[pm.id] = stale_audit
        await drive(pm)
        name = 'review_work_step' if operation == 'accept' else 'rollback_work_step'
        assert tool_results(pm, name)[-1]['ok'] is False
        assert await view(engine, run, pm) == before
        assert calls == 2 and not pm.last_error
        assert not any(event['kind'] == 'ordered_rollback' for event in engine.events)
    finally:
        await engine.close()


async def test_single_participant_two_rounds_uses_real_grants_without_self_mail(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path, count=1, creation_order=('A',))
    try:
        await install_accepting_scripts(engine, run, pm, workers, client)
        await begin(engine, run, pm, order=('A',), rounds=2)
        await advance(engine, run, pm, workers, steps=2)
        state = await view(engine, run, pm)
        assert state['complete'] and [row['value'] for row in state['accepted']] == list(VALUES[:2])
        assert [row['actor_id'] for row in state['accepted']] == [workers['A'].id] * 2
        assert all(event['from_agent_id'] != event['to_agent_id'] for event in mail_events(engine))
        assert run['status'] == pm.status == workers['A'].status == 'done'
    finally:
        await engine.close()


@pytest.mark.parametrize('failure', ['before_record', 'after_record'])
async def test_final_candidate_already_delivered_is_not_resent_or_reclassified_as_worker_error(tmp_path, monkeypatch, failure):
    engine, run, pm, workers, client, _ = await team(tmp_path, count=1, creation_order=('A',))
    record = engine.record_result
    injected = False
    def record_failure(agent, source, text, **kwargs):
        nonlocal injected
        if source == 'submit_work_step' and not injected:
            injected = True
            if failure == 'after_record':
                record(agent, source, text, **kwargs)
            raise OSError('Synthetic result-record failure after candidate delivery')
        return record(agent, source, text, **kwargs)
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        await begin(engine, run, pm, order=('A',), rounds=1)
        monkeypatch.setattr(engine, 'record_result', record_failure)
        await drive(workers['A'])
        assert injected
        candidate_messages = [event for event in mail_events(engine) if event['to_agent_id'] == pm.id]
        assert len(candidate_messages) == 1
        assert candidate_messages[0]['message_type'] == 'worker_report'
        assert not any(event['message_type'] == 'worker_error' for event in mail_events(engine))
        result = tool_results(workers['A'], 'submit_work_step')[0]
        assert result['ok'] and result['queued'] and result['warning']
        assert (await view(engine, run, pm))['phase'] == 'pending_review'
        assert len(client.calls) == 1 and run['auto_collaborations'] == 3
        assert not workers['A'].last_error
    finally:
        await engine.close()


@pytest.mark.parametrize('blocked', ['queue', 'auto'])
async def test_candidate_delivery_failure_does_not_commit_candidate_or_formal_report(tmp_path, blocked):
    engine, run, pm, workers, client, _ = await team(tmp_path, count=1, creation_order=('A',))
    observed = {}
    async def submit(request):
        if blocked == 'queue':
            for _ in range(31):
                engine.enqueue(pm, 'Existing peer input')
        else:
            run['auto_collaborations'] = 24
        observed['auto'] = run['auto_collaborations']
        return reply(calls=[('submit_work_step', {'value': VALUES[0], 'summary': 'Must not commit without delivery.'}),
                            ('wait_for_message', {})])
    try:
        bind_driver(engine)
        client.handlers[workers['A'].id] = submit
        await begin(engine, run, pm, order=('A',), rounds=1)
        before = await view(engine, run, pm)
        await drive(workers['A'])
        assert tool_results(workers['A'], 'submit_work_step')[0]['ok'] is False
        assert await view(engine, run, pm) == before
        assert run['auto_collaborations'] == observed['auto']
        assert not workers['A'].results and workers['A'].finished_revision is None
        assert len(mail_events(engine)) == 1
        assert not pm.worker_report_deliveries
    finally:
        await engine.close()


async def test_ordered_public_audit_and_sqlite_mask_known_and_retired_secrets(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    secret = 'synthetic-ordered-known-secret-1046'
    async def submit(request):
        return reply(calls=[('submit_work_step', {'value': VALUES[0], 'summary': 'Evidence ' + secret})])
    try:
        bind_driver(engine)
        engine.set_secret('local', secret)
        client.handlers[workers['A'].id] = submit
        await begin(engine, run, pm)
        await drive(workers['A'])
        engine.set_secret('local', 'synthetic-replacement-key-1046')
        public = engine.snapshot()
        visible = json.dumps(public, ensure_ascii=False)
        assert secret not in visible and '[redacted]' in visible
        assert secret not in json.dumps(await view(engine, run, pm), ensure_ascii=False)
        saved, _ = engine.history.read(run['id'], engine.redact)
        assert secret not in json.dumps(saved, ensure_ascii=False)
        assert secret.encode() not in engine.history.path.read_bytes()
        assert len(mail_events(engine)) == 2 and len(client.calls) == 1
        assert not pm.worker_report_reviews
    finally:
        await engine.close()


async def test_formal_report_revise_cannot_leave_ordered_dependencies_and_acceptance_active(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    async def formal_accept(request):
        return reply(calls=[('review_worker_report', {
            'worker_id': workers['A'].id, 'result_revision': workers['A'].result_revision,
            'decision': 'accept', 'feedback': 'Checked the current formal report against its two accepted steps.'}),
            ('wait_for_message', {})])
    async def ordinary_revise(request):
        return reply(calls=[('review_worker_report', {
            'worker_id': workers['A'].id, 'result_revision': workers['A'].result_revision,
            'decision': 'revise', 'feedback': 'Reconsider the first contribution and every dependent step.'}),
            ('wait_for_message', {})])
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        await begin(engine, run, pm)
        await advance(engine, run, pm, workers, steps=4)
        assert workers['A'].finished_revision == workers['A'].result_revision
        assert pm.worker_report_consumed[workers['A'].id] == workers['A'].result_revision
        assert not (await view(engine, run, pm))['complete']
        client.handlers[pm.id] = formal_accept
        engine._mail(workers['B'], pm, 'Review the completed participant report before final integration.')
        await drive(pm)
        assert tool_results(pm, 'review_worker_report')[-1]['accepted'] is True
        client.handlers[pm.id] = ordinary_revise
        engine._mail(workers['B'], pm, 'New audit evidence about the accepted prefix.')
        before = {
            'view': await view(engine, run, pm), 'auto': run['auto_collaborations'],
            'reviews': copy.deepcopy(pm.worker_report_reviews),
            'worker_pending': {key: list(worker.pending) for key, worker in workers.items()},
            'mail_ids': [event['mail_id'] for event in mail_events(engine)],
        }
        await drive(pm)
        result = tool_results(pm, 'review_worker_report')[-1]
        assert result['ok'] is False and 'rollback_work_step' in result['error']
        assert await view(engine, run, pm) == before['view']
        assert run['auto_collaborations'] == before['auto']
        assert pm.worker_report_reviews == before['reviews']
        assert {key: list(worker.pending) for key, worker in workers.items()} == before['worker_pending']
        assert [event['mail_id'] for event in mail_events(engine)] == before['mail_ids']
        assert not any(event['kind'] == 'ordered_rollback' for event in engine.events)
        assert not any(row['source'] == 'finish_work' for row in pm.results)
    finally:
        await engine.close()


async def test_worker_human_answer_preserves_only_its_already_consumed_current_grant(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    worker = workers['A']
    consumed = {}
    answer = 'The supplied evidence is authorized; continue your existing assigned turn.'
    async def ask(request):
        assert_real_consumption_before_request(engine, worker, request)
        consumed['grant'] = copy.deepcopy(worker._ordered_consumed_grant)
        consumed['revision'] = worker.result_revision
        return reply(calls=[('ask_user', {'question': 'May I use the supplied private evidence for this turn?'})])
    async def submit(request):
        assert request['messages'][-1]['content'] == answer and request['messages'][-1]['_human'] is True
        assert worker.result_revision > consumed['revision']
        assert worker._ordered_consumed_grant == consumed['grant']
        assert worker._ordered_dispatch_grant == consumed['grant']
        return reply(calls=[('submit_work_step', {'value': VALUES[0], 'summary': 'Meaning checked after the human answer.'})])
    try:
        bind_driver(engine)
        client.handlers[worker.id] = ask
        await begin(engine, run, pm)
        await drive(worker)
        assert worker.status == 'waiting' and worker.question and consumed['grant']
        assert (await view(engine, run, pm))['phase'] == 'ready'
        assert not worker.results and len(mail_events(engine)) == 1
        client.handlers[worker.id] = submit
        await engine.human_message(worker.id, answer)
        await drive(worker)
        state = await view(engine, run, pm)
        assert state['phase'] == 'pending_review' and state['pending']['value'] == VALUES[0]
        assert not worker.question and not worker.last_error
        assert tool_results(worker, 'submit_work_step')[-1]['ok'] is True
        assert len(client.calls) == run['model_calls'] == 2 and run['tool_calls'] == 2
        assert len(mail_events(engine)) == 2  # Initial real grant and submitted candidate; no replacement grant.
        assert len(mail_events(engine, 'mail_consumed')) == 1
        assert not worker.results and worker.finished_revision is None
    finally:
        await engine.close()


async def test_pm_human_answer_preserves_only_its_already_consumed_current_candidate(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    consumed = {}
    answer = 'The candidate evidence may be used; audit the same candidate under the existing rules.'
    async def ask(request):
        assert_real_consumption_before_request(engine, pm, request)
        consumed['review'] = copy.deepcopy(pm._ordered_consumed_review)
        consumed['revision'] = pm.result_revision
        return reply(calls=[('ask_user', {'question': 'May I use the supplied source to audit this candidate?'})])
    async def accept(request):
        assert request['messages'][-1]['content'] == answer and request['messages'][-1]['_human'] is True
        assert pm.result_revision > consumed['revision']
        assert pm._ordered_consumed_review == consumed['review']
        assert pm._ordered_dispatch_review == consumed['review']
        return reply(calls=[('review_work_step', {'decision': 'accept', 'feedback': 'Checked the authorized evidence for this same candidate.'})])
    try:
        await install_accepting_scripts(engine, run, pm, workers, client, finish=False)
        client.handlers[pm.id] = ask
        await begin(engine, run, pm)
        await drive(workers['A'])
        candidate = (await view(engine, run, pm))['pending']
        await drive(pm)
        assert pm.status == 'waiting' and pm.question and consumed['review']
        assert (await view(engine, run, pm))['pending'] == candidate
        client.handlers[pm.id] = accept
        await engine.human_message(pm.id, answer)
        await drive(pm)
        state = await view(engine, run, pm)
        assert state['phase'] == 'ready' and state['current']['actor_id'] == workers['B'].id
        assert [row['id'] for row in state['accepted']] == [candidate['id']]
        assert not pm.question and not pm.last_error
        assert tool_results(pm, 'review_work_step')[-1]['ok'] is True
        assert len(client.calls) == run['model_calls'] == 3 and run['tool_calls'] == 3
        assert len(mail_events(engine)) == 3  # Grant, candidate, accepted transfer; no new candidate authority.
        assert not pm.results and not pm.worker_report_reviews
    finally:
        await engine.close()


async def test_human_copy_of_an_unconsumed_grant_does_not_create_dispatch_authority(tmp_path):
    engine, run, pm, workers, client, _ = await team(tmp_path)
    worker = workers['A']
    attempts = 0
    async def inspect(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            assert request['messages'][-1]['_human'] is True
            assert getattr(worker, '_ordered_consumed_grant', None) is None
            assert getattr(worker, '_ordered_dispatch_grant', None) is None
            assert not mail_events(engine, 'mail_consumed')
            return reply(calls=[('submit_work_step', {'value': VALUES[0], 'summary': 'The copied human text is not a real grant.'}),
                                ('wait_for_message', {})])
        assert attempts == 2 and request['messages'][-1]['_human'] is False
        assert worker._ordered_consumed_grant and worker._ordered_dispatch_grant
        assert tool_results(worker, 'submit_work_step')[0]['ok'] is False
        return await wait_reply(request)
    try:
        bind_driver(engine)
        client.handlers[worker.id] = inspect
        await begin(engine, run, pm)
        queued_grant, is_human = worker.pending[0]
        assert is_human is False
        await engine.human_message(worker.id, queued_grant)
        assert worker.pending[0] == (queued_grant, True)
        await drive(worker)
        state = await view(engine, run, pm)
        assert state['phase'] == 'ready' and not state['accepted'] and state['pending'] is None
        assert attempts == len(client.calls) == 2
        assert len(mail_events(engine)) == len(mail_events(engine, 'mail_consumed')) == 1
        assert not worker.results and worker.finished_revision is None
        assert not pm.pending and not pm.worker_report_reviews
    finally:
        await engine.close()
