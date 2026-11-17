"""A second request that looks like a browser's, for a site that refused the ordinary one.

Some public sites (an institution's report pages behind a bot filter) answer
403 to any HTTP library, whatever headers it sends, because the TLS and HTTP/2
handshake is not a browser's. curl_cffi sends a browser's handshake. This is
the human's choice (settings: search.browser_tls_retry) and it does get
around a site's bot filter; a site's terms may forbid it.

What stays as in the ordinary request: only public addresses, each checked
before it is used and pinned for the connection; redirects followed here, one
by one, with the same checks; the configured proxy and no other; the same
certificate authorities; the same size limits. What is never done: solving a
CAPTCHA or any check meant for a person, running a page's scripts, keeping
cookies after the request, or sending anything but a GET.

curl_cffi is imported when first used. Where it is not installed the retry is
simply not available, and the ordinary refusal is reported.
"""
from __future__ import annotations

import ssl
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

KINDS = ("safari", "chrome", "edge")   # the order tried; on the test machine only the first passed the IMF's filter
REFUSALS = frozenset({403, 202})       # answers that are a filter's, not a missing page or a rate limit
REDIRECTS = 5
_bundle_lock, _bundle = threading.Lock(), None


class Refused(Exception):
    """The browser-like request was answered, but not with the page (the status is kept)."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


class TooLarge(Exception):
    """The answer is larger than allowed (``declared``: the size the server stated, if it did)."""

    def __init__(self, declared, limit, is_pdf):
        super().__init__("too large")
        self.declared, self.limit, self.is_pdf = declared, limit, is_pdf


class Failed(Exception):
    """The request could not be made or completed; the text is a fixed class, never the library's own message."""


def available() -> bool:
    try:
        import curl_cffi  # noqa: F401
    except Exception:  # noqa: BLE001 - a missing or unloadable native library is the same as none
        return False
    return True


def ca_bundle():
    """The certificate authorities Python's own TLS trusts, as a file curl can read (None: curl's default).

    The ordinary request verifies against the system's authorities (on
    Windows the certificate store, which is where an organisation's own
    root is installed). curl would use a bundled list instead, so the same
    site could pass one request and fail the other behind an inspecting proxy.
    """
    global _bundle
    with _bundle_lock:
        if _bundle is None:
            _bundle = False
            try:
                certificates = ssl.create_default_context().get_ca_certs(binary_form=True)
                if certificates:
                    handle = tempfile.NamedTemporaryFile("w", suffix=".pem", prefix="awb-ca-", delete=False, encoding="ascii")
                    with handle:
                        handle.write("".join(ssl.DER_cert_to_PEM_cert(item) for item in certificates))
                    _bundle = handle.name
            except (OSError, ssl.SSLError, ValueError):
                _bundle = False
        return _bundle or None


def _failure(exc) -> str:
    code = getattr(exc, "code", None)
    return {6: "DNS failure", 7: "connection refused or unreachable", 28: "timeout", 35: "TLS failure (handshake)",
            56: "connection reset", 60: "TLS failure (certificate verification)",
            5: "the proxy could not be resolved", 97: "the proxy refused the connection"}.get(code, "the request could not be completed")


def get(url, *, kind, pins, proxy, wait, longest, limit_for, on_redirect):
    """One GET with a browser's handshake, in the calling thread.

    pins: the addresses the first host may be reached at ([(host, port, address)]),
    already checked as public. on_redirect(url, next_url) validates a redirect
    target and returns its pins (it is called from this thread and may block).
    limit_for(content_type, path) -> (bytes, is_pdf).
    Returns (data, content_type, final_url).
    """
    from curl_cffi import CurlOpt, requests
    from curl_cffi.requests.exceptions import RequestException

    started = time.monotonic()
    bundle = ca_bundle()
    session = requests.Session(impersonate=kind, trust_env=False, allow_redirects=False, proxy=proxy or None,
                               verify=bundle if bundle else True, timeout=longest, default_headers=True)
    try:
        for _ in range(REDIRECTS + 1):
            resolve = [f"{host}:{port}:{'[' + address + ']' if ':' in address else address}" for host, port, address in pins]
            # Options of the session are applied to each request: the pins of this hop, and no other protocol.
            session.curl_options = {CurlOpt.RESOLVE: resolve, CurlOpt.PROTOCOLS_STR: "http,https"}
            try:
                response = session.get(url, stream=True)
            except RequestException as exc:
                raise Failed(_failure(exc)) from None
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise Failed("a redirect did not include a destination")
                    next_url = urllib.parse.urldefrag(urllib.parse.urljoin(url, location))[0]
                    pins = on_redirect(url, next_url)
                    url = next_url
                    continue
                if response.status_code != 200:
                    raise Refused(response.status_code)
                content_type = response.headers.get("Content-Type", "")
                limit, is_pdf = limit_for(content_type, urllib.parse.urlsplit(url).path)
                declared = response.headers.get("Content-Length", "")
                if is_pdf and declared.isdigit() and int(declared) > limit:
                    raise TooLarge(int(declared), limit, True)
                data = bytearray()
                try:
                    for chunk in response.iter_content():
                        data.extend(chunk)
                        if len(data) > limit:
                            raise TooLarge(None, limit, is_pdf)
                        if time.monotonic() - started > (longest if is_pdf else wait):
                            raise Failed("timeout")
                except RequestException as exc:
                    raise Failed(_failure(exc)) from None
                return bytes(data), content_type, url
            finally:
                response.close()
        raise Failed("too many redirects")
    finally:
        session.close()


def cleanup():
    """Remove the certificate file written for curl (tests; the file is otherwise left to the temp folder)."""
    global _bundle
    with _bundle_lock:
        if _bundle:
            Path(_bundle).unlink(missing_ok=True)
        _bundle = None
