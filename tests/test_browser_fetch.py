"""One try in a visible browser window for an address that refused the ordinary request.

The human's choice, off by default: per installation (settings) and per piece of work (start screen).
No browser is started here: the worker runs against a fake driver, and the engine against a fake opener.
"""
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import selenium_runner, selenium_worker as worker
from workbench.config import DEFAULT, validate_settings
from workbench.engine import AdmissionError
from workbench.harness import HarnessError, PathHarness
from workbench.pdfdocs import PdfLibrary
from workbench.webtools import WebToolError, WebTools
from pdf_fixture import make_pdf
from test_engine import configured, start
from test_web_phase9 import http_server, pin

REPORT = make_pdf(['World Economic Outlook', 'Executive summary. Growth is 3.2 percent.'], title='WEO (test)')
PAGE = '<html><head><title>World Economic Outlook Reports</title></head><body><h1>Reports</h1><a href="/files/weo.pdf">Full report</a></body></html>'


# --- the worker: what is done in the window ---------------------------------------------------------

class Window:
    """What the worker needs from a WebDriver. ``arrives`` writes a file into the download folder when the
    address is loaded; otherwise ``html`` stands in the window."""

    def __init__(self, downloads, *, arrives=None, html=PAGE, status=200, content_type='text/html', closes=False, never=False):
        self.downloads, self.arrives, self.html, self.status = downloads, arrives, html, status
        self.content_type, self.closes, self.never = content_type, closes, never
        self.calls, self.current_url, self.title = [], 'data:,', 'World Economic Outlook Reports'

    def set_page_load_timeout(self, value):
        self.calls.append(('load_timeout', value))

    def set_script_timeout(self, value):
        self.calls.append(('script_timeout', value))

    def implicitly_wait(self, value):
        self.calls.append(('implicit', value))

    def execute_cdp_cmd(self, name, args):
        self.calls.append((name, args))

    def get(self, url):
        self.calls.append(('get', url))
        if self.arrives:
            name, data = self.arrives
            (self.downloads / name).write_bytes(data)  # the window stays on its empty start page
        elif not self.never:
            self.current_url = url

    def execute_script(self, script):
        assert 'responseStatus' in script and 'click' not in script  # only reads how the page arrived
        if self.closes:
            raise RuntimeError('no such window')
        return [self.status, self.content_type, 'complete']

    @property
    def page_source(self):
        return self.html

    def quit(self):
        self.calls.append(('quit',))

    def __getattr__(self, name):  # click, send_keys, find_element, add_cookie ... must never be used
        raise AssertionError(f'the fetch worker must not call {name}')


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def fetch_job(**changes):
    return {'mode': 'fetch', 'url': 'https://www.imf.org/-/media/files/weo/text.pdf', 'wait_seconds': 30,
            'max_page_chars': 20000, 'max_download_bytes': 1024 * 1024,
            'browser_executable': 'C:\\edge\\msedge.exe', 'proxy_url': '', **changes}


def run_fetch(tmp_path, window_options, **job):
    clock = Clock()
    (tmp_path / 'downloads').mkdir(exist_ok=True)
    window = Window(tmp_path / 'downloads', **window_options)
    result = worker.run_fetch_job(fetch_job(**job), tmp_path, driver_factory=lambda *_: window, clock=clock, sleep=clock.sleep)
    return result, window, clock


def test_the_window_loads_the_address_once_saves_a_pdf_and_is_closed(tmp_path):
    result, window, _ = run_fetch(tmp_path, {'arrives': ('text.pdf', REPORT)})
    assert result['kind'] == 'download' and result['file'] == 'text.pdf' and result['bytes'] == len(REPORT)
    assert [call for call in window.calls if call[0] == 'get'] == [('get', 'https://www.imf.org/-/media/files/weo/text.pdf')]
    assert ('Browser.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': str(tmp_path / 'downloads')}) in window.calls
    assert window.calls[-1] == ('quit',)


