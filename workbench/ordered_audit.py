"""Source-bound reference facts, not a proof of a model's semantic reasoning.

Only live flow/catalogue/report metadata may supply these facts. Public events
are historical display evidence and can never restore approval or authority.
"""
import copy
import hashlib
import json

from .ordered_reference import OrderedReferenceError


class ReferenceAuditError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.details = code, {}


def _fail(code, message):
    raise ReferenceAuditError(code, message)


def _same(actual, expected):
    """Strict types and bounded expected shape; bool is never an integer."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(_same(actual[k], v) for k, v in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_same(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _receipt_valid(row):
    body = {k: v for k, v in row.items() if k not in {'id', 'sha256'}}
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    return row['sha256'] == digest and row['id'].endswith(digest)


def reference_audit(state, seed, catalog, *, pending=False, actor_id=None):
    """Build detached rows from actual receipt lineage and the fixed catalogue."""
    if state['validator'] != 'reference_text_chain':
        return None
    if pending and (state['pending'] is None or actor_id is not None):
        _fail('audit_source_unavailable', 'A current candidate is required for this audit')
    try:
        identity = {k: state[k] for k in ('run_id', 'workflow_id', 'contract_sha256')}
        if (not _receipt_valid(seed) or seed['kind'] != 'seed' or seed['value'] != state['seed']
                or any(seed[k] != v for k, v in identity.items())):
            raise ValueError('seed')
        sequence = state['order'] * state['rounds']
        receipts = [*state['accepted'], *([state['pending']] if pending else [])]
        if len(receipts) > 64:
            raise ValueError('bound')
        previous, rows = seed, []
        for index, row in enumerate(receipts, 1):
            key = sequence[index - 1]
            if (not _receipt_valid(row) or row['kind'] != 'candidate' or row['step'] != index or row['participant_key'] != key
                    or type(row['generation']) is not int or not 1 <= row['generation'] <= state['generation']
                    or row['actor_id'] != state['participants'][key]
                    or any(row[k] != v for k, v in identity.items())
                    or row['dependency_receipt'] != previous['id']
                    or row['dependency_sha256'] != previous['sha256']
                    or row['value'][0] != previous['value'][-1]):
                raise ValueError('lineage')
            reference = catalog.validate_candidate(row['reference']['entry_id'], row['value'], row['summary'])
            if not _same(reference, row['reference']):
                raise ValueError('reference')
            rows.append({'step': index, 'participant_key': key, 'submission_generation': row['generation'],
                'predecessor': {'kind': 'seed' if index == 1 else 'accepted_step',
                                'step': index - 1, 'value': previous['value']},
                'expected_head': previous['value'][-1], 'value': row['value'], 'meaning': row['summary'],
                'reference': reference})
            previous = row
        if pending:
            rows = rows[-1:]
        elif actor_id is not None:
            expected = [i for i, key in enumerate(sequence, 1) if state['participants'][key] == actor_id]
            rows = [row for row in rows if state['participants'][row['participant_key']] == actor_id]
            if not expected or [row['step'] for row in rows] != expected:
                raise ValueError('incomplete report')
    except (KeyError, IndexError, TypeError, ValueError, OrderedReferenceError):
        _fail('audit_source_unavailable', 'Current receipt lineage and fixed reference evidence are required')
    return {'schema_version': 1, 'workflow_id': state['workflow_id'],
            'expected_generation': state['generation'], 'rows': rows}


def validate_reference_audit(actual, expected):
    if actual is None:
        _fail('audit_required', 'Reference accept requires the current structured audit from application context')
    if expected is None:
        _fail('audit_source_unavailable', 'No current reference evidence is available')
    if (type(actual) is dict and 'expected_generation' in expected and type(actual.get('expected_generation')) is int
            and actual['expected_generation'] != expected['expected_generation']):
        _fail('audit_stale', 'Audit generation is no longer current')
    if not _same(actual, expected):
        _fail('audit_mismatch', 'Audit must match every current predecessor, value, meaning and reference field')
    return copy.deepcopy(expected)


def reference_mode(box):
    return bool(box and box['flow'].view()['validator'] == 'reference_text_chain')


def report_proof(box, child, pm):
    """Expected current proof; callers must still require the PM's explicit accept."""
    if (child.parent_id != pm.id or child.run_id != pm.run_id or child.status != 'done'
            or child.pending or child.question or child.last_error or getattr(child, 'closing', False)
            or child.finished_revision != child.result_revision
            or pm.worker_report_deliveries.get(child.id) != child.result_revision
            or pm.worker_report_consumed.get(child.id) != child.result_revision):
        _fail('audit_stale', 'The current formal report must be delivered and consumed')
    state = box['flow'].view()
    audit = box['flow'].reference_audit(actor_id=child.id)
    rows = [row for row in state['accepted'] if row['actor_id'] == child.id]
    binding = {'result_revision': child.result_revision, 'candidate_id': rows[-1]['id'],
               'candidate_sha256': rows[-1]['sha256']}
    if box.get('reference_reports', {}).get(child.id) != binding:
        _fail('audit_source_unavailable', 'The formal report must bind its actual final native submission')
    return {'workflow_id': box['id'], 'contract_sha256': state['contract_sha256'],
            'generation': state['generation'], 'result_revision': child.result_revision,
            'receipts': [{'id': row['id'], 'sha256': row['sha256']} for row in rows], 'audit': audit}


