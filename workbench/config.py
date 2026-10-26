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
COPILOT_PROFILE_ID = 'copilot-agent'
ORCHESTRATION_DEFAULTS = {'delegation_level': 1, 'workers_per_pm': 2}
DUCKDUCKGO_ENDPOINT = 'https://html.duckduckgo.com/html/'
SEARCH_KEY_UNSUPPORTED = 'Web 検索は API キー不要です。検索キーは保存できません。'


def effective_profiles(config):
    """Add the opt-in bridge without rewriting the user's saved profiles."""
    profiles = copy.deepcopy(config['providers'])
    bridge = config.get('copilot_agent', {})
    if bridge.get('enabled') is True:
        profiles.insert(0, {'id': COPILOT_PROFILE_ID, 'label': 'Copilot Agent', 'kind': 'local',
            '_copilot_agent': True,
            '_copilot_max_concurrent_requests': bridge.get('max_concurrent_requests', 1),
            'base_url': bridge['base_url'], 'model': bridge['model'], 'api_key_env': '',
            'proxy_url': '', 'enabled': True, 'request_timeout_seconds': config['local']['request_timeout_seconds'],
            'context_window_tokens': 0})
    return profiles


def effective_config(config):
    value = copy.deepcopy(config)
    value['providers'] = effective_profiles(config)
    return value


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


def _path_kind(path, *, directory=False, check_paths=True):
    # Import/startup recovery may retain a missing path, but never accept an
    # existing path of the wrong kind. Saving always uses check_paths=True.
    if '\0' in str(path):
        return False
    if not check_paths and not path.exists():
        return True
    return path.is_dir() if directory else path.is_file()


