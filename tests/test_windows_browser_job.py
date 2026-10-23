"""Trusted browser Job lifecycle checks; these do not claim OS access isolation."""
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import windows_browser_job as browser_job
from workbench.windows_sandbox import SandboxError


def test_environment_does_not_forward_host_secrets_or_profile(tmp_path, monkeypatch):
    for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'HTTP_PROXY', 'HTTPS_PROXY', 'PATH', 'USERPROFILE', 'PYTHONPATH'):
        monkeypatch.setenv(key, 'must-not-forward')
    monkeypatch.setenv('LOCALAPPDATA', 'host-private-profile')
    env = browser_job._environment(tmp_path)
    assert set(env) == {'SystemRoot', 'TEMP', 'TMP', 'LOCALAPPDATA'}
    assert all(env[key] == str(tmp_path) for key in ('TEMP', 'TMP', 'LOCALAPPDATA'))
    assert 'must-not-forward' not in env.values()


def _fake_job(active, *, query=True, terminate=True, total=2, wait=0):
    counts = iter(active)
    calls = []
    def stop(handle, code):
        calls.append((handle, code))
        return terminate
    def info(handle, kind, output, size, returned):
        if kind == 1:
            value = ctypes.cast(output, ctypes.POINTER(browser_job._Accounting)).contents
            value.active_processes = next(counts)
            value.total_processes = total
        elif kind == 3:
            value = ctypes.cast(output, ctypes.POINTER(browser_job._ProcessIds)).contents
            value.assigned = value.listed = 2
            value.pids[0], value.pids[1] = 11, 12
        elif kind == 9:
            value = ctypes.cast(output, ctypes.POINTER(browser_job._ExtendedLimits)).contents
            value.basic.flags, value.basic.active = 0x2308, 32
            value.job_memory = 12345
        return query
    def seal(handle, kind, value, size):
        limits = ctypes.cast(value, ctypes.POINTER(browser_job._ExtendedLimits)).contents
        assert limits.basic.active == 0
        assert limits.basic.flags == 0x2308 and limits.job_memory == 12345
        calls.append('sealed')
        return True
    def member(handle, job, output):
        ctypes.cast(output, ctypes.POINTER(ctypes.wintypes.BOOL)).contents.value = True
        return True
    def wait_for(handle, millis):
        calls.append(('wait', handle))
        return wait
    return SimpleNamespace(k=SimpleNamespace(
        TerminateJobObject=stop, QueryInformationJobObject=info, SetInformationJobObject=seal,
        OpenProcess=lambda access, inherit, pid: pid + 100, IsProcessInJob=member,
        WaitForSingleObject=wait_for, CloseHandle=lambda handle: calls.append(('close', handle)))), calls


def test_stop_waits_for_all_descendants(monkeypatch):
    native, calls = _fake_job([3, 1, 0])
    monkeypatch.setattr(browser_job.time, 'sleep', lambda _: None)
    browser_job._stop_job(native, 'job')
    assert calls == ['sealed', ('job', 1), ('wait', 111), ('wait', 112), ('close', 111), ('close', 112)]


def test_failed_terminate_is_ok_only_if_independently_empty():
    native, _ = _fake_job([0], terminate=False)
    browser_job._stop_job(native, 'job')


@pytest.mark.parametrize('active,query', [(1, True), (0, False)])
def test_unknown_or_live_descendants_preserve_private_storage(active, query):
    native, _ = _fake_job([active], query=query, terminate=False)
    with pytest.raises(SandboxError) as caught:
        browser_job._stop_job(native, 'job', timeout=0)
    assert caught.value.preserve_private


def test_zero_job_accounting_is_not_a_process_exit_barrier():
    native, calls = _fake_job([0], wait=258)
    with pytest.raises(SandboxError, match='termination is unconfirmed') as caught:
        browser_job._stop_job(native, 'job', timeout=0)
    assert caught.value.preserve_private
    assert ('wait', 111) in calls and ('close', 112) in calls


def test_missing_lifetime_handle_never_certifies_termination():
    native, calls = _fake_job([0], total=3)
    with pytest.raises(SandboxError, match='history is incomplete') as caught:
        browser_job._stop_job(native, 'job')
    assert caught.value.preserve_private
    assert ('wait', 111) in calls and ('wait', 112) in calls


def test_member_capture_refuses_truncated_snapshot():
    def info(handle, kind, output, size, returned):
        value = ctypes.cast(output, ctypes.POINTER(browser_job._ProcessIds)).contents
        value.assigned, value.listed = 3, 2
        return True
    native = SimpleNamespace(k=SimpleNamespace(QueryInformationJobObject=info))
    with pytest.raises(SandboxError, match='enumerate every') as caught:
        browser_job._capture_members(native, 'job', {})
    assert caught.value.preserve_private


