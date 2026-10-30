"""Bounded, pure ordered-work state; it never calls a model or delivers mail.

``text_chain`` checks declared hiragana form/connectivity, not dictionary meaning.
Engine owns permissions, consumed-input/dispatch grants, mail and formal reports.
Validate first, synchronously deliver the required mail, then commit its immutable
proposal without awaiting. A failed delivery must not be followed by a commit.
Receipt SHA256 covers canonical JSON of every field except ``id``/``sha256``.
The append-only journal is display evidence, never a restart/authority format.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass

from .ordered_reference import OrderedReferenceError, ReferenceCatalog
from .ordered_audit import reference_audit, validate_reference_audit


MAX_PARTICIPANTS = 16
MAX_STEPS = 64
MAX_VALUE = 128
MAX_SUMMARY = 512
MAX_JOURNAL = 256
KEY = re.compile(r'[A-Za-z0-9_-]{1,24}\Z')
IDENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
SMALL_KANA = frozenset('ぁぃぅぇぉゃゅょっゎゕゖ')


class OrderedWorkError(ValueError):
    """A bounded rule failure; details explain constraints, not replacement words."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.details = copy.deepcopy(details)


def _fail(code, message, **details):
    raise OrderedWorkError(code, message, **details)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        _fail('invalid_schema', f'{label}: exact declared fields are required')


def _integer(value, label, low=1, high=MAX_STEPS):
    if type(value) is not int or not low <= value <= high:
        _fail('invalid_integer', f'{label}: a bounded integer is required')
    return value


