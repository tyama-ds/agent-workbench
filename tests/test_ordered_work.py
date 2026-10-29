"""Pure synthetic ordered-work contracts; no model, mail, settings or dictionary."""
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from workbench.ordered_work import (MAX_JOURNAL, OrderedWork, OrderedWorkError,
                                    declare)


BINDINGS = {'writer': 'a-writer', 'checker': 'a-checker', 'editor': 'a-editor'}


def workflow(order=None, rounds=1, seed='あお', **kwargs):
    return declare({'order': order or ['writer', 'checker'], 'rounds': rounds,
                    'seed': seed, 'validator': 'text_chain'},
                   BINDINGS, run_id='r-example', workflow_id='ow-example', **kwargs)


def arguments(work, value='おか', summary='Synthetic proposed value, not dictionary proof.'):
    current = work.view()['current']
    return {key: current[key] for key in ('step', 'generation', 'dependency_receipt',
                                        'dependency_sha256')} | {'value': value, 'summary': summary}


def propose(work, value='おか', summary='Synthetic value'):
    current = work.view()['current']
    return work.validate_submission(current['actor_id'], arguments(work, value, summary))


def pending(work, value='おか'):
    proposal = propose(work, value)
    work.submit(proposal)
    return proposal.receipt


def review(work, decision='accept', feedback='Synthetic human-independent review'):
    candidate = work.view()['pending']
    mutation = work.validate_review(candidate['id'], candidate['sha256'], decision, feedback)
    work.commit_review(mutation)
    return mutation


def assert_unchanged(work, before, journal):
    assert work.view() == before and work.journal == journal


def assert_digest(receipt):
    body = {key: value for key, value in receipt.items() if key not in {'id', 'sha256'}}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    assert receipt['sha256'] == digest and receipt['id'].endswith(digest)


def test_declaration_uses_actual_bindings_and_has_no_side_effects_on_inputs():
    spec = {'order': ['editor', 'writer'], 'rounds': 2, 'seed': 'あお', 'validator': 'text_chain'}
    bindings = copy.deepcopy(BINDINGS)
    work = OrderedWork.declare(spec, bindings, run_id='r-test', workflow_id='ordered-test')
    spec['order'][0] = 'checker'
    bindings['editor'] = 'a-wrong'
    state = work.view()
    assert state['phase'] == 'ready' and not state['complete']
    assert state['current'] == {'step': 1, 'generation': 1, 'actor_id': 'a-editor',
        'participant_key': 'editor', 'dependency_receipt': state['current']['dependency_receipt'],
        'dependency_sha256': state['current']['dependency_sha256'], 'expected_head': 'お'}
    assert state['order'] == ['editor', 'writer'] and state['rounds'] == 2
    assert state['pending'] is None and state['accepted'] == [] and state['journal_count'] == 0
    assert state['state_version'] == 0 and state['generation'] == 1
    assert state['participants'] == {'editor': 'a-editor', 'writer': 'a-writer'}
    assert work.journal == []


@pytest.mark.parametrize('update', [
    {'extra': 1}, {'order': []}, {'order': 'writer'}, {'order': ('writer',)},
    {'order': ['writer', 'writer']}, {'order': ['unknown']}, {'order': ['日本語']},
    {'order': ['x' * 25]}, {'order': [True]},
    {'rounds': True}, {'rounds': 1.0}, {'rounds': 0}, {'rounds': 65}, {'rounds': 33},
    {'validator': 'eval'}, {'validator': True}, {'validator': ['text_chain']},
    {'seed': ''}, {'seed': 'お'}, {'seed': 'おん'}, {'seed': 'おー'},
    {'seed': 'おゃ'}, {'seed': 'お\ud800'}, {'seed': 'お' * 129}, {'seed': 123},
], ids=[f'case-{i}' for i in range(25)])
def test_declaration_rejects_undeclared_or_out_of_bounds_inputs(update):
    spec = {'order': ['writer', 'checker'], 'rounds': 1, 'seed': 'あお', 'validator': 'text_chain'}
    spec.update(update)
    with pytest.raises(OrderedWorkError):
        declare(spec, BINDINGS, run_id='r-test', workflow_id='ow-test')