def test_member_capture_rejects_reused_pid_and_bounds_history():
    native, calls = _fake_job([0])
    native.k.IsProcessInJob = lambda handle, job, output: True  # BOOL remains false.
    members = {}
    browser_job._capture_members(native, 'job', members)
    assert not members
    assert calls == [('close', 111), ('close', 112)]
    with pytest.raises(SandboxError, match='history limit'):
        browser_job._capture_members(native, 'job', {pid: pid for pid in range(100, 4196)})


@pytest.mark.skipif(os.name != 'nt', reason='Windows argument handling')
@pytest.mark.parametrize('limit', [0, -1, True, float('nan'), float('inf')])
def test_invalid_limits_do_not_launch(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(browser_job, '_Native', lambda: pytest.fail('Must not launch'))
    with pytest.raises(SandboxError, match='positive'):
        browser_job.run_browser_job(['trusted.exe'], tmp_path, timeout=limit, memory_mb=128,
                                    output_limit=1024, workspace_limit=1024)


@pytest.mark.skipif(os.name != 'nt', reason='Windows cancellation')
def test_pre_cancelled_job_does_not_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_job, '_Native', lambda: pytest.fail('Must not launch'))
    cancel = threading.Event()
    cancel.set()
    result = browser_job.run_browser_job(['trusted.exe'], tmp_path, timeout=1, memory_mb=128,
                                        output_limit=1024, workspace_limit=1024, cancel=cancel)
    assert result['termination_reason'] == 'cancelled'


@pytest.mark.skipif(os.name != 'nt', reason='Windows stream errors')
@pytest.mark.parametrize('error', [2, 3, 5, 32])
def test_stream_scan_ignores_only_missing_live_entries(error):
    def missing(*args):
        ctypes.set_last_error(error)
        return ctypes.c_void_p(-1).value
    native = SimpleNamespace(k=SimpleNamespace(FindFirstStreamW=missing))
    if error in (2, 3):
        assert browser_job._named_stream(native, 'cache', live=True) is None
    else:
        with pytest.raises(SandboxError):
            browser_job._named_stream(native, 'cache', live=True)
    with pytest.raises(SandboxError):
        browser_job._named_stream(native, 'cache', live=False)


@pytest.mark.skipif(os.name != 'nt', reason='Windows stream errors')
@pytest.mark.parametrize('error', [5, 32, 303])
def test_stream_scan_retries_transient_errors_but_requires_verified_result(error, monkeypatch):
    monkeypatch.setattr(browser_job.time, 'sleep', lambda _: None)
    errors = iter([error, 2])
    def first(*args):
        ctypes.set_last_error(next(errors))
        return ctypes.c_void_p(-1).value
    native = SimpleNamespace(k=SimpleNamespace(FindFirstStreamW=first))
    assert browser_job._named_stream(native, 'cache', live=True) is None
    errors = iter([error, 38])
    assert browser_job._named_stream(native, 'cache', live=True) is False
    errors = iter([error]*4)
    with pytest.raises(SandboxError, match=f'Windows error {error}'):
        browser_job._named_stream(native, 'cache', live=True)
    errors = iter([error])
    with pytest.raises(SandboxError, match=f'Windows error {error}'):
        browser_job._named_stream(native, 'cache', live=False)


def test_live_directory_disappearance_and_strict_final_scan(tmp_path, monkeypatch):
    cache = tmp_path/'cache'
    cache.mkdir()
    def scan(native, path, *, live):
        if Path(path) == tmp_path and cache.exists():
            # Return one queued directory, then delete it before its scan.
            return False
        return False
    monkeypatch.setattr(browser_job, '_named_stream', scan)
    original = browser_job.os.scandir
    class DirectoryListing:
        def __enter__(self):
            entries = list(original(tmp_path))
            cache.rmdir()
            return iter(entries)
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(browser_job.os, 'scandir', lambda path: DirectoryListing() if path == tmp_path else original(path))
    assert browser_job._workspace_ok(tmp_path, 1024, None, live=True)
    cache.mkdir()
    with pytest.raises(FileNotFoundError):
        browser_job._workspace_ok(tmp_path, 1024, None)


