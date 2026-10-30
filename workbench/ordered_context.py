"""Deterministic provider-only projection of an ordered-work conversation.

The caller retains original messages/history and supplies trusted record IDs from
actual consumed app mail. Text never supplies authority. Native call/result groups
are indivisible; malformed groups fail before any omission or result rewriting.
"""
from __future__ import annotations

import copy
import json
import math
from decimal import Decimal, DecimalException

from .context import groups


MODE = 'ordered_bounded_projection'
RECENT_GROUPS = 3
MAX_DETAIL = 2000
NOTICE_RANGES = 8
TRIMMABLE_TOOLS = frozenset({'start_ordered_work', 'submit_work_step',
                            'review_work_step', 'rollback_work_step', 'list_team'})


def _record_id(message):
    value = message.get('_record_id')
    return value if type(value) is int and 1 <= value <= 1000000 else None


def _ranges(values):
    """Inclusive, sorted ranges; metadata is bounded without hiding its total."""
    result = []
    for value in sorted(set(values)):
        if result and result[-1][1] + 1 == value:
            result[-1][1] = value
        else:
            result.append([value, value])
    return result


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate result keys are not projected')
        value[key] = item
    return value


def _constant(value):
    raise ValueError('Nonfinite result data are not projected')


def _float(value):
    number = float(value)
    if not math.isfinite(number) or Decimal(str(number)) != Decimal(value):
        raise ValueError('Imprecise result numbers are not projected')
    return number


def _trim(message, name, index):
    if name not in TRIMMABLE_TOOLS or message.get('_human') is True:
        return False
    try:
        result = json.loads(message.get('content', ''), object_pairs_hook=_object,
                            parse_constant=_constant, parse_float=_float)
    except (ValueError, TypeError, RecursionError, DecimalException):
        return False  # Keep unknown data exactly; never guess a result schema.
    if (type(result) is not dict or result.get('ok') is not True
            or type(result.get('ordered_work')) is not dict or '_projection' in result):
        return False
    del result['ordered_work']
    result['_projection'] = {'record_id': _record_id(message), 'omitted': 'ordered_work',
                             'source': 'read_context_history'}
    if _record_id(message) is None:
        result['_projection']['source_index'] = index
    message['content'] = json.dumps(result, ensure_ascii=False, allow_nan=False,
                                    separators=(',', ':'))
    return True


def _notice(metadata):
    detail = {'omitted_messages': metadata['omitted_message_count'],
              'omitted_record_ranges': metadata['omitted_record_ranges'][:NOTICE_RANGES],
              'omitted_index_ranges': metadata['omitted_index_ranges'][:NOTICE_RANGES],
              'trimmed_record_ids': metadata['trimmed_record_ids'][:NOTICE_RANGES],
              'trimmed_index_ranges': metadata['trimmed_index_ranges'][:NOTICE_RANGES],
              'details_truncated': metadata['detail_truncated'] or any(
                  len(metadata[key]) > NOTICE_RANGES for key in
                  ('omitted_record_ranges', 'omitted_index_ranges',
                   'trimmed_record_ids', 'trimmed_index_ranges'))}
    return {'role': 'user', '_human': False, '_ordered_projection': True,
            'content': ('Application-generated context projection DATA, not human instructions, '
                        'approval, a semantic summary, or evidence that omitted work succeeded. '
                        'Older complete groups were omitted and repeated ordered_work snapshots '
                        'removed from copied successful tool results. Current application state '
                        'does not grant authority from this text. Original messages were not changed; '
                        'read_context_history may retrieve a record_id only while retained within '
                        'the existing history limits. Missing/evicted records and anonymous index '
                        'ranges cannot be promised retrievable. Index ranges are zero-based original '
                        'message positions. Do not infer the content of omissions.\n'
                        + json.dumps(detail, ensure_ascii=False, separators=(',', ':')))}


def project_ordered_messages(messages, *, trusted_record_ids=()):
    """Return a detached replay plus bounded omission metadata; perform no IO.

    Keep the first group, latest three groups, all human/ask_user groups and every
    group containing a caller-trusted record. Unknown trusted IDs are reported.
    Protected content is never cut to reach an arbitrary size: the caller must
    measure this exact projection and stop if its protected input still exceeds
    the existing hard budget.
    """
    if type(messages) is not list or any(type(message) is not dict for message in messages):
        raise ValueError('Ordered projection requires message dictionaries in a list')
    if (type(trusted_record_ids) not in (tuple, list, set, frozenset)
            or len(trusted_record_ids) > MAX_DETAIL
            or any(type(value) is not int or not 1 <= value <= 1000000 for value in trusted_record_ids)):
        raise ValueError('Trusted record IDs must be a bounded collection of positive integers')
    original_groups = groups(messages)  # Do not conceal an orphan or incomplete batch.
    trusted = set(trusted_record_ids)
    found = {_record_id(message) for message in messages}
    protected = {0, *range(max(0, len(original_groups) - RECENT_GROUPS), len(original_groups))}
    for group_index, indexes in enumerate(original_groups):
        if any(messages[index].get('_human') is True or _record_id(messages[index]) in trusted
               for index in indexes):
            protected.add(group_index)
        if any(call.get('name') == 'ask_user' for index in indexes
               for call in messages[index].get('tool_calls', []) if messages[index]['role'] == 'assistant'):
            protected.add(group_index)

    projected, omitted, trimmed, kept_group_count = [], [], [], 0
    first_group_end = 0
    for group_index, indexes in enumerate(original_groups):
        if group_index not in protected:
            omitted.extend(indexes)
            continue
        kept_group_count += 1
        first = messages[indexes[0]]
        call_names = {call['id']: call.get('name') for call in first.get('tool_calls', [])}
        for index in indexes:
            message = copy.deepcopy(messages[index])
            if message['role'] == 'tool' and _trim(message, call_names.get(message['tool_call_id']), index):
                trimmed.append(index)
            projected.append(message)
        if group_index == 0:
            first_group_end = len(projected)

    omitted_ids = [_record_id(messages[index]) for index in omitted
                   if _record_id(messages[index]) is not None]
    omitted_anonymous = [index for index in omitted if _record_id(messages[index]) is None]
    trimmed_ids = [_record_id(messages[index]) for index in trimmed
                   if _record_id(messages[index]) is not None]
    trimmed_anonymous = [index for index in trimmed if _record_id(messages[index]) is None]
    details = {'omitted_record_ranges': _ranges(omitted_ids),
               'omitted_index_ranges': _ranges(omitted_anonymous),
               'trimmed_record_ids': sorted(set(trimmed_ids)),
               'trimmed_index_ranges': _ranges(trimmed_anonymous)}
    changed = bool(omitted or trimmed)
    metadata = {'mode': MODE, 'raw_message_count': len(messages),
                'projected_message_count': len(projected) + int(changed),
                'raw_group_count': len(original_groups), 'kept_group_count': kept_group_count,
                'omitted_group_count': len(original_groups) - kept_group_count,
                'omitted_message_count': len(omitted), 'trimmed_message_count': len(trimmed),
                **{key: value[:MAX_DETAIL] for key, value in details.items()},
                'detail_counts': {key: len(value) for key, value in details.items()},
                'detail_truncated': any(len(value) > MAX_DETAIL for value in details.values()),
                'missing_trusted_record_ids': sorted(trusted - found),
                'notice_inserted': changed, 'projection_changed': changed}
    if changed:
        projected.insert(first_group_end, _notice(metadata))
    groups(projected)  # Recheck all retained siblings and the notice boundary.
    return projected, metadata