@pytest.mark.parametrize('spec', [None, [], {}, {'order': ['writer'], 'rounds': 1, 'seed': 'あお'}])
def test_declaration_requires_all_exact_fields(spec):
    with pytest.raises(OrderedWorkError):
        declare(spec, BINDINGS, run_id='r-test', workflow_id='ow-test')


@pytest.mark.parametrize('bindings', [
    None, [], {}, {'writer': 'a-same', 'checker': 'a-same'}, {'writer': True},
    {'writer': 'a valid id'}, {'writer': 'a-' + 'x' * 80}, {'wrong key': 'a-writer'},
    {f'key{i}': f'a-{i}' for i in range(17)},
])
def test_participant_bindings_are_finite_and_actual_ids_are_distinct(bindings):
    with pytest.raises(OrderedWorkError):
        declare({'order': ['writer'], 'rounds': 1, 'seed': 'あお', 'validator': 'text_chain'},
                bindings, run_id='r-test', workflow_id='ow-test')


@pytest.mark.parametrize('field,value', [('run_id', ''), ('run_id', True), ('workflow_id', '../x'),
                                        ('workflow_id', 'x' * 81)])
def test_workflow_identity_is_bounded(field, value):
    kwargs = {'run_id': 'r-test', 'workflow_id': 'ow-test', field: value}
    with pytest.raises(OrderedWorkError):
        declare({'order': ['writer'], 'rounds': 1, 'seed': 'あお', 'validator': 'text_chain'},
                BINDINGS, **kwargs)


def test_maximum_participants_steps_and_value_summary_sizes_are_explicit():
    bindings = {f'p{i}': f'a-{i}' for i in range(16)}
    work = declare({'order': list(bindings), 'rounds': 4, 'seed': 'あお', 'validator': 'text_chain'},
                   bindings, run_id='r-test', workflow_id='ow-test')
    receipt = work.validate_submission('a-0', arguments(work, 'お' + 'か' * 127, 's' * 512)).receipt
    assert len(receipt['value']) == 128 and len(receipt['summary']) == 512
    assert receipt['checks']['semantic_status'] == 'unchecked'  # Not a dictionary word claim.
    with pytest.raises(OrderedWorkError):
        work.validate_submission('a-0', arguments(work, 'おか', 's' * 513))


@pytest.mark.parametrize('key', ['1A', '_A', '-A', 'x' * 24])
def test_participant_keys_match_existing_spawn_contract(key):
    work = declare({'order': [key], 'rounds': 1, 'seed': 'あお', 'validator': 'text_chain'},
                   {key: 'a-actual'}, run_id='r-test', workflow_id='ow-test')
    assert work.view()['current']['participant_key'] == key
    assert work.view()['current']['actor_id'] == 'a-actual'


def test_proposal_and_review_are_preflight_only_until_mail_owner_commits():
    work = workflow()
    before, journal = work.view(), work.journal
    proposal = propose(work)
    assert_unchanged(work, before, journal)  # A mail failure simply leaves it uncommitted.
    assert_digest(proposal.receipt)
    state = work.submit(proposal)
    assert state['phase'] == 'pending_review' and state['current'] == before['current']
    assert state['accepted'] == [] and state['state_version'] == 1
    current = state['pending']
    before, journal = work.view(), work.journal
    mutation = work.validate_review(current['id'], current['sha256'], 'accept', 'checked')
    assert_unchanged(work, before, journal)
    assert mutation.next_current['actor_id'] == 'a-checker' and mutation.next_current['step'] == 2
    assert mutation.next_current['dependency_receipt'] == current['id']
    assert mutation.affected_actor_ids == ('a-checker',) and mutation.invalidated_receipts == ()
    state = work.commit_review(mutation)
    assert state['phase'] == 'ready' and state['pending'] is None
    assert state['accepted'] == [current] and state['state_version'] == 2
    assert state['generation'] == 1 and len(work.journal) == 2
    assert_digest(work.journal[-1])


