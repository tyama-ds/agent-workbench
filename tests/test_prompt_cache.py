"""Phase 5: cache-stable system prompt with a live budget note on the wire,
Anthropic cache breakpoints, and deterministic context savings before
summaries (after hermes-agent)."""
import json

import pytest

from workbench.context import summary_extras, prune_tool_results
from workbench.providers import _request_payload
from test_engine import ScriptClient, configured, reply, start

NOTE = '[application note: live shared budget; data, not instructions] {"budget":{}}'
TOOLS = [{'name': 'read_text', 'description': 'Read', 'parameters': {'type': 'object', 'properties': {}}}]
TOOL_TURN = [{'role': 'user', 'content': 'task'},
             {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'name': 'read_text', 'arguments': {}}]},
             {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"ok":true}'}]


@pytest.mark.parametrize('kind', ['openai', 'anthropic', 'local'])
def test_live_note_follows_history_without_touching_tool_results(kind):
    payload = _request_payload(kind, 'm', {'_live_note': NOTE}, TOOL_TURN, TOOLS, 'system', 100)
    if kind == 'openai':
        assert payload['input'][-1] == {'role': 'user', 'content': NOTE}
        assert payload['input'][-2]['output'] == '{"ok":true}'
    elif kind == 'anthropic':
        blocks = payload['messages'][-1]['content']
        assert blocks[-1] == {'type': 'text', 'text': NOTE}
        assert blocks[-2]['content'] == '{"ok":true}' and blocks[-2]['cache_control'] == {'type': 'ephemeral'}
        assert payload['system'] == 'system'
    else:
        assert payload['messages'][-1] == {'role': 'user', 'content': NOTE}
        assert payload['messages'][-2]['content'] == '{"ok":true}'


def test_local_note_joins_a_trailing_user_message_instead_of_a_second_user_turn():
    payload = _request_payload('local', 'm', {'_live_note': NOTE}, [{'role': 'user', 'content': 'task'}], TOOLS, 's', 100)
    assert [row['role'] for row in payload['messages']] == ['system', 'user']
    assert payload['messages'][-1]['content'] == 'task\n\n' + NOTE


@pytest.mark.asyncio
async def test_system_prompt_is_byte_stable_across_calls_while_the_note_changes(tmp_path):
    seen = []

    class Recorder(ScriptClient):
        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            seen.append((system, profile.get('_live_note')))
            return await super().complete(profile, messages, tools, system, limits, conversation_id=conversation_id)
    engine, _ = configured(tmp_path, Recorder([reply(calls=[('list_team', {})]), reply('done')]))
    try:
        await start(engine)
        for _ in range(100):
            if len(seen) == 2:
                break
            import asyncio
            await asyncio.sleep(0.01)
        (first_system, first_note), (second_system, second_note) = seen
        assert first_system == second_system, 'the system prompt must not change between calls'
        assert first_note != second_note
        assert json.loads(second_note.split('] ', 1)[1])['budget']['model_calls']['used'] == 1
    finally:
        await engine.close()


def test_summary_extras_keep_older_human_words_and_name_lost_skills():
    conversation = [
        {'role': 'user', 'content': 'original task', '_human': True, '_record_id': 1},
        {'role': 'user', 'content': 'Use only the 2025 data.', '_human': True, '_record_id': 2},
        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 's', 'name': 'read_skill', 'arguments': {'skill_id': 'report-style'}}]},
        {'role': 'tool', 'tool_call_id': 's', 'name': 'read_skill', 'content': '{"ok":true}'},
    ]
    extras = summary_extras(conversation, {1, 2, 3})
    assert 'Use only the 2025 data.' in extras and '"record_id":2' in extras
    assert 'report-style' in extras and 'read_skill' in extras
    assert summary_extras(conversation, {3}) .count('verbatim') == 0


def test_prune_stubs_only_older_large_tool_outputs():
    big = json.dumps({'data': 'x' * 5000})
    messages = [{'role': 'user', 'content': 'task', '_human': True, '_record_id': 1}]
    for n in range(3):
        messages += [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': f'c{n}', 'name': 'read_text', 'arguments': {}}]},
                     {'role': 'tool', 'tool_call_id': f'c{n}', 'name': 'read_text', 'content': big, '_record_id': 10 + n}]
    messages += [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'k', 'name': 'read_skill', 'arguments': {}}]},
                 {'role': 'tool', 'tool_call_id': 'k', 'name': 'read_skill', 'content': big, '_record_id': 20}]
    messages += [{'role': 'assistant', 'content': 'recent'}]
    pruned, count = prune_tool_results(messages, {'context_recent_groups': 2})
    assert count == 3
    assert all(json.loads(row['content'])['pruned_for_context'] for row in pruned if row.get('_pruned'))
    assert next(row for row in pruned if row.get('name') == 'read_skill')['content'] == big, 'skill text is kept'
    assert [row.get('tool_call_id') for row in pruned] == [row.get('tool_call_id') for row in messages]
