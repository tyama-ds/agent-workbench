"""Fixed browser operations and publication boundaries; no browser downloads."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import selenium_runner as runner
from workbench import selenium_worker as worker
from workbench.harness import HarnessError, PathHarness
from workbench.windows_sandbox import SandboxError

PNG = b'\x89PNG\r\n\x1a\nsynthetic-screenshot'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    target, denied = tmp_path / 'write', tmp_path / 'denied'
    target.mkdir()
    denied.mkdir()
    harness = PathHarness([], [str(target), str(denied)], [str(denied)])
    config = {'enabled': True, 'browser': 'edge', 'browser_executable': 'selected-edge.exe',
              'driver_executable': 'selected-driver.exe', 'library_paths': [], 'proxy_url': '',
              'timeout_seconds': 10, 'max_memory_mb': 1024, 'max_output_chars': 20000}
    python = {'executable': 'python.exe', 'library_paths': [], 'network_enabled': True}
    monkeypatch.setattr(runner, '_runtime', lambda *_: (Path('python.exe'), [], Path('msedge.exe'), Path('msedgedriver.exe')))
    return config, python, harness, target, denied


def execute(setup, **kwargs):
    return asyncio.run(runner.execute_selenium(*setup[:3], 'https://example.test/', **kwargs))


def success(workspace, *, screenshot=False, actions=None):
    result = {'url': 'https://example.test/', 'title': 'Example', 'text': 'Page body',
              'actions': actions or [], 'elements': [], 'truncated': False}
    (workspace / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    if screenshot:
        (workspace / 'screenshot.png').write_bytes(PNG)
    return {'exit_code': 0, 'termination_reason': None, 'stdout': '', 'stderr': '', 'isolation': 'windows-job'}


@pytest.mark.parametrize('url', [
    'file:///C:/secret.txt', 'data:text/plain,secret', 'javascript:alert(1)', 'about:blank',
    'https://name:password@example.test', '//example.test/', 'https://example.test:bad/',
    'https://example.test\\@outside.test', 'https://exam\nple.test', 'https://%65xample.test/',
])
def test_rejects_non_http_and_ambiguous_urls(url):
    with pytest.raises(ValueError):
        worker.validate_url(url)


@pytest.mark.parametrize('url', ['http://127.0.0.1:8080/', 'https://example.test/資料?q=test#fragment', 'http://[::1]:8080/'])
def test_http_urls_are_not_a_network_scope_allowlist(url):
    assert worker.validate_url(url) == url


@pytest.mark.parametrize('actions', [
    [{'action': [], 'selector': 'body'}],
    [{'action': {}, 'selector': 'body'}],
    [{'action': None, 'selector': 'body'}],
    [{'action': 'script', 'selector': 'body', 'code': 'evil'}],
    [{'action': 'click', 'selector': 'body', 'options': {}}],
    [{'action': 'fill', 'selector': 'input'}],
    [{'action': 'read', 'selector': 'body', 'text': 'unused'}],
    [{'action': 'wait', 'selector': 'body'}] * 21,
    [{'action': 'fill', 'selector': 'input', 'text': 'a' * 8001}],
    [{'action': 'fill', 'selector': 'input', 'text': '\ud800'}],
])
def test_rejects_arbitrary_operations_and_oversized_actions(actions):
    with pytest.raises((ValueError, UnicodeError)):
        worker.validate_actions(actions)


@pytest.mark.parametrize('proxy', ['http://user:pass@proxy.test:8080', 'socks5://proxy.test:1080',
                                  'https://proxy.test/path', 'https://proxy.test?token=secret'])
def test_proxy_rejects_unsupported_auth_and_protocol(proxy):
    with pytest.raises(ValueError):
        worker.validate_proxy(proxy)


def test_off_and_network_off_fail_before_runtime_or_process(setup, monkeypatch):
    monkeypatch.setattr(runner, '_runtime', lambda *a: pytest.fail('Must not inspect runtime'))
    monkeypatch.setattr(runner, 'run_browser_job', lambda *a, **k: pytest.fail('Must not start processes'))
    for flag in (False, None, 1, 'true'):
        setup[0]['enabled'] = flag
        with pytest.raises(HarnessError, match='disabled'):
            execute(setup)
    setup[0]['enabled'] = True
    for flag in (False, None, 1, 'true'):
        setup[1]['network_enabled'] = flag
        with pytest.raises(HarnessError, match='network permission'):
            execute(setup)


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
def test_fixed_job_cleaned_before_screenshot_publication(setup, monkeypatch):
    config, python, harness, target, _ = setup
    saved, workspaces = [], []
    def native(command, workspace, **limits):
        workspaces.append(workspace)
        assert command[1:7] == ['-I', '-S', '-B', '-u', '-X', 'utf8']
        assert command[7:] == [str(workspace / 'worker.py'), str(workspace / 'job.json')]
        job = json.loads((workspace / 'job.json').read_text(encoding='utf-8'))
        assert job['browser_executable'] == 'msedge.exe'
        assert job['driver_executable'] == 'msedgedriver.exe'
        assert job['screenshot_requested'] is True
        assert str(target) not in (workspace / 'job.json').read_text()
        assert limits['memory_mb'] == 1024 and limits['timeout'] == 10
        assert (workspace / 'worker.py').read_bytes() == Path(worker.__file__).read_bytes()
        return success(workspace, screenshot=True)
    original = harness.write_bytes
    def publish(*args, **kwargs):
        assert not workspaces[0].exists()
        return original(*args, **kwargs)
    monkeypatch.setattr(runner, 'run_browser_job', native)
    monkeypatch.setattr(harness, 'write_bytes', publish)
    result = execute(setup, screenshot={'path': str(target / 'page.png'), 'expected_sha256': 'missing'}, on_complete=saved.append)
    assert result['outputs'] == saved and len(saved) == 1
    assert (target / 'page.png').read_bytes() == PNG
    assert result['text'] == 'Page body' and result['isolation'] == 'windows-job'


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
def test_screenshot_denial_and_hash_preflight_never_launch(setup, monkeypatch):
    _, _, _, target, denied = setup
    monkeypatch.setattr(runner, 'run_browser_job', lambda *a, **k: pytest.fail('Must not launch'))
    with pytest.raises(HarnessError, match='denied'):
        execute(setup, screenshot={'path': str(denied / 'private.png'), 'expected_sha256': 'missing'})
    (target / 'existing.png').write_bytes(PNG)
    with pytest.raises(HarnessError, match='changed'):
        execute(setup, screenshot={'path': str(target / 'existing.png'), 'expected_sha256': 'missing'})
    with pytest.raises(HarnessError, match='.png'):
        execute(setup, screenshot={'path': str(target / 'program.exe'), 'expected_sha256': 'missing'})


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
def test_screenshot_concurrent_change_is_not_overwritten(setup, monkeypatch):
    path = setup[3] / 'page.png'
    def native(command, workspace, **limits):
        result = success(workspace, screenshot=True)
        path.write_bytes(b'concurrent writer')
        return result
    monkeypatch.setattr(runner, 'run_browser_job', native)
    result = execute(setup, screenshot={'path': str(path), 'expected_sha256': 'missing'})
    assert result['outputs'] == [] and 'changed' in result['publication_error']
    assert path.read_bytes() == b'concurrent writer'


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
@pytest.mark.parametrize('reason,code', [('timeout', 1), ('cancelled', 1), ('memory_limit', 1), (None, 1)])
def test_failed_or_limited_jobs_never_publish(setup, monkeypatch, reason, code):
    def native(command, workspace, **limits):
        result = success(workspace, screenshot=True)
        return {**result, 'exit_code': code, 'termination_reason': reason}
    monkeypatch.setattr(runner, 'run_browser_job', native)
    result = execute(setup, screenshot={'path': str(setup[3] / 'page.png'), 'expected_sha256': 'missing'})
    assert result['outputs'] == [] and not (setup[3] / 'page.png').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
@pytest.mark.parametrize('corrupt', ['json', 'overlong', 'not_png', 'hardlink'])
def test_bad_results_and_screenshots_are_rejected(setup, monkeypatch, corrupt):
    outside = setup[3] / 'source.png'
    outside.write_bytes(PNG)
    def native(command, workspace, **limits):
        result = success(workspace, screenshot=True)
        if corrupt == 'json':
            (workspace / 'result.json').write_text('{broken')
        elif corrupt == 'overlong':
            data = json.loads((workspace / 'result.json').read_text())
            data['text'] = 'x' * 20001
            (workspace / 'result.json').write_text(json.dumps(data))
        elif corrupt == 'not_png':
            (workspace / 'screenshot.png').write_bytes(b'not a png')
        elif corrupt == 'hardlink':
            (workspace / 'screenshot.png').unlink()
            os.link(outside, workspace / 'screenshot.png')
        return result
    monkeypatch.setattr(runner, 'run_browser_job', native)
    with pytest.raises(HarnessError):
        execute(setup, screenshot={'path': str(setup[3] / 'page.png'), 'expected_sha256': 'missing'})
    assert outside.read_bytes() == PNG and outside.stat().st_nlink == 1
    assert not (setup[3] / 'page.png').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
def test_unconfirmed_descendant_exit_retains_workspace(setup, monkeypatch):
    workspaces = []
    def native(command, workspace, **limits):
        workspaces.append(workspace)
        raise SandboxError('Job descendants have not stopped', preserve_private=True)
    monkeypatch.setattr(runner, 'run_browser_job', native)
    try:
        with pytest.raises(HarnessError, match='storage retained'):
            execute(setup)
        assert (workspaces[0] / 'job.json').exists()
    finally:
        for path in workspaces:
            assert path.resolve() == path and path.name.startswith('awb-selenium-')
            shutil.rmtree(path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
def test_cleanup_failure_prevents_publication(setup, monkeypatch):
    workspaces = []
    def native(command, workspace, **limits):
        workspaces.append(workspace)
        return success(workspace, screenshot=True)
    original = shutil.rmtree
    def fail_cleanup(path):
        raise OSError('synthetic cleanup failure')
    monkeypatch.setattr(runner, 'run_browser_job', native)
    monkeypatch.setattr(runner.shutil, 'rmtree', fail_cleanup)
    try:
        with pytest.raises(HarnessError, match='cleanup failed'):
            execute(setup, screenshot={'path': str(setup[3] / 'page.png'), 'expected_sha256': 'missing'})
        assert not (setup[3] / 'page.png').exists()
    finally:
        for path in workspaces:
            assert path.resolve() == path and path.name.startswith('awb-selenium-')
            original(path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows process integration')
def test_repeated_cancel_waits_for_native_cleanup(setup, monkeypatch):
    started, stopped = threading.Event(), threading.Event()
    workspaces = []
    def native(command, workspace, *, cancel, **limits):
        workspaces.append(workspace)
        started.set()
        assert cancel.wait(5)
        time.sleep(.05)
        stopped.set()
        return {'exit_code': 1, 'termination_reason': 'cancelled', 'stdout': '', 'stderr': ''}
    monkeypatch.setattr(runner, 'run_browser_job', native)
    async def scenario():
        task = asyncio.create_task(runner.execute_selenium(*setup[:3], 'https://example.test/'))
        while not started.is_set():
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and not workspaces[0].exists()
    asyncio.run(scenario())


def test_runtime_combines_explicit_libraries_and_resolves_venv(tmp_path):
    base, venv = tmp_path / 'base', tmp_path / 'venv'
    (base / 'Lib').mkdir(parents=True)
    (base / 'python.exe').write_bytes(b'existing interpreter fixture')
    (venv / 'Scripts').mkdir(parents=True)
    (venv / 'Scripts' / 'python.exe').write_bytes(b'existing launcher fixture')
    (venv / 'pyvenv.cfg').write_text(f'home = {base}', encoding='utf-8')
    browser, driver = tmp_path / 'msedge.exe', tmp_path / 'msedgedriver.exe'
    for path in (browser, driver):
        path.write_bytes(b'existing executable fixture')
    first, second = tmp_path / 'selenium-packages', tmp_path / 'python-packages'
    first.mkdir()
    second.mkdir()
    config = {'browser': 'edge', 'browser_executable': str(browser), 'driver_executable': str(driver),
              'library_paths': [str(first)]}
    python = {'executable': str(venv / 'Scripts' / 'python.exe'), 'library_paths': [str(second), str(first)]}
    executable, libraries, resolved_browser, resolved_driver = runner._runtime(config, python, PathHarness([], []))
    assert executable == base / 'python.exe'
    assert libraries == [first, second]
    assert resolved_browser == browser and resolved_driver == driver


class Element:
    tag_name = 'input'
    def __init__(self, text='', kind='text', href=None):
        self.text, self.kind, self.href = text, kind, href
        self.clicked, self.value = False, None
    def is_displayed(self):
        return True
    def get_attribute(self, name):
        return self.kind if name == 'type' else self.href if name == 'href' else None
    def click(self):
        self.clicked = True
    def send_keys(self, *args):
        pytest.fail('send_keys must not be used for filling')


class Driver:
    title = 'Example title'
    current_url = 'about:blank'
    def __init__(self):
        self.events, self.elements, self.closed = [], {}, False
        self.download_failure = False
        self.body = 'Page body'
        self.discovered = {'elements': [], 'truncated': False}
    def set_page_load_timeout(self, value):
        self.events.append(('page_timeout', value))
    def set_script_timeout(self, value):
        self.events.append(('script_timeout', value))
    def implicitly_wait(self, value):
        assert value == 0
    def execute_cdp_cmd(self, name, args):
        self.events.append((name, args))
        if self.download_failure:
            raise RuntimeError('Download denial unsupported')
    def get(self, url):
        self.events.append(('get', url))
        self.current_url = url
    def find_element(self, kind, selector):
        assert kind == 'css selector'
        return self.elements[selector]
    def execute_script(self, source, *args):
        self.events.append(('fixed_script', source))
        if source == worker._FILL:
            element, value = args
            if element.kind == 'file':
                raise ValueError('Only editable text inputs and textareas may be filled')
            element.value = value
        elif source == worker._READ:
            return args[0].text[:args[1]]
        elif source == worker._BODY:
            return self.body[:args[0]]
        elif source == worker._ELEMENTS:
            assert args == (40,)
            return self.discovered
        else:
            pytest.fail('Unexpected script')
    def get_screenshot_as_png(self):
        return PNG
    def quit(self):
        self.closed = True


@pytest.fixture
def browser(monkeypatch):
    exceptions = types.ModuleType('selenium.common.exceptions')
    exceptions.NoSuchElementException = type('NoSuchElementException', (Exception,), {})
    exceptions.StaleElementReferenceException = type('StaleElementReferenceException', (Exception,), {})
    monkeypatch.setitem(sys.modules, 'selenium.common.exceptions', exceptions)
    return Driver()


def worker_job(**changes):
    return {'url': 'https://example.test/', 'actions': [], 'max_output_chars': 20000,
            'timeout_seconds': 10, 'screenshot_requested': False, 'max_screenshot_bytes': 1048576,
            **changes}


def test_worker_fixed_actions_no_send_keys_and_bounded_result(tmp_path, browser):
    browser.elements = {'#name': Element(), '#read': Element('資料' * 10000), '#link': Element(href='https://example.test/next')}
    browser.body = 'body' * 20000
    actions = [{'action': 'fill', 'selector': '#name', 'text': 'A secret value'},
               {'action': 'click', 'selector': '#link'}, {'action': 'wait', 'selector': '#name'},
               {'action': 'read', 'selector': '#read'}]
    result = worker.run_job(worker_job(actions=actions, max_output_chars=1000, screenshot_requested=True),
                            tmp_path, driver_factory=lambda *_: browser)
    assert browser.elements['#name'].value == 'A secret value'
    assert browser.elements['#link'].clicked and browser.closed
    assert sum(len(result[k]) for k in ('title', 'url', 'text')) + len(result['actions'][3]['text']) <= 1000
    assert result['truncated'] is True and (tmp_path / 'screenshot.png').read_bytes() == PNG
    assert 'A secret value' not in json.dumps(result)
    events = [name for name, _ in browser.events]
    assert events.index('Browser.setDownloadBehavior') < events.index('get')


def test_worker_download_denial_failure_stops_before_navigation(tmp_path, browser):
    browser.download_failure = True
    with pytest.raises(RuntimeError, match='Download denial'):
        worker.run_job(worker_job(), tmp_path, driver_factory=lambda *_: browser)
    assert browser.closed and not any(name == 'get' for name, _ in browser.events)


@pytest.mark.parametrize('action', ['click', 'fill'])
def test_worker_refuses_file_inputs(tmp_path, browser, action):
    browser.elements['input'] = Element(kind='file')
    operation = {'action': action, 'selector': 'input'}
    if action == 'fill':
        operation['text'] = 'C:\\outside\\private.txt'
    with pytest.raises(ValueError):
        worker.run_job(worker_job(actions=[operation]), tmp_path, driver_factory=lambda *_: browser)
    assert browser.closed and not browser.elements['input'].clicked


def test_worker_refuses_non_http_links_before_click(tmp_path, browser):
    browser.elements['a'] = Element(href='file:///C:/private.txt')
    with pytest.raises(ValueError):
        worker.run_job(worker_job(actions=[{'action': 'click', 'selector': 'a'}]), tmp_path, driver_factory=lambda *_: browser)
    assert not browser.elements['a'].clicked and browser.closed


def test_worker_checks_navigation_after_click(tmp_path, browser):
    element = Element()
    element.click = lambda: setattr(browser, 'current_url', 'data:text/plain,unsupported')
    browser.elements['a'] = element
    with pytest.raises(ValueError):
        worker.run_job(worker_job(actions=[{'action': 'click', 'selector': 'a'}]), tmp_path, driver_factory=lambda *_: browser)
    assert browser.closed


def test_discovered_elements_keep_complete_selectors_and_share_text_budget(tmp_path, browser):
    browser.discovered = {'elements': [
        {'selector': 'body > ' + 'a' * 600, 'tag': 'a', 'label': 'Cannot fit'},
        {'selector': '#go\\:now', 'tag': 'button', 'label': 'Go now'},
        {'selector': 'body > input:nth-of-type(2)', 'tag': 'input', 'label': 'Search'},
        {'selector': '#link', 'tag': 'a', 'label': 'External', 'href': 'https://example.test/' + 'x' * 600},
    ], 'truncated': False}
    browser.body = '資料' * 1000
    result = worker.run_job(worker_job(max_output_chars=1000), tmp_path, driver_factory=lambda *_: browser)
    assert result['elements'] == [
        {'selector': '#go\\:now', 'tag': 'button', 'label': 'Go now'},
        {'selector': 'body > input:nth-of-type(2)', 'tag': 'input', 'label': 'Search'},
        {'selector': '#link', 'tag': 'a', 'label': 'External'},
    ]
    text_count = sum(len(result[key]) for key in ('title', 'url', 'text'))
    text_count += sum(len(value) for item in result['elements'] for value in item.values())
    assert text_count == 1000 and result['truncated'] is True
    (tmp_path / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    assert runner._read_result(tmp_path, 1000, []) == result


def test_discovery_truncation_is_reported_even_when_text_fits(tmp_path, browser):
    browser.discovered = {'elements': [
        {'selector': '#link', 'tag': 'a', 'label': '', 'href': 'https://example.test/'}
    ], 'truncated': True}
    result = worker.run_job(worker_job(), tmp_path, driver_factory=lambda *_: browser)
    assert result['elements'] == browser.discovered['elements']
    assert result['truncated'] is True


@pytest.mark.parametrize('elements', [
    [{'selector': '#x', 'tag': 'input', 'label': 'Name', 'value': 'must not leak'}],
    [{'selector': '#x', 'tag': 'script', 'label': ''}],
    [{'selector': '#x', 'tag': [], 'label': ''}],
    [{'selector': '#x', 'tag': 'input', 'label': 'x' * 121}],
    [{'selector': '', 'tag': 'input', 'label': ''}],
    [{'selector': '#x', 'tag': 'a', 'label': 'Link', 'href': 'javascript:alert(1)'}],
    [{'selector': '#x', 'tag': 'input', 'label': ''}] * 41,
])
def test_discovery_rejects_extra_fields_unsafe_links_and_invalid_shapes(tmp_path, browser, elements):
    browser.discovered = {'elements': elements, 'truncated': False}
    with pytest.raises(ValueError):
        worker.run_job(worker_job(), tmp_path, driver_factory=lambda *_: browser)
    assert browser.closed
    raw = {'title': '', 'url': 'https://example.test/', 'text': '', 'actions': [],
           'elements': elements, 'truncated': False}
    (tmp_path / 'result.json').write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(HarnessError, match='invalid result'):
        runner._read_result(tmp_path, 20000, [])


def test_element_strings_count_toward_runner_result_limit(tmp_path):
    raw = {'title': '', 'url': 'https://example.test/', 'text': 'x' * 970, 'actions': [],
           'elements': [{'selector': '#input', 'tag': 'input', 'label': 'Name'}], 'truncated': False}
    (tmp_path / 'result.json').write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(HarnessError, match='invalid result'):
        runner._read_result(tmp_path, 1000, [])


@pytest.mark.parametrize('kind', ['edge', 'chrome'])
def test_driver_uses_explicit_service_binary_and_fresh_profile(tmp_path, monkeypatch, kind):
    created = {}
    class Options:
        def __init__(self):
            self.arguments, self.experimental = [], {}
        def add_argument(self, value):
            self.arguments.append(value)
        def add_experimental_option(self, key, value):
            self.experimental[key] = value
    class Service:
        def __init__(self, **kwargs):
            created['service_args'] = kwargs
    def factory(**kwargs):
        created.update(kwargs)
        return 'driver'
    webdriver = types.SimpleNamespace(EdgeOptions=Options, ChromeOptions=Options, Edge=factory, Chrome=factory)
    monkeypatch.setitem(sys.modules, 'selenium', types.SimpleNamespace(webdriver=webdriver))
    monkeypatch.setitem(sys.modules, f'selenium.webdriver.{kind}.service', types.SimpleNamespace(Service=Service))
    job = {'browser': kind, 'browser_executable': 'C:\\approved\\browser.exe',
           'driver_executable': 'C:\\approved\\driver.exe', 'proxy_url': 'http://proxy.test:8080'}
    assert worker.create_driver(job, tmp_path) == 'driver'
    assert created['service_args']['executable_path'] == job['driver_executable']
    assert created['service_args']['service_args'] == ['--allowed-ips=127.0.0.1']
    options = created['options']
    assert options.binary_location == job['browser_executable']
    assert f'--user-data-dir={tmp_path / "profile"}' in options.arguments
    assert '--headless=new' in options.arguments and '--disable-extensions' in options.arguments
    assert '--remote-debugging-pipe' in options.arguments
    assert '--no-sandbox' not in options.arguments
    assert '--proxy-server=http://proxy.test:8080' in options.arguments
    assert options.experimental['prefs']['download_restrictions'] == 3