def test_live_scan_keeps_root_entry_byte_and_link_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_job, '_named_stream', lambda *a, **k: False)
    (tmp_path/'data').write_bytes(b'x'*100)
    assert browser_job._workspace_ok(tmp_path, 100, None, live=True)
    assert not browser_job._workspace_ok(tmp_path, 99, None, live=True)
    assert not browser_job._workspace_ok(tmp_path, 100, None, live=True, max_entries=0)
    with pytest.raises(FileNotFoundError):
        browser_job._workspace_ok(tmp_path/'missing-root', 100, None, live=True)


def _run_python(code, workspace, *, timeout=8, cancel=None, output=4096, memory=128, workspace_limit=1024*1024):
    executable = str(Path(sys.base_prefix)/'python.exe')
    return browser_job.run_browser_job([executable, '-I', '-S', '-B', '-u', '-X', 'utf8', '-c', code],
                                       workspace, timeout=timeout, memory_mb=memory,
                                       output_limit=output, workspace_limit=workspace_limit, cancel=cancel)


def _process_api():
    from ctypes import wintypes as W
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    return kernel


NATIVE = pytest.mark.skipif(os.name != 'nt' or os.environ.get('AWB_TEST_WINDOWS_BROWSER_JOB') != '1',
                           reason='Set AWB_TEST_WINDOWS_BROWSER_JOB=1 for native Windows Job tests')


@NATIVE
@pytest.mark.parametrize('root_mode', ['exit', 'timeout', 'cancel'])
def test_real_job_stops_root_child_and_grandchild(tmp_path, root_mode):
    child_file, grandchild_file = tmp_path/'child.pid', tmp_path/'grandchild.pid'
    root_file, ready_file = tmp_path/'root.pid', tmp_path/'handles-held'
    grandchild = f"import os,time;open({str(grandchild_file)!r},'w').write(str(os.getpid()));time.sleep(60)"
    child = f'''import os,subprocess,sys,time
open({str(child_file)!r},'w').write(str(os.getpid()))
subprocess.Popen([sys.executable,'-I','-S','-c',{grandchild!r}])
time.sleep(60)
'''
    code = f'''import json,os,subprocess,sys,time
open({str(root_file)!r},'w').write(str(os.getpid()))
subprocess.Popen([sys.executable,'-I','-S','-c',{child!r}])
deadline=time.monotonic()+5
while not os.path.exists({str(ready_file)!r}):
    assert time.monotonic()<deadline,'test did not retain child handles'
    time.sleep(.01)
print(json.dumps({{'root':os.getpid()}}),flush=True)
{'pass' if root_mode=='exit' else 'time.sleep(60)'}
'''
    cancel = threading.Event()
    kernel, held, errors = _process_api(), {}, []
    finished = threading.Event()
    def hold_before_stop():
        try:
            deadline = time.monotonic()+8
            while len(held) < 3 and not finished.is_set():
                assert time.monotonic()<deadline, 'process identity handshake timed out'
                for path in (root_file, child_file, grandchild_file):
                    if path in held or not path.exists():
                        continue
                    text = path.read_text()
                    if not text:
                        continue
                    handle = kernel.OpenProcess(0x100000, False, int(text))
                    assert handle, f'Could not retain live PID {text}'
                    held[path] = handle
                    assert kernel.WaitForSingleObject(handle, 0) == 258, 'Process exited before test retained identity'
                time.sleep(.005)
            if len(held) != 3:
                return
            ready_file.touch()
            if root_mode == 'cancel':
                cancel.set()
        except BaseException as exc:
            errors.append(exc)
            cancel.set()
    observer = threading.Thread(target=hold_before_stop)
    observer.start()
    try:
        result = _run_python(code, tmp_path, timeout=2 if root_mode=='timeout' else 10, cancel=cancel)
        assert not errors, errors
        assert child_file.exists() and grandchild_file.exists(), result
        assert result['termination_reason'] == {'exit':None, 'timeout':'timeout', 'cancel':'cancelled'}[root_mode], result
        if root_mode == 'exit':
            assert result['exit_code'] == 0, result
        assert len(held) == 3
        for path, handle in held.items():
            # Identity was retained while alive; PID reuse cannot affect this.
            assert kernel.WaitForSingleObject(handle, 0) == 0, f'{path.name} is still alive'
    finally:
        finished.set()
        observer.join(10)
        for handle in held.values():
            kernel.CloseHandle(handle)


