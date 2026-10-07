"""No live providers: memory boundaries, provenance, accounting and atomic failure."""
import asyncio
import copy
import json
import time

import pytest

from workbench.config import DEFAULT, validate_settings
from workbench.context import (SUMMARY_KEYS, SUMMARY_NOTICE, groups, parse_summary, plan_compaction,
                               pressure, request_size)
from workbench.providers import ModelReply, _anthropic_messages, _local_messages, _openai_messages
from test_engine import ScriptClient, configured, reply, settled, start


def summary_reply(text='Keep original goal. Evidence record 2; pending verification.'):
    return ModelReply(text=json.dumps({key: [text] if key in {'goals', 'open_tasks'} else [] for key in SUMMARY_KEYS}))


async def seeded(tmp_path, client, *, context=50000, count=18):
    engine, _ = configured(tmp_path, client)
    engine.settings.value['limits']['max_context_chars'] = context
    engine.kick = lambda agent: None
    run, agent = await start(engine, task='Original exact task: never alter source data')
    agent.pending.clear()
    engine._append_context(agent, {'role': 'user', 'content': agent.assignment}, human=True)
    for i in range(count):
        engine._append_context(agent, {'role': 'assistant', 'content': f'Observation {i}: ' + 'a' * 1800})
    return engine, run, agent


def call_args(engine, run, agent):
    profile = next(p for p in run['_config']['providers'] if p['id'] == agent.profile_id)
    tools = engine._model_tools(run, agent)
    return profile, tools, {**run['_config']['limits'], 'local': run['_config']['local']}


async def test_automatic_summary_keeps_exact_task_recent_messages_and_originals(tmp_path):
    client = ScriptClient([summary_reply()])
    engine, run, agent = await seeded(tmp_path, client)
    try:
        engine._append_context(agent, {'role': 'user', 'content': 'Human says do not publish'}, human=True)
        before = copy.deepcopy(agent.conversation)
        history = copy.deepcopy(agent.original_history)
        profile, tools, limits = call_args(engine, run, agent)
        assert pressure(profile, before, tools, engine._policy(run, agent), limits)[0] >= .75
        await engine._ensure_context(run, agent, profile, tools, limits)
        assert agent.compactions == run['model_calls'] == 1
        assert agent.conversation[0] == before[0]
        assert agent.conversation[-4:] == before[-4:]
        assert agent.original_history == history
        marker = next(item for item in agent.conversation if item.get('_summary'))
        assert marker['role'] == 'user' and marker['content'].startswith(SUMMARY_NOTICE)
        assert not agent.compacting
        assert all('provider_raw' not in record for record in json.loads(client.calls[0][0]['content'])['records'])
        assert 'conversation' not in engine.snapshot()['agents'][0]
        assert 'original_history' not in engine.snapshot()['agents'][0]
        assert engine.snapshot()['agents'][0]['context_memory']['compactions'] == 1
    finally:
        await engine.close()


@pytest.mark.parametrize('kind', ['openai', 'anthropic', 'local'])
async def test_native_tool_batches_survive_or_are_removed_whole(tmp_path, kind):
    engine, run, agent = await seeded(tmp_path, ScriptClient([summary_reply()]))
    try:
        calls = [{'id': 'c1', 'name': 'list_team', 'arguments': {}}, {'id': 'c2', 'name': 'list_team', 'arguments': {}}]
        if kind == 'openai':
            native = {'provider': kind, 'model': 'fixture', 'output': [
                {'type': 'reasoning', 'encrypted_content': 'opaque-native-reasoning'},
                *[{'type': 'function_call', 'call_id': c['id'], 'name': c['name'], 'arguments': '{}'} for c in calls]]}
        elif kind == 'anthropic':
            native = {'provider': kind, 'model': 'fixture', 'content': [
                {'type': 'thinking', 'thinking': 'native', 'signature': 'must-preserve'},
                *[{'type': 'tool_use', 'id': c['id'], 'name': c['name'], 'input': {}} for c in calls]]}
        else:
            native = {'provider': kind, 'model': 'fixture', 'message': {'role': 'assistant', 'content': '', 'reasoning_content': 'native',
                'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': '{}'}} for c in calls]}}
        engine._append_context(agent, {'role': 'assistant', 'content': '', 'tool_calls': calls, 'provider_raw': native})
        for call in calls:
            engine._append_context(agent, {'role': 'tool', 'tool_call_id': call['id'], 'content': '{"ok":true}'})
        tail = copy.deepcopy(agent.conversation[-3:])
        run['_config']['providers'][0]['kind'] = kind
        profile, tools, limits = call_args(engine, run, agent)
        await engine._ensure_context(run, agent, profile, tools, limits)
        assert agent.compactions == 1 and agent.conversation[-3:] == tail
        groups(agent.conversation)
        converter = {'openai': _openai_messages, 'anthropic': _anthropic_messages, 'local': lambda value: _local_messages(value, '')}[kind]
        assert 'opaque-native-reasoning' in json.dumps(converter(agent.conversation)) if kind == 'openai' else 'native' in json.dumps(converter(agent.conversation))
    finally:
        await engine.close()


