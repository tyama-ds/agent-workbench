"""Keyless web search through a real browser, and what every search method shares.

Browser search opens a search engine's result page in the browser the human
configured for Selenium (a dedicated profile kept by the application, never
the human's own), and reads titles, URLs and snippets from the page. The
model gets the same shape as every other ``web_search``; it cannot steer the
browser. Engines are tried in order, each with its own pacing and its own
pause after a bot check. A bot check is never solved by the application: when
every engine asks for one, a person is asked to pass it in a visible window.

Shared by all search methods: a cache on disk that outlives a run, so the
same or a reworded query does not go out again for hours, and a count of the
requests this PC has sent in the last hour.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

MAX_RESULTS = 10
MAX_PAGE_CHARS = 1_500_000
CACHE_SECONDS = 6 * 3600
CACHE_ENTRIES = 400
HOURLY_REQUESTS = 60
HUMAN_CHECK_SECONDS = 300


class SearchChallenge(ValueError):
    """Every available engine asked for a bot check (or is paused after one)."""

    def __init__(self, engines, message):
        super().__init__(message)
        self.engines = list(engines)


class SearchBudgetExceeded(ValueError):
    """This PC sent as many searches in the last hour as the application allows."""


def _clean(value, limit):
    text = ' '.join(''.join(value).split())
    return ''.join(c for c in text if ord(c) >= 32 and not 127 <= ord(c) <= 159)[:limit]


def bing_target(href):
    """The page a Bing result link leads to, or '' when it is not an outside page.

    Bing wraps most result links as https://www.bing.com/ck/a?...&u=a1<base64url>.
    """
    if not isinstance(href, str):
        return ''
    try:
        parts = urllib.parse.urlsplit(href)
    except ValueError:
        return ''
    host = (parts.hostname or '').lower()
    if parts.scheme not in {'http', 'https'} or not host:
        return ''
    if host.endswith('bing.com') and parts.path.startswith('/ck/a'):
        token = dict(urllib.parse.parse_qsl(parts.query)).get('u', '')
        if not token.startswith('a1'):
            return ''
        try:
            decoded = base64.urlsafe_b64decode(token[2:] + '=' * (-len(token[2:]) % 4)).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            return ''
        return bing_target(decoded) if not decoded.startswith('https://www.bing.com/ck/') else ''
    if host.endswith(('bing.com', 'microsoft.com/bing', 'bingj.com')) or host in {'go.microsoft.com'}:
        return ''
    return href


_VOID = frozenset(('br', 'img', 'input', 'meta', 'link', 'hr', 'wbr', 'source', 'area', 'col', 'embed', 'track'))
_CHALLENGE_IDS = {'b_captcha', 'captcha', 'turnstile-widget', 'cf-challenge-running', 'challenge-form', 'challenge-stage'}
_CHALLENGE_CLASSES = ('captcha', 'cf-turnstile', 'b_captcha', 'challenge-form', 'anomaly-modal')


class BingHTML(HTMLParser):
    """Result rows of a Bing result page: ``li.b_algo`` with ``h2 > a`` and a snippet paragraph."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results, self.challenge, self.no_results, self.container = [], False, False, False
        self._row, self._depth, self._field, self._field_depth = None, 0, None, 0
        self._ignored = 0

    def _markers(self, tag, attributes):
        classes = (attributes.get('class') or '').split()
        ident = attributes.get('id') or ''
        if (ident in _CHALLENGE_IDS or any(marker in name for name in classes for marker in _CHALLENGE_CLASSES)
                or (tag == 'iframe' and any(marker in (attributes.get('src') or '')
                                            for marker in ('challenges.cloudflare.com', 'captcha')))):
            self.challenge = True
        if ident == 'b_results':
            self.container = True
        if 'b_no' in classes:
            self.no_results = True
        return classes

    def handle_startendtag(self, tag, attrs):
        self._markers(tag, dict(attrs))  # <br/>, <img/>: no depth change

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {'script', 'style', 'noscript'}:
            self._ignored += 1
            return
        classes = self._markers(tag, attributes)
        if tag in _VOID:
            return
        if self._row is None:
            if tag == 'li' and 'b_algo' in classes:
                self._row, self._depth = {'url': '', 'title': [], 'snippet': [], 'heading': False}, 1
            return
        self._depth += 1
        if tag == 'h2':
            self._row['heading'] = True
        elif tag == 'a' and self._row['heading'] and not self._row['url'] and self._field is None:
            self._row['url'] = attributes.get('href') or ''
            self._field, self._field_depth = 'title', self._depth
        elif tag == 'p' and self._field is None and not self._row['snippet']:
            self._field, self._field_depth = 'snippet', self._depth

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'}:
            self._ignored = max(0, self._ignored - 1)
            return
        if self._row is None or tag in _VOID:
            return
        if self._field is not None and self._depth == self._field_depth:
            self._field = None
        if tag == 'h2':
            self._row['heading'] = False
        self._depth -= 1
        if self._depth <= 0:
            self.results.append(self._row)
            self._row, self._field = None, None

    def handle_data(self, data):
        if self._row is not None and self._field is not None and not self._ignored:
            self._row[self._field].append(data)

    def rows(self, limit):
        rows, seen = [], set()
        for entry in self.results:
            address = bing_target(entry['url'])
            title = _clean(entry['title'], 500)
            if not address or not title or address in seen:
                continue
            seen.add(address)
            rows.append({'title': title, 'url': address, 'snippet': _clean(entry['snippet'], 3000)})
            if len(rows) >= limit:
                break
        return rows


