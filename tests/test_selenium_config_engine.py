"""Selenium settings/admission contracts without launching a browser."""
import asyncio
import copy
import json
import os
import time
from types import SimpleNamespace

import pytest

from workbench import engine as engine_module
from workbench.config import DEFAULT, Settings, validate_settings
from workbench.engine import SELENIUM_TOOL
from test_engine import ScriptClient, configured, reply, settled, start


def enable_selenium(engine, tmp_path):
    paths = {}
    for name in ('python.exe', 'msedge.exe', 'msedgedriver.exe'):
        path = tmp_path / name
        path.write_bytes(b'fixture: never execute')
        paths[name] = str(path)
    engine.settings.value['python'].update(executable=paths['python.exe'], network_enabled=True)
    engine.settings.value['selenium'].update(enabled=True, browser_executable=paths['msedge.exe'],
                                              driver_executable=paths['msedgedriver.exe'])
    engine.settings.value = validate_settings(engine.settings.value)


@pytest.fixture
def windows_engine(monkeypatch):
    monkeypatch.setattr(engine_module, 'os', SimpleNamespace(name='nt', environ=os.environ))


def test_legacy_settings_migrate_selenium_off_and_persist(tmp_path):
    old = copy.deepcopy(DEFAULT)
    del old['selenium']
    (tmp_path / 'settings.json').write_text(json.dumps(old), encoding='utf-8')
    settings = Settings(tmp_path)
    assert settings.value['selenium'] == DEFAULT['selenium']
    assert settings.value['selenium']['enabled'] is False
    settings.save(settings.value)
    assert Settings(tmp_path).value['selenium'] == DEFAULT['selenium']


@pytest.mark.parametrize('value', [None, [], True, {'enabled': 1}, {'enabled': 'true'},
    {'enabled': True}, {'browser': []}, {'browser': 'firefox'}, {'unknown': True},
    {'browser_executable': True}, {'driver_executable': 'relative.exe'},
    {'library_paths': 'path'}, {'library_paths': [True]}, {'library_paths': ['']},
    {'library_paths': ['missing'] * 17}, {'proxy_url': 'http://user:pass@proxy:8080'},
    {'proxy_url': 'http://proxy/path'}])
def test_selenium_invalid_config(value):
    with pytest.raises(ValueError):
        validate_settings({'selenium': value})


@pytest.mark.parametrize('key,low,high', [('timeout_seconds', 10, 300),
    ('max_memory_mb', 256, 8192), ('max_output_chars', 1000, 100000)])
def test_selenium_limits(key, low, high):
    for value in (low, high):
        assert validate_settings({'selenium': {key: value}})['selenium'][key] == value
    for value in (low - 1, high + 1, True, str(low), float(low), None):
        with pytest.raises(ValueError):
            validate_settings({'selenium': {key: value}})


def test_selenium_requires_runtime_matching_paths_network_but_not_python_tool(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    enable_selenium(engine, tmp_path)
    saved = engine.settings.value
    assert saved['python']['enabled'] is False
    assert validate_settings(saved)['selenium']['enabled'] is True
    for group, key, value in [('python', 'network_enabled', False), ('python', 'executable', ''),
        ('selenium', 'browser', 'chrome'), ('selenium', 'driver_executable', ''),
        ('selenium', 'browser_executable', '')]:
        candidate = copy.deepcopy(saved)
        candidate[group][key] = value
        with pytest.raises(ValueError):
            validate_settings(candidate)
    library = tmp_path / 'existing'
    library.mkdir()
    saved['selenium']['library_paths'] = [str(library), str(library)]
    assert validate_settings(saved)['selenium']['library_paths'] == [str(library)]


def test_selenium_schema_has_only_fixed_operations_and_screenshot():
    spec = SELENIUM_TOOL['parameters']
    assert spec['required'] == ['url'] and spec['additionalProperties'] is False
    assert set(spec['properties']) == {'url', 'actions', 'screenshot'}
    actions = spec['properties']['actions']
    assert actions['maxItems'] == 20 and actions['items']['additionalProperties'] is False
    assert actions['items']['properties']['action']['enum'] == ['click', 'fill', 'read', 'wait']
    assert spec['properties']['screenshot']['required'] == ['path', 'expected_sha256']
    assert 'NOT the Python LPAC' in SELENIUM_TOOL['description']


@pytest.mark.asyncio
async def test_selenium_run_snapshot_tools_preflight_and_disabled_new_run(tmp_path, monkeypatch, windows_engine):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_selenium(engine, tmp_path)
    captured = []
    async def fake(config, python_config, harness, **args):
        captured.append((copy.deepcopy(config), copy.deepcopy(python_config)))
        return {'exit_code': 0, 'outputs': []}
    monkeypatch.setattr(engine_module, 'execute_selenium', fake)
    try:
        preview = engine.preflight({'task': 'Read a page', 'pm_profile': 'local',
                                    'worker_profiles': [], 'max_workers': 0})
        assert preview['can_start'] and not engine.runs and not captured
        assert any(w['code'] == 'selenium_normal_user' for w in preview['warnings'])
        run, pm = await start(engine)
        worker = engine._new_agent(run, 'local', 'helper', pm.id)
        initial = copy.deepcopy(run['_config'])
        engine.settings.value['selenium']['enabled'] = False
        engine.settings.value['python']['network_enabled'] = False
        for agent in (pm, worker):
            names = {t['name'] for t in engine._model_tools(run, agent)}
            assert 'selenium_browse' in names and 'python_execute' not in names
            await engine.execute_tool(run, agent, 'selenium_browse', {'url': 'https://example.com'})
        assert captured == [(initial['selenium'], initial['python'])] * 2
        new, lead = await start(engine)
        assert 'selenium_browse' not in {t['name'] for t in engine._model_tools(new, lead)}
        with pytest.raises(ValueError, match='Selenium'):
            await engine.execute_tool(new, lead, 'selenium_browse', {'url': 'https://example.com'})
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [{}, {'url': 'https://example.com', 'code': 'pass'},
    {'url': 'https://example.com', 'enabled': True}, {'url': 'https://example.com', 'screenshot': None},
    {'url': 'https://example.com', 'screenshot': {'path': '../outside.png', 'expected_sha256': 'missing'}},
    {'url': 'https://example.com', 'screenshot': {'path': 'shot.png'}},
    {'url': 'https://example.com', 'screenshot': {'path': 'shot.png', 'expected_sha256': 'missing', 'code': ''}}])
