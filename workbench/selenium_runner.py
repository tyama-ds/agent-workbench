"""Opt-in, ordinary-user Selenium with fixed operations and scoped publication.

The Job bounds lifetime/resources; it is NOT LPAC or a folder/network sandbox.
Only screenshots published by this module are protected by PathHarness.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

from .harness import HarnessError, PathHarness, _inspect, _integer, _string
from .python_runner import _runtime_path
from .selenium_worker import _validate_elements, validate_actions, validate_proxy, validate_url
from .windows_sandbox import SandboxError, _prune_private_links
from .windows_browser_job import run_browser_job

_RUN_LOCK = threading.Lock()
_MAX_SCREENSHOT = 16 * 1024 * 1024
_PNG = b'\x89PNG\r\n\x1a\n'


class _Workspace:
    """No finalizer may delete storage while native descendants might survive."""
    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix='awb-selenium-')).resolve(strict=True)
        self.identity = self.path.stat()
        self.preserve = False
        return self

    def __exit__(self, *args):
        if self.preserve:
            return
        try:
            info = _inspect(self.path, directory=True)
            if (not self.path.is_absolute() or not self.path.name.startswith('awb-selenium-')
                    or self.path.resolve(strict=True) != self.path
                    or (info.st_dev, info.st_ino) != (self.identity.st_dev, self.identity.st_ino)):
                raise HarnessError('Private Selenium root changed')
            _prune_private_links(self.path)
            shutil.rmtree(self.path)
        except (OSError, SandboxError, HarnessError) as exc:
            raise HarnessError(f'Private Selenium cleanup failed; storage retained at {self.path}') from exc


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


def _runtime(config, python_config, harness):
    executable = _runtime_path(python_config.get('executable', ''), harness)
    if executable.name.casefold() != 'python.exe':
        raise HarnessError('Select an existing CPython python.exe in Python settings')
    # Resolve a venv launcher without running a host-side interpreter probe.
    venv = executable.parent.parent / 'pyvenv.cfg'
    if executable.parent.name.casefold() == 'scripts' and venv.is_file():
        _inspect(venv)
        if venv.stat().st_size > 16384:
            raise HarnessError('Invalid Python virtual environment configuration')
        home = next((line.split('=', 1)[1].strip() for line in venv.read_text(encoding='utf-8').splitlines()
                     if line.partition('=')[0].strip().casefold() == 'home'), '')
        executable = _runtime_path(str(Path(home) / 'python.exe'), harness)
    _runtime_path(str(executable.parent / 'Lib'), harness, directory=True)
    libraries = []
    for settings in (config, python_config):
        values = settings.get('library_paths', [])
        if not isinstance(values, list) or len(values) > 16:
            raise HarnessError('Each library_paths setting must contain at most 16 folders')
        libraries.extend(_runtime_path(value, harness, directory=True) for value in values)
    browser = config.get('browser', 'edge')
    if not isinstance(browser, str) or browser not in {'edge', 'chrome'}:
        raise HarnessError('Selenium browser must be edge or chrome')
    browser_path = _runtime_path(config.get('browser_executable', ''), harness)
    driver_path = _runtime_path(config.get('driver_executable', ''), harness)
    for path in (browser_path, driver_path):
        if path.suffix.casefold() != '.exe' or path.is_dir():
            raise HarnessError('Select existing browser and driver .exe files')
    return executable, list(dict.fromkeys(libraries)), browser_path, driver_path


def _screenshot_request(screenshot, harness):
    if screenshot is None:
        return None
    if not isinstance(screenshot, dict) or set(screenshot) != {'path', 'expected_sha256'}:
        raise HarnessError('Screenshot requires only path and expected_sha256')
    _string(screenshot['path'], 'screenshot path', 4096)
    expected = screenshot['expected_sha256']
    if expected != 'missing' and (not isinstance(expected, str) or re.fullmatch('[0-9a-f]{64}', expected) is None):
        raise HarnessError("expected_sha256 must be the current hash or 'missing'")
    path = harness.resolve(screenshot['path'], write=True, must_exist=False)
    if path.suffix.casefold() != '.png':
        raise HarnessError('Screenshot destination must have the .png extension')
    _inspect(path.parent, directory=True)
    before = hashlib.sha256(harness._read(path)).hexdigest() if path.exists() else 'missing'
    if before != expected:
        raise HarnessError('File changed: expected_sha256 does not match')
    return {'path': str(path), 'expected_sha256': expected}


def _read_result(workspace, maximum, actions):
    local = PathHarness([str(workspace)], [], max_file_bytes=1024 * 1024)
    raw = local.read_bytes(str(workspace / 'result.json'))
    if len(raw) > maximum * 6 + 16384:
        raise HarnessError('Selenium result exceeds the output limit')
    try:
        result = json.loads(raw)
        if not isinstance(result, dict) or set(result) != {'title', 'url', 'text', 'actions', 'elements', 'truncated'}:
            raise ValueError()
        if type(result['truncated']) is not bool or not isinstance(result['actions'], list):
            raise ValueError()
        if len(result['actions']) != len(actions):
            raise ValueError()
        texts = [result['title'], result['url'], result['text']]
        result['elements'] = _validate_elements(result['elements'])
        for item in result['elements']:
            texts.extend(item.values())
        for index, item in enumerate(result['actions']):
            expected = {'index', 'action', 'text'} if actions[index]['action'] == 'read' else {'index', 'action'}
            if (not isinstance(item, dict) or set(item) != expected or type(item['index']) is not int
                    or item['index'] != index or item['action'] != actions[index]['action']):
                raise ValueError()
            if 'text' in item:
                texts.append(item['text'])
        if not all(isinstance(value, str) for value in texts) or sum(map(len, texts)) > maximum:
            raise ValueError()
        for value in texts:
            value.encode('utf-8')
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HarnessError('Selenium returned an invalid result') from exc
    return result


def _execute(config, python_config, harness, url, actions, screenshot, on_complete, cancel):
    if config.get('enabled', False) is not True:
        raise HarnessError('Selenium automation is disabled in settings')
    if python_config.get('network_enabled', False) is not True:
        raise HarnessError('Selenium requires the explicit Python network permission')
    if os.name != 'nt':
        raise HarnessError('Selenium automation currently requires Windows')
    try:
        url, actions = validate_url(url), validate_actions(actions)
        proxy = validate_proxy(config.get('proxy_url', ''))
    except (ValueError, UnicodeError) as exc:
        raise HarnessError(str(exc)) from exc
    timeout = _integer(config.get('timeout_seconds', 60), 'Selenium timeout_seconds', 10, 300)
    memory = _integer(config.get('max_memory_mb', 1024), 'Selenium max_memory_mb', 256, 8192)
    maximum = _integer(config.get('max_output_chars', 20000), 'Selenium max_output_chars', 1000, 100000)
    screenshot = _screenshot_request(screenshot, harness)
    with _execution_lock(cancel) as acquired:
        if not acquired or cancel.is_set():
            return {'exit_code': None, 'termination_reason': 'cancelled', 'outputs': [], 'stdout': '', 'stderr': ''}
        executable, libraries, browser_path, driver_path = _runtime(config, python_config, harness)
        prepared = None
        with _Workspace() as private:
            workspace = private.path
            job = {'browser': config.get('browser', 'edge'), 'browser_executable': str(browser_path),
                   'driver_executable': str(driver_path), 'library_paths': [str(path) for path in libraries],
                   'proxy_url': proxy, 'url': url, 'actions': actions, 'timeout_seconds': timeout,
                   'max_output_chars': maximum, 'screenshot_requested': screenshot is not None,
                   'max_screenshot_bytes': min(harness.max_file_bytes, _MAX_SCREENSHOT)}
            job_path, worker = workspace / 'job.json', workspace / 'worker.py'
            job_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
            worker.write_bytes(Path(__file__).with_name('selenium_worker.py').read_bytes())
            try:
                result = run_browser_job([str(executable), '-I', '-S', '-B', '-u', '-X', 'utf8',
                                          str(worker), str(job_path)], workspace,
                                         timeout=timeout, memory_mb=memory, output_limit=16384,
                                         workspace_limit=256 * 1024 * 1024, cancel=cancel)
            except SandboxError as exc:
                private.preserve = exc.preserve_private
                suffix = f'; private storage retained at {workspace}' if exc.preserve_private else ''
                raise HarnessError(str(exc) + suffix) from exc
            except Exception as exc:
                # An unexpected native-runner failure cannot establish that
                # every child stopped. Avoid all automatic recursive cleanup.
                private.preserve = True
                raise HarnessError(f'Selenium process cleanup unconfirmed; private storage retained at {workspace}') from exc
            result['outputs'] = []
            if cancel.is_set() or result['exit_code'] != 0 or result['termination_reason']:
                return result
            result.update(_read_result(workspace, maximum, actions))
            if screenshot:
                local = PathHarness([str(workspace)], [], max_file_bytes=min(harness.max_file_bytes, _MAX_SCREENSHOT))
                prepared = local.read_bytes(str(workspace / 'screenshot.png'))
                if not prepared.startswith(_PNG):
                    raise HarnessError('Selenium screenshot is not a PNG')
        # No output is published until the entire native Job has stopped AND
        # the private profile/workspace cleanup has completed successfully.
        if cancel.is_set():
            result['termination_reason'] = 'cancelled'
        elif screenshot is not None and prepared is not None:
            try:
                receipt = harness.write_bytes(screenshot['path'], prepared, screenshot['expected_sha256'])
                result['outputs'].append(receipt)
                on_complete(receipt)
            except (HarnessError, OSError) as exc:
                result['publication_error'] = str(exc)
        return result


async def execute_selenium(config, python_config, harness, url, actions=None, screenshot=None, *, on_complete=None):
    """Run one fixed action batch; cancellation waits for native cleanup.

    Ordinary-user browser access is outside PathHarness. This function confines
    only screenshot publication, with the same hash guard and receipt semantics
    as other file tools. A receipt callback runs on the caller's event loop.
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
    task = asyncio.create_task(asyncio.to_thread(_execute, config, python_config, harness, url, actions,
                                                screenshot, dispatch, cancel))
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
            task.exception()
        raise
