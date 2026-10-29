"""Offline provider-view tests: original evidence and native groups stay intact."""
import copy
import json

import pytest

from workbench.context import groups
from workbench.ordered_context import project_ordered_messages


def message(record_id, text='Ordinary historical data', *, human=False):
    result = {'role': 'user', 'content': text, '_human': human}
    if record_id is not None:
        result['_record_id'] = record_id
    return result


def batch(record_id, names=('list_team',), results=None):
    calls = [{'id': f'call-{record_id}-{i}', 'name': name, 'arguments': {}}
             for i, name in enumerate(names)]
    raw = {'provider': 'local', 'model': 'synthetic', 'message': {
        'role': 'assistant', 'content': '', 'reasoning_content': 'Original native thinking',
        'tool_calls': [{'id': row['id'], 'type': 'function',
                       'function': {'name': row['name'], 'arguments': '{}'}} for row in calls]}}
    rows = [{'role': 'assistant', 'content': '', 'tool_calls': calls,
             'provider_raw': raw, '_record_id': record_id, '_human': False}]
    for i, call in enumerate(calls):
        body = results[i] if results is not None else {'ok': True, 'ordered_work': {'old': True}}
        rows.append({'role': 'tool', 'tool_call_id': call['id'], 'content': body if isinstance(body, str) else json.dumps(body),
                     '_record_id': record_id + i + 1, '_human': False})
    return rows


def real_rows(projected):
    return [row for row in projected if not row.get('_ordered_projection')]


def test_old_groups_are_omitted_but_first_latest_three_human_and_trusted_groups_remain():
    original = [message(i, human=i in (1, 4)) for i in range(1, 11)]
    before = copy.deepcopy(original)
    result, metadata = project_ordered_messages(original, trusted_record_ids=[6])
    assert [row['_record_id'] for row in real_rows(result)] == [1, 4, 6, 8, 9, 10]
    assert original == before
    assert metadata['omitted_record_ranges'] == [[2, 3], [5, 5], [7, 7]]
    assert metadata['raw_message_count'] == 10 and metadata['projected_message_count'] == 7
    assert metadata['omitted_group_count'] == metadata['omitted_message_count'] == 4
    assert metadata['missing_trusted_record_ids'] == [] and metadata['notice_inserted']
    assert result[1]['_ordered_projection'] and result[1]['_human'] is False
    assert 'not human instructions' in result[1]['content']
    assert 'not be promised retrievable' in result[1]['content']
    result[0]['content'] = 'Mutate returned copy'
    assert original == before


def test_trusted_tool_record_keeps_entire_batch_and_native_provider_raw():
    old_batch = batch(10, ('unrelated_tool', 'list_team'))
    original = [message(1, human=True), *old_batch, *[message(i) for i in range(20, 25)]]
    before = copy.deepcopy(original)
    result, metadata = project_ordered_messages(original, trusted_record_ids=[12])
    rows = {row.get('_record_id'): row for row in real_rows(result)}
    assert {10, 11, 12} <= rows.keys()
    assert rows[10] == before[1]
    assert rows[10]['provider_raw'] is not original[1]['provider_raw']
    assert rows[11] == before[2]  # A sibling whose function is not allowlisted.
    assert json.loads(rows[12]['content'])['_projection']['record_id'] == 12
    assert metadata['trimmed_record_ids'] == [12]
    assert original == before and len(groups(result)) == 6


def test_ask_user_group_is_kept_even_when_old_with_every_native_sibling():
    protected = batch(10, ('ask_user', 'list_team'))
    original = [message(1), *protected, *[message(i) for i in range(20, 26)]]
    result, metadata = project_ordered_messages(original)
    rows = {row.get('_record_id'): row for row in real_rows(result)}
    assert {10, 11, 12} <= rows.keys() and rows[10] == protected[0]
    assert rows[11] == protected[1]
    assert rows[12]['tool_call_id'] == protected[2]['tool_call_id']
    assert metadata['trimmed_record_ids'] == [12]
    assert groups(result)


@pytest.mark.parametrize('name', ['start_ordered_work', 'submit_work_step', 'review_work_step',
                                 'rollback_work_step', 'list_team'])
def test_only_ordered_work_is_removed_from_successful_allowlisted_result(name):
    body = {'ok': True, 'ordered_work': {'accepted': ['very large historical snapshot'] * 100},
            'queued': True, 'mail_id': 'm-real', 'warning': 'Already accepted; do not resend',
            'error': 'Display diagnostic', 'receipt': {'sha256': 'a' * 64},
            'nested': {'ordered_work': 'Unrelated nested data'}, 'count': 12, 'time': 1.25}
    original = [message(1, human=True), *batch(2, (name,), [body])]
    before = copy.deepcopy(original)
    result, metadata = project_ordered_messages(original)
    row = next(row for row in result if row.get('_record_id') == 3)
    actual = json.loads(row['content'])
    marker = actual.pop('_projection')
    assert actual == {key: value for key, value in body.items() if key != 'ordered_work'}
    assert marker == {'record_id': 3, 'omitted': 'ordered_work', 'source': 'read_context_history'}
    assert metadata['trimmed_message_count'] == 1 and metadata['omitted_group_count'] == 0
    assert original == before
    assert len(json.dumps(result)) < len(json.dumps(original))