@pytest.mark.parametrize('field,value', [
    ('step', True), ('step', 1.0), ('step', 2), ('step', 0),
    ('generation', True), ('generation', 0), ('generation', 2),
    ('dependency_receipt', 'a-other'), ('dependency_sha256', '0' * 64),
    ('dependency_sha256', 'bad'), ('value', None), ('summary', ''),
    ('summary', 7), ('summary', 'a\0b'), ('summary', '\ud800'),
])
def test_submission_rejects_bad_internal_grant_or_payload_without_progress(field, value):
    work = workflow()
    before, journal = work.view(), work.journal
    args = arguments(work)
    args[field] = value
    with pytest.raises(OrderedWorkError):
        work.validate_submission('a-writer', args)
    assert_unchanged(work, before, journal)


@pytest.mark.parametrize('actor', ['a-pm', 'a-checker', True, ''])
def test_only_actual_current_owner_can_submit(actor):
    work = workflow()
    with pytest.raises(OrderedWorkError):
        work.validate_submission(actor, arguments(work))
    assert work.view()['state_version'] == 0


@pytest.mark.parametrize('args', [None, {}, []])
def test_internal_submission_requires_exact_fields(args):
    with pytest.raises(OrderedWorkError):
        workflow().validate_submission('a-writer', args)


def test_unknown_submission_field_is_not_a_new_authority_channel():
    work = workflow()
    with pytest.raises(OrderedWorkError, match='exact'):
        work.validate_submission('a-writer', arguments(work) | {'role': 'pm'})


@pytest.mark.parametrize('value,code', [
    ('お', 'value_length'), ('おゃ', 'value_characters'), ('おぁ', 'value_characters'),
    ('おゕ', 'value_characters'), ('おゖ', 'value_characters'), ('おー', 'value_characters'),
    ('おか\u3099', 'value_characters'), ('おカ', 'value_characters'), ('お漢', 'value_characters'),
    ('お か', 'value_characters'), ('お1', 'value_characters'), ('お\nか', 'value_characters'),
    ('おん', 'forbidden_suffix'), ('お\ud800', 'invalid_unicode'), ('お' * 129, 'invalid_text'),
    ('かさ', 'chain_mismatch'),
])
def test_text_chain_checks_form_without_suggesting_a_replacement(value, code):
    work = workflow()
    before = work.view()
    with pytest.raises(OrderedWorkError) as exc:
        work.validate_submission('a-writer', arguments(work, value))
    assert exc.value.code == code and work.view() == before
    assert set(exc.value.details) <= {'expected_head'}
    if code == 'chain_mismatch':
        assert exc.value.details == {'expected_head': 'お'}


def test_voiced_characters_are_exact_and_not_silently_normalized():
    work = workflow(seed='りんご')
    with pytest.raises(OrderedWorkError) as exc:
        propose(work, 'こま')
    assert exc.value.code == 'chain_mismatch' and exc.value.details == {'expected_head': 'ご'}
    assert propose(work, 'ごま').receipt['value'] == 'ごま'


def test_seed_and_accepted_values_are_unique_but_invalidated_values_are_not_active():
    work = workflow(['writer'], 4, seed='ああ')
    with pytest.raises(OrderedWorkError) as exc:
        propose(work, 'ああ')
    assert exc.value.code == 'duplicate_value'
    first = pending(work, 'あか'); review(work)
    pending(work, 'かあ'); review(work)
    with pytest.raises(OrderedWorkError) as exc:
        propose(work, 'あか')
    assert exc.value.code == 'duplicate_value'
    mutation = work.validate_rollback(1, first['id'], 1, 'Correction requested')
    work.commit_rollback(mutation)
    assert propose(work, 'あか').receipt['generation'] == 2  # New review is still required.


def test_pending_candidate_blocks_parallel_proposals_and_repeated_commit():
    work = workflow()
    one, two = propose(work), propose(work, 'おと')
    work.submit(one)
    before, journal = work.view(), work.journal
    with pytest.raises(OrderedWorkError) as exc:
        work.submit(two)
    assert exc.value.code == 'stale_mutation'
    with pytest.raises(OrderedWorkError):
        work.submit(one)
    with pytest.raises(OrderedWorkError) as exc:
        propose(work, 'おと')
    assert exc.value.code == 'pending_review'
    assert_unchanged(work, before, journal)