@pytest.mark.parametrize('bad', [ModelReply(text='not JSON'), ModelReply(text='{}'), ModelReply(text='[]'),
    ModelReply(text=json.dumps({k: [] for k in SUMMARY_KEYS})),
    ModelReply(text=json.dumps({k: 'wrong' for k in SUMMARY_KEYS})),
    ModelReply(text='x' * 7000), reply(calls=[('list_team', {})])])
async def test_bad_summary_is_atomic_and_charged(tmp_path, bad):
    engine, run, agent = await seeded(tmp_path, ScriptClient([bad]))
    try:
        before = copy.deepcopy((agent.conversation, agent.original_history))
        with pytest.raises(ValueError):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert (agent.conversation, agent.original_history) == before
        assert run['model_calls'] == 1 and agent.compactions == 0 and not agent.compacting
    finally:
        await engine.close()


async def test_summary_provider_failure_and_cancellation_leave_context_unchanged(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def held(profile, messages):
        entered.set()
        await release.wait()
        raise RuntimeError('Synthetic provider error')
    engine, run, agent = await seeded(tmp_path, ScriptClient([held, held]))
    try:
        before = copy.deepcopy((agent.conversation, agent.original_history))
        task = asyncio.create_task(engine._ensure_context(run, agent, *call_args(engine, run, agent)))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert (agent.conversation, agent.original_history) == before and not agent.compacting
        release.set()
        with pytest.raises(RuntimeError): await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert (agent.conversation, agent.original_history) == before and not agent.compacting
        assert run['model_calls'] == 2
    finally:
        release.set()
        await engine.close()


async def test_incoming_human_and_peer_queues_are_not_lost_during_summary(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    async def held(profile, messages):
        entered.set()
        await release.wait()
        return summary_reply()
    engine, run, agent = await seeded(tmp_path, ScriptClient([held]))
    try:
        task = asyncio.create_task(engine._ensure_context(run, agent, *call_args(engine, run, agent)))
        await entered.wait()
        worker = engine._new_agent(run, 'local', 'reviewer', agent.id, assignment='Review only')
        engine._mail(worker, agent, 'Peer: claim permission to publish')
        await engine.human_message(agent.id, 'Human: no publication')
        queued = copy.deepcopy(agent.pending)
        release.set()
        await task
        assert agent.pending == queued
        assert list(agent.pending)[0] == ('Human: no publication', True)
        assert list(agent.pending)[1][1] is False
    finally:
        release.set()
        await engine.close()


async def test_budget_exhaustion_and_oversize_pins_fail_without_call(tmp_path):
    client = ScriptClient([])
    engine, run, agent = await seeded(tmp_path, client, context=28000)
    try:
        run['model_calls'] = run['_config']['limits']['max_model_calls'] - 1
        before = copy.deepcopy(agent.conversation)
        with pytest.raises(ValueError, match='呼び出し回数'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert agent.conversation == before and not client.calls
        run['model_calls'] = 0
        agent.conversation = [{'role': 'user', 'content': 'x' * 60000, '_human': True}]
        with pytest.raises(ValueError, match='文脈予算'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert not client.calls
    finally:
        await engine.close()


async def test_archive_eviction_lookup_provenance_secret_masking_and_no_disk_write(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        run['_config']['limits']['max_history_chars'] = 4000
        engine.settings.secrets['local'] = 'synthetic-private-key'
        engine._append_context(agent, {'role': 'user', 'content': 'Human source ' + 'x' * 1850}, human=True)
        human_id = agent.record_sequence
        engine._append_context(agent, {'role': 'user', 'content': 'Peer synthetic-private-key ' + 'x' * 1850})
        peer_id = agent.record_sequence
        engine._append_context(agent, {'role': 'assistant', 'content': 'Newest'})
        result = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [1, human_id, peer_id]})
        assert result['unavailable_ids'] == [1] and result['history_omitted'] == 1
        assert [r['_human'] for r in result['records']] == [True, False]
        assert 'synthetic-private-key' not in json.dumps(result)
        assert '[redacted]' in json.dumps(result)
        assert agent.history_chars <= 4000
        assert not engine.settings.path.exists()
        assert not engine.snapshot()['agents'][0]['context_memory']['persistent']
    finally:
        await engine.close()


def test_estimate_includes_system_tools_multibyte_and_reserves():
    profile = {'kind': 'local', 'context_window_tokens': 10000}
    messages = [{'role': 'user', 'content': '日本語' * 100}]
    tools = [{'name': 'example', 'description': 'Tool description', 'parameters': {'type': 'object'}}]
    limits = copy.deepcopy(DEFAULT['limits'])
    ratio, chars, tokens = pressure(profile, messages, tools, 'System policy', limits)
    assert tokens > chars
    assert ratio == (tokens + limits['max_output_tokens'] + limits['context_reserve_tokens']) / 10000
    assert request_size(profile, messages, tools, 'System policy')[0] > request_size(profile, messages, [], '')[0]


def test_group_cut_rejects_orphan_duplicate_missing_and_keeps_parallel_batch():
    call = {'role': 'assistant', 'tool_calls': [{'id': 'one'}, {'id': 'two'}]}
    one = {'role': 'tool', 'tool_call_id': 'one'}
    two = {'role': 'tool', 'tool_call_id': 'two'}
    assert groups([call, one, two]) == [[0, 1, 2]]
    for messages in ([one], [call, one], [call, one, one], [call, one, two, two]):
        with pytest.raises(ValueError): groups(messages)


@pytest.mark.parametrize('field,value', [('auto_compact', 'yes'), ('context_recent_groups', 0),
    ('context_summary_chars', 200), ('context_trigger_percent', 100), ('context_reserve_tokens', -1), ('max_history_chars', 2)])
def test_context_settings_validate(field, value):
    raw = copy.deepcopy(DEFAULT)
    raw['limits'][field] = value
    with pytest.raises(ValueError): validate_settings(raw)


def test_legacy_settings_inherit_compaction_and_disabled_estimated_model_budget():
    raw = copy.deepcopy(DEFAULT)
    for key in list(raw['limits']):
        if key.startswith('context_') or key in {'auto_compact', 'max_history_chars'}: del raw['limits'][key]
    for profile in raw['providers']: del profile['context_window_tokens']
    restored = validate_settings(raw)
    assert restored['limits']['auto_compact'] is True
    assert all(p['context_window_tokens'] == 0 for p in restored['providers'])
    restored['providers'][0]['context_window_tokens'] = 5000
    with pytest.raises(ValueError): validate_settings(restored)


async def test_agent_loop_compacts_then_continues_with_same_budgets(tmp_path):
    from workbench.engine import Engine
    client = ScriptClient([summary_reply(), reply('Verified continuation')])
    engine, run, agent = await seeded(tmp_path, client)
    try:
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, 'Continue with the same original constraints')
        await settled(engine)
        assert agent.status == 'done' and agent.compactions == 1
        assert run['model_calls'] == 2 and agent.turns == 1
        assert agent.results[-1]['text'] == 'Verified continuation'
        assert any(item.get('_summary') for item in client.calls[1])
        assert client.calls[1][-1]['content'] == 'Continue with the same original constraints'
        assert all(not record.get('_summary') for record, _ in agent.original_history)
    finally:
        await engine.close()


async def test_disabled_compaction_blocks_overflow_without_extra_call(tmp_path):
    client = ScriptClient([])
    engine, run, agent = await seeded(tmp_path, client, context=20000)
    try:
        run['_config']['limits']['auto_compact'] = False
        with pytest.raises(ValueError, match='文脈予算'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert run['model_calls'] == 0 and not client.calls
    finally:
        await engine.close()


async def test_no_progress_summary_and_incomplete_batch_never_replace_history(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([summary_reply('x' * 14000)]))
    try:
        limits = run['_config']['limits']
        limits['context_summary_chars'] = 32000  # Internal fault injection, not valid public settings.
        before = copy.deepcopy(agent.conversation)
        with pytest.raises(ValueError, match='短く'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert agent.conversation == before and run['model_calls'] == 1
        engine._append_context(agent, {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'unresolved', 'name': 'list_team', 'arguments': {}}]})
        with pytest.raises(ValueError, match='未完了'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert run['model_calls'] == 1
    finally:
        await engine.close()


async def test_summary_timeout_preserves_history_and_prevents_normal_call(tmp_path):
    async def never(profile, messages): await asyncio.Event().wait()
    engine, run, agent = await seeded(tmp_path, ScriptClient([never]))
    try:
        limits = run['_config']['limits']
        run['created_at'] = time.time() - limits['max_run_seconds'] + .08
        before = copy.deepcopy(agent.conversation)
        with pytest.raises(TimeoutError):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert agent.conversation == before and not agent.compacting and run['model_calls'] == 1
    finally:
        await engine.close()


async def test_compactable_overflow_allows_human_reply_but_unshrinkable_does_not(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), context=28000)
    try:
        assert len(json.dumps(agent.conversation, ensure_ascii=False)) > run['_config']['limits']['max_context_chars']
        assert engine.message_eligibility(agent)['allowed']
        await engine.human_message(agent.id, 'Priority instruction')
        assert agent.pending[0] == ('Priority instruction', True)
        agent.conversation = [{'role': 'user', 'content': 'x' * 30000, '_human': True}]
        assert engine.message_eligibility(agent)['reason'] == 'context_limit'
    finally:
        await engine.close()


async def test_lookup_bounds_apply_after_mask_expansion_and_to_requested_ids(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        engine.settings.secrets['local'] = 'x'
        engine._append_context(agent, {'role': 'user', 'content': 'x' * 4000}, human=True)
        ident = agent.record_sequence
        result = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [ident, 1000000]})
        assert result['records'] == [] and result['over_response_limit_ids'] == [ident]
        assert result['unavailable_ids'] == [1000000] and len(json.dumps(result)) <= 24000
        for ids in ([True], [0], [1000001], [10 ** 100], list(range(1, 10))):
            with pytest.raises(ValueError):
                await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': ids})
        before = copy.deepcopy(agent.original_history)
        run['_config']['limits']['max_history_chars'] = 5000
        engine._append_context(agent, {'role': 'assistant', 'content': 'oversized' * 1000})
        assert agent.original_history == before and agent.history_omitted == 1
    finally:
        await engine.close()


async def test_summary_and_next_dispatch_use_current_key_without_persisting_it(tmp_path):
    from workbench.engine import Engine
    class Client:
        def __init__(self): self.keys = []
        async def complete(self, profile, messages, tools, system, limits):
            self.keys.append(profile['api_key'])
            if not tools:
                engine.set_secret('local', 'synthetic-new-key')
                return summary_reply()
            return reply('Done')
    client = Client()
    engine, run, agent = await seeded(tmp_path, client)
    try:
        engine.set_secret('local', 'synthetic-old-key')
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, 'Continue')
        await settled(engine)
        assert agent.status == 'done'
        assert client.keys == ['synthetic-old-key', 'synthetic-new-key']
        assert 'api_key' not in run['_config']['providers'][0]
        assert run['_config'] == engine.settings.value
    finally:
        await engine.close()


