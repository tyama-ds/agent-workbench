"""Real-machine web findings, reproduced with local HTTP fixtures only.

No external search, page or model service is contacted: every "public" host is
pinned to a loopback test server through the same resolver seam the other web
tests use.
"""
import asyncio
import errno
import json
import socket
import ssl
import sys
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench.webtools as module
from workbench.webtools import WebToolError, WebTools


RESULT = ('<div class="result results_links web-result"><h2 class="result__title">'
          '<a class="result__a" href="https://example.com/article">Found</a></h2>'
          '<div><a class="result__snippet">Excerpt</a></div></div>')
# Shape of the page DuckDuckGo serves with HTTP 202 instead of results.
ANOMALY = ('<div class="anomaly-modal__mask"><div class="anomaly-modal__modal">'
           '<div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>'
           '<form id="challenge-form" action="//duckduckgo.com/anomaly.js" method="POST"></form></div></div>')


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
        yield port
    finally:
        await runner.cleanup()


def pin(monkeypatch, addresses=("127.0.0.1",)):
    seen = []

    async def public_addresses(host, port):
        seen.append(host)
        return list(addresses)

    monkeypatch.setattr(module, "_public_addresses", public_addresses)
    return seen


def duckduckgo(port, **overrides):
    tools = WebTools({"search": {"enabled": True, "provider": "duckduckgo", **overrides}})
    assert tools.endpoint == "https://html.duckduckgo.com/html/"
    tools.endpoint = f"http://search.example:{port}/html/"  # same code path, loopback fixture
    return tools


def fetcher(**overrides):
    return WebTools({"search": {"enabled": True, **overrides}})


async def record(request):
    return {"method": request.method, "path": request.raw_path, "headers": dict(request.headers),
            "body": await request.text()}


def closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# --- 1. DuckDuckGo search is a browser-like form POST ---------------------------------------------


def test_duckduckgo_search_is_a_form_post_with_browser_headers_and_no_credentials(monkeypatch):
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            return web.Response(text=RESULT, content_type="text/html", headers={"Set-Cookie": "session=tracking"})

        hosts = pin(monkeypatch)
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        async with http_server(handler) as port:
            tools = duckduckgo(port)
            first = await tools.execute("web_search", {"query": "日本語 & robotics=1", "limit": 3})
            await tools.execute("web_search", {"query": "second"})
        assert first == {"query": "日本語 & robotics=1", "untrusted": True, "results": [
            {"title": "Found", "url": "https://example.com/article", "snippet": "Excerpt"}]}
        assert hosts == ["search.example", "search.example"]  # resolved, validated and pinned each time
        sent = requests[0]
        assert sent["method"] == "POST" and sent["path"] == "/html/"  # the query is not in the URL
        assert sent["body"] == "q=" + urllib.parse.quote_plus("日本語 & robotics=1")
        assert urllib.parse.parse_qs(sent["body"]) == {"q": ["日本語 & robotics=1"]}
        headers = sent["headers"]
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert headers["User-Agent"] == module.BROWSER_USER_AGENT
        assert headers["User-Agent"].startswith("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") and "Chrome/" in headers["User-Agent"]
        assert "aiohttp" not in headers["User-Agent"] and "Python" not in headers["User-Agent"]
        assert headers["Accept"].startswith("text/html,application/xhtml+xml")
        assert headers["Accept-Language"].startswith("ja,en")
        assert headers["Host"] == f"search.example:{port}"
        assert headers["Origin"] == f"http://search.example:{port}"
        assert headers["Referer"] == f"http://search.example:{port}/"
        # Keyless and stateless: nothing identifies the user, and the cookie
        # set by the first response is not returned on the second search.
        for sent in requests:
            assert not {"Cookie", "Authorization", "Proxy-Authorization", "X-Subscription-Token"} & set(sent["headers"])
        assert len(requests) == 2
    asyncio.run(run())


@pytest.mark.parametrize("status, body, expected", [
    (202, ANOMALY, "bot check"),
    (202, "", "bot check"),
    (200, ANOMALY, "bot check"),
    (200, '<form id="challenge-form"></form>' + RESULT, "bot check"),
    (403, "<p>Forbidden</p>", "refused the search \\(HTTP 403\\)"),
    (429, "", "refused the search \\(HTTP 429\\)"),
])
def test_duckduckgo_bot_check_or_refusal_is_one_clear_error_not_empty_results(monkeypatch, status, body, expected):
    async def run():
        calls = []

        async def handler(request):
            calls.append(request.method)
            return web.Response(status=status, text=body, content_type="text/html")

        pin(monkeypatch)
        async with http_server(handler) as port:
            with pytest.raises(WebToolError, match=expected) as caught:
                await duckduckgo(port).execute("web_search", {"query": "blocked"})
        message = str(caught.value)
        assert "Do not repeat the search" in message and "web_fetch" in message
        assert "127.0.0.1" not in message and str(port) not in message and "blocked" not in message
        assert calls == ["POST"]  # the tool itself never retries a refused search
    asyncio.run(run())


def test_duckduckgo_other_status_and_unrecognized_page_stay_distinct_errors(monkeypatch):
    async def run():
        async def handler(request):
            if request.path == "/down/":
                return web.Response(status=503)
            return web.Response(text="<html><p>maintenance</p></html>", content_type="text/html")

        pin(monkeypatch)
        async with http_server(handler) as port:
            tools = duckduckgo(port)
            with pytest.raises(WebToolError, match="recognizable"):
                await tools.execute("web_search", {"query": "x"})
            tools.endpoint = f"http://search.example:{port}/down/"
            with pytest.raises(WebToolError, match=r"HTTP 503 \(server error\)"):
                await tools.execute("web_search", {"query": "x"})
    asyncio.run(run())