def _text(value, label, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum or '\0' in value:
        _fail('invalid_text', f'{label}: nonempty text within {maximum} characters is required')
    try:
        value.encode('utf-8', 'strict')
    except UnicodeError:
        _fail('invalid_unicode', f'{label}: valid Unicode is required')
    return value


def _identifier(value, label, pattern=IDENT):
    if type(value) is not str or not pattern.fullmatch(value):
        _fail('invalid_identifier', f'{label}: a bounded identifier is required')
    return value


def _word(value, label):
    _text(value, label, MAX_VALUE)
    if len(value) < 2:
        _fail('value_length', f'{label}: at least two hiragana characters are required')
    if any(not '\u3041' <= char <= '\u3096' or char in SMALL_KANA for char in value):
        _fail('value_characters', f'{label}: hiragana without small kana or long marks is required')
    if value[-1] == 'ん':
        _fail('forbidden_suffix', f'{label}: the final character must not be ん')
    return value


def _receipt(body, prefix):
    digest = _digest(body)
    return {**body, 'id': prefix + digest, 'sha256': digest}


@dataclass(frozen=True, slots=True)
class Submission:
    state_fingerprint: str
    actor_id: str
    _payload_json: str
    _receipt_json: str

    @property
    def receipt(self):
        return json.loads(self._receipt_json)


@dataclass(frozen=True, slots=True)
class ReviewMutation:
    state_fingerprint: str
    _arguments_json: str
    _receipt_json: str
    _next_json: str
    affected_actor_ids: tuple[str, ...]
    invalidated_receipts: tuple[str, ...]

    @property
    def receipt(self):
        return json.loads(self._receipt_json)

    @property
    def next_current(self):
        return json.loads(self._next_json)


@dataclass(frozen=True, slots=True)
class RollbackMutation:
    state_fingerprint: str
    _arguments_json: str
    _receipt_json: str
    _next_json: str
    affected_actor_ids: tuple[str, ...]
    invalidated_receipts: tuple[str, ...]

    @property
    def receipt(self):
        return json.loads(self._receipt_json)

    @property
    def next_current(self):
        return json.loads(self._next_json)


class OrderedWork:
    """One declared linear sequence, with explicit submission and PM review phases."""

    @classmethod
    def declare(cls, spec, participants, *, run_id, workflow_id, reference=None):
        _exact(spec, ('order', 'rounds', 'seed', 'validator'), 'spec')
        if type(spec['validator']) is not str or spec['validator'] not in ('text_chain', 'reference_text_chain'):
            _fail('unsupported_validator', 'Only text_chain or explicit reference_text_chain is supported')
        if spec['validator'] == 'reference_text_chain':
            if type(reference) is not ReferenceCatalog:
                _fail('reference_required', 'reference_text_chain requires a validated fixed ReferenceCatalog')
            # Take an independent validated copy. A caller cannot swap mutable
            # catalogue data while a prepared submission awaits mail delivery.
            try:
                reference = ReferenceCatalog.from_payload(reference.view())
            except OrderedReferenceError as exc:
                _fail(exc.code, str(exc), **exc.details)
        elif reference is not None:
            _fail('unexpected_reference', 'text_chain does not consume a reference catalogue')
        order = spec['order']
        if type(order) is not list or not 1 <= len(order) <= MAX_PARTICIPANTS:
            _fail('invalid_order', 'order must contain 1–16 participant keys')
        for key in order:
            _identifier(key, 'participant key', KEY)
        if len(set(order)) != len(order):
            _fail('duplicate_participant', 'Participant keys in order must be unique')
        if type(participants) is not dict or not 1 <= len(participants) <= MAX_PARTICIPANTS:
            _fail('invalid_participants', 'participants must contain 1–16 actual bindings')
        for key, actor in participants.items():
            _identifier(key, 'participant key', KEY)
            _identifier(actor, 'actor_id')
        if len(set(participants.values())) != len(participants):
            _fail('duplicate_actor', 'Each participant must have a distinct actual actor')
        if any(key not in participants for key in order):
            _fail('unknown_participant', 'Every ordered key must have an actual participant binding')
        rounds = _integer(spec['rounds'], 'rounds')
        if len(order) * rounds > MAX_STEPS:
            _fail('step_limit', 'The declared sequence must contain at most 64 steps')
        seed = _word(spec['seed'], 'seed')
        self = cls()
        self._contract = {'schema_version': 1, 'run_id': _identifier(run_id, 'run_id'),
            'workflow_id': _identifier(workflow_id, 'workflow_id'), 'validator': spec['validator'],
            'order': list(order), 'rounds': rounds, 'seed': seed,
            'participants': {key: participants[key] for key in order}}
        self._reference = reference
        if reference is not None:
            self._contract['reference'] = reference.descriptor()
        self._contract_sha = _digest(self._contract)
        self._sequence = tuple(order * rounds)
        self._generation = 1
        self._state_version = 0
        self._accepted = []
        self._pending = None
        self._journal = []
        self._seed = _receipt({**self._identity(), 'kind': 'seed', 'value': seed}, 'ows-')
        return self

    def _identity(self):
        return {'schema_version': 1, 'run_id': self._contract['run_id'],
                'workflow_id': self._contract['workflow_id'], 'contract_sha256': self._contract_sha}

    def _current(self, accepted=None, generation=None):
        prefix = self._accepted if accepted is None else accepted
        generation = self._generation if generation is None else generation
        if len(prefix) == len(self._sequence):
            return None
        key = self._sequence[len(prefix)]
        dependency = prefix[-1] if prefix else self._seed
        return {'step': len(prefix) + 1, 'generation': generation,
                'actor_id': self._contract['participants'][key], 'participant_key': key,
                'dependency_receipt': dependency['id'], 'dependency_sha256': dependency['sha256'],
                'expected_head': dependency['value'][-1]}

    def _fingerprint(self):
        return _digest({'contract': self._contract_sha, 'generation': self._generation,
                        'state_version': self._state_version,
                        'accepted': [row['id'] for row in self._accepted],
                        'pending': self._pending['id'] if self._pending else None})

    def _room(self):
        if len(self._journal) >= MAX_JOURNAL:
            _fail('journal_limit', 'Ordered-work event capacity reached; no transition was committed')

    def _fresh(self, mutation, kind):
        if type(mutation) is not kind or mutation.state_fingerprint != self._fingerprint():
            _fail('stale_mutation', 'Prepared mutation no longer matches current ordered work')

    def view(self):
        """Return a detached current projection; no returned value can mutate state."""
        current = self._current()
        phase = 'complete' if current is None else 'pending_review' if self._pending else 'ready'
        return copy.deepcopy({**self._contract, 'contract_sha256': self._contract_sha,
            'generation': self._generation, 'state_version': self._state_version,
            'phase': phase, 'current': current, 'pending': self._pending,
            'accepted': self._accepted, 'complete': current is None, 'journal_count': len(self._journal)})

    @property
    def journal(self):
        """Retain all bounded proposals/reviews/invalidations as detached evidence."""
        return copy.deepcopy(self._journal)

    def reference_audit(self, *, pending=False, actor_id=None):
        return reference_audit(self.view(), self._seed, self._reference, pending=pending, actor_id=actor_id)

    def validate_submission(self, actor_id, payload):
        """Validate app-owned dispatch grant and model value; do not create pending state."""
        fields = ('step', 'generation', 'dependency_receipt', 'dependency_sha256', 'value', 'summary')
        _exact(payload, fields + (('reference_id',) if self._reference is not None else ()), 'submission')
        _identifier(actor_id, 'actor_id')
        _integer(payload['step'], 'step')
        _integer(payload['generation'], 'generation', high=MAX_JOURNAL + 1)
        _identifier(payload['dependency_receipt'], 'dependency_receipt')
        _identifier(payload['dependency_sha256'], 'dependency_sha256', SHA)
        current = self._current()
        if current is None:
            _fail('workflow_complete', 'All declared steps are already accepted')
        if self._pending is not None:
            _fail('pending_review', 'The current candidate must be reviewed before another submission')
        if actor_id != current['actor_id']:
            _fail('wrong_actor', 'Only the current assigned actor may submit', expected_actor=current['actor_id'])
        if any(payload[key] != current[key] for key in ('step', 'generation', 'dependency_receipt', 'dependency_sha256')):
            _fail('stale_dependency', 'Submission must bind the current step, generation and exact input receipt')
        reference_evidence = None
        if self._reference is not None:
            try:
                reference_evidence = self._reference.validate_candidate(
                    payload['reference_id'], payload['value'], payload['summary'])
                entry = self._reference.get(payload['reference_id'])
            except OrderedReferenceError as exc:
                _fail(exc.code, str(exc), **exc.details)
            value, summary = _word(entry['value'], 'value'), entry['meaning']
        else:
            value = _word(payload['value'], 'value')
            summary = _text(payload['summary'], 'summary', MAX_SUMMARY)
        if value[0] != current['expected_head']:
            _fail('chain_mismatch', 'The first character must equal the accepted input last character', expected_head=current['expected_head'])
        if value in {self._contract['seed'], *(row['value'] for row in self._accepted)}:
            _fail('duplicate_value', 'The seed and previously accepted values cannot be reused')
        self._room()
        body = {**self._identity(), 'kind': 'candidate',
            **{key: current[key] for key in ('step', 'generation', 'actor_id', 'participant_key', 'dependency_receipt', 'dependency_sha256')},
            'value': value, 'summary': summary,
            'checks': {'validator': self._contract['validator'], 'shape_valid': True, 'chain_valid': True,
                       'unique_valid': True, 'semantic_status': 'reference_matched' if reference_evidence else 'unchecked'}}
        if reference_evidence is not None:
            body['reference'] = reference_evidence
        return Submission(self._fingerprint(), actor_id, _json(payload), _json(_receipt(body, 'owc-')))

    def submit(self, mutation):
        """Commit pending candidate after its PM delivery was accepted; do not advance."""
        self._fresh(mutation, Submission)
        checked = self.validate_submission(mutation.actor_id, json.loads(mutation._payload_json))
        if checked != mutation:
            _fail('invalid_mutation', 'Submission differs from its validated contents')
        receipt = checked.receipt
        self._journal.append(copy.deepcopy(receipt))
        self._pending = receipt
        self._state_version += 1
        return self.view()

    def validate_review(self, candidate_id, candidate_sha256, decision, feedback, *, audit=None):
        """Prepare a review; Engine verifies PM authority and actual candidate intake."""
        _identifier(candidate_id, 'candidate_id')
        _identifier(candidate_sha256, 'candidate_sha256', SHA)
        if type(decision) is not str or decision not in ('accept', 'revise'):
            _fail('invalid_decision', 'decision must be accept or revise')
        feedback = _text(feedback, 'feedback', MAX_SUMMARY)
        candidate = self._pending
        if candidate is None or candidate['id'] != candidate_id or candidate['sha256'] != candidate_sha256:
            _fail('stale_candidate', 'Review must bind the current pending candidate receipt')
        checked_audit = None
        if self._reference is not None and decision == 'accept':
            checked_audit = validate_reference_audit(audit, self.reference_audit(pending=True))
        self._room()
        prefix = [*self._accepted, candidate] if decision == 'accept' else self._accepted
        generation = self._generation + (decision == 'revise')
        next_current = self._current(prefix, generation)
        affected = (next_current['actor_id'],) if next_current else ()
        invalidated = (candidate_id,) if decision == 'revise' else ()
        args = {'candidate_id': candidate_id, 'candidate_sha256': candidate_sha256,
                'decision': decision, 'feedback': feedback}
        if checked_audit is not None:
            args['audit'] = checked_audit
        record = _receipt({**self._identity(), 'kind': 'review', **args,
            'step': candidate['step'], 'generation': self._generation,
            'next_generation': generation, 'invalidated_receipts': list(invalidated)}, 'owr-')
        return ReviewMutation(self._fingerprint(), _json(args), _json(record), _json(next_current), affected, invalidated)

    def commit_review(self, mutation):
        """Apply review after required notification delivery, retaining the candidate."""
        self._fresh(mutation, ReviewMutation)
        args = json.loads(mutation._arguments_json)
        checked = self.validate_review(**args)
        if checked != mutation:
            _fail('invalid_mutation', 'Review differs from its validated contents')
        self._journal.append(checked.receipt)
        if args['decision'] == 'accept':
            self._accepted.append(self._pending)
        else:
            self._generation += 1
        self._pending = None
        self._state_version += 1
        return self.view()

    def validate_rollback(self, step, accepted_receipt_id, expected_generation, reason):
        """Prepare correction of an accepted step and invalidation of its dependants."""
        _integer(step, 'step')
        _integer(expected_generation, 'expected_generation', high=MAX_JOURNAL + 1)
        _identifier(accepted_receipt_id, 'accepted_receipt_id')
        reason = _text(reason, 'reason', MAX_SUMMARY)
        if (expected_generation != self._generation or step > len(self._accepted)
                or self._accepted[step - 1]['id'] != accepted_receipt_id):
            _fail('stale_rollback', 'Rollback must bind a current accepted step and generation')
        self._room()
        removed = [*self._accepted[step - 1:], *([self._pending] if self._pending else [])]
        invalidated = tuple(row['id'] for row in removed)
        affected = tuple(dict.fromkeys(row['actor_id'] for row in removed))
        next_current = self._current(self._accepted[:step - 1], self._generation + 1)
        args = {'step': step, 'accepted_receipt_id': accepted_receipt_id,
                'expected_generation': expected_generation, 'reason': reason}
        record = _receipt({**self._identity(), 'kind': 'rollback', **args,
            'generation': self._generation, 'next_generation': self._generation + 1,
            'invalidated_receipts': list(invalidated), 'affected_actor_ids': list(affected)}, 'owb-')
        return RollbackMutation(self._fingerprint(), _json(args), _json(record), _json(next_current), affected, invalidated)

    def commit_rollback(self, mutation):
        """Commit correction only after delivery; original journal rows remain intact."""
        self._fresh(mutation, RollbackMutation)
        args = json.loads(mutation._arguments_json)
        checked = self.validate_rollback(**args)
        if checked != mutation:
            _fail('invalid_mutation', 'Rollback differs from its validated contents')
        self._journal.append(checked.receipt)
        self._accepted = self._accepted[:args['step'] - 1]
        self._pending = None
        self._generation += 1
        self._state_version += 1
        return self.view()


def declare(spec, participants, *, run_id, workflow_id, reference=None):
    """Convenience constructor with the same strict contract as OrderedWork.declare."""
    return OrderedWork.declare(spec, participants, run_id=run_id, workflow_id=workflow_id, reference=reference)
