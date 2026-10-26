"""Optional Copilot UI bridge supervision; never sends a model request.

Only processes started here belong to this manager. Existing loopback bridges
are borrowed, and are never terminated. Readiness describes the bridge's HTTP
contract, not a fresh login check or successful Copilot inference.
"""
from __future__ import annotations

import asyncio
import contextlib
import ctypes
from ctypes import wintypes
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

import aiohttp

from .providers import strict_json

MAX_RESPONSE_BYTES = 256 * 1024
HTTP_TIMEOUT = 2
POLL_SECONDS = .25
ROOT = Path(__file__).resolve().parent.parent

# The child cannot import the bridge (or launch Edge) before Job assignment.
# No shell, user-supplied program text, or credentials are placed in this code.
_BOOTSTRAP = (
    "import os,runpy,sys; "
    "token=sys.stdin.buffer.read(1); "
    "sys.exit(2) if token!=b'\\n' else None; "
    "os.chdir(sys.argv[1]); sys.path.insert(0,sys.argv[1]); "
    "sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0],run_name='__main__')"
)


class BridgeFailure(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _config(value):
    if not isinstance(value, dict) or type(value.get('enabled', False)) is not bool:
        raise BridgeFailure('invalid_configuration', 'Copilot agent の設定が不正です。')
    cfg = dict(enabled=value.get('enabled', False),
               bridge_directory=value.get('bridge_directory', ''),
               python_executable=value.get('python_executable', ''),
               base_url=value.get('base_url', 'http://127.0.0.1:8800/v1'),
               model=value.get('model', 'copilot'),
               startup_timeout_seconds=value.get('startup_timeout_seconds', 600))
    for key in ('bridge_directory', 'python_executable', 'base_url', 'model'):
        if not isinstance(cfg[key], str) or any(ord(c) < 32 or ord(c) == 127 for c in cfg[key]):
            raise BridgeFailure('invalid_configuration', 'Copilot agent の設定文字列が不正です。')
    try:
        parts = urlsplit(cfg['base_url'])
        if (parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost')
                or parts.username is not None or parts.password is not None
                or parts.path != '/v1' or parts.query or parts.fragment or not parts.port):
            raise ValueError
    except ValueError:
        raise BridgeFailure('invalid_configuration', 'Copilot bridge は localhost の HTTP /v1 接続先が必要です。') from None
    if (not cfg['model'].strip() or len(cfg['model']) > 200
            or type(cfg['startup_timeout_seconds']) is not int
            or not 5 <= cfg['startup_timeout_seconds'] <= 1200):
        raise BridgeFailure('invalid_configuration', 'Copilot agent のモデル名または起動待機時間が不正です。')
    return cfg


def _bridge_directory(value):
    candidates = ([Path(value)] if value else [
        ROOT.parent / 'copilot-bridge',
        ROOT.parent / 'for-eigyo-pdf-lingua' / 'copilot-bridge',
        ROOT.parent / 'for-eigyo' / 'copilot-bridge',
        ROOT.parent / 'for_eigyo' / 'copilot-bridge',
    ])
    for path in candidates:
        if (path.is_absolute() and (path / 'server.py').is_file()
                and (path / 'bridge' / 'config.py').is_file()
                and (path / 'bridge' / 'edge.py').is_file()):
            return path.resolve()
    raise BridgeFailure('bridge_not_found', '既存の copilot-bridge フォルダーを指定してください。自動インストールは行いません。')


def _python_candidates(value, directory):
    suffix = Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python')
    candidates = ([Path(value)] if value else [directory / '.venv' / suffix,
        directory.parent / '.venv' / suffix, ROOT / '.venv' / suffix, Path(sys.executable),
        Path(getattr(sys, '_base_executable', sys.executable))])
    result = []
    for path in candidates:
        if (path.is_absolute() and path.is_file()
                and path.name.casefold() in {'python.exe', 'pythonw.exe', 'python', 'python3'}):
            path = path.resolve()
            if path not in result:
                result.append(path)
    if not result:
        raise BridgeFailure('python_not_found', '既存の Python 実行ファイルを指定してください。ランチャーや自動ダウンロードは使いません。')
    return result


async def _has_dependencies(python):
    child = await asyncio.create_subprocess_exec(
        str(python), '-c', 'import selenium, pyperclip',
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    try:
        return await asyncio.wait_for(child.wait(), 5) == 0
    except asyncio.TimeoutError:
        return False
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()


class _WindowsJob:
    """Owned process tree, assigned while the bootstrap is waiting on stdin."""
    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t),
                        ('maximum', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('ro', 'wo', 'oo', 'rb', 'wb', 'ob')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('pm', ctypes.c_size_t),
                        ('jm', ctypes.c_size_t), ('ppm', ctypes.c_size_t), ('pjm', ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [('user', ctypes.c_int64), ('kernel', ctypes.c_int64),
                        ('period_user', ctypes.c_int64), ('period_kernel', ctypes.c_int64),
                        ('faults', wintypes.DWORD), ('total', wintypes.DWORD),
                        ('active', wintypes.DWORD), ('terminated', wintypes.DWORD)]
        self.accounting = Accounting
        self.extended = Extended
        self.process_handles = []
        self.kernel = k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        for name, args in {
            'SetInformationJobObject': [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            'AssignProcessToJobObject': [wintypes.HANDLE, wintypes.HANDLE],
            'TerminateJobObject': [wintypes.HANDLE, wintypes.UINT],
            'QueryInformationJobObject': [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p],
            'IsProcessInJob': [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
            'CloseHandle': [wintypes.HANDLE],
        }.items():
            function = getattr(k, name)
            function.argtypes, function.restype = args, wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('Job creation failed')
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise OSError('Job configuration failed')

    def assign(self, child):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(child._handle)):
            raise OSError('Job assignment failed')

    def terminate(self):
        # Windows can remove membership before process handles signal. Seal
        # new children, then retain identity-bound handles before terminating.
        try:
            limits = self.extended()
            if not self.kernel.QueryInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None):
                raise OSError('Job limits unavailable')
            limits.basic.flags |= 0x8  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            limits.basic.active = 0
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError('Job membership seal failed')
            class ProcessIds(ctypes.Structure):
                _fields_ = [('assigned', wintypes.DWORD), ('count', wintypes.DWORD),
                            ('pids', ctypes.c_size_t * 4096)]
            members = ProcessIds()
            if (not self.kernel.QueryInformationJobObject(self.handle, 3, ctypes.byref(members), ctypes.sizeof(members), None)
                    or members.assigned != members.count or members.count > 4096):
                raise OSError('Job member snapshot incomplete')
            for pid in members.pids[:members.count]:
                process = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
                if not process:
                    if ctypes.get_last_error() == 87:  # Already exited; do not credit a handle wait.
                        continue
                    raise OSError('Job process identity unavailable')
                owned = wintypes.BOOL()
                if not self.kernel.IsProcessInJob(process, self.handle, ctypes.byref(owned)):
                    self.kernel.CloseHandle(process)
                    raise OSError('Job process ownership unavailable')
                if owned.value:
                    self.process_handles.append(process)
                else:  # PID reused: never wait on or terminate a different process.
                    self.kernel.CloseHandle(process)
        finally:
            if not self.kernel.TerminateJobObject(self.handle, 1):
                raise OSError('Job termination failed')

    def wait_stopped(self, timeout):
        deadline = time.monotonic() + timeout
        for process in self.process_handles:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if self.kernel.WaitForSingleObject(process, remaining) != 0:
                raise OSError('Owned process exit unconfirmed')

    def active(self):
        value = self.accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise OSError('Job observation failed')
        return value.active

    def close(self):
        for process in self.process_handles:
            self.kernel.CloseHandle(process)
        self.process_handles.clear()
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class _OwnedProcess:
    def __init__(self, child, job):
        self.child, self.job = child, job

    @property
    def pid(self):
        return self.child.pid

    def poll(self):
        return self.child.poll()

    async def stop(self):
        try:
            if self.job:
                self.job.terminate()  # Also cleans descendants after parent exit.
            elif self.child.poll() is None:
                os.killpg(self.child.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(self.child.wait, timeout=3)
            except subprocess.TimeoutExpired:
                if not self.job:
                    os.killpg(self.child.pid, signal.SIGKILL)
                await asyncio.to_thread(self.child.wait, timeout=3)
            if self.job:
                await asyncio.to_thread(self.job.wait_stopped, 3)
                deadline = time.monotonic() + 3
                while self.job.active():
                    if time.monotonic() >= deadline:
                        raise OSError('Owned process tree did not stop')
                    await asyncio.sleep(.05)
        finally:
            if self.job:
                self.job.close()


def _spawn_owned(python, directory, cfg, state_directory):
    parts = urlsplit(cfg['base_url'])
    command = [str(python), '-u', '-c', _BOOTSTRAP, str(directory), str(directory / 'server.py'),
               '--host', '127.0.0.1', '--port', str(parts.port or 80), '--backend', 'edge',
               '--profile-mode', 'separate', '--log-dir', '']
    environment = dict(os.environ)
    environment['COPILOT_BRIDGE_MODEL_NAME'] = cfg['model']
    environment['COPILOT_BRIDGE_PROFILE_DIR'] = str((Path(state_directory) / 'copilot-bridge' / 'profiles').resolve())
    job = _WindowsJob() if os.name == 'nt' else None
    child = None
    try:
        child = subprocess.Popen(command, cwd=directory, env=environment, shell=False,
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}))
        if job:
            job.assign(child)
        child.stdin.write(b'\n')
        child.stdin.flush()
        child.stdin.close()
        return _OwnedProcess(child, job)
    except BaseException:
        # Handshake has not succeeded, so failure before assignment cannot spawn Edge.
        if job:
            job.close()
        if child:
            if child.stdin and not child.stdin.closed:
                child.stdin.close()
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
        raise


async def _get_json(session, url):
    async with session.get(url, allow_redirects=False) as response:
        if response.status != 200:
            raise BridgeFailure('unexpected_service', '接続先が Copilot bridge の確認 API に応答しません。既存サービスは停止していません。')
        data = bytearray()
        async for chunk in response.content.iter_chunked(16384):
            data.extend(chunk)
            if len(data) > MAX_RESPONSE_BYTES:
                raise BridgeFailure('invalid_response', 'Copilot bridge の確認応答が大きすぎます。')
        try:
            return strict_json(data.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise BridgeFailure('invalid_response', 'Copilot bridge の確認応答が不正です。') from None


async def _probe(cfg):
    origin = cfg['base_url'][:-3]
    try:
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as session:
            health = await _get_json(session, origin + '/health')
            state = await _get_json(session, origin + '/status')
            models = await _get_json(session, cfg['base_url'] + '/models')
    except aiohttp.ClientConnectorError as exc:
        if exc.os_error.errno in (errno.ECONNREFUSED, 10061):
            return None
        raise BridgeFailure('connection_failed', 'Copilot bridge の接続を確認できません。') from None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise BridgeFailure('connection_failed', 'Copilot bridge の確認が失敗またはタイムアウトしました。') from None
    valid = (isinstance(health, dict) and health.get('ok') is True
             and isinstance(health.get('version'), str) and 0 < len(health['version']) <= 50
             and isinstance(state, dict) and state.get('version') == health['version']
             and state.get('backend') == 'edge' and state.get('model') == cfg['model']
             and isinstance(models, dict) and isinstance(models.get('data'), list)
             and any(isinstance(m, dict) and m.get('id') == cfg['model'] and m.get('owned_by') == 'copilot-bridge'
                     for m in models['data']))
    windows = state.get('windows') if isinstance(state, dict) else None
    valid = valid and isinstance(windows, list) and 1 <= len(windows) <= 32
    if valid:
        valid = all(isinstance(w, dict) and isinstance(w.get('id'), str)
                    and type(w.get('busy')) is bool and isinstance(w.get('error'), str) for w in windows)
        valid = valid and len({w['id'] for w in windows}) == len(windows)
    if not valid:
        raise BridgeFailure('unexpected_service', '接続先の Copilot bridge 識別・モデル・Edge 状態が一致しません。')
    if any(w['error'] for w in windows):
        raise BridgeFailure('bridge_error', 'Copilot bridge がブラウザーのエラーを報告しています。Bridge 側を確認してください。')
    return {'version': health['version'], 'windows': len(windows),
            'busy_windows': sum(w['busy'] for w in windows)}


class CopilotBridgeManager:
    def __init__(self, state_directory):
        self.state_directory = Path(state_directory)
        self._lock = asyncio.Lock()
        self._task = None
        self._owned = None
        self._config = None
        self._closed = False
        self._cleanup_failed = False
        self._stage = 'existing_bridge_probe'
        self._state = self._status('disabled', False)

    def _status(self, state, ready=False, **extra):
        return {'state': state, 'enabled': bool(self._config and self._config['enabled']),
                'ready': ready, 'owned': self._owned is not None,
                'borrowed': ready and self._owned is None, 'pid': self._owned.pid if self._owned else None,
                'inference_tested': False, 'login_verified': False, **extra}

    def status(self, config):
        """Pure cached snapshot: no requests, spawning, or environment changes."""
        cfg = _config(config)
        if not cfg['enabled']:
            if cfg == self._config and self._state.get('code') == 'cleanup_failed':
                return dict(self._state)
            return self._status('disabled', enabled=False, message='Copilot agent モードはオフです。')
        if cfg != self._config:
            return self._status('pending', enabled=True, message='Copilot bridge の設定を反映しています。')
        return dict(self._state)

    async def _stop_owned(self):
        if self._owned:
            process = self._owned
            try:
                await process.stop()
            except Exception:
                self._cleanup_failed = True
                raise BridgeFailure('cleanup_failed', '所有 Bridge の停止確認に失敗しました。プロセス状態を確認してください。') from None
            finally:
                self._owned = None

    async def _cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        await self._stop_owned()

    async def sync(self, config):
        cfg = _config(config)
        async with self._lock:
            if self._closed:
                return self._status('closed', message='Copilot bridge 管理は終了しています。')
            if cfg != self._config or not cfg['enabled']:
                try:
                    await self._cancel()
                except BridgeFailure as exc:
                    self._config = cfg
                    self._state = self._status('error', code=exc.code, message=str(exc))
                    return dict(self._state)
            self._config = cfg
            if not cfg['enabled']:
                self._state = self._status('disabled', message='Copilot agent モードはオフです。')
                return dict(self._state)
            if self._cleanup_failed:
                self._state = self._status('error', code='cleanup_failed',
                    message='所有 Bridge の停止確認に失敗したため、追加起動を停止しています。プロセス状態を確認してください。')
                return dict(self._state)
            if not self._task or self._task.done():
                self._state = self._status('starting', message='Bridge を確認・起動しています。必要なら Edge でログインしてください。')
                self._task = asyncio.create_task(self._connect(cfg))
            task = self._task
        try:
            return dict(await asyncio.shield(task))
        except asyncio.CancelledError:
            async with self._lock:
                if self._task is task:
                    await self._cancel()
                    self._state = self._status('stopped', message='Copilot bridge の起動を取り消しました。')
            raise

    async def _prepare_connect(self, cfg):
        if self._owned and self._owned.poll() is not None:
            await self._stop_owned()
        self._stage = 'existing_bridge_probe'
        observed = await _probe(cfg)
        if observed is None:
            if self._owned:
                await self._stop_owned()
            self._stage = 'locating_bridge'
            directory = _bridge_directory(cfg['bridge_directory'])
            self._stage = 'checking_python'
            python = None
            for candidate in _python_candidates(cfg['python_executable'], directory):
                if await _has_dependencies(candidate):
                    python = candidate
                    break
            if python is None:
                raise BridgeFailure('dependencies_missing', '指定 Python に selenium と pyperclip が必要です。既存の依存導入済み Python を指定してください。')
            self._stage = 'starting_bridge'
            self._owned = _spawn_owned(python, directory, cfg, self.state_directory)
            self._stage = 'owned_bridge_probe'
            self._state = self._status('starting', message='Edge と Copilot の準備を待っています。必要なら開いた Edge でログインしてください。')
            while observed is None:
                if self._owned.poll() is not None:
                    raise BridgeFailure('startup_failed', 'Copilot bridge が起動中に終了しました。Python・Edge ドライバー・Bridge 設定を確認してください。')
                await asyncio.sleep(POLL_SECONDS)
                try:
                    observed = await _probe(cfg)
                except BridgeFailure as exc:
                    # Only our already-started child is awaited here. A transient
                    # transport failure is bounded by the outer startup deadline;
                    # identity/contract failures still stop immediately.
                    if exc.code != 'connection_failed':
                        raise
            if self._owned.poll() is not None:
                raise BridgeFailure('startup_failed', '起動した Copilot bridge の終了を検出しました。')
        return observed

    async def _connect(self, cfg):
        self._stage = 'existing_bridge_probe'
        try:
            observed = await asyncio.wait_for(self._prepare_connect(cfg), cfg['startup_timeout_seconds'])
            self._state = self._status('ready', True, **observed,
                message='Bridge API に接続しました。ログインの継続・推論・ツール応答は未検証です。')
        except asyncio.CancelledError:
            await self._stop_owned()
            raise
        except Exception as exc:
            failed_stage = self._stage
            if isinstance(exc, asyncio.TimeoutError):
                exc = BridgeFailure('startup_timeout', 'Copilot bridge の起動待機が時間切れです。ログイン・ドライバー・待機時間を確認してください。')
            cleanup_failed = False
            try:
                await self._stop_owned()
            except Exception:
                cleanup_failed = True
            stage_message = {
                'existing_bridge_probe': 'Bridge 起動前の接続確認で停止しました。',
                'locating_bridge': 'Bridge フォルダーの確認で停止しました。',
                'checking_python': '起動に使う Python・依存ライブラリの確認で停止しました。',
                'starting_bridge': 'Bridge プロセスの起動処理で停止しました。',
                'owned_bridge_probe': 'Bridge 起動後の API 接続待機で停止しました。',
            }[failed_stage]
            detail = (str(exc) if isinstance(exc, BridgeFailure) else
                      'Copilot bridge の起動または確認に失敗しました。設定を確認してください。')
            self._state = self._status('error', stage=failed_stage,
                code='cleanup_failed' if cleanup_failed else getattr(exc, 'code', 'startup_failed'),
                message=('所有 Bridge の停止確認に失敗しました。プロセス状態を確認してください。' if cleanup_failed else
                         stage_message + detail))
        return dict(self._state)

    async def ensure(self, config):
        cfg = _config(config)
        if not cfg['enabled']:
            return
        if self._closed or cfg != self._config or not self._state.get('ready'):
            raise ValueError('Copilot bridge は準備できていません。接続状態と Edge のログインを確認してください。')
        try:
            observed = await _probe(cfg)
            if self._closed or cfg != self._config or not self._state.get('ready'):
                raise ValueError('Copilot bridge の設定または状態が変わりました。接続状態を確認してください。')
            if observed is None or (self._owned and self._owned.poll() is not None):
                raise BridgeFailure('disconnected', 'Copilot bridge の接続が失われました。')
        except BridgeFailure as exc:
            self._state = self._status('error', code=exc.code, message=str(exc))
            raise ValueError(str(exc)) from None
        self._state = self._status('ready', True, **observed,
            message='Bridge API に接続しました。ログインの継続・推論・ツール応答は未検証です。')

    async def close(self):
        async with self._lock:
            self._closed = True
            await self._cancel()
            self._state = self._status('closed', message='Copilot bridge 管理を終了しました。')
