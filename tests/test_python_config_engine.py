"""Python configuration and engine contracts, with no interpreter/sandbox launch."""
import asyncio
import copy
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from workbench import engine as engine_module
from workbench.config import DEFAULT, Settings, validate_settings
from workbench.engine import PYTHON_TOOL, RuntimeBudgetError
from test_engine import ScriptClient, configured, reply, settled, start
from test_multi_pm import multi_start


def enable_python(engine, tmp_path):
    executable = tmp_path / 'python.exe'
    executable.write_bytes(b'not an executable; tests must use the mock runner')
    library = tmp_path / 'existing-libraries'
    library.mkdir()
    engine.settings.value['python'].update(enabled=True, executable=str(executable), library_paths=[str(library)])
    engine.settings.value = validate_settings(engine.settings.value)
    return copy.deepcopy(engine.settings.value['python'])


@pytest.fixture
def windows_engine(monkeypatch):
    # Replace only the module reference; changing os.name globally would affect
    # pathlib and the pytest host while simulating an unsupported platform.
    monkeypatch.setattr(engine_module, 'os', SimpleNamespace(name='nt', environ=os.environ))


def test_old_settings_migrate_to_disabled_python_and_round_trip(tmp_path):
    old = copy.deepcopy(DEFAULT)
    del old['python']
    (tmp_path / 'settings.json').write_text(json.dumps(old), encoding='utf-8')
    settings = Settings(tmp_path)
    assert settings.value['python'] == DEFAULT['python']
    assert settings.value['python']['enabled'] is False
    assert settings.value['python']['network_enabled'] is False
    settings.save(settings.value)
    assert Settings(tmp_path).value['python'] == DEFAULT['python']
    assert settings.public()['capabilities']['python_enabled'] is False


def test_existing_python_settings_default_network_off_and_persist_opt_in(tmp_path):
    old = copy.deepcopy(DEFAULT)
    del old['python']['network_enabled']
    (tmp_path / 'settings.json').write_text(json.dumps(old), encoding='utf-8')
    settings = Settings(tmp_path)
    assert settings.value['python']['network_enabled'] is False
    for enabled in (True, False):
        settings.value['python']['network_enabled'] = enabled
        settings.save(settings.value)
        assert Settings(tmp_path).value['python']['network_enabled'] is enabled


@pytest.mark.parametrize('value', [None, [], 'enabled', {'unexpected': True}, {'enabled': 1},
    {'enabled': 'true'}, {'enabled': None}, {'enabled': True}, {'executable': True},
    {'library_paths': 'site-packages'}, {'library_paths': [True]}, {'library_paths': ['']},
    {'library_paths': ['relative']}, {'library_paths': ['missing'] * 17},
    {'network_enabled': 1}, {'network_enabled': 0}, {'network_enabled': 'true'},
    {'network_enabled': None}, {'network_enabled': []}])
def test_python_config_rejects_wrong_shapes_and_missing_enabled_runtime(value):
    with pytest.raises(ValueError):
        validate_settings({'python': value})


@pytest.mark.parametrize('key,low,high', [('timeout_seconds', 1, 600), ('max_memory_mb', 128, 8192),
                                        ('max_output_bytes', 1024, 1048576)])
def test_python_numeric_bounds_are_integers_with_exact_endpoints(key, low, high):
    for value in (low, high):
        assert validate_settings({'python': {key: value}})['python'][key] == value
    for value in (low - 1, high + 1, True, str(low), float(low), None):
        with pytest.raises(ValueError):
            validate_settings({'python': {key: value}})