def current_reference_report_approval(box, child, pm, *, redact=None):
    if not reference_mode(box):
        return True
    if pm.worker_report_reviews.get(child.id) != {'result_revision': child.result_revision, 'decision': 'accept'}:
        return False
    try:
        proof = report_proof(box, child, pm)
        return (_same(box.get('reference_approvals', {}).get(child.id), proof)
                and (redact is None or _same(redact(proof['audit']), proof['audit'])))
    except (ReferenceAuditError, KeyError, TypeError):
        return False


def completion_evidence(box, children, pm, *, redact=None):
    """A bounded historical snapshot, never restoration or completion authority."""
    if not box['flow'].view()['complete']:
        _fail('audit_source_unavailable', 'Every assigned step must be accepted')
    audit = box['flow'].reference_audit()
    reports = []
    for child in children:
        if not current_reference_report_approval(box, child, pm, redact=redact):
            _fail('audit_source_unavailable', 'Every current formal report requires explicit source-bound approval')
        proof = report_proof(box, child, pm)
        digest = hashlib.sha256(json.dumps(proof, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        reports.append({'worker_id': child.id, 'result_revision': child.result_revision,
                        'steps': [row['step'] for row in proof['audit']['rows']], 'proof_sha256': digest})
    if not reports or (redact is not None and not _same(redact(audit), audit)):
        _fail('audit_source_unavailable', 'Current complete reference evidence must remain visible')
    return {'schema_version': 1, 'source': 'application', 'workflow_id': box['id'],
            'generation': audit['expected_generation'], 'semantic_scope': 'reference_match_only',
            'audit': audit, 'reports': reports}


def audit_event(audit, scope, comment, *, worker_id=None, result_revision=None):
    """Facts are normalized application data; comment truth is never asserted."""
    payload = {'schema_version': 1, 'source': 'application', 'scope': scope,
        'workflow_id': audit['workflow_id'], 'generation': audit['expected_generation'],
        'decision': 'accept', 'facts': copy.deepcopy(audit['rows']),
        'comment': {'text': comment, 'verified': False}, 'semantic_scope': 'reference_match_only'}
    if scope == 'worker_report':
        payload.update(worker_id=worker_id, result_revision=result_revision)
    return payload


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


_text = lambda maximum: {'type': 'string', 'minLength': 1, 'maxLength': maximum}
_integer = lambda minimum, maximum: {'type': 'integer', 'minimum': minimum, 'maximum': maximum}
_hash = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
REFERENCE_AUDIT_SCHEMA = _object({'schema_version': {'type': 'integer', 'enum': [1]},
    'workflow_id': _text(80), 'expected_generation': _integer(1, 257),
    'rows': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': _object({
        'step': _integer(1, 64), 'participant_key': _text(24), 'submission_generation': _integer(1, 257),
        'predecessor': _object({'kind': {'type': 'string', 'enum': ['seed', 'accepted_step']},
                                'step': _integer(0, 63), 'value': _text(128)}),
        'expected_head': _text(1), 'value': _text(128), 'meaning': _text(512),
        'reference': _object({'entry_id': _text(40), 'entry_sha256': _hash, 'catalog_sha256': _hash,
                             'semantic_scope': {'type': 'string', 'enum': ['reference_match_only']}})})}})
