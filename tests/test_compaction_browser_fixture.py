"""Exercise the browser's deterministic provider through the unmodified engine."""
import json

import pytest

from tools.browser_fixture import COMPACTION_CASE, CREDENTIAL_RECOVERY_CASE, SyntheticClient, synthetic_native
from workbench.context import request_size
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


@pytest.mark.parametrize('kind', ['local', 'openai', 'anthropic'])
async def test_saved_result_fixture_keeps_followup_eligible_with_valid_native_replay(tmp_path, kind):
    client = SyntheticClient()
    engine, _ = configured(tmp_path, client)
    engine.settings.value['providers'][0]['kind'] = kind
    engine.settings.secrets['local'] = 'synthetic-no-network-key'
    try:
        run, agent = await start(engine, task='[SYNTHETIC] Save result.', max_workers=0)
        await settled(engine)
        assert run['status'] == agent.status == 'done'
        snapshot = engine.snapshot()['agents'][0]
        assert snapshot['message_eligibility']['allowed'] is True
        assert 'PRIVATE-PROTOCOL-FIXTURE' not in json.dumps(snapshot)
        assert agent.conversation[-1]['provider_raw']['provider'] == kind
        assert 'PRIVATE-PROTOCOL-FIXTURE' in json.dumps(agent.conversation[-1]['provider_raw'])
        await engine.human_message(agent.id, '[SYNTHETIC] Follow up after saving.')
        await settled(engine)
        assert run['status'] == agent.status == 'done'
        assert client.calls[agent.id] == run['model_calls'] == 3
        assert len(agent.output_receipts) == 1
    finally:
        await engine.close()


@pytest.mark.parametrize('kind', ['local', 'openai', 'anthropic'])
def test_native_fixture_tool_batches_size_through_real_adapter(kind):
    profile = {'kind': kind, 'model': 'synthetic-model'}
    calls = [{'id': 'fixture-call', 'name': 'list_team', 'arguments': {}}]
    raw = synthetic_native(profile, '[SYNTHETIC] retained source', calls, private='PRIVATE-SENTINEL')
    messages = [{'role': 'user', 'content': '[SYNTHETIC] original task'},
        {'role': 'assistant', 'content': '[SYNTHETIC] retained source', 'tool_calls': calls, 'provider_raw': raw},
        {'role': 'tool', 'tool_call_id': 'fixture-call', 'content': '{"ok":true}'}]
    chars, estimate = request_size(profile, messages, [], 'Synthetic policy')
    assert estimate >= chars > len('PRIVATE-SENTINEL')
    assert 'PRIVATE-SENTINEL' in json.dumps(raw)