@pytest.mark.parametrize("status, methods, bodies", [
    (303, ["POST", "GET"], ["q=x", ""]),       # as a browser: the form is not re-sent
    (302, ["POST", "GET"], ["q=x", ""]),
    (307, ["POST", "POST"], ["q=x", "q=x"]),   # method and body are preserved
])
def test_search_post_redirects_stay_on_the_origin(monkeypatch, status, methods, bodies):
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            if request.path == "/html/":
                return web.Response(status=status, headers={"Location": "/moved/"})
            return web.Response(text=RESULT, content_type="text/html")

        pin(monkeypatch)
        async with http_server(handler) as port:
            result = await duckduckgo(port).execute("web_search", {"query": "x"})
        assert result["results"][0]["url"] == "https://example.com/article"
        assert [item["method"] for item in requests] == methods
        assert [item["body"] for item in requests] == bodies
        assert [item["path"] for item in requests] == ["/html/", "/moved/"]
        assert ("Content-Type" in requests[1]["headers"]) is (methods[1] == "POST")
    asyncio.run(run())


@pytest.mark.parametrize("status", [302, 307])
def test_search_post_never_follows_a_cross_origin_redirect(monkeypatch, status):
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            return web.Response(status=status, headers={"Location": "http://other.example/collect"})

        hosts = pin(monkeypatch)
        async with http_server(handler) as port:
            with pytest.raises(WebToolError, match="cross-origin"):
                await duckduckgo(port).execute("web_search", {"query": "private words"})
        assert len(requests) == 1 and hosts == ["search.example"]
    asyncio.run(run())


def test_searxng_stays_a_json_get_with_the_same_browser_identity():
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            return web.json_response({"results": [{"url": "https://example.com/a", "title": "T", "content": "C"}]})

        async with http_server(handler) as port:
            tools = WebTools({"search": {"enabled": True, "provider": "searxng",
                                         "endpoint": f"http://127.0.0.1:{port}/search?language=ja"}})
            result = await tools.execute("web_search", {"query": "テスト", "limit": 50})  # capped to 10
        assert result["results"] == [{"title": "T", "url": "https://example.com/a", "snippet": "C"}]
        sent = requests[0]
        assert sent["method"] == "GET" and sent["body"] == ""
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(sent["path"]).query) == {
            "language": ["ja"], "q": ["テスト"], "format": ["json"]}
        assert sent["headers"]["Accept"] == "application/json"
        assert sent["headers"]["User-Agent"] == module.BROWSER_USER_AGENT
        assert "Content-Type" not in sent["headers"] and "Origin" not in sent["headers"]
    asyncio.run(run())


# --- 2. Page fetches: browser headers, real causes of the generic failure, failure classes -------


def test_fetch_sends_browser_headers_without_cookies_or_a_body(monkeypatch):
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            if request.path == "/start":
                return web.Response(status=302, headers={"Location": "/page#section", "Set-Cookie": "id=1"})
            return web.Response(text="<p>Readable</p>", content_type="text/html")

        pin(monkeypatch)
        async with http_server(handler) as port:
            result = await fetcher().execute("web_fetch", {"url": f"http://public.example:{port}/start"})
        # A redirect target's fragment is dropped (it is never sent to a server).
        assert "Readable" in result["text"] and result["url"] == f"http://public.example:{port}/page"
        assert [item["path"] for item in requests] == ["/start", "/page"]
        for sent in requests:
            assert sent["method"] == "GET" and sent["body"] == ""
            assert sent["headers"]["User-Agent"] == module.BROWSER_USER_AGENT
            assert sent["headers"]["Accept"] == module.BROWSER_HEADERS["Accept"]
            assert sent["headers"]["Accept-Language"] == "ja,en-US;q=0.9,en;q=0.8"
            assert sent["headers"]["Host"] == f"public.example:{port}"
            assert not {"Cookie", "Authorization", "Content-Type", "Origin", "Referer"} & set(sent["headers"])
    asyncio.run(run())


def test_user_supplied_fragment_is_still_rejected_before_any_request(monkeypatch):
    async def run():
        hosts = pin(monkeypatch)
        with pytest.raises(WebToolError, match="fragment"):
            await fetcher().execute("web_fetch", {"url": "http://public.example/page#section"})
        assert hosts == []
    asyncio.run(run())


@pytest.mark.parametrize("path", ["/long-header", "/many-headers"])
def test_ordinary_large_response_headers_no_longer_fail_the_fetch(monkeypatch, path):
    """aiohttp's default 8190-byte/128-line header limits produced the generic failure."""
    async def run():
        async def handler(request):
            response = web.Response(text="<p>ok</p>", content_type="text/html")
            if request.path == "/long-header":
                response.headers["Content-Security-Policy"] = "default-src 'self' " + "https://cdn.example " * 600
            else:
                for index in range(150):
                    response.headers.add("Set-Cookie", f"c{index}=v; Path=/")
            return response

        pin(monkeypatch)
        async with http_server(handler) as port:
            result = await fetcher().execute("web_fetch", {"url": f"http://public.example:{port}{path}"})
        assert result["text"].strip() == "ok"
    asyncio.run(run())


