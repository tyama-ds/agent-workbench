"""Actual Engine scheduling/tool/context path, with finite synthetic providers.

No inference or external network is performed. This checks execution order and
current artifact exposure, not the quality of a model's review judgment.
"""
import asyncio
import copy
import hashlib
import json

import pytest

from test_engine import configured, reply


FINAL = 'The requested local output was saved and reviewed against the source.'
CONTENT = 'source=fixture\nvalue=42\nverified=local bytes\n'


class WorkflowProvider:
    def __init__(self, same_batch=False):
        self.engine = None
        self.same_batch = same_batch
        self.calls = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        run_id, agent_id = conversation_id.split('/')
        engine = self.engine
        run, agent = engine.runs[run_id], engine.agents[agent_id]
        self.calls.append({'agent': agent_id, 'kind': agent.kind, 'messages': copy.deepcopy(messages),
                           'tools': [t['name'] for t in tools]})
        if len(self.calls) > 12:
            raise AssertionError('Unexpected inference loop in bounded workflow')
        formation = run['formation']
        if agent_id in run['pm_agent_ids']:
            if formation['phase'] == 'unplanned':
                return reply(calls=[('plan_team', {'difficulty': 'low', 'reason': 'One local text output',
                    'reviewer_profile_id': 'local', 'assignments': [{'key': 'write', 'role': 'writer',
                        'task': 'Save result.txt and report its current bytes.', 'profile_id': 'local'}]})])
            if formation['phase'] == 'accepted':
                return reply(calls=[('finish_work', {'summary': FINAL})])
            workers = [engine.agents[key] for key in formation['worker_ids']]
            if any(child.status != 'done' or agent.worker_report_consumed.get(child.id) != child.result_revision
                   for child in workers):
                return reply(calls=[('wait_for_workers', {})])
            pending = [child for child in workers if agent.worker_report_reviews.get(child.id) !=
                       {'result_revision': child.result_revision, 'decision': 'accept'}]
            if pending:
                return reply(calls=[('review_worker_report', {'worker_id': child.id,
                    'result_revision': child.result_revision, 'decision': 'accept',
                    'feedback': 'The native save receipt and current report match the assigned output.'}) for child in pending])
            assert formation['phase'] == 'working', formation
            return reply(calls=[('request_independent_review', {'summary': FINAL, 'artifact_paths': []})])
        if agent.kind == 'independent_reviewer':
            assert 'write_text' not in {t['name'] for t in tools}
            candidate = formation['candidate']
            assert candidate['artifact_count'] == 1  # Output receipt must prevent PM omission.
            results = [json.loads(m['content']) for m in messages
                       if m.get('role') == 'tool' and m.get('name') == 'read_text']
            verdict = ('submit_independent_review', {'candidate_id': candidate['id'],
                'decision': 'accept', 'feedback': 'Compared the native text with the requested fixture value 42.'})
            if not results:
                assert FINAL in system or any(FINAL in str(m.get('content')) for m in messages)
                calls = [('read_text', {'path': 'result.txt'})]
                if self.same_batch:
                    calls.append(verdict)
                return reply(calls=calls)
            assert results[-1]['text'] == CONTENT
            if self.same_batch:
                denied = [json.loads(m['content']) for m in messages
                          if m.get('role') == 'tool' and m.get('name') == 'submit_independent_review']
                assert denied and denied[-1]['ok'] is False
            assert candidate['consumed_read_count'] == 1
            return reply(calls=[verdict])
        wrote = any(m.get('role') == 'tool' and m.get('name') == 'write_text' for m in messages)
        if not wrote:
            return reply(calls=[('write_text', {'path': 'result.txt', 'text': CONTENT,
                                               'expected_sha256': 'missing'})])
        return reply(calls=[('finish_work', {'summary': 'Saved result.txt; fixture value 42 and native receipt checked.'})])


async def joined(engine):
    async with asyncio.timeout(20):
        while True:
            pending = [a.task for a in engine.agents.values() if a.task and not a.task.done()]
            if not pending:
                return
            await asyncio.gather(*pending)


@pytest.mark.parametrize('same_batch', [False, True])
async def test_native_pipeline_independent_review_and_exact_finish(tmp_path, same_batch):
    provider = WorkflowProvider(same_batch)
    engine, work = configured(tmp_path, provider)
    provider.engine = engine
    initial_limits = copy.deepcopy(engine.settings.value['limits'])
    try:
        response = await engine.start_run({'task': 'Save result.txt containing the fixture value 42, then verify it.',
            'pm_profile': 'local', 'worker_profiles': ['local'], 'max_workers': 2, 'adaptive_team': True})
        run = engine.runs[response['run']['id']]
        await joined(engine)
        assert run['status'] == 'done', [(a.name, a.status, a.last_error, a.delegation_blocked) for a in engine.agents.values()]
        assert run['formation']['phase'] == 'complete'
        candidate = run['formation']['candidate']
        assert candidate['decision'] == 'accept'
        assert candidate['summary_sha256'] == hashlib.sha256(FINAL.encode()).hexdigest()
        assert candidate['artifact_count'] == candidate['read_count'] == candidate['consumed_read_count'] == 1
        assert (work / 'result.txt').read_text(encoding='utf-8') == CONTENT
        assert len(run['agent_ids']) == 3 and len(run['pm_agent_ids']) == 1
        reviewer = engine.agents[run['formation']['reviewer_id']]
        assert reviewer.parent_id is None and reviewer.id not in run['pm_agent_ids']
        assert not engine.message_eligibility(reviewer)['allowed']
        pm = engine.agents[run['pm_agent_ids'][0]]
        assert pm.finished_revision == pm.result_revision
        assert any(r['source'] == 'finish_work' and r['text'] == FINAL for r in pm.results)
        assert engine.settings.value['limits'] == initial_limits
        assert run['model_calls'] == len(provider.calls) <= 12
        assert run['tool_calls'] <= 15 and run['auto_collaborations'] <= 8
        assert not engine.history.error
        assert not any(a.pending or a.question or (a.task and not a.task.done()) for a in engine.agents.values())
    finally:
        await engine.close()
    assert engine.closed and not engine._question_tasks
