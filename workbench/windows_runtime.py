"""Fixed Windows utility bridge for frozen builds; no server-global DLL changes.

Only a short-lived helper resets the PyInstaller DLL search. Native utility
children join that helper's kill-on-close Job, so terminating the helper cannot
leave GPU/ACL utility processes behind. Browser launch intentionally has no Job.
"""
from __future__ import annotations

import asyncio
import contextlib
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess
import sys
import threading

from .runtime_paths import FROZEN, INSTALL_ROOT, PROTECTED_ROOTS

LIMIT = 65536
_JOB = None  # Kept open until process teardown; never inherited by children.


def helper_command(operation, argument):
    if not FROZEN or os.name != 'nt':
        raise RuntimeError('The native utility bridge requires a frozen Windows build')
    return [sys.executable, '--internal-windows-utility', operation, str(argument)]


def sanitized_environment(environment=None):
    environment = dict(os.environ if environment is None else environment)
    kept = []
    for value in environment.get('PATH', '').split(os.pathsep):
        path = Path(value.strip('"'))
        if not value or not path.is_absolute():
            continue
        try:
            path = path.resolve()
            if path == Path.cwd().resolve() or any(path.is_relative_to(root) for root in PROTECTED_ROOTS):
                continue
            kept.append(str(path))
        except (OSError, RuntimeError):
            continue
    environment['PATH'] = os.pathsep.join(kept)
    return environment


def _reset_helper_dll_search():
    # Never call from the server. No thread or external child exists here yet.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    kernel.SetDllDirectoryW.restype = wintypes.BOOL
    if not kernel.SetDllDirectoryW(None):
        raise ctypes.WinError(ctypes.get_last_error())


def _kill_children_on_exit():
    global _JOB
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                    ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    _JOB = handle


def _bounded_native(command, timeout=5):
    """Read at most LIMIT+1 bytes while a watchdog bounds a silent child too."""
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, env=dict(os.environ),
                             cwd=Path(os.environ['SystemRoot']) / 'System32', creationflags=0x08000000)
    timed_out = threading.Event()
    def kill():
        timed_out.set()
        with contextlib.suppress(OSError):
            child.kill()
    watchdog = threading.Timer(timeout, kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        output = child.stdout.read(LIMIT + 1)
        if len(output) > LIMIT:
            raise RuntimeError('Native utility exceeded its output limit')
        code = child.wait(timeout=timeout)
        if code or timed_out.is_set():
            raise RuntimeError('Native utility failed or timed out')
        return output
    finally:
        watchdog.cancel()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdout.close()


def _checked_path(argument, *, gpu=False):
    path = Path(argument)
    if not path.is_absolute() or path == Path(path.anchor):
        raise ValueError('An absolute non-root path is required')
    for item in [path, *path.parents]:
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Reparse paths are not accepted by the utility bridge')
    path = path.resolve(strict=True)
    if gpu:
        if path.name.lower() != 'nvidia-smi.exe' or not path.is_file() or path.parent == Path.cwd().resolve() or any(path.is_relative_to(root) for root in PROTECTED_ROOTS):
            raise ValueError('Invalid NVIDIA utility path')
    elif not path.is_dir():
        raise ValueError('State directory does not exist')
    return path


def _checked_browser(argument):
    match = re.fullmatch(r'http://127\.0\.0\.1:([0-9]{1,5})/#token=[A-Za-z0-9_-]{32,128}', argument)
    if not match or not 1 <= int(match[1]) <= 65535:
        raise ValueError('Only a loopback bootstrap URL can be opened')
    return argument


def helper_main(arguments):
    if not FROZEN or os.name != 'nt' or len(arguments) != 2 or arguments[0] not in {'acl', 'gpu', 'browser'}:
        print('Invalid native utility operation', file=sys.stderr)
        return 2
    operation, argument = arguments
    try:
        checked = _checked_browser(argument) if operation == 'browser' else _checked_path(argument, gpu=operation == 'gpu')
        # Validate/import before resetting; only this isolated process is affected.
        if operation != 'browser':
            _kill_children_on_exit()
        environment = sanitized_environment()
        os.chdir(Path(os.environ['SystemRoot']) / 'System32')
        _reset_helper_dll_search()
        os.environ.update(environment)
        if operation == 'browser':
            # Use the Windows URL association, never BROWSER command templates.
            os.startfile(checked)
        elif operation == 'gpu':
            output = _bounded_native([str(checked), '--query-gpu=index,memory.used,memory.total,utilization.gpu', '--format=csv,noheader,nounits'])
            sys.stdout.buffer.write(output)
            sys.stdout.buffer.flush()
        else:
            system = Path(os.environ['SystemRoot']) / 'System32'
            output = _bounded_native([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'])
            match = re.search(rb'S-1-5-[0-9-]+', output)
            if not match:
                raise RuntimeError('Could not determine the Windows user SID')
            sid = match[0].decode('ascii')
            _bounded_native([str(system / 'icacls.exe'), str(checked), '/inheritance:r', '/grant:r',
                             f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'])
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Native utility operation failed: ' + str(exc), file=sys.stderr)
        return 1


def harden_directory(path):
    try:
        result = subprocess.run(helper_command('acl', path), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=15, creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Windows state-directory permission check timed out') from None
    if result.returncode:
        raise RuntimeError('Windows state-directory permissions could not be secured')


async def _read_bounded(stream):
    output = bytearray()
    while True:
        part = await stream.read(min(8192, LIMIT + 1 - len(output)))
        if not part:
            return bytes(output)
        output.extend(part)
        if len(output) > LIMIT:
            raise RuntimeError('Native utility bridge exceeded its output limit')


async def capture_helper(operation, argument, *, timeout):
    spawning = asyncio.create_task(asyncio.create_subprocess_exec(*helper_command(operation, argument),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, creationflags=0x08000000))
    process = None
    try:
        process = await asyncio.shield(spawning)
        async with asyncio.timeout(timeout):
            output = await _read_bounded(process.stdout)
            code = await process.wait()
            if code:
                raise RuntimeError('Native utility operation failed')
            return output
    finally:
        # Cancellation can arrive during CreateProcess. Finish acquiring its
        # handle before terminating it; its kill-on-close Job reaps descendants.
        while not spawning.done():
            try:
                await asyncio.shield(spawning)
            except asyncio.CancelledError:
                continue
        if process is None and not spawning.cancelled():
            process = spawning.result()
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            # Drain bounded buffered pipe data after termination, avoiding a paused
            # StreamReader transport keeping process.wait() pending on Windows.
            reaping = asyncio.create_task(process.communicate())
            while not reaping.done():
                try:
                    await asyncio.shield(reaping)
                except asyncio.CancelledError:
                    continue
