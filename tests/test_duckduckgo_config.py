"""Keyless search settings and retired-credential handling, using synthetic data."""
import copy
import json

import pytest

from workbench.config import DEFAULT, DUCKDUCKGO_ENDPOINT, SEARCH_KEY_UNSUPPORTED, Settings, validate_settings
from workbench.engine import Engine
from workbench.redaction import RedactionCapacityError, SecretRedactor
from workbench.webtools import WebTools


OLD = 'SYNTHETIC-retired-search-value'
NEW = 'SYNTHETIC-new-retired-search-value'
MODEL = 'SYNTHETIC-provider-value'


def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.delenv('BRAVE_SEARCH_API_KEY', raising=False)
    settings = Settings(tmp_path)
    settings.value['providers'] = [settings.value['providers'][0]]
    settings.value['providers'][0].update(model='fixture', api_key_env='')
    return settings


def test_default_is_disabled_fixed_and_keyless():
    settings = validate_settings({})
    assert settings['search'] == DEFAULT['search']
    assert settings['search']['enabled'] is False
    assert settings['search']['provider'] == 'duckduckgo'
    assert settings['search']['endpoint'] == DUCKDUCKGO_ENDPOINT
    assert settings['search']['api_key_env'] == ''
    enabled = copy.deepcopy(DEFAULT)
    enabled['search']['enabled'] = True
    assert validate_settings(enabled)['search']['enabled'] is True
    assert validate_settings(enabled)['search']['endpoint'] == DUCKDUCKGO_ENDPOINT


@pytest.mark.parametrize('enabled', [False, True])
def test_brave_migrates_without_changing_policy_or_input(enabled):
    raw = {'search': {'provider': 'brave', 'enabled': enabled, 'endpoint': 'https://old.example/search',
                      'api_key_env': 'OLD_SEARCH_ENV', 'proxy_url': 'http://127.0.0.1:8080',
                      'timeout_seconds': 43, 'max_response_bytes': 32768}}
    before = copy.deepcopy(raw)
    result = validate_settings(raw)['search']
    assert raw == before
    assert result == {**raw['search'], 'provider': 'duckduckgo',
                      'endpoint': DUCKDUCKGO_ENDPOINT, 'api_key_env': ''}


@pytest.mark.parametrize('provider', ['searxng', 'brave'])
@pytest.mark.parametrize('endpoint', [{}, {'endpoint': ''}])
def test_disabled_unconfigured_legacy_search_uses_ddg(provider, endpoint):
    result = validate_settings({'search': {'provider': provider, 'enabled': False, **endpoint}})['search']
    assert result['provider'] == 'duckduckgo'
    assert result['endpoint'] == DUCKDUCKGO_ENDPOINT
    assert result['enabled'] is False and result['api_key_env'] == ''


@pytest.mark.parametrize('provider', ['searxng', 'brave'])
@pytest.mark.parametrize('endpoint', [{}, {'endpoint': ''}])
def test_enabled_legacy_search_with_missing_endpoint_stays_invalid(provider, endpoint):
    with pytest.raises(ValueError, match='endpoint'):
        validate_settings({'search': {'provider': provider, 'enabled': True, **endpoint}})


@pytest.mark.parametrize('enabled', [False, True])
def test_configured_searxng_keeps_destination_and_policy(enabled):
    raw = {'search': {'enabled': enabled, 'provider': 'searxng', 'endpoint': 'https://search.example.local/search',
                      'api_key_env': 'OLD_SEARCH_ENV', 'proxy_url': 'http://127.0.0.1:8181',
                      'timeout_seconds': 12, 'max_response_bytes': 131072}}
    result = validate_settings(raw)['search']
    assert result == {**raw['search'], 'api_key_env': ''}


@pytest.mark.parametrize('endpoint', [{}, {'endpoint': ''}, {'endpoint': DUCKDUCKGO_ENDPOINT},
                                      {'endpoint': DUCKDUCKGO_ENDPOINT.rstrip('/')}])
