"""Synthetic adapter telemetry; no real provider, credential store or model."""
import asyncio
import copy
import inspect
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from workbench.provider_observation import observe_provider, observation_phase, observed_provider_call
from workbench.providers import ProviderClient, ProviderError, ProviderTimeoutError, ProviderOutputLimitError
from workbench.resources import ResourceGate, ResourceError
from test_providers import fake_server


def profile(kind='local', **extra):
    return {'kind': kind, 'model': 'synthetic-model', 'api_key': 'synthetic-secret',
            'base_url': 'http://127.0.0.1:1234/v1' if kind == 'local' else 'https://example.test/v1', **extra}


def response(kind='local', usage=None):
    if kind == 'local':
        body = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'Done'}}]}
    elif kind == 'openai':
        body = {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'Done'}]}]}
    else:
        body = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'Done'}]}
    return {**body, 'usage': usage or {}}


async def invoke(client, kind='local', limits=None, **extra):
    return await client.complete(profile(kind, **extra), [{'role': 'user', 'content': 'private request'}],
                                 [], 'private system', limits or {}, conversation_id='private-conversation')


def phases(events):
    return [row['phase'] for row in events]


@pytest.mark.parametrize('kind', ['local', 'openai', 'anthropic'])
async def test_observed_actual_adapter_preserves_response_and_truthful_phases(monkeypatch, kind):
    client, events, posts = ProviderClient(), [], []
    async def post(*args):
        posts.append(copy.deepcopy(args))
        assert events[-1]['phase'] == 'response_wait'
        return response(kind, {'input_tokens': 7, 'output_tokens': 2})
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(events.append):
        reply = await invoke(client, kind, {'request_timeout_seconds': 37, 'local': {'queue_timeout_seconds': 23}})
    expected = ['queue_wait', 'admitted'] if kind == 'local' else []
    assert phases(events) == expected + ['response_wait', 'received', 'parse', 'completed']
    assert reply.text == 'Done' and len(posts) == 1
    assert len({row['call_id'] for row in events}) == 1
    assert [row['sequence'] for row in events] == list(range(1, len(events) + 1))
    assert events[-1]['terminal'] is True and not any(row['terminal'] for row in events[:-1])
    assert events[-1]['usage'] == {'input_tokens': 7, 'output_tokens': 2}
    assert events[-1]['provider_kind'] == kind and events[-1]['request_timeout_seconds'] == 37
    assert events[-1]['queue_timeout_seconds'] == (23 if kind == 'local' else None)
    assert all(row['phase_started_at'] == row['observed_at'] for row in events)
    assert all(row['elapsed_seconds'] >= 0 and row['phase_elapsed_seconds'] == 0 for row in events)
    serialized = json.dumps(events)
    for private in ('private request', 'private system', 'synthetic-secret', 'example.test', '127.0.0.1',
                    'synthetic-model', 'private-conversation'):
        assert private not in serialized


async def test_no_observer_does_not_change_payload_headers_limits_or_return(monkeypatch):
    client, posted = ProviderClient(), []
    async def post(*args):
        posted.append(copy.deepcopy(args))
        return response()
    monkeypatch.setattr(client, '_post', post)
    plain = await invoke(client)
    events = []
    with observe_provider(events.append):
        observed = await invoke(client)
    assert plain == observed and posted[0] == posted[1]
    assert 'conversation_id' in inspect.signature(client.complete).parameters
    assert not {'observer', 'observation'} & inspect.signature(client.complete).parameters.keys()
    await invoke(client)
    assert len(events) == 6


async def test_queue_wait_is_visible_before_admission_then_response_wait(monkeypatch):
    gate, events, release, entered = ResourceGate(), [], asyncio.Event(), asyncio.Event()
    client = ProviderClient(gate)
    async def post(*args):
        entered.set()
        await release.wait()
        return response()
    monkeypatch.setattr(client, '_post', post)
    async with gate.slot({'max_concurrent_requests': 1}):
        with observe_provider(events.append):
            task = asyncio.create_task(invoke(client))
        for _ in range(10):
            if events:
                break
            await asyncio.sleep(0)
        assert phases(events) == ['queue_wait'] and not entered.is_set()
        assert gate.snapshot()['queued'] == 1
    await entered.wait()
    assert phases(events) == ['queue_wait', 'admitted', 'response_wait']
    release.set()
    await task
    assert phases(events)[-3:] == ['received', 'parse', 'completed']
    assert gate.snapshot()['active'] == gate.snapshot()['queued'] == 0


