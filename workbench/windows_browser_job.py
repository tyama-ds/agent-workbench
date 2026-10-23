"""Lifecycle/resource limits for a fixed, trusted Selenium worker on Windows.

A Job Object is NOT a filesystem, network, or privilege sandbox. The worker
and browsers run with the caller's normal Windows permissions. Never use this
runner for model-supplied Python, executable paths, or command-line arguments.
The caller owns private-storage cleanup, after this runner confirms that every
process in the Job has stopped. No installed-file ACL or firewall is modified.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import math
import os
from pathlib import Path
import stat
import subprocess
import threading
import time

from .windows_sandbox import (
    SandboxError, _ExtendedLimits, _Native, _Process, _SecurityAttributes,
    _StartupEx, _StreamData,
)


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ('user', 'kernel', 'period_user', 'period_kernel')] + [
        ('page_faults', W.DWORD), ('total_processes', W.DWORD),
        ('active_processes', W.DWORD), ('terminated_processes', W.DWORD),
    ]


def _environment(workspace: Path) -> dict[str, str]:
    # Runtime paths and browser profiles are supplied explicitly by the trusted
    # worker. Never forward API keys, proxy variables, PATH or host profile paths.
    return {'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows'),
            'TEMP': str(workspace), 'TMP': str(workspace), 'LOCALAPPDATA': str(workspace)}


def _named_stream(native, path, *, live):
    """Inspect ADS; only a disappearing live entry can be ignored.

    Browser caches routinely rename/delete files between directory enumeration
    and opening their stream information. Access errors and other failures are
    still fatal. The shared LPAC scanner intentionally remains unchanged.
    """
    data = _StreamData()
    handle = native.k.FindFirstStreamW(str(path), 0, ctypes.byref(data), 0)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error == 38:  # ERROR_HANDLE_EOF: no streams.
            return False
        if live and error in (2, 3):  # FILE_NOT_FOUND / PATH_NOT_FOUND.
            return None
        raise SandboxError(f'Cannot inspect browser storage streams (Windows error {error})')
    try:
        while True:
            if data.name != '::$DATA':
                return True
            if not native.k.FindNextStreamW(handle, ctypes.byref(data)):
                error = ctypes.get_last_error()
                if error == 38:
                    return False
                if live and error in (2, 3):
                    return None
                raise SandboxError(f'Cannot inspect browser storage streams (Windows error {error})')
    finally:
        native.k.FindClose(handle)


def _workspace_ok(directory: Path, maximum: int, native, *, live=False, max_entries=2048):
    """Bound live storage without mistaking ordinary cache removal for escape.

    The pinned root must always exist. Only missing descendants are tolerated
    during execution; the final scan after Job termination is strict. As with
    the Python storage watchdog, this is not a hard filesystem quota.
    """
    root = directory.lstat()
    if not stat.S_ISDIR(root.st_mode) or getattr(root, 'st_file_attributes', 0) & 0x400:
        return False
    pending, count, size = [directory], 0, 0
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return False
            streams = _named_stream(native, current, live=live and current != directory)
            if streams is None:
                continue
            if streams:
                return False
            with os.scandir(current) as entries:
                for entry in entries:
                    count += 1
                    if count > max_entries:
                        return False
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if getattr(info, 'st_file_attributes', 0) & 0x400 or stat.S_ISLNK(info.st_mode):
                            return False
                        if stat.S_ISDIR(info.st_mode):
                            pending.append(Path(entry.path))
                        else:
                            streams = _named_stream(native, entry.path, live=live)
                            if streams is None:
                                continue
                            if streams:
                                return False
                            size += info.st_size
                            if size > maximum:
                                return False
                    except FileNotFoundError:
                        if not live:
                            raise
        except FileNotFoundError:
            if not live or current == directory:
                raise
    return True


def _stop_job(native, job, timeout=5.0):
    # Even a naturally exited root can leave a browser/driver grandchild alive.
    # Check the accounting after termination; a failed TerminateJobObject is
    # harmless only if the Job is independently confirmed empty.
    native.k.TerminateJobObject(job, 1)
    deadline = time.monotonic() + timeout
    accounting = _Accounting()
    while True:
        if not native.k.QueryInformationJobObject(job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
            raise SandboxError('Cannot verify browser Job termination; private storage retained', preserve_private=True)
        if accounting.active_processes == 0:
            return
        if time.monotonic() >= deadline:
            raise SandboxError('Browser descendants did not stop; private storage retained', preserve_private=True)
        time.sleep(.025)


def run_browser_job(command: list[str], workspace: Path, *, timeout: float,
                    memory_mb: int, output_limit: int, workspace_limit: int,
                    cancel: threading.Event | None = None) -> dict:
    """Run only the fixed trusted worker, then stop and account for its tree."""
    if os.name != 'nt':
        raise SandboxError('The managed Selenium worker requires Windows Job Objects')
    if not command or not all(isinstance(arg, str) and '\0' not in arg for arg in command):
        raise SandboxError('Invalid trusted browser worker command')
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
               for value in (timeout, memory_mb, output_limit, workspace_limit)):
        raise SandboxError('Browser resource limits must be positive numbers')
    if cancel is not None and cancel.is_set():
        return {'exit_code': None, 'stdout': '', 'stderr': '', 'termination_reason': 'cancelled', 'isolation': 'windows-job'}
    workspace = Path(workspace).absolute()
    info = workspace.lstat()
    if not workspace.is_dir() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise SandboxError('Browser workspace must be an existing regular directory')
    native = _Native()
    k = native.k
    k.QueryInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.c_void_p]
    k.QueryInformationJobObject.restype = W.BOOL
    handles, readers = set(), []
    process = _Process()
    job, workspace_handle, attributes = None, None, None
    assigned = initialized = drained = False
    data = {'stdout': bytearray(), 'stderr': bytearray()}
    output_lock, output_exceeded = threading.Lock(), threading.Event()

    def close(handle):
        if handle and handle in handles:
            k.CloseHandle(handle)
            handles.remove(handle)

    try:
        workspace_handle = k.CreateFileW(str(workspace), 0x20000, 3, None, 3, 0x02200000, None)
        if workspace_handle == ctypes.c_void_p(-1).value:
            workspace_handle = None
            raise SandboxError('Cannot hold browser private storage')
        job = native.check(k.CreateJobObjectW(None, None), 'CreateJobObject(browser)')
        handles.add(job)
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x8 | 0x100 | 0x200 | 0x400
        limits.basic.active = 32
        limits.process_memory = limits.job_memory = int(memory_mb * 1024 * 1024)
        native.check(k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), 'SetInformationJobObject(browser)')
        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        child_handles = []
        for stream in ('stdin', 'stdout', 'stderr'):
            read, write = W.HANDLE(), W.HANDLE()
            native.check(k.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0), 'CreatePipe(browser)')
            handles.update((read.value, write.value))
            child, parent = (read.value, write.value) if stream == 'stdin' else (write.value, read.value)
            child_handles.append(child)
            native.check(k.SetHandleInformation(parent, 1, 0), 'SetHandleInformation(browser)')
            if stream == 'stdin':
                close(parent)
                continue

            def reader(handle=parent, label=stream):
                buffer, read_size = ctypes.create_string_buffer(4096), W.DWORD()
                while k.ReadFile(handle, buffer, len(buffer), ctypes.byref(read_size), None) and read_size.value:
                    with output_lock:
                        available = int(output_limit) - sum(len(value) for value in data.values())
                        data[label].extend(buffer.raw[:min(available, read_size.value)])
                        if read_size.value > available:
                            output_exceeded.set()
                            break

            readers.append(threading.Thread(target=reader, daemon=True))
        size = ctypes.c_size_t()
        k.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        native.check(k.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)), 'InitializeProcThreadAttributeList(browser)')
        initialized = True
        inherit = (W.HANDLE * len(child_handles))(*child_handles)
        native.check(k.UpdateProcThreadAttribute(attributes, 0, 0x20002, ctypes.byref(inherit), ctypes.sizeof(inherit), None, None), 'UpdateProcThreadAttribute(browser handles)')
        startup = _StartupEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100
        startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = child_handles
        startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
        environment = _environment(workspace)
        env = ctypes.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(environment.items())) + '\0\0')
        cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        flags = 0x80000 | 0x8000000 | 0x400 | 0x4  # Extended, NO_WINDOW, Unicode, suspended.
        native.check(k.CreateProcessW(command[0], cmd, None, None, True, flags, env, str(workspace),
                                     ctypes.byref(startup), ctypes.byref(process)), 'CreateProcessW(browser worker)')
        handles.update((process.process, process.thread))
        native.check(k.AssignProcessToJobObject(job, process.process), 'AssignProcessToJobObject(browser)')
        assigned = True
        for handle in child_handles:
            close(handle)
        for thread in readers:
            thread.start()
        if k.ResumeThread(process.thread) == 0xffffffff:
            raise SandboxError('Cannot resume browser worker')
        start, reason = time.monotonic(), None
        while True:
            status = k.WaitForSingleObject(process.process, 50)
            if status == 0:
                break
            if status != 258:
                raise SandboxError('Cannot wait for browser worker')
            if cancel is not None and cancel.is_set():
                reason = 'cancelled'
            elif time.monotonic() - start >= timeout:
                reason = 'timeout'
            elif output_exceeded.is_set():
                reason = 'output_limit'
            else:
                try:
                    if not _workspace_ok(workspace, workspace_limit, native, live=True):
                        reason = 'workspace_limit'
                except (OSError, SandboxError):
                    reason = 'workspace_changed'
            if reason:
                break
        _stop_job(native, job)
        drained = True
        code = W.DWORD()
        native.check(k.GetExitCodeProcess(process.process, ctypes.byref(code)), 'GetExitCodeProcess(browser)')
        for thread in readers:
            thread.join(5)
        if any(thread.is_alive() for thread in readers):
            raise SandboxError('Could not drain browser worker output', preserve_private=True)
        if output_exceeded.is_set():
            reason = reason or 'output_limit'
        if reason is None and not _workspace_ok(workspace, workspace_limit, native):
            reason = 'workspace_limit'
        return {'exit_code': code.value, 'stdout': bytes(data['stdout']).decode('utf-8', errors='replace'),
                'stderr': bytes(data['stderr']).decode('utf-8', errors='replace'),
                'termination_reason': reason, 'isolation': 'windows-job'}
    finally:
        cleanup_error = None
        if process.process and not assigned:
            k.TerminateProcess(process.process, 1)
            if k.WaitForSingleObject(process.process, 5000) != 0:
                cleanup_error = SandboxError('Unassigned browser worker did not stop; private storage retained', preserve_private=True)
        if job and not drained:
            try:
                _stop_job(native, job)
            except SandboxError as exc:
                cleanup_error = exc
        for thread in readers:
            if thread.ident:
                thread.join(5)
        for handle in list(handles):
            close(handle)
        if initialized:
            k.DeleteProcThreadAttributeList(attributes)
        if workspace_handle:
            k.CloseHandle(workspace_handle)
        if cleanup_error is not None:
            raise cleanup_error