def test_header_limits_remain_bounded(monkeypatch):
    async def run():
        async def handler(request):
            return web.Response(text="x", content_type="text/plain", headers={"X-Large": "a" * 40000})

        pin(monkeypatch)
        async with http_server(handler) as port:
            with pytest.raises(WebToolError, match="Web request failed: response headers exceed the size limit"):
                await fetcher().execute("web_fetch", {"url": f"http://public.example:{port}/"})
    asyncio.run(run())


@pytest.mark.parametrize("path, expected", [
    ("/slow", r"Web request failed: timeout waiting for the response \(1 s limit\)"),
    ("/drop", "Web request failed: connection closed by the server without a response"),
    ("/br", "Web request failed: response used an unsupported content encoding"),
    ("/bad-gzip", "Web request failed: response body was incomplete or used an unsupported content encoding"),
    ("/403", r"Web service returned HTTP 403 \(access refused\)"),
    ("/404", r"Web service returned HTTP 404 \(not found\)"),
    ("/429", r"Web service returned HTTP 429 \(too many requests\)"),
    ("/500", r"Web service returned HTTP 500 \(server error\)"),
    ("/202", r"Web service returned HTTP 202$"),
    ("/pdf", r"Only textual web responses are supported \(HTML, plain text, JSON, Markdown, CSV\); got application/pdf$"),
    ("/odd-type", r"Only textual web responses are supported \(HTML, plain text, JSON, Markdown, CSV\)$"),
])
def test_fetch_failures_name_their_class_without_addresses(monkeypatch, path, expected):
    async def run():
        calls = []

        async def handler(request):
            calls.append(request.path)
            if request.path == "/slow":
                await asyncio.sleep(2)
            if request.path == "/drop":
                request.transport.close()
            if request.path == "/br":
                return web.Response(body=b"\x0b\x02\x80hi\x03", headers={"Content-Type": "text/html", "Content-Encoding": "br"})
            if request.path == "/bad-gzip":
                return web.Response(body=b"not gzip", headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})
            if request.path == "/pdf":
                return web.Response(body=b"%PDF-1.7", content_type="application/pdf")
            if request.path == "/odd-type":
                return web.Response(body=b"x", headers={"Content-Type": "text/<script>alert(1)</script>"})
            if request.path[1:].isdigit():
                return web.Response(status=int(request.path[1:]), text="<p>refused</p>", content_type="text/html")
            return web.Response(text="late", content_type="text/plain")

        # Only a failure to OPEN the connection may move on to another address.
        pin(monkeypatch, ("127.0.0.1", "::1"))
        async with http_server(handler) as port:
            with pytest.raises(WebToolError, match=expected) as caught:
                await fetcher(timeout_seconds=1).execute("web_fetch", {"url": f"http://public.example:{port}{path}"})
        message = str(caught.value)
        assert "127.0.0.1" not in message and str(port) not in message and "public.example" not in message
        assert "script" not in message and "check the configured" not in message
        assert set(calls) == {path}
    asyncio.run(run())


def test_connection_refused_and_tls_and_proxy_failures_are_classified(monkeypatch):
    async def run():
        async def handler(request):
            return web.Response(text="plain http", content_type="text/plain")

        pin(monkeypatch)
        port = closed_port()
        with pytest.raises(WebToolError, match="^Web request failed: connection refused$"):
            await fetcher().execute("web_fetch", {"url": f"http://public.example:{port}/"})
        with pytest.raises(WebToolError, match="^Web request failed: proxy connection refused$") as caught:
            await fetcher(proxy_url=f"http://127.0.0.1:{port}").execute("web_fetch", {"url": "http://public.example/"})
        assert str(port) not in str(caught.value)
        async with http_server(handler) as port:
            # HTTPS to a server that does not speak TLS: a handshake failure.
            with pytest.raises(WebToolError, match=r"^Web request failed: TLS failure \(handshake\)$"):
                await fetcher().execute("web_fetch", {"url": f"https://public.example:{port}/"})
        search = WebTools({"search": {"enabled": True, "provider": "searxng", "endpoint": f"http://127.0.0.1:{closed_port()}/search"}})
        with pytest.raises(WebToolError, match="^Web request failed: connection refused; check the configured search service or proxy$"):
            await search.execute("web_search", {"query": "x"})
    asyncio.run(run())


