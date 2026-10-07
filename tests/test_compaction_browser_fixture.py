"""Exercise the browser's deterministic provider through the unmodified engine."""
from tools.browser_fixture import COMPACTION_CASE, CREDENTIAL_RECOVERY_CASE, SyntheticClient
from test_engine import configured, settled, start


async def test_browser_fixture_compacts_and_verifies_original_history(tmp_path):
    client = SyntheticClient()
    engine, _ = configured(tmp_path, client)
    engine.settings.value['limits'].update(max_context_chars=50000, context_recent_groups=2,
                                          context_summary_chars=1500, max_output_tokens=2048)
    try:
        run, agent = await start(engine, task=COMPACTION_CASE['task'], max_workers=0)
        await settled(engine)
        assert run['status'] == agent.status == 'done'
        assert agent.compactions == client.summary_calls == 1
        assert run['model_calls'] == client.calls[agent.id] + client.summary_calls
        assert any(log['text'] == COMPACTION_CASE['result'] for log in agent.logs)
        assert any(log['text'].startswith('read_context_history\n') for log in agent.logs)
        assert agent.conversation[0]['content'] == COMPACTION_CASE['task']
        assert agent.original_history[1][0]['content'] == COMPACTION_CASE['observation']
        assert any(item.get('_summary') for item in agent.conversation)
        assert agent.context_chars < 50000 and not agent.compacting
    finally:
        await engine.close()


async def test_credential_browser_fixture_accepts_human_provenance_on_resume(tmp_path):
    client = SyntheticClient()
    engine, _ = configured(tmp_path, client)
    engine.settings.secrets['local'] = CREDENTIAL_RECOVERY_CASE['old']
    try:
        run, agent = await start(engine, task=CREDENTIAL_RECOVERY_CASE['task'], max_workers=0)
        await settled(engine)
        assert agent.status == 'error' and client.calls[agent.id] == 1
        engine.settings.secrets['local'] = CREDENTIAL_RECOVERY_CASE['new']
        await engine.human_message(agent.id, CREDENTIAL_RECOVERY_CASE['resume'])
        await settled(engine)
        assert run['status'] == agent.status == 'done'
        assert client.calls[agent.id] == 2
        assert agent.conversation[-2]['_human'] is True
        assert agent.conversation[-2]['content'] == CREDENTIAL_RECOVERY_CASE['resume']
    finally:
        await engine.close()
