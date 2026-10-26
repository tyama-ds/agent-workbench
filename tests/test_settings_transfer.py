"""Settings transfer is an unsaved draft; obsolete paths block all execution."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from aiohttp import ClientSession

from test_config_server import bootstrap, serving
from test_config_save_ownership import configured, put_config, read_config, saved_state
from workbench import server
from workbench.config import DEFAULT, Settings, preview_settings_import, validate_settings
from workbench.copilot_bridge import CopilotBridgeManager
from workbench.server import APP_KEY


@pytest.fixture(autouse=True)
def synthetic_credentials_only(monkeypatch):
    for profile in [*DEFAULT['providers'], DEFAULT['search']]:
        if profile['api_key_env']:
            monkeypatch.delenv(profile['api_key_env'], raising=False)


async def preview(client, auth, revision, backup):
    return await client.post(auth.origin + '/api/config/import-preview',
        json={'config_revision': revision, 'backup': backup}, headers={'Origin': auth.origin})


def wrapped(config):
    return {'format': 'agent-workbench-settings', 'format_version': 1, 'config': config}


def reject_call(*_args, **_kwargs):
    pytest.fail('Transfer/recovery must not save, execute, or connect')


def missing_config(tmp_path):
    root = tmp_path / 'old installation 日本語'
    config = copy.deepcopy(DEFAULT)
    config['providers'][0]['model'] = 'fixture-local'
    config['python'].update(enabled=True, network_enabled=True, executable=str(root / 'python.exe'),
                            library_paths=[str(root / 'packages')])
    config['selenium'].update(enabled=True, browser_executable=str(root / 'msedge.exe'),
        driver_executable=str(root / 'msedgedriver.exe'), library_paths=[str(root / 'selenium-packages')])
    config['copilot_agent'].update(enabled=True, python_executable=str(root / 'bridge-python' / 'python.exe'),
                                   bridge_directory=str(root / 'bridge'))
    config['paths'] = {field: [str(root / field)] for field in config['paths']}
    return config


async def test_export_preview_restore_lifecycle_keeps_credentials_out_and_preview_unsaved(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        engine, public = await configured(client, auth, app)
        monkeypatch.setenv('SYNTHETIC_TRANSFER_KEY', 'SYNTHETIC-env-private-value')
        saved = copy.deepcopy(engine.settings.value)
        saved['providers'][0]['api_key_env'] = 'SYNTHETIC_TRANSFER_KEY'
        engine.save_settings(saved)
        response = await client.get(auth.origin + '/api/config/export')
        assert response.status == 200 and response.headers['Cache-Control'] == 'no-store'
        backup = await response.json()
        assert backup == wrapped(engine.settings.value)
        encoded = json.dumps(backup)
        for value in ['SYNTHETIC-config-model-key', 'SYNTHETIC-config-search-key', 'SYNTHETIC-env-private-value',
                      'secret_status', 'settings_storage', 'config_revision', 'capabilities', 'effective_providers']:
            assert value not in encoded
        backup['config']['providers'][0]['label'] = 'Imported only after save'
        before = saved_state(engine)
        with monkeypatch.context() as patch:
            patch.setattr(engine, 'save_settings', reject_call)
            patch.setattr(engine, 'schedule_copilot_sync', reject_call)
            response = await preview(client, auth, engine.settings.revision, backup)
        assert response.status == 200
        draft = await response.json()
        assert set(draft) == {'config', 'config_revision', 'warnings'} and draft['warnings'] == []
        assert saved_state(engine) == before
        response = await put_config(client, auth, draft['config_revision'], draft['config'])
        assert response.status == 200
        restored = await response.json()
        assert restored['config'] == backup['config']
        assert restored['config_revision'] == draft['config_revision'] + 1
        assert json.loads(engine.settings.path.read_bytes()) == backup['config']
    # A fresh installation/process using the same state directory keeps settings.
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        restarted = await read_config(client, auth)
        assert restarted['config'] == backup['config']
        assert restarted['settings_storage'] == {'path': str(tmp_path / 'state' / 'settings.json'), 'warnings': []}
        assert app[APP_KEY].settings.secrets == {}


def test_explicit_state_directory_is_independent_of_installation_working_directory(tmp_path, monkeypatch):
    state = tmp_path / 'user state'
    first_install = tmp_path / 'version one'
    second_install = tmp_path / 'version two'
    first_install.mkdir()
    second_install.mkdir()
    monkeypatch.chdir(first_install)
    initial = Settings(state)
    config = copy.deepcopy(DEFAULT)
    config['providers'][0]['model'] = 'retained-model'
    initial.save(config)
    original = initial.path.read_bytes()
    monkeypatch.chdir(second_install)
    upgraded = Settings(state)
    assert upgraded.value == config and upgraded.path.read_bytes() == original
    assert upgraded.public()['settings_storage'] == {'path': str(state / 'settings.json'), 'warnings': []}
    assert not list(first_install.iterdir()) and not list(second_install.iterdir())


async def test_legacy_direct_settings_add_defaults_without_writing_or_syncing(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        legacy = copy.deepcopy(DEFAULT)
        del legacy['copilot_agent']
        del legacy['orchestration']
        del legacy['work_board']
        del legacy['limits']['max_auto_collaborations']
        del legacy['providers'][0]['context_window_tokens']
        before = saved_state(engine)
        monkeypatch.setattr(engine, 'schedule_copilot_sync', reject_call)
        response = await preview(client, auth, 0, legacy)
        assert response.status == 200
        result = await response.json()
        assert result['config'] == DEFAULT and result['warnings'] == []
        assert saved_state(engine) == before


async def test_missing_paths_preview_is_complete_but_save_stays_strict(tmp_path, monkeypatch):
    config = missing_config(tmp_path)
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        before = saved_state(engine)
        monkeypatch.setattr(engine, 'schedule_copilot_sync', reject_call)
        response = await preview(client, auth, 0, wrapped(config))
        assert response.status == 200
        result = await response.json()
        assert result['config'] == config and len(result['warnings']) == 10
        for field in ['python.executable', 'python.library_paths[0]', 'selenium.browser_executable',
                      'selenium.driver_executable', 'selenium.library_paths[0]', 'copilot_agent.python_executable',
                      'copilot_agent.bridge_directory', 'paths.read_roots[0]', 'paths.write_roots[0]', 'paths.deny_roots[0]']:
            assert any(message.startswith(field + ':') for message in result['warnings'])
        assert 'old installation' not in json.dumps(result['warnings'])
        assert saved_state(engine) == before and engine.settings.restore_warnings == []
        response = await put_config(client, auth, 0, result['config'])
        assert response.status == 400 and saved_state(engine) == before


@pytest.mark.parametrize('field,kind', [
    ('python.executable', 'relative'), ('python.executable', 'basename'), ('python.executable', 'directory'),
    ('python.executable', 'nul'), ('python.library_paths', 'nul'),
    ('selenium.driver_executable', 'basename'), ('selenium.driver_executable', 'directory'),
    ('copilot_agent.python_executable', 'basename'), ('copilot_agent.bridge_directory', 'file'),
    ('python.library_paths', 'file'), ('selenium.library_paths', 'file'),
    ('paths.read_roots', 'root'), ('paths.write_roots', 'file'), ('paths.deny_roots', 'relative')])
def test_preview_preserves_shape_absolute_basename_and_existing_type_checks(tmp_path, field, kind):
    config = copy.deepcopy(DEFAULT)
    if kind == 'nul':
        value = str(tmp_path / 'invalid\0component' / 'python.exe')
    elif kind == 'relative':
        value = 'relative/python.exe'
    elif kind == 'basename':
        value = str(tmp_path / 'wrong.exe')
    elif kind == 'root':
        value = str(Path(tmp_path.anchor))
    else:
        path = tmp_path / ('python.exe' if field.endswith('executable') and 'driver' not in field else
                           'msedgedriver.exe' if 'driver' in field else 'item')
        path.mkdir() if kind == 'directory' else path.write_text('fixture')
        value = str(path)
    section, name = field.split('.')
    config[section][name] = [value] if isinstance(config[section][name], list) else value
    with pytest.raises(ValueError):
        preview_settings_import(config)
    with pytest.raises(ValueError):
        validate_settings(config)


def test_missing_bridge_server_is_recoverable_but_existing_wrong_type_is_not(tmp_path):
    config = {'copilot_agent': {'bridge_directory': str(tmp_path)}}
    draft, warnings = preview_settings_import(config)
    assert len(warnings) == 1 and 'server.py' in warnings[0]
    with pytest.raises(ValueError):
        validate_settings(draft)
    (tmp_path / 'server.py').mkdir()
    with pytest.raises(ValueError):
        preview_settings_import(config)


@pytest.mark.parametrize('backup', [None, [], 'invalid', 7,
    {'format': 'other', 'format_version': 1, 'config': {}},
    {'format': 'agent-workbench-settings', 'format_version': 2, 'config': {}},
    {'format': 'agent-workbench-settings', 'format_version': True, 'config': {}},
    {'format': 'agent-workbench-settings', 'format_version': 1.0, 'config': {}},
    {'format': 'agent-workbench-settings', 'format_version': 1, 'config': {}, 'secret_status': {}},
    {'config': {}, 'config_revision': 0}, {'version': 2}, {'version': True}, {'version': 1.0},
    {'secrets': {'model': 'SYNTHETIC-imported-secret'}},
    {'providers': [{'api_key': 'SYNTHETIC-imported-secret'}]},
    {'search': {'api_key': 'SYNTHETIC-imported-secret'}}, {'python': {'enabled': 'true'}},
    {'providers': [dict(DEFAULT['providers'][0], base_url='http://localhost:SYNTHETIC-imported-secret/v1')]},
    {'system_policy': 'SYNTHETIC-imported-secret', 'unknown': True}])
async def test_invalid_future_or_secret_backups_are_rejected_without_mutation_or_echo(tmp_path, backup):
    async with serving(tmp_path) as (auth, app, client):
        engine, public = await configured(client, auth, app)
        before = saved_state(engine)
        response = await preview(client, auth, public['config_revision'], backup)
        assert response.status == 400
        assert 'SYNTHETIC' not in await response.text()
        assert saved_state(engine) == before


@pytest.mark.parametrize('revision', [None, True, 0.0, '0', -1, 1])
async def test_preview_requires_current_exact_revision_before_validation(tmp_path, monkeypatch, revision):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        monkeypatch.setattr(server, 'preview_settings_import', reject_call)
        response = await preview(client, auth, revision, {'broken': True})
        assert response.status == 409 and (await response.json())['code'] == 'settings_changed'


@pytest.mark.parametrize('status', ['running', 'waiting', 'stopping'])
async def test_preview_respects_active_work_before_validation(tmp_path, monkeypatch, status):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        engine.runs['fixture'] = {'id': 'fixture', 'status': status, 'agent_ids': []}
        monkeypatch.setattr(server, 'preview_settings_import', reject_call)
        response = await preview(client, auth, 0, {})
        assert response.status == 409 and '実行中' in (await response.json())['error']


@pytest.mark.parametrize('race', ['save', 'active'])
async def test_preview_rechecks_ownership_after_awaiting_body(tmp_path, monkeypatch, race):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        entered, release = asyncio.Event(), asyncio.Event()
        original_body = server.body
        async def observed(request):
            if request.path == '/api/config/import-preview':
                entered.set()
            return await original_body(request)
        monkeypatch.setattr(server, 'body', observed)
        payload = json.dumps({'config_revision': 0, 'backup': DEFAULT}).encode()
        async def chunks():
            yield payload[:1]
            await release.wait()
            yield payload[1:]
        async with ClientSession(cookie_jar=client.cookie_jar) as second:
            pending = asyncio.create_task(second.post(auth.origin + '/api/config/import-preview', data=chunks(),
                headers={'Origin': auth.origin, 'Content-Type': 'application/json'}))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                if race == 'save':
                    response = await put_config(client, auth, 0, copy.deepcopy(DEFAULT))
                    assert response.status == 200
                else:
                    engine.runs['fixture'] = {'id': 'fixture', 'status': 'waiting', 'agent_ids': []}
                before = saved_state(engine)
                monkeypatch.setattr(server, 'preview_settings_import', reject_call)
                release.set()
                response = await asyncio.wait_for(pending, 5)
                assert response.status == 409 and saved_state(engine) == before
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def test_transfer_endpoints_enforce_browser_auth_origin_and_body_shape(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        response = await client.get(auth.origin + '/api/config/export')
        assert response.status == 401
        response = await preview(client, auth, 0, {})
        assert response.status == 401
        await bootstrap(auth, client)
        for path, method in [('/api/config/export', 'get'), ('/api/config/import-preview', 'post')]:
            response = await getattr(client, method)(auth.origin + path, json={}, headers={'Origin': 'https://other.invalid'})
            assert response.status == 403
        response = await client.post(auth.origin + '/api/config/import-preview', json={})
        assert response.status == 403
        before = saved_state(app[APP_KEY])
        for data in ['["SYNTHETIC-body-secret"]', '{not-json-SYNTHETIC-body-secret']:
            response = await client.post(auth.origin + '/api/config/import-preview', data=data,
                headers={'Origin': auth.origin, 'Content-Type': 'application/json'})
            assert response.status == 400 and 'SYNTHETIC' not in await response.text()
        response = await client.post(auth.origin + '/api/config/import-preview',
            json={'config_revision': 0, 'backup': {}, 'check_paths': False}, headers={'Origin': auth.origin})
        assert response.status == 400 and saved_state(app[APP_KEY]) == before


async def test_missing_saved_paths_boot_ui_but_block_work_and_sync_until_strict_save(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    config = missing_config(tmp_path)
    path = state / 'settings.json'
    original = json.dumps(config, ensure_ascii=False).encode('utf-8-sig')
    path.write_bytes(original)
    calls = []
    async def sync(_self, config):
        calls.append(copy.deepcopy(config))
    monkeypatch.setattr(CopilotBridgeManager, 'sync', sync)
    monkeypatch.setattr(CopilotBridgeManager, 'ensure', reject_call)
    monkeypatch.setattr('workbench.diagnostics.diagnose_provider', reject_call)
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        public = await read_config(client, auth)
        assert public['config'] == config and len(public['settings_storage']['warnings']) == 10
        assert path.read_bytes() == original and calls == []
        assert public['copilot_agent_status']['enabled'] is True
        assert public['copilot_agent_status']['ready'] is False
        assert public['copilot_agent_status']['state'] == 'configuration_required'
        engine.schedule_copilot_sync(force=True)
        assert engine._copilot_sync_task is None and engine._copilot_desired is None
        response = await client.post(auth.origin + '/api/run-preflight', json={}, headers={'Origin': auth.origin})
        result = await response.json()
        assert response.status == 200 and result['can_start'] is False
        assert result['blockers'][0]['code'] == 'settings_recovery_required'
        for endpoint, payload, code in [('/api/runs', {}, 400),
                ('/api/copilot-agent-start', {'config_revision': 0}, 409),
                ('/api/provider-test', {'provider_id': 'local'}, 409)]:
            response = await client.post(auth.origin + endpoint, json=payload, headers={'Origin': auth.origin})
            assert response.status == code
            result = await response.json()
            if code == 409:
                assert result['code'] == 'settings_recovery_required'
        assert engine.runs == {} and engine.agents == {} and calls == []
        backup = await (await client.get(auth.origin + '/api/config/export')).json()
        assert backup == wrapped(config)
        response = await preview(client, auth, 0, DEFAULT)
        assert response.status == 200 and (await response.json())['warnings'] == []
        assert engine.settings.restore_warnings and path.read_bytes() == original
        response = await put_config(client, auth, 0, config)
        assert response.status == 400 and engine.settings.restore_warnings and calls == []
        with monkeypatch.context() as patch:
            def failed_replace(*args):
                raise OSError('Synthetic failed settings write')
            patch.setattr('workbench.config.os.replace', failed_replace)
            response = await put_config(client, auth, 0, copy.deepcopy(DEFAULT))
            assert response.status == 503 and engine.settings.restore_warnings and calls == []
            assert path.read_bytes() == original and engine.settings.revision == 0
        repaired = copy.deepcopy(DEFAULT)
        repaired['providers'][0]['model'] = 'fixture-local'
        response = await put_config(client, auth, 0, repaired)
        assert response.status == 200
        assert (await response.json())['settings_storage']['warnings'] == []
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert calls == [DEFAULT['copilot_agent']]
        assert engine.settings.restore_warnings == [] and path.read_bytes() != original
        payload = {'task': 'Fixture admission only; never infer', 'pm_profile': 'local', 'max_workers': 0}
        result = engine.preflight(payload)
        assert result['can_start'] is True and result['blockers'] == []
        admitted = []
        monkeypatch.setattr(engine, 'kick', lambda agent: admitted.append(agent.id))
        result = await engine.start_run(payload)
        assert result['run']['status'] == 'running' and len(admitted) == 1


@pytest.mark.parametrize('data', ['{broken', '[]', '{"secrets": {"key":"SYNTHETIC"}}',
                                '{"version":2}', '{"python":{"enabled":"true"}}'])
def test_startup_recovery_does_not_accept_corrupt_shapes_secrets_or_future_schema(tmp_path, data):
    path = tmp_path / 'settings.json'
    path.write_text(data, encoding='utf-8')
    original = path.read_bytes()
    with pytest.raises(ValueError):
        Settings(tmp_path)
    assert path.read_bytes() == original


def test_existing_bad_type_is_not_treated_as_a_missing_path_at_startup(tmp_path):
    file = tmp_path / 'not-a-folder'
    file.write_text('fixture')
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'paths': {'read_roots': [str(file)]}}))
    original = path.read_bytes()
    with pytest.raises(ValueError):
        Settings(tmp_path)
    assert path.read_bytes() == original


def test_reappearing_path_does_not_silently_release_recovery_until_saved(tmp_path):
    exe = tmp_path / 'old python' / 'python.exe'
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'python': {'executable': str(exe)}}))
    settings = Settings(tmp_path)
    assert settings.restore_warnings
    exe.parent.mkdir()
    exe.write_text('fixture; never executed')
    assert settings.public()['settings_storage']['warnings']
    settings.save(settings.value)
    assert settings.public()['settings_storage']['warnings'] == []
