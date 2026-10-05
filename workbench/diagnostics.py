"""Bounded, read-only model-list diagnostics, never inference or tool probes."""
from __future__ import annotations

import asyncio
import re
import ssl
from datetime import datetime, timezone

import aiohttp

from .config import url
from .providers import strict_json

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_MODELS = 200
MAX_MODEL_CHARS = 200
TIMEOUT_SECONDS = 15
_NEXT_LINK = re.compile(r'(?:^|[;,])\s*rel\s*=\s*(?:"[^"]*\bnext\b[^"]*"|next(?=[\s;,]|$))', re.I)

_ERRORS = {
    'unauthorized': 'モデル一覧 API が認証を拒否しました（HTTP 401）。API キーを確認してください。',
    'forbidden': 'モデル一覧 API へのアクセスが拒否されました（HTTP 403）。権限を確認してください。',
    'endpoint_unsupported': 'モデル一覧 API が見つからないか、この取得方法に対応していません。URL を確認してください。',
    'rate_limited': 'モデル一覧 API の利用制限に達しました（HTTP 429）。時間をおいて確認してください。',
    'server_error': 'モデル一覧 API がサーバーエラーを返しました。時間をおいて確認してください。',
    'redirect_blocked': 'モデル一覧 API がリダイレクトを返しました。転送せず停止しました。設定 URL を確認してください。',
    'http_error': 'モデル一覧 API が成功以外の HTTP ステータスを返しました。',
    'timeout': 'モデル一覧 API の確認がタイムアウトしました。接続先とネットワークを確認してください。',
    'tls_error': 'モデル一覧 API の TLS 接続に失敗しました。証明書と接続先を確認してください。',
    'connection_error': 'モデル一覧 API に接続できないか、応答の受信に失敗しました。URL・ネットワーク・proxy を確認してください。',
    'invalid_json': 'モデル一覧 API が有効な JSON を返しませんでした。',
    'invalid_schema': 'モデル一覧 API の応答形式に対応していません。',
    'response_too_large': 'モデル一覧 API の応答が 1 MiB の上限を超えたため、確認を停止しました。',
    'invalid_configuration': 'モデル一覧 API の設定が不正です。URL・認証・proxy の設定を確認してください。',
}


def _result(code: str, **values) -> dict:
    result = {
        'ok': code == 'models_listed',
        'code': code,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'models': [],
        'selected_model': 'unknown',
        'list_incomplete': False,
        'inference_tested': False,
        'tools_tested': False,
    }
    if not result['ok']:
        result['error'] = _ERRORS[code] + ' 推論・ツール実行は確認していません。'
    result.update(values)
    return result


def _http_failure(status: int) -> dict:
    code = {401: 'unauthorized', 403: 'forbidden', 404: 'endpoint_unsupported',
            405: 'endpoint_unsupported', 429: 'rate_limited'}.get(status)
    if code is None:
        code = ('redirect_blocked' if 300 <= status < 400 else
                'server_error' if 500 <= status < 600 else 'http_error')
    return _result(code, http_status=status)


def _has_more(data: dict) -> bool:
    """Recognize pagination indicators without following or exposing cursors."""
    more = False
    for field in ('has_more', 'hasMore'):
        if field in data:
            if not isinstance(data[field], bool):
                raise ValueError
            more |= data[field]
    for field in ('next', 'next_cursor', 'next_page', 'next_page_token', 'nextPageToken'):
        if field not in data or data[field] is None:
            continue
        value = data[field]
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError
        more |= bool(value)
    for field in ('pagination', 'links'):
        if field in data and data[field] is not None:
            if not isinstance(data[field], dict):
                raise ValueError
            # Do not recursively trust arbitrarily deep provider metadata.
            nested = data[field]
            if any(key in nested for key in ('pagination', 'links')):
                raise ValueError
            more |= _has_more(nested)
    return more


def _models(data, selected: str, key: str, paginated: bool = False) -> dict:
    if not isinstance(data, dict) or ('data' in data) == ('models' in data):
        raise ValueError
    entries = data['data'] if 'data' in data else data['models']
    if not isinstance(entries, list):
        raise ValueError
    incomplete = _has_more(data) or paginated or len(entries) > MAX_MODELS
    models = []
    observed = False
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError
        value = entry.get('id', entry.get('name'))
        if (not isinstance(value, str) or not value.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError
        value.encode('utf-8')  # Reject malformed Unicode, including lone surrogates.
        # Do not surface a credential even if a broken endpoint echoes it as an ID.
        if key and key in value:
            incomplete = True
            continue
        observed |= bool(selected) and value == selected
        incomplete |= len(value) > MAX_MODEL_CHARS
        if len(models) < MAX_MODELS:
            models.append(value[:MAX_MODEL_CHARS])
    state = 'observed' if observed else 'unknown' if incomplete or not selected else 'not_observed'
    return _result('models_listed', models=models, selected_model=state, list_incomplete=incomplete)


async def diagnose_provider(profile: dict, key: str) -> dict:
    """Fetch one bounded model-list response from an already saved profile.

    ``observed`` means an exact ID/name appeared in this response. Absence is
    ``unknown`` if pagination or output truncation limits the list; no result
    establishes model availability, inference success, or tool support.
    """
    try:
        if not isinstance(profile, dict) or profile.get('kind') not in {'local', 'openai', 'anthropic'}:
            raise ValueError
        if (not isinstance(key, str) or len(key) > 4096
                or any(ord(char) < 32 or ord(char) == 127 for char in key)):
            raise ValueError
        selected = profile.get('model', '')
        if not isinstance(selected, str):
            raise ValueError
        endpoint = url(profile.get('base_url'), local=profile['kind'] == 'local') + '/models'
        proxy = None
        if profile['kind'] != 'local' and profile.get('proxy_url'):
            proxy = url(profile['proxy_url'], proxy=True)
    except (ValueError, TypeError, AttributeError):
        return _result('invalid_configuration')

    headers = {}
    if profile['kind'] == 'anthropic':
        headers['anthropic-version'] = '2023-06-01'
        if key:
            headers['x-api-key'] = key
    elif key:
        headers['Authorization'] = 'Bearer ' + key
    try:
        async with aiohttp.ClientSession(trust_env=False,
                                         timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)) as session:
            async with session.get(endpoint, headers=headers, proxy=proxy, allow_redirects=False) as response:
                if response.status != 200:
                    return _http_failure(response.status)
                # A Link cursor is evidence of pagination, never a URL to visit.
                paginated = bool(_NEXT_LINK.search(response.headers.get('Link', '')))
                raw = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                        return _result('response_too_large', list_incomplete=True)
                    raw.extend(chunk)
        try:
            data = strict_json(raw)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return _result('invalid_json')
        try:
            return _models(data, selected, key, paginated)
        except (ValueError, TypeError, RecursionError):
            return _result('invalid_schema')
    except asyncio.TimeoutError:
        return _result('timeout')
    except (aiohttp.ClientSSLError, aiohttp.ServerFingerprintMismatch, ssl.SSLError):
        return _result('tls_error')
    except (aiohttp.InvalidURL, ValueError, UnicodeError):
        return _result('invalid_configuration')
    except (aiohttp.ClientError, OSError):
        return _result('connection_error')
