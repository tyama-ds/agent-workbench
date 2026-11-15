"""Phase 7: human approval of risky operations, the human-written team memo
with PM proposals, searching past work, and switching to a fallback model."""
import asyncio
import hashlib
import json

import pytest

from workbench.providers import ProviderError, ProviderTimeoutError
from test_engine import ScriptClient, configured, reply, settled, start


def sha(data):
    return hashlib.sha256(data).hexdigest()


async def until(predicate, steps=300):
    for _ in range(steps):
        if predicate():
            return
        await asyncio.sleep(.01)
    raise AssertionError('condition not reached')


# --- approvals ---------------------------------------------------------------

@pytest.mark.approvals
@pytest.mark.asyncio
async def test_overwriting_a_file_waits_for_the_human_and_runs_after_approval(tmp_path):
    engine, work = configured(tmp_path, None)
    target = work / 'report.txt'
    target.write_text('old', encoding='utf-8')
    engine.client = ScriptClient([
        reply(calls=[('write_text', {'path': str(work / 'new.txt'), 'text': 'new', 'expected_sha256': 'missing'}),
                     ('write_text', {'path': str(target), 'text': 'approved', 'expected_sha256': sha(b'old')})]),
        reply('done')])
    try:
        run, pm = await start(engine, max_workers=0)
        assert run['approval_mode'] == 'ask'
        await until(lambda: pm.approval is not None)
        assert (work / 'new.txt').read_text(encoding='utf-8') == 'new', 'creating a new file needs no approval'
        assert target.read_text(encoding='utf-8') == 'old'
        assert pm.status == 'waiting' and engine.agent_status_reason(pm) == 'approval'
        assert run['status'] == 'waiting'
        public = pm.public()['approval']
        assert public['tool'] == 'write_text' and str(target) in public['summary'] and '_future' not in public
        with pytest.raises(ValueError, match='すでに終わって'):
            engine.resolve_approval(pm.id, {'approval_id': 'ap-wrong', 'decision': 'approve'})
        assert engine.resolve_approval(pm.id, {'approval_id': public['id'], 'decision': 'approve'}) == {
            'ok': True, 'decision': 'approve'}
        await settled(engine)
        assert target.read_text(encoding='utf-8') == 'approved'
        assert pm.approval is None and pm.status == 'done'
        assert any(row['kind'] == 'approval_resolved' for row in engine.events)
    finally:
        await engine.close()


@pytest.mark.approvals
@pytest.mark.asyncio
async def test_a_rejected_operation_is_not_run_and_the_model_is_told(tmp_path):
    engine, work = configured(tmp_path, None)
    target = work / 'report.txt'
    target.write_text('old', encoding='utf-8')
    engine.client = ScriptClient([
        reply(calls=[('patch_text', {'path': str(target), 'find': 'old', 'replace': 'new', 'expected_sha256': sha(b'old')})]),
        reply('I will not change it.')])
    try:
        run, pm = await start(engine, max_workers=0)
        await until(lambda: pm.approval is not None)
        engine.resolve_approval(pm.id, {'approval_id': pm.approval['id'], 'decision': 'reject', 'note': '今は変えない'})
        await settled(engine)
        assert target.read_text(encoding='utf-8') == 'old'
        result = json.loads(next(row['content'] for row in pm.conversation if row['role'] == 'tool'))
        assert '承認しませんでした' in result['error'] and '今は変えない' in result['error']
        assert pm.status == 'done'
    finally:
        await engine.close()


@pytest.mark.approvals
@pytest.mark.asyncio
async def test_always_allow_and_the_settings_choose_what_needs_approval(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, approval_mode='always_allow')
        assert run['approval_mode'] == 'always_allow'
        assert not engine._approval_needed(run, 'python_execute', {'code': 'x'})
        ask_run, _ = await start(engine, max_workers=0)
        assert engine._approval_needed(ask_run, 'python_execute', {'code': 'x'})
        assert engine._approval_needed(ask_run, 'selenium_browse', {'url': 'https://example.com'})
        assert engine._approval_needed(ask_run, 'docx_edit', {'path': 'a.docx', 'expected_sha256': 'a' * 64})
        assert not engine._approval_needed(ask_run, 'docx_write', {'path': 'a.docx', 'expected_sha256': 'missing'})
        assert not engine._approval_needed(ask_run, 'read_text', {'path': 'a.txt'})
        ask_run['_config']['approvals']['python'] = False
        assert not engine._approval_needed(ask_run, 'python_execute', {'code': 'x'})
        with pytest.raises(ValueError, match='承認の扱い'):
            await start(engine, approval_mode='sometimes')
    finally:
        await engine.close()


