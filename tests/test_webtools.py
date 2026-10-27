"""Real local HTTP fixtures; no external search or model service is contacted."""
import asyncio
import html
import json
import socket
import sys
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench.webtools as module
from workbench.webtools import WebToolError, WebTools


@asynccontextmanager
async def http_server(handler):
    application = web.Application()
    application.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


def config(**overrides):
    return {"search": {"enabled": True, "provider": "searxng", "endpoint": "http://configured-engine.invalid/search", **overrides}}


def test_disabled_tools_and_exact_arguments():
    async def run():
        disabled = WebTools({})
        assert disabled.schemas() == []
        with pytest.raises(WebToolError, match="disabled"):
            await disabled.execute("web_fetch", {"url": "https://example.com"})
        tools = WebTools(config())
        assert {item["name"] for item in tools.schemas()} == {"web_search", "web_fetch", "web_read"}
        for name, args in (("web_search", {"query": "x", "endpoint": "http://localhost/"}),
                           ("web_fetch", {"url": "https://example.com", "proxy": "x"}),
                           ("web_search", {"query": "x", "limit": True}), ("web_search", {"query": "\n"})):
            with pytest.raises(WebToolError):
                await tools.execute(name, args)
    asyncio.run(run())


@pytest.mark.parametrize("url", ["file:///private", "ftp://example.com/x", "http://u:p@example.com/x", "http://example.com/#secret", "http://127.0.0.1/x", "http://127.1/x", "http://[::1]/x", "http://169.254.169.254/latest", "http://10.0.0.1/", "http://[::ffff:127.0.0.1]/", "http://localhost/", "http://host.local/", "http://example.com\\@127.0.0.1/", "http://example.com/\r\nheader"])
def test_invalid_and_private_fetches_fail_before_network(url):
    async def run():
        with pytest.raises(WebToolError):
            await WebTools(config()).execute("web_fetch", {"url": url})
    asyncio.run(run())


def test_explicit_proxy_carries_search_and_pinned_fetch_without_environment_proxy(monkeypatch):
    async def run():
        requests = []
        async def proxy(request):
            requests.append((request.raw_path, dict(request.headers)))
            if "configured-engine.invalid" in request.raw_path:
                return web.json_response({"results": [{"url": "https://public.example/article", "title": "Found", "content": "untrusted search excerpt"}]})
            return web.Response(text="<html><h1>Page</h1><script>do_bad_thing()</script><p>Readable data</p></html>", content_type="text/html")
        async def public_addresses(host, port):
            assert host == "public.example"
            return ["93.184.216.34"]
        monkeypatch.setattr(module, "_public_addresses", public_addresses)
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        async with http_server(proxy) as proxy_url:
            tools = WebTools(config(proxy_url=proxy_url))
            searched = await tools.execute("web_search", {"query": "日本語", "limit": 2})
            fetched = await tools.execute("web_fetch", {"url": "http://public.example/article"})
        assert searched["results"][0]["title"] == "Found" and searched["untrusted"]
        assert "Readable data" in fetched["text"] and "do_bad_thing" not in fetched["text"]
        assert fetched["untrusted"] and fetched["url"] == "http://public.example/article"
        assert len(requests) == 2
        assert requests[0][0].startswith("http://configured-engine.invalid/search?")
        assert "format=json" in requests[0][0]
        assert requests[1][0] == "http://93.184.216.34/article" or requests[1][0] == "http://93.184.216.34:80/article"
        assert requests[1][1]["Host"] == "public.example"
    asyncio.run(run())


def test_configured_internal_searxng_is_allowed_and_environment_proxy_is_ignored(monkeypatch):
    async def run():
        calls = []
        async def search(request):
            calls.append(dict(request.query))
            return web.json_response({"results": []})
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
        async with http_server(search) as endpoint:
            tools = WebTools(config(endpoint=endpoint + "/search"))
            assert (await tools.execute("web_search", {"query": "test"}))["results"] == []
            with pytest.raises(WebToolError, match="public"):
                await tools.execute("web_fetch", {"url": endpoint})
        assert calls == [{"q": "test", "format": "json"}]
    asyncio.run(run())


def test_fetch_redirect_is_revalidated_and_never_reaches_private_target(monkeypatch):
    async def run():
        calls = []
        async def proxy(request):
            calls.append(request.raw_path)
            raise web.HTTPFound("http://127.0.0.1:12345/private")
        real_resolver = module._public_addresses
        async def addresses(host, port):
            if host == "public.example":
                return ["93.184.216.34"]
            return await real_resolver(host, port)
        monkeypatch.setattr(module, "_public_addresses", addresses)
        async with http_server(proxy) as proxy_url:
            with pytest.raises(WebToolError, match="public"):
                await WebTools(config(proxy_url=proxy_url)).execute("web_fetch", {"url": "http://public.example/page"})
        assert len(calls) == 1
    asyncio.run(run())


