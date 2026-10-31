"""Bounded formation domain and native evidence provenance. Synthetic providers only."""
import copy

import pytest

from workbench.formation import FormationError
from test_engine import ScriptClient, configured, reply, settled, start
from test_worker_dependencies import consume


def plan(difficulty='low', **changes):
    count = {'low': 1, 'medium': 2, 'high': 3}[difficulty]
    return {'difficulty': difficulty, 'reason': 'Concrete bounded author assignments.',
        'reviewer_profile_id': 'local', 'assignments': [
            {'key': f'part{i}', 'role': 'author', 'task': 'Read the assigned facts and report verified results.',
             'profile_id': 'local', **({'depends_on': [f'part{i - 1}']} if i else {})}
            for i in range(count)], **changes}


def activate(engine, actor):
    engine._dependency_begin(actor)
    consume(engine, actor)
    actor._turn_revision = actor.result_revision
    actor.status = 'working'


@pytest.fixture
async def manual(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.settings.value['limits']['max_workers'] = 8
    engine.kick = lambda actor: None
    run, pm = await start(engine, adaptive_team=True, max_workers=4, delegation_level=2, workers_per_pm=8)
    activate(engine, pm)
    try:
        yield engine, work, run, pm
    finally:
        await engine.close()


async def accepted_author(manual):
    engine, work, run, pm = manual
    await engine.execute_tool(run, pm, 'plan_team', plan())
    author = engine.agents[run['formation']['worker_ids'][0]]
    activate(engine, author)
    await engine.execute_tool(run, author, 'finish_work', {'summary': 'The assigned facts were checked.'})
    author.status = 'done'
    engine._mail(author, pm, 'The assigned facts were checked.', completed=True, report_revision=author.finished_revision)
    activate(engine, pm)
    await engine.execute_tool(run, pm, 'review_worker_report', {'worker_id': author.id,
        'result_revision': author.result_revision, 'decision': 'accept', 'feedback': 'Checked current evidence.'})
    return author


@pytest.mark.parametrize('change', [
    {'assignments': []}, {'difficulty': 'automatic'}, {'reviewer_profile_id': 'not-allowed'},
    {'assignments': [{'key': 'part0', 'role': 'x', 'task': 'x', 'profile_id': 'local', 'depends_on': ['later']}]},
])
async def test_invalid_plan_has_no_agent_or_budget_side_effect(manual, change):
    engine, _, run, pm = manual
    before = (list(run['agent_ids']), run['auto_collaborations'], run['model_calls'], run['tool_calls'])
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'plan_team', {**plan(), **change})
    assert (run['agent_ids'], run['auto_collaborations'], run['model_calls'], run['tool_calls']) == before
    assert run['formation']['phase'] == 'unplanned'


async def test_fixed_count_includes_separate_reviewer_and_preserves_manual_saved_policy(manual):
    engine, _, run, pm = manual
    saved = copy.deepcopy(engine.settings.value)
    receipt = await engine.execute_tool(run, pm, 'plan_team', plan('high'))
    assert receipt['ok'] and len(run['formation']['worker_ids']) == 3
    reviewer = engine.agents[run['formation']['reviewer_id']]
    assert reviewer.parent_id is None and reviewer.id not in run['pm_agent_ids']
    assert reviewer.kind == 'independent_reviewer' and run['auto_collaborations'] == 4
    assert engine.settings.value == saved
    author = engine.agents[run['formation']['worker_ids'][0]]
    activate(engine, author)
    with pytest.raises(ValueError, match='最大 worker'):
        await engine.execute_tool(run, author, 'spawn_worker', {'role': 'extra', 'task': 'no extra slot', 'profile_id': 'local'})


