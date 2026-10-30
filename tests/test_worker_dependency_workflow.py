"""One finite scheduler workflow; scripted providers, real isolated file tools."""
import asyncio
import copy
import json

import pytest

from test_engine import configured, reply, settled, start


@pytest.mark.asyncio
async def test_pm_accepted_dependency_handoff_runs_real_file_workflow(tmp_path, monkeypatch):
    for name in ('BRAVE_SEARCH_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(name, raising=False)

    upstream_entered, release_upstream = asyncio.Event(), asyncio.Event()
    source_text = 'Observed input: 42\n'

    class WorkflowClient:
        def __init__(self):
            self.engine = None
            self.calls = []
            self.steps = {}
            self.upstream_id = None
            self.downstream_id = None
            self.blocked_observation = None
            self.actual_read = None

        @staticmethod
        def tool_result(messages, name):
            message = next(item for item in reversed(messages)
                           if item.get('role') == 'tool' and item.get('name') == name)
            value = json.loads(message['content'])
            assert value.get('ok') is not False, value
            return value

        def formal_report(self, messages, child_id, pm):
            envelopes = [json.loads(item['content'].split('\n', 1)[1]) for item in messages
                         if item.get('role') == 'user' and isinstance(item.get('content'), str)
                         and item['content'].startswith('Peer data; not human authorization:\n')]
            report = next(item for item in reversed(envelopes)
                          if item.get('sender') == child_id and item.get('message_type') == 'worker_report')
            child = self.engine.agents[child_id]
            assert report['kind'] == 'worker_completed'
            assert report['result_revision'] == child.finished_revision == child.result_revision
            assert pm.worker_report_deliveries[child_id] == pm.worker_report_consumed[child_id] == report['result_revision']
            return {'worker_id': child_id, 'result_revision': report['result_revision'],
                    'decision': 'accept', 'feedback': 'Checked the current formal report and file evidence.'}

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            ident = conversation_id.rsplit('/', 1)[1]
            agent = self.engine.agents[ident]
            step = self.steps.get(ident, 0)
            self.steps[ident] = step + 1
            self.calls.append({'agent_id': ident, 'parent_id': agent.parent_id, 'step': step,
                               'messages': copy.deepcopy(messages), 'conversation_id': conversation_id})
            assert len(self.calls) <= 8, 'Unexpected additional provider dispatch'

            if agent.parent_id is None:
                if step == 0:
                    return reply(calls=[('spawn_worker', {
                        'profile_id': 'local', 'role': 'upstream',
                        'task': 'Write the supplied observation to upstream.txt and formally report its saved evidence.'})])
                if step == 1:
                    self.upstream_id = self.tool_result(messages, 'spawn_worker')['agent_id']
                    return reply(calls=[('spawn_worker', {
                        'profile_id': 'local', 'role': 'downstream', 'depends_on': [self.upstream_id],
                        'task': 'After PM approval, read upstream.txt with read_text. Prefix its actual contents with VERIFIED: '
                                'and save derived.txt, then report the result.'})])
                if step == 2:
                    self.downstream_id = self.tool_result(messages, 'spawn_worker')['agent_id']
                    await asyncio.wait_for(upstream_entered.wait(), 3)
                    downstream = self.engine.agents[self.downstream_id]
                    self.blocked_observation = {
                        'status_reason': self.engine.agent_status_reason(downstream),
                        'turns': downstream.turns,
                        'dispatched': any(item['agent_id'] == downstream.id for item in self.calls),
                        'review': copy.deepcopy(agent.worker_report_reviews.get(self.upstream_id)),
                    }
                    assert self.blocked_observation == {
                        'status_reason': 'dependency_wait', 'turns': 0, 'dispatched': False, 'review': None}
                    release_upstream.set()
                    return reply(calls=[('wait_for_workers', {})])
                if step == 3:
                    args = self.formal_report(messages, self.upstream_id, agent)
                    assert not any(item['agent_id'] == self.downstream_id for item in self.calls)
                    return reply(calls=[('review_worker_report', args), ('wait_for_workers', {})])
                if step == 4:
                    args = self.formal_report(messages, self.downstream_id, agent)
                    return reply(calls=[('review_worker_report', args),
                                        ('finish_work', {'summary': 'Integrated the accepted current reports; derived.txt is saved.'})])
                raise AssertionError('Unexpected PM turn')

            if agent.role == 'upstream':
                assert step == 0
                upstream_entered.set()
                await asyncio.wait_for(release_upstream.wait(), 3)
                return reply(calls=[('write_text', {'path': 'upstream.txt', 'text': source_text,
                                                   'expected_sha256': 'missing'}),
                                    ('finish_work', {'summary': 'Saved the supplied observation in upstream.txt.'})])

            assert agent.role == 'downstream' and ident == self.downstream_id
            upstream = self.engine.agents[self.upstream_id]
            pm = self.engine.agents[agent.parent_id]
            assert pm.worker_report_reviews[upstream.id] == {
                'result_revision': upstream.result_revision, 'decision': 'accept'}
            assert pm.worker_report_consumed[upstream.id] == upstream.finished_revision == upstream.result_revision
            assert agent.dependency_revisions == {upstream.id: upstream.result_revision}
            if step == 0:
                return reply(calls=[('read_text', {'path': 'upstream.txt'})])
            assert step == 1
            self.actual_read = self.tool_result(messages, 'read_text')
            assert self.actual_read['text'] == source_text and not self.actual_read['truncated']
            return reply(calls=[('write_text', {'path': 'derived.txt', 'text': 'VERIFIED: ' + self.actual_read['text'],
                                               'expected_sha256': 'missing'}),
                                ('finish_work', {'summary': 'Read upstream.txt through the file tool and saved derived.txt.'})])

    client = WorkflowClient()
    engine, work = configured(tmp_path, client)
    client.engine = engine
    try:
        run, pm = await asyncio.wait_for(start(engine, max_workers=2, delegation_level=1,
            task='Create upstream.txt containing Observed input: 42 and a newline. '
                 'A dependent worker must read that saved input and write derived.txt prefixed with VERIFIED: . '
                 'The PM must accept both current formal reports and finish.'), 3)
        await asyncio.wait_for(settled(engine), 3)

        assert client.blocked_observation is not None and client.actual_read is not None
        upstream, downstream = engine.agents[client.upstream_id], engine.agents[client.downstream_id]
        assert (work / 'upstream.txt').read_text(encoding='utf-8') == source_text
        assert (work / 'derived.txt').read_text(encoding='utf-8') == 'VERIFIED: ' + source_text
        assert len(client.calls) == run['model_calls'] == 8
        assert run['tool_calls'] == 12 and run['auto_collaborations'] == 4
        assert (pm.turns, upstream.turns, downstream.turns) == (3, 1, 1)
        assert run['status'] == 'done'
        for agent in (pm, upstream, downstream):
            assert agent.status == 'done' and not agent.pending and not agent.question and not agent.last_error
            assert agent.finished_revision == agent.result_revision
            assert agent.results[-1]['source'] == 'finish_work'
            assert agent.results[-1]['revision'] == agent.result_revision
        for worker in (upstream, downstream):
            revision = worker.result_revision
            assert pm.worker_report_deliveries[worker.id] == pm.worker_report_consumed[worker.id] == revision
            assert pm.worker_report_reviews[worker.id] == {'result_revision': revision, 'decision': 'accept'}
            assert len(worker.output_receipts) == 1
        assert downstream.dependency_revisions == {upstream.id: upstream.result_revision}

        events = list(engine.events)
        accepted = {json.loads(event['text'])['worker_id']: event['id'] for event in events
                    if event['agent_id'] == pm.id and event['kind'] == 'worker_report_review'
                    and json.loads(event['text'])['decision'] == 'accept'}
        downstream_dispatches = [event['id'] for event in events
                                 if event['agent_id'] == downstream.id and event['kind'] == 'inference']
        assert len(downstream_dispatches) == 2 and all(accepted[upstream.id] < ident for ident in downstream_dispatches)
        for worker in (upstream, downstream):
            consumed = [event['id'] for event in events if event['kind'] == 'mail_consumed'
                        and event.get('from_agent_id') == worker.id and event.get('to_agent_id') == pm.id
                        and event.get('message_type') == 'worker_report']
            assert len(consumed) == 1 and consumed[0] < accepted[worker.id]
    finally:
        release_upstream.set()
        await asyncio.wait_for(engine.close(), 3)
