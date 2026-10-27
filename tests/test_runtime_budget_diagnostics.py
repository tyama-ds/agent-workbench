"""Shared limit diagnostics with fake providers and temporary public archives only."""
import asyncio
import copy
import json
import time

import pytest

from workbench.engine import Engine, RuntimeBudgetError
from workbench.context import groups, pressure
from workbench.history import HistoryError, HistoryStore, archived_view, redact_document, validate
from workbench.providers import ProviderClient, ProviderError, ProviderTimeoutError
from test_context_compaction import call_args, seeded, summary_reply
from test_engine import ScriptClient, configured, reply, settled, start
from test_history_persistence import document


async def paused(tmp_path, client=None, **limits):
    client = client or ScriptClient([])
    engine, work = configured(tmp_path, client)
    engine.settings.value['limits'].update(limits)
    engine.kick = lambda agent: None
    run, agent = await start(engine, delegation_level=0)
    return engine, run, agent, work


class CapturedDispatchClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        self.calls.append({'system': system, 'messages': copy.deepcopy(messages),
                          'pressure': pressure(profile, messages, tools, system, limits),
                          'conversation_id': conversation_id})
        return self.responses.pop(0)


@pytest.mark.parametrize('change', ['counter_digits', 'clock_digits'])
async def test_final_dispatch_measures_exact_dynamic_policy_at_hard_cap(tmp_path, monkeypatch, change):
    client = CapturedDispatchClient([reply('Bounded fake completion')])
    engine, run, agent, _ = await paused(tmp_path, client, max_model_calls=100,
                                        max_context_chars=50000, auto_compact=False)
    clock = [run['created_at'] + 1]
    monkeypatch.setattr('workbench.engine.time.time', lambda: clock[0])
    try:
        run['model_calls'] = 9  # The next charged work call crosses a decimal boundary.
        agent.pending.clear()
        engine._append_context(agent, {'role': 'user', 'content': agent.assignment}, human=True)
        profile, tools, limits = call_args(engine, run, agent)
        text = 'Keep this exact human constraint: '
        candidate = [*agent.conversation, {'role': 'user', 'content': text}]
        _, chars, _ = pressure(profile, candidate, tools, engine._policy(run, agent), limits)
        text += 'x' * (limits['max_context_chars'] - chars)
        candidate[-1]['content'] = text
        assert pressure(profile, candidate, tools, engine._policy(run, agent), limits)[1] == 50000
        agent.pending.append((text, True))
        original_ensure = engine._ensure_context
        measured = []

        async def ensure_then_observe(*args):
            await original_ensure(*args)
            measured.append(agent.context_chars)
            if change == 'clock_digits':
                clock[0] = run['created_at'] + 1.123456789

        monkeypatch.setattr(engine, '_ensure_context', ensure_then_observe)
        await engine._agent_loop(agent)
        assert measured == [50000]
        # This inspects the actual fake-provider dispatch, not a separately built policy.
        assert all(call['pressure'][0] <= 1 and call['pressure'][1] <= 50000 for call in client.calls), [call['pressure'] for call in client.calls]
        assert agent.conversation[0]['content'] == agent.assignment
        assert any(row.get('_human') and row['content'] == text for row in agent.conversation)
        assert agent.compactions == agent.fallback_compactions == 0
        assert run['tool_calls'] == 0 and not agent.output_receipts
        if change == 'counter_digits':
            assert len(client.calls) == 1 and run['model_calls'] == 10 and agent.status == 'done'
            observed = json.loads(client.calls[0]['system'].split('Verified runtime identity and user-selected scope:\n')[1])
            assert observed['budget']['model_calls']['used'] == 9  # Explicit pre-dispatch observation.
            assert client.calls[0]['pressure'][1] == agent.context_chars == 50000
        else:
            assert client.calls == [] and run['model_calls'] == 9 and agent.status == 'error'
            assert not agent.results  # A newly oversized pinned request is neither sent nor called complete.
    finally:
        await engine.close()


