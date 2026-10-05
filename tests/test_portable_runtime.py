"""Portable boundaries and helper lifecycle; Windows cases use real Jobs."""
import asyncio
import ctypes
from ctypes import wintypes
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from workbench import windows_runtime as bridge
from workbench.runtime_paths import RESOURCE_ROOT, INSTALL_ROOT


def test_source_roots_are_identical():
    assert INSTALL_ROOT == RESOURCE_ROOT == Path(__file__).resolve().parents[1]


def test_frozen_roots_protect_outer_executable(tmp_path, monkeypatch):
    import workbench.runtime_paths as paths
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'AgentWorkbench.exe'))
    spec = importlib.util.spec_from_file_location('isolated_paths', paths.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.INSTALL_ROOT == tmp_path
    assert module.RESOURCE_ROOT == RESOURCE_ROOT
    assert set(module.PROTECTED_ROOTS) == {tmp_path, RESOURCE_ROOT}


def test_bridge_does_not_allow_generic_operation_or_source_use(capsys):
    assert bridge.helper_main(['execute', 'calc.exe']) == 2
    assert bridge.helper_main(['gpu', 'nvidia-smi.exe', '--arbitrary']) == 2
    with pytest.raises(RuntimeError, match='frozen Windows'):
        bridge.helper_command('gpu', 'nvidia-smi.exe')


@pytest.mark.parametrize('value', ['https://127.0.0.1:80/#token=' + 'x'*43,
    'http://example.com:80/#token=' + 'x'*43, 'http://127.0.0.1:0/#token=' + 'x'*43,
    'http://127.0.0.1:99999/#token=' + 'x'*43, 'http://127.0.0.1:80/path#token=' + 'x'*43,
    'http://127.0.0.1:80/#token=' + 'x'*43 + '&other=1'])
def test_browser_bridge_rejects_non_bootstrap_urls(value):
    with pytest.raises(ValueError):
        bridge._checked_browser(value)


def test_browser_bridge_accepts_exact_loopback():
    value = 'http://127.0.0.1:8818/#token=' + 'x'*43
    assert bridge._checked_browser(value) == value


def test_child_path_removes_bundled_relative_and_cwd_entries(tmp_path, monkeypatch):
    install, cwd, trusted = (tmp_path / name for name in ('install', 'cwd', 'trusted'))
    for path in (install, cwd, trusted):
        path.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(bridge, 'PROTECTED_ROOTS', (install,))
    source = {'PATH': os.pathsep.join([str(install), str(install / '_internal'), '.', '', str(cwd), str(trusted)]), 'KEPT': 'value'}
    result = bridge.sanitized_environment(source)
    assert result['PATH'] == str(trusted)
    assert result['KEPT'] == 'value'
    assert source['PATH'] != result['PATH']


def test_checked_paths_reject_missing_relative_root_and_wrong_gpu(tmp_path):
    for value in ('.', str(tmp_path.anchor), str(tmp_path / 'absent')):
        with pytest.raises((ValueError, OSError)):
            bridge._checked_path(value)
    ordinary = tmp_path / 'other.exe'
    ordinary.write_text('fixture')
    with pytest.raises(ValueError):
        bridge._checked_path(str(ordinary), gpu=True)


@pytest.mark.asyncio
async def test_helper_reader_enforces_limit_while_reading():
    stream = asyncio.StreamReader()
    stream.feed_data(b'x' * (bridge.LIMIT + 100))
    with pytest.raises(RuntimeError, match='output limit'):
        await bridge._read_bounded(stream)


@pytest.mark.asyncio
async def test_cancellation_during_spawn_still_kills_and_reaps(monkeypatch):
    entered, released = asyncio.Event(), asyncio.Event()
    class Process:
        returncode = None
        killed = reaped = False
        def kill(self):
            self.killed = True
            self.returncode = -1
        async def communicate(self):
            self.reaped = True
            return b'', None
    process = Process()
    async def spawn(*args, **kwargs):
        entered.set()
        await released.wait()
        return process
    monkeypatch.setattr(bridge, 'helper_command', lambda *args: ['fixed-helper'])
    monkeypatch.setattr(bridge.asyncio, 'create_subprocess_exec', spawn)
    task = asyncio.create_task(bridge.capture_helper('gpu', 'fixed-path', timeout=1))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert process.killed and process.reaped


@pytest.mark.asyncio
async def test_helper_timeout_kills_and_reaps(monkeypatch):
    class Process:
        returncode = None
        killed = reaped = False
        stdout = asyncio.StreamReader()
        def kill(self):
            self.killed = True
            self.returncode = -1
        async def communicate(self):
            self.reaped = True
            return b'', None
    process = Process()
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(bridge, 'helper_command', lambda *args: ['fixed-helper'])
    monkeypatch.setattr(bridge.asyncio, 'create_subprocess_exec', spawn)
    with pytest.raises(TimeoutError):
        await bridge.capture_helper('gpu', 'fixed-path', timeout=.01)
    assert process.killed and process.reaped


@pytest.mark.skipif(os.name != 'nt', reason='Windows kernel Job lifecycle')
def test_windows_job_kills_native_descendant_when_helper_terminated():
    script = """
import subprocess, sys, time
from workbench.windows_runtime import _kill_children_on_exit
_kill_children_on_exit()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print(child.pid, flush=True)
time.sleep(60)
"""
    helper = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    handle = None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        # A timer prevents a failed handshake hanging the CI worker.
        import threading
        watchdog = threading.Timer(15, lambda: helper.kill() if helper.poll() is None else None)
        watchdog.start()
        try:
            line = helper.stdout.readline().strip()
        finally:
            watchdog.cancel()
        assert line.isdigit(), helper.stderr.read() if helper.poll() is not None else line
        handle = kernel.OpenProcess(0x100000, False, int(line))  # SYNCHRONIZE
        assert handle
        assert kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT: child alive
        helper.kill()
        helper.wait(timeout=10)
        assert kernel.WaitForSingleObject(handle, 10000) == 0  # child reaped by Job
    finally:
        if helper.poll() is None:
            helper.kill()
        helper.wait(timeout=10)
        helper.stdout.close()
        helper.stderr.close()
        if handle:
            kernel.CloseHandle(handle)


@pytest.mark.skipif(os.name != 'nt', reason='Windows native process watchdog/output bound')
def test_windows_native_output_bound_and_timeout():
    with pytest.raises(RuntimeError, match='output limit'):
        bridge._bounded_native([sys.executable, '-c', "import sys; sys.stdout.write('x'*1000000)"], timeout=10)
    with pytest.raises(RuntimeError, match='timed out'):
        bridge._bounded_native([sys.executable, '-c', 'import time; time.sleep(60)'], timeout=.1)


def test_helper_gpu_rejects_outer_install_directory(tmp_path, monkeypatch):
    install = tmp_path / 'installed'
    install.mkdir()
    candidate = install / 'nvidia-smi.exe'
    candidate.write_bytes(b'fixture')
    monkeypatch.setattr(bridge, 'PROTECTED_ROOTS', (install,))
    with pytest.raises(ValueError, match='NVIDIA'):
        bridge._checked_path(str(candidate), gpu=True)


def test_browser_helper_sanitizes_before_chdir_and_ignores_browser_command(tmp_path, monkeypatch):
    from types import SimpleNamespace
    original = tmp_path / 'untrusted-cwd'
    original.mkdir()
    windows = tmp_path / 'Windows'
    system = windows / 'System32'
    system.mkdir(parents=True)
    monkeypatch.chdir(original)
    events = []
    environment = {'SystemRoot': str(windows), 'PATH': os.pathsep.join([str(original), str(system)]),
                   'BROWSER': 'arbitrary-program %s'}
    fake_os = SimpleNamespace(name='nt', pathsep=os.pathsep, environ=environment,
        chdir=lambda path: events.append(('chdir', str(path))),
        startfile=lambda url: events.append(('startfile', url)))
    monkeypatch.setattr(bridge, 'os', fake_os)
    monkeypatch.setattr(bridge, 'FROZEN', True)
    monkeypatch.setattr(bridge, '_reset_helper_dll_search', lambda: events.append(('reset', None)))
    value = 'http://127.0.0.1:8818/#token=' + 'x'*43
    assert bridge.helper_main(['browser', value]) == 0
    assert environment['PATH'] == str(system)
    assert events == [('chdir', str(system)), ('reset', None), ('startfile', value)]
