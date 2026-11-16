"""Small, immutable, per-run web snapshots and non-executable JSON selection.

The byte quota measures retained UTF-8 text and metadata, not Python RSS. Count,
text, parse-depth and node limits also bound object overhead. Nothing is written
to disk; a missing snapshot never causes an implicit network request.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
import hashlib
import json
import math
import re
import secrets


MAX_TEXT_CHARS = 200000
DEFAULT_RESPONSE_CHARS = 12000
MAX_RESPONSE_CHARS = 24000
MAX_SNAPSHOTS = 8
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20000


class WebDataError(ValueError):
    pass


class _JSONLimit(ValueError):
    pass


class _DuplicateKey(ValueError):
    pass


def _dump(value):
    # Match the ordinary engine tool-result serialization, including separators.
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _size(value):
    return len(_dump(value))


def _json(text):
    """Return (value, fixed reason). Never repair ambiguous or partial JSON."""
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            depth += 1
            if depth > MAX_JSON_DEPTH:
                return None, 'json_depth_limit'
        elif char in '}]':
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _DuplicateKey()
            result[key] = value
        return result

    def number(value):
        if len(value) > 128:
            raise _JSONLimit('json_number_limit')
        result = float(value) if any(c in value for c in '.eE') else int(value)
        if isinstance(result, float) and not math.isfinite(result):
            raise _JSONLimit('json_nonfinite_number')
        if isinstance(result, float):
            try:
                if Decimal(value) != Decimal(str(result)):
                    raise _JSONLimit('json_number_precision')
            except DecimalException:
                raise _JSONLimit('json_number_precision') from None
        return result

    def constant(_):
        raise _JSONLimit('json_nonfinite_number')

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_int=number,
                           parse_float=number, parse_constant=constant)
        pending, nodes = [value], 0
        while pending:
            item = pending.pop()
            nodes += 1
            if nodes > MAX_JSON_NODES:
                return None, 'json_node_limit'
            if isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, str):
                # json.loads accepts lone escaped surrogates; they are not a
                # portable Unicode projection and must stay labeled raw text.
                item.encode('utf-8')
        return value, None
    except _DuplicateKey:
        return None, 'json_duplicate_keys'
    except _JSONLimit as exc:
        return None, str(exc)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return None, 'invalid_json'


def _kind(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, str):
        return 'string'
    return 'number'


def _describe(value, depth=2, budget=None):
    """Bounded structure, never a claim that samples are the whole dataset."""
    budget = [32] if budget is None else budget
    budget[0] -= 1
    result = {'type': _kind(value)}
    if isinstance(value, dict):
        result['key_count'] = len(value)
        result['keys'] = []
        if depth and budget[0] > 0:
            for key, item in value.items():
                if len(result['keys']) >= 8 or budget[0] <= 0:
                    break
                result['keys'].append({'key': key[:80], 'key_truncated': len(key) > 80,
                                       **_describe(item, depth - 1, budget)})
        result['structure_truncated'] = len(result['keys']) < len(value)
    elif isinstance(value, list):
        result['length'] = len(value)
        result['items'] = []
        if depth and budget[0] > 0:
            for index, item in enumerate(value[:2]):
                if budget[0] <= 0:
                    break
                result['items'].append({'index': index, **_describe(item, depth - 1, budget)})
        result['structure_truncated'] = len(result['items']) < len(value)
    elif isinstance(value, str):
        result['length'] = len(value)
        result['preview'] = value[:80]
        result['structure_truncated'] = len(value) > 80
    else:
        result['value'] = value
    return result


def received(value):
    """Bounded echo of the caller's OWN argument for an error message.

    Never pass snapshot (web) content here: error text is not labeled untrusted.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=True)
    except (TypeError, ValueError, RecursionError):
        return _kind(value)
    text = text.encode('utf-8', 'replace').decode('utf-8')
    return text if len(text) <= 60 else text[:57] + '...'


def _got(value):
    if value is None or type(value) in {int, float}:
        return received(value)
    return f'{_kind(value)} {received(value)}'


def received_names(names):
    shown = sorted(received(name) for name in names)[:5]
    return '; got unsupported: ' + ', '.join(shown) if shown else ''


_POINTER_SHAPE = 'pointer must be one RFC 6901 string such as "/items/0/name" ("" is the whole document)'


