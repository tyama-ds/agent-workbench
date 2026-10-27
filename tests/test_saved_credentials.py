"""Opt-in credential persistence, entirely synthetic keys and temporary state."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from workbench import securestore
from workbench.config import Settings, DEFAULT
from workbench.engine import Engine, AdmissionError
from workbench.history import HistoryStore, HistoryError
from workbench.securestore import CredentialStore, CredentialStorageError, SavedCredentialIdentityChange
from test_engine import ScriptClient
from test_history_persistence import document, RUN
from test_config_server import serving, bootstrap
from workbench.server import APP_KEY

KEY = 'SYNTHETIC-saved-key-never-a-user-credential'
NEXT = 'SYNTHETIC-replacement-key-never-a-user-credential'


@pytest.fixture(autouse=True)
def synthetic_environment(monkeypatch):
    for profile in [*DEFAULT['providers'], DEFAULT['search']]:
        if profile.get('api_key_env'):
            monkeypatch.delenv(profile['api_key_env'], raising=False)
    monkeypatch.delenv('BRAVE_SEARCH_API_KEY', raising=False)


@pytest.fixture
def fake_crypto(monkeypatch):
    # Test transport only; real CurrentUser DPAPI has separate Windows tests.
    def transform(data, *, decrypt=False):
        if decrypt:
            assert data.startswith(b'SYNTHETIC:')
            return bytes(value ^ 0x5a for value in data[len(b'SYNTHETIC:'):])
        return b'SYNTHETIC:' + bytes(value ^ 0x5a for value in data)
    monkeypatch.setattr(securestore, '_supported', lambda: True)
    monkeypatch.setattr(securestore, '_dpapi', transform)
    return transform


def engine_at(path):
    return Engine(Settings(path), ScriptClient([]))


@pytest.mark.asyncio
async def test_saved_key_survives_restart_without_settings_or_archive_plaintext(tmp_path, fake_crypto):
    engine = engine_at(tmp_path)
    try:
        engine.history.save(document(text=KEY), lambda text: text)
        engine.set_secret('openai', KEY, 'saved')
        assert engine.settings.key(engine.settings.value['providers'][1]) == KEY
        assert engine.settings.secret_sources()['openai'] == {'source': 'saved', 'saved': True}
        assert KEY not in json.dumps(engine.public_config())
        assert KEY not in json.dumps(engine.settings.export())
        assert KEY.encode() not in engine.credentials.path.read_bytes()
        assert KEY.encode() not in engine.history.path.read_bytes()
        assert engine.history.read(RUN)[0]['agents'][0]['logs'][0]['text'] == '[redacted]'
    finally:
        await engine.close()
    restored = engine_at(tmp_path)
    try:
        profile = next(p for p in restored.settings.value['providers'] if p['id'] == 'openai')
        assert restored.settings.key(profile) == KEY
        assert restored.settings.secrets == {}
        assert restored.settings.secret_sources()['openai']['source'] == 'saved'
        assert restored.redact(KEY) == '[redacted]'
        assert len(restored._archives) == 1
        assert restored.client.calls == [] and restored.runs == {}
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_session_switch_removes_saved_and_never_resurrects_on_restart(tmp_path, fake_crypto, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'SYNTHETIC-env')
    engine = engine_at(tmp_path)
    try:
        engine.set_secret('openai', KEY, 'saved')
        engine.set_secret('openai', NEXT)  # Existing API defaults to session.
        assert engine.settings.secret_sources()['openai'] == {'source': 'session', 'saved': False}
        assert not engine.credentials.contains('openai')
        assert engine.redact(KEY + NEXT) == '[redacted][redacted]'
    finally:
        await engine.close()
    restored = engine_at(tmp_path)
    try:
        assert restored.settings.secret_sources()['openai'] == {'source': 'environment', 'saved': False}
    finally:
        await restored.close()


@pytest.mark.parametrize('storage', ['session', 'saved'])
@pytest.mark.asyncio
async def test_clear_removes_every_direct_key_and_preserves_environment(tmp_path, fake_crypto, monkeypatch, storage):
    monkeypatch.setenv('OPENAI_API_KEY', 'SYNTHETIC-env')
    engine = engine_at(tmp_path)
    try:
        engine.set_secret('openai', KEY, 'saved')
        engine.set_secret('openai', '', storage)
        assert engine.settings.secret_sources()['openai'] == {'source': 'environment', 'saved': False}
        assert 'openai' not in engine.settings.secrets
        assert not engine.credentials.contains('openai')
    finally:
        await engine.close()


@pytest.mark.parametrize('target', ['save', 'session', 'clear'])
@pytest.mark.asyncio
async def test_ciphertext_replace_failure_preserves_active_source_and_old_bytes(tmp_path, fake_crypto, monkeypatch, target):
    engine = engine_at(tmp_path)
    try:
        engine.set_secret('openai', KEY, 'saved')
        original = engine.credentials.path.read_bytes()
        def fail(*args):
            raise OSError('SYNTHETIC disk failure')
        monkeypatch.setattr(securestore.os, 'replace', fail)
        with pytest.raises(CredentialStorageError):
            engine.set_secret('openai', '' if target == 'clear' else NEXT, 'session' if target == 'session' else 'saved')
        assert engine.credentials.path.read_bytes() == original
        assert engine.settings.secret_sources()['openai'] == {'source': 'saved', 'saved': True}
        assert engine.credentials.values() == [KEY]
        assert engine.settings.secrets == {}
        assert not list(tmp_path.glob('.credentials-*.tmp'))
        if target != 'clear':
            assert engine.redact(NEXT) == '[redacted]'
    finally:
        await engine.close()


@pytest.mark.parametrize('field,value', [('id', 'renamed'), ('kind', 'anthropic'),
                                        ('base_url', 'https://other.example/v1'), ('api_key_env', 'OTHER_KEY'), ('delete', None)])
@pytest.mark.asyncio
async def test_saved_identity_change_rejected_before_settings_or_masks_change(tmp_path, fake_crypto, field, value):
    engine = engine_at(tmp_path)
    try:
        engine.set_secret('openai', KEY, 'saved')
        raw = copy.deepcopy(engine.settings.value)
        profile = next(p for p in raw['providers'] if p['id'] == 'openai')
        if field == 'delete':
            raw['providers'].remove(profile)
        else:
            profile[field] = value
        old = copy.deepcopy(engine.settings.value)
        disk = engine.credentials.path.read_bytes()
        with pytest.raises(SavedCredentialIdentityChange) as error:
            engine.save_settings(raw)
        assert error.value.affected_ids == ['openai']
        assert engine.settings.value == old and engine.settings.revision == 0
        assert engine.credentials.path.read_bytes() == disk
        assert not engine.settings.path.exists()
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_labels_models_and_nonidentity_settings_remain_editable(tmp_path, fake_crypto):
    engine = engine_at(tmp_path)
    try:
        engine.set_secret('openai', KEY, 'saved')
        raw = copy.deepcopy(engine.settings.value)
        profile = next(p for p in raw['providers'] if p['id'] == 'openai')
        profile.update(label='New label', model='new-model')
        engine.save_settings(raw)
        assert engine.settings.secret_sources()['openai']['source'] == 'saved'
        assert engine.settings.key(profile) == KEY
        assert KEY not in engine.settings.path.read_text(encoding='utf-8')
    finally:
        await engine.close()


@pytest.mark.parametrize('orphan', [False, True])
@pytest.mark.asyncio
async def test_observed_startup_binding_mismatch_blocks_work_and_allows_explicit_clear(tmp_path, fake_crypto, orphan):
    first = engine_at(tmp_path)
    first.set_secret('openai', KEY, 'saved')
    first.history.save(document(), first._redaction.redact)
    await first.close()
    raw = copy.deepcopy(DEFAULT)
    if orphan:
        raw['providers'] = [p for p in raw['providers'] if p['id'] != 'openai']
    else:
        next(p for p in raw['providers'] if p['id'] == 'openai')['base_url'] = 'https://changed.example/v1'
    (tmp_path / 'settings.json').write_text(json.dumps(raw), encoding='utf-8')
    engine = engine_at(tmp_path)
    try:
        before = engine.credentials.path.read_bytes()
        assert engine.credentials.public()['status'] == 'identity_mismatch'
        assert engine.credentials.public()['affected_ids'] == ['openai']
        assert engine._archives == {} and engine.snapshot()['runs'] == []
        assert engine.redact(KEY) == '[redacted]'
        with pytest.raises(AdmissionError, match='API'):
            engine._prepare_run({})
        with pytest.raises(CredentialStorageError):
            engine.set_secret('local', NEXT, 'session')
        assert engine.credentials.path.read_bytes() == before
        engine.set_secret('openai', '', 'session')
        assert engine.credentials.public()['status'] == 'ready'
        assert not engine.credentials.contains('openai')
        assert len(engine._archives) == 1 and engine.client.calls == []
    finally:
        await engine.close()


@pytest.mark.parametrize('payload', [b'not-json', b'{"version":2}', b'{"version":1,"version":1}',
                                   b'{"version":1,"protection":"windows-dpapi-current-user","ciphertext":"!"}'])
@pytest.mark.asyncio
async def test_unreadable_vault_preserved_no_environment_fallback_or_archive_exposure(tmp_path, fake_crypto, monkeypatch, payload):
    monkeypatch.setenv('OPENAI_API_KEY', 'SYNTHETIC-env')
    vault = tmp_path / 'credentials.dpapi'
    vault.write_bytes(payload)
    engine = engine_at(tmp_path)
    try:
        public = engine.public_config()
        assert public['credential_storage']['status'] == 'unavailable'
        assert public['credential_storage']['affected_ids'] == []
        assert public['secret_sources']['openai']['source'] == 'none'
        assert engine.snapshot()['runs'] == []
        with pytest.raises(CredentialStorageError):
            engine.settings.key(next(p for p in engine.settings.value['providers'] if p['id'] == 'openai'))
        for operation in (lambda: engine.set_secret('openai', '', 'saved'), lambda: engine.save_settings(DEFAULT)):
            with pytest.raises(CredentialStorageError):
                operation()
        assert vault.read_bytes() == payload and engine.client.calls == []
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_second_instance_cannot_load_or_mutate_credentials(tmp_path, fake_crypto):
    owner = engine_at(tmp_path)
    owner.set_secret('openai', KEY, 'saved')
    second = engine_at(tmp_path)
    try:
        assert second.credentials.values() == []
        assert second.credentials.public()['status'] == 'unavailable'
        with pytest.raises(HistoryError):
            second.set_secret('openai', NEXT, 'saved')
        assert owner.credentials.values() == [KEY]
    finally:
        await second.close()
        await owner.close()


@pytest.mark.asyncio
async def test_cached_archived_board_cannot_escape_newly_detected_binding_failure(tmp_path, fake_crypto):
    first = engine_at(tmp_path)
    first.set_secret('openai', KEY, 'saved')
    first.history.save(document(), first._redaction.redact)
    await first.close()
    engine = engine_at(tmp_path)
    try:
        assert RUN in engine._archives
        next(p for p in engine.settings.value['providers'] if p['id'] == 'openai')['base_url'] = 'https://changed.example/v1'
        with pytest.raises(CredentialStorageError):
            engine.read_work_board(RUN)
        assert engine.snapshot()['runs'] == []
    finally:
        await engine.close()


@pytest.mark.parametrize('invalid', [{'version': 2, 'entries': []}, {'version': True, 'entries': []},
                                    {'version': 1, 'entries': [{'id': 'openai'}]},
                                    {'version': 1, 'entries': [], 'unknown': 'field'}])
def test_decrypted_schema_failure_keeps_original_ciphertext(tmp_path, fake_crypto, invalid):
    envelope = {'version': 1, 'protection': securestore.PROTECTION,
                'ciphertext': base64.b64encode(fake_crypto(json.dumps(invalid).encode())).decode()}
    path = tmp_path / 'credentials.dpapi'
    original = json.dumps(envelope).encode()
    path.write_bytes(original)
    history = HistoryStore(tmp_path)
    try:
        store = CredentialStore(tmp_path, DEFAULT['providers'], lease=history._lease)
        assert store.public()['status'] == 'unavailable'
        with pytest.raises(CredentialStorageError):
            store.replace('openai', '')
        assert path.read_bytes() == original
    finally:
        history.close()


def test_hardlinked_vault_is_rejected_without_touching_either_name(tmp_path, fake_crypto):
    original = tmp_path / 'other'
    original.write_bytes(b'SYNTHETIC')
    os.link(original, tmp_path / 'credentials.dpapi')
    history = HistoryStore(tmp_path)
    try:
        store = CredentialStore(tmp_path, DEFAULT['providers'], lease=history._lease)
        assert store.error and store.values() == []
        assert original.read_bytes() == (tmp_path / 'credentials.dpapi').read_bytes() == b'SYNTHETIC'
    finally:
        history.close()


@pytest.mark.asyncio
async def test_failed_history_scrub_prevents_vault_and_active_key_change(tmp_path, fake_crypto, monkeypatch):
    from workbench.history import HistoryError
    engine = engine_at(tmp_path)
    try:
        engine.set_secret('openai', KEY, 'saved')
        original = engine.credentials.path.read_bytes()
        def fail(*args):
            raise HistoryError('SYNTHETIC scrub failure')
        monkeypatch.setattr(engine.history, 'scrub', fail)
        with pytest.raises(HistoryError):
            engine.set_secret('openai', NEXT, 'saved')
        assert engine.credentials.path.read_bytes() == original
        assert engine.credentials.values() == [KEY] and engine.settings.secrets == {}
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_unsupported_absent_vault_keeps_session_and_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(securestore, '_supported', lambda: False)
    engine = engine_at(tmp_path)
    try:
        assert engine.credentials.public()['status'] == 'unsupported'
        engine.set_secret('openai', KEY)
        assert engine.settings.secret_sources()['openai']['source'] == 'session'
        with pytest.raises(CredentialStorageError):
            engine.set_secret('openai', NEXT, 'saved')
        assert engine.settings.secrets['openai'] == KEY
        assert not engine.credentials.path.exists()
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_atomic_temp_is_ciphertext_only_and_external_change_not_overwritten(tmp_path, fake_crypto, monkeypatch):
    engine = engine_at(tmp_path)
    try:
        replace = securestore.os.replace
        observations = []
        def inspect(source, target):
            payload = Path(source).read_bytes()
            assert KEY.encode() not in payload
            observations.append(payload)
            return replace(source, target)
        monkeypatch.setattr(securestore.os, 'replace', inspect)
        engine.set_secret('openai', KEY, 'saved')
        assert len(observations) == 1
        engine.credentials.path.write_bytes(b'external-change')
        with pytest.raises(CredentialStorageError):
            engine.set_secret('openai', NEXT, 'saved')
        assert engine.credentials.path.read_bytes() == b'external-change'
        assert engine.credentials.values() == [KEY]
    finally:
        await engine.close()


@pytest.mark.parametrize('bad', [None, [], 'persistent', True, 1])
@pytest.mark.asyncio
async def test_invalid_storage_rejected_without_changes(tmp_path, fake_crypto, bad):
    engine = engine_at(tmp_path)
    try:
        with pytest.raises(ValueError):
            engine.set_secret('openai', KEY, bad)
        assert engine.settings.secrets == {} and not engine.credentials.path.exists()
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_api_receipts_storage_modes_and_identity_conflict(tmp_path, fake_crypto):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        headers = {'Origin': auth.origin}
        payload = {'id': 'openai', 'key': KEY, 'storage': 'saved', 'config_revision': 0}
        response = await client.post(auth.origin + '/api/secrets', json=payload, headers=headers)
        assert response.status == 200
        receipt = await response.json()
        assert (receipt['source'], receipt['saved'], receipt['configured'], receipt['storage']) == ('saved', True, True, 'saved')
        assert KEY not in json.dumps(receipt)
        raw = copy.deepcopy(engine.settings.value)
        next(p for p in raw['providers'] if p['id'] == 'openai')['api_key_env'] = 'DIFFERENT_ENV'
        response = await client.put(auth.origin + '/api/config', json={'config_revision': 0, 'config': raw}, headers=headers)
        assert response.status == 409
        assert (await response.json())['code'] == 'saved_credential_identity_change'
        payload.update(key='', storage='session')
        response = await client.post(auth.origin + '/api/secrets', json=payload, headers=headers)
        receipt = await response.json()
        assert response.status == 200
        assert (receipt['source'], receipt['saved'], receipt['configured']) == ('none', False, False)


@pytest.mark.skipif(os.name != 'nt', reason='Windows CurrentUser DPAPI')
@pytest.mark.parametrize('plaintext', [b'SYNTHETIC-real-DPAPI-only', 'SYNTHETIC-日本語-key'.encode('utf-8')])
def test_actual_windows_dpapi_current_user_roundtrip_and_tamper(plaintext):
    encrypted = securestore._dpapi(plaintext)
    assert encrypted != plaintext and plaintext not in encrypted
    assert securestore._dpapi(encrypted, decrypt=True) == plaintext
    changed = bytearray(encrypted)
    changed[-1] ^= 1
    with pytest.raises(CredentialStorageError):
        securestore._dpapi(bytes(changed), decrypt=True)


@pytest.mark.skipif(os.name != 'nt', reason='Windows CurrentUser DPAPI')
@pytest.mark.asyncio
async def test_actual_windows_vault_restart_uses_only_temporary_state(tmp_path):
    first = engine_at(tmp_path)
    first.set_secret('openai', KEY, 'saved')
    encrypted = first.credentials.path.read_bytes()
    await first.close()
    second = engine_at(tmp_path)
    try:
        assert second.credentials.values() == [KEY]
        assert second.credentials.path.read_bytes() == encrypted
        assert KEY.encode() not in encrypted
        second.set_secret('openai', '', 'saved')
        assert second.credentials.values() == []
    finally:
        await second.close()
