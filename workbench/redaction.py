"""Bounded, process-local exact-value masks; never an authentication source."""
from __future__ import annotations

import heapq


MAX_REDACTION_VALUES = 512
MAX_REDACTION_BYTES = 2 * 1024 * 1024
REDACTION_CAPACITY_MESSAGE = (
    '資格情報の保護履歴が上限に達しました。新しい設定・キーは適用されていません。'
    '作業を保存し、アプリを再起動してから設定してください。'
)


class RedactionCapacityError(ValueError):
    """Fixed safe text only: callers must not retry a failing redaction path."""

    def __init__(self):
        super().__init__(REDACTION_CAPACITY_MESSAGE)


class SecretRedactor:
    """Retired values live only as long as the Engine's retained histories.

    The limits bound distinct values and their UTF-8 payload, not total Python or
    matching memory. No eviction is safe while old conversations remain.
    Prepared replacements are committed synchronously with a settings transition.
    """

    def __init__(self, *, max_values=MAX_REDACTION_VALUES, max_bytes=MAX_REDACTION_BYTES):
        self._max_values = max_values
        self._max_bytes = max_bytes
        self._values = frozenset()
        self._byte_count = 0
        self._ordered = ()

    @property
    def value_count(self):
        return len(self._values)

    @property
    def byte_count(self):
        return self._byte_count

    def prepare(self, values):
        """Validate/prepare without changing masks or external configuration."""
        additions = set()
        for value in values:
            if not isinstance(value, str):
                raise TypeError('資格情報の保護設定が不正です')
            if value and value not in self._values:
                additions.add(value)
        if not additions:
            return None
        byte_count = self._byte_count + sum(len(value.encode('utf-8')) for value in additions)
        if len(self._values) + len(additions) > self._max_values or byte_count > self._max_bytes:
            raise RedactionCapacityError()
        combined = self._values | additions
        ordered = tuple(sorted(combined, key=lambda value: (-len(value), value)))
        return combined, byte_count, ordered

    def commit(self, prepared):
        if prepared is not None:
            self._values, self._byte_count, self._ordered = prepared

    def remember(self, values):
        self.commit(self.prepare(values))

    def redact(self, value):
        if not self._ordered:
            return value
        if len(self._ordered) == 1:
            return value.replace(self._ordered[0], '[redacted]')
        # One pending occurrence per key, using C-level literal find rather than
        # a large regex alternation (near-matching shared prefixes can stall it).
        # Earliest start wins, then longest key; replacement markers are never
        # searched. Heap size is bounded by the registry, not match count.
        pending = [(position, -len(key), key) for key in self._ordered
                   if (position := value.find(key)) >= 0]
        if not pending:
            return value
        heapq.heapify(pending)
        parts, cursor = [], 0
        while pending:
            position, negative_length, key = heapq.heappop(pending)
            if position >= cursor:
                parts.extend((value[cursor:position], '[redacted]'))
                cursor = position - negative_length
            position = value.find(key, cursor)
            if position >= 0:
                heapq.heappush(pending, (position, negative_length, key))
        parts.append(value[cursor:])
        return ''.join(parts)
