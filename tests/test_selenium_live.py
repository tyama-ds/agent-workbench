"""Opt-in installed-browser smoke test; downloads nothing, uses no user profile.

Set AWB_TEST_BROWSER_EXE, AWB_TEST_DRIVER_EXE, AWB_TEST_PYTHON_EXE and
AWB_TEST_SELENIUM_LIB to existing absolute paths. Optional AWB_TEST_BROWSER=edge
or chrome (default chrome). The fixture only serves a synthetic loopback page.
"""
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from workbench.config import DEFAULT
from workbench.harness import PathHarness
from workbench.selenium_runner import execute_selenium

_PATH_KEYS = ('AWB_TEST_BROWSER_EXE', 'AWB_TEST_DRIVER_EXE', 'AWB_TEST_PYTHON_EXE', 'AWB_TEST_SELENIUM_LIB')
pytestmark = pytest.mark.skipif(os.name != 'nt' or not all(os.environ.get(key) for key in _PATH_KEYS),
                                reason='Explicit existing Windows browser/driver/Python/library paths required')


class _Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'''<!doctype html><title>Workbench Selenium fixture</title>
<label>Name <input id="name"></label><button id="apply" onclick="document.getElementById('result').textContent='Hello '+document.getElementById('name').value">Apply</button>
<p id="result">Waiting</p><input id="upload" type="file">
<button id="special:id">Special</button><button id="duplicate">First</button><button id="duplicate">Second</button>
<input id="secret" type="password" value="fixture-password-value" placeholder="Password">
<textarea id="notes" placeholder="Notes">fixture-textarea-value</textarea>'''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_browser(tmp_path):
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {**DEFAULT['selenium'], 'enabled': True,
        'browser': os.environ.get('AWB_TEST_BROWSER', 'chrome'),
        'browser_executable': os.environ['AWB_TEST_BROWSER_EXE'],
        'driver_executable': os.environ['AWB_TEST_DRIVER_EXE'],
        'library_paths': [os.environ['AWB_TEST_SELENIUM_LIB']]}
    python = {**DEFAULT['python'], 'executable': os.environ['AWB_TEST_PYTHON_EXE'], 'network_enabled': True}
    harness = PathHarness([str(tmp_path)], [str(tmp_path)])
    try:
        yield config, python, harness, f'http://127.0.0.1:{server.server_port}/'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.mark.asyncio
async def test_installed_browser_fill_click_read_and_scoped_screenshot(local_browser, tmp_path):
    config, python, harness, url = local_browser
    receipts = []
    result = await execute_selenium(config, python, harness, url, actions=[
        {'action': 'fill', 'selector': '#name', 'text': 'Workbench'},
        {'action': 'click', 'selector': '#apply'},
        {'action': 'wait', 'selector': '#result'},
        {'action': 'read', 'selector': '#result'}],
        screenshot={'path': str(tmp_path / 'browser.png'), 'expected_sha256': 'missing'},
        on_complete=receipts.append)
    assert result['exit_code'] == 0 and result['termination_reason'] is None, result
    assert result['title'] == 'Workbench Selenium fixture'
    assert result['actions'][3]['text'] == 'Hello Workbench'
    elements = result['elements']
    special = next(item for item in elements if item['label'] == 'Special')
    assert special['selector'] == '#special\\:id'
    duplicates = [item for item in elements if item['label'] in ('First', 'Second')]
    assert len(duplicates) == 2 and all(':nth-of-type(' in item['selector'] for item in duplicates)
    assert duplicates[0]['selector'] != duplicates[1]['selector']
    assert 'fixture-password-value' not in str(elements) and 'fixture-textarea-value' not in str(elements)
    assert result['isolation'] == 'windows-job'
    assert (tmp_path / 'browser.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert result['outputs'] == receipts and len(receipts) == 1


@pytest.mark.asyncio
async def test_installed_browser_refuses_file_input_fill_and_no_screenshot(local_browser, tmp_path):
    config, python, harness, url = local_browser
    result = await execute_selenium(config, python, harness, url, actions=[
        {'action': 'fill', 'selector': '#upload', 'text': 'C:\\not-uploaded.txt'}],
        screenshot={'path': str(tmp_path / 'must-not-exist.png'), 'expected_sha256': 'missing'})
    assert result['exit_code'] != 0 and result['outputs'] == []
    assert 'Only editable text inputs' in result['stderr'], result
    assert not (tmp_path / 'must-not-exist.png').exists()