@pytest.mark.approvals
@pytest.mark.asyncio
async def test_stopping_the_team_while_an_approval_waits_runs_nothing(tmp_path):
    engine, work = configured(tmp_path, None)
    target = work / 'report.txt'
    target.write_text('old', encoding='utf-8')
    engine.client = ScriptClient([reply(calls=[('write_text', {
        'path': str(target), 'text': 'never', 'expected_sha256': sha(b'old')})])])
    try:
        run, pm = await start(engine, max_workers=0)
        await until(lambda: pm.approval is not None)
        ident = pm.approval['id']
        await engine.stop_run(run['id'])
        assert pm.approval is None and pm.status == 'stopped'
        with pytest.raises(ValueError):
            engine.resolve_approval(pm.id, {'approval_id': ident, 'decision': 'approve'})
        assert target.read_text(encoding='utf-8') == 'old'
    finally:
        await engine.close()


# --- team memo -------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_human_memo_reaches_new_runs_only(tmp_path):
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        before, pm_before = await start(engine)
        engine.save_memo({'text': '報告書は必ず日本語で書く。'})
        after, pm_after = await start(engine)
        assert '報告書は必ず日本語で書く。' in engine._policy(after, pm_after)
        assert 'grants no tools' in engine._policy(after, pm_after)
        assert '報告書は必ず日本語で書く。' not in engine._policy(before, pm_before)
        spawned = await engine.execute_tool(after, pm_after, 'spawn_worker', {'role': 'w', 'task': 't', 'profile_id': 'local'})
        assert '報告書は必ず日本語で書く。' in engine._policy(after, engine.agents[spawned['agent_id']])
        assert engine.memo_state()['memo']['text'] == '報告書は必ず日本語で書く。'
        with pytest.raises(ValueError):
            engine.save_memo({'text': 'x' * 4001})
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_pm_proposals_wait_for_the_human_and_never_change_the_running_team(tmp_path):
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        names = {tool['name'] for tool in engine._model_tools(run, pm)}
        assert 'propose_memo' in names and 'search_past_work' not in names
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'w', 'task': 't', 'profile_id': 'local'})
        worker = engine.agents[spawned['agent_id']]
        assert 'propose_memo' not in {tool['name'] for tool in engine._model_tools(run, worker)}
        with pytest.raises(ValueError, match='PM'):
            await engine.execute_tool(run, worker, 'propose_memo', {'text': 'x', 'reason': 'y'})
        result = await engine.execute_tool(run, pm, 'propose_memo', {'text': '数値は千円単位で書く', 'reason': '人が確認した'})
        assert result['status'] == 'pending'
        snapshot = engine.snapshot()
        assert [row['text'] for row in snapshot['memo_proposals']] == ['数値は千円単位で書く']
        engine.resolve_memo_proposal(result['proposal_id'], {'decision': 'approve'})
        assert engine.memo.text == '- 数値は千円単位で書く'
        assert '千円単位' not in engine._policy(run, pm), 'the running team keeps its memo snapshot'
        rejected = await engine.execute_tool(run, pm, 'propose_memo', {'text': '不要な提案', 'reason': ''})
        engine.resolve_memo_proposal(rejected['proposal_id'], {'decision': 'reject'})
        assert '不要な提案' not in engine.memo.text and not engine.snapshot()['memo_proposals']
        with pytest.raises(ValueError, match='すでに処理'):
            engine.resolve_memo_proposal(rejected['proposal_id'], {'decision': 'approve'})
        for n in range(3):
            await engine.execute_tool(run, pm, 'propose_memo', {'text': f'提案{n}', 'reason': ''})
        with pytest.raises(ValueError, match='多すぎます'):
            await engine.execute_tool(run, pm, 'propose_memo', {'text': '4件目', 'reason': ''})
    finally:
        await engine.close()


# --- searching past work ---------------------------------------------------------