@pytest.mark.parametrize('body', [
    {'ok': False, 'ordered_work': {}}, {'ok': 1, 'ordered_work': {}},
    {'ordered_work': {}}, {'ok': True, 'ordered_work': []}, {'ok': True},
    {'ok': True, 'ordered_work': {}, '_projection': {'existing': True}},
    'invalid JSON', '{"ok":true,"ordered_work":{},"x":NaN}',
    '{"ok":true,"ordered_work":{},"x":1e999}',
    '{"ok":true,"ordered_work":{},"x":0.123456789012345678901}',
    '{"ok":true,"ok":false,"ordered_work":{}}',
], ids=[f'unchanged-{i}' for i in range(11)])
def test_unknown_failed_or_ambiguous_result_is_preserved_exactly(body):
    original = [message(1), *batch(2, results=[body])]
    result, metadata = project_ordered_messages(original)
    assert result == original and result is not original
    assert not metadata['projection_changed'] and metadata['trimmed_record_ids'] == []


def test_unrelated_tool_and_human_origin_are_never_trimmed_by_result_shape():
    original = [message(1), *batch(2, ('unrelated_tool', 'list_team'))]
    original[-1]['_human'] = True
    result, metadata = project_ordered_messages(original)
    assert result == original and not metadata['projection_changed']


def test_matching_uses_native_call_name_not_a_spoofed_result_name():
    original = [message(1), *batch(2, ('unrelated_tool',))]
    original[-1]['name'] = 'list_team'
    result, metadata = project_ordered_messages(original)
    assert result == original and not metadata['projection_changed']


def test_notice_is_after_first_complete_native_batch_never_between_siblings():
    original = [*batch(1, ('unrelated_tool', 'unrelated_tool')),
                *[message(i) for i in range(10, 17)]]
    result, metadata = project_ordered_messages(original)
    assert result[:3] == original[:3]
    assert result[3]['_ordered_projection']
    assert metadata['omitted_group_count'] == 4
    assert groups(result)[0] == [0, 1, 2]


def test_anonymous_records_have_explicit_zero_based_index_ranges():
    original = [message(None, str(i)) for i in range(8)]
    result, metadata = project_ordered_messages(original)
    assert metadata['omitted_record_ranges'] == []
    assert metadata['omitted_index_ranges'] == [[1, 4]]
    assert 'anonymous index ranges' in result[1]['content']
    assert [row['content'] for row in real_rows(result)] == ['0', '5', '6', '7']


def test_anonymous_trimmed_result_has_index_and_does_not_invent_record_id():
    original = batch(1)
    del original[-1]['_record_id']
    result, metadata = project_ordered_messages(original)
    marker = json.loads(result[1]['content'])['_projection']
    assert marker['record_id'] is None and marker['source_index'] == 1
    assert metadata['trimmed_record_ids'] == [] and metadata['trimmed_index_ranges'] == [[1, 1]]
    assert result[2]['_ordered_projection']


def test_deterministic_projection_does_not_invent_time_ids_or_hide_missing_trust():
    original = [message(i) for i in range(1, 8)]
    first = project_ordered_messages(original, trusted_record_ids=[999, 3])
    assert first == project_ordered_messages(original, trusted_record_ids=[3, 999])
    assert first[1]['missing_trusted_record_ids'] == [999]
    assert all(row.get('_record_id') != 999 for row in first[0])


@pytest.mark.parametrize('ids', ['3', [True], [0], [-1], [1000001], [1.0], list(range(1, 2002))],
                         ids=[f'trust-{i}' for i in range(7)])
def test_trusted_ids_are_strict_bounded_metadata(ids):
    with pytest.raises(ValueError):
        project_ordered_messages([message(1)], trusted_record_ids=ids)


@pytest.mark.parametrize('broken', [
    [{'role': 'tool', 'tool_call_id': 'missing', 'content': '{}'}],
    batch(1)[:1],
    [batch(1)[0], {**batch(1)[1], 'tool_call_id': 'wrong'}],
    [*batch(1), batch(1)[1]],
    [{**batch(1)[0], 'tool_calls': [batch(1)[0]['tool_calls'][0]] * 2}, batch(1)[1]],
], ids=['orphan', 'incomplete', 'wrong-id', 'duplicate-result', 'duplicate-call'])
def test_broken_old_batch_is_rejected_before_it_could_be_omitted(broken):
    original = [message(10), *broken, *[message(i) for i in range(20, 27)]]
    before = copy.deepcopy(original)
    with pytest.raises(ValueError):
        project_ordered_messages(original)
    assert original == before


def test_unbounded_protected_human_content_is_kept_for_callers_hard_limit_check():
    original = [message(i, 'Human instruction ' + 'x' * 100000, human=True) for i in range(1, 8)]
    result, metadata = project_ordered_messages(original)
    assert result == original and not metadata['notice_inserted']
    assert all(len(row['content']) > 100000 for row in result)
    assert metadata['omitted_message_count'] == 0


def test_large_omission_metadata_and_notice_are_bounded_with_honest_counts():
    original = [message(i * 2 + 1) for i in range(4010)]
    result, metadata = project_ordered_messages(original)
    assert metadata['omitted_message_count'] == 4006
    assert len(metadata['omitted_record_ranges']) == 2000 and metadata['detail_truncated']
    assert metadata['detail_counts']['omitted_record_ranges'] == 4006
    notice = next(row for row in result if row.get('_ordered_projection'))
    assert len(notice['content']) < 2048 and '"details_truncated":true' in notice['content']
    assert len(real_rows(result)) == 4


def test_empty_or_short_input_has_no_unnecessary_notice_and_no_shared_containers():
    assert project_ordered_messages([])[0] == []
    original = [message(1), message(2), message(3)]
    result, metadata = project_ordered_messages(original)
    assert result == original and not metadata['notice_inserted']
    assert all(new is not old for new, old in zip(result, original))
