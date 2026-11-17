"""A site that refuses the ordinary request is asked again with a browser's handshake (curl_cffi).

No external site is contacted. The local server cannot see a TLS handshake, so it tells the two requests
apart by what else differs: the ordinary request sends this application's fixed Chrome headers, the
browser-like one sends the headers of the browser it imitates.
"""
import json
import sys
import time
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import browserfetch
from workbench.config import DEFAULT, validate_settings
from workbench.pdfdocs import PdfLibrary
from workbench.webtools import BROWSER_USER_AGENT, WebToolError, WebTools
from pdf_fixture import make_pdf
from test_engine import configured, start
from test_web_phase9 import http_server, pin

pytestmark = pytest.mark.skipif(not browserfetch.available(), reason='curl_cffi is not installed')
REPORT = make_pdf(['World Economic Outlook', 'Executive summary. Growth is 3.2 percent.'], title='WEO (test)')


def tools_for(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(WebTools, '_TLS_SCHEMES', frozenset({'http', 'https'}))
    monkeypatch.setattr(WebTools, 'TLS_PAUSE', .05)
    tools = WebTools({'search': {'enabled': True, 'provider': 'duckduckgo', 'browser_tls_retry': True, **settings}})
    tools.use_pdf_library(PdfLibrary(tmp_path / 'pdf-cache'), 50 * 1024 * 1024)
    return tools


def filtered(accept, seen):
    """A site whose filter lets through only requests whose User-Agent contains one of ``accept``."""
    async def handler(request):
        agent = request.headers.get('User-Agent', '')
        ordinary = agent == BROWSER_USER_AGENT
        seen.append(('ordinary' if ordinary else 'safari' if 'Version/' in agent and 'Safari' in agent
                     else 'edge' if 'Edg/' in agent else 'chrome' if 'Chrome/' in agent else agent, request.path))
        if request.path == '/missing':
            return web.Response(status=404, text='not here')
        if request.path == '/busy':
            return web.Response(status=403 if ordinary else 429, text='slow down')
        if seen[-1][0] not in accept:
            return web.Response(status=403, text='<html>Access Denied</html>', content_type='text/html',
                                headers={'Server': 'AkamaiGHost'})
        if request.path == '/moved':
            raise web.HTTPFound('/en/Publications/WEO')
        if request.path == '/inside':
            raise web.HTTPFound('http://169.254.169.254/latest/meta-data')
        if request.path.endswith('.pdf'):
            return web.Response(body=REPORT, content_type='application/pdf')
        if request.path == '/big':
            return web.Response(text='x' * (2 * 1024 * 1024), content_type='text/plain')
        return web.Response(text='<html><body><h1>World Economic Outlook Reports</h1>'
                                 '<a href="/-/media/files/weo/text.pdf">Full report</a></body></html>', content_type='text/html')
    return handler


async def test_a_refused_page_and_its_pdf_are_fetched_with_the_kind_the_site_accepts(tmp_path, monkeypatch):
    seen = []
    pin(monkeypatch)
    async with http_server(filtered({'safari'}, seen)) as port:
        tools = tools_for(tmp_path, monkeypatch)
        base = f'http://www.reports.example:{port}'
        page = await tools.execute('web_fetch', {'url': base + '/en/Publications/WEO'})
        assert 'World Economic Outlook Reports' in page['text'] and page['fetched_as'] == 'safari'
        assert 'refused the ordinary request' in page['fetched_note']
        assert page['pdf_links'] == [{'url': base + '/-/media/files/weo/text.pdf', 'text': 'Full report'}]
        assert [kind for kind, _ in seen] == ['ordinary', 'safari']  # the first kind tried is the one that passed
        # Later requests to this site go straight with that kind: no second refusal is collected.
        started = time.monotonic()
        report = await tools.execute('web_fetch', {'url': page['pdf_links'][0]['url']})
        assert report['pages'] == 2 and report['fetched_as'] == 'safari' and report['pdf_id'] in tools.pdf_ids
        assert [kind for kind, _ in seen[2:]] == ['safari'] and time.monotonic() - started >= .04  # and not at once
        moved = await tools.execute('web_fetch', {'url': base + '/moved'})
        assert moved['url'] == base + '/en/Publications/WEO' and moved['fetched_as'] == 'safari'
        # The limits and the address rules are those of the ordinary request.
        with pytest.raises(WebToolError, match='exceeds the configured size limit'):
            await tools.execute('web_fetch', {'url': base + '/big'})
        with pytest.raises(WebToolError, match='HTTP 404'):
            await tools.execute('web_fetch', {'url': base + '/missing'})


async def test_a_redirect_to_a_private_address_is_refused_in_the_browser_like_request_too(tmp_path, monkeypatch):
    import workbench.webtools as module
    seen = []
    real = module._public_addresses

    async def addresses(host, port):
        if host == '169.254.169.254':
            return await real(host, port)  # the real check: not a public address
        return ['127.0.0.1']

    monkeypatch.setattr(module, '_public_addresses', addresses)
    async with http_server(filtered({'safari'}, seen)) as port:
        tools = tools_for(tmp_path, monkeypatch)
        with pytest.raises(WebToolError) as caught:
            await tools.execute('web_fetch', {'url': f'http://www.reports.example:{port}/inside'})
        assert 'meta-data' not in str(caught.value) and [path for _, path in seen] == ['/inside', '/inside']


async def test_every_kind_is_tried_once_and_a_site_that_refuses_all_is_left_alone(tmp_path, monkeypatch):
    seen = []
    pin(monkeypatch)
    async with http_server(filtered(set(), seen)) as port:
        tools = tools_for(tmp_path, monkeypatch)
        url = f'http://www.closed.example:{port}/report'
        with pytest.raises(WebToolError) as caught:
            await tools.execute('web_fetch', {'url': url})
        text = str(caught.value)
        assert 'HTTP 403 (access refused)' in text and "also refused a request with a browser's TLS (safari, chrome, edge)" in text
        assert 'Do not retry this URL' in text and "same institution's other official site" in text
        assert [kind for kind, _ in seen] == ['ordinary', 'safari', 'chrome', 'edge']
        with pytest.raises(WebToolError, match='a moment ago'):
            await tools.execute('web_fetch', {'url': url + '/other'})
        assert len(seen) == 5  # the ordinary request was made; no further browser-like ones
        # A rate limit or a missing page is the site's answer, not its filter: the other kinds are not tried.
        del seen[:]
        other = tools_for(tmp_path, monkeypatch)
        with pytest.raises(WebToolError, match='HTTP 429'):
            await other.execute('web_fetch', {'url': f'http://www.closed.example:{port}/busy'})
        assert [kind for kind, _ in seen] == ['ordinary', 'safari']


async def test_the_retry_is_the_humans_setting_and_searches_never_use_it(tmp_path, monkeypatch):
    seen = []
    pin(monkeypatch)
    async with http_server(filtered({'safari'}, seen)) as port:
        off = tools_for(tmp_path, monkeypatch, browser_tls_retry=False)
        with pytest.raises(WebToolError, match=r'HTTP 403 \(access refused\)$'):
            await off.execute('web_fetch', {'url': f'http://www.reports.example:{port}/page'})
        assert [kind for kind, _ in seen] == ['ordinary']
        # Without the library the ordinary refusal is reported as before.
        monkeypatch.setattr(browserfetch, 'available', lambda: False)
        on = tools_for(tmp_path, monkeypatch)
        with pytest.raises(WebToolError, match=r'HTTP 403 \(access refused\)$'):
            await on.execute('web_fetch', {'url': f'http://www.reports.example:{port}/page'})
    assert DEFAULT['search']['browser_tls_retry'] is True  # the human's instruction: on unless turned off
    raw = json.loads(json.dumps(DEFAULT))
    del raw['search']['browser_tls_retry']
    assert validate_settings(raw, check_paths=False)['search']['browser_tls_retry'] is True
    raw['search']['browser_tls_retry'] = 'yes'
    with pytest.raises(ValueError):
        validate_settings(raw, check_paths=False)
    with pytest.raises(WebToolError, match='browser_tls_retry'):
        WebTools({'search': {'enabled': True, 'browser_tls_retry': 1}})
    # Plain http is not retried: a browser's handshake means nothing there.
    assert WebTools._TLS_SCHEMES == frozenset({'http', 'https'})  # (this test's own setting)


async def test_the_human_sees_each_use_in_the_agents_log(tmp_path, monkeypatch):
    seen = []
    pin(monkeypatch)
    monkeypatch.setattr(WebTools, '_TLS_SCHEMES', frozenset({'http', 'https'}))
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    engine.kick = lambda agent: None
    try:
        async with http_server(filtered({'safari'}, seen)) as port:
            run, pm = await start(engine, max_workers=0)
            assert run['_web'].browser_tls_retry is True
            url = f'http://www.reports.example:{port}/-/media/files/weo/text.pdf'
            result = await engine.execute_tool(run, pm, 'web_fetch', {'url': url})
            assert result['pages'] == 2 and result['fetched_as'] == 'safari'
            notices = [row['text'] for row in pm.logs if row['kind'] == 'notice']
            assert any('ブラウザ相当の通信（safari）で取得しました' in text and 'text.pdf' in text for text in notices)
            page = await engine.execute_tool(run, pm, 'pdf_read', {'pdf_id': result['pdf_id'], 'first_page': 2})
            assert 'Growth is 3.2 percent' in page['content'][0]['text']
    finally:
        await engine.close()