# What a verification page says, as seen on a real machine. A page with no
# result rows that carries one of these is a bot check, not "no results".
_CHECK_WORDS = ('bots use duckduckgo', 'select all squares containing', '課題を解決してください', '最後のステップ',
                'one last step', 'solve the challenge', 'verify you are human', 'verifying you are human',
                'あなたが人間であることを確認', 'unusual traffic')
_EMPTY_WORDS = ('no results found for', 'の検索結果はありません', 'に一致する結果は見つかりませんでした', 'no more results found for')


def _says(html, words):
    text = html[:MAX_PAGE_CHARS].casefold()
    return any(word in text for word in words)


def _state(rows, html, *, challenge=False, empty=False):
    """('results', rows) | ('empty', []) | ('challenge', []) | ('unknown', [])."""
    if rows:
        return 'results', rows
    if challenge or _says(html, _CHECK_WORDS):
        return 'challenge', []
    return ('empty', []) if empty or _says(html, _EMPTY_WORDS) else ('unknown', [])


def read_bing(html, limit):
    parser = BingHTML()
    parser.feed(html[:MAX_PAGE_CHARS])
    parser.close()
    return _state(parser.rows(limit), html, challenge=parser.challenge, empty=parser.no_results and parser.container)


def read_duckduckgo(html, limit):
    """html.duckduckgo.com (no scripts): the same page the keyless HTTP method reads."""
    from .webtools import WebToolError, _DuckDuckGoHTML
    parser = _DuckDuckGoHTML()
    parser.feed(html[:MAX_PAGE_CHARS])
    parser.close()
    if parser.challenge:
        return 'challenge', []
    try:
        rows = parser.rows(limit)
    except WebToolError:
        rows = []
    return _state(rows, html, empty=parser.no_results and not parser.candidates)


