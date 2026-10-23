"""Windows LPAC process boundary for explicitly configured Python tools.

No unrestricted fallback exists. The Windows kernel enforces the package SID,
network capability policy, child-process restriction and Job Object limits.
Private workspace/profile storage is writable; selected runtime folders are
read-only. Windows resources already exposed to LPAC remain accessible.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid


class SandboxError(RuntimeError):
    def __init__(self, message, *, preserve_private=False):
        super().__init__(message)
        self.preserve_private = preserve_private


class _Trustee(ctypes.Structure):
    _fields_ = [('multiple', ctypes.c_void_p), ('operation', W.DWORD), ('form', W.DWORD),
                ('kind', W.DWORD), ('name', ctypes.c_void_p)]


class _Access(ctypes.Structure):
    _fields_ = [('permissions', W.DWORD), ('mode', W.DWORD), ('inheritance', W.DWORD), ('trustee', _Trustee)]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [('length', W.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', W.BOOL)]


class _Startup(ctypes.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                ('x', W.DWORD), ('y', W.DWORD), ('xsize', W.DWORD), ('ysize', W.DWORD),
                ('xchars', W.DWORD), ('ychars', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                ('show', W.WORD), ('reserved_count', W.WORD), ('reserved_bytes', ctypes.c_void_p),
                ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]


class _StartupEx(ctypes.Structure):
    _fields_ = [('startup', _Startup), ('attributes', ctypes.c_void_p)]


class _Process(ctypes.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]


class _Capabilities(ctypes.Structure):
    _fields_ = [('sid', ctypes.c_void_p), ('capabilities', ctypes.c_void_p), ('count', W.DWORD), ('reserved', W.DWORD)]


class _SidAttributes(ctypes.Structure):
    _fields_ = [('sid', ctypes.c_void_p), ('attributes', W.DWORD)]


class _StreamData(ctypes.Structure):
    _fields_ = [('size', ctypes.c_int64), ('name', W.WCHAR * 296)]


class _BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', W.DWORD),
                ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t), ('active', W.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ('reads', 'writes', 'others', 'read_bytes', 'write_bytes', 'other_bytes')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', _BasicLimits), ('io', _IOCounters), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


def _capability_names(network_enabled):
    if type(network_enabled) is not bool:
        raise SandboxError('Python network_enabled must be a boolean')
    # Internet client excludes unsolicited public inbound connections. Windows
    # exposes LAN connectivity only as the combined client/server capability.
    return ('registryRead', 'internetClient', 'privateNetworkClientServer') if network_enabled else ('registryRead',)


def _derive_capabilities(native, names, allocations):
    """Keep every allocated SID alive through process creation and track cleanup."""
    cap_sids = []
    for name in names:
        group_array, cap_array = ctypes.c_void_p(), ctypes.c_void_p()
        group_count, cap_count = W.DWORD(), W.DWORD()
        native.check(native.b.DeriveCapabilitySidsFromName(name, ctypes.byref(group_array), ctypes.byref(group_count),
                                                         ctypes.byref(cap_array), ctypes.byref(cap_count)), 'DeriveCapabilitySidsFromName')
        for array, count in ((group_array, group_count), (cap_array, cap_count)):
            entries = ctypes.cast(array, ctypes.POINTER(ctypes.c_void_p))
            allocations.extend(entries[index] for index in range(count.value))
            allocations.append(array)
        cap_sids.extend(ctypes.cast(cap_array, ctypes.POINTER(ctypes.c_void_p))[index] for index in range(cap_count.value))
    return (_SidAttributes * len(cap_sids))(*[_SidAttributes(value, 4) for value in cap_sids])


class _Native:
    def __init__(self):
        if os.name != 'nt':
            raise SandboxError('Isolated Python execution requires Windows 10/11 LPAC; no unrestricted fallback is available')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)
        self.u = ctypes.WinDLL('userenv', use_last_error=True)
        self.b = ctypes.WinDLL('kernelbase', use_last_error=True)
        P = ctypes.c_void_p
        def bind(lib, name, args, result=W.BOOL):
            function = getattr(lib, name)
            function.argtypes, function.restype = args, result
        bind(self.u, 'CreateAppContainerProfile', [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, P, W.DWORD, ctypes.POINTER(P)], ctypes.c_long)
        bind(self.u, 'DeleteAppContainerProfile', [W.LPCWSTR], ctypes.c_long)
        bind(self.a, 'FreeSid', [P], P)
        bind(self.a, 'ConvertSidToStringSidW', [P, ctypes.POINTER(P)])
        bind(self.u, 'GetAppContainerFolderPath', [W.LPCWSTR, ctypes.POINTER(P)], ctypes.c_long)
        self.ole = ctypes.WinDLL('ole32', use_last_error=True)
        bind(self.ole, 'CoTaskMemFree', [P], None)
        bind(self.a, 'GetNamedSecurityInfoW', [W.LPCWSTR, W.DWORD, W.DWORD, P, P, ctypes.POINTER(P), P, ctypes.POINTER(P)], W.DWORD)
        bind(self.a, 'SetEntriesInAclW', [W.DWORD, ctypes.POINTER(_Access), P, ctypes.POINTER(P)], W.DWORD)
        bind(self.a, 'SetNamedSecurityInfoW', [W.LPWSTR, W.DWORD, W.DWORD, P, P, P, P], W.DWORD)
        bind(self.a, 'SetSecurityInfo', [W.HANDLE, W.DWORD, W.DWORD, P, P, P, P], W.DWORD)
        bind(self.b, 'DeriveCapabilitySidsFromName', [W.LPCWSTR, ctypes.POINTER(P), ctypes.POINTER(W.DWORD), ctypes.POINTER(P), ctypes.POINTER(W.DWORD)])
        bind(self.k, 'CreateFileW', [W.LPCWSTR, W.DWORD, W.DWORD, P, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE)
        bind(self.k, 'FindFirstStreamW', [W.LPCWSTR, W.DWORD, ctypes.POINTER(_StreamData), W.DWORD], W.HANDLE)
        bind(self.k, 'FindNextStreamW', [W.HANDLE, ctypes.POINTER(_StreamData)])
        bind(self.k, 'FindClose', [W.HANDLE])
        bind(self.k, 'LocalFree', [P], P)
        bind(self.k, 'CloseHandle', [W.HANDLE])
        bind(self.k, 'CreatePipe', [ctypes.POINTER(W.HANDLE), ctypes.POINTER(W.HANDLE), ctypes.POINTER(_SecurityAttributes), W.DWORD])
        bind(self.k, 'SetHandleInformation', [W.HANDLE, W.DWORD, W.DWORD])
        bind(self.k, 'ReadFile', [W.HANDLE, P, W.DWORD, ctypes.POINTER(W.DWORD), P])
        bind(self.k, 'InitializeProcThreadAttributeList', [P, W.DWORD, W.DWORD, ctypes.POINTER(ctypes.c_size_t)])
        bind(self.k, 'UpdateProcThreadAttribute', [P, W.DWORD, ctypes.c_size_t, P, ctypes.c_size_t, P, P])
        bind(self.k, 'DeleteProcThreadAttributeList', [P], None)
        bind(self.k, 'CreateProcessW', [W.LPCWSTR, W.LPWSTR, P, P, W.BOOL, W.DWORD, P, W.LPCWSTR, ctypes.POINTER(_StartupEx), ctypes.POINTER(_Process)])
        bind(self.k, 'CreateJobObjectW', [P, W.LPCWSTR], W.HANDLE)
        bind(self.k, 'CreateMutexW', [P, W.BOOL, W.LPCWSTR], W.HANDLE)
        bind(self.k, 'ReleaseMutex', [W.HANDLE])
        bind(self.k, 'SetInformationJobObject', [W.HANDLE, ctypes.c_int, P, W.DWORD])
        bind(self.k, 'AssignProcessToJobObject', [W.HANDLE, W.HANDLE])
        bind(self.k, 'TerminateJobObject', [W.HANDLE, W.UINT])
        bind(self.k, 'TerminateProcess', [W.HANDLE, W.UINT])
        bind(self.k, 'ResumeThread', [W.HANDLE], W.DWORD)
        bind(self.k, 'WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD)
        bind(self.k, 'GetExitCodeProcess', [W.HANDLE, ctypes.POINTER(W.DWORD)])

    def check(self, value, label):
        if not value:
            raise SandboxError(f'{label} failed (Windows error {ctypes.get_last_error()})')
        return value

    def named_stream(self, path):
        data = _StreamData()
        handle = self.k.FindFirstStreamW(str(path), 0, ctypes.byref(data), 0)
        if handle == ctypes.c_void_p(-1).value:
            if ctypes.get_last_error() == 38:  # ERROR_HANDLE_EOF: no streams
                return False
            raise SandboxError('Cannot inspect private storage streams')
        try:
            while True:
                if data.name != '::$DATA':
                    return True
                if not self.k.FindNextStreamW(handle, ctypes.byref(data)):
                    if ctypes.get_last_error() != 38:
                        raise SandboxError('Cannot inspect private storage streams')
                    return False
        finally:
            self.k.FindClose(handle)

    def acl(self, path, sid, *, writable=False, remove=False, inherit=True):
        old, descriptor, new = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        error = self.a.GetNamedSecurityInfoW(str(path), 1, 4, None, None, ctypes.byref(old), None, ctypes.byref(descriptor))
        if error:
            raise SandboxError(f'Cannot inspect runtime/workspace permissions (Windows error {error})')
        try:
            entry = _Access(0x1301BF if writable else 0x1200A9, 4 if remove else 1, 3 if inherit else 0,
                            _Trustee(None, 0, 0, 0, sid))
            error = self.a.SetEntriesInAclW(1, ctypes.byref(entry), old, ctypes.byref(new))
            if not error:
                if inherit or not Path(path).is_dir():
                    error = self.a.SetNamedSecurityInfoW(str(path), 1, 4, None, None, new, None)
                else:
                    # MAXIMUM_ALLOWED explicitly suppresses child propagation
                    # (SetSecurityInfo contract). Keep parent-only grants local.
                    handle = self.k.CreateFileW(str(path), 0x02000000, 7, None, 3, 0x02200000, None)
                    if handle == ctypes.c_void_p(-1).value:
                        raise SandboxError('Cannot open runtime permission handle')
                    try:
                        error = self.a.SetSecurityInfo(handle, 1, 4, None, None, new, None)
                    finally:
                        self.k.CloseHandle(handle)
            if error:
                raise SandboxError(f'Cannot update temporary sandbox permissions (Windows error {error})')
        finally:
            if new:
                self.k.LocalFree(new)
            if descriptor:
                self.k.LocalFree(descriptor)


def _workspace_size(directory: Path, max_bytes: int, max_entries=2048, named_stream=None):
    """Watchdog limit, not an NTFS quota; transient write overshoot is possible."""
    count, size = 0, 0
    pending = [directory]
    while pending:
        current = pending.pop()
        if named_stream and named_stream(current):
            return False
        with os.scandir(current) as items:
            for item in items:
                count += 1
                if count > max_entries:
                    return False
                info = item.stat(follow_symlinks=False)
                if getattr(info, 'st_file_attributes', 0) & 0x400 or item.is_symlink():
                    return False
                if item.is_dir(follow_symlinks=False):
                    pending.append(Path(item.path))
                else:
                    if named_stream and named_stream(item.path):
                        return False
                    size += info.st_size
                    if size > max_bytes:
                        return False
    return True


def _prune_private_links(directory: Path):
    """After process exit, remove link entries without traversing their targets.

    Runtime ACL removal and profile deletion must never walk an untrusted
    junction. A live handle prevents replacement of each private storage root.
    """
    root_info = directory.lstat()
    if getattr(root_info, 'st_file_attributes', 0) & 0x400 or directory.is_symlink():
        raise SandboxError('Private sandbox root was replaced')
    pending = [directory]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                # Windows DirEntry.stat reports st_nlink=0; use lstat for the
                # actual hard-link count before deciding to remove an entry.
                info = os.lstat(entry.path)
                if getattr(info, 'st_file_attributes', 0) & 0x400 or entry.is_symlink():
                    if getattr(info, 'st_file_attributes', 0) & 0x10 and not entry.is_symlink():
                        os.rmdir(entry.path)
                    else:
                        os.unlink(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif info.st_nlink != 1:
                    os.unlink(entry.path)


def run_isolated(command: list[str], workspace: Path, runtime_roots: list[tuple[Path, bool]], *,
                 timeout: float, memory_mb: int, output_limit: int,
                 workspace_limit: int, cancel: threading.Event | None = None,
                 network_enabled: bool = False) -> dict:
    """Run a trusted interpreter plus untrusted code in LPAC; network defaults off.

    Temporary ACEs use a fresh SID and are removed without replacing other ACL
    entries. The suspended child enters its Job before any Python code executes.
    """
    names = _capability_names(network_enabled)
    native = _Native()
    k = native.k
    name = 'AgentWorkbench.Python.' + uuid.uuid4().hex
    sid = ctypes.c_void_p()
    profile_created = False
    granted = []
    handles = set()
    attributes = None
    attributes_initialized = False
    process = _Process()
    job = None
    readers = []
    output_exceeded = threading.Event()
    data = {'stdout': bytearray(), 'stderr': bytearray()}
    cleanup_errors = []
    profile_path = None
    capability_allocations = []
    private_handles = []
    output_lock = threading.Lock()
    mutex, mutex_owned = None, False
    child_stopped = True
    def close(handle):
        if handle and handle in handles:
            k.CloseHandle(handle)
            handles.remove(handle)
    try:
        # Serialize ACL read/modify/write across Workbench processes as well as
        # threads. A contended/missing mutex must never bypass isolation.
        mutex = native.check(k.CreateMutexW(None, False, 'Global\\AgentWorkbench.Python.RuntimeACL.v1'), 'CreateMutex')
        while True:
            status = k.WaitForSingleObject(mutex, 100)
            if status in (0, 128):
                mutex_owned = True
                if status == 128:
                    raise SandboxError('Previous Python isolation setup did not cleanly finish; inspect runtime permissions')
                break
            if status != 258:
                raise SandboxError('Cannot acquire runtime permissions lock')
            if cancel is not None and cancel.is_set():
                raise SandboxError('Python execution cancelled before setup')
        # The profile and child token receive the same declared capabilities.
        # No loopback exemption or firewall policy is registered by this runner.
        cap_entries = _derive_capabilities(native, names, capability_allocations)
        cap_pointer = ctypes.cast(cap_entries, ctypes.c_void_p)
        result = native.u.CreateAppContainerProfile(name, 'Agent Workbench Python', 'Temporary isolated Python execution',
                                                   cap_pointer, len(cap_entries), ctypes.byref(sid))
        if result < 0:
            raise SandboxError(f'Cannot create isolated Python profile (HRESULT {result & 0xffffffff:08x})')
        profile_created = True
        sid_text, profile_folder = ctypes.c_void_p(), ctypes.c_void_p()
        try:
            native.check(native.a.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)), 'ConvertSidToStringSid')
            result = native.u.GetAppContainerFolderPath(ctypes.wstring_at(sid_text), ctypes.byref(profile_folder))
            if result < 0:
                raise SandboxError('Cannot locate private sandbox storage')
            profile_path = Path(ctypes.wstring_at(profile_folder))
        finally:
            if sid_text:
                k.LocalFree(sid_text)
            if profile_folder:
                native.ole.CoTaskMemFree(profile_folder)
        for private_root in (workspace, profile_path):
            handle = k.CreateFileW(str(private_root), 0x20000, 3, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise SandboxError('Cannot hold private sandbox storage')
            private_handles.append(handle)
        for root, inherit, writable in [(root, inherit, False) for root, inherit in runtime_roots] + [(workspace, True, True)]:
            # A failed tree update can already have changed the parent or some
            # children, so register rollback before attempting the grant.
            granted.append((root, inherit))
            native.acl(root, sid, writable=writable, inherit=inherit)
        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        child_handles = []
        for stream in ('stdin', 'stdout', 'stderr'):
            read, write = W.HANDLE(), W.HANDLE()
            native.check(k.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0), 'CreatePipe')
            handles.update((read.value, write.value))
            child, parent = (read.value, write.value) if stream == 'stdin' else (write.value, read.value)
            child_handles.append(child)
            native.check(k.SetHandleInformation(parent, 1, 0), 'SetHandleInformation')
            if stream == 'stdin':
                close(parent)
                continue
            def reader(handle=parent, label=stream):
                buffer = ctypes.create_string_buffer(4096)
                read_size = W.DWORD()
                while k.ReadFile(handle, buffer, len(buffer), ctypes.byref(read_size), None) and read_size.value:
                    with output_lock:
                        available = output_limit - sum(len(value) for value in data.values())
                        data[label].extend(buffer.raw[:min(available, read_size.value)])
                        if read_size.value > available:
                            output_exceeded.set()
                            break
            thread = threading.Thread(target=reader, daemon=True)
            readers.append(thread)
        job = native.check(k.CreateJobObjectW(None, None), 'CreateJobObject')
        handles.add(job)
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x8 | 0x100 | 0x200 | 0x400
        limits.basic.active = 1
        limits.process_memory = limits.job_memory = memory_mb * 1024 * 1024
        native.check(k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), 'SetInformationJobObject')
        size = ctypes.c_size_t()
        k.InitializeProcThreadAttributeList(None, 4, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        native.check(k.InitializeProcThreadAttributeList(attributes, 4, 0, ctypes.byref(size)), 'InitializeProcThreadAttributeList')
        attributes_initialized = True
        # CPython/Windows DLL initialization requires registryRead. Network
        # capabilities are explicit opt-in; COM/credentials remain ungranted.
        capabilities = _Capabilities(sid, cap_pointer, len(cap_entries), 0)
        lpac, no_children = W.DWORD(1), W.DWORD(1)
        inherit = (W.HANDLE * len(child_handles))(*child_handles)
        for attribute, value in ((0x20009, capabilities), (0x2000F, lpac), (0x2000E, no_children), (0x20002, inherit)):
            native.check(k.UpdateProcThreadAttribute(attributes, 0, attribute, ctypes.byref(value), ctypes.sizeof(value), None, None), 'UpdateProcThreadAttribute')
        startup = _StartupEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
        startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = child_handles
        startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
        # Do not inherit credentials, proxies, PYTHONPATH, user profile or PATH.
        environment = {'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows'),
                       'LOCALAPPDATA': os.environ.get('LOCALAPPDATA', ''),
                       'TEMP': str(workspace), 'TMP': str(workspace)}
        env = ctypes.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(environment.items())) + '\0\0')
        cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        # Detached console avoids creating/constraining a console host process;
        # explicitly inherited pipes still provide Python's standard streams.
        flags = 0x80000 | 0x8 | 0x400 | 0x4
        native.check(k.CreateProcessW(command[0], cmd, None, None, True, flags, env, str(workspace),
                                     ctypes.byref(startup), ctypes.byref(process)), 'CreateProcessW(LPAC)')
        handles.update((process.process, process.thread))
        native.check(k.AssignProcessToJobObject(job, process.process), 'AssignProcessToJobObject')
        for handle in child_handles:
            close(handle)
        for thread in readers:
            thread.start()
        if k.ResumeThread(process.thread) == 0xffffffff:
            raise SandboxError('Cannot resume sandboxed Python')
        start = time.monotonic()
        reason = None
        while True:
            wait = k.WaitForSingleObject(process.process, 50)
            if wait == 0:
                break
            if wait != 258:
                raise SandboxError('Cannot wait for sandboxed Python')
            if cancel is not None and cancel.is_set():
                reason = 'cancelled'
            elif time.monotonic() - start >= timeout:
                reason = 'timeout'
            elif output_exceeded.is_set():
                reason = 'output_limit'
            else:
                try:
                    if (not _workspace_size(workspace, workspace_limit, named_stream=native.named_stream) or
                            not _workspace_size(profile_path, workspace_limit, named_stream=native.named_stream)):
                        reason = 'workspace_limit'
                except (OSError, SandboxError):
                    reason = 'workspace_changed'
            if reason:
                k.TerminateJobObject(job, 1)
                k.WaitForSingleObject(process.process, 5000)
                break
        code = W.DWORD()
        native.check(k.GetExitCodeProcess(process.process, ctypes.byref(code)), 'GetExitCodeProcess')
        for thread in readers:
            thread.join(5)
        if any(thread.is_alive() for thread in readers):
            raise SandboxError('Could not drain sandbox output')
        if output_exceeded.is_set():
            reason = reason or 'output_limit'
        if reason is None:
            if (not _workspace_size(workspace, workspace_limit, named_stream=native.named_stream) or
                    not _workspace_size(profile_path, workspace_limit, named_stream=native.named_stream)):
                reason = 'workspace_limit'
        return {'exit_code': code.value, 'stdout': bytes(data['stdout']).decode('utf-8', errors='replace'),
                'stderr': bytes(data['stderr']).decode('utf-8', errors='replace'), 'termination_reason': reason,
                'isolation': 'windows-lpac', 'network': 'enabled' if network_enabled else 'disabled',
                'network_capabilities': list(names[1:]),
                'read_exceptions': ['selected_runtime_and_libraries', 'windows_lpac_accessible_resources'],
                'registry_capability': 'registryRead'}
    finally:
        if process.process:
            # Also terminate a suspended child if assignment or resume failed.
            k.TerminateProcess(process.process, 1)
            child_stopped = k.WaitForSingleObject(process.process, 5000) == 0
            if not child_stopped:
                close(job)  # KILL_ON_JOB_CLOSE is an independent final stop.
                child_stopped = k.WaitForSingleObject(process.process, 5000) == 0
            if not child_stopped:
                cleanup_errors.append('Sandbox child did not stop; private storage retained')
        for thread in readers:
            if thread.ident:
                thread.join(5)
        for handle in list(handles):
            close(handle)
        if attributes_initialized:
            k.DeleteProcThreadAttributeList(attributes)
        safe_private = child_stopped
        for private_root in (workspace, profile_path):
            if private_root is not None and child_stopped:
                try:
                    _prune_private_links(private_root)
                except Exception as exc:
                    safe_private = False
                    cleanup_errors.append(str(exc))
        for root, inherit in reversed(granted):
            if root == workspace and not safe_private:
                continue
            try:
                native.acl(root, sid, remove=True, inherit=inherit)
            except Exception as exc:
                cleanup_errors.append(str(exc))
        for handle in private_handles:
            k.CloseHandle(handle)
        if profile_created and safe_private:
            result = native.u.DeleteAppContainerProfile(name)
            if result < 0:
                cleanup_errors.append(f'Cannot remove isolated profile ({result & 0xffffffff:08x})')
        if sid:
            native.a.FreeSid(sid)
        for allocation in capability_allocations:
            k.LocalFree(allocation)
        if mutex_owned:
            k.ReleaseMutex(mutex)
        if mutex:
            k.CloseHandle(mutex)
        if cleanup_errors:
            raise SandboxError('Temporary sandbox permission/profile cleanup failed: ' + '; '.join(cleanup_errors),
                               preserve_private=not safe_private)
