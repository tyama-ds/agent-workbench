"""Long runs keep saving, inputs are not lost at limits, context order is kept,
and transient provider outages do not stop an agent."""
import copy
import json

import pytest

import workbench.engine as engine_module
import workbench.history as history
from workbench.context import plan_compaction
from workbench.history import HistoryStore, fit_document
from workbench.providers import ModelReply, ProviderError, ProviderTimeoutError
from test_engine import ScriptClient, configured, reply, settled, start
from test_history_persistence import RUN, document


@pytest.fixture
def store(tmp_path):
    value = HistoryStore(tmp_path / 'state')
    try:
        yield value
    finally:
        value.close()


def test_oversized_archive_is_shortened_instead_of_refused(store, monkeypatch):
    monkeypatch.setattr(history, 'MAX_RUN_BYTES', 60_000)
    first = document()
    first['agents'][0]['logs'] = [{'id': i, 'kind': 'assistant', 'text': f'log {i}', 'thinking': 't' * 400, 'at': 11.0 + i}
                                  for i in range(1, 400)]
    assert store.save(first, lambda s: s)
    restored, _ = store.read(RUN)
    logs = restored['agents'][0]['logs']
    assert len(json.dumps(restored, ensure_ascii=False).encode()) <= 60_000
    assert logs[-1]['id'] == 399 and logs[-1]['thinking'], 'newest rows and their thinking are kept'
    assert 'thinking' not in logs[0], 'oldest thinking is dropped first'
    assert restored['run'] == first['run'] and not store.error


def test_fit_document_bounds_every_list_to_the_item_limit(monkeypatch):
    monkeypatch.setattr(history, 'MAX_ITEMS', 5)
    value = document()
    value['agents'][0]['logs'] = [{'id': i, 'kind': 'assistant', 'text': 'x', 'at': 11.0} for i in range(1, 9)]
    fitted = fit_document(value)
    assert [row['id'] for row in fitted['agents'][0]['logs']] == [4, 5, 6, 7, 8]


def test_repeat_saves_reuse_this_apps_last_document_instead_of_decoding(store, monkeypatch):
    store.save(document(), lambda s: s)
    monkeypatch.setattr(history, 'decode', lambda value: pytest.fail('own archive was decoded again'))
    later = document()
    later['agents'][0]['logs'] = [{'id': 2, 'kind': 'assistant', 'text': 'later', 'at': 12.0}]
    assert store.save(later, lambda s: s)
    monkeypatch.undo()
    restored, _ = store.read(RUN)
    assert [row['id'] for row in restored['agents'][0]['logs']] == [1, 2]
    # A scrub rewrites stored payloads, so the next save reads them again.
    store.scrub(lambda s: s)
    assert store._saved == {}


@pytest.mark.asyncio
async def test_turn_limit_keeps_the_queued_input(tmp_path):
    client = ScriptClient([reply('first turn done')])
    engine, _ = configured(tmp_path, client)
    engine.settings.value['limits']['max_turns_per_agent'] = 1
    try:
        run, agent = await start(engine)
        await settled(engine)
        engine.enqueue(agent, 'peer update that must not be lost')
        engine.kick(agent)
        await settled(engine)
        assert agent.stop_reason == 'turn_limit'
        assert [content for content, _ in agent.pending] == ['peer update that must not be lost']
    finally:
        await engine.close()


def test_compaction_never_moves_later_work_in_front_of_a_protected_human_message():
    limits = {'auto_compact': True, 'context_trigger_percent': 10, 'context_recent_groups': 2,
              'max_context_chars': 20000, 'max_output_tokens': 2048, 'context_summary_chars': 1500,
              'context_reserve_tokens': 256}
    bulk = 'x' * 1500
    messages = [{'role': 'user', 'content': 'task', '_human': True}]
    messages += [{'role': 'assistant', 'content': f'A{i} ' + bulk} for i in range(3)]
    messages += [{'role': 'user', 'content': 'human instruction H1', '_human': True}]
    messages += [{'role': 'assistant', 'content': f'B{i} ' + bulk} for i in range(3)]
    messages += [{'role': 'user', 'content': 'human instruction H2', '_human': True}]
    messages += [{'role': 'assistant', 'content': f'C{i} ' + bulk} for i in range(3)]
    plan = plan_compaction({'kind': 'local'}, messages, [], 'system', limits)
    assert plan is not None
    h1 = next(i for i, row in enumerate(messages) if row['content'] == 'human instruction H1')
    assert plan.indexes and max(plan.indexes) < h1, 'only the contiguous run before H1 is summarized'


@pytest.mark.asyncio
async def test_transient_outage_resends_the_same_call_in_the_same_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_module, 'TRANSIENT_OUTAGE_DELAYS', (0, 0))
    attempts = []

    async def flaky(profile, messages):
        attempts.append(copy.deepcopy(messages))
        if len(attempts) < 3:
            raise ProviderError('Provider returned HTTP 503; response body withheld', status=503, retryable=True)
        return reply('done after outage')
    client = ScriptClient([flaky, flaky, flaky])
    engine, _ = configured(tmp_path, client)
    try:
        run, agent = await start(engine)
        await settled(engine)
        assert agent.status == 'done', agent.last_error
        assert len(attempts) == 3 and attempts[0] == attempts[2], 'the same request is re-sent'
        assert agent.turns == 1 and run['model_calls'] == 1
        assert sum(1 for row in agent.logs if row['kind'] == 'notice' and '再送' in row['text']) == 2
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [ProviderError('HTTP 400', status=400),
                                   ProviderTimeoutError('Provider request timed out; no automatic retry')])
async def test_non_transient_errors_and_timeouts_still_stop(tmp_path, monkeypatch, error):
    monkeypatch.setattr(engine_module, 'TRANSIENT_OUTAGE_DELAYS', (0, 0))
    calls = []

    async def failing(profile, messages):
        calls.append(1)
        raise error
    engine, _ = configured(tmp_path, ScriptClient([failing]))
    try:
        run, agent = await start(engine)
        await settled(engine)
        assert agent.status == 'error' and len(calls) == 1
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_hierarchy_failure_still_pairs_every_call_with_a_result(tmp_path):
    client = ScriptClient([reply(calls=[('list_team', {}), ('list_team', {})]), reply('finished')])
    engine, _ = configured(tmp_path, client)
    original = engine._hierarchy_require
    failures = []

    def flaky(agent):
        last = agent.conversation[-1] if agent.conversation else {}
        if not failures and last.get('role') == 'assistant' and last.get('tool_calls'):
            # Fail only inside the tool batch, before its first call runs.
            failures.append(1)
            raise ValueError('hierarchy lineage changed')
        return original(agent)
    engine._hierarchy_require = flaky
    try:
        run, agent = await start(engine)
        await settled(engine)
        calls = [call['id'] for row in agent.conversation if row['role'] == 'assistant' for call in row.get('tool_calls', [])]
        results = [row['tool_call_id'] for row in agent.conversation if row['role'] == 'tool']
        assert failures and calls and sorted(calls) == sorted(results), 'no tool call is left without a result'
    finally:
        await engine.close()
