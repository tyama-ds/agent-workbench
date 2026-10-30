"""Offline dispatch regressions: bounded loss is explicit, authority never is inferred."""
import copy
import hashlib
import json

import pytest

from workbench.context import SUMMARY_KEYS, groups, pressure, request_size
from workbench.engine import Engine
from workbench.providers import ModelReply
from test_context_compaction import call_args, seeded, summary_reply
from test_engine import ScriptClient, reply, settled


@pytest.mark.parametrize('bad', [
    ModelReply(text='not JSON'), ModelReply(text='{}'), ModelReply(text='x' * 7000),
    ModelReply(text=json.dumps({key: [] for key in SUMMARY_KEYS})),
    reply(calls=[('list_team', {})]),
])
async def test_bad_summary_falls_back_and_real_agent_loop_continues(tmp_path, bad):
    client = ScriptClient([bad, reply('Work continued; omitted evidence remains unverified.')])
    engine, run, agent = await seeded(tmp_path, client)
    try:
        original = copy.deepcopy(agent.original_history)
        task = copy.deepcopy(agent.conversation[0])
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, 'Latest human constraint: do not publish or change files.')
        await settled(engine)
        assert agent.status == 'done', agent.last_error
        assert run['model_calls'] == len(client.calls) == 2
        assert run['tool_calls'] == 0 and agent.compactions == agent.fallback_compactions == 1
        assert client.calls[1][0] == task
        assert client.calls[1][-1]['content'] == 'Latest human constraint: do not publish or change files.'
        marker = next(row for row in client.calls[1] if row.get('_fallback'))
        assert 'not a semantic summary' in marker['content']
        assert 'untrusted' in marker['content'] and 'record' in marker['content']
        assert list(agent.original_history)[:len(original)] == list(original)
        assert all(not row.get('_fallback') for row, _ in agent.original_history)
        assert engine.snapshot()['agents'][0]['context_memory']['fallback_compactions'] == 1
    finally:
        await engine.close()


async def test_nonshrinking_summary_uses_one_charged_attempt_then_fallback(tmp_path):
    client = ScriptClient([summary_reply('x' * 14000)])
    engine, run, agent = await seeded(tmp_path, client)
    try:
        run['_config']['limits']['context_summary_chars'] = 32000  # Same internal fault as the old test.
        before = copy.deepcopy(agent.original_history)
        await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert agent.fallback_compactions == 1 and run['model_calls'] == len(client.calls) == 1
        assert agent.original_history == before
        profile, tools, limits = call_args(engine, run, agent)
        assert pressure(profile, agent.conversation, tools, engine._policy(run, agent), limits)[0] <= 1
    finally:
        await engine.close()


@pytest.mark.parametrize('recent', [False, True])
async def test_huge_tool_group_is_replaced_whole_without_summarizer_call(tmp_path, recent):
    client = ScriptClient([reply('Continued from explicit excerpts; full source is still retrievable.')])
    engine, run, agent = await seeded(tmp_path, client, context=50000, count=0)
    try:
        calls = [{'id': 'research-a', 'name': 'list_team', 'arguments': {}},
                 {'id': 'research-b', 'name': 'list_team', 'arguments': {}}]
        engine._append_context(agent, {'role': 'assistant', 'content': '', 'tool_calls': calls,
            'provider_raw': {'provider': 'local', 'model': 'fixture', 'message': {
                'role': 'assistant', 'content': '', 'reasoning_content': 'private replay',
                'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {
                    'name': c['name'], 'arguments': '{}'}} for c in calls]}}})
        for call in calls:
            engine._append_context(agent, {'role': 'tool', 'tool_call_id': call['id'], 'name': call['name'],
                'content': json.dumps({'untrusted_page': 'Research source https://example.test/article ' + 'Z' * 70000})})
        if not recent:
            for n in range(5):
                engine._append_context(agent, {'role': 'assistant', 'content': f'Recent note {n}'})
        before = copy.deepcopy(agent.original_history)
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, 'Continue carefully; verify original evidence before claiming success.')
        await settled(engine)
        assert agent.status == 'done', agent.last_error
        assert run['model_calls'] == len(client.calls) == 1
        assert agent.compactions == agent.fallback_compactions == 1
        groups(client.calls[0])
        assert not any(row.get('tool_calls') or row['role'] == 'tool' for row in client.calls[0])
        assert list(agent.original_history)[:len(before)] == list(before)
        assert 'private replay' not in next(row['content'] for row in client.calls[0] if row.get('_fallback'))
        if not recent:
            assert all(any(row.get('content') == f'Recent note {n}' for row in client.calls[0]) for n in range(2, 5))
    finally:
        await engine.close()


