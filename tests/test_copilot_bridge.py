"""No Copilot/Edge/inference; mocks, loopback HTTP, and a local Windows Job stub."""
import asyncio
import copy
import ctypes
from ctypes import wintypes
import io
import json
from pathlib import Path
import subprocess
import sys
import time

from aiohttp import web
import pytest

from workbench import copilot_bridge as cb


CONFIG = dict(enabled=True, bridge_directory='', python_executable='',
              base_url='http://127.0.0.1:8800/v1', model='copilot', startup_timeout_seconds=600)
OBSERVED = dict(version='0.1.0', windows=2, busy_windows=0)
REAL_POPEN = subprocess.Popen


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('A real subprocess is prohibited in bridge tests')
    monkeypatch.setattr(cb.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(cb.asyncio, 'create_subprocess_exec', forbidden)


class Owned:
    pid = 12345
    def __init__(self):
        self.code = None
        self.stops = 0
        self.fail_stop = False

    def poll(self):
        return self.code

    async def stop(self):
        self.stops += 1
        self.code = -1
        if self.fail_stop:
            raise OSError('secret must not be exposed')


@pytest.fixture
def setup(monkeypatch, tmp_path):
    state = {'spawned': [], 'probes': 0, 'responses': [None, OBSERVED]}
    async def probe(cfg):
        state['probes'] += 1
        result = state['responses'].pop(0) if len(state['responses']) > 1 else state['responses'][0]
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)
    async def dependencies(python):
        state.setdefault('dependencies', []).append(python)
        return True
    def spawn(python, directory, cfg, state_directory):
        child = Owned()
        state['spawned'].append(child)
        return child
    monkeypatch.setattr(cb, '_probe', probe)
    monkeypatch.setattr(cb, '_bridge_directory', lambda value: tmp_path)
    monkeypatch.setattr(cb, '_python_candidates', lambda value, directory: [tmp_path / 'python.exe'])
    monkeypatch.setattr(cb, '_has_dependencies', dependencies)
    monkeypatch.setattr(cb, '_spawn_owned', spawn)
    monkeypatch.setattr(cb, 'POLL_SECONDS', .001)
    return state


async def test_owned_ready_then_off_stops_only_owned_and_cache_is_pure(setup, tmp_path):
    manager = cb.CopilotBridgeManager(tmp_path)
    before = copy.deepcopy(CONFIG)
    result = await manager.sync(CONFIG)
    assert result['ready'] is True and result['owned'] is True and result['borrowed'] is False
    assert result['enabled'] is True
    assert result['login_verified'] is result['inference_tested'] is False
    calls = setup['probes']
    for _ in range(3):
        assert manager.status(CONFIG) == result
    assert setup['probes'] == calls and CONFIG == before
    result = await manager.sync({**CONFIG, 'enabled': False})
    assert result['state'] == 'disabled' and not result['ready']
    assert result['enabled'] is False
    assert setup['spawned'][0].stops == 1
    await manager.close()
    assert setup['spawned'][0].stops == 1


async def test_existing_valid_bridge_borrowed_even_without_paths(setup, tmp_path):
    setup['responses'] = [OBSERVED]
    manager = cb.CopilotBridgeManager(tmp_path)
    result = await manager.sync(CONFIG)
    assert result['borrowed'] is True and not result['owned']
    assert setup['spawned'] == [] and 'dependencies' not in setup
    await manager.ensure(CONFIG)
    await manager.sync({**CONFIG, 'enabled': False})
    await manager.close()
    assert setup['spawned'] == []


async def test_concurrent_start_is_one_child(setup, tmp_path):
    manager = cb.CopilotBridgeManager(tmp_path)
    results = await asyncio.gather(*(manager.sync(CONFIG) for _ in range(5)))
    assert all(result['ready'] for result in results)
    assert len(setup['spawned']) == 1
    await manager.close()


async def test_existing_wrong_service_is_never_replaced(setup, tmp_path):
    setup['responses'] = [cb.BridgeFailure('unexpected_service', 'wrong service')]
    manager = cb.CopilotBridgeManager(tmp_path)
    result = await manager.sync(CONFIG)
    assert result['code'] == 'unexpected_service' and result['ready'] is False
    assert setup['spawned'] == []