def test_search_redirect_cannot_change_trusted_origin_or_leak_key():
    async def run():
        calls = []
        async def endpoint(request):
            calls.append(request.raw_path)
            raise web.HTTPFound("http://127.0.0.1:1/private")
        async with http_server(endpoint) as origin:
            with pytest.raises(WebToolError, match="origin"):
                await WebTools(config(endpoint=origin + "/search")).execute("web_search", {"query": "x"})
        assert len(calls) == 1
    asyncio.run(run())


def test_response_limit_applies_to_decompressed_data(monkeypatch):
    async def run():
        async def endpoint(request):
            response = web.Response(text="a" * 10000, content_type="text/plain")
            response.enable_compression()
            return response
        async def addresses(host, port):
            return ["93.184.216.34"]
        monkeypatch.setattr(module, "_public_addresses", addresses)
        async with http_server(endpoint) as proxy_url:
            with pytest.raises(WebToolError, match="size limit"):
                await WebTools(config(proxy_url=proxy_url, max_response_bytes=1024)).execute("web_fetch", {"url": "http://public.example/"})
    asyncio.run(run())


def test_mixed_public_private_dns_is_rejected(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        async def records(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)) for ip in ("93.184.216.34", "127.0.0.1")]
        monkeypatch.setattr(loop, "getaddrinfo", records)
        with pytest.raises(WebToolError, match="public"):
            await module._public_addresses("mixed.example", 80)
    asyncio.run(run())


def ddg_result(url="https://example.com/article", title="調査結果", snippet="資料の抜粋", *, classes="result results_links web-result"):
    return (f'<div class="{classes}"><h2 class="result__title">'
            f'<a class="result__a" href="{html.escape(url, quote=True)}">{title}</a></h2>'
            f'<div><a class="result__snippet">{snippet}</a></div></div>')


@pytest.mark.parametrize("provider", ["duckduckgo", "brave"])
def test_duckduckgo_fixed_public_endpoint_and_no_search_credentials(monkeypatch, provider):
    async def run():
        requests = []
        async def request(url, **kwargs):
            requests.append((url, kwargs))
            return ddg_result().encode(), "text/html; charset=utf-8", url
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "old-env-secret")
        tools = WebTools(config(provider=provider, endpoint="http://old-brave.example/search", api_key="runtime-secret"))
        monkeypatch.setattr(tools, "_request", request)
        result = await tools.execute("web_search", {"query": "日本語 & robotics", "limit": 2})
        url, options = requests[0]
        assert url.startswith("https://html.duckduckgo.com/html/?")
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) == {"q": ["日本語 & robotics"]}
        assert options == {"headers": {"Accept": "text/html"}, "trusted_search": False}
        assert tools.api_key == "" and tools.provider == "duckduckgo"
        assert result == {"query": "日本語 & robotics", "results": [
            {"title": "調査結果", "url": "https://example.com/article", "snippet": "資料の抜粋"}], "untrusted": True}
        assert "runtime-secret" not in json.dumps(requests + [result])
        assert "old-env-secret" not in json.dumps(requests + [result])
    asyncio.run(run())


def test_duckduckgo_parses_nested_text_redirect_links_deduplicates_and_limits(monkeypatch):
    async def run():
        target = "https://example.com/article?literal=%2F&name=robot"
        wrapped = "//duckduckgo.com/l/?uddg=" + urllib.parse.quote(target, safe="") + "&rut=ignored"
        body = (ddg_result("https://ad.example/", classes="result web-result result--ad result--ad--small")
                + ddg_result(wrapped, "研究 <b>成果</b> &amp; 資料", "日本語<br>抜粋<script>ignore()</script>")
                + ddg_result(target, "duplicate")
                + ddg_result("https://example.org/second", "Second", "Summary")
                + ddg_result("https://example.net/third"))
        tools = WebTools(config(provider="duckduckgo"))
        async def request(url, **kwargs):
            return body.encode(), "text/html; charset=utf-8", url
        monkeypatch.setattr(tools, "_request", request)
        rows = (await tools.execute("web_search", {"query": "robot", "limit": 2}))["results"]
        assert rows == [
            {"title": "研究 成果 & 資料", "url": target, "snippet": "日本語 抜粋"},
            {"title": "Second", "url": "https://example.org/second", "snippet": "Summary"}]
    asyncio.run(run())


@pytest.mark.parametrize("href", [
    "javascript:alert(1)", "file:///secret", "https://user:password@example.com/", "/relative",
    "https://duckduckgo.com/l/?uddg=javascript%3Aalert%281%29", "https://duckduckgo.com/l/?rut=missing",
    "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fa.example&uddg=https%3A%2F%2Fb.example",
    "https://duckduckgo.com/y.js?ad=1", "https://duckduckgo.com/l/?uddg=https%253A%252F%252Fexample.com",
    "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fduckduckgo.com%2Fy.js%3Fad%3D1",
])
def test_duckduckgo_invalid_targets_are_not_returned(href):
    parser = module._DuckDuckGoHTML()
    parser.feed(ddg_result(href) + ddg_result("https://safe.example/"))
    parser.close()
    assert [row["url"] for row in parser.rows(5)] == ["https://safe.example/"]