def test_dns_failure_keeps_its_own_message(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()

        async def failing(*args, **kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "synthetic")

        monkeypatch.setattr(loop, "getaddrinfo", failing)
        with pytest.raises(WebToolError, match="^Web destination DNS lookup failed$"):
            await fetcher().execute("web_fetch", {"url": "http://no-such-host.example/"})
    asyncio.run(run())


def _windows_error(code):
    error = OSError(22, "synthetic Windows system error")  # proactor errors carry EINVAL plus winerror
    error.winerror = code
    return error


def _connector_error(kind, os_error):
    key = aiohttp.client_reqrep.ConnectionKey("203.0.113.9", 443, True, True, None, None, None)
    return kind(key, os_error)


@pytest.mark.parametrize("error, expected", [
    (lambda: _connector_error(aiohttp.ClientConnectorCertificateError,
                              ssl.SSLCertVerificationError(1, "certificate verify failed: CN=secret.internal")),
     "TLS failure (certificate verification)"),
    (lambda: _connector_error(aiohttp.ClientConnectorSSLError, ssl.SSLError(1, "wrong version number")), "TLS failure (handshake)"),
    (lambda: ssl.SSLError(1, "decryption failed"), "TLS failure (handshake)"),
    (lambda: _connector_error(aiohttp.ClientConnectorDNSError, socket.gaierror(-2, "proxy.internal")), "DNS failure"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, ConnectionRefusedError(errno.ECONNREFUSED, "refused")), "connection refused"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, OSError(errno.ENETUNREACH, "unreachable")), "network unreachable"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, OSError(10051, "WSAENETUNREACH")), "network unreachable"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, OSError(99, "other")), "connection failed"),
    (lambda: _connector_error(aiohttp.ClientProxyConnectionError, ConnectionRefusedError(errno.ECONNREFUSED, "refused")),
     "proxy connection refused"),
    (lambda: aiohttp.ClientOSError(errno.ECONNRESET, "Connection reset by peer"), "connection reset"),
    (lambda: aiohttp.ClientOSError(10054, "An existing connection was forcibly closed by the remote host"), "connection reset"),
    (lambda: aiohttp.ClientOSError(None, "unspecified"), "connection failed"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, _windows_error(1225)), "connection refused"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, _windows_error(121)), "timeout while connecting"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, _windows_error(1231)), "network unreachable"),
    (lambda: _windows_error(64), "connection reset"),
    (lambda: _windows_error(5), "connection failed"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, OSError(10061, "WSAECONNREFUSED")), "connection refused"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, OSError(10060, "WSAETIMEDOUT")), "timeout while connecting"),
    (lambda: _connector_error(aiohttp.ClientConnectorError, TimeoutError(errno.ETIMEDOUT, "timed out")), "timeout while connecting"),
    (lambda: ConnectionResetError(errno.ECONNRESET, "reset"), "connection reset"),
    (lambda: aiohttp.ClientConnectionResetError("Cannot write to closing transport"), "connection reset"),
    (lambda: aiohttp.ConnectionTimeoutError("Connection timeout to host http://203.0.113.9"), "timeout while connecting (20 s limit)"),
    (lambda: aiohttp.SocketTimeoutError("Timeout on reading data from socket"), "timeout waiting for the response (20 s limit)"),
    (lambda: asyncio.TimeoutError(), "timeout waiting for the response (20 s limit)"),
    (lambda: aiohttp.ClientHttpProxyError(None, (), status=407, message="Proxy Authentication Required"),
     "the proxy refused the connection (HTTP 407)"),
    (lambda: aiohttp.ServerDisconnectedError(), "connection closed by the server without a response"),
    (lambda: aiohttp.ClientPayloadError("Response payload is not completed"),
     "response body was incomplete or used an unsupported content encoding"),
    (lambda: aiohttp.ClientResponseError(None, (), status=400, message="Invalid header token"), "malformed HTTP response"),
    (lambda: aiohttp.InvalidURL("http://203.0.113.9/\ud800"), "the URL could not be sent as an HTTP request"),
    (lambda: UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed"), "the URL could not be sent as an HTTP request"),
])
def test_failure_classes_are_fixed_labels_that_never_echo_exception_text(error, expected):
    label = module._failure_class(error(), 20)
    assert label == expected
    for private in ("203.0.113.9", "secret.internal", "proxy.internal", "CN="):
        assert private not in label


def test_a_later_validated_address_is_used_only_when_the_first_cannot_be_reached(monkeypatch):
    """An IPv6-first DNS answer on a machine without working IPv6 used to fail outright."""
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            return web.Response(text="reached", content_type="text/plain")

        pin(monkeypatch, ("::1", "127.0.0.1"))  # the fixture listens on IPv4 loopback only
        async with http_server(handler) as port:
            result = await fetcher().execute("web_fetch", {"url": f"http://public.example:{port}/page"})
        assert result["text"] == "reached" and len(requests) == 1
        assert requests[0]["headers"]["Host"] == f"public.example:{port}"
    asyncio.run(run())


def test_address_order_and_retry_policy():
    assert module._attempt_order(["2001:db8::1", "2001:db8::2", "192.0.2.1", "192.0.2.2"]) == [
        "2001:db8::1", "192.0.2.1", "2001:db8::2"]
    assert module._attempt_order(["192.0.2.1"]) == ["192.0.2.1"]
    assert module._attempt_order(["192.0.2.1", "192.0.2.2", "192.0.2.3", "192.0.2.4"]) == ["192.0.2.1", "192.0.2.2", "192.0.2.3"]
    retry = module._retry_next_address
    assert retry(_connector_error(aiohttp.ClientConnectorError, OSError(errno.ENETUNREACH, "x")))
    assert retry(aiohttp.ConnectionTimeoutError("x"))
    assert retry(aiohttp.ClientHttpProxyError(None, (), status=502, message="Bad Gateway"))
    # Nothing is re-sent once a request may have reached a server, and a proxy
    # or certificate problem is the same for every address.
    for error in (aiohttp.ServerDisconnectedError(), aiohttp.SocketTimeoutError("x"), asyncio.TimeoutError(),
                  aiohttp.ClientPayloadError("x"), aiohttp.ClientHttpProxyError(None, (), status=407, message="x"),
                  _connector_error(aiohttp.ClientProxyConnectionError, OSError(errno.ECONNREFUSED, "x")),
                  _connector_error(aiohttp.ClientConnectorCertificateError, ssl.SSLCertVerificationError(1, "x")),
                  _connector_error(aiohttp.ClientConnectorSSLError, ssl.SSLError(1, "x"))):
        assert not retry(error)