async def test_cancel_start_cleans_before_reraising(setup, tmp_path):
    setup['responses'] = [None]
    manager = cb.CopilotBridgeManager(tmp_path)
    task = asyncio.create_task(manager.sync(CONFIG))
    while not setup['spawned']:
        await asyncio.sleep(0)
    assert manager.status(CONFIG)['state'] == 'starting'
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert setup['spawned'][0].stops == 1
    assert not manager.status(CONFIG)['ready']
    await manager.close()


async def test_off_during_start_stops_old_child(setup, tmp_path):
    setup['responses'] = [None]
    manager = cb.CopilotBridgeManager(tmp_path)
    task = asyncio.create_task(manager.sync(CONFIG))
    while not setup['spawned']:
        await asyncio.sleep(0)
    result = await manager.sync({**CONFIG, 'enabled': False})
    assert result['state'] == 'disabled'
    with pytest.raises(asyncio.CancelledError):
        await task
    assert setup['spawned'][0].stops == 1


async def test_timeout_cleanup_and_no_secret_error(setup, tmp_path, monkeypatch):
    async def stalled(cfg):
        manager._owned = setup_child = Owned()
        setup['spawned'].append(setup_child)
        raise asyncio.TimeoutError
    manager = cb.CopilotBridgeManager(tmp_path)
    monkeypatch.setattr(manager, '_prepare_connect', stalled)
    result = await manager.sync(CONFIG)
    assert result['code'] == 'startup_timeout' and not result['ready']
    assert setup['spawned'][0].stops == 1


async def test_early_exit_also_stops_descendants(setup, tmp_path, monkeypatch):
    setup['responses'] = [None]
    child = Owned()
    child.code = 1
    monkeypatch.setattr(cb, '_spawn_owned', lambda *args: child)
    manager = cb.CopilotBridgeManager(tmp_path)
    result = await manager.sync(CONFIG)
    assert result['code'] == 'startup_failed'
    assert child.stops == 1


async def test_cleanup_failure_blocks_new_start(setup, tmp_path):
    manager = cb.CopilotBridgeManager(tmp_path)
    await manager.sync(CONFIG)
    setup['spawned'][0].fail_stop = True
    stopped = await manager.sync({**CONFIG, 'enabled': False})
    assert stopped['code'] == 'cleanup_failed' and 'secret' not in json.dumps(stopped)
    assert manager.status({**CONFIG, 'enabled': False}) == stopped
    assert stopped['enabled'] is False
    result = await manager.sync(CONFIG)
    assert result['code'] == 'cleanup_failed'
    assert len(setup['spawned']) == 1
    assert 'secret' not in json.dumps(result)


async def test_ensure_never_waits_for_start_or_spawns(setup, tmp_path):
    manager = cb.CopilotBridgeManager(tmp_path)
    with pytest.raises(ValueError, match='準備'):
        await manager.ensure(CONFIG)
    assert setup['spawned'] == [] and setup['probes'] == 0
    await manager.sync(CONFIG)
    setup['responses'] = [None]
    with pytest.raises(ValueError, match='接続'):
        await manager.ensure(CONFIG)
    assert not manager.status(CONFIG)['ready']
    assert len(setup['spawned']) == 1
    await manager.close()


async def test_close_while_starting_rejects_later_start(setup, tmp_path):
    setup['responses'] = [None]
    manager = cb.CopilotBridgeManager(tmp_path)
    task = asyncio.create_task(manager.sync(CONFIG))
    while not setup['spawned']:
        await asyncio.sleep(0)
    await manager.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await manager.sync(CONFIG))['state'] == 'closed'
    assert len(setup['spawned']) == 1 and setup['spawned'][0].stops == 1


async def test_missing_dependencies_no_spawn(setup, tmp_path, monkeypatch):
    async def missing(path):
        return False
    monkeypatch.setattr(cb, '_has_dependencies', missing)
    result = await cb.CopilotBridgeManager(tmp_path).sync(CONFIG)
    assert result['code'] == 'dependencies_missing'
    assert not setup['spawned']


@pytest.mark.parametrize('change', [
    {'enabled': 1}, {'startup_timeout_seconds': True}, {'startup_timeout_seconds': 4},
    {'startup_timeout_seconds': 1201}, {'startup_timeout_seconds': float('nan')},
    {'base_url': 'https://127.0.0.1:8800/v1'}, {'base_url': 'http://evil.invalid:8800/v1'},
    {'base_url': 'http://user:secret@127.0.0.1:8800/v1'},
    {'base_url': 'http://127.0.0.1:8800/v1?secret=x'}, {'base_url': 'http://127.0.0.1:8800/v1#x'},
    {'model': ''}, {'model': 'x\nsecret'}, {'python_executable': []},
])
async def test_invalid_config_has_no_side_effects(change, setup, tmp_path):
    with pytest.raises(ValueError):
        await cb.CopilotBridgeManager(tmp_path).sync({**CONFIG, **change})
    assert setup['spawned'] == [] and setup['probes'] == 0


