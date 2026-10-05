"""Selected state is a live projection, never full-state serialization plus pruning."""
import copy
import json

import pytest

from workbench.server import APP_KEY
from test_config_server import bootstrap, serving
from test_engine import ScriptClient, configured, start


HEAVY_FIELDS = {'logs', 'results', 'output_receipts'}


async def populate(engine):
    engine.kick = lambda agent: None
    engine.settings.value['providers'][0]['model'] = 'fixture'
    run, pm = await start(engine)
    worker = engine._new_agent(run, 'local', 'writer', pm.id, assignment='Write the report')
    other_run, other_pm = await start(engine, task='Another team')
    for agent in engine.agents.values():
        engine.log(agent, 'assistant', f'Log for {agent.id}', 'Visible provider reasoning')
        engine.record_result(agent, 'response', f'Result for {agent.id}')
        engine.record_receipt(agent, 'write_text', {
            'path': f'{agent.id}.txt', 'bytes': 12, 'sha256': 'a' * 64, 'operation': 'created'})
        agent.results_omitted = 2
        agent.receipts_omitted = 3
        agent.result_revision = 4
    return run, pm, worker, other_run, other_pm


@pytest.fixture
async def populated(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    value = await populate(engine)
    try:
        yield engine, *value
    finally:
        await engine.close()


def test_full_and_selected_field_parity_and_no_mutation(populated):
    engine, run, pm, worker, other_run, other_pm = populated
    before = engine.snapshot()
    assert set(before) == {'runs', 'agents', 'events', 'resources'}
    selected = engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)
    assert set(selected) == set(before) | {'selection'}
    assert selected['selection'] == {'run_id': run['id'], 'agent_id': worker.id, 'detail_loaded': True}
    assert selected['runs'] == before['runs']
    assert selected['resources'] == before['resources']
    assert selected['events'] == [event for event in before['events'] if event['run_id'] == run['id']]
    assert len(selected['agents']) == len(before['agents'])
    for full, compact in zip(before['agents'], selected['agents']):
        if full['id'] == worker.id:
            assert compact == full
        else:
            assert compact == {key: value for key, value in full.items() if key not in HEAVY_FIELDS}
            assert HEAVY_FIELDS.isdisjoint(compact)
        assert 'conversation' not in compact and 'pending' not in compact
    assert engine.snapshot() == before
    # The returned display objects must not be aliases into mutable engine data.
    selected['agents'][1]['logs'][0]['text'] = 'Changed client copy'
    selected['runs'][0]['agent_ids'].clear()
    selected['events'][0]['text'] = 'Changed event'
    assert engine.snapshot() == before


def test_summary_only_and_run_only_have_explicit_selection(populated):
    engine, run, *_ = populated
    summary = engine.selected_snapshot()
    assert summary['selection'] == {'run_id': None, 'agent_id': None, 'detail_loaded': False}
    assert summary['events'] == []
    assert all(HEAVY_FIELDS.isdisjoint(agent) for agent in summary['agents'])
    selected_run = engine.selected_snapshot(run_id=run['id'])
    assert selected_run['selection'] == {'run_id': run['id'], 'agent_id': None, 'detail_loaded': False}
    assert selected_run['agents'] == summary['agents']
    assert selected_run['events'] and all(event['run_id'] == run['id'] for event in selected_run['events'])


def test_unselected_histories_are_not_materialized_or_redacted(populated, monkeypatch):
    engine, run, pm, worker, other_run, other_pm = populated

    class UnreadableHistory:
        def __iter__(self):
            raise AssertionError('Summary must not materialize a history')

        def __len__(self):
            raise AssertionError('Summary must not inspect a history')

    selected_agent = engine.snapshot()['agents'][1]
    for agent in (pm, other_pm):
        for field in HEAVY_FIELDS:
            monkeypatch.setattr(agent, field, UnreadableHistory())
    assert engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)['agents'][1] == selected_agent
    for field in HEAVY_FIELDS:
        monkeypatch.setattr(worker, field, UnreadableHistory())
    assert engine.selected_snapshot()['agents']
    assert engine.selected_snapshot(run_id=run['id'])['agents']