async def test_native_duplicate_storage_does_not_reject_fitting_followup(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), context=100000, count=0)
    try:
        text = 'x' * 55000
        engine._append_context(agent, {'role': 'assistant', 'content': text,
            'provider_raw': {'provider': 'local', 'model': 'fixture', 'message': {'role': 'assistant', 'content': text}}})
        assert len(json.dumps(agent.conversation)) > 100000
        profile, tools, limits = call_args(engine, run, agent)
        assert pressure(profile, agent.conversation, tools, engine._policy(run, agent), limits)[0] < 1
        assert engine.message_eligibility(agent)['allowed']
        await engine._ensure_context(run, agent, profile, tools, limits)
        assert run['model_calls'] == 0
        await engine.human_message(agent.id, 'Continue')
        assert agent.pending[-1] == ('Continue', True)
    finally:
        await engine.close()


async def test_token_window_overflow_is_shared_by_dispatch_and_admission(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        for config in (engine.settings.value, run['_config']):
            config['providers'][0]['context_window_tokens'] = 6000
        assert len(json.dumps(agent.conversation)) < run['_config']['limits']['max_context_chars']
        assert engine.message_eligibility(agent)['reason'] == 'context_limit'
        with pytest.raises(ValueError, match='文脈予算'):
            await engine.human_message(agent.id, 'Cannot fit')
        with pytest.raises(ValueError, match='文脈予算'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert run['model_calls'] == 0
    finally:
        await engine.close()


async def test_last_call_is_usable_below_hard_cap_without_optional_summary(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]))
    try:
        run['model_calls'] = run['_config']['limits']['max_model_calls'] - 1
        before = copy.deepcopy(agent.conversation)
        assert engine.message_eligibility(agent)['allowed']
        await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert agent.conversation == before and agent.compactions == 0
        assert run['model_calls'] == run['_config']['limits']['max_model_calls'] - 1
    finally:
        await engine.close()