def test_known_paths_only_and_no_install_discovery(tmp_path, monkeypatch):
    root = tmp_path / 'awb'
    root.mkdir()
    monkeypatch.setattr(cb, 'ROOT', root)
    with pytest.raises(cb.BridgeFailure):
        cb._bridge_directory('')
    directory = tmp_path / 'for-eigyo-pdf-lingua' / 'copilot-bridge'
    (directory / 'bridge').mkdir(parents=True)
    for path in (directory / 'server.py', directory / 'bridge/config.py', directory / 'bridge/edge.py'):
        path.write_text('# fixture', encoding='utf-8')
    assert cb._bridge_directory('') == directory.resolve()
    suffix = Path('Scripts/python.exe') if cb.os.name == 'nt' else Path('bin/python')
    python = directory.parent / '.venv' / suffix
    python.parent.mkdir(parents=True)
    python.touch()
    assert cb._python_candidates('', directory)[0] == python.resolve()
    with pytest.raises(cb.BridgeFailure):
        cb._python_candidates('relative/python.exe', directory)


@pytest.fixture
async def stub():
    state = {'requests': [], 'health': {'ok': True, 'version': '0.1.0'},
             'status': {'version': '0.1.0', 'backend': 'edge', 'model': 'copilot',
                        'windows': [{'id': 'w0', 'busy': False, 'error': ''}],
                        'sessions': [{'key': 'private session not for UI'}]},
             'models': {'object': 'list', 'data': [{'id': 'copilot', 'owned_by': 'copilot-bridge'}]}}
    async def handle(request):
        state['requests'].append((request.method, request.path))
        key = {'/health': 'health', '/status': 'status', '/v1/models': 'models'}.get(request.path)
        if state.get('redirect'):
            raise web.HTTPFound('http://127.0.0.1:1/private')
        if state.get('raw') is not None:
            return web.Response(body=state['raw'])
        return web.json_response(state[key])
    app = web.Application()
    app.router.add_route('*', '/{path:.*}', handle)
    runner = web.AppRunner(app, shutdown_timeout=.1)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    state['config'] = {**CONFIG, 'base_url': f'http://127.0.0.1:{port}/v1'}
    try:
        yield state
    finally:
        await runner.cleanup()