def test_a_page_a_refusal_a_closed_window_and_nothing_at_all_are_told_apart(tmp_path):
    page, window, clock = run_fetch(tmp_path / 'a', {}, url='https://www.imf.org/en/Publications/WEO') if (tmp_path / 'a').mkdir() is None else None
    assert page['kind'] == 'page' and page['status'] == 200 and page['title'] == 'World Economic Outlook Reports'
    assert page['html'] == PAGE and page['url'] == 'https://www.imf.org/en/Publications/WEO' and clock.now >= 2
    assert window.calls[-1] == ('quit',)
    (tmp_path / 'b').mkdir()
    denied, window, _ = run_fetch(tmp_path / 'b', {'html': '<html><title>Access Denied</title></html>', 'status': 403})
    assert denied['kind'] == 'page' and denied['status'] == 403 and window.calls[-1] == ('quit',)
    (tmp_path / 'c').mkdir()
    closed, window, _ = run_fetch(tmp_path / 'c', {'closes': True})
    assert closed['kind'] == 'closed' and closed['html'] == '' and window.calls[-1] == ('quit',)
    (tmp_path / 'd').mkdir()
    nothing, window, clock = run_fetch(tmp_path / 'd', {'never': True}, wait_seconds=10)
    assert nothing['kind'] == 'timeout' and 10 <= clock.now <= 11 and window.calls[-1] == ('quit',)
    # A download that is still being written is waited for; one over the limit is given up.
    (tmp_path / 'e').mkdir()
    partial, _, clock = run_fetch(tmp_path / 'e', {'arrives': ('text.pdf.crdownload', b'%PDF-1.4 half')}, wait_seconds=5)
    assert partial['kind'] == 'timeout' and clock.now >= 5
    (tmp_path / 'f').mkdir()
    large, window, _ = run_fetch(tmp_path / 'f', {'arrives': ('big.pdf', b'%PDF' + b'0' * 5000)}, max_download_bytes=2048)
    assert large['kind'] == 'too_large' and large['bytes'] == 5004 and window.calls[-1] == ('quit',)
    for bad in ({'wait_seconds': 1}, {'wait_seconds': 3000}, {'url': 'file:///C:/secret'}, {'max_download_bytes': 5}):
        with pytest.raises(ValueError):
            worker.run_fetch_job(fetch_job(**bad), tmp_path, driver_factory=lambda *_: Window(tmp_path))


def test_the_window_is_an_ordinary_one_and_nothing_disguises_the_browser(tmp_path):
    class Options:
        def __init__(self):
            self.arguments, self.experimental, self.binary_location = [], {}, ''

        def add_argument(self, value):
            self.arguments.append(value)

        def add_experimental_option(self, name, value):
            self.experimental[name] = value

    options = worker._fetch_options(Options(), fetch_job(), tmp_path)
    text = ' '.join(options.arguments).lower()
    assert '--window-position=60,40' in text and f'--user-data-dir={tmp_path / "profile"}'.lower() in text
    for hidden in ('headless', 'user-agent', 'automationcontrolled', 'disable-blink-features', 'excludeswitches', '-2400'):
        assert hidden not in text and hidden not in json.dumps(options.experimental).lower()
    assert set(options.experimental) == {'prefs'}  # no "excludeSwitches", no "useAutomationExtension"
    prefs = options.experimental['prefs']
    assert prefs['download.default_directory'] == str(tmp_path / 'downloads') and prefs['plugins.always_open_pdf_externally'] is True
    assert prefs['download.prompt_for_download'] is False and prefs['credentials_enable_service'] is False


# --- the runner: why a window cannot be opened --------------------------------------------------------

def test_without_windows_or_without_a_browser_or_driver_the_reason_is_returned(tmp_path, monkeypatch):
    import threading
    harness = PathHarness([str(tmp_path)], [])
    arguments = ({}, {}, harness, 'https://www.imf.org/x.pdf', 60, '', 1500000, 1024 * 1024, threading.Event())
    if selenium_runner.os.name != 'nt':
        with pytest.raises(HarnessError, match='requires Windows'):
            selenium_runner._execute_fetch(*arguments)
    # On Windows the configured files are checked before anything is started.
    monkeypatch.setattr(selenium_runner.os, 'name', 'nt')
    started = []
    monkeypatch.setattr(selenium_runner, 'run_browser_job', lambda *args, **kwargs: started.append(args))
    for config, python_config in (({}, {}),                                                        # no python.exe
                                  ({'browser_executable': '', 'driver_executable': ''}, {'executable': str(tmp_path / 'python.exe')})):
        with pytest.raises(HarnessError):
            selenium_runner._execute_fetch(config, python_config, *arguments[2:])
    with pytest.raises(HarnessError, match='HTTP'):
        selenium_runner._execute_fetch({}, {}, harness, 'file:///C:/secret.pdf', 60, '', 1500000, 1024 * 1024, threading.Event())
    assert started == []


