"""Shared launcher arguments plus real Windows duplicate-launch smoke coverage."""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('start_workbench', ROOT / 'scripts/start_workbench.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.skipif(os.name == 'nt', reason='Unit case uses non-Windows branch; real Windows smoke below')
def test_launch_arguments(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launcher.subprocess, 'call', lambda args, **kwargs: calls.append((args, kwargs)) or 17)
    state = tmp_path / '会社 state & !'
    assert launcher.main(['--project-root', str(ROOT), '-Port', '8820', '-StateDir', str(state), '-NoBrowser']) == 17
    assert calls == [([sys.executable, '-m', 'workbench.server', '--port', '8820', '--no-browser', '--state-dir', str(state)], {'cwd': ROOT})]


def test_invalid_port():
    with pytest.raises(SystemExit):
        launcher.main(['--port', '65536'])


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows mutex and console process group required')
def test_windows_duplicate_launch(tmp_path):
    import signal
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    state = tmp_path / '会社 state with spaces'
    command = [sys.executable, str(ROOT / 'scripts/start_workbench.py'), '--no-browser', '--port', str(port), '--state-dir', str(state)]
    output = tmp_path / 'launcher.log'
    with output.open('w') as log:
        first = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if first.poll() is not None:
                    pytest.fail(output.read_text())
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                pytest.fail('Listener did not start: ' + output.read_text())
            second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
            assert second.returncode == 0, second.stdout + second.stderr
            assert 'already starting/running' in second.stdout
            assert first.poll() is None
        finally:
            if first.poll() is None:
                first.send_signal(signal.CTRL_BREAK_EVENT)
                try:
                    first.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    first.kill()
                    first.wait(timeout=10)
