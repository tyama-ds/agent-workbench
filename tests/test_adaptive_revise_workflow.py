"""A bounded native revision round, using deterministic synthetic responses.

The first synthetic author deliberately writes the wrong fixture value. The
separate reviewer requests correction; only actual native tools may repair,
report, approve and finish. No model quality or external inference is claimed.
"""
import copy
import hashlib
import json

from test_adaptive_workflow import joined
from test_engine import configured, reply


TASK = 'Save result.txt containing exactly value=43, then independently verify the saved file.'
INITIAL = 'value=42\n'
CORRECTED = 'value=43\n'
FIRST_SUMMARY = 'The first candidate file is saved and awaits independent checking.'
FINAL = 'Saved result.txt containing value=43 and independently reviewed its current bytes.'
REASSIGN = 'Correct result.txt to exactly value=43. Read its current bytes, save the correction, and submit a new formal report.'
CAPS = {'max_model_calls': 24, 'max_tool_calls': 60,
        'max_auto_collaborations': 24, 'max_run_seconds': 3600}


def last_result(messages, name):
    matches = [message for message in messages
               if message.get('role') == 'tool' and message.get('name') == name]
    assert matches, f'The actual {name} result must have entered this request.'
    return json.loads(matches[-1]['content'])


class RevisionProvider:
    def __init__(self):
        self.engine = None
        self.calls = []
        self.author_stage = 0
        self.review_stages = {}
        self.first_candidate_id = None
        self.second_candidate_id = None
        self.reassigned = False
        self.parent_probe_sent = False
        self.parent_probe_rejected = False
        self.old_verdict_rejected = False
        self.revise_control_consumed = False
        self.accept_control_consumed = False
        self.old_verdict_auto_before = None
        self.parent_probe_auto_before = None
        self.first_author_revision = None
        self.second_author_revision = None

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        run_id, agent_id = conversation_id.split('/')
        engine = self.engine
        run, actor = engine.runs[run_id], engine.agents[agent_id]
        assert run['task'] == TASK
        assert {name: run['_config']['limits'][name] for name in CAPS} == CAPS
        self.calls.append({'agent_id': agent_id, 'messages': copy.deepcopy(messages)})
        assert len(self.calls) <= CAPS['max_model_calls'], 'Unexpected retry loop in finite revision fixture.'
        if actor.id in run['pm_agent_ids']:
            return self.pm_reply(run, actor, messages)
        if actor.kind == 'independent_reviewer':
            return self.review_reply(run, actor, messages, system)
        return self.author_reply(messages)

    def pm_reply(self, run, pm, messages):
        formation = run['formation']
        if formation['phase'] == 'unplanned':
            return reply(calls=[('plan_team', {
                'difficulty': 'low', 'reason': 'One bounded text artifact and a separate independent reviewer.',
                'reviewer_profile_id': 'local', 'assignments': [{
                    'key': 'write', 'role': 'writer', 'profile_id': 'local',
                    'task': TASK}]})])
        candidate = formation['candidate']
        if formation['phase'] == 'accepted':
            assert candidate['round'] == 2 and candidate['id'] == self.second_candidate_id
            assert pm._review_control_candidate == candidate['id']
            assert any(candidate['id'] in message.get('content', '') and '"decision":"accept"' in message.get('content', '')
                       and message.get('_human') is False for message in messages)
            self.accept_control_consumed = True
            return reply(calls=[('finish_work', {'summary': FINAL})])
        if formation['phase'] == 'revise' and not self.reassigned:
            assert candidate['id'] == self.first_candidate_id and candidate['decision'] == 'revise'
            assert pm._review_control_candidate == candidate['id']
            assert any(candidate['id'] in message.get('content', '') and '"decision":"revise"' in message.get('content', '')
                       and message.get('_human') is False for message in messages)
            # The application control must not create a new authored revision.
            assert pm.result_revision == run['_formation']['candidate']['authors'][pm.id]['revision']
            self.revise_control_consumed = self.reassigned = True
            return reply(calls=[('send_message', {
                'to_agent_id': formation['worker_ids'][0], 'body': REASSIGN})])

        author = self.engine.agents[formation['worker_ids'][0]]
        if author.status != 'done' or pm.worker_report_consumed.get(author.id) != author.result_revision:
            return reply(calls=[('wait_for_workers', {})])
        current_approval = pm.worker_report_reviews.get(author.id) == {
            'result_revision': author.result_revision, 'decision': 'accept'}
        if self.reassigned and not current_approval and not self.parent_probe_sent:
            # The corrected report has really arrived, but its new revision has
            # not been approved. A previous parent approval must not suffice.
            assert author.finished_revision == author.result_revision
            assert author.result_revision != self.first_author_revision
            self.second_author_revision = author.result_revision
            self.parent_probe_sent = True
            self.parent_probe_auto_before = run['auto_collaborations']
            return reply(calls=[('request_independent_review', {
                'summary': FINAL, 'artifact_paths': ['result.txt']})])
        if self.parent_probe_sent and not self.parent_probe_rejected:
            assert last_result(messages, 'request_independent_review').get('ok') is False
            assert formation['candidate_count'] == 1 and candidate['id'] == self.first_candidate_id
            assert run['auto_collaborations'] == self.parent_probe_auto_before
            assert not current_approval
            self.parent_probe_rejected = True
        if not current_approval:
            if not self.reassigned:
                self.first_author_revision = author.result_revision
            return reply(calls=[('review_worker_report', {
                'worker_id': author.id, 'result_revision': author.result_revision,
                'decision': 'accept', 'feedback': 'The current formal report and native save receipt are recorded.'})])
        if formation['candidate_count'] == 0:
            assert formation['phase'] == 'working'
            return reply(calls=[('request_independent_review', {
                'summary': FIRST_SUMMARY, 'artifact_paths': []})])
        assert formation['phase'] == 'revise' and self.parent_probe_rejected
        assert author.result_revision == self.second_author_revision
        return reply(calls=[('request_independent_review', {
            'summary': FINAL, 'artifact_paths': []})])

    def author_reply(self, messages):
        stage = self.author_stage
        self.author_stage += 1
        if stage == 0:
            return reply(calls=[('write_text', {
                'path': 'result.txt', 'text': INITIAL, 'expected_sha256': 'missing'})])
        if stage == 1:
            assert last_result(messages, 'write_text')['sha256'] == hashlib.sha256(INITIAL.encode()).hexdigest()
            return reply(calls=[('finish_work', {'summary': 'Saved the first fixture candidate in result.txt.'})])
        if stage == 2:
            assert any(REASSIGN in message.get('content', '') and message.get('_human') is False
                       for message in messages)
            return reply(calls=[('read_text', {'path': 'result.txt'})])
        if stage == 3:
            observed = last_result(messages, 'read_text')
            assert observed['text'] == INITIAL
            return reply(calls=[('write_text', {
                'path': 'result.txt', 'text': CORRECTED, 'expected_sha256': observed['sha256']})])
        assert stage == 4, 'The author must not enter an unbounded correction loop.'
        assert last_result(messages, 'write_text')['sha256'] == hashlib.sha256(CORRECTED.encode()).hexdigest()
        return reply(calls=[('finish_work', {'summary': 'Corrected result.txt to value=43 with the current native save receipt.'})])

    def review_reply(self, run, actor, messages, system):
        candidate = run['formation']['candidate']
        ident, round_number = candidate['id'], candidate['round']
        assert round_number in (1, 2) and TASK in system
        assert (FIRST_SUMMARY if round_number == 1 else FINAL) in system
        stage = self.review_stages.get(ident, 0)
        self.review_stages[ident] = stage + 1
        if stage == 0:
            if round_number == 1:
                self.first_candidate_id = ident
            else:
                assert ident != self.first_candidate_id
                self.second_candidate_id = ident
            assert candidate['consumed_read_count'] == 0
            return reply(calls=[('read_text', {'path': 'result.txt'})])
        observed = last_result(messages, 'read_text')
        assert observed['independent_review_read']['candidate_id'] == ident
        assert candidate['consumed_read_count'] == 1
        if round_number == 1:
            assert stage == 1 and observed['text'] == INITIAL
            return reply(calls=[('submit_independent_review', {
                'candidate_id': ident, 'decision': 'revise',
                'feedback': 'The actual file contains value=42; the immutable original request requires value=43.'})])
        assert observed['text'] == CORRECTED
        if stage == 1:
            # Everything else is current and exposed. Only the candidate ID is
            # stale, so this checks identity rather than missing read evidence.
            self.old_verdict_auto_before = run['auto_collaborations']
            return reply(calls=[('submit_independent_review', {
                'candidate_id': self.first_candidate_id, 'decision': 'accept',
                'feedback': 'This obsolete candidate ID must be rejected.'})])
        assert stage == 2, 'The reviewer must not enter an unbounded retry loop.'
        assert last_result(messages, 'submit_independent_review').get('ok') is False
        assert candidate['decision'] is None and run['formation']['phase'] == 'reviewing'
        assert run['auto_collaborations'] == self.old_verdict_auto_before
        self.old_verdict_rejected = True
        return reply(calls=[('submit_independent_review', {
            'candidate_id': ident, 'decision': 'accept',
            'feedback': 'The current candidate content is value=43, matching the immutable original request.'})])


