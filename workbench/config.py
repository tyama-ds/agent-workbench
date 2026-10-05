"""Validated public settings and process-local secret references."""
from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .runtime_paths import RESOURCE_ROOT as ROOT
DEFAULT = json.loads((ROOT / 'docs' / 'interface.json').read_text(encoding='utf-8'))['config']
ID = re.compile(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}\Z')
ENV = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}\Z')
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
LAN = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7')]


def local_host(host):
    if host in LOOPBACK:
        return True
    try:
        address = ipaddress.ip_address(host)
        return any(address in network for network in LAN)
    except ValueError:
        return False


def number(value, label, low, high, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)) or not low <= value <= high:
        raise ValueError(f'{label}: {low}–{high} の範囲で指定してください')
    return value


def text(value, label, limit=4096, empty=True):
    if not isinstance(value, str) or len(value) > limit or '\0' in value or (not empty and not value.strip()):
        raise ValueError(f'{label}: 有効な文字列を指定してください')
    return value


def url(value, *, optional=False, proxy=False, local=False):
    if value == '' and optional:
        return value
    text(value, 'URL', 4096, False)
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError('URL は資格情報・クエリ・フラグメントを含まない HTTP(S) を指定してください')
    if proxy and parsed.path not in {'', '/'}:
        raise ValueError('Proxy は origin のみ指定してください')
    if any(ord(c) < 33 for c in value) or '\\' in value:
        raise ValueError('URL に空白・制御文字・バックスラッシュは使用できません')
    if local and not local_host(parsed.hostname):
        raise ValueError('Local API は loopback またはプライベート LAN の IP アドレスを指定してください')
    if not local and not proxy and parsed.scheme != 'https' and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('外部 API は HTTPS が必要です')
    if parsed.port is not None:
        number(parsed.port, 'port', 1, 65535, integer=True)
    return value.rstrip('/')


