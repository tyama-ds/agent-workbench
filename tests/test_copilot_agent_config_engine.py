"""Opt-in routing and lifecycle admission, with no Copilot or model traffic."""
import asyncio
import copy
import json
from contextlib import asynccontextmanager

import pytest

from workbench.config import DEFAULT, Settings, validate_settings, effective_profiles
from workbench.providers import ProviderClient, ProviderError
from test_engine import configured, ScriptClient


class FakeBridge:
    def __init__(self, *, ready=True):
        self.ready = ready
        self.syncs = []
        self.ensure_calls = 0
        self.closed = False
        self.on_ensure = None

    def status(self, config):
        ready = config['enabled'] and self.ready
        return {'enabled': config['enabled'], 'state': 'ready' if ready else 'disabled' if not config['enabled'] else 'error',
                'ready': ready, 'message': 'fixture ready' if ready else 'fixture unavailable', 'owned': False}

    async def sync(self, config):
        self.syncs.append(copy.deepcopy(config))
        self.ready = config['enabled']
        return self.status(config)

    async def ensure(self, config):
        self.ensure_calls += 1
        if self.on_ensure:
            self.on_ensure()
        if not self.ready:
            raise ValueError('fixture bridge lost')

    async def close(self):
        self.closed = True


def bridge_engine(tmp_path, *, ready=True):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.settings.value['copilot_agent']['enabled'] = True
    engine.copilot_bridge = FakeBridge(ready=ready)
    engine.kick = lambda agent: None
    return engine


def test_old_settings_migrate_off_without_touching_saved_bytes(tmp_path):
    old = copy.deepcopy(DEFAULT)
    del old['copilot_agent']
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(old), encoding='utf-8')
    before = path.read_bytes()
    settings = Settings(tmp_path)
    assert settings.value['copilot_agent']['enabled'] is False
    assert path.read_bytes() == before
    assert effective_profiles(settings.value) == old['providers']


@pytest.mark.parametrize('change', [
    {'enabled': 'true'}, {'enabled': 1}, {'model': ''}, {'model': 'copilot\n'},
    {'model': 'co\tpilot'}, {'model': 'copilot\x7f'}, {'startup_timeout_seconds': True},
    {'startup_timeout_seconds': 4}, {'startup_timeout_seconds': 1201},
    {'base_url': 'http://192.168.1.10:8800/v1'}, {'base_url': 'https://example.com/v1'},
    {'base_url': 'http://127.0.0.1:8800/v1?key=x'}, {'base_url': 'http://127.0.0.1:8800/other'},
    {'base_url': 'http://127.0.0.1/v1'},
    {'bridge_directory': 'relative'}, {'python_executable': 'cmd.exe'}, {'command': 'anything'},
])
def test_bridge_config_rejects_invalid_or_arbitrary_command_fields(change):
    with pytest.raises(ValueError):
        validate_settings({'copilot_agent': change})


def test_virtual_profile_is_reserved_and_does_not_mutate_saved_profiles():
    config = validate_settings({'copilot_agent': {'enabled': True}})
    before = copy.deepcopy(config)
    profiles = effective_profiles(config)
    assert profiles[0]['id'] == 'copilot-agent'
    assert profiles[0]['kind'] == 'local' and profiles[0]['model'] == 'copilot'
    assert not profiles[0]['api_key_env'] and not profiles[0]['proxy_url']
    profiles[0]['base_url'] = 'changed'
    assert config == before
    config['providers'][0]['id'] = 'copilot-agent'
    with pytest.raises(ValueError, match='予約'):
        validate_settings(config)


