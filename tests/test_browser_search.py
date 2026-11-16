"""Keyless browser search, the shared search queue and cache, and the human check.

No browser and no search service is contacted: pages come from fixtures, and
the browser itself is replaced by a function that returns prepared HTML.
"""
import asyncio
import base64
import json
import time

import pytest

from workbench import browser_search, webtools
from workbench.browser_search import (BrowserSearch, SearchCache, SearchChallenge, bing_target, query_key, read_bing,
                                      read_duckduckgo)
from workbench.config import DEFAULT, validate_settings
from workbench.webtools import WebToolError, WebTools
from test_engine import configured, start


def wrapped(url):
    return 'https://www.bing.com/ck/a?!&&p=abc&u=a1' + base64.urlsafe_b64encode(url.encode()).decode().rstrip('=') + '&ntb=1'


BING = f'''<html><body><ol id="b_results">
<li class="b_algo"><div class="b_tpcn"><a class="tilk" href="{wrapped('https://www.meti.go.jp/policy/ai.html')}">
<div class="tptt">経済産業省</div><cite>https://www.meti.go.jp</cite></a></div>
<h2><a href="{wrapped('https://www.meti.go.jp/policy/ai.html').replace('&', '&amp;')}">AI事業者<strong>ガイドライン</strong> | 経済産業省</a></h2>
<div class="b_caption"><p class="b_lineclamp2"><span>2024年4月19日</span> · 生成AIの<strong>ガイドライン</strong>を<br/>取りまとめました。</p></div></li>
<li class="b_algo"><h2><a href="https://example.org/direct">Direct link</a></h2><div class="b_caption"><p>Plain snippet</p></div></li>
<li class="b_ad"><h2><a href="https://ads.example/x">Sponsored</a></h2></li>
<li class="b_algo"><h2><a href="https://www.bing.com/images/search?q=x">Images for x</a></h2></li>
<script>var x = "<li class='b_algo'><h2><a href='https://script.example/'>not a result</a></h2></li>";</script>
</ol></body></html>'''
BING_EMPTY = '<html><body><ol id="b_results"><li class="b_no"><h1>結果はありません</h1></li></ol></body></html>'
BING_CHECK = '<html><body><div id="b_captcha"><iframe src="https://challenges.cloudflare.com/turnstile"></iframe></div></body></html>'
DDG = ('<div class="result results_links web-result"><h2 class="result__title">'
       '<a class="result__a" href="https://example.com/article">Found</a></h2>'
       '<div><a class="result__snippet">Excerpt</a></div></div>')
DDG_CHECK = '<form id="challenge-form" action="//duckduckgo.com/anomaly.js" method="POST"></form>'


@pytest.fixture(autouse=True)
def fresh_engine_guards():
    """Each test starts with no engine paused and no waiting between requests."""
    guards = browser_search.engine_guards()
    for guard in guards.values():
        guard.reset()
        guard.min_interval = 0.0
    yield guards
    guards['bing'].reset()
    guards['bing'].min_interval = browser_search.ENGINES[0]['interval']


def pages(script):
    """A stand-in browser: {engine host: [html, ...]}; records every (url, ready, visible, wait)."""
    calls = []

    async def page(url, ready, visible, wait_seconds):
        calls.append((url, ready, visible, wait_seconds))
        host = 'bing' if 'bing.com' in url else 'duckduckgo'
        queue = script[host]
        html = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(html, Exception):
            raise html
        return {'url': url, 'title': 't', 'html': html, 'ready': True, 'closed': False, 'truncated': False}
    return page, calls


# --- reading result pages ----------------------------------------------------------------

