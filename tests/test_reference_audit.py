"""Synthetic source binding; matching facts never proves free-text reasoning."""
import copy
import hashlib
import json
from dataclasses import replace

import pytest

from workbench.ordered_audit import ReferenceAuditError
from workbench.ordered_reference import ReferenceCatalog
from workbench.ordered_work import OrderedWork, OrderedWorkError


ENTRIES = [
    {'id': 'seed-food', 'value': 'ごま', 'meaning': 'Synthetic seed food'},
    {'id': 'bean', 'value': 'まめ', 'meaning': 'Synthetic bean'},
    {'id': 'fish', 'value': 'めだか', 'meaning': 'Synthetic fish'},
    {'id': 'umbrella', 'value': 'かさ', 'meaning': 'Synthetic umbrella'},
    {'id': 'flower', 'value': 'さくら', 'meaning': 'Synthetic flower'},
    {'id': 'camel', 'value': 'らくだ', 'meaning': 'Synthetic camel'},
]
SOURCE = {'schema_version': 1, 'label': 'Synthetic reference',
          'source_note': 'Test data only; not dictionary truth.', 'entries': ENTRIES}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def flow():
    return OrderedWork.declare({'order': ['A', 'B', 'C'], 'rounds': 2,
        'seed': 'りんご', 'validator': 'reference_text_chain'},
        {'A': 'worker-a', 'B': 'worker-b', 'C': 'worker-c'}, run_id='r-audit',
        workflow_id='ow-audit', reference=ReferenceCatalog.from_payload(SOURCE))


def expected_row(index, *, generation=1):
    entry = ENTRIES[index - 1]
    previous = 'りんご' if index == 1 else ENTRIES[index - 2]['value']
    return {'step': index, 'participant_key': 'ABC'[(index - 1) % 3],
        'submission_generation': generation,
        'predecessor': {'kind': 'seed' if index == 1 else 'accepted_step', 'step': index - 1, 'value': previous},
        'expected_head': previous[-1], 'value': entry['value'], 'meaning': entry['meaning'],
        'reference': {'entry_id': entry['id'], 'entry_sha256': digest(entry),
                      'catalog_sha256': digest(SOURCE), 'semantic_scope': 'reference_match_only'}}


def expected_audit(indices, *, generation=1):
    return {'schema_version': 1, 'workflow_id': 'ow-audit', 'expected_generation': generation,
            'rows': [expected_row(index, generation=generation) for index in indices]}


def submit(current_flow, index):
    current = current_flow.view()['current']
    entry = ENTRIES[index - 1]
    payload = {key: current[key] for key in ('step', 'generation', 'dependency_receipt', 'dependency_sha256')}
    payload.update(value=entry['value'], summary=entry['meaning'], reference_id=entry['id'])
    mutation = current_flow.validate_submission(current['actor_id'], payload)
    current_flow.submit(mutation)
    return mutation.receipt


def accept(current_flow, index, *, generation=1, feedback='Synthetic source checked'):
    candidate = current_flow.view()['pending']
    mutation = current_flow.validate_review(candidate['id'], candidate['sha256'], 'accept', feedback,
        audit=expected_audit([index], generation=generation))
    current_flow.commit_review(mutation)
    return mutation


def test_six_rows_bind_actual_predecessors_and_every_reference_without_proving_comment_truth():
    current = flow()
    false_comment = 'The predecessor of step 4 is the seed and its last character is お.'
    for index in range(1, 7):
        submit(current, index)
        assert current.reference_audit(pending=True) == expected_audit([index])
        accept(current, index, feedback=false_comment if index == 4 else 'Source match only')
    assert current.reference_audit() == expected_audit(range(1, 7))
    assert current.reference_audit(actor_id='worker-a') == expected_audit([1, 4])
    assert current.reference_audit(actor_id='worker-b') == expected_audit([2, 5])
    assert current.reference_audit(actor_id='worker-c') == expected_audit([3, 6])
    fourth = [row for row in current.journal if row['kind'] == 'review'][3]
    assert fourth['feedback'] == false_comment  # Never relabel this as true reasoning.
    assert fourth['audit']['rows'][0]['predecessor']['value'] == 'めだか'
    detached = current.reference_audit()
    detached['rows'][0]['meaning'] = 'Changed by caller'
    assert current.reference_audit() == expected_audit(range(1, 7))