# --- web_fetch: when the window is opened, and what comes of it ---------------------------------------

def refusing(seen):
    async def handler(request):
        seen.append(request.path)
        if request.path == '/missing':
            return web.Response(status=404, text='not here')
        if request.path == '/open':
            return web.Response(text='<html><body>Public page</body></html>', content_type='text/html')
        return web.Response(status=403, text='<html>Access Denied</html>', content_type='text/html')
    return handler


def tools_with(tmp_path, answers):
    """WebTools whose browser opener answers from ``answers`` (url suffix -> result or exception) and counts its calls."""
    opened = []

    async def opener(url, max_download_bytes):
        opened.append(url)
        answer = next(value for key, value in answers.items() if url.endswith(key))
        if isinstance(answer, Exception):
            raise answer
        return {'kind': 'page', 'url': url, 'status': 200, 'content_type': 'text/html', 'title': '', 'html': '',
                'truncated': False, 'file': '', 'bytes': 0, 'data': None, **answer}

    tools = WebTools({'search': {'enabled': True, 'provider': 'duckduckgo'}})
    tools.use_pdf_library(PdfLibrary(tmp_path / 'pdf-cache'), 50 * 1024 * 1024)
    tools.use_browser_fetch(opener)
    return tools, opened


async def test_a_refused_pdf_and_page_come_from_one_try_each_in_the_window(tmp_path, monkeypatch):
    seen = []
    pin(monkeypatch)
    async with http_server(refusing(seen)) as port:
        base = f'http://www.reports.example:{port}'
        tools, opened = tools_with(tmp_path, {
            '/text.pdf': {'kind': 'download', 'file': 'text.pdf', 'bytes': len(REPORT), 'data': REPORT},
            '/WEO': {'title': 'World Economic Outlook Reports', 'html': PAGE}})
        report = await tools.execute('web_fetch', {'url': base + '/files/text.pdf'})
        assert report['pages'] == 2 and report['pdf_id'] in tools.pdf_ids and report['fetched_with'] == 'browser window'
        assert 'allowed one try in a visible browser window' in report['fetched_note']
        page = await tools.execute('web_fetch', {'url': base + '/en/Publications/WEO'})
        assert 'Reports' in page['text'] and page['fetched_with'] == 'browser window'
        assert page['pdf_links'] == [{'url': base + '/files/weo.pdf', 'text': 'Full report'}]
        assert opened == [base + '/files/text.pdf', base + '/en/Publications/WEO']
        assert [(row['outcome'], row['detail']) for row in tools.browser_log] == [('success', 'PDF saved, 2 pages'), ('success', 'page read')]
        # What the site answers itself needs no window; a missing page is not a refusal.
        assert 'fetched_with' not in await tools.execute('web_fetch', {'url': base + '/open'})
        with pytest.raises(WebToolError, match=r'HTTP 404 \(not found\)$'):
            await tools.execute('web_fetch', {'url': base + '/missing'})
        assert len(opened) == 2