async def test_real_loopback_stub_three_gets_no_inference_or_session_disclosure(stub, tmp_path, monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    manager = cb.CopilotBridgeManager(tmp_path)
    result = await manager.sync(stub['config'])
    assert result['ready'] and result['borrowed']
    assert stub['requests'] == [('GET', '/health'), ('GET', '/status'), ('GET', '/v1/models')]
    assert 'private' not in json.dumps(result)
    await manager.close()
    assert (await cb._probe(stub['config']))['windows'] == 1  # Borrowed service still running.


@pytest.mark.parametrize('change', ['health_only', 'fake', 'model', 'owner', 'windows', 'busy_type', 'duplicate', 'error'])
async def test_loopback_readiness_rejects_partial_wrong_or_fake_service(stub, change):
    if change == 'health_only':
        stub['status'] = {}
    elif change == 'fake':
        stub['status']['backend'] = 'fake'
    elif change == 'model':
        stub['status']['model'] = 'other'
    elif change == 'owner':
        stub['models']['data'][0]['owned_by'] = 'other'
    elif change == 'windows':
        stub['status']['windows'] = []
    elif change == 'busy_type':
        stub['status']['windows'][0]['busy'] = 'false'
    elif change == 'duplicate':
        stub['status']['windows'] *= 2
    else:
        stub['status']['windows'][0]['error'] = 'SECRET_ERROR_CONTENT'
    with pytest.raises(cb.BridgeFailure) as caught:
        await cb._probe(stub['config'])
    assert 'SECRET' not in str(caught.value)


@pytest.mark.parametrize('raw', [b'{"ok":true,"ok":false}', b'{"ok":NaN}', b'\xff', b'x' * (cb.MAX_RESPONSE_BYTES + 1)],
                         ids=['duplicate-key', 'nonfinite', 'invalid-utf8', 'oversize'])
async def test_loopback_malformed_and_bounded_response(stub, raw):
    stub['raw'] = raw
    with pytest.raises(cb.BridgeFailure):
        await cb._probe(stub['config'])


async def test_loopback_redirect_is_never_followed(stub):
    stub['redirect'] = True
    with pytest.raises(cb.BridgeFailure):
        await cb._probe(stub['config'])
    assert stub['requests'] == [('GET', '/health')]


def test_windows_spawn_assigns_job_before_handshake_and_uses_no_shell(tmp_path, monkeypatch):
    if cb.os.name != 'nt':
        pytest.skip('Windows Job subprocess flags')
    events = []
    class Stream(io.BytesIO):
        def write(self, data):
            events.append(('handshake', data))
            return super().write(data)
    class Child:
        pid = 123
        _handle = 456
        stdin = Stream()
    class Job:
        def __init__(self):
            events.append(('job',))
        def assign(self, child):
            events.append(('assign', child.pid))
    def popen(command, **kwargs):
        events.append(('spawn', command, kwargs))
        return Child()
    monkeypatch.setattr(cb, '_WindowsJob', Job)
    monkeypatch.setattr(cb.subprocess, 'Popen', popen)
    monkeypatch.setenv('COPILOT_BRIDGE_MODEL_NAME', 'wrong-model')
    monkeypatch.setenv('COPILOT_BRIDGE_PROFILE_DIR', 'wrong-profile')
    monkeypatch.setenv('COPILOT_BRIDGE_LOG_DIR', 'private-transcript-log')
    owned = cb._spawn_owned(tmp_path / 'python.exe', tmp_path, CONFIG, tmp_path / 'state')
    assert [e[0] for e in events] == ['job', 'spawn', 'assign', 'handshake']
    command, kwargs = events[1][1:]
    assert command[0] == str(tmp_path / 'python.exe') and command[4] == str(tmp_path)
    assert command[-10:] == ['--host', '127.0.0.1', '--port', '8800', '--backend', 'edge', '--profile-mode', 'separate', '--log-dir', '']
    assert kwargs['shell'] is False and kwargs['creationflags'] == subprocess.CREATE_NO_WINDOW
    assert kwargs['stdout'] == kwargs['stderr'] == subprocess.DEVNULL
    assert kwargs['env']['COPILOT_BRIDGE_MODEL_NAME'] == CONFIG['model']
    assert kwargs['env']['COPILOT_BRIDGE_PROFILE_DIR'] == str((tmp_path / 'state/copilot-bridge/profiles').resolve())
    assert cb.os.environ['COPILOT_BRIDGE_MODEL_NAME'] == 'wrong-model'  # Only child env changed.
    assert owned.pid == 123


def test_job_assignment_failure_never_unlocks_bridge(tmp_path, monkeypatch):
    if cb.os.name != 'nt':
        pytest.skip('Windows Job subprocess flags')
    events = []
    class Stream(io.BytesIO):
        def write(self, data):
            events.append('handshake')
            return super().write(data)
    class Child:
        stdin = Stream()
        def poll(self): return None
        def kill(self): events.append('kill')
        def wait(self, timeout): events.append('wait')
    class Job:
        def assign(self, child): raise OSError('assignment failed')
        def close(self): events.append('close_job')
    monkeypatch.setattr(cb, '_WindowsJob', Job)
    monkeypatch.setattr(cb.subprocess, 'Popen', lambda *a, **k: Child())
    with pytest.raises(OSError):
        cb._spawn_owned(tmp_path / 'python.exe', tmp_path, CONFIG, tmp_path / 'state')
    assert events == ['close_job', 'kill', 'wait']


async def test_windows_job_stop_observes_children_even_when_parent_exited():
    events = []
    class Child:
        def poll(self): return 1
        def wait(self, timeout): events.append('parent_wait')
    class Job:
        def terminate(self): events.append('terminate_tree')
        def wait_stopped(self, timeout): events.append('wait_handles')
        def active(self): events.append('observe_tree'); return 0
        def close(self): events.append('close_job')
    await cb._OwnedProcess(Child(), Job()).stop()
    assert events == ['terminate_tree', 'parent_wait', 'wait_handles', 'observe_tree', 'close_job']


async def test_owned_handle_wait_failure_still_closes_job_and_never_claims_cleanup():
    events = []
    class Child:
        def wait(self, timeout): events.append('parent_wait')
    class Job:
        def terminate(self): events.append('terminate_tree')
        def wait_stopped(self, timeout):
            assert timeout == 3
            raise OSError('Owned process exit unconfirmed')
        def active(self): raise AssertionError('Do not claim completion after failed handle wait')
        def close(self): events.append('close_job')
    with pytest.raises(OSError, match='unconfirmed'):
        await cb._OwnedProcess(Child(), Job()).stop()
    assert events == ['terminate_tree', 'parent_wait', 'close_job']


async def test_dependency_probe_cancel_kills_only_probe(monkeypatch, tmp_path):
    entered = asyncio.Event()
    class Child:
        returncode = None
        killed = False
        async def wait(self):
            entered.set()
            if self.killed:
                self.returncode = 1
                return 1
            await asyncio.Event().wait()
        def kill(self): self.killed = True
    child = Child()
    async def spawn(*args, **kwargs):
        assert args[-1] == 'import selenium, pyperclip'
        assert kwargs['stdout'] == kwargs['stderr'] == subprocess.DEVNULL
        return child
    monkeypatch.setattr(cb.asyncio, 'create_subprocess_exec', spawn)
    task = asyncio.create_task(cb._has_dependencies(tmp_path / 'python.exe'))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed and child.returncode == 1


async def test_ensure_does_not_publish_stale_ready_after_off(setup, tmp_path, monkeypatch):
    setup['responses'] = [OBSERVED]
    manager = cb.CopilotBridgeManager(tmp_path)
    await manager.sync(CONFIG)
    entered, resume = asyncio.Event(), asyncio.Event()
    async def probe(cfg):
        entered.set()
        await resume.wait()
        return OBSERVED
    monkeypatch.setattr(cb, '_probe', probe)
    task = asyncio.create_task(manager.ensure(CONFIG))
    await entered.wait()
    disabled = {**CONFIG, 'enabled': False}
    await manager.sync(disabled)
    resume.set()
    with pytest.raises(ValueError, match='変わりました'):
        await task
    assert manager.status(disabled)['state'] == 'disabled'
    assert not manager.status(disabled)['ready']


async def test_new_endpoint_cleans_owned_then_borrows_new_service(setup, tmp_path):
    manager = cb.CopilotBridgeManager(tmp_path)
    await manager.sync(CONFIG)
    setup['responses'] = [OBSERVED]
    result = await manager.sync({**CONFIG, 'base_url': 'http://127.0.0.1:8801/v1'})
    assert result['borrowed'] and result['ready']
    assert len(setup['spawned']) == 1 and setup['spawned'][0].stops == 1
    await manager.close()
    assert setup['spawned'][0].stops == 1


@pytest.mark.skipif(cb.os.name != 'nt', reason='Native Windows Job process containment')
@pytest.mark.parametrize('pause_before_publish', [False, True], ids=['normal', 'paused-receipt'])
async def test_real_windows_job_handshake_and_child_grandchild_cleanup(tmp_path, monkeypatch, pause_before_publish):
    """Exercise the real bootstrap/Job with stdlib-only local fixture processes."""
    stderr_path = tmp_path / 'stub-stderr.txt'
    stderr = stderr_path.open('wb')
    def spawn(*args, **kwargs):
        kwargs['stderr'] = stderr  # Keep fixture diagnostics; product logging stays disabled.
        return REAL_POPEN(*args, **kwargs)
    monkeypatch.setattr(cb.subprocess, 'Popen', spawn)
    ready = tmp_path / 'ready.json'
    grandchild_code = (
        "import os,time\nfrom pathlib import Path\n"
        "pending=Path('grandchild-ready.tmp')\n"
        "with pending.open('w',encoding='ascii') as stream:\n"
        f"    if {pause_before_publish!r}:\n"
        "        Path('writing-receipt').touch()\n"
        "        deadline=time.monotonic()+5\n"
        "        while not Path('publish-receipt').exists():\n"
        "            assert time.monotonic()<deadline\n"
        "            time.sleep(.02)\n"
        "    stream.write(str(os.getpid()))\n"
        "pending.replace('grandchild-ready.txt')\n"
        "time.sleep(60)\n")
    (tmp_path / 'server.py').write_text(
        "import json,os,subprocess,sys,time\n"
        "from pathlib import Path\n"
        f"child=subprocess.Popen([sys.executable,'-c',{grandchild_code!r}],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=open('grandchild-stderr.txt','wb'),"
        "creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "deadline=time.monotonic()+5\n"
        "while not Path('grandchild-ready.txt').exists():\n"
        "    assert time.monotonic()<deadline\n"
        "    time.sleep(.02)\n"
        "Path('ready.tmp').write_text(json.dumps({'pid':os.getpid(),'grandchild_launcher':child.pid,"
        "'grandchild':int(Path('grandchild-ready.txt').read_text(encoding='ascii')),"
        "'argv':sys.argv[1:]}),encoding='utf-8')\n"
        "Path('ready.tmp').replace('ready.json')\n"
        "time.sleep(60)\n", encoding='utf-8')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    owned, handles, details, pause_observed = None, [], None, False
    def diagnostics():
        return repr({path.name: path.read_bytes()[-4096:] for path in
                     (stderr_path, tmp_path / 'grandchild-stderr.txt') if path.exists()})
    try:
        owned = cb._spawn_owned(Path(sys.executable).resolve(), tmp_path, CONFIG, tmp_path / 'state')
        deadline = time.monotonic() + 10
        while details is None:
            assert owned.poll() is None, 'Local stub exited before its ready receipt: ' + diagnostics()
            assert time.monotonic() < deadline, 'Local stub did not become ready: ' + diagnostics()
            if pause_before_publish and not pause_observed and (tmp_path / 'writing-receipt').exists():
                # Exists is not a commit signal for write_text: publish only
                # the closed complete file, even while its staging file is empty.
                assert (tmp_path / 'grandchild-ready.tmp').read_bytes() == b''
                assert not (tmp_path / 'grandchild-ready.txt').exists() and not ready.exists()
                (tmp_path / 'publish-receipt').touch()
                pause_observed = True
            if ready.exists():
                details = json.loads(ready.read_text(encoding='utf-8'))
            await asyncio.sleep(.02)
        assert pause_observed is pause_before_publish
        assert details['argv'] == ['--host', '127.0.0.1', '--port', '8800', '--backend', 'edge',
                                   '--profile-mode', 'separate', '--log-dir', '']
        # Windows venv python.exe may launch the base interpreter. Check that
        # launcher as well as each observed interpreter, without conflating PIDs.
        expected_pids = {owned.pid, details['pid'], details['grandchild_launcher'], details['grandchild']}
        class JobProcesses(ctypes.Structure):
            _fields_ = [('assigned', wintypes.DWORD), ('count', wintypes.DWORD),
                        ('pids', ctypes.c_size_t * 64)]
        processes = JobProcesses()
        assert owned.job.kernel.QueryInformationJobObject(
            owned.job.handle, 3, ctypes.byref(processes), ctypes.sizeof(processes), None)
        assert processes.assigned == processes.count <= 64
        pids = set(processes.pids[:processes.count])
        assert expected_pids <= pids  # Include any Windows runtime helper processes too.
        for pid in pids:
            handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)  # SYNCHRONIZE + QUERY_LIMITED_INFORMATION
            assert handle, 'Could not observe the exact owned process'
            handles.append(handle)
            member = wintypes.BOOL()
            assert kernel.IsProcessInJob(handle, owned.job.handle, ctypes.byref(member))
            assert bool(member.value), 'Stub process is outside the exact owned Job'
            assert kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT: still running
        assert owned.job.active() == len(pids) >= 2
        await owned.stop()
        assert owned.poll() is not None
        assert owned.job.handle is None
        assert all(kernel.WaitForSingleObject(handle, 0) == 0 for handle in handles)
        print(json.dumps({'kind': 'native_windows_job_stub', 'launcher_pid': owned.pid,
                          'child_pid': details['pid'], 'grandchild_launcher_pid': details['grandchild_launcher'],
                          'grandchild_pid': details['grandchild'], 'all_in_exact_job': True,
                          'observed_owned_process_count': len(pids),
                          'paused_incomplete_receipt_was_not_published': pause_observed,
                          'all_process_handles_signaled': True, 'remaining_owned_processes': 0,
                          'actual_bridge_or_browser_started': False}))
    finally:
        # On any assertion failure, kill only this test's owned tree. Stable
        # handles avoid PID reuse; the fixture also has a 60-second backstop.
        try:
            if owned is not None and owned.job.handle is not None:
                await owned.stop()
        finally:
            stderr.close()
            for handle in handles:
                try:
                    assert kernel.WaitForSingleObject(handle, 5000) == 0, 'Owned stub survived cleanup'
                finally:
                    kernel.CloseHandle(handle)