def test_model_meaning_is_retained_but_never_certified_by_the_machine():
    work = workflow(['writer'])
    proposal = propose(work, 'おあ', 'Deliberately unsupported meaning supplied by a synthetic actor.')
    assert proposal.receipt['checks'] == {'validator': 'text_chain', 'shape_valid': True,
        'chain_valid': True, 'unique_valid': True, 'semantic_status': 'unchecked'}
    work.submit(proposal)
    review(work)
    assert work.view()['accepted'][0]['checks']['semantic_status'] == 'unchecked'


@pytest.mark.parametrize('id_change,sha_change,decision,feedback', [
    (True, False, 'accept', 'ok'), (False, True, 'accept', 'ok'),
    (False, False, 'approve', 'ok'), (False, False, True, 'ok'),
    (False, False, 'revise', ''), (False, False, 'accept', 'x' * 513),
    (False, False, 'accept', '\ud800'),
])
def test_review_is_bound_to_exact_current_candidate_and_bounded_feedback(id_change, sha_change, decision, feedback):
    work = workflow()
    candidate = pending(work)
    before, journal = work.view(), work.journal
    with pytest.raises(OrderedWorkError):
        work.validate_review('ow-other' if id_change else candidate['id'],
                             '0' * 64 if sha_change else candidate['sha256'], decision, feedback)
    assert_unchanged(work, before, journal)


def test_revision_keeps_owner_step_and_history_but_invalidates_old_grants():
    work = workflow()
    old_args = arguments(work)
    candidate = pending(work)
    old_review = work.validate_review(candidate['id'], candidate['sha256'], 'accept', 'early')
    mutation = work.validate_review(candidate['id'], candidate['sha256'], 'revise', 'Check the meaning again')
    assert mutation.next_current['step'] == 1 and mutation.next_current['generation'] == 2
    assert mutation.next_current['actor_id'] == 'a-writer'
    assert mutation.invalidated_receipts == (candidate['id'],)
    before = work.journal
    state = work.commit_review(mutation)
    assert state['phase'] == 'ready' and state['pending'] is None and state['accepted'] == []
    assert work.journal[:len(before)] == before
    with pytest.raises(OrderedWorkError):
        work.commit_review(old_review)
    with pytest.raises(OrderedWorkError):
        work.validate_submission('a-writer', old_args)
    corrected = pending(work, 'おと')
    assert corrected['generation'] == 2 and corrected['id'] != candidate['id']
    review(work)
    assert work.view()['current']['expected_head'] == 'と'


def test_rollback_invalidates_accepted_suffix_and_pending_candidate_without_erasing_originals():
    work = workflow(['writer', 'checker', 'editor'], 2)
    first = pending(work, 'おか'); review(work)
    second = pending(work, 'かさ'); review(work)
    third = pending(work, 'さる')
    old_review = work.validate_review(third['id'], third['sha256'], 'accept', 'old')
    before, journal = work.view(), work.journal
    mutation = work.validate_rollback(2, second['id'], 1, 'Second step meaning needs correction')
    assert_unchanged(work, before, journal)
    assert mutation.next_current == {**before['current'], 'step': 2, 'generation': 2,
        'actor_id': 'a-checker', 'participant_key': 'checker', 'dependency_receipt': first['id'],
        'dependency_sha256': first['sha256'], 'expected_head': 'か'}
    assert mutation.invalidated_receipts == (second['id'], third['id'])
    assert mutation.affected_actor_ids == ('a-checker', 'a-editor')
    state = work.commit_rollback(mutation)
    assert state['accepted'] == [first] and state['pending'] is None and state['generation'] == 2
    assert work.journal[:len(journal)] == journal
    with pytest.raises(OrderedWorkError):
        work.commit_review(old_review)
    with pytest.raises(OrderedWorkError):
        work.commit_rollback(mutation)
    next_candidate = pending(work, 'かめ')
    review(work)
    assert work.view()['current']['dependency_receipt'] == next_candidate['id']
    assert work.view()['current']['expected_head'] == 'め'


@pytest.mark.parametrize('step,generation,receipt', [(True, 1, None), (0, 1, None),
    (2, 1, None), (1, True, None), (1, 2, None), (1, 1, 'ow-wrong')])
def test_rollback_requires_current_accepted_step_and_generation(step, generation, receipt):
    work = workflow()
    current = pending(work); review(work)
    before, journal = work.view(), work.journal
    with pytest.raises(OrderedWorkError):
        work.validate_rollback(step, receipt or current['id'], generation, 'reason')
    assert_unchanged(work, before, journal)


