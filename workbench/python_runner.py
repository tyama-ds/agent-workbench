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
    return path


def _mappings(items, *, outputs=False):
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > 16:
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
            script = workspace / '.awb_script.py'
            script.write_text(code, encoding='utf-8')
            bootstrap = workspace / '.awb_bootstrap.py'
            bootstrap.write_text('import sys,runpy,os\n'
                                 f'sys.path.extend({[str(path) for path in libraries]!r})\n'
                                 f'os.chdir({str(workspace)!r})\n'
                                 f'os.environ["TEMP"]=os.environ["TMP"]={str(workspace)!r}\n'
                                 f'sys.argv=[{str(script)!r}]\n'
                                 f'runpy.run_path({str(script)!r},run_name="__main__")\n', encoding='utf-8')
            try:
                result = run_isolated([str(executable), '-I', '-S', '-B', '-u', '-X', 'utf8', str(bootstrap)],
                                      workspace, access, timeout=timeout, memory_mb=memory,
                                      output_limit=output_limit, workspace_limit=64 * 1024 * 1024, cancel=cancel)
            except SandboxError as exc:
                if exc.preserve_private:
                    private.preserve = True
                    raise HarnessError(f'{exc}; private storage retained at {workspace}') from exc
                raise HarnessError(str(exc)) from exc
            result['outputs'] = []
            if cancel.is_set() or result['exit_code'] != 0 or result['termination_reason']:
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