@NATIVE
def test_real_job_environment_memory_and_combined_output(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-do-not-inherit')
    environment = _run_python("import os;assert 'OPENAI_API_KEY' not in os.environ;assert 'USERPROFILE' not in os.environ;print('clean')", tmp_path)
    assert environment['exit_code'] == 0 and environment['stdout'].strip() == 'clean', environment
    memory = _run_python("try:\n x=bytearray(300*1024*1024)\nexcept MemoryError:\n print('memory denied')", tmp_path)
    assert memory['exit_code'] == 0 and memory['stdout'].strip() == 'memory denied', memory
    output = _run_python("import sys;sys.stdout.write('x'*800);sys.stderr.write('y'*800)", tmp_path, output=1024)
    assert output['termination_reason'] == 'output_limit', output
    assert len(output['stdout'].encode())+len(output['stderr'].encode()) == 1024


@NATIVE
def test_real_job_descendants_cannot_break_away(tmp_path):
    code = '''import subprocess,sys
try: subprocess.Popen([sys.executable,'-c','pass'],creationflags=0x01000000)
except OSError as error:
    assert error.winerror==5,repr(error)
    print('breakaway denied')
else: raise AssertionError('child escaped Job')
'''
    result = _run_python(code, tmp_path)
    assert result['exit_code'] == 0 and result['stdout'].strip() == 'breakaway denied', result


@NATIVE
def test_real_job_process_ceiling_applies_to_kernel(tmp_path):
    # Query the Job attached to the actual child, rather than only checking the
    # structure we passed to SetInformationJobObject in the parent.
    code = r'''import ctypes,json
from ctypes import wintypes as W
class Basic(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',W.DWORD),
              ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',W.DWORD),
              ('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.QueryInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.c_void_p]
info=Basic()
assert kernel.QueryInformationJobObject(None,2,ctypes.byref(info),ctypes.sizeof(info),None),ctypes.get_last_error()
assert info.active==32,info.active
assert info.flags & 0x8,info.flags
assert info.flags & 0x2000,info.flags
assert not info.flags & (0x800|0x1000),info.flags
print('kernel limits verified')
'''
    result = _run_python(code, tmp_path)
    assert result['exit_code'] == 0 and result['stdout'].strip() == 'kernel limits verified', result


@NATIVE
def test_real_job_preserves_storage_when_termination_cannot_be_certified(tmp_path, monkeypatch):
    original = browser_job._stop_job
    def uncertain(native, job, timeout=5, **kwargs):
        # Actually stop our test process before injecting the uncertainty.
        original(native, job, timeout, **kwargs)
        raise SandboxError('synthetic unknown termination', preserve_private=True)
    monkeypatch.setattr(browser_job, '_stop_job', uncertain)
    marker = tmp_path/'keep.txt'
    with pytest.raises(SandboxError) as caught:
        _run_python(f"open({str(marker)!r},'w').write('retained')", tmp_path)
    assert caught.value.preserve_private
    assert marker.read_text() == 'retained'


@NATIVE
def test_real_browser_cache_create_rename_delete_is_not_a_failure(tmp_path):
    code = '''import os,time,threading
from pathlib import Path
end=time.monotonic()+3
def writer(index):
    i=0
    while time.monotonic()<end:
        a=Path(f'{index}-{i%32}.tmp');b=a.with_suffix('.cache')
        try:
            a.write_bytes(b'x'*100)
            os.replace(a,b)
            b.unlink()
        except (FileNotFoundError,PermissionError): pass
        i+=1
threads=[threading.Thread(target=writer,args=(i,)) for i in range(4)]
for thread in threads: thread.start()
for thread in threads: thread.join()
print('normal concurrent rename/delete complete')
'''
    result = _run_python(code, tmp_path)
    assert result['exit_code'] == 0 and result['termination_reason'] is None, result
    assert result['stdout'].strip() == 'normal concurrent rename/delete complete'


@NATIVE
def test_real_live_stream_disappearance_is_ignored_but_ads_is_denied(tmp_path, monkeypatch):
    from workbench.windows_sandbox import _Native
    native = _Native()
    cache = tmp_path/'cache'
    original = browser_job._named_stream
    def remove_before_stream_info(native, path, *, live):
        if Path(path) == cache:
            cache.unlink()
        return original(native, path, live=live)
    monkeypatch.setattr(browser_job, '_named_stream', remove_before_stream_info)
    cache.write_text('normal transient cache')
    assert browser_job._workspace_ok(tmp_path, 1024, native, live=True)
    cache.write_text('normal transient cache')
    with pytest.raises(SandboxError, match='Windows error 2'):
        browser_job._workspace_ok(tmp_path, 1024, native)
    monkeypatch.setattr(browser_job, '_named_stream', original)
    cache.write_text('ordinary')
    Path(str(cache)+':hidden').write_text('named stream')
    assert not browser_job._workspace_ok(tmp_path, 1024, native, live=True)
    assert not browser_job._workspace_ok(tmp_path, 1024, native)