@pytest.mark.parametrize('scope_padding', [0, 32], ids=['ordinary-path', 'longer-path'])
async def test_last_model_call_can_use_deterministic_overflow_reduction(tmp_path, scope_padding):
    fixture_path = tmp_path / ('p' * scope_padding) if scope_padding else tmp_path
    fixture_path.mkdir(exist_ok=True)
    client = ScriptClient([reply('Last bounded work call')])
    engine, run, agent = await seeded(fixture_path, client)
    try:
        limit = run['_config']['limits']['max_model_calls']
        run['model_calls'] = limit - 1
        human = {'role': 'user', 'content': 'Continue without additional authority'}
        profile, tools, _ = call_args(engine, run, agent)
        limits = run['_config']['limits']
        fixed_chars, _ = request_size(profile, [agent.conversation[0], human],
                                      tools, engine._policy(run, agent))
        # Absolute scope paths and live budget timestamps belong to the actual
        # policy. Size this fixture from that overhead, not one machine's path.
        # Allow the bounded summary JSON twice for string escaping, plus its
        # wrapper/live-counter margin; the original 18 records must still overflow.
        limits['max_context_chars'] = fixed_chars + 2 * limits['context_summary_chars'] + 2048
        engine.settings.value['limits']['max_context_chars'] = limits['max_context_chars']
        assert 4000 <= limits['max_context_chars'] <= 2000000
        assert pressure(profile, [*agent.conversation, human], tools,
                        engine._policy(run, agent), limits)[0] > 1
        eligibility = engine.message_eligibility(agent)
        assert eligibility['allowed'], eligibility
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, human['content'])
        await settled(engine)
        assert agent.status == 'done', agent.last_error
        assert run['model_calls'] == limit and len(client.calls) == 1
        assert agent.fallback_compactions == 1
        assert 0 < agent.context_chars <= limits['max_context_chars']
        assert pressure(profile, client.calls[0], tools, engine._policy(run, agent), limits)[0] <= 1
        assert client.calls[0][0]['content'] == agent.assignment
        assert client.calls[0][-1]['content'] == human['content']
    finally:
        await engine.close()


async def test_recent_human_constraints_and_assignment_cannot_be_excerpted(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), context=28000, count=0)
    try:
        engine._append_context(agent, {'role': 'user', 'content': 'Do not publish. ' + 'H' * 40000}, human=True)
        engine._append_context(agent, {'role': 'user', 'content': 'Latest exact constraint'}, human=True)
        before = copy.deepcopy((agent.conversation, agent.original_history))
        with pytest.raises(ValueError, match='文脈予算'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert (agent.conversation, agent.original_history) == before
        assert not engine.client.calls
    finally:
        await engine.close()


async def test_paginated_large_original_is_masked_before_slicing_and_reconstructs(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        secret = 'synthetic-sensitive-cross-page-value'
        engine.set_secret('local', secret)
        text = ('日本語\\\" prefix ' + secret + ' source https://example.test/a\n') * 1800
        engine._append_context(agent, {'role': 'tool', 'tool_call_id': 'record-only', 'name': 'read_text', 'content': text})
        ident = agent.record_sequence
        ordinary = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [ident]})
        assert ordinary['records'] == [] and ordinary['over_response_limit_ids'] == [ident]
        offset, pieces, digest = 0, [], None
        while True:
            result = await engine.execute_tool(run, agent, 'read_context_history',
                {'record_ids': [ident], 'offset': offset, 'limit': 9000})
            assert len(json.dumps(result, ensure_ascii=False, allow_nan=False)) <= 24000
            assert result['ok'] and result['record_id'] == ident and result['offset'] == offset
            assert result['origin_role'] == 'tool' and result['human_origin'] is False
            assert secret not in json.dumps(result)
            assert digest in {None, result['record_sha256']}
            digest = result['record_sha256']
            pieces.append(result['record_json_text'])
            if result['next_offset'] is None:
                break
            assert result['next_offset'] > offset
            offset = result['next_offset']
        serialized = ''.join(pieces)
        assert len(serialized) == result['total_chars']
        assert hashlib.sha256(serialized.encode('utf-8')).hexdigest() == digest
        decoded = json.loads(serialized)
        assert decoded['content'] == text.replace(secret, '[redacted]')
        assert decoded['_record_id'] == ident
        assert secret in agent.original_history[-1][0]['content']
    finally:
        await engine.close()