@pytest.mark.parametrize('when', ['queue', 'response'])
async def test_cancellation_reports_real_phase_and_releases_gate(monkeypatch, when):
    gate, events, entered = ResourceGate(), [], asyncio.Event()
    client = ProviderClient(gate)
    async def post(*args):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(client, '_post', post)
    async def cancel_one():
        with observe_provider(events.append):
            task = asyncio.create_task(invoke(client))
        if when == 'response':
            await entered.wait()
        else:
            for _ in range(10):
                if events:
                    break
                await asyncio.sleep(0)
            assert not entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    if when == 'queue':
        async with gate.slot():
            await cancel_one()
    else:
        await cancel_one()
    assert events[-1]['phase'] == 'cancelled' and events[-1]['terminal']
    assert events[-1]['previous_phase'] == ('queue_wait' if when == 'queue' else 'response_wait')
    assert events[-1]['error_type'] == 'cancelled'
    assert gate.snapshot()['active'] == gate.snapshot()['queued'] == 0


@pytest.mark.parametrize('error,code', [
    (ProviderTimeoutError('secret timeout'), 'provider_timeout'),
    (ProviderError('secret connection'), 'provider_error'),
    (RuntimeError('secret unexpected'), 'unexpected_error'),
])
async def test_provider_failure_classification_preserves_exception_and_no_retry(monkeypatch, error, code):
    client, events, posts = ProviderClient(), [], []
    async def post(*args):
        posts.append(args)
        raise error
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(events.append), pytest.raises(type(error)) as caught:
        await invoke(client)
    assert caught.value is error and len(posts) == 1
    assert phases(events) == ['queue_wait', 'admitted', 'response_wait', 'error']
    assert events[-1]['error_type'] == code and events[-1]['terminal']
    assert 'secret' not in json.dumps(events)


async def test_parse_output_limit_remains_typed_failure(monkeypatch):
    client, events = ProviderClient(), []
    async def post(*args):
        return {'choices': [{'finish_reason': 'length', 'message': {'role': 'assistant', 'content': 'partial'}}]}
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(events.append), pytest.raises(ProviderOutputLimitError):
        await invoke(client)
    assert phases(events)[-3:] == ['received', 'parse', 'error']
    assert events[-1]['error_type'] == 'provider_output_limit'
    assert 'completed' not in phases(events)


async def test_queue_timeout_is_not_mislabeled_as_http_timeout(monkeypatch):
    gate, events = ResourceGate(), []
    client = ProviderClient(gate)
    async def forbidden(*args):
        raise AssertionError('HTTP must not start without admission')
    monkeypatch.setattr(client, '_post', forbidden)
    async with gate.slot():
        with observe_provider(events.append), pytest.raises(ResourceError):
            await invoke(client, limits={'local': {'queue_timeout_seconds': .01}})
    assert phases(events) == ['queue_wait', 'error']
    assert events[-1]['error_type'] == 'resource_error'
    assert gate.snapshot()['active'] == gate.snapshot()['queued'] == 0


async def test_existing_retry_sequence_and_count_are_unchanged(monkeypatch):
    client, events, posted = ProviderClient(), [], []
    async def post(*args):
        posted.append(args)
        if len(posted) == 1:
            raise ProviderError('secret 503 details', status=503, retryable=True)
        return response()
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(events.append):
        reply = await invoke(client, limits={'local': {'max_retries': 1, 'retry_backoff_seconds': 0}})
    assert reply.text == 'Done' and len(posted) == 2
    assert phases(events) == ['queue_wait', 'admitted', 'response_wait', 'error', 'retry_wait',
                              'queue_wait', 'admitted', 'response_wait', 'received', 'parse', 'completed']
    assert not events[3]['terminal'] and events[4]['retry_after_seconds'] == 0
    assert events[-1]['attempt'] == events[-1]['attempt_limit'] == 2
    assert posted[0] == posted[1]


@pytest.mark.parametrize('error', [ValueError('observer secret'), asyncio.CancelledError(), SystemExit('observer')],
                         ids=['exception', 'cancelled-error', 'system-exit'])
async def test_callback_failure_never_changes_provider_result_or_retry(monkeypatch, error):
    client, posts = ProviderClient(), []
    async def post(*args):
        posts.append(args)
        return response()
    def broken(event):
        raise error
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(broken):
        result = await invoke(client)
    assert result.text == 'Done' and len(posts) == 1
    assert client.resource_gate.snapshot()['active'] == 0


async def test_callback_mutation_and_reentrant_phase_calls_do_not_rewrite_later_events(monkeypatch):
    client, events = ProviderClient(), []
    async def post(*args):
        return response(usage={'prompt_tokens': 12})
    def sink(event):
        events.append(copy.deepcopy(event))
        event.update(phase='forged', attempt_limit=1000)
        observation_phase('error', error=RuntimeError('forged recursive event'))
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(sink):
        await invoke(client)
    assert len(events) == 6 and events[-1]['phase'] == 'completed'
    assert all(row['attempt_limit'] == 1 for row in events)


