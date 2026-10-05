"""The state benchmark is bounded, reproducible and incapable of model work."""
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from aiohttp import ClientSession

import workbench.engine as engine_module
import tools.benchmark_state as benchmark_module
from tools.benchmark_state import (CREATED_AT, FIXTURES, ITERATIONS, REDACTION_MODES, NoModelClient,
                                   benchmark_fixture, fixture_text, populate, populate_registry, registry_keys)
from workbench.config import Settings
from workbench.engine import Engine
from workbench.redaction import MAX_REDACTION_BYTES, MAX_REDACTION_VALUES


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


@pytest.mark.parametrize('mode', REDACTION_MODES)
def test_registry_fixture_retains_exact_synthetic_values_without_public_values(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda: CREATED_AT))
    engine = Engine(Settings(tmp_path), client=NoModelClient())
    populate(engine, FIXTURES[0])
    metadata = populate_registry(engine, mode)
    keys = registry_keys(mode)
    assert metadata['value_count'] == (4 if mode == 'normal' else MAX_REDACTION_VALUES - 1)
    assert metadata['byte_count'] == sum(len(key.encode()) for key in keys) < MAX_REDACTION_BYTES
    assert engine.settings.secrets == {'local': keys[-1]}
    # Raw fixture records genuinely contain current and retired values; no pre-masking.
    assert keys[0] in engine.runs['r-0']['task']
    assert keys[0] in engine.agents['a-0-0'].name
    assert keys[1] in engine.agents['a-0-0'].question
    assert keys[-1] in engine.agents['a-0-0'].results[0]['text']
    for state in (engine.snapshot(), engine.selected_snapshot(run_id='r-0', agent_id='a-0-0')):
        encoded = json.dumps(state)
        assert not any(key in encoded for key in keys)
        lead = state['agents'][0]
        for value in (state['runs'][0]['task'], lead['assignment'], lead['name'], lead['question'],
                      lead['logs'][0]['text'], lead['results'][0]['text'],
                      lead['output_receipts'][0]['path'], state['events'][0]['text']):
            assert '[redacted]' in value
    assert not any(key in json.dumps(metadata) for key in keys)


@pytest.mark.parametrize('mode', REDACTION_MODES)
async def test_registry_benchmark_uses_real_endpoints_without_operator_credentials(tmp_path, monkeypatch, mode):
    # Deliberately poisonous operator values must not become registry entries.
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'BRAVE_SEARCH_API_KEY'):
        monkeypatch.setenv(name, 'operator-key-must-not-be-read-' + name)
    report = await benchmark_fixture(tmp_path, FIXTURES[0], registry_mode=mode)
    assert report['redaction_registry']['value_count'] == len(registry_keys(mode))
    assert report['model_calls'] == 0
    assert report['views']['full']['body_bytes'] > report['views']['selected']['body_bytes'] > 0
    assert report['views']['selected']['agents_with_detail'] == 1
    assert not any(key in json.dumps(report) for key in registry_keys(mode))


def test_unknown_registry_fixture_mode_rejected():
    with pytest.raises(ValueError, match='Unknown redaction'):
        registry_keys('unbounded')


def test_adversarial_registry_report_contract_uses_bounded_test_scale(monkeypatch):
    # CI checks report semantics at a small scale; the CLI stress is explicitly opt-in.
    monkeypatch.setattr(benchmark_module, 'MAX_REDACTION_VALUES', 8)
    monkeypatch.setattr(benchmark_module, 'MAX_REDACTION_BYTES', 128)
    report = benchmark_module.adversarial_registry_benchmark()
    assert report['benchmark'] == 'synthetic_redaction_mixed_prefix_stress'
    assert report['value_count'] == report['value_capacity'] == 8
    assert report['byte_count'] == report['byte_capacity'] == 128
    assert report['key_chars'] == 16 and report['report_chars'] == 24000
    assert all(report[key] >= 0 for key in ('registration_ms', 'no_match_ms', 'matching_ms'))


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
    assert [item['redaction_registry']['mode'] for item in report['redaction_registry_results']] == list(REDACTION_MODES)
    normal, near = report['redaction_registry_results']
    for view in ('full', 'selected'):
        assert normal['views'][view]['body_bytes'] == near['views'][view]['body_bytes']
