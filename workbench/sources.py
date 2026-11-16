"""Which URLs a run has actually seen, and which a written file only claims.

A URL is "known" when it appeared in the human's request or messages, in a web
tool result, in a file the run read, or in a script the run executed
successfully. A document that cites any other URL is citing something nobody
retrieved; the engine refuses such a write once (so the model can verify or
drop the URL) and afterwards reports it to the human.
"""
from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit

_URL = re.compile(r'https?://[^\s<>"\'`（）「」『』【】、。|\\^{}\[\]]+', re.I)
_TRAILING = '.,;:!?)]}>*_~'
_PLACEHOLDER = re.compile(r'0{6,}|x{4,}|_{3,}|\.\.\.|…|%7b|<|\[', re.I)
_RESERVED_HOSTS = ('localhost', 'example.com', 'example.org', 'example.net', 'example.jp')
# Source code and configuration legitimately contain endpoint URLs; they are not citations.
CODE_SUFFIXES = frozenset(('.py', '.pyi', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.java', '.kt', '.c', '.h', '.cpp',
                           '.cs', '.go', '.rs', '.rb', '.php', '.sh', '.ps1', '.bat', '.cmd', '.sql', '.yml', '.yaml',
                           '.toml', '.ini', '.cfg', '.json', '.xml', '.css', '.scss', '.ipynb'))


def normalize(url: str) -> str:
    url = url.rstrip(_TRAILING)
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        return url.lower()
    port = f':{parts.port}' if parts.port and parts.port not in (80, 443) else ''
    path = parts.path.rstrip('/')
    return f'{parts.scheme.lower()}://{host}{port}{path}' + (f'?{parts.query}' if parts.query else '')


def extract(value) -> set[str]:
    """Normalized URLs found anywhere in a string or JSON-like value."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return {normalize(match) for match in _URL.findall(text.replace('\\/', '/'))}


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


def exempt(url: str) -> bool:
    """Loopback, private and reserved example hosts are never citations."""
    host = _host(url)
    if not host or host in _RESERVED_HOSTS or host.endswith(('.localhost', '.example', '.test', '.invalid', '.local')):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def placeholder(url: str) -> bool:
    """A URL that is visibly a filler (long zero runs, xxxx, template marks)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return True
    return bool(_PLACEHOLDER.search(parts.path + '?' + parts.query))


def unknown(urls: set[str], known: set[str]) -> list[str]:
    """URLs not seen in this run. A bare site root counts as seen when any page of that host was."""
    hosts = {_host(url) for url in known}
    result = []
    for url in sorted(urls):
        if exempt(url) or url in known:
            continue
        try:
            parts = urlsplit(url)
        except ValueError:
            parts = None
        if parts is not None and not parts.path.strip('/') and not parts.query and _host(url) in hosts:
            continue
        result.append(url)
    return result