@pytest.mark.parametrize('summary_kind', ['valid', 'invalid'])
async def test_post_summary_dispatch_remeasures_updated_policy_and_reuses_its_exact_bytes(tmp_path, monkeypatch, summary_kind):
    client = CapturedDispatchClient([summary_reply() if summary_kind == 'valid' else reply('Not a usable JSON summary'),
                                    reply('Verified fake continuation')])
    engine, run, agent = await seeded(tmp_path, client)
    clock = [run['created_at'] + 1]
    monkeypatch.setattr('workbench.engine.time.time', lambda: clock[0])
    measurements = []

    def measured_pressure(profile, messages, tools, system, limits, **kwargs):
        result = pressure(profile, messages, tools, system, limits, **kwargs)
        measurements.append((system, result))
        return result

    monkeypatch.setattr('workbench.engine.pressure', measured_pressure)
    original_complete = client.complete

    async def complete_then_advance(*args, **kwargs):
        result = await original_complete(*args, **kwargs)
        if kwargs.get('conversation_id') is None:
            clock[0] = run['created_at'] + 12.123456789
        else:
            client.calls[-1]['measurement_at_dispatch'] = measurements[-1]
        return result

    monkeypatch.setattr(client, 'complete', complete_then_advance)
    try:
        agent.pending.append(('Preserve the original task; finish with available evidence.', True))
        await engine._agent_loop(agent)
        assert len(client.calls) == run['model_calls'] == 2 and run['tool_calls'] == 0
        assert agent.compactions == 1 and agent.fallback_compactions == int(summary_kind == 'invalid') and agent.status == 'done'
        work = client.calls[1]
        assert work['conversation_id'] == f'{run["id"]}/{agent.id}'
        assert (work['system'], work['pressure']) == work['measurement_at_dispatch']
        identity = json.loads(work['system'].split('Verified runtime identity and user-selected scope:\n')[1])
        assert identity['budget']['model_calls']['used'] == 1  # Summary charged; work not yet charged.
        assert identity['budget']['observed_at'] == clock[0]
        assert work['pressure'][0] <= 1 and work['pressure'][1] == agent.context_chars
        assert any(row.get('_summary') for row in work['messages'])
        assert work['messages'][0]['content'] == agent.assignment
        assert work['messages'][-1]['content'] == 'Preserve the original task; finish with available evidence.'
    finally:
        await engine.close()


@pytest.mark.parametrize('auto_compact', [True, False])
async def test_final_policy_overflow_preserves_native_group_and_human_pins(tmp_path, monkeypatch, auto_compact):
    client = CapturedDispatchClient([reply('Verified bounded continuation')])
    engine, run, agent, _ = await paused(tmp_path, client, max_context_chars=50000,
                                        max_model_calls=100, auto_compact=auto_compact,
                                        context_recent_groups=6)
    clock = [run['created_at'] + 1]
    monkeypatch.setattr('workbench.engine.time.time', lambda: clock[0])
    try:
        run['model_calls'] = 9
        agent.pending.clear()
        engine._append_context(agent, {'role': 'user', 'content': agent.assignment}, human=True)
        call = {'id': 'native-boundary', 'name': 'list_team', 'arguments': {}}
        native = {'provider': 'local', 'model': 'fixture', 'message': {'role': 'assistant', 'content': '',
            'reasoning_content': 'preserve exact native original', 'tool_calls': [
                {'id': call['id'], 'type': 'function', 'function': {'name': call['name'], 'arguments': '{}'}}]}}
        engine._append_context(agent, {'role': 'assistant', 'content': '', 'tool_calls': [call], 'provider_raw': native})
        engine._append_context(agent, {'role': 'tool', 'tool_call_id': call['id'], 'content': 'Old observation: ' + 'd' * 8000})
        original = copy.deepcopy(agent.original_history)
        profile, tools, limits = call_args(engine, run, agent)
        text = 'Exact latest human instructions, not peer authority: '
        candidate = [*agent.conversation, {'role': 'user', 'content': text}]
        chars = pressure(profile, candidate, tools, engine._policy(run, agent), limits)[1]
        text += 'x' * (50000 - chars)
        candidate[-1]['content'] = text
        assert pressure(profile, candidate, tools, engine._policy(run, agent), limits)[1] == 50000
        agent.pending.append((text, True))
        ensure = engine._ensure_context

        async def advance_after_ensure(*args):
            await ensure(*args)
            assert agent.compactions == 0 and agent.context_chars == 50000
            clock[0] = run['created_at'] + 1.123456789

        monkeypatch.setattr(engine, '_ensure_context', advance_after_ensure)
        await engine._agent_loop(agent)
        groups(agent.conversation)  # Never split a native assistant/tool batch.
        assert list(agent.original_history)[:len(original)] == list(original)
        assert agent.conversation[0]['content'] == agent.assignment
        assert any(row.get('_human') and row['content'] == text for row in agent.conversation)
        assert run['tool_calls'] == 0 and not agent.output_receipts
        if auto_compact:
            assert len(client.calls) == 1 and run['model_calls'] == 10 and agent.status == 'done'
            assert agent.compactions == agent.fallback_compactions == 1
            assert client.calls[0]['pressure'][0] <= 1 and client.calls[0]['pressure'][1] == agent.context_chars
            assert any(row.get('_fallback') for row in client.calls[0]['messages'])
            assert not any(row.get('tool_call_id') == call['id'] or row.get('tool_calls') for row in client.calls[0]['messages'])
        else:
            assert not client.calls and run['model_calls'] == 9 and agent.status == 'error'
            assert agent.compactions == agent.fallback_compactions == 0 and not agent.results
            assert agent.conversation[1]['provider_raw'] == native
            assert agent.conversation[2]['tool_call_id'] == call['id']
    finally:
        await engine.close()