class DuckDuckGoWeb(HTMLParser):
    """duckduckgo.com as a browser renders it: ``a[data-testid="result-title-a"]`` and ``[data-result="snippet"]``."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results, self.challenge = [], False
        self._depth, self._field, self._field_depth, self._ignored = 0, None, 0, 0

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self._ignored += 1
            return
        if tag in _VOID:
            return
        attributes = dict(attrs)
        classes = (attributes.get('class') or '').split()
        if attributes.get('id') in _CHALLENGE_IDS or any(marker in name for name in classes for marker in _CHALLENGE_CLASSES):
            self.challenge = True
        self._depth += 1
        if self._field is not None:
            return
        if tag == 'a' and attributes.get('data-testid') == 'result-title-a':
            self.results.append({'url': attributes.get('href') or '', 'title': [], 'snippet': []})
            self._field, self._field_depth = 'title', self._depth
        elif attributes.get('data-result') == 'snippet' and self.results and not self.results[-1]['snippet']:
            self._field, self._field_depth = 'snippet', self._depth

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'}:
            self._ignored = max(0, self._ignored - 1)
            return
        if tag in _VOID:
            return
        if self._field is not None and self._depth == self._field_depth:
            self._field = None
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._field is not None and not self._ignored and self.results:
            self.results[-1][self._field].append(data)

    def rows(self, limit):
        from .webtools import WebToolError, _duckduckgo_result_url
        rows, seen = [], set()
        for entry in self.results:
            try:
                address = _duckduckgo_result_url(entry['url'])
                host = (urllib.parse.urlsplit(address).hostname or '').lower()
            except (WebToolError, ValueError):
                continue
            title = _clean(entry['title'], 500)
            if not title or address in seen or host == 'duckduckgo.com' or host.endswith('.duckduckgo.com'):
                continue  # advertisements and the engine's own pages are not results
            seen.add(address)
            rows.append({'title': title, 'url': address, 'snippet': _clean(entry['snippet'], 3000)})
            if len(rows) >= limit:
                break
        return rows


def read_duckduckgo_web(html, limit):
    parser = DuckDuckGoWeb()
    parser.feed(html[:MAX_PAGE_CHARS])
    parser.close()
    return _state(parser.rows(limit), html, challenge=parser.challenge)


# Tried in this order. ``ready`` is a CSS selector that exists once results are
# on the page; the browser waits for it briefly (or, in a human check, until
# the person has passed the verification).
#
# The order follows what a real machine showed with an ordinary (not headless)
# window: duckduckgo.com answered ten searches in a row, 2.5 s apart, while the
# keyless HTTP method was paused for the same address; Bing answered once and
# then asked for a verification every time.
ENGINES = (
    {'name': 'duckduckgo_web', 'label': 'DuckDuckGo', 'url': 'https://duckduckgo.com/?q={query}&ia=web',
     'ready': 'a[data-testid="result-title-a"]', 'read': read_duckduckgo_web, 'interval': 3.0},
    {'name': 'bing', 'label': 'Bing', 'url': 'https://www.bing.com/search?q={query}', 'ready': '#b_results li.b_algo, #b_results .b_no',
     'read': read_bing, 'interval': 5.0},
    {'name': 'duckduckgo_html', 'label': 'DuckDuckGo (HTML)', 'url': 'https://html.duckduckgo.com/html/?q={query}',
     'ready': '.result__a, .no-results', 'read': read_duckduckgo, 'interval': 6.0},
)


def engine_guards():
    """One pacing/pause record per browser engine.

    These are separate from the keyless HTTP method's record: a browser was
    answered while HTTP requests from the same address were being refused.
    """
    from . import webtools
    guards = getattr(engine_guards, '_guards', None)
    if guards is None:
        guards = engine_guards._guards = {}
        for engine in ENGINES:
            guard = guards[engine['name']] = webtools.SearchGuard()
            guard.min_interval = engine['interval']
    return guards


class BrowserSearch:
    """Run one search through the engines in order.

    ``page(url, ready, visible, wait_seconds)`` is an async callable that opens
    the URL in the application's browser profile and returns
    ``{'url', 'title', 'html'}``. It is the only thing that touches a browser.
    """

    def __init__(self, page, engines=ENGINES):
        self.page, self.engines = page, tuple(engines)

    async def search(self, query, limit):
        guards, asked, problems = engine_guards(), [], []
        for engine in self.engines:
            guard = guards[engine['name']]
            if guard.blocked_seconds():
                asked.append(engine['name'])
                continue
            await guard.pace()
            try:
                loaded = await self.page(engine['url'].format(query=urllib.parse.quote_plus(query)), engine['ready'], False, 8)
            except ValueError as exc:
                problems.append(f'{engine["label"]}: {str(exc)[:200]}')
                continue
            state, rows = engine['read'](str(loaded.get('html', '')), limit)
            if state == 'challenge':
                guard.refused()
                asked.append(engine['name'])
                continue
            if state == 'unknown':
                problems.append(f'{engine["label"]}: the result page was not recognised (its layout may have changed)')
                continue
            guard.succeeded()
            return {'query': query, 'results': rows, 'engine': engine['name'], 'untrusted': True}
        if asked:
            labels = ', '.join(engine['label'] for engine in self.engines if engine['name'] in asked)
            raise SearchChallenge(asked, f'Every search engine that could be tried asked for a human check or is paused after one ({labels}). '
                                         'The search was not completed.' + (' Other problems: ' + '; '.join(problems) if problems else ''))
        raise ValueError('Browser search failed: ' + ('; '.join(problems) or 'no engine is available')
                         + '. Do not repeat the search now; use web_fetch with known URLs or report that web search is unavailable')

    async def human_check(self, query, limit, engines=None):
        """Show the first engine that asked for a check and wait for a person to pass it."""
        guards = engine_guards()
        candidates = [engine for engine in self.engines if engines is None or engine['name'] in engines] or list(self.engines)
        engine = candidates[0]
        loaded = await self.page(engine['url'].format(query=urllib.parse.quote_plus(query)), engine['ready'], True, HUMAN_CHECK_SECONDS)
        state, rows = engine['read'](str(loaded.get('html', '')), limit)
        if state in {'results', 'empty'}:
            guards[engine['name']].succeeded()
            return {'query': query, 'results': rows, 'engine': engine['name'], 'untrusted': True}
        raise ValueError('The human check was not completed (the window was closed, or the time ran out). '
                         'Web search stays unavailable; use web_fetch with known URLs or report it')


def query_key(query):
    """The same for a query and its rewordings: width, case, spacing, punctuation and word order do not matter."""
    text = unicodedata.normalize('NFKC', query).casefold()
    words = sorted(set(re.findall(r'[^\W_]+', text)))
    return hashlib.sha256(' '.join(words).encode('utf-8')).hexdigest() if words else ''


class SearchCache:
    """Search results kept on disk for a few hours, and this PC's recent request times.

    Keys are hashes of the normalised query, so the file does not list what was
    asked. Values are public web data (titles, URLs, snippets).
    """

    def __init__(self, path, *, seconds=CACHE_SECONDS, hourly=HOURLY_REQUESTS):
        self.path, self.seconds, self.hourly = Path(path), seconds, hourly
        self.entries, self.requests = {}, []
        self._load()

    def _load(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 8 * 1024 * 1024:
                return
            data = json.loads(self.path.read_text(encoding='utf-8'))
            entries, requests = data.get('entries'), data.get('requests')
            if data.get('version') != 1 or not isinstance(entries, dict) or not isinstance(requests, list):
                return
        except (OSError, ValueError, AttributeError):
            return
        now = time.time()
        for key, entry in entries.items():
            if (isinstance(key, str) and re.fullmatch('[0-9a-f]{64}', key) and isinstance(entry, dict)
                    and isinstance(entry.get('at'), (int, float)) and now - entry['at'] < self.seconds
                    and type(entry.get('limit')) is int and isinstance(entry.get('rows'), list)):
                rows = [{name: str(row.get(name, ''))[:3000] for name in ('title', 'url', 'snippet')}
                        for row in entry['rows'][:MAX_RESULTS] if isinstance(row, dict)]
                self.entries[key] = {'at': float(entry['at']), 'limit': entry['limit'], 'rows': rows,
                                     'engine': str(entry.get('engine', ''))[:40]}
        self.requests = [float(at) for at in requests if isinstance(at, (int, float)) and now - at < 3600][-1000:]

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix='.search-cache-', suffix='.tmp', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    json.dump({'version': 1, 'entries': self.entries, 'requests': self.requests}, stream, ensure_ascii=False)
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        except OSError:
            pass  # the cache is a convenience; a search result is never lost because of it

    def get(self, query, limit):
        key = query_key(query)
        entry = self.entries.get(key)
        if not key or entry is None:
            return None
        if time.time() - entry['at'] >= self.seconds:
            self.entries.pop(key, None)
            return None
        # Enough rows for this request, or the engine had no more to give.
        if limit <= entry['limit'] or len(entry['rows']) < entry['limit']:
            return {'query': query, 'results': [dict(row) for row in entry['rows'][:limit]], 'untrusted': True,
                    'cached': True, **({'engine': entry['engine']} if entry['engine'] else {})}
        return None

    def put(self, query, limit, result):
        key = query_key(query)
        rows = result.get('results') if isinstance(result, dict) else None
        if not key or not isinstance(rows, list):
            return
        self.entries[key] = {'at': time.time(), 'limit': int(limit), 'engine': str(result.get('engine', ''))[:40],
                             'rows': [{name: str(row.get(name, ''))[:3000] for name in ('title', 'url', 'snippet')}
                                      for row in rows[:MAX_RESULTS] if isinstance(row, dict)]}
        if len(self.entries) > CACHE_ENTRIES:
            for old in sorted(self.entries, key=lambda item: self.entries[item]['at'])[:len(self.entries) - CACHE_ENTRIES]:
                self.entries.pop(old, None)
        self._save()

    def recent(self):
        now = time.time()
        self.requests = [at for at in self.requests if now - at < 3600]
        return len(self.requests)

    def spend(self):
        """Count one request to a search service, or refuse when the hour's allowance is used up."""
        if self.recent() >= self.hourly:
            wait = int((3600 - (time.time() - self.requests[0])) // 60) + 1
            raise SearchBudgetExceeded(
                f'This PC has sent {self.hourly} searches in the last hour, the most the application allows (so the search '
                f'services do not block it). New searches are possible in about {wait} minutes. Do not repeat the search now: '
                'use the results already returned, web_fetch with known URLs, or report that more searching is not possible')
        self.requests.append(time.time())
        self._save()
