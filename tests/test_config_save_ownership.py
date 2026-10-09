"""Real loopback configuration saves require ownership of the last saved revision."""
import asyncio
import copy
import json

import pytest
from aiohttp import ClientSession

from test_config_server import bootstrap, serving
from workbench import server
from workbench.config import DEFAULT
from workbench.redaction import SecretRedactor
from workbench.server import APP_KEY


MODEL_KEY = 'SYNTHETIC-config-model-key'
SEARCH_KEY = 'SYNTHETIC-config-search-key'
NEXT_KEY = 'SYNTHETIC-config-next-key'
NEXT_ENV = 'SYNTHETIC_CONFIG_NEXT_ENV'


@pytest.fixture(autouse=True)
def synthetic_credentials_only(monkeypatch):
    for profile in [*DEFAULT['providers'], DEFAULT['search']]:
        if profile['api_key_env']:
            monkeypatch.delenv(profile['api_key_env'], raising=False)


async def read_config(client, auth):
    response = await client.get(auth.origin + '/api/config')
    assert response.status == 200
    return await response.json()


async def put_config(client, auth, revision, config):
    return await client.put(auth.origin + '/api/config',
                            json={'config_revision': revision, 'config': config},
                            headers={'Origin': auth.origin})


async def configured(client, auth, app):
    await bootstrap(auth, client)
    public = await read_config(client, auth)
    config = public['config']
    config['providers'] = [dict(config['providers'][0], id='model', kind='openai', model='fixture',
                                base_url='https://saved.example/v1', api_key_env='', proxy_url='')]
    config['search'].update(provider='brave', endpoint='https://saved.example/search', api_key_env='', enabled=False)
    response = await put_config(client, auth, public['config_revision'], config)
    assert response.status == 200
    public = await response.json()
    for ident, key in [('model', MODEL_KEY), ('search', SEARCH_KEY)]:
        response = await client.post(auth.origin + '/api/secrets',
                                     json={'config_revision': public['config_revision'], 'id': ident, 'key': key},
                                     headers={'Origin': auth.origin})
        assert response.status == 200
    return app[APP_KEY], await read_config(client, auth)


def saved_state(engine):
    """Compare all save-owned state, including masks and failed-write leftovers."""
    return {
        'config': copy.deepcopy(engine.settings.value),
        'revision': engine.settings.revision,
        'secrets': dict(engine.settings.secrets),
        'redaction': copy.deepcopy(vars(engine._redaction)),
        'files': {path.name: path.read_bytes() for path in engine.settings.directory.iterdir()},
    }


async def assert_conflict(response):
    assert response.status == 409
    result = await response.json()
    assert result['ok'] is False and result['code'] == 'settings_changed'
    assert set(result) == {'ok', 'code', 'error'}
    assert '読み直' in result['error']
    assert all(key not in json.dumps(result) for key in [MODEL_KEY, SEARCH_KEY, NEXT_KEY])