def test_secret_redaction_covers_summaries_details_events_and_resources(populated, monkeypatch):
    engine, run, pm, worker, *_ = populated
    memory_secret, environment_secret = 'compact-memory-secret', 'compact-environment-secret'
    engine.settings.secrets['local'] = memory_secret
    monkeypatch.setenv('BRAVE_SEARCH_API_KEY', environment_secret)
    run['task'] = f'Brief {memory_secret}'
    for agent in (pm, worker):
        agent.assignment = memory_secret
        agent.question = environment_secret
        agent.last_error = memory_secret
        agent.logs[0]['text'] = memory_secret
        agent.logs[0]['thinking'] = environment_secret
        agent.results[0]['text'] = memory_secret
        agent.output_receipts[0]['path'] = environment_secret
    engine.events[-1]['run_id'] = run['id']
    engine.events[-1]['text'] = memory_secret
    engine.events[-1]['metadata'] = {'nested': [environment_secret]}
    engine.gate.last_admission = {'message': memory_secret}
    engine.gate.last_gpu_readings = [{'message': environment_secret}]
    for state in (engine.snapshot(), engine.selected_snapshot(), engine.selected_snapshot(run_id=run['id']),
                  engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)):
        encoded = json.dumps(state)
        assert memory_secret not in encoded and environment_secret not in encoded
        assert '[redacted]' in encoded
        assert all(not any(key.startswith('_') for key in row) for row in state['runs'])
        assert not any(key in encoded for key in ('api_key', 'conversation', 'system_policy'))
    assert worker.assignment == memory_secret  # Read-only redaction.


def test_selected_events_filter_before_limit_and_remain_chronological(populated):
    engine, run, pm, worker, other_run, other_pm = populated
    engine.events.clear()
    for index in range(140):
        engine.event(run['id'], pm.id, 'mail', f'PM message {index}')
        engine.event(other_run['id'], other_pm.id, 'mail', f'Other team {index}')
        engine.event(run['id'], worker.id, 'mail', f'Worker message {index}')
        engine.event(other_run['id'], other_pm.id, 'mail', f'Other activity {index}')
    full = engine.snapshot()
    expected = [event for event in full['events'] if event['run_id'] == run['id']][-100:]
    selected = engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)
    assert selected['events'] == expected
    assert len(selected['events']) == 100
    assert {event['agent_id'] for event in selected['events']} == {pm.id, worker.id}
    assert [event['id'] for event in selected['events']] == sorted(event['id'] for event in expected)
    assert len(full['events']) == 560


@pytest.mark.parametrize('selection', [
    {'run_id': 'unknown'}, {'run_id': ''}, {'run_id': []},
    {'run_id': 'run', 'agent_id': 'unknown'}, {'run_id': 'run', 'agent_id': ''},
    {'run_id': 'run', 'agent_id': []}, {'agent_id': 'pm'},
    {'run_id': 'other_run', 'agent_id': 'pm'},
])
def test_invalid_selection_is_an_error_without_state_changes(populated, selection):
    engine, run, pm, worker, other_run, _ = populated
    ids = {'run': run['id'], 'other_run': other_run['id'], 'pm': pm.id}
    values = {key: ids.get(value, value) if isinstance(value, str) else value for key, value in selection.items()}
    before = engine.snapshot()
    with pytest.raises(ValueError):
        engine.selected_snapshot(**values)
    assert engine.snapshot() == before


