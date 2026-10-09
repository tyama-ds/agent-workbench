"""Only synthetic credentials; no live providers or external requests."""
import asyncio
import copy
import json
import threading

import pytest

from test_engine import ScriptClient, configured, reply, settled, start
from test_config_server import serving, bootstrap
from workbench.config import Settings, validate_settings
from workbench.engine import Engine
from workbench.redaction import SecretRedactor, RedactionCapacityError, REDACTION_CAPACITY_MESSAGE
from workbench.server import APP_KEY
from test_frontend import APP, run_javascript
from test_compact_frontend import DOM


OLD = 'SYNTHETIC-lifecycle-old-credential'
NEW = 'SYNTHETIC-lifecycle-new-credential'


def isolate(engine):
    """Never consult the test operator's credential environment."""
    engine.settings.value['providers'] = [engine.settings.value['providers'][0]]
    engine.settings.value['providers'][0].update(api_key_env='', model='fixture')
    engine.settings.value['search']['api_key_env'] = ''


def assert_masked(engine, run, agent, *values):
    states = [engine.snapshot(), engine.selected_snapshot(),
              engine.selected_snapshot(run_id=run['id'], agent_id=agent.id)]
    for state in states:
        encoded = json.dumps(state)
        assert all(value not in encoded for value in values)
        assert '_redaction' not in encoded and 'conversation' not in encoded
    return states


def test_literal_longest_first_single_pass_and_utf8_capacity():
    redactor = SecretRedactor(max_values=5, max_bytes=100)
    redactor.remember(['token', 'token-long', 'a.*[b]', '鍵', 'redacted'])
    assert redactor.redact('token-long token a.*[b] 鍵 redacted') == ' '.join(['[redacted]'] * 5)
    assert redactor.redact('TOKEN aZZb') == 'TOKEN aZZb'
    assert redactor.value_count == 5
    assert redactor.byte_count == sum(len(value.encode('utf-8')) for value in ['token', 'token-long', 'a.*[b]', '鍵', 'redacted'])
    with pytest.raises(RedactionCapacityError):
        redactor.remember(['extra'])
    assert redactor.value_count == 5 and redactor.redact('token-long') == '[redacted]'
    tiny = SecretRedactor(max_bytes=3)
    prepared = tiny.prepare(['鍵'])
    assert tiny.value_count == 0
    tiny.commit(prepared)
    with pytest.raises(RedactionCapacityError):
        tiny.remember(['a'])
    assert tiny.byte_count == 3 and tiny.redact('鍵') == '[redacted]'


def test_adversarial_shared_prefix_and_overlapping_literal_matching():
    redactor = SecretRedactor()
    redactor.remember(['a' * 4092 + format(i, '04x') for i in range(511)] + ['b' * 4096])
    assert redactor.byte_count == 2 * 1024 * 1024
    assert redactor.redact('a' * 24000) == 'a' * 24000
    assert redactor.redact('b' * 4096) == '[redacted]'
    overlap = SecretRedactor()
    overlap.remember(['a' * i for i in range(1, 513)])
    assert overlap.redact('a' * 24000) == '[redacted]' * 47


@pytest.mark.parametrize('transition', ['replace', 'clear', 'env_reference', 'remove_profile'])
async def test_retained_metadata_and_captured_outputs_survive_transition(tmp_path, monkeypatch, transition):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.kick = lambda agent: None
    if transition in {'env_reference', 'remove_profile'}:
        monkeypatch.setenv('LIFECYCLE_TEST_KEY', OLD)
        engine.settings.value['providers'][0]['api_key_env'] = 'LIFECYCLE_TEST_KEY'
    else:
        engine.set_secret('local', OLD)
    try:
        run, pm = await start(engine, task='Task ' + OLD)
        response = await engine.execute_tool(run, pm, 'spawn_worker', {
            'role': 'Role ' + OLD, 'task': 'Assignment ' + OLD, 'profile_id': 'local'})
        worker = engine.agents[response['agent_id']]
        await engine.execute_tool(run, worker, 'ask_user', {'question': 'Question ' + OLD})
        engine._mail(worker, pm, 'Message ' + OLD)
        engine.log(worker, 'assistant', OLD, thinking=OLD)
        engine.record_result(worker, 'assistant_response', OLD)
        engine.record_receipt(worker, 'write_text', {'path': '/synthetic/' + OLD, 'bytes': 1,
                                                    'sha256': 'a' * 64, 'operation': 'created'})
        assert_masked(engine, run, worker, OLD)
        if transition in {'replace', 'clear'}:
            engine.set_secret('local', NEW if transition == 'replace' else '')
        else:
            config = copy.deepcopy(engine.settings.value)
            if transition == 'env_reference':
                config['providers'][0]['api_key_env'] = ''
            else:
                config['providers'][0]['id'] = 'replacement'
                config['providers'][0]['api_key_env'] = ''
            engine.save_settings(config)
            monkeypatch.delenv('LIFECYCLE_TEST_KEY')
        assert_masked(engine, run, worker, OLD)
        assert pm.assignment == 'Task ' + OLD  # Private protocol/source is not rewritten.
        assert worker.question == 'Question ' + OLD
        assert all(OLD not in json.dumps(value) for value in [list(worker.logs), list(worker.results), list(worker.output_receipts)])
    finally:
        await engine.close()