async def test_live_budget_is_shared_original_config_and_readonly_in_both_projections(tmp_path, monkeypatch):
    engine, run, agent, _ = await paused(tmp_path, max_model_calls=8, max_tool_calls=12, max_run_seconds=60)
    try:
        run.update(model_calls=3, tool_calls=4)
        child = engine._new_agent(run, 'local', 'research', agent.id, assignment='Check selected fields')
        monkeypatch.setattr('workbench.engine.time.time', lambda: run['created_at'] + 17.5)
        engine.settings.value['limits'].update(max_model_calls=999, max_tool_calls=1000, max_run_seconds=3600)
        sequence, calls = engine.sequence, (run['model_calls'], run['tool_calls'])
        full = engine.snapshot()['runs'][0]
        selected = engine.selected_snapshot(run_id=run['id'], agent_id=child.id)['runs'][0]
        budget = full['budget']
        assert selected['budget'] == budget
        assert budget['shared'] is True and budget['started_at'] == run['created_at']
        assert budget['observed_at'] == run['created_at'] + 17.5
        assert budget['model_calls'] == {'used': 3, 'limit': 8, 'remaining': 5}
        assert budget['tool_calls'] == {'used': 4, 'limit': 12, 'remaining': 8}
        assert budget['time'] == {'used_seconds': 17.5, 'limit_seconds': 60, 'remaining_seconds': 42.5}
        for member in (agent, child):
            identity = json.loads(engine._policy(run, member).split('Verified runtime identity and user-selected scope:\n')[1])
            assert identity['budget'] == budget
        assert (await engine.execute_tool(run, agent, 'list_team', {}))['budget'] == budget
        assert engine.sequence == sequence and calls == (run['model_calls'], run['tool_calls'])
        full['budget']['model_calls']['used'] = 777
        assert engine.snapshot()['runs'][0]['budget']['model_calls']['used'] == 3
    finally:
        await engine.close()


async def test_terminal_observation_freezes_and_human_continue_does_not_refill(tmp_path, monkeypatch):
    engine, run, agent, _ = await paused(tmp_path, max_run_seconds=60)
    clock = [run['created_at'] + 10]
    monkeypatch.setattr('workbench.engine.time.time', lambda: clock[0])
    try:
        agent.pending.clear()
        agent.status = 'done'
        run['model_calls'] = 3
        engine._run_status(run)
        before = engine.snapshot()['runs'][0]['budget']
        clock[0] += 20
        assert engine.snapshot()['runs'][0]['budget'] == before
        await engine.human_message(agent.id, 'Continue with existing findings only')
        current = engine.snapshot()['runs'][0]['budget']
        assert current['time']['used_seconds'] == 30 and current['time']['remaining_seconds'] == 30
        assert current['model_calls'] == before['model_calls']
        await engine.stop_run(run['id'])
        stopped = engine.snapshot()['runs'][0]['budget']
        clock[0] += 100
        assert engine.snapshot()['runs'][0]['budget'] == stopped
    finally:
        await engine.close()


