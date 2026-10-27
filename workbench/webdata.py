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


def _pointer(value, pointer):
    if not isinstance(pointer, str) or len(pointer) > 2048:
        raise WebDataError('pointer must be an RFC 6901 string of at most 2048 characters')
    try:
        pointer.encode('utf-8')
    except UnicodeError:
        raise WebDataError('pointer must contain valid Unicode text') from None
    if not pointer:
        return value
    if not pointer.startswith('/') or pointer.count('/') > MAX_JSON_DEPTH:
        raise WebDataError('pointer must be an RFC 6901 path; URI fragments and excessive depth are unsupported')
    for token in pointer[1:].split('/'):
        if re.search(r'~(?![01])', token):
            raise WebDataError('pointer contains an invalid RFC 6901 escape')
        key = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict):
            if key not in value:
                raise WebDataError('JSON pointer does not exist in this snapshot')
            value = value[key]
        elif isinstance(value, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', key) or len(key) > 10 or int(key) >= len(value):
                raise WebDataError('JSON pointer array index does not exist; use a nonnegative canonical index')
            value = value[int(key)]
        else:
            raise WebDataError('JSON pointer cannot descend into a scalar')
    return value


def _integer(args, name, default, minimum, maximum):
    value = args.get(name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise WebDataError(f'{name} must be an integer between {minimum} and {maximum}')
    return value


def _fields(args):
    fields = args.get('fields')
    if fields is None and 'fields' not in args:
        return None
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 20
            or any(not isinstance(key, str) or len(key) > 256 for key in fields)
            or len(set(fields)) != len(fields)):
        raise WebDataError('fields must contain 1 to 20 distinct literal object keys, each at most 256 characters')
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
        raise WebDataError('fields selects object keys; select an object or an array of objects')
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
        offset = _integer(args, 'offset', 0, 0, MAX_TEXT_CHARS)
        limit = _integer(args, 'limit', 2000, 1, 10000)
        if offset > len(text):
            raise WebDataError('offset is beyond the retained text; no request was made')
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
        base = {**metadata, 'mode': 'preview', 'cached': False,
                'read_hint': 'Use web_read with this snapshot_id. JSON uses exact RFC6901 pointer, object fields or array offset/limit. Raw text uses character offset/limit. Samples and previews are not complete data.'}
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
            raise WebDataError('web_read accepts only snapshot_id, pointer, offset, limit, fields and max_chars')
        ident = args.get('snapshot_id')
        if not isinstance(ident, str) or not re.fullmatch(r'web-[0-9a-f]{32}', ident):
            raise WebDataError('snapshot_id must be an ID returned by web_fetch in this run')
        maximum = _integer(args, 'max_chars', DEFAULT_RESPONSE_CHARS, 1024, MAX_RESPONSE_CHARS)
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
            offset = _integer(args, 'offset', 0, 0, MAX_JSON_NODES)
            limit = _integer(args, 'limit', 20, 1, 100)
            if offset > len(selected):
                raise WebDataError('offset is beyond this JSON array')
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
            raise WebDataError('offset/limit apply only to arrays or strings')
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
