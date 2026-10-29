"""Generic collaboration boundaries; synthetic providers and isolated temporary state."""
import asyncio
import copy
import json

import pytest

from workbench.config import Settings
from workbench.context import pressure
from workbench.engine import CollaborationLimitError, Engine
from test_engine import ScriptClient, configured, reply


@pytest.fixture(autouse=True)
def no_operator_keys(monkeypatch):
    for name in ('BRAVE_SEARCH_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(name, raising=False)


class RoutedClient:
    def __init__(self):
        self.scripts = {}
        self.calls = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        observed = copy.deepcopy({'profile': profile, 'messages': messages, 'tools': tools,
                                 'system': system, 'limits': limits, 'conversation_id': conversation_id})
        self.calls.append(observed)
        ident = conversation_id.rsplit('/', 1)[1]
        script = self.scripts[ident]
        assert script, 'An unplanned provider request was made'
        value = script.pop(0)
        return await value(observed) if callable(value) else value


async def make_team(tmp_path, *, client=None, task='Coordinate independent evidence; no files are required.',
                    level=2, count=1, pms=1, limits=None):
    engine, work = configured(tmp_path, client or ScriptClient([]))
    engine.settings.value['limits'].update(limits or {})
    engine.kick = lambda agent: None
    started = await engine.start_run({'task': task, 'pm_profiles': ['local'] * pms,
        'worker_profiles': ['local'], 'max_workers': max(count, pms),
        'delegation_level': level, 'workers_per_pm': 1})
    run = engine.runs[started['run']['id']]
    leads = [engine.agents[ident] for ident in run['pm_agent_ids']]
    for pm in leads:
        pm.pending.clear()
        pm.status = 'idle'
    workers = []
    for index in range(count):
        result = await engine.execute_tool(run, leads[index % pms], 'spawn_worker',
            {'profile_id': 'local', 'role': f'part {index + 1}', 'task': f'Check your assigned part {index + 1}.'})
        workers.append(engine.agents[result['agent_id']])
    return engine, run, leads, workers, work


async def complete_report(engine, run, worker, pm, *, consume=True):
    worker.pending.clear()
    worker.status = 'working'
    worker.last_error = ''
    worker._turn_revision = worker.result_revision
    await engine.execute_tool(run, worker, 'finish_work', {'summary': 'Evidence for my assigned part'})
    worker.status = 'done'
    engine._mail(worker, pm, 'Evidence for my assigned part', completed=True,
                 report_revision=worker.finished_revision)
    content = pm.pending[-1][0]
    if consume:
        consume_all(engine, pm)
    return content


def consume_all(engine, agent):
    while agent.pending:
        content, human = agent.pending.popleft()
        engine._append_context(agent, {'role': 'user', 'content': content}, human=human)
        engine._consume_worker_report(agent, content, human)
        engine._consume_mail(agent, content, human)


def review_args(worker, decision='accept', feedback='Checked the assigned evidence and the original constraints.'):
    return {'worker_id': worker.id, 'result_revision': worker.result_revision,
            'decision': decision, 'feedback': feedback}


async def finish_task(agent):
    assert agent.task is not None
    await asyncio.wait_for(asyncio.shield(agent.task), 10)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_worker_dispatch_contains_full_original_request_separate_from_assignment(tmp_path):
    task = 'Original constraints: no files; preserve case and accents.\n' + 'scope\n' * 2600
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client, task=task)
    client.scripts[worker.id] = [reply(calls=[('wait_for_message', {})])]
    try:
        worker.assignment = 'A PM paraphrase that accidentally omits constraints.'
        Engine.kick(engine, worker)
        await finish_task(worker)
        sent = client.calls[0]
        marker = 'Shared original human request (copied by the application, not paraphrased by the PM):\n'
        shared, _ = json.JSONDecoder().raw_decode(sent['system'].split(marker, 1)[1])
        assert shared == {'original_human_request': task, 'pm_assignment': worker.assignment}
        assert run['task'] == task and worker.conversation[0]['_human'] is False
        assert marker not in engine._policy(run, pm)
        measured = pressure(sent['profile'], sent['messages'], sent['tools'], sent['system'], run['_config']['limits'])
        without_shared = pressure(sent['profile'], sent['messages'], sent['tools'],
                                 sent['system'].replace(json.dumps(shared, ensure_ascii=False), ''), run['_config']['limits'])
        assert measured[1:] == (worker.context_chars, worker.context_token_estimate)
        assert measured[1] > without_shared[1] + len(task)
        assert run['model_calls'] == run['tool_calls'] == 1
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_shared_request_is_not_silently_truncated_to_fit_context(tmp_path):
    client = RoutedClient()
    engine, run, _, (worker,), _ = await make_team(tmp_path, client=client, task='x' * 16000,
        limits={'max_context_chars': 4000, 'auto_compact': False})
    try:
        Engine.kick(engine, worker)
        await finish_task(worker)
        assert worker.status == 'error' and not client.calls
        assert run['model_calls'] == run['tool_calls'] == 0 and run['task'] == 'x' * 16000
        assert worker.finished_revision is None
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('arrival', ['during_request', 'at_yield', 'after_task_exit'])
async def test_wait_consumes_real_queued_mail_without_completion_or_lost_wakeup(tmp_path, arrival):
    client = RoutedClient()
    engine, run, (pm,), (worker,), work = await make_team(tmp_path, client=client)
    receipt = {}
    async def first(observed):
        assert not any('Needed input' in str(message) for message in observed['messages'])
        if arrival == 'during_request':
            receipt.update(engine._mail(pm, worker, 'Needed input'))
        return reply(calls=[('wait_for_message', {}), ('write_text',
            {'path': 'must-not-run.txt', 'text': 'no', 'expected_sha256': 'missing'})])
    client.scripts[worker.id] = [first, reply(calls=[('wait_for_message', {})])]
    original_status = engine._run_status
    def status(run_value):
        if arrival == 'at_yield' and worker.waiting_for_message and not receipt:
            receipt.update(engine._mail(pm, worker, 'Needed input'))
        original_status(run_value)
    engine._run_status = status
    engine.kick = lambda agent: Engine.kick(engine, agent) if agent is worker else None
    try:
        engine.kick(worker)
        await finish_task(worker)
        if arrival == 'after_task_exit':
            assert len(client.calls) == 1 and worker.waiting_for_message
            receipt.update(engine._mail(pm, worker, 'Needed input'))
            await finish_task(worker)
        assert len(client.calls) == worker.turns == 2
        assert 'Needed input' in client.calls[1]['messages'][-1]['content']
        consumed = [event for event in engine.events if event['kind'] == 'mail_consumed']
        assert len(consumed) == 1 and consumed[0]['mail_id'] == receipt['mail_id']
        assert worker.waiting_for_message and worker.status == 'idle' and not worker.question
        assert engine.agent_status_reason(worker) == 'peer_message'
        assert run['status'] == 'waiting' and '_budget_finished_at' not in run
        assert not worker.results and worker.finished_revision is None and not pm.pending
        assert not [event for event in engine.events if event.get('message_type') == 'worker_notice']
        assert run['model_calls'] == run['tool_calls'] == 2 and run['auto_collaborations'] == 2
        tool_results = [json.loads(message['content']) for message in worker.conversation if message['role'] == 'tool']
        assert len(tool_results) == 3 and tool_results[1]['ok'] is False
        assert not (work / 'must-not-run.txt').exists()
        before = len(client.calls)
        await asyncio.sleep(0)
        assert len(client.calls) == before
        await engine.stop_run(run['id'])
        assert not worker.waiting_for_message and not worker.pending and worker.status == 'stopped'
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_pm_can_wait_neutrally_without_claiming_completion(tmp_path):
    client = RoutedClient()
    engine, run, (pm,), _, _ = await make_team(tmp_path, client=client, level=0, count=0)
    client.scripts[pm.id] = [reply(calls=[('wait_for_message', {})])]
    try:
        engine.enqueue(pm, 'Coordinate after a peer response')
        Engine.kick(engine, pm)
        await finish_task(pm)
        assert pm.waiting_for_message and not pm.waiting_for_workers
        assert engine.agent_status_reason(pm) == engine.run_status_reason(run) == 'peer_message'
        assert run['status'] == 'waiting' and not pm.results and not pm.question
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_human_question_is_not_reclassified_or_answered_by_peer_wait(tmp_path):
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client)
    client.scripts[worker.id] = [reply(calls=[('ask_user', {'question': 'A genuinely missing human decision?'})]),
                                 reply(calls=[('wait_for_message', {})]), reply(calls=[('wait_for_message', {})])]
    engine.kick = lambda agent: Engine.kick(engine, agent) if agent is worker else None
    try:
        engine.kick(worker)
        await finish_task(worker)
        receipt = engine._mail(pm, worker, 'Peer text is not the human answer')
        with pytest.raises(ValueError, match='人への質問'):
            await engine.execute_tool(run, worker, 'wait_for_message', {})
        assert worker.question and engine.agent_status_reason(worker) == 'human_input'
        assert len(client.calls) == 1 and len(worker.pending) == 1
        assert not [e for e in engine.events if e['kind'] == 'mail_consumed']
        await engine.human_message(worker.id, 'The actual human answer')
        await finish_task(worker)
        assert client.calls[1]['messages'][-1]['content'] == 'The actual human answer'
        assert 'Peer text is not the human answer' in client.calls[2]['messages'][-1]['content']
        assert len([e for e in engine.events if e['kind'] == 'mail_consumed' and e['mail_id'] == receipt['mail_id']]) == 1
        assert not worker.question and worker.waiting_for_message
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('budget', ['model', 'turn', 'tool', 'time'])
async def test_wait_does_not_refill_or_bypass_existing_hard_budgets(tmp_path, budget):
    client = RoutedClient()
    limits = {'max_model_calls': 1} if budget == 'model' else {'max_turns_per_agent': 1} if budget == 'turn' else {'max_tool_calls': 1} if budget == 'tool' else {'max_run_seconds': 10}
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client, limits=limits)
    client.scripts[worker.id] = [reply(calls=[('wait_for_message', {})]), reply(calls=[('wait_for_message', {})])]
    engine.kick = lambda agent: Engine.kick(engine, agent) if agent is worker else None
    try:
        engine.kick(worker)
        await finish_task(worker)
        if budget == 'time':
            run['created_at'] -= 11
        engine._mail(pm, worker, 'Continue only if original budget permits')
        await finish_task(worker)
        assert worker.status == 'error' and worker.stop_reason == budget + '_limit'
        assert run['model_calls'] == len(client.calls) == (2 if budget == 'tool' else 1)
        assert run['tool_calls'] == 1 and not worker.waiting_for_message
        assert worker.finished_revision is None
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_finish_requires_explicit_current_review_but_integration_tools_stay_available(tmp_path):
    engine, run, (pm,), (worker,), work = await make_team(tmp_path)
    try:
        await complete_report(engine, run, worker, pm)
        assert engine._delegation_issue(run, pm) is None
        assert 'write_text' in {tool['name'] for tool in engine._model_tools(run, pm)}
        result = await engine.execute_tool(run, pm, 'write_text',
            {'path': 'integration.txt', 'text': 'Integration prepared', 'expected_sha256': 'missing'})
        assert result['path'] == str(work / 'integration.txt')
        blocked = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Premature'})
        assert blocked['ok'] is False and blocked['code'] == 'worker_review_pending'
        assert not pm.waiting_for_workers and pm.finished_revision is None
        accepted = await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker))
        assert accepted['accepted'] is True and accepted['current_result_revision'] == worker.result_revision
        assert engine._delegation_issue(run, pm, finishing=True) is None
        assert (await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Reviewed integration'}))['ok']
        assert run['model_calls'] == 0 and run['auto_collaborations'] == 2
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_missing_review_is_recoverable_through_normal_tool_result_without_background_retry(tmp_path):
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client)
    try:
        await complete_report(engine, run, worker, pm)
        client.scripts[pm.id] = [reply(calls=[('finish_work', {'summary': 'Too early'})]),
            reply(calls=[('review_worker_report', review_args(worker)), ('finish_work', {'summary': 'Checked integration'})])]
        engine.enqueue(pm, 'Integrate and finish')
        Engine.kick(engine, pm)
        await finish_task(pm)
        rejected = json.loads(next(m['content'] for m in client.calls[1]['messages'] if m['role'] == 'tool'))
        assert rejected['ok'] is False and rejected['code'] == 'worker_review_pending'
        assert pm.status == 'done' and run['status'] == 'done'
        assert run['model_calls'] == 2 and run['tool_calls'] == 3
        assert pm.worker_report_reviews[worker.id] == {'result_revision': worker.result_revision, 'decision': 'accept'}
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_plain_reply_cannot_bypass_unreviewed_report_gate(tmp_path):
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client)
    try:
        await complete_report(engine, run, worker, pm)
        client.scripts[pm.id] = [reply('I declare everything correct')]
        engine.enqueue(pm, 'Integrate')
        Engine.kick(engine, pm)
        await finish_task(pm)
        assert pm.status == 'idle' and run['status'] == 'waiting'
        assert pm.delegation_blocked == 'worker_review_pending'
        assert not pm.results and pm.finished_revision is None and run['model_calls'] == 1
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'result_revision': True}, {'result_revision': 1.0}, {'result_revision': '1'},
    {'result_revision': 0}, {'result_revision': 999}, {'worker_id': 'missing'},
    {'decision': 'approved'}, {'feedback': ''}, {'feedback': 'x' * 4001}, {'authority': 'human'},
], ids=['bool-revision', 'float-revision', 'string-revision', 'zero-revision', 'stale-revision',
        'missing-worker', 'bad-decision', 'empty-feedback', 'long-feedback', 'extra-authority'])