async def test_selenium_bad_dispatch_never_starts_runner(tmp_path, monkeypatch, windows_engine, arguments):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_selenium(engine, tmp_path)
    async def forbidden(*args, **kwargs): pytest.fail('Invalid input reached runner')
    monkeypatch.setattr(engine_module, 'execute_selenium', forbidden)
    try:
        run, pm = await start(engine)
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'selenium_browse', arguments)
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_selenium_non_windows_hidden_and_rejected(tmp_path, monkeypatch):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_selenium(engine, tmp_path)
    monkeypatch.setattr(engine_module, 'os', SimpleNamespace(name='posix', environ=os.environ))
    try:
        run, pm = await start(engine)
        assert 'selenium_browse' not in {t['name'] for t in engine._model_tools(run, pm)}
        with pytest.raises(ValueError, match='Selenium'):
            await engine.execute_tool(run, pm, 'selenium_browse', {'url': 'https://example.com'})
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_selenium_screenshot_reservations_and_saved_receipt_redaction(tmp_path, monkeypatch, windows_engine):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_selenium(engine, tmp_path)
    secret = 'synthetic-selenium-secret'
    engine.settings.secrets['local'] = secret
    calls = []
    async def fake(config, python_config, harness, *, screenshot, on_complete, **args):
        receipt = harness.write_bytes(screenshot['path'], b'fixture', screenshot['expected_sha256'])
        on_complete(receipt)
        calls.append(receipt)
        return {'exit_code': 0, 'outputs': [receipt]}
    monkeypatch.setattr(engine_module, 'execute_selenium', fake)
    try:
        run, pm = await start(engine)
        worker = engine._new_agent(run, 'local', 'helper', pm.id)
        path = secret + '.png'
        await engine.execute_tool(run, pm, 'reserve_paths', {'paths': [path]})
        arguments = {'url': 'https://example.com', 'screenshot': {'path': path, 'expected_sha256': 'missing'}}
        with pytest.raises(ValueError, match='予約中'):
            await engine.execute_tool(run, worker, 'selenium_browse', arguments)
        assert not calls
        await engine.execute_tool(run, pm, 'selenium_browse', arguments)
        assert (work / path).read_bytes() == b'fixture'
        assert len(pm.output_receipts) == 1 and pm.output_receipts[0]['tool'] == 'selenium_browse'
        assert secret not in json.dumps(engine.snapshot())
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_selenium_deadline_drains_cleanup_before_releasing_file_lock(tmp_path, monkeypatch, windows_engine):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_selenium(engine, tmp_path)
    entered, cancelled, release = (asyncio.Event() for _ in range(3))
    async def fake(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            raise
    monkeypatch.setattr(engine_module, 'execute_selenium', fake)
    task = None
    try:
        run, pm = await start(engine)
        run['created_at'] = time.time() - run['_config']['limits']['max_run_seconds'] + .1
        task = asyncio.create_task(engine.execute_tool(run, pm, 'selenium_browse', {'url': 'https://example.com'}))
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(cancelled.wait(), 2)
        assert engine.lock.locked() and not task.done()
        release.set()
        with pytest.raises(ValueError, match='制限時間'):
            await task
        assert not engine.lock.locked()
    finally:
        release.set()
        if task: await asyncio.gather(task, return_exceptions=True)
        await engine.close()