async def test_old_same_named_profile_remains_usable_while_mode_is_off(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    config = copy.deepcopy(engine.settings.value)
    config['providers'][0]['id'] = 'copilot-agent'
    del config['copilot_agent']
    engine.settings.path.write_text(json.dumps(config), encoding='utf-8')
    before = engine.settings.path.read_bytes()
    engine.settings = Settings(engine.settings.directory)
    try:
        assert not engine.settings.value['copilot_agent']['enabled']
        assert engine.settings.path.read_bytes() == before
        assert '_copilot_agent' not in effective_profiles(engine.settings.value)[0]
        preview = engine.preflight({'task': 'Legacy profile', 'pm_profile': 'copilot-agent', 'max_workers': 0})
        assert preview['can_start'] is True
        assert not any(w['code'] == 'copilot_bridge_destination' for w in preview['warnings'])
        result = await engine.start_run({'task': 'Legacy profile', 'pm_profile': 'copilot-agent', 'max_workers': 0})
        assert result['run']['pm_profile'] == 'copilot-agent'
        enabled = copy.deepcopy(engine.settings.value)
        enabled['copilot_agent']['enabled'] = True
        with pytest.raises(ValueError, match='予約'):
            engine.settings.save(enabled)
        assert engine.settings.path.read_bytes() == before
    finally:
        await engine.close()


async def test_on_defaults_pm_and_workers_to_bridge_and_preserves_run_identity(tmp_path):
    engine = bridge_engine(tmp_path)
    try:
        original = copy.deepcopy(engine.settings.value)
        payload = {'task': 'Fixture assignment', 'max_workers': 2}
        preview = engine.preflight(payload)
        assert preview['can_start'] is True
        assert preview['destinations'][0]['profile_id'] == 'copilot-agent'
        assert engine.copilot_bridge.ensure_calls == 0  # Preflight remains network-free.
        result = await engine.start_run(payload)
        run = engine.runs[result['run']['id']]
        pm = engine.agents[run['pm_agent_ids'][0]]
        assert run['pm_profiles'] == run['worker_profiles'] == ['copilot-agent']
        assert engine.configured_profile(pm)['model'] == 'copilot'
        assert engine.message_eligibility(pm)['allowed'] is True
        assert engine.settings.value == original
        assert engine.public_config()['config']['providers'] == original['providers']
        assert engine.public_config()['effective_providers'][0]['id'] == 'copilot-agent'
        assert engine.copilot_bridge.ensure_calls == 1
    finally:
        await engine.close()


async def test_explicit_profile_remains_available_and_off_never_routes_to_bridge(tmp_path):
    engine = bridge_engine(tmp_path, ready=False)
    try:
        result = await engine.start_run({'task': 'Explicit local', 'pm_profile': 'local', 'max_workers': 0})
        assert result['run']['pm_profile'] == 'local'
        assert engine.copilot_bridge.ensure_calls == 0
        engine.settings.value['copilot_agent']['enabled'] = False
        preview = engine.preflight({'task': 'No hidden bridge', 'pm_profile': 'copilot-agent'})
        assert preview['can_start'] is False
        assert preview['blockers'][0]['code'] == 'invalid_selection'
    finally:
        await engine.close()


async def test_unavailable_bridge_never_falls_back_or_creates_run(tmp_path):
    engine = bridge_engine(tmp_path, ready=False)
    try:
        payload = {'task': 'Fixture assignment'}
        preview = engine.preflight(payload)
        assert preview['can_start'] is False
        assert preview['blockers'][0]['code'] == 'copilot_bridge_unavailable'
        with pytest.raises(ValueError, match='unavailable'):
            await engine.start_run(payload)
        assert not engine.runs and not engine.agents
        engine.copilot_bridge.ready = True
        engine.copilot_bridge.on_ensure = lambda: setattr(engine.copilot_bridge, 'ready', False)
        with pytest.raises(ValueError, match='bridge lost'):
            await engine.start_run(payload)
        assert not engine.runs
    finally:
        await engine.close()


async def test_settings_change_during_connection_check_does_not_start_stale_run(tmp_path):
    engine = bridge_engine(tmp_path)
    try:
        engine.copilot_bridge.on_ensure = lambda: engine.settings.value['copilot_agent'].update(enabled=False)
        with pytest.raises(ValueError, match='設定が変更'):
            await engine.start_run({'task': 'Fixture assignment'})
        assert not engine.runs
    finally:
        await engine.close()


async def test_toggle_cancels_startup_then_reconciles_off_once(tmp_path):
    engine = bridge_engine(tmp_path)
    starting, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def sync(config):
        calls.append(config['enabled'])
        if config['enabled']:
            starting.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                await release.wait()
        return engine.copilot_bridge.status(config)

    engine.copilot_bridge.sync = sync
    try:
        engine.schedule_copilot_sync()
        await starting.wait()
        engine.schedule_copilot_sync()  # Saving the same settings cannot duplicate startup.
        assert engine.copilot_status()['state'] == 'starting'
        engine.settings.value['copilot_agent']['enabled'] = False
        engine.schedule_copilot_sync()
        await cleanup.wait()
        engine.schedule_copilot_sync(force=True)  # Must not interrupt cleanup a second time.
        release.set()
        await engine._copilot_sync_task
        assert calls == [True, False]
        assert engine.copilot_status()['enabled'] is False
    finally:
        release.set()
        await engine.close()
    assert engine.copilot_bridge.closed is True


async def test_managed_bridge_keeps_queue_timeout_and_conversation_but_no_gpu_or_retry():
    admissions, requests = [], []

    class Gate:
        @asynccontextmanager
        async def slot(self, config):
            admissions.append(config)
            yield {}

    gate = Gate()
    client = ProviderClient(gate, copilot_gate=gate)
    async def post(endpoint, body, headers, timeout, proxy):
        requests.append((endpoint, body, headers, timeout, proxy))
        raise ProviderError('Busy', status=503, retryable=True)
    client._post = post
    local = {'gpu_guard_enabled': True, 'max_retries': 3, 'max_concurrent_requests': 1,
             'queue_timeout_seconds': 44, 'request_timeout_seconds': 55}
    profile = effective_profiles(validate_settings({'copilot_agent': {'enabled': True}}))[0]
    with pytest.raises(ProviderError, match='Busy'):
        await client.complete(profile, [{'role': 'user', 'content': 'fixture'}], [], 'fixture',
                              {'local': local}, conversation_id='run/agent')
    assert len(requests) == len(admissions) == 1
    assert admissions[0]['gpu_guard_enabled'] is False
    assert admissions[0]['queue_timeout_seconds'] == 44
    assert local['gpu_guard_enabled'] is True and local['max_retries'] == 3
    assert requests[0][2]['X-Conversation-Id'] == 'run/agent'
    assert requests[0][3] == 55 and requests[0][4] is None
    legacy = {key: value for key, value in profile.items() if key != '_copilot_agent'}
    with pytest.raises(ProviderError, match='Busy'):
        await client.complete(legacy, [{'role': 'user', 'content': 'fixture'}], [], 'fixture',
                              {'local': {**local, 'max_retries': 0}})
    assert admissions[-1]['gpu_guard_enabled'] is True