@pytest.mark.asyncio
async def test_people_search_saved_runs_and_pm_search_is_opt_in(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([reply(calls=[('finish_work', {'summary': '売上の集計結果: 1,234件'})])]))
    try:
        old_run, old_pm = await start(engine, task='四半期の売上を集計する', max_workers=0)
        await settled(engine)
        found = engine.search_history('売上')
        assert [row['run_id'] for row in found['runs']] == [old_run['id']]
        sources = {match['source'] for match in found['runs'][0]['matches']}
        assert 'task' in sources and 'result' in sources
        assert engine.search_history('存在しない語')['runs'] == []
        with pytest.raises(ValueError):
            engine.search_history('')

        engine.kick = lambda agent: None
        run, pm = await start(engine, max_workers=0)
        assert 'search_past_work' not in {tool['name'] for tool in engine._model_tools(run, pm)}
        with pytest.raises(ValueError, match='無効'):
            await engine.execute_tool(run, pm, 'search_past_work', {'query': '売上'})
        engine.settings.value['history_search']['pm_enabled'] = True
        allowed, allowed_pm = await start(engine, max_workers=0)
        assert 'search_past_work' in {tool['name'] for tool in engine._model_tools(allowed, allowed_pm)}
        result = await engine.execute_tool(allowed, allowed_pm, 'search_past_work', {'query': '売上'})
        assert result['untrusted_past_data'] is True
        assert [row['run_id'] for row in result['runs']] == [old_run['id']]
        assert all(match['source'] != 'log' for row in result['runs'] for match in row['matches'])
    finally:
        await engine.close()


# --- fallback model --------------------------------------------------------------

class FallbackClient:
    def __init__(self, error):
        self.error, self.calls = error, []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        self.calls.append(profile['id'])
        if profile['id'] == 'local':
            raise self.error
        assert all('provider_raw' not in row for row in messages), 'no native envelopes cross providers'
        return reply('Finished on the fallback model.')


@pytest.mark.asyncio
async def test_a_timeout_switches_once_to_the_fallback_model(tmp_path):
    client = FallbackClient(ProviderTimeoutError('Provider request timed out'))
    engine, _ = configured(tmp_path, client)
    engine.settings.value['providers'][0]['fallback_profile_id'] = 'openai'
    engine.settings.value['providers'][1]['model'] = 'fixture-openai'
    engine.settings.secrets['openai'] = 'test-key'
    try:
        result = await engine.start_run({'task': 'Work', 'pm_profile': 'local', 'worker_profiles': ['openai'], 'max_workers': 1})
        run = engine.runs[result['run']['id']]
        pm = engine.agents[run['agent_ids'][0]]
        await settled(engine)
        assert client.calls == ['local', 'openai']
        assert pm.profile_id == 'openai' and pm.status == 'done'
        assert any(row['kind'] == 'model_fallback' for row in engine.events)
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_no_fallback_for_request_errors_or_profiles_the_run_does_not_allow(tmp_path):
    client = FallbackClient(ProviderError('Provider returned HTTP 401; check the API key', status=401))
    engine, _ = configured(tmp_path, client)
    engine.settings.value['providers'][0]['fallback_profile_id'] = 'openai'
    try:
        run, pm = await start(engine, max_workers=0)
        await settled(engine)
        assert client.calls == ['local'] and pm.status == 'error' and pm.profile_id == 'local'
        client.error = ProviderTimeoutError('Provider request timed out')
        timeout_run, timeout_pm = await start(engine, max_workers=0)  # openai is not allowed in this run
        await settled(engine)
        assert timeout_pm.status == 'error' and timeout_pm.profile_id == 'local'
    finally:
        await engine.close()


def test_settings_reject_a_fallback_to_itself_or_an_unknown_profile(tmp_path):
    from workbench.config import validate_settings, DEFAULT
    import copy
    value = copy.deepcopy(DEFAULT)
    value['providers'][0]['fallback_profile_id'] = 'local'
    with pytest.raises(ValueError, match='代替モデル'):
        validate_settings(value, check_paths=False)
    value['providers'][0]['fallback_profile_id'] = 'missing'
    with pytest.raises(ValueError, match='代替モデル'):
        validate_settings(value, check_paths=False)
    value['providers'][0]['fallback_profile_id'] = 'openai'
    assert validate_settings(value, check_paths=False)['providers'][0]['fallback_profile_id'] == 'openai'