def test_every_fallback_address_must_still_be_public(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()

        async def records(*args, **kwargs):
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1::1", 80, 0, 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]

        monkeypatch.setattr(loop, "getaddrinfo", records)
        with pytest.raises(WebToolError, match="public"):
            await fetcher().execute("web_fetch", {"url": "http://mixed.example/"})
    asyncio.run(run())


# --- 3. web_read / web_search arguments: exact shapes, received values, safe capping --------------


def reader(monkeypatch, body, content_type="application/json"):
    tools = fetcher()
    calls = []

    async def request(url, **kwargs):
        calls.append(url)
        return body.encode("utf-8"), content_type, url

    monkeypatch.setattr(tools, "_request", request)
    return tools, calls


SECRET_KEY = "confidential_column"
SOURCE = json.dumps({"items": [{"name": f"n{index}", SECRET_KEY: index} for index in range(250)],
                     "title": "T" * 30000, "meta": {"count": 250}})


def test_too_large_limit_and_max_chars_are_capped_and_reported(monkeypatch):
    async def run():
        tools, calls = reader(monkeypatch, SOURCE)
        first = await tools.execute("web_fetch", {"url": "https://public.example/data"})
        ident = first["snapshot_id"]
        assert "limit_capped_to" not in first
        assert '"/items/0/name"' in first["read_hint"] and '["name","code"]' in first["read_hint"]
        assert "limit 1..100" in first["read_hint"] and "limit 1..10000" in first["read_hint"]
        page = await tools.execute("web_read", {"snapshot_id": ident, "pointer": "/items", "limit": 500, "fields": ["name"]})
        assert page["returned_items"] == 100 and page["limit_capped_to"] == 100
        assert page["next_offset"] == 100 and page["total_items"] == 250 and page["truncated"] is True
        assert [entry["index"] for entry in page["items"]] == list(range(100))
        exact = await tools.execute("web_read", {"snapshot_id": ident, "pointer": "/items", "limit": 100, "fields": ["name"]})
        assert "limit_capped_to" not in exact and exact["items"] == page["items"]
        text = await tools.execute("web_read", {"snapshot_id": ident, "pointer": "/title", "limit": 50000, "max_chars": 999999})
        assert text["returned_chars"] == 10000 and text["limit_capped_to"] == 10000 and text["next_offset"] == 10000
        assert len(json.dumps(text, ensure_ascii=False)) <= 24000  # max_chars is capped to its maximum, never exceeded
        assert len(calls) == 1
    asyncio.run(run())


def test_raw_text_limit_is_capped_too(monkeypatch):
    async def run():
        tools, _ = reader(monkeypatch, "字" * 30000, "text/plain; charset=utf-8")
        first = await tools.execute("web_fetch", {"url": "https://public.example/text"})
        assert "raw text, so pointer and fields do not apply" in first["read_hint"] and "limit 1..10000" in first["read_hint"]
        page = await tools.execute("web_read", {"snapshot_id": first["snapshot_id"], "limit": 10001, "max_chars": 24000})
        assert page["returned_chars"] == 10000 and page["limit_capped_to"] == 10000 and page["next_offset"] == 10000
    asyncio.run(run())


@pytest.mark.parametrize("args, expected", [
    ({"pointer": "/items", "limit": 0}, r"limit must be an integer 1\.\.100 items for a JSON array; got 0$"),
    ({"pointer": "/items", "limit": -5}, r"limit must be an integer 1\.\.100 items for a JSON array; got -5$"),
    ({"pointer": "/items", "limit": "50"}, r'limit must be an integer 1\.\.100 items for a JSON array; got string "50"$'),
    ({"pointer": "/items", "limit": True}, r"limit must be an integer 1\.\.100 .*; got boolean true$"),
    ({"pointer": "/title", "limit": 0}, r"limit must be an integer 1\.\.10000 characters for text; got 0$"),
    ({"pointer": "/items", "offset": -1}, r"offset must be an integer 0\.\.20000 items; got -1$"),
    ({"pointer": "/items", "offset": 251}, r"offset 251 is beyond this JSON array \(250 items\)$"),
    ({"pointer": "/title", "offset": 30001}, r"offset 30001 is beyond the retained text \(30000 characters\)"),
    ({"max_chars": 500}, r"max_chars must be an integer 1024\.\.24000; got 500$"),
    ({"pointer": "items"}, r'pointer must be one RFC 6901 string such as "/items/0/name".*got "items" \(try "/items"\)'),
    ({"pointer": "$.items[0].name"}, r'start with "/".*got "\$\.items\[0\]\.name"\. JSONPath'),
    ({"pointer": "items.0.name"}, r'got "items\.0\.name"\. JSONPath, dots'),
    ({"pointer": "#/items"}, r'got "#/items"'),
    ({"pointer": ["items", 0]}, r'pointer must be one RFC 6901 string.*; got array \["items", 0\]$'),
    ({"pointer": None}, r"pointer must be one RFC 6901 string.*; got null$"),
    ({"pointer": 3}, r"pointer must be one RFC 6901 string.*; got 3$"),
    ({"pointer": "/items/0/nam"}, r'the object at "/items/0" has no key "nam"; read that pointer to see its keys$'),
    ({"pointer": "/nope"}, r'the object at the root \(""\) has no key "nope"'),
    ({"pointer": "/items/250"}, r'array index does not exist: got 250, but the array at "/items" has 250 items'),
    ({"pointer": "/items/*"}, r'array index must be a canonical nonnegative integer such as 0; got "\*" for the array at "/items"'),
    ({"pointer": "/meta/count/x"}, r'cannot descend into a scalar: the value at "/meta/count" has type number'),
    ({"pointer": "/a~2"}, r'invalid RFC 6901 escape in "a~2"; only ~0 \(for ~\) and ~1 \(for /\) exist$'),
    ({"pointer": "/" + "a/" * 40}, r'pointer must have at most 32 "/" levels; got 41$'),
    ({"fields": "name"}, r'fields must be an array of 1\.\.20 distinct object-key strings such as \["name","code"\]; got string "name"$'),
    ({"fields": {"name": True}}, r'fields must be an array.*; got object \{"name": true\}$'),
    ({"fields": None}, r"fields must be an array.*; got null$"),
    ({"fields": []}, r"fields must be an array.*; got 0 entries$"),
    ({"fields": ["x"] * 21}, r"fields must be an array.*; got 21 entries$"),
    ({"fields": [["name"]]}, r"fields must be an array.*; got an entry of type array \(nested paths belong in pointer\)$"),
    ({"fields": ["name", "name"]}, r'fields must be an array.*; got "name" more than once$'),
    ({"fields": ["k" * 257]}, r"each at most 256 characters; got one of 257$"),
    ({"pointer": "/meta", "limit": 5}, r"offset/limit apply only to arrays or strings; the selected value has type object"),
    ({"pointer": "/meta/count", "fields": ["a"]}, r"fields selects object keys, but the selected value has type number"),
    ({"url": "https://other.example", "path": "/items"}, r'web_read accepts only snapshot_id, pointer, offset, limit, fields and max_chars; got unsupported: "path", "url"$'),
])
def test_read_argument_errors_say_what_is_accepted_and_what_was_received(monkeypatch, args, expected):
    async def run():
        tools, calls = reader(monkeypatch, SOURCE)
        first = await tools.execute("web_fetch", {"url": "https://public.example/data"})
        with pytest.raises(WebToolError, match=expected) as caught:
            await tools.execute("web_read", {"snapshot_id": first["snapshot_id"], **args})
        # Error text is not labeled untrusted, so it never carries snapshot content.
        assert SECRET_KEY not in str(caught.value) and len(str(caught.value)) <= 400
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("args, expected", [
    ({}, "got no snapshot_id$"),
    ({"snapshot_id": "abc"}, r'snapshot_id must be the "web-" plus 32 hex characters ID returned by web_fetch in this run; got "abc"$'),
    ({"snapshot_id": 5}, "got 5$"),
    ({"snapshot_id": "web-" + "x" * 5000}, r'got "web-x{52}\.\.\.$'),
])
def test_snapshot_id_errors_are_bounded_echoes(args, expected):
    async def run():
        with pytest.raises(WebToolError, match=expected) as caught:
            await fetcher().execute("web_read", args)
        assert len(str(caught.value)) <= 200
    asyncio.run(run())


def test_received_echo_is_bounded_and_survives_unusual_values():
    from workbench.webdata import received, received_names
    assert received("a\nb") == '"a\\nb"'
    assert len(received("x" * 5000)) == 60
    assert received("\ud800") == '"?"'  # never an unencodable error string
    assert received(float("nan")) == "NaN"
    assert received_names({"b", "a"}) == '; got unsupported: "a", "b"'
    assert received_names(set()) == ""
    assert received_names({str(index) for index in range(40)}).count(",") == 4


@pytest.mark.parametrize("name, args, expected", [
    ("web_search", {"query": "x", "limit": 0}, r"Search limit must be an integer 1\.\.10; got 0$"),
    ("web_search", {"query": "x", "limit": "5"}, r'Search limit must be an integer 1\.\.10; got "5"$'),
    ("web_search", {"query": "x", "limit": True}, r"Search limit must be an integer 1\.\.10; got true$"),
    ("web_search", {"query": "x", "count": 3}, r'web_search requires query and accepts only an optional limit; got unsupported: "count"$'),
    ("web_search", {"q": "x"}, r'web_search requires query .*; got unsupported: "q"$'),
    ("web_search", {"query": ""}, r"Search query must be one line of 1 to 1000 characters; got an empty query$"),
    ("web_search", {"query": "a\nb"}, r"got a line break or control character$"),
    ("web_search", {"query": "x" * 1001}, r"got 1001 characters$"),
    ("web_search", {"query": ["a"]}, r'got \["a"\]$'),
    ("web_fetch", {"url": "https://example.com/", "timeout": 3}, r'web_fetch requires only url; got unsupported: "timeout"$'),
    ("web_fetch", {}, r"web_fetch requires only url$"),
    ("web_browse", {}, r"Unknown web tool$"),
])
def test_search_and_fetch_argument_errors_fail_before_any_request(monkeypatch, name, args, expected):
    async def run():
        tools, calls = reader(monkeypatch, "{}")
        with pytest.raises(WebToolError, match=expected):
            await tools.execute(name, args)
        assert calls == []
    asyncio.run(run())


def test_search_limit_above_the_maximum_is_capped(monkeypatch):
    async def run():
        tools = WebTools({"search": {"enabled": True}})

        async def request(url, **kwargs):
            body = "".join(RESULT.replace("/article", f"/article{index}") for index in range(15))
            return body.encode(), "text/html; charset=utf-8", url

        monkeypatch.setattr(tools, "_request", request)
        assert len((await tools.execute("web_search", {"query": "x", "limit": 500}))["results"]) == 10
        assert len((await tools.execute("web_search", {"query": "x"}))["results"]) == 5
    asyncio.run(run())


def test_schemas_state_ranges_shapes_and_an_example_within_a_size_budget():
    schemas = {item["name"]: item for item in fetcher().schemas()}
    read = schemas["web_read"]
    for phrase in ('{"snapshot_id":"web-...","pointer":"/items","fields":["name"],"limit":50}',
                   "limit 1..100", "limit 1..10000", '""=root', "array of literal object keys", "No JSONPath"):
        assert phrase in read["description"]
    assert read["parameters"]["properties"]["pointer"]["description"] == "e.g. /items/0/name"
    assert read["parameters"]["properties"]["fields"]["description"] == 'e.g. ["name","code"]'
    assert "limit is 1..10 (default 5)" in schemas["web_search"]["description"]
    assert "#fragment" in schemas["web_fetch"]["description"]
    # Every schema is sent with every model request; the baseline was 2195.
    assert sum(len(json.dumps(item, ensure_ascii=False)) for item in schemas.values()) <= 2600


# --- real-machine follow-up: DuckDuckGo blocks an address that searches too often ---

def test_after_a_bot_check_no_further_search_is_sent_until_the_cooldown_ends(monkeypatch):
    from workbench import webtools
    from workbench.readiness import summarize  # noqa: F401  (imports the shared guard)

    async def run():
        hits = []

        async def handler(request):
            hits.append(request.method)
            if len(hits) == 1:
                return web.Response(status=202, text="<html>bot check</html>", content_type="text/html")
            return web.Response(text='<div class="result results_links"><a class="result__a" href="https://example.org/a">A</a>'
                                     '<a class="result__snippet">s</a></div>', content_type="text/html")

        pin(monkeypatch)
        async with http_server(handler) as port:
            tools = duckduckgo(port)
            with pytest.raises(WebToolError, match="HTTP 202"):
                await tools.execute("web_search", {"query": "x"})
            assert webtools.SEARCH_GUARD.status()["blocked"] and webtools.SEARCH_GUARD.status()["blocked_minutes"] == 10
            for query in ("y", "z"):
                with pytest.raises(WebToolError, match="will not be asked again for about 10 more minutes"):
                    await tools.execute("web_search", {"query": query})
            assert hits == ["POST"], "a blocked service is not asked again"
            # Another run's tools share the block; it lifts when the cool-down ends.
            other = duckduckgo(port)
            with pytest.raises(WebToolError, match="bot check"):
                await other.execute("web_search", {"query": "x"})
            webtools.SEARCH_GUARD.blocked_until = 0.0
            first = await other.execute("web_search", {"query": "x"})
            again = await other.execute("web_search", {"query": "x"})
            assert first["results"] and again is first and len(hits) == 2, "the same query in one run is sent once"
            assert not webtools.SEARCH_GUARD.status()["blocked"] and webtools.SEARCH_GUARD.status()["last_success"]
    asyncio.run(run())


def test_searches_are_spaced_out(monkeypatch):
    from workbench import webtools
    waits = []

    async def fake_sleep(seconds):
        waits.append(round(seconds, 1))

    async def run():
        monkeypatch.setattr(webtools.asyncio, "sleep", fake_sleep)
        guard = webtools.SearchGuard()
        for _ in range(3):
            await guard.pace()
    asyncio.run(run())
    assert waits == [2.0, 4.0], "the first search goes at once; later ones wait their turn"


# --- 5. Brave Search: the optional engine that uses the human's own key ---------------------------


def brave(port, key="BSA-test-key"):
    tools = WebTools({"search": {"enabled": True, "provider": "brave", "endpoint": module.BRAVE_ENDPOINT}},
                     search_key=lambda: key)
    assert tools.endpoint == module.BRAVE_ENDPOINT and tools.api_key == ""
    tools.endpoint = f"http://search.example:{port}/res/v1/web/search"  # same code path, loopback fixture
    return tools


def test_brave_search_sends_the_key_only_as_its_header_and_reads_json_results(monkeypatch):
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            return web.json_response({"type": "search", "web": {"results": [
                {"title": "生成AI <strong>規制</strong> &amp; 動向", "url": "https://example.com/a", "description": "<strong>要約</strong>"},
                {"title": "bad", "url": "javascript:alert(1)"},
                {"title": "B", "url": "https://example.com/b", "description": "二件目"}]}})

        pin(monkeypatch)
        async with http_server(handler) as port:
            tools = brave(port)
            result = await tools.execute("web_search", {"query": "生成AI 規制", "limit": 2})
            again = await tools.execute("web_search", {"query": "生成AI 規制", "limit": 2})
        assert result == again and len(requests) == 1  # the same query does not spend quota twice
        assert result["results"] == [{"title": "生成AI 規制 & 動向", "url": "https://example.com/a", "snippet": "要約"},
                                     {"title": "B", "url": "https://example.com/b", "snippet": "二件目"}]
        sent = requests[0]
        assert sent["method"] == "GET" and sent["body"] == ""
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(sent["path"]).query) == {
            "q": ["生成AI 規制"], "count": ["2"], "text_decorations": ["false"]}
        assert sent["headers"]["X-Subscription-Token"] == "BSA-test-key" and sent["headers"]["Accept"] == "application/json"
        assert "BSA-test-key" not in sent["path"] and "Cookie" not in sent["headers"]
        assert "BSA-test-key" not in json.dumps(result)
    asyncio.run(run())


