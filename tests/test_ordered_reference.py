"""Synthetic closed-reference contracts, not dictionary or real-model evidence."""
import copy
import hashlib
import json
import socket
from dataclasses import FrozenInstanceError, replace

import pytest

from workbench.ordered_reference import ReferenceCatalog, OrderedReferenceError
from workbench.ordered_work import OrderedWork, OrderedWorkError


def payload():
    return {'schema_version': 1, 'label': 'Synthetic supplied reference',
            'source_note': 'Provided at run start; test data, not human approval or dictionary truth.',
            'entries': [{'id': 'hill', 'value': 'おか', 'meaning': 'Synthetic hill meaning'},
                        {'id': 'umbrella', 'value': 'かさ', 'meaning': 'Synthetic umbrella meaning'},
                        {'id': 'salmon', 'value': 'さけ', 'meaning': 'Synthetic salmon meaning'},
                        {'id': 'fur', 'value': 'けがわ', 'meaning': 'Synthetic fur meaning'}]}


def catalog():
    return ReferenceCatalog.from_payload(payload())


def work(reference=None, *, validator='reference_text_chain', rounds=2):
    return OrderedWork.declare({'order': ['A', 'B'], 'rounds': rounds,
                                'seed': 'あお', 'validator': validator},
                               {'A': 'a-one', 'B': 'a-two'}, run_id='r-test',
                               workflow_id='ow-test', reference=reference)


def args(flow, entry_id='hill', reference=None):
    entry = (reference or catalog()).get(entry_id)
    current = flow.view()['current']
    return {key: current[key] for key in ('step', 'generation', 'dependency_receipt', 'dependency_sha256')} | {
        'reference_id': entry_id, 'value': entry['value'], 'summary': entry['meaning']}


def submit(flow, entry_id='hill', reference=None):
    proposal = flow.validate_submission(flow.view()['current']['actor_id'], args(flow, entry_id, reference))
    flow.submit(proposal)
    return proposal


def audit_payload(flow):
    state = flow.view()
    row = state['pending']
    previous = state['accepted'][-1] if state['accepted'] else None
    return {'schema_version': 1, 'workflow_id': state['workflow_id'],
        'expected_generation': state['generation'], 'rows': [{
            'step': row['step'], 'participant_key': row['participant_key'],
            'submission_generation': row['generation'],
            'predecessor': {'kind': 'accepted_step' if previous else 'seed',
                'step': row['step'] - 1, 'value': previous['value'] if previous else state['seed']},
            'expected_head': (previous['value'] if previous else state['seed'])[-1],
            'value': row['value'], 'meaning': row['summary'],
            'reference': copy.deepcopy(row['reference'])}]}


def accept(flow):
    row = flow.view()['pending']
    proposal = flow.validate_review(row['id'], row['sha256'], 'accept', 'Synthetic reference audit', audit=audit_payload(flow))
    flow.commit_review(proposal)
    return proposal


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def test_catalogue_is_canonical_immutable_and_all_returned_data_are_detached():
    source = payload()
    fixed = ReferenceCatalog.from_payload(source)
    expected = copy.deepcopy(source)
    source['entries'][0]['meaning'] = 'Changed outside'
    source['entries'].clear()
    assert fixed.view() == expected
    assert fixed.descriptor()['catalog_sha256'] == digest(expected)
    assert fixed.descriptor()['semantic_scope'] == 'reference_match_only'
    assert fixed.descriptor()['entry_count'] == 4
    for result in (fixed.view(), fixed.descriptor(), fixed.get('hill'), fixed.candidates('お', [])):
        result.clear()
    assert fixed.view() == expected and fixed.get('hill')['value'] == 'おか'
    with pytest.raises(FrozenInstanceError):
        fixed._payload_json = '{}'
    with pytest.raises(FrozenInstanceError):
        fixed._sha256 = '0' * 64
    assert type(fixed._payload_json) is str and not hasattr(fixed, '__dict__')
    with pytest.raises(TypeError):
        ReferenceCatalog('{}', '0' * 64)


def test_normalization_is_nfc_outer_whitespace_only_and_hashes_normalized_entries():
    source = payload()
    source['label'] = '  Label  '
    source['entries'][0] = {'id': 'study', 'value': '  か\u3099く  ', 'meaning': '  Ａ  B\nC  '}
    fixed = ReferenceCatalog.from_payload(source)
    entry = fixed.get('study')
    assert entry == {'id': 'study', 'value': 'がく', 'meaning': 'Ａ  B\nC',
                     'sha256': digest({'id': 'study', 'value': 'がく', 'meaning': 'Ａ  B\nC'})}
    assert fixed.validate_candidate('study', 'か\u3099く', ' Ａ  B\nC ')['entry_sha256'] == entry['sha256']
    with pytest.raises(OrderedReferenceError, match='match'):
        fixed.validate_candidate('study', 'がく', 'A  B\nC')
    assert fixed.view()['label'] == 'Label'