def test_ddg_requires_no_endpoint_input_and_normalizes_slash(endpoint):
    result = validate_settings({'search': {'provider': 'duckduckgo', 'enabled': True, **endpoint}})['search']
    assert result['endpoint'] == DUCKDUCKGO_ENDPOINT and result['enabled'] is True


@pytest.mark.parametrize('endpoint', ['https://other.example/html/', 'https://html.duckduckgo.com/other/',
                                      'https://html.duckduckgo.com/html/?key=private',
                                      'https://user:private@html.duckduckgo.com/html/',
                                      'http://html.duckduckgo.com/html/'])
def test_ddg_rejects_an_explicit_different_or_unsafe_endpoint(endpoint):
    with pytest.raises(ValueError):
        validate_settings({'search': {'provider': 'duckduckgo', 'endpoint': endpoint}})


@pytest.mark.parametrize('value', [None, 1, [], 'not an env name', 'ENV\nHEADER'])
def test_retired_search_env_field_still_validates_shape(value):
    with pytest.raises(ValueError, match='search api_key_env'):
        validate_settings({'search': {'provider': 'brave', 'endpoint': 'https://old.example/search', 'api_key_env': value}})


@pytest.mark.parametrize('change', [{'proxy_url': 'http://user:secret@proxy.example'}, {'timeout_seconds': 61},
                                    {'max_response_bytes': 0}, {'api_key': 'must-not-save'}])
def test_migration_does_not_hide_invalid_legacy_settings(change):
    with pytest.raises(ValueError):
        validate_settings({'search': {'provider': 'brave', 'endpoint': 'https://old.example/search', **change}})


@pytest.mark.parametrize('provider,endpoint', [('brave', 'https://old.example/search'), ('searxng', '')])
def test_load_migrates_in_memory_only_and_remembers_custom_redaction_env(tmp_path, monkeypatch, provider, endpoint):
    monkeypatch.delenv('BRAVE_SEARCH_API_KEY', raising=False)
    monkeypatch.setenv('RETIRED_SEARCH_ENV', OLD)
    raw = copy.deepcopy(DEFAULT)
    raw['providers'] = [raw['providers'][0]]
    raw['search'].update(provider=provider, enabled=False, endpoint=endpoint, api_key_env='RETIRED_SEARCH_ENV')
    original = json.dumps(raw, ensure_ascii=False, indent=4).encode('utf-8')
    path = tmp_path / 'settings.json'
    path.write_bytes(original)
    settings = Settings(tmp_path)
    engine = Engine(settings)
    assert settings.value['search']['provider'] == 'duckduckgo'
    assert settings.value['search']['api_key_env'] == ''
    assert settings.revision == 0 and path.read_bytes() == original
    assert engine.redact(OLD) == '[redacted]'
    monkeypatch.setenv('RETIRED_SEARCH_ENV', NEW)
    assert engine.redact(f'{OLD} {NEW}') == '[redacted] [redacted]'
    settings.secrets['search'] = OLD  # Synthetic retired memory, not accepted input.
    engine.set_secret('local', MODEL)
    public = settings.public()
    assert public['secret_status']['search'] is False and public['secret_status']['local'] is True
    assert settings.key(settings.value['providers'][0]) == MODEL
    serialized = json.dumps(public)
    assert all(secret not in serialized for secret in (OLD, NEW, MODEL))
    assert '_search_redaction_env_names' not in serialized
    engine.save_settings(copy.deepcopy(settings.value))
    assert settings.secrets == {'local': MODEL}
    assert engine.redact(f'{OLD} {NEW}') == '[redacted] [redacted]'
    persisted = path.read_text(encoding='utf-8')
    assert json.loads(persisted)['search']['provider'] == 'duckduckgo'
    assert all(secret not in persisted for secret in (OLD, NEW, MODEL, 'RETIRED_SEARCH_ENV'))
    assert settings.revision == 1


