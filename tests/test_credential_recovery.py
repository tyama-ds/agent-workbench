"""Saved-destination credential writes and recovery; synthetic values only."""
import asyncio
import copy
import json

import pytest

from test_config_server import serving, bootstrap
from test_engine import ScriptClient, reply, settled
from workbench.server import APP_KEY
from workbench.redaction import SecretRedactor, RedactionCapacityError

OLD = 'SYNTHETIC-recovery-old'
NEW = 'SYNTHETIC-recovery-new'


async def setup(auth, app, client):
    await bootstrap(auth, client)
    headers = {'Origin': auth.origin}
    engine = app[APP_KEY]
    config = copy.deepcopy(engine.settings.value)
    config['providers'] = [dict(config['providers'][0], id='model', kind='openai', model='fixture',
                                base_url='https://saved.example/v1', api_key_env='', proxy_url='')]
    config['search'].update(provider='brave', endpoint='https://saved.example/search', api_key_env='', enabled=False)
    response = await client.put(auth.origin + '/api/config', json=config, headers=headers)
    assert response.status == 200
    return engine, config, headers, (await response.json())['config_revision']


async def set_key(client, auth, headers, revision, ident='model', key=NEW):
    return await client.post(auth.origin + '/api/secrets',
                             json={'id': ident, 'key': key, 'config_revision': revision}, headers=headers)


@pytest.mark.parametrize('revision', [None, True, False, -1, '1', 1.0, [], {}])
async def test_invalid_revision_never_mutates_secret_or_masks(tmp_path, revision):
    async with serving(tmp_path) as (auth, app, client):
        engine, _, headers, _ = await setup(auth, app, client)
        before = (dict(engine.settings.secrets), engine._redaction.value_count)
        response = await set_key(client, auth, headers, revision)
        assert response.status == 409
        assert (await response.json())['code'] == 'settings_changed'
        assert (engine.settings.secrets, engine._redaction.value_count) == before
        assert NEW not in await response.text()
        response = await client.post(auth.origin + '/api/secrets', json={'id': 'model', 'key': NEW}, headers=headers)
        assert response.status == 409  # No unguarded legacy path.


@pytest.mark.parametrize('change', ['endpoint', 'proxy', 'kind', 'env', 'id_reuse', 'aba', 'label'])
async def test_stale_saved_target_rejected_before_mutation(tmp_path, change):
    async with serving(tmp_path) as (auth, app, client):
        engine, config, headers, revision = await setup(auth, app, client)
        assert (await set_key(client, auth, headers, revision, key=OLD)).status == 200
        changed = copy.deepcopy(config)
        fields = {'endpoint': ('base_url', 'https://new.example/v1'), 'proxy': ('proxy_url', 'http://127.0.0.1:7777'),
                  'kind': ('kind', 'anthropic'), 'env': ('api_key_env', 'SYNTHETIC_ABSENT_KEY'),
                  'label': ('label', 'New label')}
        if change in fields:
            key, value = fields[change]
            changed['providers'][0][key] = value
        else:
            changed['providers'][0]['id' if change == 'id_reuse' else 'base_url'] = 'other' if change == 'id_reuse' else 'https://new.example/v1'
        assert (await client.put(auth.origin + '/api/config', json=changed, headers=headers)).status == 200
        if change in {'id_reuse', 'aba'}:
            assert (await client.put(auth.origin + '/api/config', json=config, headers=headers)).status == 200
        before = (dict(engine.settings.secrets), engine._redaction.value_count, engine.settings.path.read_bytes())
        for key in [NEW, '']:
            response = await set_key(client, auth, headers, revision, key=key)
            assert response.status == 409
            assert (engine.settings.secrets, engine._redaction.value_count, engine.settings.path.read_bytes()) == before
        assert engine.settings.revision > revision
        assert (await set_key(client, auth, headers, engine.settings.revision)).status == 200