async def test_revision_in_get_and_success_response_advances_even_on_identical_save(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        initial = await read_config(client, auth)
        assert type(initial['config_revision']) is int and initial['config_revision'] == 0
        assert not engine.settings.path.exists()
        for expected in [1, 2]:
            response = await put_config(client, auth, expected - 1, initial['config'])
            assert response.status == 200
            public = await response.json()
            assert public == await read_config(client, auth)
            assert public['config'] == initial['config']
            assert public['config_revision'] == expected == engine.settings.revision
            persisted = json.loads(engine.settings.path.read_bytes())
            assert persisted == initial['config']
            assert 'config_revision' not in persisted
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        restarted = await read_config(client, auth)
        assert restarted['config'] == initial['config'] and restarted['config_revision'] == 0


async def test_two_clients_stale_save_cannot_overwrite_newer_config_or_credentials(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, first):
        engine, original = await configured(first, auth, app)
        async with ClientSession(cookie_jar=first.cookie_jar) as second:
            stale = await read_config(second, auth)
            assert stale == original
            changed = copy.deepcopy(original['config'])
            changed['providers'][0]['label'] = 'Saved by the first client'
            response = await put_config(first, auth, original['config_revision'], changed)
            assert response.status == 200
            winner = await response.json()
            assert winner['config_revision'] == original['config_revision'] + 1
            assert engine.settings.secrets == {'model': MODEL_KEY, 'search': SEARCH_KEY}

            monkeypatch.setenv(NEXT_ENV, NEXT_KEY)
            stale['config']['providers'][0].update(base_url='https://stale.example/v1', api_key_env=NEXT_ENV)
            stale['config']['search']['endpoint'] = 'https://stale.example/search'
            before = saved_state(engine)

            def unexpected_save(_raw):
                pytest.fail('A stale configuration must be rejected before Engine.save_settings')
            monkeypatch.setattr(engine, 'save_settings', unexpected_save)
            await assert_conflict(await put_config(second, auth, stale['config_revision'], stale['config']))
            assert saved_state(engine) == before
            assert await read_config(first, auth) == winner
            assert engine._redaction.redact(NEXT_KEY) == NEXT_KEY


@pytest.mark.parametrize('revision', [None, True, False, -1, 0, 2, '1', 1.0, [], {}, 2**80])
async def test_invalid_or_stale_revision_never_enters_save(tmp_path, monkeypatch, revision):
    async with serving(tmp_path) as (auth, app, client):
        engine, public = await configured(client, auth, app)
        assert public['config_revision'] == 1  # True and 1.0 compare equal, but are not exact ints.
        monkeypatch.setenv(NEXT_ENV, NEXT_KEY)
        config = copy.deepcopy(public['config'])
        config['providers'][0]['api_key_env'] = NEXT_ENV
        before = saved_state(engine)

        def unexpected_save(_raw):
            pytest.fail('Revision rejection must not invoke the save path')
        monkeypatch.setattr(engine, 'save_settings', unexpected_save)
        await assert_conflict(await put_config(client, auth, revision, config))
        assert saved_state(engine) == before


@pytest.mark.parametrize('shape', ['missing_revision', 'legacy_raw', 'nested_revision'])
async def test_missing_revision_has_no_legacy_save_bypass(tmp_path, shape):
    async with serving(tmp_path) as (auth, app, client):
        engine, public = await configured(client, auth, app)
        payload = {'config': public['config']}
        if shape == 'legacy_raw':
            payload = public['config']
        elif shape == 'nested_revision':
            payload['config']['config_revision'] = public['config_revision']
        before = saved_state(engine)
        response = await client.put(auth.origin + '/api/config', json=payload, headers={'Origin': auth.origin})
        await assert_conflict(response)
        assert saved_state(engine) == before


async def test_false_revision_cannot_match_initial_zero(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        public = await read_config(client, auth)
        before = saved_state(app[APP_KEY])
        await assert_conflict(await put_config(client, auth, False, public['config']))
        assert saved_state(app[APP_KEY]) == before


@pytest.mark.parametrize('intervening_save', ['identical', 'aba'])
async def test_value_equality_cannot_reauthorize_an_old_revision(tmp_path, intervening_save):
    async with serving(tmp_path) as (auth, app, client):
        engine, original = await configured(client, auth, app)
        changed = copy.deepcopy(original['config'])
        if intervening_save == 'aba':
            changed['providers'][0]['label'] = 'Intermediate B'
        response = await put_config(client, auth, original['config_revision'], changed)
        assert response.status == 200
        public = await response.json()
        if intervening_save == 'aba':
            response = await put_config(client, auth, public['config_revision'], original['config'])
            assert response.status == 200
            public = await response.json()
        assert public['config'] == original['config']
        assert public['config_revision'] > original['config_revision']
        before = saved_state(engine)
        await assert_conflict(await put_config(client, auth, original['config_revision'], original['config']))
        assert saved_state(engine) == before


async def test_simultaneous_saves_of_one_revision_have_exactly_one_winner(tmp_path):
    async with serving(tmp_path) as (auth, app, first):
        engine, original = await configured(first, auth, app)
        configs = [copy.deepcopy(original['config']) for _ in range(2)]
        for index, config in enumerate(configs):
            config['providers'][0]['label'] = f'Client {index}'
        async with ClientSession(cookie_jar=first.cookie_jar) as second:
            responses = await asyncio.gather(*(put_config(client, auth, original['config_revision'], config)
                                              for client, config in zip([first, second], configs)))
            assert sorted(response.status for response in responses) == [200, 409]
            winner = next(index for index, response in enumerate(responses) if response.status == 200)
            await assert_conflict(responses[1 - winner])
            public = await responses[winner].json()
            assert public == await read_config(first, auth)
            assert public['config'] == configs[winner] == engine.settings.value
            assert public['config_revision'] == original['config_revision'] + 1
            assert engine.settings.secrets == {'model': MODEL_KEY, 'search': SEARCH_KEY}
            assert engine._redaction.value_count == 2
            assert json.loads(engine.settings.path.read_bytes()) == configs[winner]


@pytest.mark.parametrize('race', ['new_save', 'active_run'])
async def test_revision_and_active_lock_are_checked_after_streamed_body(tmp_path, monkeypatch, race):
    async with serving(tmp_path) as (auth, app, first):
        engine, original = await configured(first, auth, app)
        entered, release = asyncio.Event(), asyncio.Event()
        original_body = server.body

        async def observed_body(request):
            if request.headers.get('X-Synthetic-Paused'):
                entered.set()
            return await original_body(request)
        monkeypatch.setattr(server, 'body', observed_body)
        draft = copy.deepcopy(original['config'])
        draft['providers'][0]['base_url'] = 'https://stale.example/v1'
        payload = json.dumps({'config_revision': original['config_revision'], 'config': draft}).encode()

        async def chunks():
            yield payload[:1]
            await release.wait()
            yield payload[1:]

        async with ClientSession(cookie_jar=first.cookie_jar) as second:
            pending = asyncio.create_task(second.put(auth.origin + '/api/config', data=chunks(),
                headers={'Origin': auth.origin, 'Content-Type': 'application/json', 'X-Synthetic-Paused': 'yes'}))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                assert not pending.done()
                if race == 'new_save':
                    changed = copy.deepcopy(original['config'])
                    changed['providers'][0]['label'] = 'Newer save during streamed body'
                    response = await put_config(first, auth, original['config_revision'], changed)
                    assert response.status == 200
                else:
                    engine.runs['synthetic'] = {'id': 'synthetic', 'status': 'waiting', 'agent_ids': []}
                before = saved_state(engine)
                release.set()
                response = await asyncio.wait_for(pending, 10)
                if race == 'new_save':
                    await assert_conflict(response)
                else:
                    assert response.status == 409
                    assert '実行中' in (await response.json())['error']
                assert saved_state(engine) == before
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize('status', ['running', 'waiting', 'stopping'])
async def test_current_revision_still_respects_active_run_lock(tmp_path, status):
    async with serving(tmp_path) as (auth, app, client):
        engine, public = await configured(client, auth, app)
        engine.runs['synthetic'] = {'id': 'synthetic', 'status': status, 'agent_ids': []}
        before = saved_state(engine)
        changed = copy.deepcopy(public['config'])
        changed['providers'][0]['base_url'] = 'https://blocked.example/v1'
        response = await put_config(client, auth, public['config_revision'], changed)
        assert response.status == 409
        assert '実行中' in (await response.json())['error']
        assert saved_state(engine) == before


@pytest.mark.parametrize('config', [None, [], '', 1, {'unsupported': 'value'}])
async def test_current_revision_still_validates_enclosed_configuration(tmp_path, config):
    async with serving(tmp_path) as (auth, app, client):
        engine, public = await configured(client, auth, app)
        before = saved_state(engine)
        response = await put_config(client, auth, public['config_revision'], config)
        assert response.status == 400
        assert saved_state(engine) == before
        response = await client.put(auth.origin + '/api/config',
                                     json={'config_revision': public['config_revision']},
                                     headers={'Origin': auth.origin})
        assert response.status == 400
        assert saved_state(engine) == before


@pytest.mark.parametrize('failure', ['validation', 'redaction_capacity', 'disk'])
async def test_save_failure_is_atomic_and_same_revision_remains_retryable(tmp_path, monkeypatch, failure):
    async with serving(tmp_path) as (auth, app, client):
        engine, public = await configured(client, auth, app)
        monkeypatch.setenv(NEXT_ENV, NEXT_KEY)
        changed = copy.deepcopy(public['config'])
        changed['providers'][0]['api_key_env'] = NEXT_ENV
        if failure == 'validation':
            changed['limits']['max_model_calls'] = 0
        elif failure == 'redaction_capacity':
            engine._redaction = SecretRedactor(max_values=2)
            engine._redaction.remember([MODEL_KEY, SEARCH_KEY])
        before = saved_state(engine)
        with monkeypatch.context() as patch:
            if failure == 'disk':
                def fail_replace(*_args):
                    raise OSError('Synthetic failed replacement')
                patch.setattr('workbench.config.os.replace', fail_replace)
            response = await put_config(client, auth, public['config_revision'], changed)
        assert response.status == {'validation': 400, 'redaction_capacity': 409, 'disk': 503}[failure]
        result = await response.json()
        assert result['ok'] is False
        if failure == 'redaction_capacity':
            assert result['code'] == 'redaction_capacity'
        assert all(key not in json.dumps(result) for key in [MODEL_KEY, SEARCH_KEY, NEXT_KEY])
        assert saved_state(engine) == before
        assert engine._redaction.redact(NEXT_KEY) == NEXT_KEY
        assert engine._redaction.redact(MODEL_KEY + SEARCH_KEY) == '[redacted][redacted]'

        # A failed attempt consumes no revision and leaves the same ownership usable.
        if failure == 'validation':
            changed['limits']['max_model_calls'] = public['config']['limits']['max_model_calls']
        elif failure == 'redaction_capacity':
            engine._redaction = SecretRedactor()
            engine._redaction.remember([MODEL_KEY, SEARCH_KEY])
        response = await put_config(client, auth, public['config_revision'], changed)
        assert response.status == 200
        saved = await response.json()
        assert saved['config_revision'] == public['config_revision'] + 1
        assert saved['config'] == changed == engine.settings.value
        assert engine.settings.secrets == {'search': SEARCH_KEY}
        assert engine._redaction.redact(NEXT_KEY) == '[redacted]'
        assert 'config_revision' not in json.loads(engine.settings.path.read_bytes())
        assert list(engine.settings.directory.iterdir()) == [engine.settings.path]