def test_duckduckgo_never_unwraps_lookalike_host():
    address = "https://duckduckgo.com.evil.example/l/?uddg=https%3A%2F%2Fexample.com"
    assert module._duckduckgo_result_url(address) == address
    target = "https://example.com/x?literal=%2F"
    wrapped = "/l/?uddg=" + urllib.parse.quote(target, safe="")
    assert module._duckduckgo_result_url(wrapped) == target


@pytest.mark.parametrize("body, message", [
    ('<form id="challenge-form"><p>Verify you are human</p></form>', "verification"),
    (ddg_result() + '<form id="challenge-form"></form>', "verification"),
    ('<html><p>Something went wrong</p></html>', "recognizable"),
    ('<html><title>DuckDuckGo</title><form><input name="q"></form></html>', "recognizable"),
    ('<script>' + ddg_result() + '</script>', "recognizable"),
    (ddg_result()[:-6], "recognizable"),
    ('<div class="no-results">No results found', "recognizable"),
    (ddg_result("javascript:invalid") + '<div class="no-results"></div>', "recognizable"),
])
def test_duckduckgo_blocked_unknown_or_incomplete_html_is_not_empty_success(body, message):
    parser = module._DuckDuckGoHTML()
    parser.feed(body)
    parser.close()
    with pytest.raises(WebToolError, match=message):
        parser.rows(5)


def test_duckduckgo_explicit_no_results_and_result_text_limits():
    empty = module._DuckDuckGoHTML()
    empty.feed('<div class="no-results"><div class="no-results__message">No results found</div></div>')
    empty.close()
    assert empty.rows(5) == []
    parser = module._DuckDuckGoHTML()
    parser.feed(ddg_result(title="t" * 600, snippet="s" * 4000))
    parser.close()
    row = parser.rows(5)[0]
    assert len(row["title"]) == 500 and len(row["snippet"]) == 3000


def test_duckduckgo_bounds_html_depth_and_result_candidates():
    parser = module._DuckDuckGoHTML()
    with pytest.raises(WebToolError, match="nesting limit"):
        parser.feed("<div>" * 257)
    parser = module._DuckDuckGoHTML()
    parser.feed(ddg_result("javascript:invalid") * 100 + ddg_result("https://outside-cap.example/"))
    parser.close()
    with pytest.raises(WebToolError, match="recognizable"):
        parser.rows(5)


@pytest.mark.parametrize("data, content_type, message", [
    (b'{"results": []}', "application/json", "HTML"),
    (b'<p>\xff</p>', "text/html; charset=utf-8", "decode"),
])
def test_duckduckgo_rejects_non_html_or_invalid_encoding(monkeypatch, data, content_type, message):
    async def run():
        tools = WebTools(config(provider="duckduckgo"))
        async def request(url, **kwargs):
            return data, content_type, url
        monkeypatch.setattr(tools, "_request", request)
        with pytest.raises(WebToolError, match=message):
            await tools.execute("web_search", {"query": "x"})
    asyncio.run(run())


def test_duckduckgo_resolver_is_not_the_searxng_private_network_exception(monkeypatch):
    async def run():
        calls = []
        async def addresses(host, port):
            calls.append((host, port))
            raise WebToolError("Only public web destinations are allowed")
        monkeypatch.setattr(module, "_public_addresses", addresses)
        with pytest.raises(WebToolError, match="public"):
            await WebTools(config(provider="duckduckgo")).execute("web_search", {"query": "x"})
        assert calls == [("html.duckduckgo.com", 443)]
    asyncio.run(run())


@pytest.mark.parametrize("address", ["64:ff9b::7f00:1", "64:ff9b:1::7f00:1", "2002:7f00:1::", "2001::1"])
def test_ipv6_transition_addresses_cannot_reach_private_ipv4(address):
    assert module._public_ip(address) is False


def test_real_proxy_shift_jis_header_bytes_and_final_url(monkeypatch):
    async def run():
        paths = []
        async def endpoint(request):
            paths.append(request.path)
            if request.path == '/start':
                raise web.HTTPFound('/shift-jis')
            return web.Response(body='<p>日本語 ①髙﨑</p>'.encode('cp932'),
                                headers={'Content-Type': 'text/html; charset="Shift_JIS"'})
        async def addresses(host, port):
            assert host == 'public.example'
            return ['93.184.216.34']
        monkeypatch.setattr(module, '_public_addresses', addresses)
        async with http_server(endpoint) as proxy_url:
            result = await WebTools(config(proxy_url=proxy_url)).execute('web_fetch', {'url': 'http://public.example/start'})
        assert result['text'] == '\n日本語 ①髙﨑'
        assert result['url'] == 'http://public.example/shift-jis'
        assert result['encoding'] == 'cp932' and result['encoding_source'] == 'http_charset'
        assert result['untrusted'] and not result['encoding_assumed'] and not result['truncated']
        assert paths == ['/start', '/shift-jis']
    asyncio.run(run())
