"""Real engine dispatch keeps one identity per agent conversation, excluding summaries."""
import re

from test_context_compaction import summary_reply
from test_engine import ScriptClient, configured, reply, settled, start


class IdentityClient(ScriptClient):
    def __init__(self, responses):
        super().__init__(responses)
        self.conversation_ids = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        self.conversation_ids.append(conversation_id)
        return await super().complete(profile, messages, tools, system, limits,
                                      conversation_id=conversation_id)


async def test_identity_survives_tool_followups_and_human_turns(tmp_path):
    client = IdentityClient([
        reply(calls=[('list_team', {})]), reply('Initial work completed'), reply('Followup completed')])
    engine, _ = configured(tmp_path, client)
    try:
        run, agent = await start(engine)
        await settled(engine)
        assert agent.status == 'done' and len(client.calls) == 2
        await engine.human_message(agent.id, 'Continue the same work')
        await settled(engine)
        assert agent.status == 'done' and agent.turns == 2
        expected = f'{run["id"]}/{agent.id}'
        assert re.fullmatch(r'[A-Za-z0-9_./:-]{1,128}', expected)
        assert client.conversation_ids == [expected, expected, expected]
    finally:
        await engine.close()


async def test_workers_and_separate_runs_have_distinct_identities(tmp_path):
    client = IdentityClient([reply('Complete') for _ in range(4)])
    engine, _ = configured(tmp_path, client)
    try:
        first_run, lead = await start(engine)
        await settled(engine)
        created = await engine.execute_tool(first_run, lead, 'spawn_worker', {
            'profile_id': 'local', 'role': 'reviewer', 'task': 'Review the existing result'})
        worker = engine.agents[created['agent_id']]
        await settled(engine)
        second_run, other_lead = await start(engine, task='An independent task')
        await settled(engine)
        assert all(agent.status == 'done' for agent in (lead, worker, other_lead))
        expected_lead = f'{first_run["id"]}/{lead.id}'
        expected_worker = f'{first_run["id"]}/{worker.id}'
        expected_other = f'{second_run["id"]}/{other_lead.id}'
        assert len({expected_lead, expected_worker, expected_other}) == 3
        # Worker completion is another turn of the existing PM conversation.
        assert client.conversation_ids == [expected_lead, expected_worker, expected_lead, expected_other]
    finally:
        await engine.close()


async def test_compaction_omits_identity_then_resumes_same_agent_identity(tmp_path):
    client = IdentityClient([reply('Initial answer'), summary_reply(), reply('Continued after compaction')])
    engine, _ = configured(tmp_path, client)
    engine.settings.value['limits']['max_context_chars'] = 50000
    try:
        run, agent = await start(engine)
        await settled(engine)
        assert agent.status == 'done'
        initial_message = client.calls[0][0]
        for index in range(18):
            engine._append_context(agent, {'role': 'assistant', 'content': f'Observation {index}: ' + 'a' * 1800})
        await engine.human_message(agent.id, 'Continue after these observations')
        await settled(engine)
        assert agent.status == 'done' and agent.compactions == 1
        assert run['model_calls'] == 3
        expected = f'{run["id"]}/{agent.id}'
        assert client.conversation_ids == [expected, None, expected]
        assert client.calls[-1][0] == initial_message
        assert any(message.get('_summary') for message in client.calls[-1])
    finally:
        await engine.close()