def validate_settings(raw, *, check_paths=True):
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
    if type(value['version']) is not int or value['version'] != 1:
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
        if profile['id'] == 'search':
            raise ValueError('プロファイル ID search は検索用に予約されています。別の ID を指定してください')
        if profile['id'] == COPILOT_PROFILE_ID and value['copilot_agent']['enabled'] is True:
            raise ValueError('オンの間はプロファイル ID copilot-agent が専用モードに予約されます。既存プロファイルの ID を変更してください')
        seen.add(profile['id'])
        if profile.get('kind') not in {'local', 'openai', 'anthropic'}:
            raise ValueError('provider kind が不正です')
        for key in ('label', 'model'):
            text(profile.setdefault(key, ''), key, 200)
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
        number(profile.setdefault('context_window_tokens', 0), 'context_window_tokens', 0, 2000000, integer=True)
    bridge = value['copilot_agent']
    if type(bridge['enabled']) is not bool:
        raise ValueError('copilot_agent.enabled: bool が必要です')
    bridge['base_url'] = url(bridge['base_url'], local=True)
    endpoint = urlsplit(bridge['base_url'])
    if (endpoint.scheme != 'http' or endpoint.hostname not in {'127.0.0.1', 'localhost'}
            or endpoint.path != '/v1' or endpoint.port is None):
        raise ValueError('copilot-agent: 接続先は http://127.0.0.1:ポート/v1 を指定してください')
    text(bridge['model'], 'copilot_agent.model', 200, False)
    for field in ('model', 'bridge_directory', 'python_executable', 'base_url'):
        supplied = text(bridge[field], f'copilot_agent.{field}', 4096)
        if any(ord(c) < 32 or ord(c) == 127 for c in supplied):
            raise ValueError(f'copilot_agent.{field}: 制御文字は使用できません')
    number(bridge['startup_timeout_seconds'], 'copilot_agent.startup_timeout_seconds', 5, 1200, integer=True)
    number(bridge.get('max_concurrent_requests', 1), 'copilot_agent.max_concurrent_requests', 1, 16, integer=True)
    for field in ('bridge_directory', 'python_executable'):
        supplied = text(bridge[field], f'copilot_agent.{field}', 4096)
        if supplied:
            path = Path(supplied)
            valid = (_path_kind(path, directory=True, check_paths=check_paths)
                     and _path_kind(path / 'server.py', check_paths=check_paths) if field == 'bridge_directory' else
                     _path_kind(path, check_paths=check_paths) and path.name.casefold() in {'python.exe', 'pythonw.exe', 'python', 'python3'})
            if not path.is_absolute() or not valid:
                raise ValueError(f'copilot_agent.{field}: 既存の bridge フォルダー / Python の絶対パスを指定してください')
            bridge[field] = str(path.absolute())
    for name, roots in value['paths'].items():
        if not isinstance(roots, list) or len(roots) > 32:
            raise ValueError(f'{name}: フォルダーを32個以内で指定してください')
        cleaned = []
        for item in roots:
            text(item, name, 4096, False)
            path = Path(item)
            if not path.is_absolute() or not _path_kind(path, directory=True, check_paths=check_paths) or path == Path(path.anchor):
                raise ValueError(f'{name}: ドライブ全体ではなく既存の絶対フォルダーパスを指定してください')
            cleaned.append(str(path.absolute()))
        value['paths'][name] = list(dict.fromkeys(cleaned))
    python = value['python']
    for key in ('enabled', 'network_enabled'):
        if type(python[key]) is not bool:
            raise ValueError(f'python.{key}: bool が必要です')
    executable = text(python['executable'], 'python.executable', 4096)
    if executable:
        path = Path(executable)
        if not path.is_absolute() or not _path_kind(path, check_paths=check_paths) or path.name.casefold() != 'python.exe':
            raise ValueError('python.executable: インストール済みの python.exe の絶対パスを指定してください')
        python['executable'] = str(path.absolute())
    elif python['enabled']:
        raise ValueError('Pythonを有効にするには既存の python.exe を指定してください')
    libraries = python['library_paths']
    if not isinstance(libraries, list) or len(libraries) > 16:
        raise ValueError('python.library_paths: フォルダーを16個以内で指定してください')
    cleaned = []
    for item in libraries:
        path = Path(text(item, 'python.library_paths', 4096, False))
        if not path.is_absolute() or not _path_kind(path, directory=True, check_paths=check_paths) or path == Path(path.anchor):
            raise ValueError('python.library_paths: 既存ライブラリの絶対フォルダーパスを指定してください')
        cleaned.append(str(path.absolute()))
    python['library_paths'] = list(dict.fromkeys(cleaned))
    for key, (low, high) in {'timeout_seconds': (1, 600), 'max_memory_mb': (128, 8192),
                            'max_output_bytes': (1024, 1048576)}.items():
        number(python[key], f'python.{key}', low, high, integer=True)
    selenium = value['selenium']
    if type(selenium['enabled']) is not bool or selenium['browser'] not in ('edge', 'chrome'):
        raise ValueError('Selenium の有効設定は bool、browser は edge / chrome です')
    expected = {'edge': ('msedge.exe', 'msedgedriver.exe'), 'chrome': ('chrome.exe', 'chromedriver.exe')}
    for key, filename in zip(('browser_executable', 'driver_executable'), expected[selenium['browser']]):
        supplied = text(selenium[key], f'selenium.{key}', 4096)
        if supplied:
            path = Path(supplied)
            if not path.is_absolute() or not _path_kind(path, check_paths=check_paths) or path.name.casefold() != filename:
                raise ValueError(f'selenium.{key}: 既存の {filename} の絶対パスを指定してください')
            selenium[key] = str(path.absolute())
        elif selenium['enabled']:
            raise ValueError(f'Seleniumを有効にするには既存の {filename} を指定してください')
    if selenium['enabled'] and (not python['executable'] or not python['network_enabled']):
        raise ValueError('Seleniumには既存の python.exe と「Python のネット接続を許可」が必要です')
    libraries = selenium['library_paths']
    if not isinstance(libraries, list) or len(libraries) > 16:
        raise ValueError('selenium.library_paths: フォルダーを16個以内で指定してください')
    cleaned = []
    for item in libraries:
        path = Path(text(item, 'selenium.library_paths', 4096, False))
        if not path.is_absolute() or not _path_kind(path, directory=True, check_paths=check_paths) or path == Path(path.anchor):
            raise ValueError('selenium.library_paths: 既存ライブラリの絶対フォルダーパスを指定してください')
        cleaned.append(str(path.absolute()))
    selenium['library_paths'] = list(dict.fromkeys(cleaned))
    selenium['proxy_url'] = url(selenium['proxy_url'], optional=True, proxy=True)
    for key, (low, high) in {'timeout_seconds': (10, 300), 'max_memory_mb': (256, 8192),
                            'max_output_chars': (1000, 100000)}.items():
        number(selenium[key], f'selenium.{key}', low, high, integer=True)
    search = value['search']
    if type(search['enabled']) is not bool or search['provider'] not in {'duckduckgo', 'searxng', 'brave'}:
        raise ValueError('検索設定が不正です')
    # An old provider without an endpoint must not inherit the new DDG URL.
    if search['provider'] in {'searxng', 'brave'} and 'endpoint' not in raw.get('search', {}):
        search['endpoint'] = ''
    search['endpoint'] = url(search['endpoint'], optional=True)
    if search['provider'] == 'duckduckgo' and not search['endpoint']:
        search['endpoint'] = DUCKDUCKGO_ENDPOINT.rstrip('/')
    search['proxy_url'] = url(search['proxy_url'], optional=True, proxy=True)
    if not isinstance(search['api_key_env'], str) or (search['api_key_env'] and not ENV.fullmatch(search['api_key_env'])):
        raise ValueError('search api_key_env が不正です')
    if search['enabled'] and not search['endpoint']:
        raise ValueError('検索 API endpoint を指定してください')
    number(search['timeout_seconds'], 'search timeout', 1, 60)
    number(search['max_response_bytes'], 'search response limit', 1024, 4 * 1024 * 1024, integer=True)
    if search['provider'] == 'brave' or (search['provider'] == 'searxng' and not search['endpoint']):
        search.update(provider='duckduckgo', endpoint=DUCKDUCKGO_ENDPOINT)
    elif search['provider'] == 'duckduckgo':
        if search['endpoint'] != DUCKDUCKGO_ENDPOINT.rstrip('/'):
            raise ValueError('DuckDuckGo の接続先は固定です')
        search['endpoint'] = DUCKDUCKGO_ENDPOINT
    # Kept as an empty compatibility field; search never consumes credentials.
    search['api_key_env'] = ''
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
              'max_file_bytes': (1024, 50 * 1024 * 1024),
              'context_trigger_percent': (50, 90), 'context_recent_groups': (2, 32),
              'context_summary_chars': (512, 16000), 'context_reserve_tokens': (256, 65536),
              'max_history_chars': (4000, 4000000)}
    for key, (low, high) in limits.items():
        number(value['limits'][key], key, low, high, integer=True)
    if type(value['limits']['auto_compact']) is not bool:
        raise ValueError('auto_compact: bool が必要です')
    for profile in profiles:
        window = profile['context_window_tokens']
        if window and window <= value['limits']['max_output_tokens'] + value['limits']['context_reserve_tokens']:
            raise ValueError('モデルの文脈予算は出力上限と余白の合計より大きく指定してください')
    text(value['system_policy'], 'system_policy', 16000, False)
    orchestration = value.setdefault('orchestration', copy.deepcopy(ORCHESTRATION_DEFAULTS))
    number(orchestration['delegation_level'], 'orchestration.delegation_level', 0, 2, integer=True)
    number(orchestration['workers_per_pm'], 'orchestration.workers_per_pm', 1, 16, integer=True)
    if type(value['work_board']['enabled']) is not bool:
        raise ValueError('work_board.enabled: bool が必要です')
    return value