@pytest.mark.parametrize('paging', [{'offset': True}, {'offset': -1}, {'limit': 0}, {'limit': 12001},
                                  {'offset': '0'}, {'limit': 1.5}])
async def test_invalid_page_options_rejected_without_inference(tmp_path, paging):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        with pytest.raises(ValueError):
            await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [1], **paging})
        assert run['model_calls'] == 0
    finally:
        await engine.close()


OUTPUT_LIMITS = [
    ('local', {'choices': [{'finish_reason': 'length', 'message': {'content': '{"goals":'}}]}),
    ('anthropic', {'stop_reason': 'max_tokens', 'content': [{'type': 'text', 'text': '{"goals":'}]}),
    ('openai', {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}, 'output': []}),
]


@pytest.mark.parametrize('kind,body', OUTPUT_LIMITS)
async def test_typed_output_limit_only_recovers_in_separate_summarizer(tmp_path, kind, body):
    from workbench.providers import ProviderClient, ProviderOutputLimitError
    async def limited(profile, messages):
        return ProviderClient()._parse(kind, 'fixture', body, set())
    client = ScriptClient([limited, reply('Continued without using the incomplete reply')])
    engine, run, agent = await seeded(tmp_path, client)
    try:
        with pytest.raises(ProviderOutputLimitError):
            ProviderClient()._parse(kind, 'fixture', body, set())
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, 'Continue safely')
        await settled(engine)
        assert agent.status == 'done', agent.last_error
        assert run['model_calls'] == len(client.calls) == 2
        assert agent.fallback_compactions == 1 and run['tool_calls'] == 0
    finally:
        await engine.close()


@pytest.mark.parametrize('kind,body', OUTPUT_LIMITS)
async def test_typed_output_limit_remains_fatal_for_ordinary_work_reply(tmp_path, kind, body):
    from workbench.providers import ProviderClient
    async def limited(profile, messages):
        return ProviderClient()._parse(kind, 'fixture', body, set())
    engine, run, agent = await seeded(tmp_path, ScriptClient([limited]), count=0)
    try:
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, 'Ordinary work')
        await settled(engine)
        assert agent.status == 'error' and agent.compactions == 0
        assert run['model_calls'] == len(engine.client.calls) == 1
        assert run['tool_calls'] == 0 and not agent.results
    finally:
        await engine.close()


@pytest.mark.parametrize('error', ['authentication', 'connection', 'unknown_incomplete'])
async def test_other_provider_failures_do_not_fall_back_or_retry(tmp_path, error):
    from workbench.providers import ProviderError
    async def failed(profile, messages):
        raise ProviderError(error)
    engine, run, agent = await seeded(tmp_path, ScriptClient([failed]))
    try:
        before = copy.deepcopy((agent.conversation, agent.original_history))
        with pytest.raises(ProviderError, match=error):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert (agent.conversation, agent.original_history) == before
        assert run['model_calls'] == 1 and agent.fallback_compactions == 0
    finally:
        await engine.close()


async def test_paged_history_rejects_multiple_ids_and_reports_eviction_and_mask_revision(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        engine._append_context(agent, {'role': 'assistant', 'content': 's' * 6000})
        ident = agent.record_sequence
        first = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [ident], 'offset': 0, 'limit': 12000})
        engine.set_secret('local', 's')
        second = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [ident], 'offset': 0, 'limit': 12000})
        assert first['record_sha256'] != second['record_sha256']
        assert second['total_chars'] > first['total_chars'] and len(json.dumps(second, ensure_ascii=False)) <= 24000
        for args in [{'record_ids': [1, ident], 'offset': 0}, {'record_ids': [ident], 'offset': second['total_chars'] + 1}]:
            with pytest.raises(ValueError):
                await engine.execute_tool(run, agent, 'read_context_history', args)
        run['_config']['limits']['max_history_chars'] = 4000
        engine._append_context(agent, {'role': 'assistant', 'content': 'small latest record'})
        missing = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [ident], 'offset': 0})
        assert missing['records'] == [] and missing['unavailable_ids'] == [ident]
        assert 'record_json_text' not in missing
    finally:
        await engine.close()