async def test_lookup_masks_nested_argument_keys_without_merging_collisions(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        secret = 'SYNTHETIC-secret-as-property'
        engine.set_secret('local', secret)
        arguments = {secret: 'first', '[redacted]': 'second', 'nested': [{secret: {'inside-' + secret: 'third'}}]}
        original = {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'name': 'list_team', 'arguments': arguments}]}
        engine._append_context(agent, original)
        before = copy.deepcopy(agent.original_history)
        result = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [agent.record_sequence]})
        assert secret not in json.dumps(result)
        call = result['records'][0]['tool_calls'][0]
        assert 'arguments' not in call
        # JSON text remains text: duplicate masked names are never parsed into
        # a collapsing object by the application.
        text = call['arguments_json']
        assert '"[redacted]":"first"' in text and '"[redacted]":"second"' in text
        assert 'inside-[redacted]' in text and 'third' in text
        assert agent.original_history == before
        assert secret in agent.conversation[-1]['tool_calls'][0]['arguments']
        assert len(json.dumps(result)) < 24000
    finally:
        await engine.close()


@pytest.mark.parametrize('kind', ['local', 'openai', 'anthropic'])
def test_planner_estimates_incrementally_without_reserializing_all_prefixes(monkeypatch, kind):
    import workbench.context as context
    profile = {'kind': kind, 'context_window_tokens': 0}
    limits = {**DEFAULT['limits'], 'max_context_chars': 1000000}
    messages = [{'role': 'user', 'content': 'Original task', '_human': True}]
    messages += [{'role': 'assistant', 'content': ('日本語\\n"quoted"\\backslash' + 'x' * 950), '_record_id': index + 2}
                 for index in range(950)]
    measured = []
    original = context.request_size
    def observe(*args):
        measured.append(1)
        return original(*args)
    monkeypatch.setattr(context, 'request_size', observe)
    plan = plan_compaction(profile, messages, [], 'Fixed policy', limits)
    assert plan is not None and len(measured) == 2
    system = context.SUMMARY_POLICY + f'\nKeep the complete JSON output within {limits["context_summary_chars"]} characters.'
    assert pressure(profile, plan.request, [], system, limits, output_tokens=4096)[0] <= 1
    assert len(plan.indexes) > 800