@pytest.mark.parametrize("status,expected", [(401, "did not accept the API key"), (422, "did not accept the API key"),
                                              (429, "rate or monthly limit")])
def test_brave_refusals_are_named_and_never_echo_the_key(monkeypatch, status, expected):
    async def run():
        async def handler(request):
            return web.json_response({"error": {"detail": request.headers.get("X-Subscription-Token")}}, status=status)

        pin(monkeypatch)
        async with http_server(handler) as port:
            with pytest.raises(WebToolError, match=expected) as error:
                await brave(port).execute("web_search", {"query": "q"})
        assert "BSA-test-key" not in str(error.value)
    asyncio.run(run())


def test_brave_without_a_key_sends_nothing_and_a_retired_configuration_stays_keyless(monkeypatch):
    async def run():
        async def handler(request):
            raise AssertionError("no request without a key")

        pin(monkeypatch)
        async with http_server(handler) as port:
            for source in (None, lambda: ""):
                tools = WebTools({"search": {"enabled": True, "provider": "brave", "endpoint": module.BRAVE_ENDPOINT}},
                                 search_key=source)
                tools.endpoint = f"http://search.example:{port}/res/v1/web/search"
                assert not tools.search_key_set()
                with pytest.raises(WebToolError, match="needs an API key"):
                    await tools.execute("web_search", {"query": "q"})
        # A retired Brave configuration (custom endpoint) is DuckDuckGo and never receives a key.
        legacy = WebTools({"search": {"enabled": True, "provider": "brave", "endpoint": "https://old.example/search"}},
                          search_key=lambda: "BSA-test-key")
        assert legacy.provider == "duckduckgo" and legacy.endpoint == module.DUCKDUCKGO_ENDPOINT and legacy._search_key is None
        keyless = WebTools({"search": {"enabled": True, "provider": "searxng", "endpoint": "https://s.example/search"}},
                           search_key=lambda: "BSA-test-key")
        assert keyless._search_key is None and not keyless.search_key_set()
    asyncio.run(run())


