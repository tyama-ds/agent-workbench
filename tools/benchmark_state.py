"""Bounded synthetic /api/state benchmark; never constructs a model client.

Run from the repository root with ``python -m tools.benchmark_state``.
Only temporary settings and authenticated 127.0.0.1 HTTP are used. The JSON
report is a local microbenchmark, not a production capacity or memory claim.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import platform
import socket
import statistics
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import ClientSession, ClientTimeout, CookieJar, web

import workbench.engine as engine_module
from workbench.config import Settings
from workbench.engine import Agent
from workbench.harness import ToolExecutor
from workbench.redaction import MAX_REDACTION_BYTES, MAX_REDACTION_VALUES, SecretRedactor
from workbench.server import APP_KEY, BrowserAuth, create_app


ITERATIONS = 7
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
TEXT_PATTERN = '調査abcde'
# Keep admission checks eligible, including their actual serialized-request admission scan.
# Only engine_module.time is replaced while measuring; wall-clock timings remain real.
CREATED_AT = 1700000000.0


@dataclass(frozen=True)
class Fixture:
    name: str
    runs: int
    agents_per_run: int
    logs_per_agent: int
    log_chars: int
    reports_per_agent: int
    report_chars: int
    receipts_per_agent: int
    events_total: int


FIXTURES = (
    Fixture('small', 1, 3, 40, 400, 2, 2000, 4, 60),
    Fixture('medium', 5, 5, 120, 800, 10, 6000, 24, 500),
    Fixture('report_cap', 1, 5, 200, 800, 20, 24000, 64, 200),
)
REDACTION_MODES = ('normal', 'near_capacity')


def adversarial_registry_benchmark():
    """Opt-in mixed-prefix 2 MiB stress; run the CLI under an external timeout.

    One different leading character prevents a regex common-prefix fast path.
    Payload limits alone do not bound compiled matcher/Python allocation or CPU.
    """
    width = min(4096, MAX_REDACTION_BYTES // MAX_REDACTION_VALUES)
    keys = tuple('a' * (width - 4) + f'{index:04x}' for index in range(MAX_REDACTION_VALUES - 1)) + ('b' * width,)
    value = 'a' * 24000
    redactor = SecretRedactor()
    started = time.perf_counter_ns()
    redactor.remember(keys)
    registration_ms = (time.perf_counter_ns() - started) / 1_000_000
    started = time.perf_counter_ns()
    masked = redactor.redact(value)
    no_match_ms = (time.perf_counter_ns() - started) / 1_000_000
    if masked != value:
        raise AssertionError('An almost-matching report must not be altered')
    matching = value + keys[0] + keys[-1]
    started = time.perf_counter_ns()
    masked = redactor.redact(matching)
    matching_ms = (time.perf_counter_ns() - started) / 1_000_000
    if masked != value + '[redacted][redacted]':
        raise AssertionError('Mixed-prefix synthetic exact matches must be masked')
    report = {
        'benchmark': 'synthetic_redaction_mixed_prefix_stress',
        'python': platform.python_version(), 'platform': platform.platform(),
        'value_count': redactor.value_count, 'byte_count': redactor.byte_count,
        'value_capacity': MAX_REDACTION_VALUES, 'byte_capacity': MAX_REDACTION_BYTES,
        'key_chars': width, 'report_chars': len(value),
        'registration_ms': round(registration_ms, 6),
        'no_match_ms': round(no_match_ms, 6), 'matching_ms': round(matching_ms, 6),
        'assumptions': 'One measurement each, no model or network. Almost all 4 KiB keys share a repeated prefix; one has a different leading character. A 24 KiB repeated-prefix report contains no full match; a second adds two exact matches. Payload limits do not measure compiled matcher/Python memory. Run in a disposable process with an external timeout.',
    }
    try:
        import resource
        maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['peak_process_rss_bytes'] = maximum if sys.platform == 'darwin' else maximum * 1024
    except (ImportError, AttributeError):
        report['peak_process_rss_bytes'] = None
    return report


def registry_keys(mode):
    """Deterministic synthetic exact values; never consult operator credentials."""
    if mode not in REDACTION_MODES:
        raise ValueError('Unknown redaction registry benchmark mode')
    count = 4 if mode == 'normal' else MAX_REDACTION_VALUES - 1
    return tuple(f'synthetic-state-key-{index:04d}-exact-value-only' for index in range(count))


def populate_registry(engine, mode):
    """Exercise retained and current credentials across every public record kind."""
    keys = registry_keys(mode)
    engine._redaction.remember(keys[:-1])  # Previously accepted, now retired values.
    engine.settings.secrets['local'] = keys[-1]  # The sole current credential.
    run, agent = engine.runs['r-0'], engine.agents['a-0-0']

    def marked(value, key):
        # Preserve the fixture's documented character lengths.
        return key + value[len(key):]

    run['task'] = marked(run['task'], keys[0])
    agent.assignment = marked(agent.assignment, keys[-1])
    agent.name = 'Synthetic worker ' + keys[0]
    agent.question = 'Synthetic historical question ' + keys[1]
    agent.logs[0]['text'] = marked(agent.logs[0]['text'], keys[0])
    agent.results[0]['text'] = marked(agent.results[0]['text'], keys[-1])
    agent.output_receipts[0]['path'] = '/synthetic/' + keys[1] + '/result.txt'
    engine.events[0]['text'] = marked(engine.events[0]['text'], keys[-2])
    # The first projection includes current credentials and prepares the matcher.
    encoded = json.dumps(engine.snapshot())
    if any(key in encoded for key in keys) or '[redacted]' not in encoded:
        raise AssertionError('Synthetic credential escaped the public projection')
    return {
        'mode': mode, 'value_count': engine._redaction.value_count,
        'byte_count': engine._redaction.byte_count,
        'value_capacity': MAX_REDACTION_VALUES, 'byte_capacity': MAX_REDACTION_BYTES,
        'current_values': 1, 'retired_values': len(keys) - 1,
        'capacity_scope': 'Near capacity refers to value count, not byte count.',
        'records_checked': ['task', 'assignment', 'name', 'question', 'logs', 'results',
                            'output_receipts', 'events'],
    }


class NoToolExecutor:
    """Schemas only for exact request budgeting; execution is always rejected."""

    def schemas(self):
        return ToolExecutor.schemas(self)

    async def execute(self, *args, **kwargs):
        raise AssertionError('The state benchmark must not execute tools')


class NoModelClient:
    """A fail-fast sentinel, not a live provider or a synthetic model runner."""

    def __init__(self):
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError('The state benchmark must not call a model')


def fixture_text(length):
    """Return exactly length Unicode characters, without random data or padding."""
    return (TEXT_PATTERN * ((length + len(TEXT_PATTERN) - 1) // len(TEXT_PATTERN)))[:length]


def populate(engine, fixture):
    """Seed bounded in-memory records directly; do not start scheduler tasks."""
    if engine.runs or engine.agents or engine.events:
        raise ValueError('Benchmark requires an empty engine')
    settings = engine.settings
    # Do not read the operator's API keys or involve a real provider.
    for profile in settings.value['providers']:
        profile['api_key_env'] = ''
        profile['model'] = 'synthetic-no-network'
    settings.value['search']['api_key_env'] = ''
    settings.value['limits'].update(max_workers=4, max_turns_per_agent=100,
                                    max_run_seconds=86400)
    sequence = 0

    def next_id():
        nonlocal sequence
        sequence += 1
        return sequence

    for run_index in range(fixture.runs):
        run_id = f'r-{run_index}'
        run = {
            'id': run_id, 'task': fixture_text(160), 'pm_profile': 'local',
            'worker_profiles': ['local'], 'max_workers': fixture.agents_per_run - 1,
            'status': 'done', 'created_at': CREATED_AT, 'model_calls': 10,
            'tool_calls': 10, 'auto_collaborations': 0, 'max_auto_collaborations': 24,
            'collaboration_limit_reached': False, '_collaboration_blocked': False,
            'agent_ids': [], '_config': copy.deepcopy(settings.value), '_executor': NoToolExecutor(),
        }
        engine.runs[run_id] = run
        for agent_index in range(fixture.agents_per_run):
            agent_id = f'a-{run_index}-{agent_index}'
            agent = Agent(
                agent_id, run_id, 'PM' if agent_index == 0 else f'Worker {agent_index}',
                'pm' if agent_index == 0 else 'worker', 'local',
                parent_id=None if agent_index == 0 else f'a-{run_index}-0',
                status='done', turns=10, assignment=fixture_text(160),
                conversation=[{'role': 'user', 'content': fixture_text(4000)},
                              {'role': 'assistant', 'content': fixture_text(16000)}],
            )
            engine.agents[agent_id] = agent
            run['agent_ids'].append(agent_id)
            for _ in range(fixture.logs_per_agent):
                agent.logs.append({'id': next_id(), 'kind': 'assistant',
                                   'text': fixture_text(fixture.log_chars), 'thinking': '', 'at': 0.0})
            for _ in range(fixture.reports_per_agent):
                agent.results.append({'id': next_id(), 'source': 'assistant_response',
                                      'text': fixture_text(fixture.report_chars), 'truncated': False,
                                      'at': 0.0, 'turn': 10, 'revision': 1})
            agent.result_revision = 1
            for receipt_index in range(fixture.receipts_per_agent):
                agent.output_receipts.append({
                    'id': next_id(), 'tool': 'write_text', 'at': 0.0, 'turn': 10,
                    'path': f'/synthetic/work/run-{run_index}/agent-{agent_index}/file-{receipt_index}.txt',
                    'bytes': 4096, 'sha256': 'a' * 64, 'operation': 'write',
                })
    for event_index in range(fixture.events_total):
        run_index = event_index % fixture.runs
        engine.events.append({'id': next_id(), 'run_id': f'r-{run_index}',
                              'agent_id': f'a-{run_index}-0', 'kind': 'mail',
                              'text': fixture_text(160), 'at': 0.0})
    engine.sequence = sequence
    # Catch accidental expired/budget-limited fixtures that skip the conversation scan.
    if not all(engine.message_eligibility(agent)['allowed'] for agent in engine.agents.values()):
        raise AssertionError('Every fixture agent must reach the context-length admission check')


@asynccontextmanager
async def serving(directory):
    """Use real app authentication and TCP HTTP, restricted to numeric loopback."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    runner = None
    try:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.setblocking(False)
        auth = BrowserAuth(listener.getsockname()[1])
        model = NoModelClient()
        # Clear default references before Engine construction as well as populate(),
        # so eager credential registration cannot read the operator's environment.
        settings = Settings(directory)
        for profile in settings.value['providers']:
            profile['api_key_env'] = ''
        settings.value['search']['api_key_env'] = ''
        settings.save(settings.value)
        app = create_app(directory, auth, client=model)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        async with ClientSession(cookie_jar=CookieJar(unsafe=True), trust_env=False,
                                 timeout=ClientTimeout(total=10)) as client:
            async with client.post(auth.origin + '/api/bootstrap', json={}, headers={
                    'Origin': auth.origin, 'X-Workbench-Bootstrap': auth.launch_token}) as response:
                if response.status != 200:
                    raise RuntimeError(f'Fixture authentication failed: HTTP {response.status}')
                await response.read()
            yield app[APP_KEY], client, auth.origin, model
    finally:
        if runner is not None:
            await runner.cleanup()
        listener.close()


