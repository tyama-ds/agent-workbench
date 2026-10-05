"""Contextual lifetime help matches server state, admission and explicit exports."""
from pathlib import Path

import pytest
from aiohttp import ClientSession, CookieJar

from test_config_server import serving, bootstrap
from test_engine import configured, ScriptClient, start
from test_task_guidance import Elements, descendants
from workbench.engine import AdmissionError
from workbench.server import APP_KEY

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'static/app.js').read_text(encoding='utf-8')


def test_lifetime_warning_is_visible_and_optional_help_is_static():
    tree = Elements()
    note = tree.ids['historyRetention']
    assert all(n['tag'] != 'details' and 'hidden' not in n['attrs'] for n in (*note['ancestors'], note))
    assert 'サーバー終了で消えます' in note['text'] and '.txt 保存' in note['text']
    count = tree.ids['runCount']
    assert count['text'] == '0 / 20' and '上限20件' in count['attrs']['aria-label']
    assert "$('runCount').textContent=`${ui.state.runs.length} / 20`" in APP
    details = tree.ids['historyDetails']
    assert details['tag'] == 'details' and 'open' not in details['attrs']
    assert details['children'][0]['tag'] == 'summary'
    assert tree.ids['resultsPanel'] in details['ancestors']
    help_text = tree.ids['historyLifetimeHelp']['text']
    for text in ('最新20件', '24,000文字', '64件', '200件', '表示用の履歴から省略します', 'タブを閉じたり再読み込み',
                 '作業は停止しません', '選択したチームだけ', '履歴は保持', 'すべてのチーム',
                 '入力した API キー', '環境変数', '未送信の下書き', '再接続は保証しません',
                 '削除しません', '現在のファイルの存在・内容は未確認'):
        assert text in help_text
    assert not any(n['tag'] in {'a', 'input', 'button', 'select', 'textarea', 'form', 'script'} for n in descendants(details))
    assert not any(k.startswith('on') for n in descendants(details) for k in n['attrs'])
    assert all(ident not in APP for ident in ('historyRetention', 'historyDetails', 'historyLifetimeHelp', 'resultRetentionHelp'))


def test_export_help_keeps_selected_record_and_receipt_boundaries():
    tree = Elements()
    help_text = tree.ids['resultRetentionHelp']
    assert tree.ids['exportResult']['attrs']['aria-describedby'] == 'resultRetentionHelp'
    assert '選択中の1件だけ' in help_text['text'] and 'ファイル本体は含みません' in help_text['text']
    assert tree.ids['resultsPanel'] in help_text['ancestors']
    assert tree.ids['historyDetails'] not in help_text['ancestors']
    assert 'モデルによる報告です。内容の正しさや作業の完了を検証したものではありません。' in APP
    assert '保存時点の記録です。現在のファイルの存在・内容は未確認です。ファイル本体のダウンロードはできません。' in APP
    assert 'ダウンロードを開始しました' in APP


async def test_twenty_runs_reject_new_work_without_eviction_and_warn_before_restart(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda _: None
    try:
        for index in range(20):
            run, agent = await start(engine, max_workers=0)
            engine.record_result(agent, 'assistant_response', f'Synthetic report {index}')
            if index % 2:
                await engine.stop_run(run['id'])
            else:
                run['status'] = agent.status = 'done'
        before = engine.snapshot()
        payload = {'task': 'Twenty-first work', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0}
        preview = engine.preflight(payload)
        blocker = preview['blockers'][0]
        assert not preview['can_start'] and blocker['code'] == 'engine_unavailable'
        for text in ('1起動20作業', '.txt 保存', 'すべての作業完了後', 'サーバーを再起動', '履歴と入力した API キーは失われます'):
            assert text in blocker['message']
        with pytest.raises(AdmissionError) as error:
            await engine.start_run(payload)
        assert str(error.value) == blocker['message']
        after = engine.snapshot()
        assert after['runs'] == before['runs'] and after['agents'] == before['agents'] and after['events'] == before['events']
        assert len(engine.runs) == 20 and len(engine.agents) == 20
    finally:
        await engine.close()


async def test_closed_engine_message_does_not_misreport_a_history_cap(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    await engine.close()
    preview = engine.preflight({'task': 'Synthetic', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})
    message = preview['blockers'][0]['message']
    assert not preview['can_start'] and preview['blockers'][0]['code'] == 'engine_unavailable'
    assert '終了処理中' in message and '履歴と入力した API キーは引き継ぎません' in message
    assert '上限' not in message


async def test_page_reconnect_stop_and_fresh_server_have_distinct_lifetimes(tmp_path, monkeypatch):
    work = tmp_path / 'workspace'
    work.mkdir()
    monkeypatch.setenv('WORKBENCH_TEST_RETENTION_KEY', 'synthetic-environment-key')
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        engine.kick = lambda _: None
        config = engine.settings.value
        config['providers'][0].update(model='synthetic-retention-model', api_key_env='WORKBENCH_TEST_RETENTION_KEY')
        config['paths'] = {'read_roots': [str(work)], 'write_roots': [str(work)], 'deny_roots': []}
        engine.save_settings(config)
        engine.set_secret('local', 'synthetic-memory-key')
        run, agent = await start(engine, max_workers=0)
        engine.record_result(agent, 'assistant_response', 'Synthetic retained report')
        await engine.execute_tool(run, agent, 'write_text', {'path': str(work / 'saved.txt'), 'text': 'Synthetic retained bytes', 'expected_sha256': 'missing'})
        before = engine.snapshot()
        response = await client.get(auth.origin + '/')
        assert response.status == 200
        # This is a same-cookie transport reconnect, not a browser-restart guarantee.
        async with ClientSession(cookie_jar=client.cookie_jar) as reconnect:
            restored = await (await reconnect.get(auth.origin + '/api/state')).json()
        assert restored['runs'] == before['runs'] and restored['agents'] == before['agents']
        assert engine.settings.key(config['providers'][0]) == 'synthetic-memory-key'
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as unauthenticated:
            assert (await unauthenticated.get(auth.origin + '/api/state')).status == 401
            assert (await unauthenticated.post(auth.origin + '/api/bootstrap', json={}, headers={
                'Origin': auth.origin, 'X-Workbench-Bootstrap': auth.launch_token})).status == 401
        assert not engine.closed and len(engine.runs) == 1
        await engine.stop_run(run['id'])
        assert list(agent.results) == before['agents'][0]['results']
        assert list(agent.output_receipts) == before['agents'][0]['output_receipts']
        assert engine.settings.secrets['local'] == 'synthetic-memory-key'
        assert (work / 'saved.txt').read_text(encoding='utf-8') == 'Synthetic retained bytes'
    assert engine.closed and not engine.settings.secrets
    settings_bytes = (tmp_path / 'state' / 'settings.json').read_bytes()
    assert b'synthetic-memory-key' not in settings_bytes and b'synthetic-environment-key' not in settings_bytes
    assert sorted(p.name for p in (tmp_path / 'state').iterdir()) == ['settings.json']
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        fresh = app[APP_KEY]
        assert not fresh.runs and not fresh.agents and not fresh.settings.secrets
        assert fresh.settings.value['providers'][0]['model'] == 'synthetic-retention-model'
        assert fresh.settings.key(fresh.settings.value['providers'][0]) == 'synthetic-environment-key'
        assert fresh.settings.public()['secret_status']['local']
        assert (tmp_path / 'state' / 'settings.json').read_bytes() == settings_bytes
        assert (work / 'saved.txt').read_text(encoding='utf-8') == 'Synthetic retained bytes'
        assert fresh.preflight({'task': 'New startup', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})['can_start']