def test_bing_results_are_read_from_the_page_and_wrapped_links_are_decoded():
    state, rows = read_bing(BING, 5)
    assert state == 'results'
    assert rows == [
        {'title': 'AI事業者ガイドライン | 経済産業省', 'url': 'https://www.meti.go.jp/policy/ai.html',
         'snippet': '2024年4月19日 · 生成AIのガイドラインを取りまとめました。'},
        {'title': 'Direct link', 'url': 'https://example.org/direct', 'snippet': 'Plain snippet'}]
    assert read_bing(BING, 1)[1] == rows[:1]
    assert read_bing(BING_EMPTY, 5) == ('empty', [])
    assert read_bing(BING_CHECK, 5) == ('challenge', [])
    assert read_bing('<html><body><p>Something else entirely</p></body></html>', 5) == ('unknown', [])
    assert bing_target(wrapped('https://example.com/a?b=1')) == 'https://example.com/a?b=1'
    for bad in ('https://www.bing.com/ck/a?u=zz', 'https://www.bing.com/search?q=x', 'javascript:alert(1)', None,
                wrapped('javascript:alert(1)'), wrapped('https://www.bing.com/ck/a?u=a1x')):
        assert bing_target(bad) == ''


def test_duckduckgo_pages_use_the_existing_reader():
    assert read_duckduckgo(DDG, 5) == ('results', [{'title': 'Found', 'url': 'https://example.com/article', 'snippet': 'Excerpt'}])
    assert read_duckduckgo(DDG_CHECK, 5) == ('challenge', [])
    assert read_duckduckgo('<html><body>nothing recognisable</body></html>', 5)[0] == 'unknown'


# --- engines in order, each with its own pause -------------------------------------------

def test_the_first_engine_answers_and_the_model_gets_the_usual_shape():
    async def run():
        page, calls = pages({'bing': [BING], 'duckduckgo': [DDG]})
        result = await BrowserSearch(page).search('生成AI ガイドライン', 5)
        assert result['engine'] == 'bing' and result['untrusted'] is True and result['query'] == '生成AI ガイドライン'
        assert [row['url'] for row in result['results']] == ['https://www.meti.go.jp/policy/ai.html', 'https://example.org/direct']
        assert len(calls) == 1
        url, ready, visible, wait = calls[0]
        assert url == 'https://www.bing.com/search?q=%E7%94%9F%E6%88%90AI+%E3%82%AC%E3%82%A4%E3%83%89%E3%83%A9%E3%82%A4%E3%83%B3'
        assert visible is False and wait == 8 and 'b_algo' in ready
    asyncio.run(run())


def test_a_bot_check_pauses_only_that_engine_and_the_next_one_is_used(fresh_engine_guards):
    async def run():
        page, calls = pages({'bing': [BING_CHECK], 'duckduckgo': [DDG]})
        search = BrowserSearch(page)
        first = await search.search('q one', 3)
        assert first['engine'] == 'duckduckgo' and first['results'][0]['url'] == 'https://example.com/article'
        assert fresh_engine_guards['bing'].status()['blocked'] and not fresh_engine_guards['duckduckgo'].status()['blocked']
        second = await search.search('q two', 3)
        assert second['engine'] == 'duckduckgo'
        # Bing was asked once; while it is paused the second search goes straight to DuckDuckGo.
        assert ['bing' if 'bing.com' in call[0] else 'ddg' for call in calls] == ['bing', 'ddg', 'ddg']
    asyncio.run(run())


def test_when_every_engine_asks_for_a_check_a_person_is_needed(fresh_engine_guards):
    async def run():
        page, calls = pages({'bing': [BING_CHECK, BING], 'duckduckgo': [DDG_CHECK]})
        search = BrowserSearch(page)
        with pytest.raises(SearchChallenge) as challenge:
            await search.search('q', 5)
        assert challenge.value.engines == ['bing', 'duckduckgo'] and 'human check' in str(challenge.value)
        assert all(guard.status()['blocked'] for guard in fresh_engine_guards.values())
        with pytest.raises(SearchChallenge):  # both paused: nothing more is sent
            await search.search('other', 5)
        assert len(calls) == 2
        # A person passes the check in a visible window; the engine is usable again.
        result = await search.human_check('q', 5, challenge.value.engines)
        assert calls[-1][2] is True and calls[-1][3] == browser_search.HUMAN_CHECK_SECONDS and 'bing.com' in calls[-1][0]
        assert result['engine'] == 'bing' and len(result['results']) == 2
        assert not fresh_engine_guards['bing'].status()['blocked']
    asyncio.run(run())