def median_ms(operation):
    operation()  # One unmeasured warmup per operation.
    measurements = []
    for _ in range(ITERATIONS):
        started = time.perf_counter_ns()
        operation()
        measurements.append((time.perf_counter_ns() - started) / 1_000_000)
    return statistics.median(measurements)


async def measure_endpoint(client, url):
    async def request():
        async with client.get(url) as response:
            payload = await response.read()
            if response.status != 200:
                raise RuntimeError(f'Benchmark endpoint failed: HTTP {response.status}')
            if response.headers.get('Content-Encoding'):
                raise AssertionError('Benchmark requires uncompressed response bodies')
            return payload

    body = await request()  # Warmup also captures the actual endpoint body.
    measurements = []
    for _ in range(ITERATIONS):
        started = time.perf_counter_ns()
        observed = await request()
        measurements.append((time.perf_counter_ns() - started) / 1_000_000)
        if observed != body:
            raise AssertionError('Fixture endpoint body changed during measurements')
    return body, statistics.median(measurements)


async def benchmark_fixture(directory, fixture, *, registry_mode=None):
    with patch.object(engine_module, 'time', SimpleNamespace(time=lambda: CREATED_AT)):
        return await _benchmark_fixture(directory, fixture, registry_mode=registry_mode)


async def _benchmark_fixture(directory, fixture, *, registry_mode=None):
    async with serving(directory) as (engine, client, origin, model):
        populate(engine, fixture)
        result = {'fixture': asdict(fixture), 'agents_total': len(engine.agents), 'views': {}}
        if registry_mode is not None:
            result['redaction_registry'] = populate_registry(engine, registry_mode)
        selections = (
            ('full', '/api/state', engine.snapshot),
            ('selected', '/api/state?view=selected&run_id=r-0&agent_id=a-0-0',
             lambda: engine.selected_snapshot(run_id='r-0', agent_id='a-0-0')),
        )
        for name, path, project in selections:
            snapshot = project()
            body, endpoint_ms = await measure_endpoint(client, origin + path)
            # Match web.json_response's actual default serializer, including ASCII escapes.
            encoded = json.dumps(snapshot).encode('utf-8')
            if body != encoded:
                raise AssertionError('Measured JSON serialization differs from actual HTTP body')
            if registry_mode is not None and any(key.encode() in body for key in registry_keys(registry_mode)):
                raise AssertionError('Synthetic credential escaped an authenticated state endpoint')
            state = json.loads(body)
            result['views'][name] = {
                'endpoint': path,
                'body_bytes': len(body),
                'snapshot_median_ms': round(median_ms(project), 6),
                'json_median_ms': round(median_ms(lambda: json.dumps(snapshot)), 6),
                'endpoint_median_ms': round(endpoint_ms, 6),
                'events_returned': len(state['events']),
                'agents_with_detail': sum('logs' in agent for agent in state['agents']),
            }
            del body, encoded, state, snapshot
        full_bytes = result['views']['full']['body_bytes']
        selected_bytes = result['views']['selected']['body_bytes']
        result['body_reduction_percent'] = round(100 * (1 - selected_bytes / full_bytes), 3)
        result['model_calls'] = model.calls
        if model.calls:
            raise AssertionError('Unexpected model calls')
        return result