async def test_a_refusal_or_a_check_in_the_window_is_final_and_the_human_is_asked(tmp_path, monkeypatch):
    seen = []
    pin(monkeypatch)
    async with http_server(refusing(seen)) as port:
        base = f'http://www.closed.example:{port}'
        tools, opened = tools_with(tmp_path, {'/denied.pdf': {'status': 403, 'title': 'Access Denied', 'html': '<html>Access Denied</html>'},
                                              '/other.pdf': {'kind': 'download', 'data': REPORT}})
        with pytest.raises(WebToolError) as caught:
            await tools.execute('web_fetch', {'url': base + '/denied.pdf'})
        text = str(caught.value)
        assert 'HTTP 403 (access refused)' in text and 'A browser window tried once and was also turned away: refused (HTTP 403)' in text
        assert 'does not solve such checks or disguise the browser' in text and 'Ask the human with ask_user' in text
        # The same address again, and another address of the site that turned the window away: no window.
        with pytest.raises(WebToolError, match='already tried this address once in this work'):
            await tools.execute('web_fetch', {'url': base + '/denied.pdf'})
        with pytest.raises(WebToolError, match='also refused the browser window earlier in this work'):
            await tools.execute('web_fetch', {'url': base + '/other.pdf'})
        assert opened == [base + '/denied.pdf'] and tools.browser_log[0]['outcome'] == 'refused'
        # A check meant for a person arrives with status 200: it is recognised and not waited on.
        check = f'http://www.check.example:{port}'
        tools, opened = tools_with(tmp_path, {'/doc.pdf': {'title': 'Just a moment...', 'html': '<html>Verify you are human</html>'},
                                              '/gone.pdf': {'kind': 'closed'}, '/slow.pdf': {'kind': 'timeout'},
                                              '/big.pdf': {'kind': 'too_large', 'bytes': 80 * 1024 * 1024},
                                              '/shown.pdf': {'content_type': 'application/pdf', 'html': '<html><embed></html>'}})
        with pytest.raises(WebToolError, match='the site showed a check meant for a person'):
            await tools.execute('web_fetch', {'url': check + '/doc.pdf'})
        other = f'http://files.example:{port}'
        for path, problem in (('/gone.pdf', 'the window was closed before anything arrived'), ('/slow.pdf', 'nothing arrived in time'),
                              ('/big.pdf', r'larger than the limit in the settings \(80\.0 MB; limit 50\.0 MB\)'),
                              ('/shown.pdf', 'showed the PDF but did not save it')):
            with pytest.raises(WebToolError, match=problem):
                await tools.execute('web_fetch', {'url': other + path})
        assert len(opened) == 5 and not (tmp_path / 'pdf-cache').exists()
        # The most one piece of work may open.
        with pytest.raises(WebToolError, match='opened 5 times in this work'):
            await tools.execute('web_fetch', {'url': other + '/sixth.pdf'})
        assert len(opened) == 5
        # A saved file that is not a PDF is not kept.
        tools, opened = tools_with(tmp_path, {'/zip.pdf': {'kind': 'download', 'data': b'PK\x03\x04'}})
        with pytest.raises(WebToolError, match='is not a PDF; nothing was kept'):
            await tools.execute('web_fetch', {'url': other + '/zip.pdf'})
        assert not (tmp_path / 'pdf-cache').exists()


async def test_a_window_that_cannot_be_opened_says_why_once_and_is_not_tried_again(tmp_path, monkeypatch):
    seen = []
    pin(monkeypatch)
    async with http_server(refusing(seen)) as port:
        base = f'http://www.reports.example:{port}'
        tools, opened = tools_with(tmp_path, {'.pdf': ValueError('Select existing browser and driver .exe files')})
        with pytest.raises(WebToolError) as caught:
            await tools.execute('web_fetch', {'url': base + '/a.pdf'})
        assert 'could not be opened: Select existing browser and driver .exe files' in str(caught.value)
        with pytest.raises(WebToolError, match=r'cannot be opened here \(Select existing browser and driver'):
            await tools.execute('web_fetch', {'url': base + '/b.pdf'})
        assert opened == [base + '/a.pdf'] and tools.browser_log[0]['outcome'] == 'failed'
        # Without the human's choice nothing is opened: the refusal is the answer.
        plain = WebTools({'search': {'enabled': True, 'provider': 'duckduckgo'}})
        with pytest.raises(WebToolError, match=r'HTTP 403 \(access refused\)$'):
            await plain.execute('web_fetch', {'url': base + '/a.pdf'})
        assert plain.browser_log == []


# --- the engine: chosen per installation and per piece of work, off unless chosen ----------------------

