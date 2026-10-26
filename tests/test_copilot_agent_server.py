"""Authenticated loopback routes with a fake bridge; no bridge or inference starts."""
import asyncio
import copy
from contextlib import asynccontextmanager
import socket

import pytest
from aiohttp import web

from test_config_server import bootstrap, serving
from workbench import engine as engine_module, server
from workbench.config import DEFAULT, Settings
from workbench.server import APP_KEY


class FakeManager:
    instances = []

    def __init__(self, directory):
        self.directory = directory
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = 0
        self.closed = False
        self.fail = False
        self.current = {'state': 'disabled', 'ready': False, 'owned': False, 'message': ''}
        self.instances.append(self)

    def status(self, config):
        return {**self.current, 'enabled': config['enabled']}

    async def sync(self, config):
        self.calls.append(copy.deepcopy(config))
        if not config['enabled']:
            self.current.update(state='disabled', ready=False, owned=False)
            return self.status(config)
        self.current.update(state='starting', ready=False)
        self.entered.set()
        try:
            await self.release.wait()
            if self.fail:
                raise ValueError('synthetic-private-start-failure')
            self.current.update(state='ready', ready=True, owned=True)
            return self.status(config)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise

    async def ensure(self, config):
        raise AssertionError('server configuration/diagnostics must not start an inference run')

    async def close(self):
        self.closed = True
        self.current.update(state='closed', ready=False, owned=False)


@pytest.fixture(autouse=True)
def fake_manager(monkeypatch):
    FakeManager.instances = []
    monkeypatch.setattr(engine_module, 'CopilotBridgeManager', FakeManager)


async def get_config(client, auth):
    response = await client.get(auth.origin + '/api/config')
    assert response.status == 200
    return await response.json()


async def put_config(client, auth, public, enabled):
    config = copy.deepcopy(public['config'])
    config['copilot_agent']['enabled'] = enabled
    return await client.put(auth.origin + '/api/config',
        json={'config_revision': public['config_revision'], 'config': config},
        headers={'Origin': auth.origin})


async def retry(client, auth, revision):
    return await client.post(auth.origin + '/api/copilot-agent-start',
        json={'config_revision': revision}, headers={'Origin': auth.origin})


async def settle(engine):
    await asyncio.wait_for(asyncio.shield(engine._copilot_sync_task), 2)


async def enable(client, auth, engine):
    response = await asyncio.wait_for(put_config(client, auth, await get_config(client, auth), True), 2)
    assert response.status == 200
    public = await response.json()
    await asyncio.wait_for(engine.copilot_bridge.entered.wait(), 2)
    return public