@pytest.mark.parametrize('path,value', [
    (('schema_version',), True), (('workflow_id',), 'ow-other'),
    (('expected_generation',), True), (('expected_generation',), 2),
    (('rows', 0, 'step'), True), (('rows', 0, 'submission_generation'), 2),
    (('rows', 0, 'participant_key'), 'B'),
    (('rows', 0, 'predecessor', 'value'), 'りんお'),
    (('rows', 0, 'predecessor', 'step'), 1), (('rows', 0, 'expected_head'), 'お'),
    (('rows', 0, 'value'), 'ごぼう'), (('rows', 0, 'meaning'), 'Unsupported meaning'),
    (('rows', 0, 'reference', 'entry_id'), 'bean'),
    (('rows', 0, 'reference', 'entry_sha256'), '0' * 64),
    (('rows', 0, 'reference', 'catalog_sha256'), '0' * 64),
    (('rows', 0, 'reference', 'semantic_scope'), 'dictionary_truth'),
    (('rows',), []), (('rows',), [expected_row(1), expected_row(1)]),
])
def test_correct_reference_id_does_not_rescue_wrong_or_missing_facts(path, value):
    current = flow()
    candidate = submit(current, 1)
    bad = expected_audit([1])
    target = bad
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    before = current.view(), current.journal
    with pytest.raises(ReferenceAuditError):
        current.validate_review(candidate['id'], candidate['sha256'], 'accept', 'A comment', audit=bad)
    assert (current.view(), current.journal) == before


@pytest.mark.parametrize('audit', [None, {}, {'rows': [{'reference_id': 'seed-food'}]}])
def test_accept_requires_explicit_complete_audit_but_revise_retains_specific_reason(audit):
    current = flow()
    candidate = submit(current, 1)
    with pytest.raises(ReferenceAuditError):
        current.validate_review(candidate['id'], candidate['sha256'], 'accept', 'Copied ID', audit=audit)
    mutation = current.validate_review(candidate['id'], candidate['sha256'], 'revise', 'Check the supplied source again')
    current.commit_review(mutation)
    assert current.view()['generation'] == 2 and not current.view()['accepted']


def test_commit_rechecks_audit_and_mutation_not_only_receipt_id():
    current = flow()
    candidate = submit(current, 1)
    mutation = current.validate_review(candidate['id'], candidate['sha256'], 'accept', 'Source match',
                                       audit=expected_audit([1]))
    changed = json.loads(mutation._arguments_json)
    changed['audit']['rows'][0]['expected_head'] = 'お'
    forged = replace(mutation, _arguments_json=json.dumps(changed, ensure_ascii=False))
    before = current.view(), current.journal
    with pytest.raises(ReferenceAuditError):
        current.commit_review(forged)
    assert (current.view(), current.journal) == before
    current.commit_review(mutation)
    with pytest.raises(OrderedWorkError):
        current.commit_review(mutation)


def test_rollback_retains_prefix_receipt_generation_and_rejects_stale_audit_replay():
    current = flow()
    for index in range(1, 7):
        submit(current, index)
        accept(current, index)
    original = current.view()['accepted']
    current.commit_rollback(current.validate_rollback(5, original[4]['id'], 1, 'Recheck the later source'))
    assert current.reference_audit()['rows'] == [expected_row(i) for i in range(1, 5)]
    prefix_audit = current.reference_audit(actor_id='worker-a')
    assert prefix_audit['expected_generation'] == 2
    assert [row['submission_generation'] for row in prefix_audit['rows']] == [1, 1]
    with pytest.raises(ReferenceAuditError):
        current.reference_audit(actor_id='worker-b')
    candidate = submit(current, 5)
    with pytest.raises(ReferenceAuditError, match='generation'):
        current.validate_review(candidate['id'], candidate['sha256'], 'accept', 'Old source copied',
                                audit=expected_audit([5]))
    accept(current, 5, generation=2)
    assert current.view()['accepted'][4]['id'] != original[4]['id']


def test_corrupted_lineage_is_unavailable_not_a_reconstructed_source():
    current = flow()
    submit(current, 1)
    current._pending['dependency_receipt'] = 'copied-from-comment'
    with pytest.raises(ReferenceAuditError, match='lineage'):
        current.reference_audit(pending=True)


def test_nonreference_review_contract_remains_unchanged():
    current = OrderedWork.declare({'order': ['A'], 'rounds': 1, 'seed': 'りんご', 'validator': 'text_chain'},
                                 {'A': 'worker-a'}, run_id='r-legacy', workflow_id='ow-legacy')
    step = current.view()['current']
    payload = {k: step[k] for k in ('step', 'generation', 'dependency_receipt', 'dependency_sha256')}
    current.submit(current.validate_submission('worker-a', dict(payload, value='ごま', summary='Unverified free meaning')))
    candidate = current.view()['pending']
    current.commit_review(current.validate_review(candidate['id'], candidate['sha256'], 'accept', 'Legacy judgment'))
    assert current.view()['complete'] and current.reference_audit() is None