async def test_waiting_error_keeps_elapsed_budget_and_reports_distinct_teammate_causes(tmp_path, monkeypatch):
    engine, run, agent, _ = await paused(tmp_path, max_run_seconds=60)
    try:
        child = engine._new_agent(run, 'local', 'research', agent.id, assignment='Check selected fields')
        for member, reason in ((agent, 'model_limit'), (child, 'provider_timeout')):
            member.pending.clear()
            member.status = 'error'
            member.stop_reason = reason
        monkeypatch.setattr('workbench.engine.time.time', lambda: run['created_at'] + 10)
        engine._run_status(run)
        before = engine.snapshot()['runs'][0]
        assert before['status'] == 'waiting' and before['status_reason'] == 'error'
        assert before['stop_reason'] == 'multiple'
        assert before['stop_reasons'] == ['model_limit', 'provider_timeout']
        monkeypatch.setattr('workbench.engine.time.time', lambda: run['created_at'] + 20)
        after = engine.snapshot()['runs'][0]['budget']
        assert after['time']['used_seconds'] == 20 and after['time']['remaining_seconds'] == 40
        assert after['model_calls'] == before['budget']['model_calls']
        stored, _ = engine.history.read(run['id'])
        assert stored['run']['budget'] == before['budget']
        assert stored['run']['stop_reasons'] == before['stop_reasons']
        assert [row['stop_reason'] for row in stored['agents']] == ['model_limit', 'provider_timeout']
    finally:
        await engine.close()


async def test_late_peer_mail_unfreezes_observation_without_refilling_budget(tmp_path, monkeypatch):
    engine, run, agent, _ = await paused(tmp_path, max_run_seconds=60)
    try:
        agent.pending.clear()
        agent.status = 'done'
        run['model_calls'] = 2
        monkeypatch.setattr('workbench.engine.time.time', lambda: run['created_at'] + 10)
        engine._run_status(run)
        monkeypatch.setattr('workbench.engine.time.time', lambda: run['created_at'] + 25)
        engine.enqueue(agent, 'Peer evidence, not human authority')
        snapshot = engine.snapshot()['runs'][0]['budget']
        assert snapshot['time']['used_seconds'] == 25 and snapshot['time']['remaining_seconds'] == 35
        assert snapshot['model_calls']['used'] == 2 and agent.status == 'queued'
    finally:
        await engine.close()


@pytest.mark.parametrize('reason', ['model_limit', 'time_limit', 'turn_limit'])
async def test_exhaustion_before_dispatch_never_starts_provider(tmp_path, reason):
    engine, run, agent, _ = await paused(tmp_path, max_model_calls=2, max_run_seconds=10)
    try:
        if reason == 'model_limit': run['model_calls'] = 2
        elif reason == 'time_limit': run['created_at'] -= 11
        else: agent.turns = run['_config']['limits']['max_turns_per_agent']
        await engine._agent_loop(agent)
        assert engine.client.calls == [] and agent.status == 'error'
        assert agent.stop_reason == reason and run['status'] == 'waiting'
        state = engine.snapshot()
        assert state['agents'][0]['stop_reason'] == reason
        assert state['runs'][0]['stop_reason'] == reason and state['runs'][0]['stop_reasons'] == [reason]
        assert not agent.results and not agent.output_receipts
    finally:
        await engine.close()


async def test_tool_budget_closes_batch_without_extra_tool_or_model_call(tmp_path):
    client = ScriptClient([reply(calls=[('list_team', {}), ('write_text', {
        'path': 'must-not-exist.txt', 'text': 'no', 'expected_sha256': 'missing'})])])
    engine, run, agent, work = await paused(tmp_path, client, max_tool_calls=1)
    try:
        await engine._agent_loop(agent)
        assert agent.stop_reason == 'tool_limit' and agent.status == 'error'
        assert run['model_calls'] == len(client.calls) == 1 and run['tool_calls'] == 1
        assert len([row for row in agent.conversation if row['role'] == 'tool']) == 2
        assert not (work / 'must-not-exist.txt').exists() and not agent.results
        assert engine.snapshot()['runs'][0]['budget']['tool_calls']['remaining'] == 0
    finally:
        await engine.close()


