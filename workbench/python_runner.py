"""Normal Python scripts with a Windows OS boundary and explicit file transfer.

The selected interpreter and module folders are trusted, read-only runtime
dependencies. Scripts see copies of declared inputs. Only declared outputs are
published by PathHarness; a subprocess cwd is never used as a security boundary.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading

from .harness import HarnessError, PathHarness, _inspect, _literal_path, _string
from .runtime_paths import PROTECTED_ROOTS
from .windows_sandbox import SandboxError, run_isolated

# ACL read/modify/write and cleanup must not race between Python executions.
_RUN_LOCK = threading.Lock()
_MAX_TRANSFER = 32 * 1024 * 1024
_MAX_FILES = 16
_WORKSPACE_LIMIT = 64 * 1024 * 1024
# The in-sandbox test helper: sandbox_pytest.py is copied to a reserved folder
# (no declared name can collide with it) that is first on the script's sys.path.
_HELPER_SOURCE = Path(__file__).with_name('sandbox_pytest.py')
_HELPER_FOLDER, _HELPER_MODULE = '.awb_lib', 'awb_pytest'
_RUN_TESTS = 'import awb_pytest; raise SystemExit(awb_pytest.run())'


class _Workspace:
    """No GC finalizer may remove storage while a child might still be alive."""
    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix='awb-python-')).resolve(strict=True)
        self.preserve = False
        return self

    def __exit__(self, *args):
        if not self.preserve:
            # Normal cleanup runs only after the native boundary confirms exit.
            # Refuse replacement of the private root before recursive removal.
            if (not self.path.name.startswith('awb-python-') or not self.path.is_absolute()
                    or self.path.resolve(strict=True) != self.path or self.path.is_symlink()
                    or getattr(self.path.lstat(), 'st_file_attributes', 0) & 0x400):
                raise HarnessError('Private Python storage changed; automatic cleanup refused')
            shutil.rmtree(self.path)


@contextlib.contextmanager
def _execution_lock(cancel):
    while not _RUN_LOCK.acquire(timeout=.1):
        if cancel.is_set():
            yield False
            return
    try:
        yield True
    finally:
        _RUN_LOCK.release()


def _name(value):
    path = _literal_path(_string(value, 'sandbox name', 240))
    if path.is_absolute() or path.drive or re.match(r'^[A-Za-z]:', value) or value.startswith(('/', '\\')):
        raise HarnessError('Sandbox names must be relative paths')
    if any(part.casefold().startswith('.awb_') for part in path.parts):
        raise HarnessError('Sandbox name uses a reserved prefix')
    if path.parts and path.parts[0].casefold().split('.')[0] == _HELPER_MODULE:
        # `import awb_pytest` always means the built-in helper; a file of that
        # name in the working directory could never be imported.
        raise HarnessError(f'Sandbox name {_HELPER_MODULE} is reserved for the built-in test helper')
    return path


def _mappings(items, *, outputs=False):
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > _MAX_FILES:
        raise HarnessError('Python inputs and outputs must each contain at most 16 files')
    result, seen = [], set()
    keys = {'path', 'name', 'expected_sha256'} if outputs else {'path', 'name'}
    for item in items:
        if not isinstance(item, dict) or set(item) != keys:
            raise HarnessError('Python file mappings have unsupported or missing fields')
        name = _name(item['name'])
        if str(name).casefold() in seen:
            raise HarnessError('Python file names must not be duplicated')
        seen.add(str(name).casefold())
        _string(item['path'], 'path', 4096)
        if outputs and item['expected_sha256'] != 'missing' and (
                not isinstance(item['expected_sha256'], str) or
                re.fullmatch('[0-9a-f]{64}', item['expected_sha256']) is None):
            raise HarnessError("expected_sha256 must be the current hash or 'missing'")
        result.append({**item, 'name': name})
    return result


def _runtime_path(value, harness, *, directory=False):
    path = _literal_path(_string(value, 'Python runtime path', 4096))
    if not path.is_absolute() or path == Path(path.anchor):
        raise HarnessError('Python runtime paths must be explicit absolute paths below a drive root')
    PathHarness._ancestors(path, require_leaf=True)
    _inspect(path, directory=directory)
    path = path.resolve(strict=True)
    for denied in harness.deny_roots:
        if path.is_relative_to(denied) or denied.is_relative_to(path):
            # A narrowly selected site-packages folder may live in the protected
            # installation. It is never exposed to data tools or made writable.
            protected_package = (denied in PROTECTED_ROOTS and path.name.casefold() == 'site-packages'
                                 and path.is_relative_to(denied) and path != denied)
            if not protected_package:
                raise HarnessError('Python runtime overlaps a denied/protected folder')
    return path


def _safe_tree(path):
    """Reject reparse points/hardlinks before applying inheritable read grants."""
    pending, count = [path], 0
    while pending:
        current = pending.pop()
        info = _inspect(current)
        count += 1
        if count > 100000:
            raise HarnessError('Python runtime folder is too large; select narrower library folders')
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(current) as entries:
                pending.extend(Path(entry.path) for entry in entries)


def _runtime(config, harness):
    executable = _runtime_path(config.get('executable', ''), harness)
    if executable.name.casefold() != 'python.exe':
        raise HarnessError('Select an existing CPython python.exe; shell/launcher executables are not supported')
    # Windows venv python.exe is a launcher. Resolve its declared base without
    # running any host-side probe; child process creation remains prohibited.
    venv = executable.parent.parent / 'pyvenv.cfg'
    if executable.parent.name.casefold() == 'scripts' and venv.is_file():
        _inspect(venv)
        if venv.stat().st_size > 16384:
            raise HarnessError('Invalid Python virtual environment configuration')
        home = next((line.split('=', 1)[1].strip() for line in venv.read_text(encoding='utf-8').splitlines()
                     if line.partition('=')[0].strip().casefold() == 'home'), '')
        executable = _runtime_path(str(Path(home) / 'python.exe'), harness)
    root = executable.parent
    library = root / 'Lib'
    _runtime_path(str(library), harness, directory=True)
    if not (library / 'encodings' / '__init__.py').is_file():
        raise HarnessError('Selected Python lacks its standard library')
    extra = config.get('library_paths', [])
    if not isinstance(extra, list) or len(extra) > 16:
        raise HarnessError('Python library_paths must contain at most 16 folders')
    extra = [_runtime_path(path, harness, directory=True) for path in extra]
    # Do not recursively grant the installation root: it may include unrelated
    # packages/data, and Windows propagates a directory ACL update recursively.
    access = [(root, False), (library, False), (executable, False)]
    access.extend((item, False) for item in root.glob('*.dll'))
    for folder in ('DLLs',):
        if (root / folder).is_dir():
            access.append((root / folder, True))
    access.extend((item, item.is_dir()) for item in library.iterdir()
                  if item.name not in {'site-packages', '__pycache__'})
    access.extend((path, True) for path in extra)
    access = list(dict.fromkeys(access))
    for path, inherit in access:
        _runtime_path(str(path), harness, directory=inherit)
        if inherit:
            _safe_tree(path)
    return executable, extra, access


def _integer(config, name, default, low, high):
    value = config.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise HarnessError(f'Python {name} must be an integer between {low} and {high}')
    return value


def _prepare_workspace(workspace, code, libraries, timeout):
    """Write the script, the test helper and the bootstrap; return the bootstrap.

    `-I -S` leaves only the standard library on sys.path. The bootstrap adds the
    helper folder and the working directory first (as `python script.py` does
    for the script's folder), then the selected library folders.
    """
    script = workspace / '.awb_script.py'
    script.write_text(code, encoding='utf-8')
    helper = workspace / _HELPER_FOLDER
    try:
        source = _HELPER_SOURCE.read_bytes()
    except OSError as exc:
        raise HarnessError('The Python test helper (sandbox_pytest.py) is missing from this installation') from exc
    helper.mkdir()
    (helper / f'{_HELPER_MODULE}.py').write_bytes(source)
    bootstrap = workspace / '.awb_bootstrap.py'
    bootstrap.write_text('import sys,runpy,os,time\n'
                         # awb_pytest budgets its own deadline from these two.
                         f'os.environ["AWB_PYTHON_TIMEOUT"]={str(timeout)!r}\n'
                         'os.environ["AWB_PYTHON_STARTED"]=repr(time.monotonic())\n'
                         f'sys.path[:0]={[str(helper), str(workspace)]!r}\n'
                         f'sys.path.extend({[str(path) for path in libraries]!r})\n'
                         f'os.chdir({str(workspace)!r})\n'
                         f'os.environ["TEMP"]=os.environ["TMP"]={str(workspace)!r}\n'
                         f'sys.argv=[{str(script)!r}]\n'
                         f'runpy.run_path({str(script)!r},run_name="__main__")\n', encoding='utf-8')
    return bootstrap


_FILE_DENIED = re.compile(r'\[Errno 13\]|\[WinError 5\]')
_FILE_MISSING = re.compile(r'FileNotFoundError|NotADirectoryError|\[Errno 2\]|\[WinError [23]\]')
_PROCESS = re.compile(r'subprocess\.py|CreateProcess|popen_spawn_win32|\bos\.(?:system|popen|startfile|spawn\w*|exec\w*)\(')
_SOCKET_DENIED = re.compile(r'WinError 10013')
_CONNECTION = re.compile(r'gaierror|getaddrinfo failed|URLError|ConnectionError|ConnectTimeout|NameResolutionError'
                         r'|\[WinError 100(?:5[01]|6[015])\]')
_MODULE_MISSING = re.compile(r"ModuleNotFoundError: No module named '([^'\r\n]{1,80})'")
# A quoted absolute path: drive, UNC or rooted. Exception messages print paths
# with repr(), so backslashes may be doubled.
_QUOTED_PATH = re.compile(r'''(['"])((?:[A-Za-z]:[\\/]|\\\\|/)[^'"\r\n\t<>|*?]{1,300})\1''')
_HINT_PATHS, _HINT_PATH_LENGTH, _HINT_LENGTH = 3, 200, 1800


def _host_paths(stderr, internal=()):
    """Absolute host paths the script named, at most a few and each bounded.

    They come from exception messages and from the source lines a traceback
    quotes. Traceback frame lines are skipped, and anything inside the
    workspace, interpreter or library folders is the sandbox's own.
    """
    internal = [str(path).casefold().rstrip('\\/') for path in internal]
    host = []
    for line in stderr.splitlines():
        if line.lstrip().startswith('File "'):
            continue
        for match in _QUOTED_PATH.finditer(line):
            path = match.group(2).rstrip()
            if re.search(r'(?<!\\)\\(?!\\)', path) is None:  # no single backslash: repr()-doubled
                path = path.replace('\\\\', '\\')
            folded = path.casefold()
            if 'awb-python-' in folded or any(folded == root or folded.startswith((root + '\\', root + '/'))
                                              for root in internal):
                continue
            # A rooted '/x' string in a source line is as likely a URL path.
            if (4 <= len(path) <= _HINT_PATH_LENGTH and path not in host and len(host) < _HINT_PATHS
                    and (path[0] != '/' or not line[:1].isspace())):
                host.append(path)
    return host


def failure_hint(exit_code, termination_reason, stderr, *, timeout=None, network_enabled=False,
                 output_limit=None, internal=()):
    """Explain a recognisable sandbox failure to the model, or return None.

    Pure: it reads only the exit status and stderr text of a finished run. The
    hint quotes paths that already appear in stderr and never file contents.
    """
    if termination_reason == 'cancelled' or (exit_code == 0 and not termination_reason):
        return None
    stderr = stderr if isinstance(stderr, str) else ''
    hints = []
    if termination_reason == 'timeout':
        hints.append(f'The script was stopped at the {timeout or "configured"} s time limit; nothing was published. '
                     'Typical causes: waiting on a blocked connection or on input(), an endless loop, or too much work '
                     'for one call. Do less per call and print progress to see where it stops. Run tests with '
                     f'`{_RUN_TESTS}`: it has its own deadline and names the test that was running.')
    elif termination_reason == 'output_limit':
        hints.append(f'stdout+stderr exceeded the {output_limit or "configured"}-byte limit and the script was stopped; '
                     'nothing was published. Print summaries, not whole files, and write large results to a declared output.')
    elif termination_reason == 'workspace_limit':
        hints.append(f'The working directory exceeded its limit ({_WORKSPACE_LIMIT // (1024 * 1024)} MiB, 2048 entries, '
                     'no links or alternate data streams) and the script was stopped; nothing was published. '
                     'Create fewer or smaller temporary files and delete them when done.')
    paths = _host_paths(stderr, internal)
    process = _PROCESS.search(stderr) is not None
    if process:
        hints.append('Starting other programs is blocked in the sandbox (subprocess, os.system, multiprocessing, pip, '
                     f'the pytest command). Do the work in this script with imports; to run tests call `{_RUN_TESTS}`.')
    # Access denied without a named host path has other causes (a refused
    # CreateProcess, a directory opened as a file); a missing relative file
    # usually means an undeclared input.
    denied = _FILE_DENIED.search(stderr) is not None
    missing = _FILE_MISSING.search(stderr) is not None
    if (paths and (denied or missing)) or (missing and not process):
        example = paths[0] if paths else r'C:\folder\data.csv'
        name = re.split(r'[\\/]', example.rstrip('\\/'))[-1]
        if not name or name.casefold().startswith('.awb_') or ':' in name:
            name = 'data.csv'
        hints.append(('Host files cannot be opened by their host path inside the script. ' if paths else '') +
                     'The script runs in a private working directory that holds only the declared inputs and the '
                     f'files it creates. For each file to read (up to {_MAX_FILES}), add '
                     "{'path': <host path>, 'name': <relative name>} to inputs and open it by that name, e.g. "
                     f"inputs=[{{'path': '{example}', 'name': '{name}'}}] then open('{name}'). "
                     'For each file to save, write it to a relative name and add '
                     "{'path': <host path>, 'name': <relative name>, 'expected_sha256': 'missing' for a new file "
                     'or the current sha256 of the file being replaced} to outputs.'
                     + (' Host paths in the error: ' + '; '.join(paths) if paths else ''))
    if _SOCKET_DENIED.search(stderr) or (not network_enabled and _CONNECTION.search(stderr)):
        if network_enabled:
            hints.append('WinError 10013 with network access enabled: Windows still blocks loopback '
                         '(localhost/127.0.0.1) connections from the sandbox, including local servers and '
                         'asyncio socket pairs. Only outbound connections to other hosts can work.')
        else:
            hints.append('Network access is disabled for this run: sockets are refused (WinError 10013), including '
                         'localhost and libraries that open a socket on import (asyncio event loops, pytest plugins '
                         'such as pytest-asyncio). Do not retry; work offline or ask the human to enable Python '
                         f'network access. For tests use `{_RUN_TESTS}`, which loads no such plugins.')
    module = _MODULE_MISSING.search(stderr)
    if module:
        hints.append(f"No module named '{module.group(1)}': only the standard library and the library folders the "
                     'human selected can be imported, and packages cannot be installed from the script. '
                     'For your own module, declare its .py file in inputs (the working directory is on sys.path).'
                     + (' awb_pytest.run() also works without pytest (built-in simple runner).'
                        if module.group(1) == 'pytest' else ''))
    text = ' '.join(hints)
    return (text if len(text) <= _HINT_LENGTH else text[:_HINT_LENGTH - 3] + '...') or None


def _execute(config, harness, code, inputs, outputs, on_complete, cancel):
    if not config.get('enabled', False):
        raise HarnessError('Python execution is disabled in settings')
    if os.name != 'nt':
        raise HarnessError('Python execution requires Windows LPAC; no unrestricted fallback is available')
    code = _string(code, 'Python code', 200000)
    inputs, outputs = _mappings(inputs), _mappings(outputs, outputs=True)
    timeout = _integer(config, 'timeout_seconds', 60, 1, 600)
    memory = _integer(config, 'max_memory_mb', 512, 128, 8192)
    output_limit = _integer(config, 'max_output_bytes', 65536, 1024, 1048576)
    network_enabled = config.get('network_enabled', False)
    if type(network_enabled) is not bool:
        raise HarnessError('Python network_enabled must be a boolean')
    with _execution_lock(cancel) as acquired:
        if not acquired or cancel.is_set():
            return {'exit_code': None, 'termination_reason': 'cancelled', 'outputs': [], 'stdout': '', 'stderr': ''}
        executable, libraries, access = _runtime(config, harness)
        # Validate every source/destination before launching. Output parents must
        # already exist, as with write_text; create_directory is a separate tool.
        staged, total, destinations = [], 0, set()
        for item in inputs:
            data = harness.read_bytes(item['path'])
            total += len(data)
            if total > _MAX_TRANSFER:
                raise HarnessError('Combined Python inputs exceed 32 MiB')
            staged.append((item['name'], data))
        for item in outputs:
            path = harness.resolve(item['path'], write=True, must_exist=False)
            _inspect(path.parent, directory=True)
            if str(path).casefold() in destinations:
                raise HarnessError('Python output destinations must not be duplicated')
            destinations.add(str(path).casefold())
            before = hashlib.sha256(harness._read(path)).hexdigest() if path.exists() else 'missing'
            if before != item['expected_sha256']:
                raise HarnessError('File changed: expected_sha256 does not match')
        with _Workspace() as private:
            workspace = private.path
            temporary = str(workspace)
            for name, data in staged:
                target = workspace / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for item in outputs:
                (workspace / item['name']).parent.mkdir(parents=True, exist_ok=True)
            bootstrap = _prepare_workspace(workspace, code, libraries, timeout)
            try:
                result = run_isolated([str(executable), '-I', '-S', '-B', '-u', '-X', 'utf8', str(bootstrap)],
                                      workspace, access, timeout=timeout, memory_mb=memory,
                                      output_limit=output_limit, workspace_limit=_WORKSPACE_LIMIT, cancel=cancel,
                                      network_enabled=network_enabled)
            except SandboxError as exc:
                if exc.preserve_private:
                    private.preserve = True
                    raise HarnessError(f'{exc}; private storage retained at {workspace}') from exc
                raise HarnessError(str(exc)) from exc
            result['outputs'] = []
            if cancel.is_set() or result['exit_code'] != 0 or result['termination_reason']:
                hint = None if cancel.is_set() else failure_hint(
                    result['exit_code'], result['termination_reason'], result.get('stderr', ''),
                    timeout=timeout, network_enabled=network_enabled, output_limit=output_limit,
                    internal=[workspace, executable.parent, *libraries])
                if hint:
                    result['hint'] = hint
                return result
            # Validate and read all generated files before the first publication.
            local = PathHarness([temporary], [], max_file_bytes=harness.max_file_bytes)
            prepared, total = [], 0
            try:
                for item in outputs:
                    data = local.read_bytes(str(workspace / item['name']))
                    total += len(data)
                    if total > _MAX_TRANSFER:
                        raise HarnessError('Combined Python outputs exceed 32 MiB')
                    prepared.append((item, data))
                for item, data in prepared:
                    if cancel.is_set():
                        result['termination_reason'] = 'cancelled'
                        break
                    receipt = harness.write_bytes(item['path'], data, item['expected_sha256'])
                    result['outputs'].append(receipt)
                    if on_complete:
                        on_complete(receipt)
            except (HarnessError, OSError) as exc:
                # Earlier successful publications are real and remain visible.
                result['publication_error'] = str(exc)
            return result


async def execute_python(config, harness, code, inputs=None, outputs=None, *, on_complete=None):
    """Execute with a python-settings dict. Callback receives each saved receipt.

    Cancellation kills and waits for the OS job and cleanup before propagating.
    on_complete is synchronous, runs on the calling event loop after each saved
    publication; callback exceptions cannot change file results. Outputs may be
    partially published if a destination changes; outputs[] lists successes and
    publication_error explains.
    """
    cancel = threading.Event()
    loop = asyncio.get_running_loop()
    def complete(receipt):
        if on_complete:
            try:
                on_complete(receipt)
            except Exception:
                pass
    def dispatch(receipt):
        loop.call_soon_threadsafe(complete, receipt)
    task = asyncio.create_task(asyncio.to_thread(_execute, config, harness, code, inputs, outputs, dispatch, cancel))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            # Retrieve a cleanup failure even during repeated cancellation.
            task.exception()
        raise
