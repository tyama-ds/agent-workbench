"""Preflight shares actual admission and never calls a model or writes files."""
import asyncio
import json

import pytest

from workbench.config import Settings
from workbench.engine import Engine
from test_config_server import serving, bootstrap


def make_engine(tmp_path):
    settings = Settings(tmp_path / 'state')
    settings.value['providers'][0]['model'] = 'custom-unlisted-alias'
    return Engine(settings)


def payload(**changes):
    return {'task': 'Answer in text only', 'pm_profile': 'local', 'worker_profiles': ['local'], 'max_workers': 0, **changes}


@pytest.mark.asyncio
async def test_text_only_pm_and_unused_workers_preflight_start_parity(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(engine, 'kick', lambda agent: None)
    request = payload(worker_profiles=['openai', 'stale-disabled-profile'])
    preview = engine.preflight(request)
    assert preview['can_start'] and not preview['inference_tested'] and not preview['tools_tested']
    assert len(preview['destinations']) == 1
    assert preview['destinations'][0]['protocol'] == '/chat/completions'
    assert preview['scope']['read_roots'] == preview['scope']['write_roots'] == []
    assert not preview['web']['enabled']
    assert not engine.runs and not engine.agents and not engine.events
    started = await engine.start_run(request)
    assert started['run']['worker_profiles'] == []
    assert started['run']['model_calls'] == 0
    await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['missing_model', 'missing_key', 'worker_key', 'stale_worker', 'missing_root', 'bad_task', 'bad_count', 'bad_payload', 'closed'])
async def test_blockers_match_real_admission_without_run(tmp_path, case):
    engine = make_engine(tmp_path)
    request = payload()
    if case == 'missing_model': engine.settings.value['providers'][0]['model'] = ''
    if case == 'missing_key':
        request['pm_profile'] = 'openai';engine.settings.value['providers'][1]['model'] = 'manual'
    if case == 'worker_key':
        request.update(max_workers=1, worker_profiles=['openai']);engine.settings.value['providers'][1]['model'] = 'manual'
    if case == 'stale_worker': request.update(max_workers=1, worker_profiles=['missing'])
    if case == 'missing_root': engine.settings.value['paths']['read_roots'] = [str(tmp_path / 'removed')]
    if case == 'bad_task': request['task'] = ''
    if case == 'bad_count': request['max_workers'] = True
    if case == 'bad_payload': request['skip_check'] = True
    if case == 'closed': engine.closed = True
    preview = engine.preflight(request)
    assert not preview['can_start']
    with pytest.raises(ValueError) as raised:
        await engine.start_run(request)
    assert preview['blockers'][0]['message'] == engine.redact(str(raised.value))
    assert not engine.runs and not engine.agents
    await engine.close()


def test_scope_exclusions_web_and_potential_destinations(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    work = tmp_path / 'work';work.mkdir()
    engine.settings.value['paths'] = {'read_roots': [str(work)], 'write_roots': [str(work)], 'deny_roots': [str(work)]}
    engine.settings.value['providers'][1]['model'] = 'alias'
    monkeypatch.setenv('OPENAI_API_KEY', 'secret-do-not-return')
    engine.settings.value['search'].update(enabled=True, provider='brave', endpoint='https://api.search.brave.com/res/v1/web/search')
    monkeypatch.delenv('BRAVE_SEARCH_API_KEY', raising=False)
    preview = engine.preflight(payload(max_workers=1, worker_profiles=['openai']))
    assert preview['can_start'] and len(preview['destinations']) == 2
    assert preview['destinations'][1]['protocol'] == '/responses'
    assert preview['web']['fetch_enabled'] and not preview['web']['search_configured']
    assert {'read_scope_denied', 'write_scope_denied', 'search_key_missing'} <= {w['code'] for w in preview['warnings']}
    assert str(engine.settings.directory) in preview['scope']['deny_roots']
    assert 'secret-do-not-return' not in json.dumps(preview)


@pytest.mark.asyncio
async def test_authenticated_preflight_route_is_no_network_and_no_side_effect(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        # Block model transport and DNS outright; this local request uses a literal IP.
        from workbench.server import APP_KEY
        engine = app[APP_KEY]
        engine.settings.value['providers'][0]['model'] = 'manual-alias'
        async def forbidden(*args, **kwargs): raise AssertionError('preflight performed model network work')
        monkeypatch.setattr(engine.client, 'complete', forbidden)
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', forbidden)
        for _ in range(2):
            response = await client.post(auth.origin + '/api/run-preflight', json=payload(), headers={'Origin': auth.origin})
            assert response.status == 200 and (await response.json())['can_start']
        assert not engine.runs and not engine.agents and not engine.settings.path.exists()

@pytest.mark.asyncio
async def test_invalid_environment_key_is_rejected_before_any_run(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    engine.settings.value['providers'][0]['api_key_env'] = 'FIXTURE_MODEL_KEY'
    monkeypatch.setenv('FIXTURE_MODEL_KEY', 'private-key\nunsafe')
    preview = engine.preflight(payload())
    assert not preview['can_start'] and preview['blockers'][0]['code'] == 'key_invalid'
    assert 'private-key' not in json.dumps(preview)
    with pytest.raises(ValueError): await engine.start_run(payload())
    assert not engine.runs
    await engine.close()