def test_an_unfinished_human_check_and_an_unreadable_page_are_errors_not_empty_results():
    async def run():
        page, _ = pages({'bing': [BING_CHECK], 'duckduckgo': [DDG_CHECK]})
        with pytest.raises(ValueError, match='was not completed'):
            await BrowserSearch(page).human_check('q', 5, ['bing'])
        page, _ = pages({'bing': ['<html>layout changed</html>'], 'duckduckgo': [ValueError('The browser could not open the search page: x')]})
        with pytest.raises(ValueError, match='Browser search failed: Bing: the result page was not recognised') as failure:
            await BrowserSearch(page).search('q', 5)
        assert not isinstance(failure.value, SearchChallenge) and 'DuckDuckGo: The browser could not open' in str(failure.value)
        page, _ = pages({'bing': [BING_EMPTY], 'duckduckgo': [DDG]})
        assert (await BrowserSearch(page).search('zzzz', 5))['results'] == []  # a real "no results" is an answer
    asyncio.run(run())


# --- one queue, one cache, one hourly allowance -------------------------------------------

def test_rewordings_of_a_query_share_one_key():
    assert query_key('生成AI ガイドライン') == query_key('ガイドライン　生成ＡＩ') == query_key('生成ai、ガイドライン!')
    assert query_key('a b') != query_key('a c') and query_key('  ') == ''


def test_the_cache_outlives_a_run_expires_and_never_lists_the_queries(tmp_path):
    path = tmp_path / 'search-cache.json'
    cache = SearchCache(path)
    rows = [{'title': f'T{index}', 'url': f'https://example.com/{index}', 'snippet': 's'} for index in range(3)]
    cache.put('World Bank 人口 ドイツ', 5, {'query': 'x', 'results': rows, 'engine': 'bing', 'untrusted': True})
    hit = SearchCache(path).get('ドイツ world bank 人口', 2)  # another run, reworded, fewer rows wanted
    assert hit['results'] == rows[:2] and hit['cached'] is True and hit['engine'] == 'bing' and hit['query'] == 'ドイツ world bank 人口'
    assert SearchCache(path).get('World Bank 人口 ドイツ', 10)['results'] == rows  # the engine had no more than three
    cache.put('full page', 3, {'results': rows})
    assert cache.get('full page', 3) and cache.get('full page', 5) is None  # more could exist: ask again
    assert 'World Bank' not in path.read_text(encoding='utf-8') and 'ドイツ' not in path.read_text(encoding='utf-8')
    assert SearchCache(path, seconds=0).get('World Bank 人口 ドイツ', 2) is None
    path.write_text('not json', encoding='utf-8')
    assert SearchCache(path).entries == {}  # a damaged file is an empty cache, not an error


def test_the_hourly_allowance_counts_requests_across_runs_and_says_when_it_ends(tmp_path):
    path = tmp_path / 'search-cache.json'
    cache = SearchCache(path, hourly=3)
    for _ in range(3):
        cache.spend()
    with pytest.raises(browser_search.SearchBudgetExceeded, match='3 searches in the last hour'):
        cache.spend()
    again = SearchCache(path, hourly=3)  # restarting the application does not reset it
    assert again.recent() == 3
    again.requests = [time.time() - 3700] * 3  # an hour later
    again.spend()