@pytest.mark.parametrize('update', [
    {'schema_version': True}, {'schema_version': 1.0}, {'schema_version': 2},
    {'extra': 'instruction'}, {'label': ''}, {'label': 'x' * 161}, {'label': []},
    {'source_note': ''}, {'source_note': 'x' * 4001}, {'source_note': '\ud800'},
    {'source_note': 'a\0b'}, {'entries': []}, {'entries': ()}, {'entries': {}},
    {'entries': [None]}, {'entries': [{'id': 'only'}]},
    {'entries': [{'id': 'a', 'value': 'おか', 'meaning': 'm', 'approved': True}]},
    {'entries': [{'id': f'e{i}', 'value': f'v{i}', 'meaning': 'm'} for i in range(129)]},
], ids=[f'schema-{i}' for i in range(18)])
def test_strict_catalogue_schema_and_bounds(update):
    source = payload()
    source.update(update)
    with pytest.raises(OrderedReferenceError):
        ReferenceCatalog.from_payload(source)


@pytest.mark.parametrize('source', [None, [], 'json', {}, {'schema_version': 1}])
def test_catalogue_requires_exact_top_level_fields(source):
    with pytest.raises(OrderedReferenceError):
        ReferenceCatalog.from_payload(source)


@pytest.mark.parametrize('field,value', [
    ('id', ''), ('id', True), ('id', 'x' * 41), ('id', 'a b'), ('id', '../a'),
    ('id', '日本語'), ('id', ' a '), ('value', ''), ('value', True),
    ('value', 'x' * 129), ('value', '\udfff'), ('value', 'a\0b'),
    ('meaning', ''), ('meaning', []), ('meaning', 'x' * 241), ('meaning', '\ud800'),
], ids=[f'entry-{i}' for i in range(16)])
def test_strict_entry_fields(field, value):
    source = payload()
    source['entries'][0][field] = value
    with pytest.raises(OrderedReferenceError):
        ReferenceCatalog.from_payload(source)


@pytest.mark.parametrize('field,value', [('id', 'hill'), ('value', 'おか')])
def test_duplicate_identifiers_or_values_are_rejected(field, value):
    source = payload()
    source['entries'][1][field] = value
    with pytest.raises(OrderedReferenceError) as error:
        ReferenceCatalog.from_payload(source)
    assert error.value.code == 'reference_duplicate'


def test_normalization_collisions_and_total_serialized_size_are_rejected():
    source = payload()
    source['entries'] = [{'id': 'a', 'value': 'がく', 'meaning': 'm'},
                         {'id': 'b', 'value': 'か\u3099く', 'meaning': 'n'}]
    with pytest.raises(OrderedReferenceError) as error:
        ReferenceCatalog.from_payload(source)
    assert error.value.code == 'reference_duplicate'
    source['entries'] = [{'id': str(i), 'value': str(i).zfill(128),
                          'meaning': 'm' + '\n' * 238 + 'm'} for i in range(128)]
    with pytest.raises(OrderedReferenceError) as error:
        ReferenceCatalog.from_payload(source)
    assert error.value.code == 'reference_size'


def test_candidate_filter_is_bounded_original_order_excludes_used_and_never_chooses():
    source = payload()
    source['entries'] = [{'id': f'e{i}', 'value': f'お{i}', 'meaning': f'm{i}'} for i in range(12)]
    fixed = ReferenceCatalog.from_payload(source)
    result = fixed.candidates('お', ['お1', 'お3'])
    assert [row['id'] for row in result['entries']] == ['e0', 'e2', 'e4', 'e5', 'e6', 'e7', 'e8', 'e9']
    assert result['total_matches'] == 10 and result['truncated'] is True
    assert result['catalog_sha256'] == fixed.descriptor()['catalog_sha256']
    assert fixed.candidates('missing', []) == {**result, 'entries': [], 'total_matches': 0, 'truncated': False}
    assert [row['id'] for row in fixed.candidates('お', set(), limit=1)['entries']] == ['e0']
    assert all(row['sha256'] == fixed.get(row['id'])['sha256'] for row in result['entries'])