def validate_settings(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT):
        raise ValueError('設定形式が不正です')
    value = copy.deepcopy(DEFAULT)
    for key, supplied in raw.items():
        if isinstance(value.get(key), dict):
            if not isinstance(supplied, dict) or set(supplied) - set(value[key]):
                raise ValueError(f'{key}: 未対応の設定です')
            value[key].update(supplied)
        else:
            value[key] = supplied
    if value['version'] != 1:
        raise ValueError('設定バージョンが不正です')
    profiles = value['providers']
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 16:
        raise ValueError('API プロファイルは1–16個です')
    seen = set()
    allowed = set(DEFAULT['providers'][0])
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) - allowed:
            raise ValueError('プロファイルには公開設定のみ保存できます。API キーは環境変数またはメモリ欄を使ってください')
        if not isinstance(profile.get('id'), str) or not ID.fullmatch(profile['id']) or profile['id'] in seen:
            raise ValueError('プロファイル ID は重複しない英数字を指定してください')
        seen.add(profile['id'])
        if profile.get('kind') not in {'local', 'openai', 'anthropic'}:
            raise ValueError('provider kind が不正です')
        for key in ('label', 'model'):
            text(profile.get(key, ''), key, 200)
        profile['base_url'] = url(profile.get('base_url'), local=profile['kind'] == 'local')
        env = profile.setdefault('api_key_env', '')
        if not isinstance(env, str) or (env and not ENV.fullmatch(env)):
            raise ValueError('api_key_env が不正です')
        profile['proxy_url'] = url(profile.get('proxy_url', ''), optional=True, proxy=True)
        if profile['kind'] == 'local' and profile['proxy_url']:
            raise ValueError('Local API は proxy を使用しません')
        profile.setdefault('enabled', True)
        if type(profile['enabled']) is not bool:
            raise ValueError('enabled は bool です')
        number(profile.setdefault('request_timeout_seconds', 180), 'API timeout', 5, 1800)
    for name, roots in value['paths'].items():
        if not isinstance(roots, list) or len(roots) > 32:
            raise ValueError(f'{name}: フォルダーを32個以内で指定してください')
        cleaned = []
        for item in roots:
            text(item, name, 4096, False)
            path = Path(item)
            if not path.is_absolute() or not path.is_dir() or path == Path(path.anchor):
                raise ValueError(f'{name}: ドライブ全体ではなく既存の絶対フォルダーパスを指定してください')
            cleaned.append(str(path.absolute()))
        value['paths'][name] = list(dict.fromkeys(cleaned))
    search = value['search']
    if type(search['enabled']) is not bool or search['provider'] not in {'searxng', 'brave'}:
        raise ValueError('検索設定が不正です')
    search['endpoint'] = url(search['endpoint'], optional=True)
    search['proxy_url'] = url(search['proxy_url'], optional=True, proxy=True)
    if not isinstance(search['api_key_env'], str) or (search['api_key_env'] and not ENV.fullmatch(search['api_key_env'])):
        raise ValueError('search api_key_env が不正です')
    if search['enabled'] and not search['endpoint']:
        raise ValueError('検索 API endpoint を指定してください')
    number(search['timeout_seconds'], 'search timeout', 1, 60)
    number(search['max_response_bytes'], 'search response limit', 1024, 4 * 1024 * 1024, integer=True)
    local = value['local']
    for field in ('gpu_guard_enabled', 'gpu_guard_fail_closed'):
        if type(local[field]) is not bool:
            raise ValueError(f'{field}: bool が必要です')
    bounds = {'max_concurrent_requests': (1, 16), 'queue_timeout_seconds': (1, 3600),
              'request_timeout_seconds': (5, 1800), 'min_interval_seconds': (0, 120),
              'max_retries': (0, 3), 'retry_backoff_seconds': (0, 60), 'gpu_index': (0, 31),
              'max_vram_mb': (0, 1048576), 'max_gpu_utilization_percent': (0, 100),
              'gpu_wait_timeout_seconds': (1, 3600), 'gpu_poll_interval_seconds': (.1, 60)}
    for key, (low, high) in bounds.items():
        number(local[key], key, low, high, integer=key in {'max_concurrent_requests', 'max_retries', 'gpu_index', 'max_vram_mb'})
    if local['gpu_guard_enabled'] and any(p['enabled'] and p['kind'] == 'local' and urlsplit(p['base_url']).hostname not in LOOPBACK for p in profiles):
        raise ValueError('LAN の Local API では、このPCの GPU 監視を使用できません')
    limits = {'max_workers': (0, 16), 'max_auto_collaborations': (0, 1000), 'max_model_calls': (1, 1000), 'max_tool_calls': (1, 5000),
              'max_turns_per_agent': (1, 100), 'max_run_seconds': (10, 86400),
              'max_context_chars': (4000, 2000000), 'max_output_tokens': (128, 65536),
              'max_file_bytes': (1024, 50 * 1024 * 1024)}
    for key, (low, high) in limits.items():
        number(value['limits'][key], key, low, high, integer=True)
    text(value['system_policy'], 'system_policy', 16000, False)
    return value


class Settings:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'settings.json'
        if self.path.is_symlink() or (self.path.exists() and getattr(self.path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('設定ファイルにリンクは使用できません')
        self.value = validate_settings(json.loads(self.path.read_text(encoding='utf-8'))) if self.path.exists() else copy.deepcopy(DEFAULT)
        self.secrets: dict[str, str] = {}

    def key(self, profile):
        return self.secrets.get(profile['id']) or os.environ.get(profile.get('api_key_env', ''), '')

    def public(self):
        return {'config': copy.deepcopy(self.value),
                'secret_status': {p['id']: bool(self.key(p)) for p in self.value['providers']},
                'capabilities': {'office': ['docx', 'xlsx', 'pptx'], 'shell': False,
                    'gpu_hard_limit': False, 'gpu_admission_guard': True, 'state_persistence': False}}

    def save(self, raw):
        value = validate_settings(raw)
        handle, name = tempfile.mkstemp(prefix='settings-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
        self.value = value
        return self.public()