async def test_revision_is_checked_after_request_body_arrives(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        engine, config, headers, revision = await setup(auth, app, client)
        entered, release = asyncio.Event(), asyncio.Event()
        async def chunks():
            yield b'{'
            entered.set()
            await release.wait()
            yield json.dumps({'id': 'model', 'key': NEW, 'config_revision': revision}).encode()[1:]
        pending = asyncio.create_task(client.post(auth.origin + '/api/secrets', data=chunks(),
                                      headers={**headers, 'Content-Type': 'application/json'}))
        await entered.wait()
        config['providers'][0]['base_url'] = 'https://new.example/v1'
        assert (await client.put(auth.origin + '/api/config', json=config, headers=headers)).status == 200
        release.set()
        response = await pending
        assert response.status == 409
        assert engine.settings.secrets == {} and engine._redaction.value_count == 0


async def test_search_destination_and_provider_namespaces_are_separate(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        engine, config, headers, revision = await setup(auth, app, client)
        assert (await set_key(client, auth, headers, revision, key=OLD)).status == 200
        response = await set_key(client, auth, headers, revision, ident='search')
        assert await response.json() == {'ok': True, 'id': 'search', 'config_revision': revision, 'configured': True}
        assert engine.settings.secrets == {'model': OLD, 'search': NEW}
        for provider, endpoint in [('searxng', 'https://saved.example/search'), ('brave', '')]:
            config['search'].update(provider=provider, endpoint=endpoint)
            saved = await client.put(auth.origin + '/api/config', json=config, headers=headers)
            revision = (await saved.json())['config_revision']
            response = await set_key(client, auth, headers, revision, ident='search')
            assert response.status == 400 and NEW not in await response.text()
            assert engine.settings.secrets == {'model': OLD}
        assert OLD not in engine.settings.path.read_text(encoding='utf-8')
        assert NEW not in engine.settings.path.read_text(encoding='utf-8')


async def test_real_api_recovery_requires_explicit_message_without_reset(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        engine, config, headers, revision = await setup(auth, app, client)
        original = engine.settings.path.read_bytes()
        seen = []
        async def authenticate(profile, messages):
            seen.append((profile['base_url'], profile['api_key']))
            if profile['api_key'] != NEW:
                raise ValueError('Synthetic authentication error ' + OLD)
            return reply('Recovered without losing the original task')
        engine.client = ScriptClient([authenticate, authenticate])
        assert (await set_key(client, auth, headers, revision, key=OLD)).status == 200
        response = await client.post(auth.origin + '/api/runs', json={'task': 'Synthetic recovery', 'pm_profile': 'model',
                                     'worker_profiles': [], 'max_workers': 0}, headers=headers)
        run = engine.runs[(await response.json())['run']['id']]
        agent = engine.agents[run['agent_ids'][0]]
        await settled(engine)
        assert (run['status'], agent.status) == ('waiting', 'error')
        assert engine.message_eligibility(agent)['allowed']
        before = (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns, run['created_at'], agent.result_revision)
        assert (await client.put(auth.origin + '/api/config', json=config, headers=headers)).status == 409
        assert engine.settings.revision == revision
        assert (await set_key(client, auth, headers, revision)).status == 200
        await asyncio.sleep(.02)
        assert (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns, run['created_at'], agent.result_revision) == before
        assert (run['status'], agent.status) == ('waiting', 'error')
        assert (await client.post(auth.origin + f'/api/agents/{agent.id}/message', json={'text': 'Retry now'}, headers=headers)).status == 200
        await settled(engine)
        assert (run['status'], agent.status) == ('done', 'done')
        assert (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns) == (2, 0, 0, 2)
        assert seen == [('https://saved.example/v1', OLD), ('https://saved.example/v1', NEW)]
        assert run['_config'] == engine.settings.value and engine.settings.path.read_bytes() == original
        assert engine.settings.revision == revision
        for state in [engine.snapshot(), engine.selected_snapshot(run_id=run['id'], agent_id=agent.id)]:
            assert all(value not in json.dumps(state) for value in [OLD, NEW])


@pytest.mark.parametrize('limit', ['model_limit', 'turn_limit', 'time_limit', 'context_limit', 'stopped', 'settings_changed'])
async def test_key_replacement_never_bypasses_reply_eligibility(tmp_path, limit):
    async with serving(tmp_path) as (auth, app, client):
        engine, config, headers, revision = await setup(auth, app, client)
        engine.client = ScriptClient([reply('Initial result')])
        assert (await set_key(client, auth, headers, revision, key=OLD)).status == 200
        response = await client.post(auth.origin + '/api/runs', json={'task': 'Synthetic eligibility', 'pm_profile': 'model',
                                     'worker_profiles': [], 'max_workers': 0}, headers=headers)
        run = engine.runs[(await response.json())['run']['id']]
        agent = engine.agents[run['agent_ids'][0]]
        await settled(engine)
        if limit == 'model_limit': run['model_calls'] = run['_config']['limits']['max_model_calls']
        elif limit == 'turn_limit': agent.turns = run['_config']['limits']['max_turns_per_agent']
        elif limit == 'time_limit': run['created_at'] -= run['_config']['limits']['max_run_seconds'] + 1
        elif limit == 'context_limit': agent.conversation.append({'role': 'user', 'content': 'x' * run['_config']['limits']['max_context_chars']})
        elif limit == 'stopped': await engine.stop_run(run['id'])
        else:
            config['providers'][0]['model'] = 'changed-model'
            response = await client.put(auth.origin + '/api/config', json=config, headers=headers)
            revision = (await response.json())['config_revision']
        before = (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns)
        assert (await set_key(client, auth, headers, revision)).status == 200
        assert engine.message_eligibility(agent)['reason'] == limit
        response = await client.post(auth.origin + f'/api/agents/{agent.id}/message', json={'text': 'Do not bypass limits'}, headers=headers)
        assert response.status == 400
        assert (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns) == before


async def test_failed_save_and_capacity_do_not_advance_revision(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        engine, config, headers, revision = await setup(auth, app, client)
        engine._redaction = SecretRedactor(max_values=1)
        assert (await set_key(client, auth, headers, revision, key=OLD)).status == 200
        before = engine.settings.path.read_bytes()
        response = await set_key(client, auth, headers, revision)
        assert response.status == 409 and (await response.json())['code'] == 'redaction_capacity'
        assert engine.settings.revision == revision and engine.settings.secrets == {'model': OLD}
        invalid = copy.deepcopy(config); invalid['limits']['max_model_calls'] = 0
        assert (await client.put(auth.origin + '/api/config', json=invalid, headers=headers)).status == 400
        monkeypatch.setenv('SYNTHETIC_RECOVERY_ENV', NEW)
        changed = copy.deepcopy(config); changed['providers'][0]['api_key_env'] = 'SYNTHETIC_RECOVERY_ENV'
        with pytest.raises(RedactionCapacityError): engine.save_settings(changed)
        def fail(*args): raise OSError('synthetic failure')
        monkeypatch.setattr('workbench.config.os.replace', fail)
        assert (await client.put(auth.origin + '/api/config', json=config, headers=headers)).status == 503
        assert engine.settings.revision == revision and engine.settings.path.read_bytes() == before
        assert 'config_revision' not in json.loads(before)