@pytest.mark.parametrize('failure', [False, True])
async def test_late_response_or_error_after_active_rotation(tmp_path, failure):
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []
    async def delayed(profile, messages):
        seen.append(profile['api_key']); entered.set(); await release.wait()
        if failure:
            raise ValueError('Late error ' + OLD)
        value = reply('Late response ' + OLD); value.thinking = OLD
        return value
    engine, _ = configured(tmp_path, ScriptClient([delayed])); isolate(engine)
    engine.set_secret('local', OLD)
    try:
        run, pm = await start(engine)
        await entered.wait(); engine.set_secret('local', NEW); release.set(); await settled(engine)
        assert seen == [OLD] and engine.settings.key(engine.settings.value['providers'][0]) == NEW
        assert_masked(engine, run, pm, OLD, NEW)
        if failure:
            assert pm.last_error == 'Late error [redacted]'
        else:
            assert pm.results[-1]['text'] == 'Late response [redacted]'
            assert pm.logs[-1]['thinking'] == '[redacted]'
    finally:
        release.set(); await engine.close()


async def test_completed_continuation_uses_new_key_but_masks_old_private_history(tmp_path):
    seen = []
    async def echo(profile, messages):
        seen.append(profile['api_key'])
        return reply(messages[0]['content'])
    engine, _ = configured(tmp_path, ScriptClient([echo, echo])); isolate(engine)
    engine.set_secret('local', OLD)
    try:
        run, pm = await start(engine, task='Private original ' + OLD); await settled(engine)
        engine.set_secret('local', NEW)
        assert engine.message_eligibility(pm)['allowed']
        await engine.human_message(pm.id, 'Continue'); await settled(engine)
        assert seen == [OLD, NEW]
        assert pm.conversation[0]['content'] == 'Private original ' + OLD
        assert all(result['text'] == 'Private original [redacted]' for result in pm.results)
        assert_masked(engine, run, pm, OLD, NEW)
    finally:
        await engine.close()


