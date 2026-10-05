"""Development-only real Windows console interrupt test of the packaged EXE.

Python drives the test; the application child has a system-only environment.
Only the newly spawned application's private console receives CTRL_C_EVENT.
"""
from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, ProxyHandler, build_opener


def interrupt_private_console(process):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.GetConsoleProcessList.restype = wintypes.DWORD
    kernel.FreeConsole.restype = wintypes.BOOL
    kernel.AttachConsole.argtypes = [wintypes.DWORD]
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
    pids = (wintypes.DWORD * 128)()
    count = kernel.GetConsoleProcessList(pids, 128)
    previous = [pids[index] for index in range(min(count, 128)) if pids[index] != os.getpid()]
    attached = False
    try:
        kernel.FreeConsole()
        if process.poll() is not None or not kernel.AttachConsole(process.pid):
            raise RuntimeError('Could not attach to the spawned private console')
        attached = True
        if not kernel.SetConsoleCtrlHandler(None, True):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.GenerateConsoleCtrlEvent(0, 0):  # CTRL_C_EVENT: this private console only
            raise ctypes.WinError(ctypes.get_last_error())
        code = process.wait(timeout=15)
        if code != 130:
            raise AssertionError(f'Expected handled console interrupt (130), got {code}')
    finally:
        if attached:
            kernel.FreeConsole()
        for pid in previous:
            if kernel.AttachConsole(pid):
                break
        kernel.SetConsoleCtrlHandler(None, False)


def main():
    if os.name != 'nt':
        raise RuntimeError('This check requires Windows')
    executable = Path(os.environ['WORKBENCH_PORTABLE_EXE']).resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    report_path = root / 'runtime' / 'verification' / 'portable-console.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    held, release = threading.Event(), threading.Event()
    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.send_error(404)
                return
            length = int(self.headers.get('Content-Length', '0'))
            assert 0 < length < 1024 * 1024
            self.rfile.read(length)
            held.set()
            release.wait(30)
            with contextlib.suppress(BrokenPipeError, ConnectionResetError, OSError):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"role":"assistant","content":"fixture"},"finish_reason":"stop"}]}')
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    thread = threading.Thread(target=model.serve_forever, daemon=True)
    thread.start()
    report = {'schema_version': 1, 'fixture': 'SYNTHETIC; actual frozen EXE; no live inference',
              'commit': os.environ.get('GITHUB_SHA'), 'application': str(executable), 'checks': [], 'passed': False}
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='workbench-console-') as temp:
            sandbox = Path(temp) / '会社 console & !'
            sandbox.mkdir()
            state = sandbox / 'state'
            profile = sandbox / 'profile'
            profile.mkdir()
            env = {'SystemRoot': os.environ['SystemRoot'], 'WINDIR': os.environ['SystemRoot'],
                   'PATH': str(Path(os.environ['SystemRoot']) / 'System32'),
                   'USERPROFILE': str(profile), 'LOCALAPPDATA': str(profile),
                   'TEMP': str(sandbox), 'TMP': str(sandbox)}
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            command = [str(executable), '--no-browser', '--port', str(port), '--state-dir', str(state)]
            opener = build_opener(ProxyHandler({}))
            cookie = ''
            origin = f'http://127.0.0.1:{port}'
            def api(route, data=None, extra=None):
                headers = {'Origin': origin, 'Cookie': cookie, **(extra or {})}
                encoded = None if data is None else json.dumps(data).encode()
                if encoded is not None:
                    headers['Content-Type'] = 'application/json'
                request = Request(origin + route, data=encoded, headers=headers,
                                  method='PUT' if route == '/api/config' and data is not None else None)
                with opener.open(request, timeout=5) as response:
                    return json.load(response), response.headers
            for cycle in range(2):
                log_path = sandbox / f'console-{cycle}.log'
                with log_path.open('wb') as log:
                    process = subprocess.Popen(command, cwd=sandbox, env=env, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=log, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    deadline = time.monotonic() + 30
                    token = None
                    while time.monotonic() < deadline:
                        text = log_path.read_text(encoding='utf-8', errors='replace')
                        match = re.search(r'#token=([A-Za-z0-9_-]+)', text)
                        if match:
                            token = match[1]
                            break
                        if process.poll() is not None:
                            raise AssertionError('Packaged app exited during console startup: ' + re.sub(r'#token=\S+', '#token=[redacted]', text))
                        time.sleep(.1)
                    assert token, 'Console app did not produce its bootstrap URL'
                    _, headers = api('/api/bootstrap', {}, {'X-Workbench-Bootstrap': token})
                    cookie = headers['Set-Cookie'].split(';', 1)[0]
                    if cycle == 0:
                        public, _ = api('/api/config')
                        config = public['config']
                        config['providers'] = [{**config['providers'][0], 'model': 'console-fixture',
                            'base_url': f'http://127.0.0.1:{model.server_port}/v1'}]
                        api('/api/config', config)
                        api('/api/runs', {'task': '[SYNTHETIC] Wait for interruption', 'pm_profile': 'local',
                                           'worker_profiles': [], 'max_workers': 0})
                        assert held.wait(10), 'Real provider request was not held by local fixture'
                    interrupt_private_console(process)
                    report['checks'].append('Ctrl+C handled with active provider request' if cycle == 0 else 'same state/port restarted and interrupted cleanly')
                    with socket.socket() as probe:
                        probe.settimeout(.3)
                        assert probe.connect_ex(('127.0.0.1', port)) != 0, 'Listener remained open'
                    process = None
            report['checks'].append('listener closed after both console interrupts')
            report['passed'] = True
    except Exception as exc:
        report['error'] = re.sub(r'#token=\S+', '#token=[redacted]', str(exc))
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        release.set()
        model.shutdown()
        model.server_close()
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
