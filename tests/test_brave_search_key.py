"""Phase 9: Brave Search as the optional engine that uses the human's own key.

The default stays the keyless DuckDuckGo. The key lives in the session or the
encrypted store (never in settings, history, or the environment) and has one
fixed destination. Synthetic keys and temporary state only.
"""
import copy
import json

import pytest

from workbench import securestore
from workbench.config import BRAVE_ENDPOINT, DEFAULT, DUCKDUCKGO_ENDPOINT, SEARCH_KEY_UNSUPPORTED, Settings, validate_settings
from workbench.engine import Engine
from workbench.securestore import SEARCH_BINDING, CredentialStorageError
from test_engine import ScriptClient
from test_saved_credentials import fake_crypto, synthetic_environment  # noqa: F401  (fixtures)

KEY = 'SYNTHETIC-brave-key-never-a-user-credential'
NEXT = 'SYNTHETIC-brave-replacement-never-a-user-credential'


def engine_at(path):
    settings = Settings(path)
    settings.value['providers'][0]['model'] = 'fixture'
    return Engine(settings, ScriptClient([]))


def choose_brave(engine, enabled=True):
    raw = copy.deepcopy(engine.settings.value)
    raw['search'].update(provider='brave', endpoint=BRAVE_ENDPOINT, enabled=enabled)
    engine.save_settings(raw)


def test_the_default_stays_keyless_duckduckgo_and_brave_is_an_explicit_choice():
    assert DEFAULT['search']['provider'] == 'duckduckgo' and validate_settings({})['search']['endpoint'] == DUCKDUCKGO_ENDPOINT
    for endpoint in (BRAVE_ENDPOINT, BRAVE_ENDPOINT + '/'):
        chosen = validate_settings({'search': {'provider': 'brave', 'endpoint': endpoint, 'enabled': True,
                                               'api_key_env': 'BRAVE_SEARCH_API_KEY'}})['search']
        assert chosen['provider'] == 'brave' and chosen['endpoint'] == BRAVE_ENDPOINT
        assert chosen['api_key_env'] == ''  # never an environment variable
    # A retired configuration (another endpoint) is still migrated to DuckDuckGo.
    retired = validate_settings({'search': {'provider': 'brave', 'endpoint': 'https://old.example/search'}})['search']
    assert retired['provider'] == 'duckduckgo' and retired['endpoint'] == DUCKDUCKGO_ENDPOINT
    with pytest.raises(ValueError):
        validate_settings({'search': {'provider': 'brave', 'endpoint': BRAVE_ENDPOINT, 'api_key': KEY}})
    assert SEARCH_BINDING['base_url'] == BRAVE_ENDPOINT


@pytest.mark.asyncio
async def test_a_session_key_is_accepted_only_while_brave_is_selected(tmp_path, monkeypatch):
    monkeypatch.setenv('BRAVE_SEARCH_API_KEY', 'SYNTHETIC-environment-value')
    engine = engine_at(tmp_path)
    try:
        with pytest.raises(ValueError, match=SEARCH_KEY_UNSUPPORTED):
            engine.set_secret('search', KEY)
        assert engine.settings.search_key() == '' and engine.settings.secret_sources()['search'] == {'source': 'none', 'saved': False}
        choose_brave(engine)
        assert engine.settings.search_key() == ''  # the environment is never read
        preview = engine.preflight({'task': 'Text only', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})
        assert preview['can_start'] and preview['web']['search_key_missing'] is True and preview['web']['search_provider'] == 'brave'
        assert any(row['code'] == 'search_key_missing' for row in preview['warnings'])
        engine.set_secret('search', KEY)
        assert engine.settings.search_key() == KEY
        assert engine.settings.secret_sources()['search'] == {'source': 'session', 'saved': False}
        public = engine.public_config()
        assert public['secret_status']['search'] is True and KEY not in json.dumps(public)
        assert KEY not in json.dumps(engine.settings.export()) and KEY not in engine.settings.path.read_text(encoding='utf-8')
        assert engine.redact(f'token {KEY}') == 'token [redacted]'
        preview = engine.preflight({'task': 'Text only', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})
        assert 'search_key_missing' not in preview['web'] and KEY not in json.dumps(preview)
        assert preview['web']['search_endpoint'] == BRAVE_ENDPOINT
        # The run's tools read the key when a search is sent; the run's configuration never holds it.
        prepared = engine._prepare_run({'task': 'Text only', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})
        assert prepared[-1].search_key_set() and KEY not in json.dumps(prepared[1])
        # Saving other settings keeps the session key; choosing another engine stops using it.
        raw = copy.deepcopy(engine.settings.value)
        raw['search']['timeout_seconds'] = 12
        engine.save_settings(raw)
        assert engine.settings.search_key() == KEY
        raw['search'].update(provider='duckduckgo', endpoint=DUCKDUCKGO_ENDPOINT)
        engine.save_settings(raw)
        assert engine.settings.search_key() == '' and 'search' not in engine.settings.secrets
        assert engine.settings.secret_sources()['search'] == {'source': 'none', 'saved': False}
        assert engine.redact(KEY) == '[redacted]'  # a key once entered stays masked
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_saved_key_is_encrypted_bound_to_brave_and_survives_restart(tmp_path, fake_crypto):
    engine = engine_at(tmp_path)
    try:
        choose_brave(engine)
        engine.set_secret('search', KEY, 'saved')
        assert engine.settings.search_key() == KEY
        assert engine.settings.secret_sources()['search'] == {'source': 'saved', 'saved': True}
        assert KEY.encode() not in engine.credentials.path.read_bytes()
        assert KEY not in engine.settings.path.read_text(encoding='utf-8')
        assert engine.credentials.public()['status'] == 'ready' and not engine.credentials.affected_ids
        # Saving unrelated settings does not disturb the binding.
        raw = copy.deepcopy(engine.settings.value)
        raw['limits']['max_run_seconds'] = raw['limits']['max_run_seconds']
        engine.save_settings(raw)
    finally:
        await engine.close()
    engine = engine_at(tmp_path)
    try:
        assert engine.settings.value['search']['provider'] == 'brave' and engine.settings.search_key() == KEY
        assert engine.redact(KEY) == '[redacted]'
        engine.set_secret('search', NEXT)  # a session key replaces the saved one
        assert engine.settings.search_key() == NEXT and not engine.credentials.contains('search')
        engine.set_secret('search', '')
        assert engine.settings.search_key() == '' and engine.settings.secret_sources()['search'] == {'source': 'none', 'saved': False}
    finally:
        await engine.close()


def test_the_store_accepts_a_search_entry_only_with_its_fixed_binding():
    row = {**SEARCH_BINDING, 'key': KEY}
    assert securestore._validate({'version': 1, 'entries': [row]}) == {'search': row}
    for change in ({'base_url': 'https://elsewhere.example/search'}, {'kind': 'openai'}, {'api_key_env': 'BRAVE_SEARCH_API_KEY'},
                   {'id': 'other'}):
        with pytest.raises(CredentialStorageError):
            securestore._validate({'version': 1, 'entries': [{**row, **change}]})