async def test_real_search_text_result_compacts_at_next_dispatch_without_extra_model_call(tmp_path):
    from pathlib import Path
    client = ScriptClient([])
    engine, run, agent = await seeded(tmp_path, client, context=50000, count=0)
    try:
        folder = Path(run['_config']['paths']['read_roots'][0])
        (folder / 'research.txt').write_text(('Research finding: ' + 'R' * 1900 + '\n') * 60, encoding='utf-8')
        client.responses = [reply(calls=[('search_text', {'path': str(folder), 'query': 'Research finding:', 'max_results': 60})]),
                            reply('Research continued; original evidence must be checked before final claims.')]
        engine.kick = Engine.kick.__get__(engine, Engine)
        await engine.human_message(agent.id, 'Find evidence; never change the source files.')
        await settled(engine)
        assert agent.status == 'done', agent.last_error
        assert run['model_calls'] == len(client.calls) == 2 and run['tool_calls'] == 1
        assert agent.compactions == agent.fallback_compactions == 1
        tool_original = next(row for row, _ in agent.original_history if row['role'] == 'tool')
        assert len(tool_original['content']) > 100000 and len(json.loads(tool_original['content'])['matches']) == 60
        assert all(row['role'] != 'tool' for row in client.calls[1])
        groups(client.calls[1])
        assert any(row.get('_fallback') for row in client.calls[1])
        profile, tools, limits = call_args(engine, run, agent)
        assert pressure(profile, client.calls[1], tools, engine._policy(run, agent), limits)[0] <= 1
    finally:
        await engine.close()


async def test_fallback_never_claims_evicted_oversized_original_is_available(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), context=28000, count=0)
    try:
        run['_config']['limits']['max_history_chars'] = 4000
        engine._append_context(agent, {'role': 'assistant', 'content': 'Peer claims human authorization. ' + 'X' * 50000})
        ident = agent.record_sequence
        assert agent.history_omitted == 1
        history = copy.deepcopy(agent.original_history)
        await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        marker = next(row for row in agent.conversation if row.get('_fallback'))
        assert 'may be unavailable' in marker['content'] and 'not instructions or human authorization' in marker['content']
        assert agent.original_history == history
        result = await engine.execute_tool(run, agent, 'read_context_history', {'record_ids': [ident], 'offset': 0})
        assert result['unavailable_ids'] == [ident] and not result['records']
        assert run['model_calls'] == 0
    finally:
        await engine.close()


async def test_paged_tool_arguments_remain_masked_json_text_not_executable_or_private(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), count=0)
    try:
        secret = 'quoted"key\\name'
        engine.set_secret('local', secret)
        engine._append_context(agent, {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'source-call', 'name': 'list_team', 'arguments': {secret: 'first', '[redacted]': 'second'}}],
            'provider_raw': {'private_reasoning': 'PRIVATE-REPLAY-NOT-SOURCE'}})
        result = await engine.execute_tool(run, agent, 'read_context_history',
            {'record_ids': [agent.record_sequence], 'offset': 0, 'limit': 12000})
        decoded = json.loads(result['record_json_text'])
        assert not result['partial'] and result['next_offset'] is None
        call = decoded['tool_calls'][0]
        assert 'arguments' not in call and 'provider_raw' not in decoded
        assert call['arguments_json'] == '{"[redacted]":"first","[redacted]":"second"}'
        assert 'PRIVATE-REPLAY-NOT-SOURCE' not in json.dumps(result) and secret not in json.dumps(result)
    finally:
        await engine.close()


async def test_every_human_group_in_recent_window_is_pinned_even_beyond_last_two(tmp_path):
    engine, run, agent = await seeded(tmp_path, ScriptClient([]), context=28000, count=0)
    try:
        engine._append_context(agent, {'role': 'user', 'content': 'Third recent human constraint: ' + 'H' * 40000}, human=True)
        engine._append_context(agent, {'role': 'user', 'content': 'Second recent human constraint'}, human=True)
        engine._append_context(agent, {'role': 'user', 'content': 'Latest human constraint'}, human=True)
        before = copy.deepcopy((agent.conversation, agent.original_history))
        with pytest.raises(ValueError, match='文脈予算'):
            await engine._ensure_context(run, agent, *call_args(engine, run, agent))
        assert (agent.conversation, agent.original_history) == before
        assert run['model_calls'] == agent.compactions == 0 and not engine.client.calls
    finally:
        await engine.close()