def limit_address_space():
    """Apply a best-effort process address-space ceiling in the standalone CLI only."""
    report = {'requested_bytes': MEMORY_LIMIT_BYTES, 'applied': False,
              'kind': 'process_virtual_address_space', 'actual_memory_usage_measured': False}
    try:
        import resource
        if not hasattr(resource, 'RLIMIT_AS'):
            report['reason'] = 'RLIMIT_AS is unavailable on this platform'
            return report
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        candidates = [MEMORY_LIMIT_BYTES]
        candidates.extend(value for value in (soft, hard) if value != resource.RLIM_INFINITY)
        ceiling = min(candidates)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))
        report.update(applied=True, effective_bytes=ceiling)
    except (ImportError, OSError, ValueError) as error:
        report['reason'] = f'{type(error).__name__}: {error}'
    return report


async def run_benchmark(fixtures=FIXTURES, registry_modes=REDACTION_MODES):
    # Fixed fixtures and bounded iterations avoid allocating a theoretical global maximum.
    async with asyncio.timeout(30):
        with tempfile.TemporaryDirectory(prefix='workbench-state-benchmark-') as directory:
            results = [await benchmark_fixture(Path(directory) / fixture.name, fixture)
                       for fixture in fixtures]
            registry_results = [await benchmark_fixture(Path(directory) / ('registry-' + mode),
                                FIXTURES[0], registry_mode=mode) for mode in registry_modes]
    return {
        'benchmark': 'synthetic_state_projection', 'iterations': ITERATIONS, 'warmups': 1,
        'python': platform.python_version(), 'platform': platform.platform(),
        'assumptions': {
            'text_pattern': TEXT_PATTERN, 'length_unit': 'Unicode characters',
            'task_and_assignment_chars': 160, 'event_chars': 160, 'thinking_chars': 0,
            'conversation_chars_per_agent': {'user': 4000, 'assistant': 16000},
            'agent_status': 'done', 'run_status': 'done', 'turns': 10,
            'max_turns_per_agent': 100, 'max_run_seconds': 86400,
            'created_at': CREATED_AT, 'record_timestamp': 0.0,
            'timestamp_note': 'Only engine wall clock is frozen at created_at; agents are fresh and eligible; performance timings remain real.',
            'eligibility': 'Real per-agent 20,000-character conversation JSON scan runs in both projections.',
            'selection': {'run_id': 'r-0', 'agent_id': 'a-0-0'},
            'events': 'Round-robin across runs; selected endpoint returns at most the latest 100 for r-0.',
            'serializer': 'Actual aiohttp web.json_response defaults: json.dumps, ensure_ascii=True, UTF-8 body.',
            'json_timing': 'json.dumps of a prebuilt snapshot; excludes snapshot creation and UTF-8 encoding.',
            'snapshot_timing': 'Real engine projection, including redaction and message eligibility.',
            'endpoint_timing': 'Authenticated loopback GET through full body read; no JSON parse or browser rendering.',
            'body_bytes': 'Actual uncompressed response body; excludes HTTP headers and TCP overhead.',
            'fixture_storage': 'In-memory synthetic records; temporary real Settings, no saved user settings.',
            'network': '127.0.0.1 only; proxy environment ignored; no live model client or model calls.',
            'scope': 'Three bounded fixtures, not global worst-case capacity, production latency, or memory usage.',
            'redaction_registry': 'Two additional small fixtures compare 4 versus value-capacity-minus-1 synthetic exact values; one current value, the rest retained. Timings exclude initial registration/preparation. This is not a worst-case prefix or byte-capacity claim.',
        },
        'results': results,
        'redaction_registry_results': registry_results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', choices=[fixture.name for fixture in FIXTURES],
                        help='Run one bounded fixture instead of all three')
    parser.add_argument('--redaction-registry', choices=['both', 'none', *REDACTION_MODES],
                        default='both', help='Additional small registry fixtures (default: both)')
    parser.add_argument('--adversarial-redaction', action='store_true',
                        help='Only run opt-in mixed-prefix byte-capacity stress; use an external process timeout')
    args = parser.parse_args()
    memory_limit = limit_address_space()
    fixtures = tuple(fixture for fixture in FIXTURES if not args.fixture or fixture.name == args.fixture)
    try:
        modes = REDACTION_MODES if args.redaction_registry == 'both' else (() if args.redaction_registry == 'none' else (args.redaction_registry,))
        report = adversarial_registry_benchmark() if args.adversarial_redaction else asyncio.run(run_benchmark(fixtures, modes))
    except (MemoryError, TimeoutError) as error:
        print(json.dumps({'error': type(error).__name__, 'memory_limit': memory_limit}), file=sys.stderr)
        return 1
    report['memory_limit'] = memory_limit
    # ASCII-escaped JSON also works when Windows redirects a legacy code-page stdout.
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