def test_python_paths_must_exist_be_absolute_and_libraries_are_deduplicated(tmp_path):
    executable, wrong = tmp_path / 'python.exe', tmp_path / 'other.exe'
    executable.write_bytes(b'fixture')
    wrong.write_bytes(b'fixture')
    library = tmp_path / 'site-packages'
    library.mkdir()
    config = validate_settings({'python': {'enabled': True, 'executable': str(executable),
                                           'library_paths': [str(library), str(library)]}})
    assert config['python']['executable'] == str(executable.absolute())
    assert config['python']['library_paths'] == [str(library.absolute())]
    for path in ('python.exe', str(tmp_path / 'missing.exe'), str(wrong), str(library)):
        with pytest.raises(ValueError):
            validate_settings({'python': {'executable': path}})
    for path in (str(tmp_path / 'missing'), str(executable), str(Path(tmp_path.anchor))):
        with pytest.raises(ValueError):
            validate_settings({'python': {'library_paths': [path]}})


def test_python_schema_describes_typed_input_output_mappings_without_extra_properties():
    spec = PYTHON_TOOL['parameters']
    assert spec['required'] == ['code'] and spec['additionalProperties'] is False
    assert 'network_enabled' not in spec['properties']
    assert spec['properties']['code'] == {'type': 'string', 'maxLength': 200000}
    for key, required in (('inputs', {'path', 'name'}), ('outputs', {'path', 'name', 'expected_sha256'})):
        field = spec['properties'][key]
        assert field['type'] == 'array' and field['maxItems'] == 16
        item = field['items']
        assert item['type'] == 'object' and item['additionalProperties'] is False
        assert set(item['required']) == set(item['properties']) == required
        assert all(value['type'] == 'string' for value in item['properties'].values())


@pytest.mark.asyncio
async def test_python_tools_and_runtime_use_per_run_settings_snapshot(tmp_path, monkeypatch, windows_engine):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    captured = []

    async def fake(config, harness, code, *, on_complete, **kwargs):
        captured.append((copy.deepcopy(config), harness, code, kwargs))
        return {'exit_code': 0, 'stdout': '42', 'stderr': '', 'outputs': [], 'termination_reason': None}

    monkeypatch.setattr(engine_module, 'execute_python', fake)
    try:
        initial = enable_python(engine, tmp_path)
        run, pm = await start(engine, max_delegation_depth=1)
        worker = engine._new_agent(run, 'local', 'helper', pm.id)
        assert all('python_execute' in {tool['name'] for tool in engine._model_tools(run, agent)} for agent in (pm, worker))
        assert 'spawn_worker' not in {tool['name'] for tool in engine._model_tools(run, worker)}
        engine.settings.value['python'].update(enabled=False, timeout_seconds=1)
        engine.settings.value['python']['library_paths'].clear()
        assert (await engine.execute_tool(run, worker, 'python_execute', {'code': 'print(42)'}))['stdout'] == '42'
        assert captured == [(initial, run['_harness'], 'print(42)', {})]
        new, lead = await start(engine)
        assert 'python_execute' not in {tool['name'] for tool in engine._model_tools(new, lead)}
        with pytest.raises(ValueError, match='Python'):
            await engine.execute_tool(new, lead, 'python_execute', {'code': 'print(42)'})
        assert len(captured) == 1
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('network_enabled', [False, True])
async def test_python_network_snapshot_reaches_runner_and_tool_description(
        tmp_path, monkeypatch, windows_engine, network_enabled):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    captured = []

    async def fake(config, harness, code, **kwargs):
        captured.append(config['network_enabled'])
        return {'exit_code': 0, 'stdout': '', 'stderr': '', 'outputs': [], 'termination_reason': None}

    monkeypatch.setattr(engine_module, 'execute_python', fake)
    try:
        enable_python(engine, tmp_path)
        engine.settings.value['python']['network_enabled'] = network_enabled
        run, pm = await start(engine)
        worker = engine._new_agent(run, 'local', 'helper', pm.id)
        engine.settings.value['python']['network_enabled'] = not network_enabled
        for agent in (pm, worker):
            tool = next(tool for tool in engine._model_tools(run, agent) if tool['name'] == 'python_execute')
            assert ('Network access is enabled' if network_enabled else 'Network access is disabled') in tool['description']
            await engine.execute_tool(run, agent, 'python_execute', {'code': 'pass'})
        new, lead = await start(engine)
        await engine.execute_tool(new, lead, 'python_execute', {'code': 'pass'})
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'python_execute',
                                      {'code': 'pass', 'network_enabled': not network_enabled})
        assert captured == [network_enabled, network_enabled, not network_enabled]
        assert 'Network access is' not in PYTHON_TOOL['description']
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_non_windows_python_is_hidden_and_rejected_before_runner(tmp_path, monkeypatch):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_python(engine, tmp_path)
    monkeypatch.setattr(engine_module, 'os', SimpleNamespace(name='posix', environ=os.environ))
    async def forbidden(*args, **kwargs): pytest.fail('Unsupported platform must not reach the runner')
    monkeypatch.setattr(engine_module, 'execute_python', forbidden)
    try:
        run, pm = await start(engine)
        assert 'python_execute' not in {tool['name'] for tool in engine._model_tools(run, pm)}
        with pytest.raises(ValueError, match='Python'):
            await engine.execute_tool(run, pm, 'python_execute', {'code': 'pass'})
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [{}, {'code': 'pass', 'shell': True},
    {'code': 'pass', 'outputs': 'out.txt'}, {'code': 'pass', 'outputs': [{}] * 17},
    {'code': 'pass', 'outputs': [1]}, {'code': 'pass', 'outputs': [{'path': None}]},
    {'code': 'pass', 'outputs': [{'path': '../outside.txt', 'name': 'out.txt', 'expected_sha256': 'missing'}]}])