async def test_last_allowed_call_may_finish_but_never_gets_refilled(tmp_path):
    client = ScriptClient([reply('Verified existing evidence; no new output requested.')])
    engine, run, agent, _ = await paused(tmp_path, client, max_model_calls=1)
    try:
        await engine._agent_loop(agent)
        assert agent.status == run['status'] == 'done' and agent.stop_reason == ''
        assert run['model_calls'] == len(client.calls) == 1
        assert engine.snapshot()['runs'][0]['budget']['model_calls']['remaining'] == 0
        with pytest.raises(ValueError, match='モデル呼び出し回数'):
            await engine.human_message(agent.id, 'One more')
        assert run['model_calls'] == 1 and len(client.calls) == 1
    finally:
        await engine.close()


class HangingClient:
    def __init__(self):
        self.calls = 0
        self.cancelled = False
        self.entered = asyncio.Event()

    async def complete(self, *args, **kwargs):
        self.calls += 1
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class ControlledDeadline:
    """Keep the real owning Timeout; expire only after the fake work is entered."""
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.owner = None
        self.deadlines = []
        real_timeout = asyncio.timeout
        def observed_timeout(delay):
            deadline = real_timeout(delay)
            if asyncio.current_task() is self.owner:
                self.deadlines.append(deadline)
            return deadline
        monkeypatch.setattr('workbench.engine.asyncio.timeout', observed_timeout)

    async def expire_after_entry(self, entered, run):
        await asyncio.wait_for(entered.wait(), 5)
        assert self.owner is not None and not self.owner.done() and self.deadlines
        # Align the server clock with the triggered deadline; do not alter the
        # configured limit or original run start. The production expired() branch
        # and actual task cancellation still execute on a real asyncio Timeout.
        expired_at = run['created_at'] + run['_config']['limits']['max_run_seconds'] + 1
        self.monkeypatch.setattr('workbench.engine.time.time', lambda: expired_at)
        self.deadlines[-1].reschedule(asyncio.get_running_loop().time() - 1)

    async def cleanup(self):
        if self.owner is not None:
            if not self.owner.done():
                self.owner.cancel()
            await asyncio.gather(self.owner, return_exceptions=True)


async def test_outer_run_deadline_cancels_fake_provider_and_has_own_reason(tmp_path, monkeypatch):
    client = HangingClient()
    engine, run, agent, _ = await paused(tmp_path, client, max_run_seconds=60)
    clock = ControlledDeadline(monkeypatch)
    try:
        clock.owner = asyncio.create_task(engine._agent_loop(agent))
        await clock.expire_after_entry(client.entered, run)
        await asyncio.wait_for(clock.owner, 5)
        assert client.calls == run['model_calls'] == 1 and client.cancelled
        assert agent.stop_reason == 'time_limit' and agent.status == 'error'
        assert '作業全体' in agent.last_error and not agent.results
        assert engine.snapshot()['runs'][0]['budget']['time']['remaining_seconds'] == 0
    finally:
        await clock.cleanup()
        await engine.close()


@pytest.mark.parametrize('failure,expected', [
    (ProviderTimeoutError('Provider request timed out; no automatic retry'), 'provider_timeout'),
    (ProviderError('Provider request timed out; no automatic retry'), ''),
    (TimeoutError('untyped external timeout'), ''),
    (ValueError('実行時間またはモデル呼び出し回数の上限です'), ''),
])
async def test_typed_provider_timeout_is_not_inferred_from_unknown_error_text(tmp_path, failure, expected):
    async def fail(*args):
        raise failure
    client = ScriptClient([fail])
    engine, run, agent, _ = await paused(tmp_path, client)
    try:
        await engine._agent_loop(agent)
        assert agent.status == 'error' and agent.stop_reason == expected
        assert agent.last_error == str(failure)
        assert len(client.calls) == run['model_calls'] == 1 and not agent.results
        assert engine.snapshot()['runs'][0]['budget']['time']['remaining_seconds'] > 0
    finally:
        await engine.close()