def test_six_synthetic_steps_require_six_separate_reviews_and_complete_has_no_current():
    work = workflow(['writer', 'checker', 'editor'], 2)
    actors, receipts = [], []
    for value in ('おか', 'かさ', 'さる', 'るす', 'すし', 'しま'):
        actors.append(work.view()['current']['actor_id'])
        receipt = pending(work, value)
        assert not work.view()['complete']
        receipts.append(receipt)
        review(work)
    state = work.view()
    assert actors == ['a-writer', 'a-checker', 'a-editor'] * 2
    assert state['phase'] == 'complete' and state['complete'] and state['current'] is None
    assert state['pending'] is None and state['accepted'] == receipts
    assert state['state_version'] == 12 and state['generation'] == 1
    assert len(work.journal) == 12
    with pytest.raises(OrderedWorkError):
        work.validate_submission('a-writer', {'step': 1, 'generation': 1,
            'dependency_receipt': receipts[-1]['id'], 'dependency_sha256': receipts[-1]['sha256'],
            'value': 'まめ', 'summary': 'No seventh step'})
    mutation = work.validate_rollback(4, receipts[3]['id'], 1, 'Review later evidence')
    assert mutation.next_current['step'] == 4
    assert not work.commit_rollback(mutation)['complete']


def test_receipts_are_immutable_and_all_public_projections_are_detached():
    work = workflow()
    proposal = propose(work)
    with pytest.raises(FrozenInstanceError):
        proposal.actor_id = 'a-forged'
    detached = proposal.receipt
    detached['value'] = 'おと'
    state = work.submit(proposal)
    state['pending']['checks']['semantic_status'] = 'proved'
    state['participants']['writer'] = 'a-forged'
    work.journal[0]['value'] = 'おと'
    assert work.view()['pending']['value'] == 'おか'
    assert work.view()['pending']['checks']['semantic_status'] == 'unchecked'
    assert work.view()['participants']['writer'] == 'a-writer'
    pending_receipt = work.view()['pending']
    mutation = work.validate_review(pending_receipt['id'], pending_receipt['sha256'], 'accept', 'ok')
    mutation.next_current['actor_id'] = 'a-forged'
    mutation.receipt['feedback'] = 'changed'
    state = work.commit_review(mutation)
    state['accepted'][0]['value'] = 'おと'
    assert work.view()['accepted'][0]['value'] == 'おか'


def test_forged_proposal_or_review_fields_are_revalidated_before_commit():
    work = workflow()
    proposal = propose(work)
    forged = replace(proposal, _receipt_json=proposal._receipt_json.replace('おか', 'おと'))
    before = work.view()
    with pytest.raises(OrderedWorkError):
        work.submit(forged)
    assert work.view() == before
    work.submit(proposal)
    receipt = work.view()['pending']
    mutation = work.validate_review(receipt['id'], receipt['sha256'], 'accept', 'ok')
    forged = replace(mutation, _next_json='null')
    before = work.view()
    with pytest.raises(OrderedWorkError):
        work.commit_review(forged)
    assert work.view() == before


def test_cross_workflow_candidates_cannot_be_committed_even_with_same_actor_and_values():
    one = workflow()
    two = declare({'order': ['writer', 'checker'], 'rounds': 1, 'seed': 'あお', 'validator': 'text_chain'},
                  BINDINGS, run_id='r-other', workflow_id='ow-other')
    candidate = propose(one)
    with pytest.raises(OrderedWorkError):
        two.submit(candidate)
    assert candidate.receipt['id'] != propose(two).receipt['id']


def test_journal_is_bounded_and_refuses_new_work_instead_of_evicting_evidence():
    work = workflow(['writer'])
    for _ in range(MAX_JOURNAL // 2):
        pending(work)
        review(work, 'revise', 'Synthetic repeat to reach the explicit storage bound')
    before, journal = work.view(), work.journal
    assert len(journal) == MAX_JOURNAL
    with pytest.raises(OrderedWorkError) as exc:
        propose(work)
    assert exc.value.code == 'journal_limit'
    assert_unchanged(work, before, journal)
    for row in journal:
        assert_digest(row)