def test_the_brave_key_never_follows_a_redirect_to_another_origin(monkeypatch):
    async def run():
        async def handler(request):
            raise web.HTTPFound("http://elsewhere.example:1/steal")

        hosts = pin(monkeypatch)
        async with http_server(handler) as port:
            with pytest.raises(WebToolError, match="cross-origin redirect"):
                await brave(port).execute("web_search", {"query": "q"})
        assert hosts == ["search.example"]
    asyncio.run(run())


def test_blocked_minutes_round_up_without_adding_a_minute_to_a_whole_number(monkeypatch):
    """A coarse clock (Windows) can leave exactly 600 seconds: that is 10 minutes, not 11."""
    guard = module.SearchGuard()
    for seconds, minutes in ((600.0, 10), (599.2, 10), (540.0, 9), (0.4, 1), (0.0, 0)):
        monkeypatch.setattr(guard, "blocked_seconds", lambda seconds=seconds: seconds)
        assert guard.status()["blocked_minutes"] == minutes
        if seconds:
            with pytest.raises(WebToolError, match=f"about {minutes} more minutes"):
                guard.check()


# --- 6. What the bot check keys on, and what a challenge page leaves behind ----------------------


def test_no_request_offers_only_gzip_and_deflate_with_the_browser_identity(monkeypatch):
    """Real-machine finding: aiohttp's automatic "Accept-Encoding: gzip, deflate" next to a
    Chrome User-Agent got HTTP 202 (bot check) from DuckDuckGo on every search, while the same
    request without it returned results. Every request states the header itself."""
    async def run():
        requests = []

        async def handler(request):
            requests.append(await record(request))
            if request.path.startswith("/html"):
                return web.Response(text=RESULT, content_type="text/html")
            if request.path.startswith("/res"):
                return web.json_response({"web": {"results": [{"title": "T", "url": "https://example.com/a", "description": "D"}]}})
            if request.path.startswith("/search"):
                return web.json_response({"results": [{"url": "https://example.com/a", "title": "T", "content": "C"}]})
            return web.Response(text="<html><title>page</title><p>body</p></html>", content_type="text/html")

        pin(monkeypatch)
        async with http_server(handler) as port:
            await duckduckgo(port).execute("web_search", {"query": "生成AI ガイドライン"})
            await brave(port).execute("web_search", {"query": "q"})
            await WebTools({"search": {"enabled": True, "provider": "searxng",
                                       "endpoint": f"http://127.0.0.1:{port}/search"}}).execute("web_search", {"query": "q"})
            await fetcher().execute("web_fetch", {"url": f"http://page.example:{port}/article"})
        assert [row["path"].split("?")[0] for row in requests] == ["/html/", "/res/v1/web/search", "/search", "/article"]
        for sent in requests:
            offered = sent["headers"].get("Accept-Encoding", "")
            assert offered == "identity", (sent["path"], offered)
            assert "gzip" not in offered and "deflate" not in offered
            assert [name for name in sent["headers"] if name.lower() == "accept-encoding"] == ["Accept-Encoding"]  # sent once
    asyncio.run(run())


def test_a_challenge_page_with_status_200_keeps_the_block_and_is_an_error(monkeypatch):
    async def run():
        hits = []

        async def handler(request):
            hits.append(request.method)
            return web.Response(text=ANOMALY if len(hits) == 1 else RESULT, content_type="text/html")

        pin(monkeypatch)
        async with http_server(handler) as port:
            tools = duckduckgo(port)
            with pytest.raises(WebToolError, match="bot check"):
                await tools.execute("web_search", {"query": "x"})
            status = module.SEARCH_GUARD.status()
            assert status["blocked"] and status["blocked_minutes"] == 10 and status["last_success"] is None
            with pytest.raises(WebToolError, match="will not be asked again"):
                await tools.execute("web_search", {"query": "y"})
            assert hits == ["POST"]  # the challenge did not count as a success, so nothing more was sent
    asyncio.run(run())