async def test_delayed_committed_receipt_after_key_rotation(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.kick = lambda agent: None; engine.set_secret('local', OLD)
    run, pm = await start(engine)
    entered, release = threading.Event(), threading.Event()
    original = run['_executor']._execute
    def delayed(name, args):
        entered.set(); assert release.wait(5); return original(name, args)
    run['_executor']._execute = delayed
    operation = asyncio.create_task(engine.execute_tool(run, pm, 'write_text', {
        'path': str(work / (OLD + '.txt')), 'text': 'Synthetic content unchanged', 'expected_sha256': 'missing'}))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        engine.set_secret('local', NEW); release.set(); await operation
        assert pm.output_receipts[-1]['path'].endswith('[redacted].txt')
        assert (work / (OLD + '.txt')).read_text(encoding='utf-8') == 'Synthetic content unchanged'
        assert_masked(engine, run, pm, OLD, NEW)
    finally:
        release.set(); await engine.close()


async def test_new_search_dispatch_uses_current_key_and_keeps_inflight_headers(tmp_path, monkeypatch):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.kick = lambda agent: None
    engine.settings.value['search'].update(enabled=True, provider='brave',
        endpoint='https://api.search.brave.com/res/v1/web/search')
    engine.set_secret('search', OLD)
    run, pm = await start(engine)
    assert run['_web'].api_key == ''
    entered, release = asyncio.Event(), asyncio.Event(); seen = []
    async def fake_request(self, url, **kwargs):
        seen.append(kwargs['headers']['X-Subscription-Token'])
        if len(seen) == 1:
            entered.set(); await release.wait()
        return b'{"web":{"results":[]}}', 'application/json', url
    monkeypatch.setattr(type(run['_web']), '_request', fake_request)
    first = asyncio.create_task(engine.execute_tool(run, pm, 'web_search', {'query': 'one'}))
    try:
        await entered.wait(); engine.set_secret('search', NEW)
        await engine.execute_tool(run, pm, 'web_search', {'query': 'two'})
        release.set(); await first
        assert seen == [OLD, NEW]
        engine.set_secret('search', '')
        with pytest.raises(ValueError, match='runtime API key'):
            await engine.execute_tool(run, pm, 'web_search', {'query': 'three'})
        assert seen == [OLD, NEW]
    finally:
        release.set(); await engine.close()


async def test_new_key_masks_already_retained_data_then_survives_removal(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task=NEW)
        engine.log(pm, 'assistant', NEW)
        engine.record_result(pm, 'assistant_response', NEW)
        assert NEW in json.dumps(engine.snapshot())
        engine.set_secret('local', NEW)
        assert_masked(engine, run, pm, NEW)
        engine.set_secret('local', '')
        assert_masked(engine, run, pm, NEW)
        assert pm.results[-1]['text'] == NEW  # Only the public projection changes.
    finally:
        await engine.close()


async def test_search_uses_current_env_and_saturation_blocks_dispatch(tmp_path, monkeypatch):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.kick = lambda agent: None
    monkeypatch.setenv('LIFECYCLE_SEARCH_OLD', OLD); monkeypatch.setenv('LIFECYCLE_SEARCH_NEW', NEW)
    engine.settings.value['search'].update(enabled=True, provider='brave', api_key_env='LIFECYCLE_SEARCH_OLD',
        endpoint='https://api.search.brave.com/res/v1/web/search', proxy_url='')
    run, pm = await start(engine); seen = []
    async def fake_request(self, url, **kwargs):
        seen.append((self.endpoint, self.proxy, kwargs['headers']['X-Subscription-Token']))
        return b'{"web":{"results":[]}}', 'application/json', url
    monkeypatch.setattr(type(run['_web']), '_request', fake_request)
    try:
        engine.settings.value['search'].update(api_key_env='LIFECYCLE_SEARCH_NEW', endpoint='https://unused.example', proxy_url='http://unused.example')
        await engine.execute_tool(run, pm, 'web_search', {'query': 'synthetic'})
        assert seen == [('https://api.search.brave.com/res/v1/web/search', None, NEW)]
        engine._redaction = SecretRedactor(max_values=1); engine._redaction.remember([NEW])
        engine.settings.secrets['unexpected'] = OLD
        with pytest.raises(RedactionCapacityError):
            await engine.execute_tool(run, pm, 'web_search', {'query': 'blocked'})
        assert len(seen) == 1
    finally:
        engine.settings.secrets.pop('unexpected', None); await engine.close()


@pytest.mark.parametrize('change', ['remove_reuse', 'endpoint', 'kind', 'env_reference'])
async def test_changed_provider_identity_does_not_inherit_memory_auth(tmp_path, change):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.set_secret('local', OLD)
    initial = copy.deepcopy(engine.settings.value)
    replacement = copy.deepcopy(initial)
    if change == 'remove_reuse':
        replacement['providers'][0]['id'] = 'different'
        engine.save_settings(replacement)
        replacement = initial
    elif change == 'endpoint':
        replacement['providers'][0]['base_url'] = 'http://127.0.0.1:9999/v1'
    elif change == 'kind':
        replacement['providers'][0]['kind'] = 'openai'
    else:
        replacement['providers'][0]['api_key_env'] = 'LIFECYCLE_ABSENT_TEST_ENV'
    engine.save_settings(replacement)
    assert 'local' not in engine.settings.secrets
    assert engine.settings.key(engine.settings.value['providers'][0]) == ''
    assert engine.redact(OLD) == '[redacted]'
    assert OLD not in engine.settings.path.read_text(encoding='utf-8')
    await engine.close()


def test_model_label_edit_retains_auth_and_search_namespace_is_reserved(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.set_secret('local', OLD)
    changed = copy.deepcopy(engine.settings.value)
    changed['providers'][0].update(model='new-model', label='New label')
    engine.save_settings(changed)
    assert engine.settings.key(changed['providers'][0]) == OLD
    changed['providers'][0]['id'] = 'search'
    with pytest.raises(ValueError, match='予約'):
        validate_settings(changed)


def test_previously_saved_reserved_id_has_explicit_startup_migration_error(tmp_path):
    settings = Settings(tmp_path)
    value = copy.deepcopy(settings.value)
    value['providers'][0]['id'] = 'search'
    settings.path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='search.*予約.*別の ID'):
        Settings(tmp_path)
    assert json.loads(settings.path.read_text(encoding='utf-8'))['providers'][0]['id'] == 'search'


def test_frontend_refreshes_credential_status_without_rebuilding_settings():
    result = run_javascript(DOM + APP + r'''
const labels=[new Node('p'),new Node('p')],ids=['local','renamed'];
const cards=ids.map((id,index)=>({querySelector:selector=>selector==='[data-key="id"]'?{value:id}:labels[index]}));
$('profilesEditor').querySelectorAll=()=>cards;
refreshSecretStatus({local:true,renamed:false,search:true});
assert(labels[0].textContent.includes('キー設定あり'));assert(labels[1].textContent.includes('キー未設定'));
assert($('searchSecretStatus').textContent.includes('キー設定あり'));
refreshSecretStatus({local:false,renamed:false,search:false});
assert(labels.every(label=>label.textContent.includes('キー未設定')));
assert($('searchSecretStatus').textContent.includes('キー未設定'));
console.log(JSON.stringify({ok:true}));
''')
    assert result['ok']
    assert 'refreshSecretStatus(response.secret_status)' in APP


def test_search_auth_status_tracks_identity_change(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.set_secret('search', OLD)
    assert engine.settings.public()['secret_status']['search']
    changed = copy.deepcopy(engine.settings.value)
    changed['search']['endpoint'] = 'https://different.example/search'
    response = engine.save_settings(changed)
    assert not response['secret_status']['search'] and 'search' not in engine.settings.secrets
    assert engine.redact(OLD) == '[redacted]'


def test_capacity_rejection_is_atomic_for_key_config_and_failed_disk_write(tmp_path, monkeypatch):
    engine, _ = configured(tmp_path, ScriptClient([])); isolate(engine)
    engine.save_settings(engine.settings.value)
    engine._redaction = SecretRedactor(max_values=1)
    engine.set_secret('local', OLD)
    before = engine.settings.path.read_bytes()
    with pytest.raises(RedactionCapacityError):
        engine.set_secret('local', NEW)
    assert engine.settings.secrets == {'local': OLD}
    monkeypatch.setenv('LIFECYCLE_NEW_ENV', NEW)
    changed = copy.deepcopy(engine.settings.value)
    changed['providers'][0]['api_key_env'] = 'LIFECYCLE_NEW_ENV'
    with pytest.raises(RedactionCapacityError):
        engine.save_settings(changed)
    assert engine.settings.path.read_bytes() == before
    assert engine.settings.value['providers'][0]['api_key_env'] == ''
    assert engine._redaction.value_count == 1 and engine.redact(OLD) == '[redacted]'
    engine._redaction = SecretRedactor()
    engine._redaction.remember([OLD])
    def fail(raw):
        raise OSError('Synthetic disk failure')
    monkeypatch.setattr(engine.settings, 'save', fail)
    with pytest.raises(OSError):
        engine.save_settings(changed)
    assert engine._redaction.value_count == 1 and engine.settings.secrets == {'local': OLD}


async def test_unexpected_saturation_blocks_snapshot_dispatch_and_error_fallback(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(profile, messages):
        entered.set(); await release.wait(); raise ValueError('Unsafe exception ' + OLD + NEW)
    engine, _ = configured(tmp_path, ScriptClient([delayed])); isolate(engine)
    engine._redaction = SecretRedactor(max_values=1); engine.set_secret('local', OLD)
    try:
        run, pm = await start(engine); await entered.wait()
        engine.settings.secrets['unexpected'] = NEW  # Bypass the supported atomic setter deliberately.
        for projection in (engine.snapshot, engine.selected_snapshot):
            with pytest.raises(RedactionCapacityError):
                projection()
        release.set(); await settled(engine)
        assert pm.status == 'error' and pm.last_error == REDACTION_CAPACITY_MESSAGE
        assert pm.task.exception() is None
        assert all(NEW not in log['text'] for log in pm.logs)
        with pytest.raises(RedactionCapacityError):
            await start(engine)
        assert len(engine.client.calls) == 1
    finally:
        release.set(); await engine.close()


async def test_http_transition_state_errors_and_capacity_fail_closed(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client); headers = {'Origin': auth.origin}
        engine = app[APP_KEY]; isolate(engine)
        engine.client = ScriptClient([reply('Response ' + OLD)])
        response = await client.post(auth.origin + '/api/secrets', json={'config_revision': app[APP_KEY].settings.revision, 'id': 'local', 'key': OLD}, headers=headers)
        assert response.status == 200
        response = await client.post(auth.origin + '/api/runs', json={'task': 'Task ' + OLD,
            'pm_profile': 'local', 'max_workers': 0}, headers=headers)
        assert response.status == 200
        await settled(engine)
        response = await client.post(auth.origin + '/api/secrets', json={'config_revision': app[APP_KEY].settings.revision, 'id': 'local', 'key': NEW}, headers=headers)
        assert response.status == 200
        for path in ('/api/state', '/api/state?view=selected'):
            response = await client.get(auth.origin + path)
            assert response.status == 200 and OLD not in await response.text()
        engine.settings.value['providers'][0].update(label='Label ' + OLD, model='')
        response = await client.post(auth.origin + '/api/runs', json={'task': 'Task', 'pm_profile': 'local'}, headers=headers)
        assert response.status == 400 and OLD not in await response.text()
        engine._redaction = SecretRedactor(max_values=1); engine._redaction.remember([NEW])
        response = await client.post(auth.origin + '/api/secrets', json={'config_revision': app[APP_KEY].settings.revision, 'id': 'local', 'key': OLD}, headers=headers)
        assert response.status == 409
        assert await response.json() == {'ok': False, 'error': REDACTION_CAPACITY_MESSAGE, 'code': 'redaction_capacity'}
        assert engine.settings.secrets['local'] == NEW
        engine.settings.secrets['unexpected'] = OLD
        response = await client.get(auth.origin + '/api/state')
        assert response.status == 409 and (await response.json())['code'] == 'redaction_capacity'
        # Clean-up must not retry a failed redactor through stop events.
        engine.settings.secrets.pop('unexpected')


async def test_delayed_diagnostic_masks_old_key_and_capacity_blocks_new_probe(tmp_path, monkeypatch):
    import workbench.diagnostics as diagnostics
    entered, release = asyncio.Event(), asyncio.Event(); seen = []
    async def fake(profile, key):
        seen.append(key); entered.set(); await release.wait()
        return {'ok': True, 'models': ['model-' + key]}
    monkeypatch.setattr(diagnostics, 'diagnose_provider', fake)
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client); headers = {'Origin': auth.origin}
        engine = app[APP_KEY]; isolate(engine); engine.set_secret('local', OLD)
        task = asyncio.create_task(client.post(auth.origin + '/api/provider-test', json={'provider_id': 'local'}, headers=headers))
        try:
            await entered.wait()
            response = await client.post(auth.origin + '/api/secrets', json={'config_revision': app[APP_KEY].settings.revision, 'id': 'local', 'key': NEW}, headers=headers)
            assert response.status == 200
            release.set(); response = await task
            assert response.status == 200 and (await response.json())['models'] == ['model-[redacted]']
            assert seen == [OLD]
            engine._redaction = SecretRedactor(max_values=1); engine._redaction.remember([NEW])
            engine.settings.secrets['unexpected'] = OLD
            response = await client.post(auth.origin + '/api/provider-test', json={'provider_id': 'local'}, headers=headers)
            assert response.status == 409 and seen == [OLD]
        finally:
            release.set(); engine.settings.secrets.pop('unexpected', None)