async def test_adaptive_pm_delegation_metadata_matches_fixed_plan_with_descendant_room(manual):
    engine, _, run, pm = manual
    await engine.execute_tool(run, pm, 'plan_team', plan())
    author = engine.agents[run['formation']['worker_ids'][0]]
    activate(engine, author)
    rows = {row['id']: row for row in engine.snapshot()['agents']}
    assert rows[pm.id]['hierarchy']['can_delegate'] is False
    assert rows[author.id]['hierarchy']['can_delegate'] is True
    before = list(run['agent_ids'])
    with pytest.raises(FormationError) as error:
        await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'extra direct author',
            'task': 'The fixed plan cannot add another direct author.', 'profile_id': 'local'})
    assert error.value.code == 'formation_fixed_workers'
    assert run['agent_ids'] == before
    spawned = await engine.execute_tool(run, author, 'spawn_worker', {'role': 'child author',
        'task': 'Use a remaining shared slot for a child assignment.', 'profile_id': 'local'})
    assert engine.agents[spawned['agent_id']].parent_id == author.id
    assert len(run['agent_ids']) - len(run['pm_agent_ids']) == 3 <= run['max_workers']


async def test_plan_committed_notification_failure_is_not_retryable(manual, monkeypatch):
    engine, _, run, pm = manual
    with monkeypatch.context() as patch:
        patch.setattr(engine, 'event', lambda *a, **kw: (_ for _ in ()).throw(OSError('synthetic event failure')))
        receipt = await engine.execute_tool(run, pm, 'plan_team', plan())
    assert receipt['ok'] and receipt['warning']
    assert len(run['agent_ids']) == 3 and run['auto_collaborations'] == 2
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'plan_team', plan())
    assert len(run['agent_ids']) == 3 and run['auto_collaborations'] == 2


async def test_request_checks_whole_receipt_history_and_does_not_spend_invalid_candidate(manual):
    engine, _, run, pm = manual
    author = await accepted_author(manual)
    author.receipts_omitted = 1
    before = run['auto_collaborations']
    with pytest.raises(FormationError) as error:
        await engine.execute_tool(run, pm, 'request_independent_review', {'summary': 'Summary', 'artifact_paths': []})
    assert error.value.code == 'review_receipts_omitted'
    assert run['formation']['candidate_count'] == 0 and run['auto_collaborations'] == before


async def test_candidate_limit_is_lifetime_and_author_input_does_not_refund(manual):
    engine, _, run, pm = manual
    await accepted_author(manual)
    candidate_ids = []
    for index in range(3):
        receipt = await engine.execute_tool(run, pm, 'request_independent_review',
            {'summary': f'Candidate {index}', 'artifact_paths': []})
        candidate_ids.append(receipt['candidate']['id'])
        assert receipt['candidate']['summary_only']
        reviewer = engine.agents[run['formation']['reviewer_id']]
        # This domain fixture consumes an assignment without producing a verdict.
        # No model exposure or correctness is claimed by this transition.
        activate(engine, reviewer)
        reviewer.status = 'idle'
        engine.enqueue(pm, 'Explicitly reconsider this candidate.', human=True)
        activate(engine, pm)
        assert run['formation']['phase'] == 'stale'
    before = run['auto_collaborations']
    with pytest.raises(FormationError) as error:
        await engine.execute_tool(run, pm, 'request_independent_review', {'summary': 'Fourth', 'artifact_paths': []})
    assert error.value.code == 'review_candidate_limit'
    assert len(set(candidate_ids)) == 3 and run['formation']['candidate_count'] == 3
    assert run['auto_collaborations'] == before


async def test_request_postcommit_save_failure_is_accepted_once(manual, monkeypatch):
    engine, _, run, pm = manual
    await accepted_author(manual)
    with monkeypatch.context() as patch:
        patch.setattr(engine, '_persist_run', lambda *a: (_ for _ in ()).throw(OSError('synthetic save failure')))
        receipt = await engine.execute_tool(run, pm, 'request_independent_review', {'summary': 'Summary', 'artifact_paths': []})
    assert receipt['ok'] and receipt['warning'] and run['formation']['candidate_count'] == 1
    reviewer = engine.agents[run['formation']['reviewer_id']]
    assert len(reviewer.pending) == 1
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'request_independent_review', {'summary': 'Summary', 'artifact_paths': []})
    assert run['formation']['candidate_count'] == 1 and len(reviewer.pending) == 1