def test_eligibility_recomputed_when_only_clock_changes(populated, monkeypatch):
    engine, run, pm, worker, *_ = populated
    cutoff = run['created_at'] + run['_config']['limits']['max_run_seconds']
    monkeypatch.setattr('workbench.engine.time.time', lambda: cutoff - 1)
    before = engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)
    assert all(agent['message_eligibility']['allowed'] for agent in before['agents'])
    sequence, revisions = engine.sequence, [agent.result_revision for agent in engine.agents.values()]
    monkeypatch.setattr('workbench.engine.time.time', lambda: cutoff + 1)
    after = engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)
    assert all(not agent['message_eligibility']['allowed'] and
               agent['message_eligibility']['reason'] == 'time_limit' for agent in after['agents'])
    assert engine.sequence == sequence
    assert [agent.result_revision for agent in engine.agents.values()] == revisions
    assert before['events'] == after['events'] and before['selection'] == after['selection']
    assert [agent['message_eligibility'] for agent in engine.snapshot()['agents']] == [
        agent['message_eligibility'] for agent in after['agents']]


async def test_endpoint_contract_auth_headers_freshness_and_config(tmp_path, monkeypatch):
    async with serving(tmp_path / 'http') as (auth, app, client):
        engine = app[APP_KEY]
        run, pm, worker, other_run, other_pm = await populate(engine)
        url = auth.origin + '/api/state'
        selection = {'view': 'selected', 'run_id': run['id'], 'agent_id': worker.id}
        response = await client.get(url, params=selection)
        assert response.status == 401 and response.headers['Cache-Control'] == 'no-store'
        await bootstrap(auth, client)
        config_before = copy.deepcopy(engine.settings.public())
        for params in ({}, {'run_id': 'ignored-without-view'}):
            response = await client.get(url, params=params)
            assert response.status == 200 and await response.json() == engine.snapshot()
        for params in ({'view': 'selected'}, {'view': 'selected', 'run_id': run['id']}, selection):
            response = await client.get(url, params=params, headers={'If-None-Match': '*'})
            assert response.status == 200
            assert response.headers['Cache-Control'] == 'no-store' and 'ETag' not in response.headers
            assert response.headers['X-Frame-Options'] == 'DENY'
            assert response.headers['Referrer-Policy'] == 'no-referrer'
            assert "script-src 'self'" in response.headers['Content-Security-Policy']
            assert await response.json() == engine.selected_snapshot(
                run_id=params.get('run_id'), agent_id=params.get('agent_id'))
        for headers in ({'Origin': 'https://attacker.invalid'}, {'Host': 'attacker.invalid'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            response = await client.get(url, params=selection, headers=headers)
            assert response.status == 403 and response.headers['Cache-Control'] == 'no-store'
        invalid_queries = [
            {'view': 'unknown'}, {'view': ''}, {'view': 'selected', 'run_id': 'unknown'},
            {'view': 'selected', 'run_id': ''}, {'view': 'selected', 'agent_id': worker.id},
            {**selection, 'agent_id': 'unknown'}, {**selection, 'run_id': other_run['id']},
            [('view', 'selected'), ('view', 'selected')],
            [('view', 'selected'), ('run_id', run['id']), ('run_id', other_run['id'])],
            [('view', 'selected'), ('run_id', run['id']), ('agent_id', worker.id), ('agent_id', pm.id)],
        ]
        for params in invalid_queries:
            response = await client.get(url, params=params)
            assert response.status == 400
            assert (await response.json())['ok'] is False
            assert response.headers['Cache-Control'] == 'no-store'
        cutoff = run['created_at'] + run['_config']['limits']['max_run_seconds']
        monkeypatch.setattr('workbench.engine.time.time', lambda: cutoff + 1)
        engine.gate._waiting = 3
        response = await client.get(url, params=selection, headers={'If-None-Match': '*'})
        result = await response.json()
        assert response.status == 200
        assert result['agents'][0]['message_eligibility']['reason'] == 'time_limit'
        assert result['resources']['waiting'] == result['resources']['queued'] == 3
        response = await client.get(auth.origin + '/api/config')
        assert response.status == 200 and await response.json() == config_before
        assert engine.settings.public() == config_before
        assert not engine.settings.path.exists()