def missing_settings_paths(value):
    """Return field-only warnings for an already structurally validated config."""
    paths = [(f'paths.{name}[{index}]', root)
             for name, roots in value['paths'].items() for index, root in enumerate(roots)]
    for section, fields in {'python': ('executable',),
                            'selenium': ('browser_executable', 'driver_executable'),
                            'copilot_agent': ('python_executable', 'bridge_directory')}.items():
        paths.extend((f'{section}.{field}', value[section][field]) for field in fields)
    for section in ('python', 'selenium'):
        paths.extend((f'{section}.library_paths[{index}]', root)
                     for index, root in enumerate(value[section]['library_paths']))
    missing = [field for field, supplied in paths if supplied and not Path(supplied).exists()]
    bridge = value['copilot_agent']['bridge_directory']
    if bridge and Path(bridge).exists() and not (Path(bridge) / 'server.py').exists():
        missing.append('copilot_agent.bridge_directory (server.py)')
    return [f'{field}: パスが存在しません。現在のPCの場所を確認して保存してください。' for field in missing]


def preview_settings_import(backup):
    """Validate a public backup without changing settings, secrets or services."""
    if not isinstance(backup, dict):
        raise ValueError('設定バックアップの形式が不正です')
    if set(backup) & {'format', 'format_version', 'config'}:
        if (set(backup) != {'format', 'format_version', 'config'}
                or backup['format'] != 'agent-workbench-settings'
                or type(backup['format_version']) is not int or backup['format_version'] != 1):
            raise ValueError('設定バックアップの形式・バージョンが未対応です')
        backup = backup['config']
    config = validate_settings(backup, check_paths=False)
    return config, missing_settings_paths(config)