async def test_the_window_is_off_unless_the_human_chose_it_for_the_setting_or_the_work(tmp_path, monkeypatch):
    import workbench.engine as engine_module
    started = []

    async def execute_fetch(*args, **kwargs):
        started.append(args[3])
        return {'kind': 'download', 'url': args[3], 'status': 0, 'content_type': '', 'title': '', 'html': '',
                'truncated': False, 'file': 'text.pdf', 'bytes': len(REPORT), 'data': REPORT}

    monkeypatch.setattr(engine_module, 'execute_fetch', execute_fetch)
    seen = []
    pin(monkeypatch)
    assert DEFAULT['search']['browser_fetch'] is False
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    engine.kick = lambda agent: None
    try:
        async with http_server(refusing(seen)) as port:
            url = f'http://www.imf.example:{port}/files/text.pdf'
            # Off (the default): the refusal is reported and no browser is started.
            run, pm = await start(engine, max_workers=0)
            assert run['browser_fetch'] is False and 'one try in a visible browser window' not in engine._policy(run, pm)
            with pytest.raises(ValueError, match=r'HTTP 403 \(access refused\)$'):
                await engine.execute_tool(run, pm, 'web_fetch', {'url': url})
            assert started == [] and not [row for row in engine.events if row['kind'] == 'browser_fetch']
            # Chosen for one piece of work on the start screen, with the setting still off.
            run, pm = await start(engine, max_workers=0, browser_fetch=True)
            assert run['browser_fetch'] is True and 'the human allowed one try in a visible browser window' in engine._policy(run, pm)
            result = await engine.execute_tool(run, pm, 'web_fetch', {'url': url})
            assert result['pages'] == 2 and result['fetched_with'] == 'browser window' and started == [url]
            events = [row['text'] for row in engine.events if row['kind'] == 'browser_fetch' and row['run_id'] == run['id']]
            assert len(events) == 1 and 'ブラウザで試行 → 成功（PDF saved, 2 pages）' in events[0] and 'text.pdf' in events[0]
            assert any('ブラウザで試行 → 成功' in row['text'] for row in pm.logs if row['kind'] == 'notice')
            saved = engine.history.load(run['id']) if hasattr(engine.history, 'load') else None
            # The setting on, and one piece of work turned off at start.
            engine.settings.value['search']['browser_fetch'] = True
            run, pm = await start(engine, max_workers=0, browser_fetch=False)
            assert run['browser_fetch'] is False
            with pytest.raises(ValueError, match=r'HTTP 403'):
                await engine.execute_tool(run, pm, 'web_fetch', {'url': url})
            run, pm = await start(engine, max_workers=0)
            assert run['browser_fetch'] is True and len(started) == 1
            with pytest.raises(AdmissionError):
                await start(engine, max_workers=0, browser_fetch='yes')
    finally:
        await engine.close()


async def test_a_refusal_in_the_window_is_recorded_for_the_human(tmp_path, monkeypatch):
    import workbench.engine as engine_module

    async def execute_fetch(*args, **kwargs):
        raise HarnessError('Select existing browser and driver .exe files')

    monkeypatch.setattr(engine_module, 'execute_fetch', execute_fetch)
    seen = []
    pin(monkeypatch)
    engine, work = configured(tmp_path, None)
    engine.settings.value['search'].update(enabled=True, browser_fetch=True)
    engine.kick = lambda agent: None
    try:
        async with http_server(refusing(seen)) as port:
            run, pm = await start(engine, max_workers=0)
            with pytest.raises(ValueError, match='could not be opened: Select existing browser and driver'):
                await engine.execute_tool(run, pm, 'web_fetch', {'url': f'http://www.imf.example:{port}/files/text.pdf'})
            events = [row['text'] for row in engine.events if row['kind'] == 'browser_fetch']
            assert len(events) == 1 and 'ブラウザで試行 → 失敗（the browser could not be opened' in events[0]
    finally:
        await engine.close()


def test_the_setting_is_off_by_default_and_must_be_true_or_false():
    raw = json.loads(json.dumps(DEFAULT))
    del raw['search']['browser_fetch']  # settings saved before this version
    assert validate_settings(raw, check_paths=False)['search']['browser_fetch'] is False
    raw['search']['browser_fetch'] = True
    assert validate_settings(raw, check_paths=False)['search']['browser_fetch'] is True
    raw['search']['browser_fetch'] = 'on'
    with pytest.raises(ValueError):
        validate_settings(raw, check_paths=False)
    page = (Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8')
    assert 'id="browserFetchAllow" type="checkbox"' in page and 'この作業でブラウザ操作を許可' in page
    assert 'id="browserFetchAllow" type="checkbox" checked' not in page