async def test_startup_off_and_status_shutdown_clear_secrets(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        engine = app[APP_KEY]
        manager = engine.copilot_bridge
        await bootstrap(auth, client)
        await settle(engine)
        public = await get_config(client, auth)
        assert public['effective_providers'] == public['config']['providers']
        assert public['copilot_agent_status']['state'] == 'disabled'
        response = await client.get(auth.origin + '/api/copilot-agent-status')
        assert await response.json() == public['copilot_agent_status']
        assert len(manager.calls) == 1 and manager.calls[0]['enabled'] is False
        assert not engine.settings.path.exists()
        engine.settings.secrets['local'] = 'synthetic-server-secret'
    assert manager.closed and engine.closed
    assert engine.settings.secrets == {}


async def test_saved_on_startup_does_not_wait_for_bridge(tmp_path):
    config = copy.deepcopy(DEFAULT)
    config['copilot_agent']['enabled'] = True
    Settings(tmp_path / 'state').save(config)
    async with serving(tmp_path) as (auth, app, client):
        engine = app[APP_KEY]
        await bootstrap(auth, client)
        public = await asyncio.wait_for(get_config(client, auth), 2)
        await asyncio.wait_for(engine.copilot_bridge.entered.wait(), 2)
        assert public['effective_providers'][0]['id'] == 'copilot-agent'
        assert public['copilot_agent_status']['ready'] is False
        assert public['copilot_agent_status']['state'] == 'starting'
        assert not engine.copilot_bridge.release.is_set()
    assert engine.copilot_bridge.cancelled == 1
    assert engine.copilot_bridge.closed


async def test_save_on_identical_save_and_off_are_background(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        manager = engine.copilot_bridge
        await settle(engine)
        public = await enable(client, auth, engine)
        assert public['config_revision'] == 1
        assert public['copilot_agent_status']['state'] == 'starting'
        assert Settings(engine.settings.directory).value['copilot_agent']['enabled'] is True
        response = await put_config(client, auth, public, True)
        assert response.status == 200
        public = await response.json()
        assert public['config_revision'] == 2
        assert [row['enabled'] for row in manager.calls] == [False, True]
        assert manager.cancelled == 0
        response = await asyncio.wait_for(put_config(client, auth, public, False), 2)
        assert response.status == 200
        public = await response.json()
        await settle(engine)
        assert [row['enabled'] for row in manager.calls] == [False, True, False]
        assert manager.cancelled == 1
        assert public['effective_providers'] == public['config']['providers']
        assert (await get_config(client, auth))['copilot_agent_status']['state'] == 'disabled'


async def test_failed_start_is_public_status_and_explicit_retry_only(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        manager = engine.copilot_bridge
        await settle(engine)
        manager.fail = True
        manager.release.set()
        public = await enable(client, auth, engine)
        await settle(engine)
        public = await get_config(client, auth)
        assert public['copilot_agent_status']['state'] == 'error'
        assert 'synthetic-private-start-failure' not in str(public)
        calls = len(manager.calls)
        # Reading status does not retry a failed launch.
        await client.get(auth.origin + '/api/copilot-agent-status')
        assert len(manager.calls) == calls
        manager.fail = False
        response = await retry(client, auth, public['config_revision'])
        assert response.status == 200
        await settle(engine)
        public = await get_config(client, auth)
        assert public['copilot_agent_status']['ready'] is True
        assert public['config_revision'] == 1
        assert len(manager.calls) == calls + 1


async def test_repeated_retry_does_not_restart_pending_or_ready_bridge(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        public = await enable(client, auth, engine)
        manager = engine.copilot_bridge
        original = engine._copilot_sync_task
        for _ in range(2):
            response = await retry(client, auth, public['config_revision'])
            assert response.status == 200
            assert (await response.json())['copilot_agent_status']['state'] == 'starting'
        assert engine._copilot_sync_task is original
        assert manager.cancelled == 0
        manager.release.set()
        await settle(engine)
        calls = len(manager.calls)
        response = await retry(client, auth, public['config_revision'])
        assert response.status == 200
        assert (await response.json())['copilot_agent_status']['ready'] is True
        assert len(manager.calls) == calls


@pytest.mark.parametrize('revision', [None, False, 1.0, -1, 0, '1'])
async def test_retry_rejects_missing_wrong_type_or_stale_revision(tmp_path, revision):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        await enable(client, auth, engine)
        calls = len(engine.copilot_bridge.calls)
        response = await retry(client, auth, revision)
        assert response.status == 409
        assert (await response.json())['code'] == 'settings_changed'
        assert len(engine.copilot_bridge.calls) == calls


async def test_retry_disabled_does_not_enable_or_save(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        response = await retry(client, auth, 0)
        assert response.status == 409
        assert (await response.json())['code'] == 'copilot_agent_disabled'
        assert engine.settings.revision == 0 and not engine.settings.path.exists()
        assert len(engine.copilot_bridge.calls) == 1


async def test_active_team_blocks_save_and_retry_without_restarting(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        public = await enable(client, auth, engine)
        before = engine.settings.path.read_bytes()
        calls = len(engine.copilot_bridge.calls)
        monkeypatch.setattr(engine, 'active', lambda: True)
        assert (await retry(client, auth, public['config_revision'])).status == 409
        assert (await put_config(client, auth, public, False)).status == 409
        assert engine.settings.path.read_bytes() == before
        assert len(engine.copilot_bridge.calls) == calls


async def test_failed_atomic_save_does_not_schedule_bridge(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        public = await get_config(client, auth)
        calls = len(engine.copilot_bridge.calls)
        def fail(_value):
            raise OSError('synthetic-save-error')
        monkeypatch.setattr(engine, 'save_settings', fail)
        response = await put_config(client, auth, public, True)
        assert response.status == 503
        assert len(engine.copilot_bridge.calls) == calls
        assert engine.settings.revision == 0


@pytest.mark.parametrize('changed', ['revision', 'active'])
async def test_retry_rechecks_ownership_after_body_arrives(tmp_path, monkeypatch, changed):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        public = await enable(client, auth, engine)
        engine.copilot_bridge.fail = True
        engine.copilot_bridge.release.set()
        await settle(engine)
        entered, release = asyncio.Event(), asyncio.Event()
        original = server.body
        async def paused_body(request):
            value = await original(request)
            entered.set()
            await release.wait()
            return value
        monkeypatch.setattr(server, 'body', paused_body)
        pending = asyncio.create_task(retry(client, auth, public['config_revision']))
        await asyncio.wait_for(entered.wait(), 2)
        if changed == 'revision':
            engine.save_settings(copy.deepcopy(engine.settings.value))
        else:
            monkeypatch.setattr(engine, 'active', lambda: True)
        calls = len(engine.copilot_bridge.calls)
        release.set()
        response = await pending
        assert response.status == 409
        assert len(engine.copilot_bridge.calls) == calls


async def test_new_routes_require_auth_and_same_origin(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        assert (await client.get(auth.origin + '/api/copilot-agent-status')).status == 401
        response = await client.post(auth.origin + '/api/copilot-agent-start',
            json={'config_revision': 0}, headers={'Origin': auth.origin})
        assert response.status == 401
        await bootstrap(auth, client)
        response = await client.post(auth.origin + '/api/copilot-agent-start',
            json={'config_revision': 0}, headers={'Origin': 'https://other.example'})
        assert response.status == 403


@pytest.mark.parametrize('ready', [False, 1, 'true', None])
async def test_provider_test_requires_strict_ready_without_launch_or_diagnostics(tmp_path, monkeypatch, ready):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        await enable(client, auth, engine)
        monkeypatch.setattr(engine, 'copilot_status', lambda: {'ready': ready, 'state': 'ready', 'message': 'Not ready'})
        from workbench import diagnostics
        async def forbidden(*args):
            raise AssertionError('not-ready bridge must not receive a request')
        monkeypatch.setattr(diagnostics, 'diagnose_provider', forbidden)
        response = await client.post(auth.origin + '/api/provider-test', json={'provider_id': 'copilot-agent'},
                                    headers={'Origin': auth.origin})
        assert response.status == 409
        assert (await response.json())['code'] == 'copilot_bridge_unavailable'


@asynccontextmanager
async def models_endpoint():
    requests = []
    async def models(request):
        requests.append((request.method, request.path))
        return web.json_response({'data': [{'id': 'copilot'}]})
    app = web.Application()
    app.router.add_route('*', '/{path:.*}', models)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen()
    sock.setblocking(False)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    try:
        yield f'http://127.0.0.1:{sock.getsockname()[1]}/v1', requests
    finally:
        await runner.cleanup()
        sock.close()


async def test_ready_effective_copilot_profile_uses_get_models_only(tmp_path):
    async with models_endpoint() as (base_url, requests):
        async with serving(tmp_path) as (auth, app, client):
            await bootstrap(auth, client)
            engine = app[APP_KEY]
            await settle(engine)
            public = await get_config(client, auth)
            public['config']['copilot_agent']['base_url'] = base_url
            engine.copilot_bridge.release.set()
            response = await put_config(client, auth, public, True)
            assert response.status == 200
            await settle(engine)
            assert 'copilot-agent' not in {p['id'] for p in engine.settings.value['providers']}
            response = await client.post(auth.origin + '/api/provider-test', json={'provider_id': 'copilot-agent'},
                                        headers={'Origin': auth.origin})
            assert response.status == 200
            value = await response.json()
            assert value['ok'] is True
            assert value['inference_tested'] is False
            assert value['tools_tested'] is False
            assert requests == [('GET', '/v1/models')]


async def test_explicit_other_profile_diagnostic_survives_copilot_not_ready(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        await enable(client, auth, engine)
        observed = []
        from workbench import diagnostics
        async def diagnose(profile, key):
            observed.append(profile['id'])
            return {'ok': True, 'inference_tested': False}
        monkeypatch.setattr(diagnostics, 'diagnose_provider', diagnose)
        response = await client.post(auth.origin + '/api/provider-test', json={'provider_id': 'local'},
                                    headers={'Origin': auth.origin})
        assert response.status == 200 and observed == ['local']


@pytest.mark.parametrize('model', ['copilot\nfixture', 'copilot\tfixture', 'copilot\x7ffixture'])
async def test_control_character_model_is_rejected_before_atomic_save(tmp_path, model):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        response = await put_config(client, auth, await get_config(client, auth), False)
        assert response.status == 200
        before = await get_config(client, auth)
        saved_bytes = engine.settings.path.read_bytes()
        calls = len(engine.copilot_bridge.calls)
        submitted = copy.deepcopy(before)
        submitted['config']['copilot_agent']['model'] = model
        response = await put_config(client, auth, submitted, True)
        assert response.status == 400
        assert engine.settings.path.read_bytes() == saved_bytes
        assert engine.settings.revision == before['config_revision']
        assert await get_config(client, auth) == before
        assert len(engine.copilot_bridge.calls) == calls


async def test_legacy_same_named_profile_diagnostic_remains_ordinary_when_mode_off(tmp_path, monkeypatch):
    old = copy.deepcopy(DEFAULT)
    old.pop('copilot_agent')
    old['providers'][0].update(id='copilot-agent', model='legacy-local-model',
                               base_url='http://127.0.0.1:11434/v1')
    directory = tmp_path / 'state'
    directory.mkdir()
    import json
    path = directory / 'settings.json'
    path.write_text(json.dumps(old), encoding='utf-8')
    original_bytes = path.read_bytes()
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        await settle(engine)
        observed = []
        from workbench import diagnostics
        async def diagnose(profile, key):
            observed.append((copy.deepcopy(profile), key))
            return {'ok': True, 'inference_tested': False}
        monkeypatch.setattr(diagnostics, 'diagnose_provider', diagnose)
        response = await client.post(auth.origin + '/api/provider-test', json={'provider_id': 'copilot-agent'},
                                    headers={'Origin': auth.origin})
        assert response.status == 200
        assert len(observed) == 1
        assert observed[0][0]['model'] == 'legacy-local-model'
        assert observed[0][0]['base_url'] == old['providers'][0]['base_url']
        assert engine.copilot_status()['ready'] is False
        assert path.read_bytes() == original_bytes


async def test_shutdown_clears_secrets_even_if_manager_close_fails(tmp_path, monkeypatch):
    engine = None
    with pytest.raises(OSError, match='synthetic-close-error'):
        async with serving(tmp_path) as (auth, app, client):
            engine = app[APP_KEY]
            await settle(engine)
            engine.settings.secrets['local'] = 'synthetic-server-secret'
            async def fail_close():
                raise OSError('synthetic-close-error')
            monkeypatch.setattr(engine.copilot_bridge, 'close', fail_close)
    assert engine is not None and engine.settings.secrets == {}