async def test_direct_content_tool_execution_is_not_model_consumption(manual):
    engine, work, run, pm = manual
    await accepted_author(manual)
    source = work / 'evidence.txt'
    source.write_text('A source fact.', encoding='utf-8')
    await engine.execute_tool(run, pm, 'request_independent_review', {'summary': 'A source fact.', 'artifact_paths': [str(source)]})
    pm.status = 'idle'
    reviewer = engine.agents[run['formation']['reviewer_id']]
    activate(engine, reviewer)
    result = await engine.execute_tool(run, reviewer, 'read_text', {'path': str(source)})
    assert result['text'] == 'A source fact.'
    with pytest.raises(FormationError) as error:
        await engine.execute_tool(run, reviewer, 'submit_independent_review', {'candidate_id': run['formation']['candidate']['id'],
            'decision': 'accept', 'feedback': 'Direct execution is not a provider request.'})
    assert error.value.code == 'review_not_presented'
    assert run['formation']['candidate']['consumed_read_count'] == 0


class ExposureClient:
    def __init__(self, source):
        self.engine = None
        self.source = source
        self.review_calls = 0
        self.exposed = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        engine = self.engine
        run = next(iter(engine.runs.values()))
        actor = engine.agents[conversation_id.split('/')[-1]]
        if actor.kind == 'independent_reviewer':
            self.review_calls += 1
            self.exposed.append(copy.deepcopy(messages))
            if self.review_calls == 1:
                return reply(calls=[('read_text', {'path': str(self.source)})])
            if self.review_calls == 2:
                return reply(calls=[('submit_independent_review', {'candidate_id': run['formation']['candidate']['id'],
                    'decision': 'accept', 'feedback': 'Trying to accept after the source record was removed.'})])
            return reply('No current native evidence; cannot provide a verdict.')
        if actor.parent_id:
            return reply(calls=[('finish_work', {'summary': 'The evidence was checked.'})])
        if run['formation']['phase'] == 'unplanned':
            return reply(calls=[('plan_team', plan())])
        child = engine.agents[run['formation']['worker_ids'][0]]
        if child.status != 'done' or actor.worker_report_consumed.get(child.id) != child.result_revision:
            return reply(calls=[('wait_for_workers', {})])
        if actor.worker_report_reviews.get(child.id, {}).get('decision') != 'accept':
            return reply(calls=[('review_worker_report', {'worker_id': child.id, 'result_revision': child.result_revision,
                'decision': 'accept', 'feedback': 'Checked report.'})])
        return reply(calls=[('request_independent_review', {'summary': 'A source fact.', 'artifact_paths': [str(self.source)]})])


@pytest.mark.parametrize('replacement', ['drop', 'copied_user_text', 'copied_record'])
async def test_post_compaction_requires_original_native_result_identity(tmp_path, replacement):
    client = ExposureClient(None)
    engine, work = configured(tmp_path, client)
    client.engine = engine
    client.source = work / 'evidence.txt'
    client.source.write_text('A source fact.', encoding='utf-8')
    original = engine._ensure_context

    async def remove_raw(run, actor, profile, tools, limits):
        await original(run, actor, profile, tools, limits)
        if actor.kind != 'independent_reviewer' or client.review_calls != 1:
            return
        evidence = next(iter(run['_formation']['reads'].values()), None)
        if evidence is None:
            return
        tool_record = evidence['record']
        call_record = next(record for record in actor.conversation if record.get('role') == 'assistant'
            and any(call is evidence['call'] for call in record.get('tool_calls', [])))
        actor.conversation = [record for record in actor.conversation if record is not tool_record and record is not call_record]
        if replacement == 'copied_user_text':
            engine._append_context(actor, {'role': 'user', 'content': tool_record['content']})
        elif replacement == 'copied_record':
            actor.conversation.extend([copy.deepcopy(call_record), copy.deepcopy(tool_record)])

    engine._ensure_context = remove_raw
    try:
        run, pm = await start(engine, adaptive_team=True)
        await settled(engine)
        assert client.review_calls >= 2
        assert run['formation']['candidate']['decision'] is None
        assert run['formation']['candidate']['consumed_read_count'] == 0
        assert run['status'] == 'waiting' and pm.finished_revision is None
    finally:
        await engine.close()