def test_a_run_sends_each_question_once_whatever_the_wording_or_the_worker(tmp_path):
    async def run():
        page, calls = pages({'bing': [BING], 'duckduckgo': [DDG]})
        cache = SearchCache(tmp_path / 'search-cache.json')
        tools = WebTools({'search': {'enabled': True, 'provider': 'browser'}})
        tools.use_browser(page)
        tools.use_search_cache(cache)
        assert tools.endpoint == 'https://www.bing.com/search'
        answers = await asyncio.gather(*(tools.execute('web_search', {'query': query, 'limit': 2})
                                         for query in ('生成AI ガイドライン', 'ガイドライン 生成AI', '生成AI ガイドライン')))
        assert len(calls) == 1 and cache.recent() == 1
        assert all(answer['results'] == answers[0]['results'] for answer in answers)
        # Another run of the application reuses it from disk.
        later = WebTools({'search': {'enabled': True, 'provider': 'browser'}})
        later.use_browser(page)
        later.use_search_cache(SearchCache(tmp_path / 'search-cache.json'))
        assert (await later.execute('web_search', {'query': '生成AI　ガイドライン', 'limit': 2}))['cached'] is True and len(calls) == 1
        # The whole result page was kept, so asking for more rows needs no new search either.
        assert (await later.execute('web_search', {'query': '生成AI ガイドライン', 'limit': 5}))['cached'] is True and len(calls) == 1
        # Without a browser the method says so instead of pretending to search.
        bare = WebTools({'search': {'enabled': True, 'provider': 'browser'}})
        with pytest.raises(WebToolError, match='Browser search is not available'):
            await bare.execute('web_search', {'query': 'x'})
    asyncio.run(run())


def test_the_allowance_stops_new_searches_with_a_clear_message(tmp_path):
    async def run():
        page, calls = pages({'bing': [BING], 'duckduckgo': [DDG]})
        tools = WebTools({'search': {'enabled': True, 'provider': 'browser'}})
        tools.use_browser(page)
        tools.use_search_cache(SearchCache(tmp_path / 'search-cache.json', hourly=1))
        await tools.execute('web_search', {'query': 'first'})
        with pytest.raises(WebToolError, match='New searches are possible in about'):
            await tools.execute('web_search', {'query': 'second'})
        assert (await tools.execute('web_search', {'query': 'first'}))['results'] and len(calls) == 1  # held answers stay free
    asyncio.run(run())


# --- settings ------------------------------------------------------------------------------

def test_browser_search_needs_the_browser_driver_and_python_but_not_selenium_itself(tmp_path):
    for name in ('python.exe', 'msedge.exe', 'msedgedriver.exe'):
        (tmp_path / name).write_bytes(b'')
    raw = json.loads(json.dumps(DEFAULT))
    raw['search'].update(provider='browser', enabled=True, endpoint='https://ignored.example/')
    with pytest.raises(ValueError, match='ブラウザ検索には'):
        validate_settings(raw)
    raw['search']['enabled'] = False
    assert validate_settings(raw)['search']['endpoint'] == 'https://www.bing.com/search'  # choosing it does not switch search on
    raw['search']['enabled'] = True
    raw['python']['executable'] = str(tmp_path / 'python.exe')
    raw['selenium'].update(browser_executable=str(tmp_path / 'msedge.exe'), driver_executable=str(tmp_path / 'msedgedriver.exe'))
    ready = validate_settings(raw)
    assert ready['search']['provider'] == 'browser' and ready['search']['endpoint'] == 'https://www.bing.com/search'
    assert ready['selenium']['enabled'] is False and ready['python']['network_enabled'] is False


# --- the human check, through the engine ---------------------------------------------------

def browser_run(engine, script):
    """Give a started run a stand-in browser (the real one needs Windows)."""
    page, calls = pages(script)
    engine.settings.value['search'].update(enabled=True, provider='browser')

    def attach(run):
        run['_web'].use_browser(page)
        return calls
    return attach


