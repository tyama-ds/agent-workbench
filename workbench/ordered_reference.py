"""Immutable, bounded reference data for an explicitly declared work sequence.

A match proves consistency with this supplied catalogue, not dictionary truth,
human approval, or permission. This module never chooses an answer, evaluates
source text, reads files, or calls a provider. All returned containers are copies.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass


MAX_ENTRIES = 128
MAX_ID = 40
MAX_VALUE = 128
MAX_MEANING = 240
MAX_LABEL = 160
MAX_SOURCE_NOTE = 4000
MAX_CATALOG_CHARS = 64000
MAX_CANDIDATES = 8
ENTRY_ID = re.compile(r'[A-Za-z0-9_-]{1,40}\Z')
SEMANTIC_SCOPE = 'reference_match_only'


class OrderedReferenceError(ValueError):
    """A fixed rule failure that does not disclose an input value or invent one."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.details = {}


def _fail(code, message):
    raise OrderedReferenceError(code, message)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        _fail('reference_schema', f'{label}: exact declared fields are required')


def _text(value, label, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum or '\0' in value:
        _fail('reference_text', f'{label}: bounded nonempty text is required')
    try:
        value.encode('utf-8', 'strict')
    except UnicodeError:
        _fail('reference_unicode', f'{label}: valid Unicode is required')
    # Canonical equivalence and outer whitespace only: no case folding, NFKC,
    # transliteration, fuzzy matching or claim that two meanings are synonyms.
    value = unicodedata.normalize('NFC', value.strip())
    if len(value) > maximum:
        _fail('reference_text', f'{label}: normalized text exceeds its bound')
    return value


def _id(value):
    if type(value) is not str or not ENTRY_ID.fullmatch(value):
        _fail('reference_id', 'reference_id: 1–40 ASCII letters, digits, underscore or hyphen are required')
    return value


@dataclass(frozen=True, slots=True, init=False)
class ReferenceCatalog:
    """Frozen canonical strings, with no mutable input dictionaries retained."""

    _payload_json: str
    _sha256: str

    def __init__(self, *args, **kwargs):
        raise TypeError('Use ReferenceCatalog.from_payload')

    @classmethod
    def from_payload(cls, payload):
        _exact(payload, ('schema_version', 'label', 'source_note', 'entries'), 'catalogue')
        if type(payload['schema_version']) is not int or payload['schema_version'] != 1:
            _fail('reference_version', 'Only reference schema_version 1 is supported')
        entries = payload['entries']
        if type(entries) is not list or not 1 <= len(entries) <= MAX_ENTRIES:
            _fail('reference_entries', 'Catalogue must contain 1–128 entries')
        clean = {'schema_version': 1,
                 'label': _text(payload['label'], 'label', MAX_LABEL),
                 'source_note': _text(payload['source_note'], 'source_note', MAX_SOURCE_NOTE),
                 'entries': []}
        ids, values = set(), set()
        for item in entries:
            _exact(item, ('id', 'value', 'meaning'), 'entry')
            entry = {'id': _id(item['id']),
                     'value': _text(item['value'], 'value', MAX_VALUE),
                     'meaning': _text(item['meaning'], 'meaning', MAX_MEANING)}
            if entry['id'] in ids or entry['value'] in values:
                _fail('reference_duplicate', 'Entry identifiers and normalized values must be unique')
            ids.add(entry['id'])
            values.add(entry['value'])
            clean['entries'].append(entry)
        serialized = _json(clean)
        if len(serialized) > MAX_CATALOG_CHARS:
            _fail('reference_size', 'Canonical catalogue exceeds 64000 characters')
        self = object.__new__(cls)
        object.__setattr__(self, '_payload_json', serialized)
        object.__setattr__(self, '_sha256', hashlib.sha256(serialized.encode('utf-8')).hexdigest())
        return self

    def view(self):
        """Detached normalized input; source_note remains arbitrary source data."""
        return json.loads(self._payload_json)

    def descriptor(self):
        data = self.view()
        return {'schema_version': 1, 'label': data['label'],
                'source_note': data['source_note'], 'catalog_sha256': self._sha256,
                'entry_count': len(data['entries']), 'semantic_scope': SEMANTIC_SCOPE}

    def get(self, entry_id):
        entry_id = _id(entry_id)
        for entry in self.view()['entries']:
            if entry['id'] == entry_id:
                return {**entry, 'sha256': _sha(entry)}
        _fail('reference_missing', 'The requested entry is not in the fixed catalogue')

    def candidates(self, prefix, used, limit=8):
        """Filter in declared order; never rank, choose, or manufacture a word."""
        prefix = _text(prefix, 'prefix', MAX_VALUE)
        if type(used) not in (list, tuple, set, frozenset) or len(used) > MAX_ENTRIES:
            _fail('reference_used', 'used must be a bounded collection of values')
        excluded = {_text(value, 'used value', MAX_VALUE) for value in used}
        if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
            _fail('reference_limit', 'limit must be an integer from 1 through 8')
        entries = [entry for entry in self.view()['entries']
                   if entry['value'].startswith(prefix) and entry['value'] not in excluded]
        return {'catalog_sha256': self._sha256,
                'entries': [{**entry, 'sha256': _sha(entry)} for entry in entries[:limit]],
                'total_matches': len(entries), 'truncated': len(entries) > limit}

    def validate_candidate(self, entry_id, value, summary):
        """Verify exact normalized reference text; return evidence, not authority."""
        entry = self.get(entry_id)
        if (_text(value, 'value', MAX_VALUE) != entry['value']
                or _text(summary, 'summary', MAX_MEANING) != entry['meaning']):
            _fail('reference_mismatch', 'The value and summary must match that fixed entry exactly')
        return {'catalog_sha256': self._sha256, 'entry_id': entry['id'],
                'entry_sha256': entry['sha256'], 'semantic_scope': SEMANTIC_SCOPE}