def test_nonempty_search_secret_rejected_without_mutation_but_clear_remembers_old(tmp_path, monkeypatch):
    settings = isolated_settings(tmp_path, monkeypatch)
    settings.secrets['search'] = OLD
    engine = Engine(settings)
    before = copy.deepcopy(settings.public())
    with pytest.raises(ValueError, match=SEARCH_KEY_UNSUPPORTED):
        engine.set_secret('search', NEW)
    assert settings.secrets == {'search': OLD} and settings.public() == before
    assert engine._redaction.value_count == 0
    engine.set_secret('search', '')
    assert not settings.secrets and settings.public()['secret_status']['search'] is False
    assert engine.redact(OLD) == '[redacted]'
    assert not settings.path.exists()


@pytest.mark.parametrize('failure', ['disk', 'capacity'])
def test_failed_save_does_not_commit_migration_masks_or_env_history(tmp_path, monkeypatch, failure):
    settings = isolated_settings(tmp_path, monkeypatch)
    settings.save(copy.deepcopy(settings.value))
    engine = Engine(settings)
    engine.set_secret('local', MODEL)
    before = settings.path.read_bytes(), copy.deepcopy(settings.public()), set(settings._search_redaction_env_names)
    raw = copy.deepcopy(settings.value)
    raw['search'].update(provider='brave', endpoint='https://old.example/search', api_key_env='RETIRED_SAVE_ENV')
    monkeypatch.setenv('RETIRED_SAVE_ENV', NEW)
    if failure == 'disk':
        def denied(*args):
            raise OSError('synthetic write denied')
        monkeypatch.setattr('workbench.config.os.replace', denied)
        error = OSError
    else:
        engine._redaction = SecretRedactor(max_values=1)
        engine._redaction.remember([MODEL])
        error = RedactionCapacityError
    with pytest.raises(error):
        engine.save_settings(raw)
    assert (settings.path.read_bytes(), settings.public(), settings._search_redaction_env_names) == before
    assert settings.secrets == {'local': MODEL}
    assert engine._redaction.redact(MODEL) == '[redacted]'
    assert engine._redaction.redact(NEW) == NEW
    assert not list(tmp_path.glob('settings-*.tmp'))


def test_successful_save_retains_new_legacy_env_only_for_redaction(tmp_path, monkeypatch):
    settings = isolated_settings(tmp_path, monkeypatch)
    engine = Engine(settings)
    monkeypatch.setenv('RETIRED_SAVE_ENV', NEW)
    raw = copy.deepcopy(settings.value)
    raw['search'].update(provider='brave', endpoint='https://old.example/search', api_key_env='RETIRED_SAVE_ENV')
    engine.save_settings(raw)
    assert engine.redact(NEW) == '[redacted]'
    monkeypatch.setenv('RETIRED_SAVE_ENV', OLD)
    assert engine.redact(f'{OLD} {NEW}') == '[redacted] [redacted]'
    assert settings.value['search']['api_key_env'] == ''
    assert 'RETIRED_SAVE_ENV' not in settings.path.read_text(encoding='utf-8')


def test_preflight_never_injects_retired_search_secrets_into_webtools(tmp_path, monkeypatch):
    settings = isolated_settings(tmp_path, monkeypatch)
    settings.value['search']['enabled'] = True
    settings.secrets['search'] = OLD
    monkeypatch.setenv('BRAVE_SEARCH_API_KEY', NEW)
    captured = []
    class CaptureWebTools(WebTools):
        def __init__(self, config):
            captured.append(copy.deepcopy(config))
            super().__init__(config)
        async def _request(self, *args, **kwargs):
            raise AssertionError('preflight attempted network')
    monkeypatch.setattr('workbench.engine.WebTools', CaptureWebTools)
    engine = Engine(settings)
    preview = engine.preflight({'task': 'Text only', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})
    assert preview['can_start'] and preview['web']['search_configured']
    assert preview['web']['search_endpoint'] == DUCKDUCKGO_ENDPOINT
    assert not preview['inference_tested'] and not preview['tools_tested']
    assert len(captured) == 1 and captured[0] == {'search': settings.value['search']}
    assert 'api_key' not in captured[0]['search']
    assert all(secret not in json.dumps(captured) for secret in (OLD, NEW))
    assert not engine.runs and not engine.agents and not settings.path.exists()
    assert engine.redact(f'{OLD} {NEW}') == '[redacted] [redacted]'