async def test_http_timeout_is_typed_at_transport_and_never_replayed(monkeypatch):
    sessions = []
    class TimedOutSession:
        def __init__(self, **kwargs): sessions.append(kwargs)
        async def __aenter__(self): raise asyncio.TimeoutError
        async def __aexit__(self, *args): pass
    monkeypatch.setattr('workbench.providers.aiohttp.ClientSession', TimedOutSession)
    with pytest.raises(ProviderTimeoutError, match='no automatic retry') as caught:
        await ProviderClient().complete({'kind': 'openai', 'model': 'fixture', 'api_key': 'synthetic',
            'request_timeout_seconds': 12, 'max_retries': 3}, [], [], '', {})
    assert caught.value.retryable is False and len(sessions) == 1
    assert sessions[0]['timeout'].total == 12


async def test_summary_counts_against_same_budget_and_reserves_no_extra_calls(tmp_path):
    client = ScriptClient([summary_reply()])
    engine, run, agent = await seeded(tmp_path, client)
    try:
        run['_config']['limits']['max_model_calls'] = 4
        run['model_calls'] = 2
        await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert run['model_calls'] == 3 and len(client.calls) == 1 and agent.compactions == 1
        assert engine.snapshot()['runs'][0]['budget']['model_calls'] == {'used': 3, 'limit': 4, 'remaining': 1}
    finally:
        await engine.close()


async def test_summary_provider_timeout_preserves_originals_without_retry(tmp_path):
    async def fail(*args): raise ProviderTimeoutError('Provider request timed out; no automatic retry')
    client = ScriptClient([fail])
    engine, run, agent = await seeded(tmp_path, client)
    try:
        before = copy.deepcopy((agent.conversation, agent.original_history))
        with pytest.raises(ProviderTimeoutError):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert (agent.conversation, agent.original_history) == before
        assert len(client.calls) == run['model_calls'] == 1
        assert agent.compactions == agent.fallback_compactions == 0 and not agent.compacting
    finally:
        await engine.close()


@pytest.mark.parametrize('name', ['web_search', 'web_fetch', 'web_read'])
async def test_web_routes_obey_remaining_overall_deadline_without_retry(tmp_path, name, monkeypatch):
    engine, run, agent, _ = await paused(tmp_path, max_run_seconds=60)
    client = HangingClient()
    clock = ControlledDeadline(monkeypatch)
    class FakeWeb:
        async def execute(self, tool, args):
            assert tool == name
            return await client.complete()
    try:
        run['_config']['search']['enabled'] = True
        run['_web'] = FakeWeb()
        clock.owner = asyncio.create_task(engine.execute_tool(run, agent, name, {}))
        await clock.expire_after_entry(client.entered, run)
        with pytest.raises(RuntimeBudgetError) as caught:
            await asyncio.wait_for(clock.owner, 5)
        assert caught.value.reason == 'time_limit' and client.calls == 1 and client.cancelled
        assert run['model_calls'] == run['tool_calls'] == 0  # Dispatcher charges calls, not this tool boundary.
    finally:
        await clock.cleanup()
        await engine.close()


async def test_expired_web_request_closes_sibling_tool_without_false_file_completion(tmp_path, monkeypatch):
    client = ScriptClient([reply(calls=[('web_fetch', {'url': 'https://example.test/data'}),
        ('write_text', {'path': 'later.txt', 'text': 'not verified', 'expected_sha256': 'missing'})])])
    engine, run, agent, work = await paused(tmp_path, client, max_run_seconds=60)
    hanging = HangingClient()
    clock = ControlledDeadline(monkeypatch)
    class FakeWeb:
        def schemas(self): return []
        async def execute(self, name, args): return await hanging.complete()
    try:
        run['_config']['search']['enabled'] = True
        run['_web'] = FakeWeb()
        clock.owner = asyncio.create_task(engine._agent_loop(agent))
        await clock.expire_after_entry(hanging.entered, run)
        await asyncio.wait_for(clock.owner, 5)
        assert agent.stop_reason == 'time_limit' and agent.status == 'error'
        assert run['model_calls'] == len(client.calls) == run['tool_calls'] == hanging.calls == 1
        assert hanging.cancelled and not (work / 'later.txt').exists() and not agent.output_receipts
        tool_rows = [json.loads(row['content']) for row in agent.conversation if row['role'] == 'tool']
        assert len(tool_rows) == 2 and all(row['ok'] is False for row in tool_rows)
    finally:
        await clock.cleanup()
        await engine.close()