async def test_nested_scopes_and_nested_complete_calls_restore_outer_sink(monkeypatch):
    outer, inner = ProviderClient(), ProviderClient()
    out_events, in_events = [], []
    async def inner_post(*args):
        return response()
    async def outer_post(*args):
        with observe_provider(in_events.append):
            await invoke(inner)
        with observe_provider(None):
            await invoke(inner)
        return response()
    monkeypatch.setattr(outer, '_post', outer_post)
    monkeypatch.setattr(inner, '_post', inner_post)
    with observe_provider(out_events.append):
        await invoke(outer)
    assert len(out_events) == len(in_events) == 6
    assert len({row['call_id'] for row in out_events}) == len({row['call_id'] for row in in_events}) == 1
    assert out_events[0]['call_id'] != in_events[0]['call_id']
    assert out_events[-1]['phase'] == in_events[-1]['phase'] == 'completed'


async def test_concurrent_contexts_do_not_mix_callbacks_or_call_ids(monkeypatch):
    client = ProviderClient()
    events = [[], []]
    entered, release, count = asyncio.Event(), asyncio.Event(), 0
    async def post(*args):
        nonlocal count
        count += 1
        if count == 2:
            entered.set()
        await release.wait()
        return response()
    monkeypatch.setattr(client, '_post', post)
    async def one(index):
        with observe_provider(events[index].append):
            return await invoke(client, limits={'local': {'max_concurrent_requests': 2}})
    tasks = [asyncio.create_task(one(index)) for index in range(2)]
    await entered.wait()
    assert all(phases(rows) == ['queue_wait', 'admitted', 'response_wait'] for rows in events)
    release.set()
    await asyncio.gather(*tasks)
    assert all(len(rows) == 6 for rows in events)
    assert events[0][0]['call_id'] != events[1][0]['call_id']


async def test_usage_is_known_bounded_numeric_only_and_returned_usage_is_unchanged(monkeypatch):
    usage = {'prompt_tokens': 42, 'completion_tokens': True, 'total_tokens': -1,
             'input_tokens': 10 ** 30, 'output_tokens': 2.5, 'secret': 'never copy',
             'prompt_tokens_details': {'cached_tokens': 3, 'secret': 'never copy'},
             'completion_tokens_details': {'reasoning_tokens': 0, 'audio_tokens': float('inf')}}
    client, events = ProviderClient(), []
    async def post(*args):
        return response(usage=copy.deepcopy(usage))
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(events.append):
        reply = await invoke(client)
    assert reply.usage == usage
    assert events[-1]['usage'] == {'prompt_tokens': 42,
        'prompt_tokens_details': {'cached_tokens': 3}, 'completion_tokens_details': {'reasoning_tokens': 0}}
    assert 'never copy' not in json.dumps(events)


async def test_observation_elapsed_uses_monotonic_clock_even_when_wallclock_moves_back(monkeypatch):
    import workbench.provider_observation as observation
    clock = {'wall': 1000.0, 'mono': 10.0}
    monkeypatch.setattr(observation, 'time', SimpleNamespace(
        time=lambda: clock['wall'], monotonic=lambda: clock['mono']))
    @observed_provider_call
    async def scripted():
        observation_phase('queue_wait')
        clock.update(wall=900.0, mono=14.0)
        observation_phase('response_wait')
        clock.update(wall=901.0, mono=20.0)
        return SimpleNamespace(usage={})
    events = []
    with observe_provider(events.append):
        await scripted()
    assert events[1]['phase_started_at'] == 900
    assert events[1]['elapsed_seconds'] == events[1]['previous_phase_elapsed_seconds'] == 4
    assert events[-1]['elapsed_seconds'] == 10 and events[-1]['previous_phase_elapsed_seconds'] == 6


async def test_managed_copilot_observation_uses_its_separate_admission_without_protocol_change(monkeypatch):
    client, events = ProviderClient(), []
    async def post(*args):
        assert client.resource_gate.snapshot()['active'] == 0
        assert client.copilot_resource_gate.snapshot()['active'] == 1
        return response()
    monkeypatch.setattr(client, '_post', post)
    with observe_provider(events.append):
        reply = await invoke(client, id='copilot-agent', _copilot_agent=True)
    assert reply.text == 'Done' and all(row['admission_kind'] == 'copilot' for row in events)


async def test_invalid_configuration_error_remains_original_and_does_not_expose_input():
    events = []
    with observe_provider(events.append), pytest.raises(ProviderError):
        await invoke(ProviderClient(), kind='secret-unsupported-kind')
    assert phases(events) == ['error'] and events[0]['provider_kind'] == 'unknown'
    assert 'secret-unsupported-kind' not in json.dumps(events)


async def test_real_loopback_http_path_has_received_parse_and_terminal_usage():
    requests, events = [], []
    async def handler(request):
        requests.append(await request.json())
        return web.json_response(response(usage={'prompt_tokens': 3, 'completion_tokens': 1}))
    async with fake_server(handler) as url:
        with observe_provider(events.append):
            reply = await invoke(ProviderClient(), base_url=url)
    assert reply.text == 'Done' and len(requests) == 1
    assert phases(events) == ['queue_wait', 'admitted', 'response_wait', 'received', 'parse', 'completed']
    assert events[-1]['usage'] == {'prompt_tokens': 3, 'completion_tokens': 1}