@pytest.mark.asyncio
async def test_the_human_is_asked_once_to_pass_the_check_and_the_search_then_completes(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    attach = browser_run(engine, {'bing': [BING_CHECK, BING], 'duckduckgo': [DDG_CHECK]})
    try:
        run, pm = await start(engine, task='生成AI規制を調べて', max_workers=0)
        calls = attach(run)
        assert 'Search sparingly' in engine._policy(run, pm)
        search = asyncio.ensure_future(engine.execute_tool(run, pm, 'web_search', {'query': '生成AI 規制', 'limit': 2}))
        for _ in range(200):
            await asyncio.sleep(.01)
            if pm.approval:
                break
        assert pm.approval and pm.approval['tool'] == 'search_human_check'
        assert '人による確認' in pm.approval['summary'] and '生成AI 規制' in pm.approval['summary'] and '自動では解きません' in pm.approval['summary']
        assert not any(call[2] for call in calls), 'no window is shown before the human agrees'
        engine.resolve_approval(pm.id, {'approval_id': pm.approval['id'], 'decision': 'approve'})
        result = await search
        assert result['engine'] == 'bing' and len(result['results']) == 2
        assert calls[-1][2] is True  # the visible window
        assert 'https://www.meti.go.jp/policy/ai.html' in run['_known_urls']
        # The same question again is answered from what is held; nobody is asked twice.
        again = await engine.execute_tool(run, pm, 'web_search', {'query': '規制 生成AI', 'limit': 2})
        assert again['results'] == result['results'] and pm.approval is None
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_human_who_declines_is_not_asked_again_and_the_model_is_told_plainly(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    attach = browser_run(engine, {'bing': [BING_CHECK], 'duckduckgo': [DDG_CHECK]})
    try:
        run, pm = await start(engine, task='調べて', max_workers=0)
        calls = attach(run)
        search = asyncio.ensure_future(engine.execute_tool(run, pm, 'web_search', {'query': 'x'}))
        for _ in range(200):
            await asyncio.sleep(.01)
            if pm.approval:
                break
        engine.resolve_approval(pm.id, {'approval_id': pm.approval['id'], 'decision': 'reject'})
        with pytest.raises(ValueError, match='Web 検索は使えません'):
            await search
        with pytest.raises(ValueError, match='Web 検索は使えません'):
            await engine.execute_tool(run, pm, 'web_search', {'query': 'y'})
        assert pm.approval is None and not any(call[2] for call in calls)
    finally:
        await engine.close()


# --- the browser worker: one page, nothing clicked or typed ----------------------------------

class FakeBrowser:
    """What the worker needs from a WebDriver; the page appears after ``appears_after`` polls."""

    def __init__(self, html='<html><li class="b_algo"></li></html>', appears_after=0, closes=False):
        self.html, self.appears_after, self.closes = html, appears_after, closes
        self.calls, self.polls, self.current_url, self.title = [], 0, 'about:blank', 'T'

    def set_page_load_timeout(self, value):
        self.calls.append(('load_timeout', value))

    def set_script_timeout(self, value):
        self.calls.append(('script_timeout', value))

    def implicitly_wait(self, value):
        self.calls.append(('implicit', value))

    def execute_cdp_cmd(self, name, args):
        self.calls.append((name, args))

    def minimize_window(self):
        self.calls.append(('minimize',))

    def get(self, url):
        self.calls.append(('get', url))
        self.current_url = url

    def find_elements(self, by, selector):
        self.polls += 1
        if self.closes:
            raise RuntimeError('no such window')
        return ['row'] if self.polls > self.appears_after else []

    @property
    def page_source(self):
        return self.html

    def quit(self):
        self.calls.append(('quit',))

    def __getattr__(self, name):  # click, send_keys, execute_script ... must never be used
        raise AssertionError(f'the search worker must not call {name}')


def page_job(**changes):
    return {'mode': 'page', 'url': 'https://www.bing.com/search?q=x', 'ready_selector': '#b_results li.b_algo',
            'visible': False, 'wait_seconds': 2, 'max_page_chars': 20000, 'profile_dir': 'C:\\state\\browser-search-profile',
            'browser_executable': 'C:\\edge\\msedge.exe', 'proxy_url': '', **changes}


def test_the_worker_opens_one_page_waits_for_results_and_returns_its_html(tmp_path, monkeypatch):
    from workbench import selenium_worker as worker
    monkeypatch.setattr(worker.time, 'sleep', lambda _: None)
    browser = FakeBrowser(html='<html>\0<li class="b_algo">' + 'x' * 30000 + '</li></html>', appears_after=3)
    page = worker.run_page_job(page_job(), tmp_path, driver_factory=lambda *_: browser)
    assert set(page) == {'url', 'title', 'html', 'ready', 'closed', 'truncated'}
    assert page['ready'] is True and page['closed'] is False and page['truncated'] is True
    assert len(page['html']) == 20000 and '\0' not in page['html'] and page['url'] == 'https://www.bing.com/search?q=x'
    names = [call[0] for call in browser.calls]
    assert names.index('Browser.setDownloadBehavior') < names.index('get') and names[-1] == 'quit' and 'minimize' in names
    assert browser.polls == 4
    json.dumps(page)  # what the worker writes for the host


def test_a_visible_check_waits_for_the_person_and_reports_a_closed_window(tmp_path, monkeypatch):
    from workbench import selenium_worker as worker
    monkeypatch.setattr(worker.time, 'sleep', lambda _: None)
    waiting = FakeBrowser(appears_after=40)
    page = worker.run_page_job(page_job(visible=True, wait_seconds=300), tmp_path, driver_factory=lambda *_: waiting)
    assert page['ready'] is True and waiting.polls == 41 and ('minimize',) not in waiting.calls
    closed = FakeBrowser(closes=True)
    page = worker.run_page_job(page_job(visible=True, wait_seconds=300), tmp_path, driver_factory=lambda *_: closed)
    assert page == {'url': 'https://www.bing.com/search?q=x', 'title': '', 'html': '', 'ready': False, 'closed': True, 'truncated': False}
    assert closed.calls[-1] == ('quit',)
    for bad in ({'url': 'file:///C:/x'}, {'wait_seconds': 0}, {'wait_seconds': 601}, {'visible': 'yes'}, {'max_page_chars': 5}):
        with pytest.raises(ValueError):
            worker.run_page_job(page_job(**bad), tmp_path, driver_factory=lambda *_: FakeBrowser())


def test_the_search_window_uses_the_applications_own_profile_and_is_not_headless():
    from workbench import selenium_worker as worker

    class Options:
        def __init__(self):
            self.arguments, self.prefs, self.binary_location = [], None, None

        def add_argument(self, value):
            self.arguments.append(value)

        def add_experimental_option(self, name, value):
            self.prefs = (name, value)

    hidden = worker._page_options(Options(), page_job(), None)
    assert '--user-data-dir=C:\\state\\browser-search-profile' in hidden.arguments
    assert not any('headless' in value for value in hidden.arguments)
    assert '--window-position=-2400,-2400' in hidden.arguments and '--no-proxy-server' in hidden.arguments
    assert hidden.binary_location == 'C:\\edge\\msedge.exe' and hidden.prefs[1]['download_restrictions'] == 3
    # Nothing here hides that the browser is automated; a bot check is passed by a person.
    assert not any('AutomationControlled' in value for value in hidden.arguments) and hidden.prefs[0] == 'prefs'
    shown = worker._page_options(Options(), page_job(visible=True, proxy_url='http://proxy.example:8080'), None)
    assert '--window-position=60,40' in shown.arguments and '--proxy-server=http://proxy.example:8080' in shown.arguments


def test_the_page_runner_needs_windows_and_validates_before_starting_anything(tmp_path, monkeypatch):
    import threading
    import types
    from workbench import selenium_runner as runner
    from workbench.harness import HarnessError, PathHarness
    monkeypatch.setattr(runner, 'os', types.SimpleNamespace(name='posix'))  # the same on every platform
    harness = PathHarness([str(tmp_path)], [])
    arguments = ({}, {}, harness, 'https://www.bing.com/search?q=x', '#b_results', False, 8, str(tmp_path / 'profile'), '', 100000,
                 threading.Event())
    with pytest.raises(HarnessError, match='requires Windows'):
        runner._execute_page(*arguments)
    assert not (tmp_path / 'profile').exists()


def test_the_page_runner_writes_a_fixed_job_and_returns_only_a_valid_page(tmp_path, monkeypatch):
    """The Windows Job is replaced; everything around it (job file, result checks, clean-up) is real."""
    import types
    from pathlib import Path
    from workbench import selenium_runner as runner
    from workbench import selenium_worker as worker
    from workbench.harness import HarnessError, PathHarness
    monkeypatch.setattr(runner, 'os', types.SimpleNamespace(name='nt'))
    monkeypatch.setattr(runner, '_runtime', lambda *_: (Path('python.exe'), [Path('libs')], Path('msedge.exe'), Path('msedgedriver.exe')))
    harness, profile, seen = PathHarness([str(tmp_path)], []), tmp_path / 'state' / 'browser-search-profile', []

    def native(result):
        def run(command, workspace, **limits):
            job = json.loads((workspace / 'job.json').read_text(encoding='utf-8'))
            seen.append((job, limits, workspace))
            assert command[7:] == [str(workspace / 'worker.py'), str(workspace / 'job.json')]
            assert (workspace / 'worker.py').read_bytes() == Path(worker.__file__).read_bytes()
            if isinstance(result, dict) and 'html' in result:
                (workspace / 'result.json').write_text(json.dumps(result), encoding='utf-8')
                return {'exit_code': 0, 'termination_reason': None, 'stdout': '', 'stderr': ''}
            return result
        return run

    good = {'url': 'https://www.bing.com/search?q=x', 'title': 'x - 検索', 'html': BING, 'ready': True, 'closed': False, 'truncated': False}
    monkeypatch.setattr(runner, 'run_browser_job', native(good))
    config = {'browser': 'edge', 'max_memory_mb': 1024, 'enabled': False}
    page = asyncio.run(runner.execute_page(config, {'network_enabled': False}, harness, 'https://www.bing.com/search?q=x',
                                           '#b_results li.b_algo', visible=True, wait_seconds=300, profile_dir=str(profile),
                                           proxy_url='http://proxy.example:8080'))
    assert page == good and read_bing(page['html'], 5)[0] == 'results'
    job, limits, workspace = seen[0]
    assert job == {'mode': 'page', 'browser': 'edge', 'browser_executable': 'msedge.exe', 'driver_executable': 'msedgedriver.exe',
                   'library_paths': ['libs'], 'proxy_url': 'http://proxy.example:8080', 'url': 'https://www.bing.com/search?q=x',
                   'ready_selector': '#b_results li.b_algo', 'visible': True, 'wait_seconds': 300, 'profile_dir': str(profile),
                   'max_page_chars': 1500000}
    assert limits['timeout'] == 360 and limits['memory_mb'] == 1024
    assert profile.is_dir() and not workspace.exists()  # the profile stays; the private job folder is removed
    # Selenium itself being off, and Python's network permission being off, do not matter here.
    for bad in ({'exit_code': 1, 'termination_reason': None, 'stdout': '', 'stderr': 'Selenium WebDriverException: no driver\\n'},
                {'exit_code': None, 'termination_reason': 'timeout', 'stdout': '', 'stderr': ''}):
        monkeypatch.setattr(runner, 'run_browser_job', native(bad))
        with pytest.raises(HarnessError, match='could not open the search page'):
            asyncio.run(runner.execute_page(config, {}, harness, 'https://www.bing.com/search?q=x', '#b', profile_dir=str(profile)))
    monkeypatch.setattr(runner, 'run_browser_job', native({**good, 'html': 5}))
    with pytest.raises(HarnessError, match='invalid page result'):
        asyncio.run(runner.execute_page(config, {}, harness, 'https://www.bing.com/search?q=x', '#b', profile_dir=str(profile)))
    with pytest.raises(HarnessError):
        asyncio.run(runner.execute_page(config, {}, harness, 'file:///C:/x', '#b', profile_dir=str(profile)))