class Settings:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'settings.json'
        if self.path.is_symlink() or (self.path.exists() and getattr(self.path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('設定ファイルにリンクは使用できません')
        raw = json.loads(self.path.read_text(encoding='utf-8-sig')) if self.path.exists() else copy.deepcopy(DEFAULT)
        self.value = validate_settings(raw, check_paths=False)
        # Keep obsolete installation paths visible for repair without rewriting
        # the original file or enabling work until a strict save succeeds.
        self.restore_warnings = missing_settings_paths(self.value)
        # Retired search environment names are process-local redaction inputs
        # only. Neither their values nor this metadata enter public/disk config.
        self._search_redaction_env_names = {'BRAVE_SEARCH_API_KEY'}
        old_env = raw.get('search', {}).get('api_key_env', '')
        if old_env:
            self._search_redaction_env_names.add(old_env)
        self.secrets: dict[str, str] = {}
        # Process-local ownership for browser config/credential writes. It is not part
        # of persisted settings or a retained run's configuration/eligibility.
        self.revision = 0

    def key(self, profile):
        return self.secrets.get(profile['id']) or os.environ.get(profile.get('api_key_env', ''), '')

    def public(self):
        return {'config': copy.deepcopy(self.value), 'config_revision': self.revision,
                'settings_storage': {'path': str(self.path.absolute()), 'warnings': list(self.restore_warnings)},
                'secret_status': {p['id']: bool(self.key(p)) for p in self.value['providers']} |
                    {'search': False},
                'capabilities': {'office': ['docx', 'xlsx', 'pptx'], 'shell': False,
                    'python_isolation': 'windows_lpac' if os.name == 'nt' else None,
                    'python_enabled': self.value['python']['enabled'],
                    'selenium_available': os.name == 'nt',
                    'selenium_isolation': 'windows_job_normal_user' if os.name == 'nt' else None,
                    'gpu_hard_limit': False, 'gpu_admission_guard': True, 'state_persistence': False}}

    def export(self):
        return {'format': 'agent-workbench-settings', 'format_version': 1, 'config': copy.deepcopy(self.value)}

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
        self.restore_warnings = []
        old_env = raw.get('search', {}).get('api_key_env', '')
        if old_env:
            self._search_redaction_env_names.add(old_env)
        self.revision += 1
        return self.public()