async def test_python_dispatch_rejects_invalid_arguments_and_output_scope_before_runner(tmp_path, monkeypatch, windows_engine, arguments):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_python(engine, tmp_path)
    async def forbidden(*args, **kwargs): pytest.fail('Invalid dispatch must not reach the runner')
    monkeypatch.setattr(engine_module, 'execute_python', forbidden)
    try:
        run, pm = await start(engine)
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'python_execute', arguments)
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('actor_role', ['other_pm', 'worker'])
async def test_python_outputs_obey_other_agents_reservations(tmp_path, monkeypatch, windows_engine, actor_role):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_python(engine, tmp_path)
    calls = []
    async def fake(*args, **kwargs):
        calls.append(kwargs)
        return {'exit_code': 0, 'outputs': []}
    monkeypatch.setattr(engine_module, 'execute_python', fake)
    try:
        run, (owner, other_pm) = await multi_start(engine)
        actor = other_pm if actor_role == 'other_pm' else engine._new_agent(run, 'local', 'helper', other_pm.id)
        await engine.execute_tool(run, owner, 'reserve_paths', {'paths': ['shared.txt']})
        arguments = {'code': 'pass', 'outputs': [{'path': 'shared.txt', 'name': 'out.txt', 'expected_sha256': 'missing'}]}
        with pytest.raises(ValueError, match='予約中'):
            await engine.execute_tool(run, actor, 'python_execute', arguments)
        assert not calls
        await engine.execute_tool(run, owner, 'python_execute', arguments)
        assert len(calls) == 1  # Owning a reservation does not block its own execution.
        await engine.execute_tool(run, owner, 'release_paths', {})
        await engine.execute_tool(run, actor, 'python_execute', arguments)
        assert len(calls) == 2
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_python_deadline_cancels_and_drains_before_file_lock_is_released(tmp_path, monkeypatch, windows_engine):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    enable_python(engine, tmp_path)
    entered, cancelled, release, cleaned = (asyncio.Event() for _ in range(4))

    async def fake(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()  # Model the runner's job termination and ACL cleanup.
            cleaned.set()
            raise

    monkeypatch.setattr(engine_module, 'execute_python', fake)
    pending = follower = None
    try:
        run, pm = await start(engine)
        run['created_at'] = time.time() - run['_config']['limits']['max_run_seconds'] + .08
        pending = asyncio.create_task(engine.execute_tool(run, pm, 'python_execute', {'code': 'pass'}))
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(cancelled.wait(), 2)
        follower = asyncio.create_task(engine.execute_tool(run, pm, 'write_text',
            {'path': 'late.txt', 'text': 'must not save', 'expected_sha256': 'missing'}))
        await asyncio.sleep(0)
        assert engine.lock.locked() and not pending.done() and not follower.done()
        release.set()
        with pytest.raises(RuntimeBudgetError) as deadline:
            await pending
        assert deadline.value.reason == 'time_limit'
        with pytest.raises(RuntimeBudgetError) as expired:
            await follower
        assert expired.value.reason == 'time_limit'
        assert cleaned.is_set() and not (work / 'late.txt').exists() and not engine.lock.locked()
    finally:
        release.set()
        await asyncio.gather(*(task for task in (pending, follower) if task), return_exceptions=True)
        await engine.close()


@pytest.mark.asyncio
async def test_stop_waits_for_python_cleanup_and_preserves_already_saved_receipt(tmp_path, monkeypatch, windows_engine):
    client = ScriptClient([reply(calls=[('python_execute', {'code': 'pass'})])])
    engine, work = configured(tmp_path, client)
    enable_python(engine, tmp_path)
    entered, cancelled, release = (asyncio.Event() for _ in range(3))

    async def fake(config, harness, code, *, on_complete, **kwargs):
        on_complete(harness.write_bytes('committed.txt', b'committed before stop', 'missing'))
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            raise

    monkeypatch.setattr(engine_module, 'execute_python', fake)
    stopping = None
    try:
        run, pm = await start(engine)
        await asyncio.wait_for(entered.wait(), 2)
        stopping = asyncio.create_task(engine.stop_run(run['id']))
        await asyncio.wait_for(cancelled.wait(), 2)
        assert run['status'] == 'stopping' and not stopping.done()
        release.set()
        await stopping
        assert run['status'] == pm.status == 'stopped'
        assert (work / 'committed.txt').read_bytes() == b'committed before stop'
        assert len(pm.output_receipts) == 1 and pm.output_receipts[0]['tool'] == 'python_execute'
        assert not engine.reservations and not engine.lock.locked()
    finally:
        release.set()
        if stopping: await asyncio.gather(stopping, return_exceptions=True)
        await engine.close()


@pytest.mark.asyncio
async def test_python_saved_receipts_and_output_are_redacted_in_public_state(tmp_path, monkeypatch, windows_engine):
    secret = 'synthetic-python-secret'
    arguments = {'code': 'print("result")', 'inputs': [], 'outputs': [
        {'path': secret + '.txt', 'name': 'result.txt', 'expected_sha256': 'missing'}]}
    engine, work = configured(tmp_path, ScriptClient([reply(calls=[('python_execute', arguments)]),
        reply(calls=[('finish_work', {'summary': 'Saved verified Python output'})])]))
    enable_python(engine, tmp_path)
    engine.settings.secrets['local'] = secret
    loop_thread = threading.get_ident()

    async def fake(config, harness, code, inputs, outputs, *, on_complete):
        assert threading.get_ident() == loop_thread
        receipt = harness.write_bytes(outputs[0]['path'], b'42', outputs[0]['expected_sha256'])
        on_complete(receipt)
        return {'exit_code': 0, 'termination_reason': None, 'stdout': 'stdout ' + secret,
                'stderr': 'stderr ' + secret, 'outputs': [receipt]}

    monkeypatch.setattr(engine_module, 'execute_python', fake)
    try:
        run, pm = await start(engine)
        await settled(engine)
        assert run['status'] == 'done' and (work / (secret + '.txt')).read_bytes() == b'42'
        assert len(pm.output_receipts) == 1 and pm.output_receipts[0]['tool'] == 'python_execute'
        assert pm.output_receipts[0]['bytes'] == 2 and len(pm.output_receipts[0]['sha256']) == 64
        assert secret not in json.dumps(engine.snapshot())
        assert secret not in json.dumps(engine.selected_snapshot(run_id=run['id'], agent_id=pm.id))
        assert '[redacted]' in json.dumps(list(pm.output_receipts))
        assert run['tool_calls'] == 2 and run['model_calls'] == 2
    finally:
        await engine.close()