async def test_unknown_web_timeout_is_not_misclassified_as_overall_deadline(tmp_path):
    engine, run, agent, _ = await paused(tmp_path)
    class FakeWeb:
        async def execute(self, name, args): raise TimeoutError('other timeout')
    try:
        run['_config']['search']['enabled'] = True
        run['_web'] = FakeWeb()
        with pytest.raises(TimeoutError, match='other timeout'):
            await engine.execute_tool(run, agent, 'web_read', {})
    finally:
        await engine.close()


async def test_policy_bounds_research_without_waiving_delegation_or_sparse_data_meaning(tmp_path):
    engine, run, agent, _ = await paused(tmp_path)
    try:
        run['delegation_level'] = 2
        policy = engine._policy(run, agent)
        assert 'remaining calls, tools and time' in policy and 'region, dates and fields from this task' in policy
        assert 'Sparse or null data may be valid' in policy and 'report missing or unverified fields honestly' in policy
        assert 'every owned worker has completed' in policy and 'finish_work' in policy
        assert 'Only successful tool results' in policy and 'not reserved capacity' in policy
        assert 'JMA' not in policy and 'weather' not in policy
    finally:
        await engine.close()


def budget_document():
    value = document()
    value['run'].update(model_calls=3, tool_calls=5, budget={'observed_at': 30, 'started_at': 10, 'shared': True,
        'model_calls': {'used': 3, 'limit': 10, 'remaining': 7},
        'tool_calls': {'used': 5, 'limit': 20, 'remaining': 15},
        'time': {'used_seconds': 20, 'limit_seconds': 60, 'remaining_seconds': 40}},
        stop_reason='provider_timeout', stop_reasons=['provider_timeout'])
    value['agents'][0]['stop_reason'] = 'provider_timeout'
    return value


@pytest.mark.parametrize('mutation', ['nan', 'bool_count', 'negative', 'unknown_key', 'wrong_remaining',
    'huge_count', 'wrong_started', 'wrong_elapsed', 'wrong_run_count', 'unknown_reason', 'duplicate_reason', 'unknown_agent_reason'])
def test_archive_rejects_corrupted_budget_and_stop_metadata(mutation):
    value = budget_document()
    budget = value['run']['budget']
    if mutation == 'nan': budget['time']['used_seconds'] = float('nan')
    elif mutation == 'bool_count': budget['model_calls']['used'] = True
    elif mutation == 'negative': budget['time']['remaining_seconds'] = -1
    elif mutation == 'unknown_key': budget['api_key'] = 'no'
    elif mutation == 'wrong_remaining': budget['model_calls']['remaining'] = 9
    elif mutation == 'huge_count': budget['model_calls']['used'] = 2 ** 80
    elif mutation == 'wrong_started': budget['started_at'] = 11
    elif mutation == 'wrong_elapsed': budget['time']['used_seconds'] = 1
    elif mutation == 'wrong_run_count': value['run']['tool_calls'] = 4
    elif mutation == 'unknown_reason': value['run']['stop_reason'] = 'success'
    elif mutation == 'duplicate_reason': value['run']['stop_reasons'] *= 2
    else: value['agents'][0]['stop_reason'] = 'success'
    with pytest.raises(HistoryError): validate(value)


def test_archive_keeps_observed_budget_and_reason_without_inventing_live_time(tmp_path):
    value = budget_document()
    store = HistoryStore(tmp_path / 'history')
    try:
        saved = store.save(value, lambda text: text)
        restored, _ = store.read(value['run']['id'])
        viewed = archived_view(restored, saved + 3600)
        assert viewed['run']['budget'] == value['run']['budget']
        assert viewed['agents'][0]['stop_reason'] == 'provider_timeout'
        assert viewed['run']['archived'] and viewed['run']['read_only']
        assert 'budget' not in archived_view(document(), saved)['run']
        masked = redact_document(value, lambda text: text.replace('provider', '[redacted]'))
        assert masked['run']['stop_reason'] == masked['agents'][0]['stop_reason'] == 'provider_timeout'
    finally:
        store.close()