def _pointer(value, pointer):
    if not isinstance(pointer, str):
        raise WebDataError(f'{_POINTER_SHAPE}; got {_got(pointer)}')
    if len(pointer) > 2048:
        raise WebDataError(f'pointer must be at most 2048 characters; got {len(pointer)}')
    try:
        pointer.encode('utf-8')
    except UnicodeError:
        raise WebDataError('pointer must contain valid Unicode text') from None
    if not pointer:
        return value
    if not pointer.startswith('/'):
        hint = f' (try {received("/" + pointer)})' if re.fullmatch(r'[^$#.*\[\]]+', pointer) else ''
        raise WebDataError(f'{_POINTER_SHAPE}: start with "/" and put "/" before every key or array index; '
                           f'got {received(pointer)}{hint}. JSONPath, dots, brackets, "#" fragments and wildcards are unsupported')
    if pointer.count('/') > MAX_JSON_DEPTH:
        raise WebDataError(f'pointer must have at most {MAX_JSON_DEPTH} "/" levels; got {pointer.count("/")}')
    tokens = pointer[1:].split('/')
    for position, token in enumerate(tokens):
        if re.search(r'~(?![01])', token):
            raise WebDataError(f'pointer contains an invalid RFC 6901 escape in {received(token)}; only ~0 (for ~) and ~1 (for /) exist')
        key = token.replace('~1', '/').replace('~0', '~')
        # Only the caller's own pointer text and container sizes are reported.
        parent = received('/' + '/'.join(tokens[:position])) if position else 'the root ("")'
        if isinstance(value, dict):
            if key not in value:
                raise WebDataError(f'JSON pointer does not exist in this snapshot: the object at {parent} has no key '
                                   f'{received(key)}; read that pointer to see its keys')
            value = value[key]
        elif isinstance(value, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', key) or len(key) > 10:
                raise WebDataError(f'JSON pointer array index must be a canonical nonnegative integer such as 0; got '
                                   f'{received(key)} for the array at {parent}. Wildcards and "-" are unsupported; page with offset/limit')
            if int(key) >= len(value):
                raise WebDataError(f'JSON pointer array index does not exist: got {key}, but the array at {parent} has '
                                   f'{len(value)} items (valid indices start at 0)')
            value = value[int(key)]
        else:
            raise WebDataError(f'JSON pointer cannot descend into a scalar: the value at {parent} has type {_kind(value)}, '
                               f'so {received(key)} cannot be selected')
    return value


def _integer(args, name, default, minimum, maximum, *, cap=False, scope=''):
    """Validate an integer argument. ``cap`` lowers a too-large value to the
    maximum, which can only shrink the response; nothing else is repaired."""
    value = args.get(name, default)
    if cap and type(value) is int and value > maximum:
        return maximum
    if type(value) is not int or not minimum <= value <= maximum:
        raise WebDataError(f'{name} must be an integer {minimum}..{maximum}{scope}; got {_got(value)}')
    return value


def _limit(base, args, default, maximum, scope):
    limit = _integer(args, 'limit', default, 1, maximum, cap=True, scope=scope)
    if limit != args.get('limit', default):
        base['limit_capped_to'] = maximum  # visible, so a short page is not mistaken for the end
    return limit


_FIELDS_SHAPE = 'fields must be an array of 1..20 distinct object-key strings such as ["name","code"]'


def _fields(args):
    fields = args.get('fields')
    if fields is None and 'fields' not in args:
        return None
    if not isinstance(fields, list):
        raise WebDataError(f'{_FIELDS_SHAPE}; got {_got(fields)}')
    if not 1 <= len(fields) <= 20:
        raise WebDataError(f'{_FIELDS_SHAPE}; got {len(fields)} entries')
    for key in fields:
        if not isinstance(key, str):
            raise WebDataError(f'{_FIELDS_SHAPE}; got an entry of type {_kind(key)} (nested paths belong in pointer)')
        if len(key) > 256:
            raise WebDataError(f'{_FIELDS_SHAPE}, each at most 256 characters; got one of {len(key)}')
    if len(set(fields)) != len(fields):
        repeated = next(key for index, key in enumerate(fields) if key in fields[:index])
        raise WebDataError(f'{_FIELDS_SHAPE}; got {received(repeated)} more than once')
    try:
        for key in fields:
            key.encode('utf-8')
    except UnicodeError:
        raise WebDataError('fields must contain valid Unicode object keys') from None
    return fields


def _project(value, fields):
    if fields is None:
        return value, []
    if not isinstance(value, dict):
        raise WebDataError(f'fields selects object keys, but the selected value has type {_kind(value)}; '
                           'select an object or an array of objects, or omit fields')
    return {key: value[key] for key in fields if key in value}, [key for key in fields if key not in value]


@dataclass(frozen=True)
class _Snapshot:
    text: str
    metadata: str
    charge: int


class WebSnapshots:
    def __init__(self):
        self._entries = OrderedDict()
        self.byte_count = 0

    def _base(self, snapshot):
        # No mutable dictionary owned by the cache is returned to a caller.
        return json.loads(snapshot.metadata)

    def _fit_structure(self, base, value, maximum):
        for depth in (2, 1, 0):
            result = {**base, 'structure': _describe(value, depth)}
            if _size(result) <= maximum:
                return result
        raise WebDataError('max_chars is too small for snapshot metadata; request a larger response limit')

    def _text_page(self, base, text, args, maximum):
        offset = _integer(args, 'offset', 0, 0, MAX_TEXT_CHARS, scope=' characters')
        base = dict(base)
        limit = _limit(base, args, 2000, 10000, ' characters for text')
        if offset > len(text):
            raise WebDataError(f'offset {offset} is beyond the retained text ({len(text)} characters); no request was made')
        wanted = min(limit, len(text) - offset)

        def page(count):
            end = offset + count
            return {**base, 'offset': offset, 'total_chars': len(text), 'returned_chars': count,
                    'text': text[offset:end], 'next_offset': end if end < len(text) else None,
                    'page_complete': count == wanted,
                    'truncated': offset != 0 or end < len(text) or base['source_truncated']}

        low, high = 0, wanted
        while low < high:
            middle = (low + high + 1) // 2
            if _size(page(middle)) <= maximum:
                low = middle
            else:
                high = middle - 1
        result = page(low)
        if _size(result) > maximum or wanted and not low:
            raise WebDataError('max_chars is too small for snapshot metadata; request a larger response limit')
        return result

    def capture(self, text, *, url, content_type, decoding, source_sha256, source_bytes, source_truncated,
                json_candidate):
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
            raise WebDataError('Retained web text exceeded its limit')
        # The caller determines this from decoded source BEFORE any text-only
        # control filtering. Filtering must not accidentally repair JSON.
        is_json = json_candidate
        value, reason = (None, 'retained_text_limit') if source_truncated and is_json else (
            _json(text) if is_json else (None, None))
        valid = is_json and reason is None
        ident = 'web-' + secrets.token_hex(16)
        metadata = {'snapshot_id': ident, 'sha256': source_sha256,
                    'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                    'fetched_at': datetime.now(timezone.utc).isoformat(), 'url': url,
                    'content_type': content_type, **decoding, 'untrusted': True,
                    'source_bytes': source_bytes, 'retained_chars': len(text),
                    'source_truncated': source_truncated, 'format': 'json' if valid else 'text',
                    'json_status': 'valid' if valid else ('raw_only' if is_json else 'not_json')}
        if reason:
            metadata['json_reason'] = reason
        encoded = _dump(metadata)
        snapshot = _Snapshot(text, encoded, len(text.encode('utf-8')) + len(encoded.encode('utf-8')))
        if snapshot.charge > MAX_SNAPSHOT_BYTES:
            raise WebDataError('This snapshot exceeds the in-memory retention limit')
        # State the accepted shapes where the model decides its next call.
        base = {**metadata, 'mode': 'preview', 'cached': False,
                'read_hint': ('Use web_read with this snapshot_id: an exact RFC6901 pointer such as "/items/0/name" ("" is the root), '
                              'fields such as ["name","code"], and offset/limit for arrays (limit 1..100) or strings (limit 1..10000). '
                              if valid else
                              'Use web_read with this snapshot_id and character offset/limit (limit 1..10000); '
                              'this snapshot is raw text, so pointer and fields do not apply. ')
                             + 'Samples and previews are not complete data.'}
        if valid:
            # Leave room for the preview/page envelope before describing nodes.
            base = self._fit_structure(base, value, DEFAULT_RESPONSE_CHARS - 1500)
        result = self._text_page(base, text, {'limit': 6000}, DEFAULT_RESPONSE_CHARS)
        while self._entries and (len(self._entries) >= MAX_SNAPSHOTS
                                 or self.byte_count + snapshot.charge > MAX_SNAPSHOT_BYTES):
            _, old = self._entries.popitem(last=False)
            self.byte_count -= old.charge
        self._entries[ident] = snapshot
        self.byte_count += snapshot.charge
        return result

    def read(self, args):
        if not isinstance(args, dict) or set(args) - {'snapshot_id', 'pointer', 'offset', 'limit', 'fields', 'max_chars'}:
            raise WebDataError('web_read accepts only snapshot_id, pointer, offset, limit, fields and max_chars' + (
                received_names(set(args) - {'snapshot_id', 'pointer', 'offset', 'limit', 'fields', 'max_chars'})
                if isinstance(args, dict) else ''))
        ident = args.get('snapshot_id')
        if not isinstance(ident, str) or not re.fullmatch(r'web-[0-9a-f]{32}', ident):
            raise WebDataError('snapshot_id must be the "web-" plus 32 hex characters ID returned by web_fetch in this run; '
                               f'got {received(ident) if "snapshot_id" in args else "no snapshot_id"}')
        maximum = _integer(args, 'max_chars', DEFAULT_RESPONSE_CHARS, 1024, MAX_RESPONSE_CHARS, cap=True)
        fields = _fields(args)
        snapshot = self._entries.get(ident)
        if snapshot is None:
            raise WebDataError('Snapshot is unknown or evicted from this run; no network request was made. Fetch explicitly only if new data is needed.')
        base = {**self._base(snapshot), 'mode': 'read', 'cached': True}
        pointer = args.get('pointer', '')
        if base['format'] != 'json':
            if pointer != '' or fields is not None:
                raise WebDataError('This snapshot is raw text only; use character offset/limit without pointer or fields')
            return self._text_page(base, snapshot.text, args, maximum)
        value, reason = _json(snapshot.text)
        if reason:
            raise WebDataError('Snapshot JSON cannot be projected; no network request was made')
        selected = _pointer(value, pointer)
        base.update(pointer=pointer, node_type=_kind(selected))
        if isinstance(selected, str):
            if fields is not None:
                raise WebDataError('fields cannot select string characters; use offset/limit')
            return self._text_page(base, selected, args, maximum)
        if isinstance(selected, list):
            offset = _integer(args, 'offset', 0, 0, MAX_JSON_NODES, scope=' items')
            limit = _limit(base, args, 20, 100, ' items for a JSON array')
            if offset > len(selected):
                raise WebDataError(f'offset {offset} is beyond this JSON array ({len(selected)} items)')
            end = min(offset + limit, len(selected))
            # Validate every requested item before returning a partial page.
            items = []
            for index in range(offset, end):
                item = selected[index]
                # Null is a real aligned cell, never an object-field miss.
                projected, missing = (None, []) if item is None else _project(item, fields)
                entry = {'index': index, 'value': projected}
                if fields is not None and item is not None:
                    entry['missing_fields'] = missing
                items.append(entry)

            def page(count):
                next_index = offset + count
                return {**base, 'offset': offset, 'total_items': len(selected),
                        'fields': fields, 'items': items[:count], 'returned_items': count,
                        'next_offset': next_index if next_index < len(selected) else None,
                        'page_complete': count == len(items),
                        'truncated': offset != 0 or next_index < len(selected) or base['source_truncated'],
                        'projected': fields is not None}

            low, high = 0, len(items)
            while low < high:
                middle = (low + high + 1) // 2
                if _size(page(middle)) <= maximum:
                    low = middle
                else:
                    high = middle - 1
            result = page(low)
            if items and not low:
                # Never silently skip a large entry or suggest a nonadvancing
                # page. The caller must narrow that exact entry instead.
                result.update(next_offset=None, blocked_index=offset,
                              item_pointer=pointer + '/' + str(offset),
                              read_hint='The first selected item exceeds max_chars. Read item_pointer with narrower object fields or a deeper pointer; it was not skipped.')
                result = self._fit_structure(result, selected[offset], maximum)
            if _size(result) > maximum:
                raise WebDataError('max_chars is too small for snapshot metadata; request a larger response limit')
            return result
        if 'offset' in args or 'limit' in args:
            raise WebDataError(f'offset/limit apply only to arrays or strings; the selected value has type {_kind(selected)}. '
                               'Omit them, or use fields or a deeper pointer')
        projected, missing = _project(selected, fields)
        result = {**base, 'value': projected, 'value_included': True,
                  'fields': fields, 'missing_fields': missing, 'projected': fields is not None,
                  'truncated': False}
        if _size(result) <= maximum:
            return result
        result.pop('value')
        result.update(value_included=False, truncated=True,
                      read_hint='Selected value exceeds max_chars. Choose narrower fields or a deeper pointer; no values were silently omitted from a returned object.')
        return self._fit_structure(result, projected, maximum)
