"""The state benchmark is bounded, reproducible and incapable of model work."""
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from aiohttp import ClientSession

import workbench.engine as engine_module
from tools.benchmark_state import (CREATED_AT, FIXTURES, ITERATIONS, NoModelClient,
                                   benchmark_fixture, fixture_text, populate)
from workbench.config import Settings
from workbench.engine import Engine


@pytest.mark.parametrize('length', [0, 1, 7, 160, 400, 800, 2000, 4000, 6000, 16000, 24000])
def test_fixture_text_has_exact_unicode_character_count(length):
    value = fixture_text(length)
    assert len(value) == length
    assert value == ('調査abcde' * ((length + 6) // 7))[:length]


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda fixture: fixture.name)
def test_seeded_fixture_is_exact_bounded_and_context_eligible(tmp_path, monkeypatch, fixture):
    monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda: CREATED_AT))
    model = NoModelClient()
    engine = Engine(Settings(tmp_path), client=model)
    populate(engine, fixture)
    assert len(engine.runs) == fixture.runs
    assert len(engine.agents) == fixture.runs * fixture.agents_per_run
    assert len(engine.events) == fixture.events_total <= 1000
    for index, run in enumerate(engine.runs.values()):
        assert run['id'] == f'r-{index}'
        assert run['created_at'] == CREATED_AT
        assert len(run['task']) == 160
        assert run['_config']['limits']['max_turns_per_agent'] == 100
        assert run['_config']['limits']['max_run_seconds'] == 86400
    for agent in engine.agents.values():
        assert agent.status == 'done' and agent.turns == 10
        assert agent.task is None and not agent.pending
        assert len(agent.assignment) == 160
        assert len(agent.logs) == fixture.logs_per_agent <= agent.logs.maxlen
        assert all(len(log['text']) == fixture.log_chars and log['thinking'] == '' for log in agent.logs)
        assert len(agent.results) == fixture.reports_per_agent <= agent.results.maxlen
        assert all(len(result['text']) == fixture.report_chars <= 24000 for result in agent.results)
        assert len(agent.output_receipts) == fixture.receipts_per_agent <= agent.output_receipts.maxlen
        run_number, agent_number = agent.id[2:].split('-')
        for receipt_index, receipt in enumerate(agent.output_receipts):
            assert receipt['path'] == f'/synthetic/work/run-{run_number}/agent-{agent_number}/file-{receipt_index}.txt'
            assert receipt['bytes'] == 4096 and receipt['sha256'] == 'a' * 64
        assert [len(message['content']) for message in agent.conversation] == [4000, 16000]
        assert engine.message_eligibility(agent)['allowed']
    assert all(len(event['text']) == 160 for event in engine.events)

    # Prove each public projection reaches every private conversation's real
    # json.dumps admission scan; no early time/budget guard hides that cost.
    conversation_ids = {id(agent.conversation) for agent in engine.agents.values()}
    observed = []
    original_dumps = json.dumps

    def observe_dumps(value, *args, **kwargs):
        if id(value) in conversation_ids:
            observed.append(id(value))
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(engine_module.json, 'dumps', observe_dumps)
    engine.snapshot()
    assert set(observed) == conversation_ids and len(observed) == len(conversation_ids)
    observed.clear()
    engine.selected_snapshot(run_id='r-0', agent_id='a-0-0')
    assert set(observed) == conversation_ids and len(observed) == len(conversation_ids)
    assert model.calls == 0
    with pytest.raises(ValueError, match='empty engine'):
        populate(engine, fixture)


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda fixture: fixture.name)
async def test_actual_endpoint_measurements_are_loopback_only_and_no_live_client(tmp_path, monkeypatch, fixture):
    def reject_live_client(*args, **kwargs):
        raise AssertionError('Live ProviderClient construction is forbidden')

    monkeypatch.setattr(engine_module, 'ProviderClient', reject_live_client)
    original_request = ClientSession._request
    requests = []

    async def loopback_request(self, method, url, **kwargs):
        parsed = urlsplit(str(url))
        assert parsed.hostname == '127.0.0.1'
        assert parsed.path in {'/api/bootstrap', '/api/state'}
        requests.append((method, parsed.path, parsed.query))
        return await original_request(self, method, url, **kwargs)

    monkeypatch.setattr(ClientSession, '_request', loopback_request)
    report = await benchmark_fixture(tmp_path / 'state', fixture)
    assert report['model_calls'] == 0
    assert report['agents_total'] == fixture.runs * fixture.agents_per_run
    assert len(requests) == 1 + 2 * (ITERATIONS + 1)  # Authentication, warmups, medians.
    full, selected = report['views']['full'], report['views']['selected']
    assert full['body_bytes'] > selected['body_bytes'] > 0
    assert full['events_returned'] == fixture.events_total
    assert selected['events_returned'] == min(100, fixture.events_total // fixture.runs)
    assert full['agents_with_detail'] == fixture.runs * fixture.agents_per_run
    assert selected['agents_with_detail'] == 1
    for measurement in (full, selected):
        assert all(measurement[key] >= 0 for key in (
            'snapshot_median_ms', 'json_median_ms', 'endpoint_median_ms'))
    # The fixture clock replacement must not escape into other tests or real work.
    assert engine_module.time is not None and hasattr(engine_module.time, 'monotonic')


async def test_sentinel_rejects_any_model_work():
    model = NoModelClient()
    with pytest.raises(AssertionError, match='must not call a model'):
        await model.complete()
    assert model.calls == 1


def test_cli_json_survives_legacy_windows_stdout_encoding():
    import os
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-m', 'tools.benchmark_state', '--fixture', 'small'],
                            env={**os.environ, 'PYTHONIOENCODING': 'cp1252'},
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode('ascii', errors='replace')
    report = json.loads(result.stdout.decode('ascii'))
    assert report['assumptions']['text_pattern'] == '調査abcde'
    assert report['results'][0]['model_calls'] == 0