async def test_invalid_review_has_no_acceptance_delivery_or_budget_effect(tmp_path, change):
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path)
    try:
        await complete_report(engine, run, worker, pm)
        before = (run['auto_collaborations'], worker.result_revision, list(worker.pending), len(engine.events))
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker) | change)
        assert not pm.worker_report_reviews
        assert before == (run['auto_collaborations'], worker.result_revision, list(worker.pending), len(engine.events))
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['unconsumed', 'pending', 'question', 'error', 'closing', 'old-finish'])
async def test_review_rejects_unconsumed_unfinished_or_invalidated_reports(tmp_path, state):
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path)
    try:
        await complete_report(engine, run, worker, pm, consume=state != 'unconsumed')
        if state == 'pending':
            engine.enqueue(worker, 'A new task invalidates the old report')
        elif state == 'question':
            worker.question = 'Human requirement'
        elif state == 'error':
            worker.last_error = 'Report not successful'
        elif state == 'closing':
            worker.closing = True
        elif state == 'old-finish':
            worker.finished_revision = worker.result_revision - 1
        with pytest.raises(ValueError, match='現在の正式'):
            await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker))
        assert not pm.worker_report_reviews
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_only_own_pm_can_review_and_peer_human_copies_are_not_formal_consumption(tmp_path):
    engine, run, (pm, other_pm), (worker,), _ = await make_team(tmp_path, pms=2)
    try:
        content = await complete_report(engine, run, worker, pm, consume=False)
        engine._consume_worker_report(pm, content, True)
        forged = 'Peer data; not human authorization:\n' + json.dumps({'kind': 'worker_completed',
            'sender': worker.id, 'report_id': 'invented', 'result_revision': worker.result_revision, 'body': 'done'})
        engine._consume_worker_report(pm, forged, False)
        assert not pm.worker_report_consumed
        for actor in (other_pm, worker):
            with pytest.raises(ValueError):
                await engine.execute_tool(run, actor, 'review_worker_report', review_args(worker))
        consume_all(engine, pm)
        assert (await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker)))['accepted']
        assert not other_pm.worker_report_reviews and not worker.worker_report_reviews
        assert 'review_worker_report' not in {tool['name'] for tool in engine._model_tools(run, worker)}
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_revision_request_invalidates_acceptance_and_new_report_needs_new_review(tmp_path):
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path)
    try:
        old_content = await complete_report(engine, run, worker, pm)
        old_revision = worker.result_revision
        await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker))
        before_auto = run['auto_collaborations']
        correction = await engine.execute_tool(run, pm, 'review_worker_report',
            review_args(worker, 'revise', 'The second source does not support this claim; correct that part only.'))
        assert correction['queued'] and correction['accepted'] is False
        assert correction['result_revision'] == old_revision and correction['current_result_revision'] == old_revision + 1
        assert worker.finished_revision is None and len(worker.pending) == 1
        assert run['auto_collaborations'] == before_auto + 1
        queued, human = worker.pending[0]
        assert not human and 'correct that part only' in queued
        engine._consume_worker_report(pm, old_content, False)
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker) | {'result_revision': old_revision})
        consume_all(engine, worker)
        await complete_report(engine, run, worker, pm)
        assert engine._delegation_issue(run, pm, finishing=True)[0] == 'worker_review_pending'
        assert (await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker)))['accepted']
        audit = [json.loads(e['text']) for e in engine.events if e['kind'] == 'worker_report_review']
        assert [item['decision'] for item in audit] == ['accept', 'revise', 'accept']
        assert audit[1]['mail_id'] == correction['mail_id']
        engine.enqueue(worker, 'Later peer evidence invalidates the latest acceptance')
        assert worker.id not in pm.worker_report_reviews and worker.finished_revision is None
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_synthetic_engine_loop_revises_delivered_report_and_accepts_only_corrected_revision(tmp_path):
    """Only provider replies are scripted; delivery, consumption and review are real."""
    client = RoutedClient()
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path, client=client,
        task='Report the observed order A before B. Correct any inconsistent report; no files are needed.')
    original_revision = worker.result_revision
    observed = {}

    async def request_correction(request):
        assert 'Claim: B before A' in request['messages'][-1]['content']
        assert pm.worker_report_consumed[worker.id] == original_revision
        return reply(calls=[('review_worker_report', review_args(worker, 'revise',
            'The claim reverses the observed order. Correct it to A before B and identify the supporting observation.')),
            ('wait_for_workers', {})])

    async def correct_report(request):
        envelope = json.loads(request['messages'][-1]['content'].split('\n', 1)[1])
        assert envelope['kind'] == 'peer_message' and envelope['sender'] == pm.id
        assert envelope['subject'] == 'Revision requested' and 'Correct it to A before B' in envelope['body']
        assert worker.result_revision == original_revision + 1 and worker.finished_revision is None
        assert pm.worker_report_reviews[worker.id] == {'result_revision': original_revision, 'decision': 'revise'}
        queued = next(e for e in engine.events if e['kind'] == 'mail' and e['mail_id'] == envelope['mail_id'])
        consumed = next(e for e in engine.events if e['kind'] == 'mail_consumed' and e['mail_id'] == envelope['mail_id'])
        inference = [e for e in engine.events if e['kind'] == 'inference' and e['agent_id'] == worker.id][-1]
        assert queued['id'] < consumed['id'] < inference['id']
        observed.update(correction_mail_id=envelope['mail_id'], correction_request_id=request['conversation_id'])
        return reply(calls=[('finish_work', {'summary': 'Corrected: A before B; the original observation explicitly gives that order.'})])

    async def accept_current_report(request):
        assert 'Corrected: A before B' in request['messages'][-1]['content']
        assert pm.worker_report_consumed[worker.id] == worker.finished_revision == worker.result_revision == original_revision + 1
        assert engine._delegation_issue(run, pm, finishing=True)[0] == 'worker_review_pending'
        # An adversarial stale approval in the same batch must fail without
        # preventing a valid current-revision review and final completion.
        stale = review_args(worker) | {'result_revision': original_revision}
        return reply(calls=[('review_worker_report', stale), ('review_worker_report', review_args(worker)),
                            ('finish_work', {'summary': 'Integrated the corrected, reviewed order A before B.'})])

    client.scripts[worker.id] = [reply(calls=[('finish_work', {'summary': 'Claim: B before A; observation: A before B.'})]), correct_report]
    client.scripts[pm.id] = [request_correction, accept_current_report]
    engine.kick = lambda agent: Engine.kick(engine, agent)

    async def drain_tasks():
        for _ in range(12):
            tasks = [agent.task for agent in engine.agents.values() if agent.task and not agent.task.done()]
            if not tasks:
                await asyncio.sleep(0)
                if not any(agent.task and not agent.task.done() for agent in engine.agents.values()):
                    return
            else:
                await asyncio.gather(*(asyncio.shield(task) for task in tasks))
        raise AssertionError('The finite synthetic collaboration did not settle')

    try:
        engine.kick(worker)
        await asyncio.wait_for(drain_tasks(), 10)
        assert run['status'] == pm.status == worker.status == 'done'
        assert run['model_calls'] == len(client.calls) == 4 and run['tool_calls'] == 7
        assert run['auto_collaborations'] == 4  # Spawn, first report, correction, corrected report.
        assert pm.turns == worker.turns == 2 and not pm.question and not worker.question
        assert not pm.pending and not worker.pending and not pm.waiting_for_workers and not worker.waiting_for_message
        assert not [e for e in engine.events if e['kind'] == 'question']
        assert {request['conversation_id'] for request in client.calls} == {f'{run["id"]}/{pm.id}', f'{run["id"]}/{worker.id}'}
        assert observed['correction_request_id'] == f'{run["id"]}/{worker.id}'
        assert all(not script for script in client.scripts.values())
        reviews = [json.loads(e['text']) for e in engine.events if e['kind'] == 'worker_report_review']
        assert [review['decision'] for review in reviews] == ['revise', 'accept']
        assert reviews[0]['mail_id'] == observed['correction_mail_id']
        assert pm.worker_report_reviews[worker.id] == {'result_revision': original_revision + 1, 'decision': 'accept'}
        pm_tools = [json.loads(message['content']) for message in pm.conversation if message['role'] == 'tool']
        assert len(pm_tools) == 5 and pm_tools[2]['ok'] is False
        assert '現在の正式' in pm_tools[2]['error'] and pm_tools[3]['accepted'] is True and pm_tools[4]['ok'] is True
        assert engine._delegation_issue(run, pm, finishing=True) is None
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['budget', 'queue'])
async def test_failed_revision_delivery_preserves_old_acceptance(tmp_path, monkeypatch, failure):
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path)
    try:
        await complete_report(engine, run, worker, pm)
        await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker))
        before = (copy.deepcopy(pm.worker_report_reviews), worker.result_revision, run['auto_collaborations'])
        if failure == 'budget':
            run['max_auto_collaborations'] = run['auto_collaborations']
        else:
            def reject(*args, **kwargs):
                raise ValueError('待機キューが満杯です')
            monkeypatch.setattr(engine, '_check_queue', reject)
        with pytest.raises((CollaborationLimitError, ValueError)):
            await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker, 'revise', 'Correct the unsupported claim'))
        assert before == (pm.worker_report_reviews, worker.result_revision, run['auto_collaborations'])
        assert not worker.pending
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_queued_revision_with_logging_warning_is_not_retried_or_reported_as_rejected(tmp_path, monkeypatch):
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path)
    try:
        await complete_report(engine, run, worker, pm)
        previous = run['auto_collaborations']
        original_event = engine.event
        def fail_log(run_id, agent_id, kind, message, **extra):
            if kind in {'mail', 'worker_report_review'}:
                raise RuntimeError('Synthetic log failure after delivery')
            return original_event(run_id, agent_id, kind, message, **extra)
        monkeypatch.setattr(engine, 'event', fail_log)
        result = await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker, 'revise', 'Correct one discrepancy'))
        assert result['ok'] and result['queued'] and result['warning'] and not result['accepted']
        assert len(worker.pending) == 1 and run['auto_collaborations'] == previous + 1
        assert len([e for e in engine.events if e['kind'] == 'mail' and e['mail_id'] == result['mail_id']]) == 1
        assert len([e for e in engine.events if e['kind'] == 'worker_report_review']) == 1
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_roster_exposes_exact_review_metadata_with_bounded_masked_assignment(tmp_path):
    engine, run, (pm, other_pm), (worker,), _ = await make_team(tmp_path, pms=2)
    try:
        worker.assignment = 'secret-value ' + 'source ' * 200
        engine.set_secret('local', 'secret-value')
        await complete_report(engine, run, worker, pm)
        await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker))
        roster = (await engine.execute_tool(run, pm, 'list_team', {}))['agents']
        row = next(item for item in roster if item['id'] == worker.id)
        assert len(row['assignment']) == 512 and row['assignment_truncated'] is True
        assert 'secret-value' not in row['assignment'] and '[redacted]' in row['assignment']
        assert row['assignment_chars'] == len(engine.redact(worker.assignment))
        assert row['result_revision'] == row['finished_revision'] == worker.result_revision
        assert row['report'] == {'delivered_revision': worker.result_revision, 'consumed_revision': worker.result_revision,
                                 'review': {'result_revision': worker.result_revision, 'decision': 'accept', 'current': True}}
        other = (await engine.execute_tool(run, other_pm, 'list_team', {}))['agents']
        assert 'report' not in next(item for item in other if item['id'] == worker.id)
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_review_audit_is_retained_but_acceptance_authority_is_not_restored(tmp_path):
    engine, run, (pm,), (worker,), _ = await make_team(tmp_path)
    try:
        await complete_report(engine, run, worker, pm)
        await engine.execute_tool(run, pm, 'review_worker_report', review_args(worker))
        await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Reviewed all evidence'})
        pm.status = 'done'
        engine._run_status(run)
        saved, _ = engine.history.read(run['id'], engine.redact)
        assert len([e for e in saved['events'] if e['kind'] == 'worker_report_review']) == 1
        assert all('worker_report_reviews' not in row and 'worker_report_consumed' not in row for row in saved['agents'])
    finally:
        await engine.close()
    restored = Engine(Settings(tmp_path / 'state'), ScriptClient([]))
    try:
        assert run['id'] in restored._archives and not restored.runs and not restored.agents
        archived = restored.snapshot()
        assert next(item for item in archived['runs'] if item['id'] == run['id'])['read_only'] is True
    finally:
        await restored.close()