async def test_native_revise_correction_reapproval_and_current_candidate_finish(tmp_path):
    provider = RevisionProvider()
    engine, folder = configured(tmp_path, provider)
    engine.settings.value['limits'].update(CAPS)
    provider.engine = engine
    saved_settings = copy.deepcopy(engine.settings.value)
    try:
        created = await engine.start_run({'task': TASK, 'pm_profile': 'local',
            'worker_profiles': ['local'], 'max_workers': 2, 'adaptive_team': True})
        run = engine.runs[created['run']['id']]
        await joined(engine)
        assert run['status'] == 'done', [(agent.name, agent.status, agent.last_error) for agent in engine.agents.values()]
        assert provider.revise_control_consumed and provider.accept_control_consumed
        assert provider.parent_probe_rejected and provider.old_verdict_rejected
        assert provider.first_author_revision != provider.second_author_revision
        assert provider.first_candidate_id != provider.second_candidate_id
        formation, candidate = run['formation'], run['formation']['candidate']
        assert formation['phase'] == 'complete' and formation['candidate_count'] == candidate['round'] == 2
        assert candidate['id'] == provider.second_candidate_id and candidate['decision'] == 'accept'
        assert candidate['summary_sha256'] == hashlib.sha256(FINAL.encode()).hexdigest()
        assert candidate['artifact_count'] == candidate['read_count'] == candidate['consumed_read_count'] == 1
        assert (folder / 'result.txt').read_text(encoding='utf-8') == CORRECTED
        pm = engine.agents[run['pm_agent_ids'][0]]
        author = engine.agents[formation['worker_ids'][0]]
        assert pm.worker_report_reviews[author.id] == {
            'result_revision': provider.second_author_revision, 'decision': 'accept'}
        assert pm.finished_revision == pm.result_revision
        assert any(result['source'] == 'finish_work' and result['text'] == FINAL for result in pm.results)
        assert len(run['agent_ids']) == 3 and len(run['pm_agent_ids']) == 1
        assert run['model_calls'] == len(provider.calls) <= CAPS['max_model_calls']
        assert run['tool_calls'] <= CAPS['max_tool_calls']
        assert run['auto_collaborations'] == 9 <= CAPS['max_auto_collaborations']
        assert engine.settings.value == saved_settings and run['task'] == TASK
        assert not engine.history.error
        assert not any(agent.pending or agent.question or (agent.task and not agent.task.done())
                       for agent in engine.agents.values())
    finally:
        await engine.close()
    assert engine.closed and not engine._question_tasks
