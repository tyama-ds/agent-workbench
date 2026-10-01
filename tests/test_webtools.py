"""Real local HTTP fixtures; no external search or model service is contacted."""
import asyncio
import json
import socket
import sys
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
        assert {item["name"] for item in tools.schemas()} == {"web_search", "web_fetch"}
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


def test_brave_secret_stays_in_header_and_response_never_contains_it(monkeypatch):
    async def run():
        requests = []
        async def proxy(request):
            requests.append((request.raw_path, dict(request.headers)))
            return web.json_response({"web": {"results": [{"url": "https://example.com/x", "title": "Answer", "description": "Source"}]}})
        async def addresses(host, port):
            return ["93.184.216.34"]
        monkeypatch.setattr(module, "_public_addresses", addresses)
        async with http_server(proxy) as proxy_url:
            tools = WebTools(config(provider="brave", endpoint="http://brave.example/search", api_key="runtime-secret", proxy_url=proxy_url))
            result = await tools.execute("web_search", {"query": "test"})
        assert requests[0][1]["X-Subscription-Token"] == "runtime-secret"
        assert "runtime-secret" not in requests[0][0] and "runtime-secret" not in json.dumps(result)
    asyncio.run(run())


@pytest.mark.parametrize("address", ["64:ff9b::7f00:1", "64:ff9b:1::7f00:1", "2002:7f00:1::", "2001::1"])
def test_ipv6_transition_addresses_cannot_reach_private_ipv4(address):
    assert module._public_ip(address) is False