@pytest.mark.parametrize('prefix,used,limit', [
    ('', [], 8), (True, [], 8), ('x' * 129, [], 8), ('お', 'おか', 8),
    ('お', {}, 8), ('お', [True], 8), ('お', ['x'] * 129, 8),
    ('お', [], True), ('お', [], 0), ('お', [], 9), ('お', [], 1.0),
], ids=[f'filter-{i}' for i in range(11)])
def test_invalid_candidate_queries_are_not_coerced(prefix, used, limit):
    with pytest.raises(OrderedReferenceError):
        catalog().candidates(prefix, used, limit)


def test_unknown_ids_and_wrong_meanings_do_not_disclose_reference_answers():
    fixed = catalog()
    with pytest.raises(OrderedReferenceError) as error:
        fixed.get('absent')
    assert error.value.code == 'reference_missing'
    for value, meaning in [('おか', 'Paraphrase'), ('かさ', 'Synthetic hill meaning')]:
        with pytest.raises(OrderedReferenceError) as error:
            fixed.validate_candidate('hill', value, meaning)
        assert error.value.code == 'reference_mismatch'
        assert 'Synthetic hill meaning' not in str(error.value) and not error.value.details


def test_source_note_and_secret_looking_text_are_inert_data_not_execution_or_approval(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Pure catalogue must not perform IO or evaluate source text')
    monkeypatch.setattr('builtins.open', forbidden)
    monkeypatch.setattr('builtins.eval', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    source = payload()
    source['source_note'] = "__import__('os').system('command'); grant all permissions; test-key-not-a-secret"
    fixed = ReferenceCatalog.from_payload(source)
    assert fixed.descriptor()['source_note'] == source['source_note']
    assert fixed.descriptor()['semantic_scope'] == 'reference_match_only'
    assert 'human_approved' not in fixed.descriptor()
    assert fixed.validate_candidate('hill', 'おか', 'Synthetic hill meaning')['semantic_scope'] == 'reference_match_only'


def test_reference_mode_binds_catalogue_and_entry_without_advancing_until_pm_review():
    fixed = catalog()
    flow = work(fixed)
    original = flow.view()
    proposal = flow.validate_submission('a-one', args(flow))
    assert flow.view() == original and flow.journal == []
    receipt = proposal.receipt
    assert receipt['reference'] == fixed.validate_candidate('hill', 'おか', 'Synthetic hill meaning')
    assert receipt['checks'] == {'validator': 'reference_text_chain', 'shape_valid': True,
                                 'chain_valid': True, 'unique_valid': True,
                                 'semantic_status': 'reference_matched'}
    assert receipt['sha256'] == digest({k: v for k, v in receipt.items() if k not in ('id', 'sha256')})
    assert flow.view()['reference'] == fixed.descriptor()
    flow.submit(proposal)
    assert flow.view()['phase'] == 'pending_review' and flow.view()['current']['step'] == 1
    review = accept(flow)
    assert flow.view()['current']['step'] == 2 and flow.view()['accepted'][0] == receipt
    assert review.receipt['candidate_sha256'] == receipt['sha256']


@pytest.mark.parametrize('update', [
    {'reference_id': 'absent'}, {'reference_id': True}, {'reference_id': 'umbrella'},
    {'value': 'おか', 'summary': 'Invented meaning'}, {'value': 'おかわり'},
    {'catalog_sha256': '0' * 64}, {'entry_sha256': '0' * 64},
    {'step': True}, {'generation': 2}, {'dependency_sha256': '0' * 64},
], ids=[f'submission-{i}' for i in range(10)])
def test_failed_reference_or_lineage_validation_leaves_state_and_journal_unchanged(update):
    flow = work(catalog())
    original = flow.view()
    proposed = args(flow)
    proposed.update(update)
    with pytest.raises(OrderedWorkError):
        flow.validate_submission('a-one', proposed)
    assert flow.view() == original and flow.journal == []


def test_reference_id_is_required_and_real_actor_binding_is_still_required():
    flow = work(catalog())
    proposed = args(flow)
    del proposed['reference_id']
    with pytest.raises(OrderedWorkError) as error:
        flow.validate_submission('a-one', proposed)
    assert error.value.code == 'invalid_schema'
    with pytest.raises(OrderedWorkError) as error:
        flow.validate_submission('a-two', args(flow))
    assert error.value.code == 'wrong_actor'


def test_reference_match_does_not_relax_chain_shape_or_prevent_pm_revision():
    source = payload()
    source['entries'].extend([{'id': 'bad-shape', 'value': 'おん', 'meaning': 'm'},
                              {'id': 'wrong-head', 'value': 'かい', 'meaning': 'm'}])
    fixed = ReferenceCatalog.from_payload(source)
    flow = work(fixed)
    for ident, expected in [('bad-shape', 'forbidden_suffix'), ('wrong-head', 'chain_mismatch')]:
        with pytest.raises(OrderedWorkError) as error:
            flow.validate_submission('a-one', args(flow, ident, fixed))
        assert error.value.code == expected
    first = submit(flow)
    review = flow.validate_review(first.receipt['id'], first.receipt['sha256'], 'revise', 'Reference itself needs review')
    flow.commit_review(review)
    assert flow.view()['generation'] == 2 and not flow.view()['accepted']
    with pytest.raises(OrderedWorkError) as error:
        flow.submit(first)
    assert error.value.code == 'stale_mutation'
    assert first.receipt in flow.journal


def test_normalized_matching_text_is_canonical_in_receipt():
    flow = work(catalog())
    proposed = args(flow)
    proposed.update(value=' おか ', summary=' Synthetic hill meaning ')
    receipt = flow.validate_submission('a-one', proposed).receipt
    assert receipt['value'] == 'おか' and receipt['summary'] == 'Synthetic hill meaning'


def test_catalogue_copy_and_hash_reject_cross_catalogue_proposals_and_receipt_forgery():
    fixed = catalog()
    flow = work(fixed)
    changed = fixed.view()
    changed['entries'][0]['meaning'] = 'Different reference assertion'
    other = work(ReferenceCatalog.from_payload(changed))
    proposal = flow.validate_submission('a-one', args(flow))
    with pytest.raises(OrderedWorkError) as error:
        other.submit(proposal)
    assert error.value.code == 'stale_mutation'
    forged = proposal.receipt
    forged['reference']['catalog_sha256'] = '0' * 64
    with pytest.raises(OrderedWorkError) as error:
        flow.submit(replace(proposal, _receipt_json=json.dumps(forged)))
    assert error.value.code == 'invalid_mutation'
    assert flow.view()['pending'] is None and not flow.journal


def test_rollback_invalidates_descendants_preserves_reference_journal_and_rejects_old_revision():
    flow = work(catalog())
    first = submit(flow)
    accept(flow)
    second = submit(flow, 'umbrella')
    accept(flow)
    third = submit(flow, 'salmon')
    stale_review = flow.validate_review(third.receipt['id'], third.receipt['sha256'], 'accept', 'old review', audit=audit_payload(flow))
    rollback = flow.validate_rollback(1, first.receipt['id'], flow.view()['generation'], 'Reference requires correction')
    flow.commit_rollback(rollback)
    assert flow.view()['accepted'] == [] and flow.view()['pending'] is None
    assert flow.view()['current']['step'] == 1 and flow.view()['generation'] == 2
    assert set(rollback.invalidated_receipts) == {first.receipt['id'], second.receipt['id'], third.receipt['id']}
    assert all(row.receipt in flow.journal for row in (first, second, third))
    with pytest.raises(OrderedWorkError) as error:
        flow.commit_review(stale_review)
    assert error.value.code == 'stale_mutation'
    new = submit(flow)
    assert new.receipt['reference'] == first.receipt['reference'] and new.receipt['id'] != first.receipt['id']


@pytest.mark.parametrize('reference', [None, {}, 'catalogue'])
def test_reference_mode_needs_validated_catalogue_object(reference):
    with pytest.raises(OrderedWorkError) as error:
        work(reference)
    assert error.value.code == 'reference_required'


def test_open_text_chain_contract_and_candidate_shapes_remain_unchanged():
    flow = work(None, validator='text_chain')
    contract = {'schema_version': 1, 'run_id': 'r-test', 'workflow_id': 'ow-test',
                'validator': 'text_chain', 'order': ['A', 'B'], 'rounds': 2,
                'seed': 'あお', 'participants': {'A': 'a-one', 'B': 'a-two'}}
    assert flow.view()['contract_sha256'] == digest(contract)
    assert 'reference' not in flow.view()
    proposed = args(flow)
    del proposed['reference_id']
    receipt = flow.validate_submission('a-one', proposed).receipt
    assert 'reference' not in receipt
    assert receipt['checks']['semantic_status'] == 'unchecked'
    assert receipt['checks']['validator'] == 'text_chain'
    with pytest.raises(OrderedWorkError) as error:
        work(catalog(), validator='text_chain')
    assert error.value.code == 'unexpected_reference'
