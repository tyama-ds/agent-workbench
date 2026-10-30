"""Adaptive formation archives are display evidence, never executable authority."""
import copy
import json

import pytest

from test_history_persistence import document
from workbench.history import HistoryError, HistoryStore, archived_view, public_document, redact_document, validate
from workbench.redaction import SecretRedactor


def formation_document(phase='reviewing', artifacts=1):
    value = document()
    pm = value['agents'][0]
    worker_id, reviewer_id = 'a-' + '3' * 16, 'a-' + '4' * 16
    pm['kind'] = 'author'
    pm['hierarchy'] = {'depth': 0, 'root_pm_id': pm['id'], 'unit_id': pm['id'],
                       'direct_children': [worker_id], 'can_delegate': True}
    worker = copy.deepcopy(pm)
    worker.update(id=worker_id, name='Author a', parent_id=pm['id'], status='done')
    worker['hierarchy'] = {'depth': 1, 'root_pm_id': pm['id'], 'unit_id': pm['id'],
                           'direct_children': [], 'can_delegate': True}
    reviewer = copy.deepcopy(pm)
    reviewer.update(id=reviewer_id, name='Reviewer a', kind='independent_reviewer', role='pm', status='working')
    reviewer.pop('hierarchy')
    value['agents'].extend([worker, reviewer])
    decision = 'accept' if phase in ('accepted', 'complete') else 'revise' if phase == 'revise' else None
    value['run'].update(adaptive_team=True, max_delegation_depth=3,
        agent_ids=[pm['id'], worker_id, reviewer_id], formation={
            'version': 1, 'phase': phase, 'difficulty': 'low', 'reason': 'Read a single artifact',
            'worker_ids': [worker_id], 'reviewer_id': reviewer_id, 'reviewer_slots': 1,
            'candidate_count': 1, 'stale_reason': '', 'candidate': {
                'id': 'c-' + 'a' * 32, 'round': 1, 'summary_sha256': 'a' * 64,
                'manifest_sha256': 'b' * 64, 'artifact_count': artifacts,
                'summary_only': artifacts == 0, 'read_count': artifacts,
                'consumed_read_count': artifacts, 'decision': decision, 'feedback': 'Check a value'}})
    return value


def test_manual_archive_keeps_exact_old_shape_without_optin_fields():
    value = document()
    projected = public_document(value['run'], value['agents'], [], [])
    assert validate(projected) == value
    assert 'adaptive_team' not in projected['run'] and 'formation' not in projected['run']
    assert all('kind' not in agent for agent in projected['agents'])


def test_separate_root_reviewer_roundtrips_without_pm_or_hierarchy_authority(tmp_path):
    value = formation_document('accepted')
    store = HistoryStore(tmp_path / 'history')
    try:
        store.save(value, lambda text: text)
        saved, at = store.read(value['run']['id'])
        assert saved == value
        view = archived_view(saved, at)
        reviewer = view['agents'][2]
        assert reviewer['parent_id'] is None and reviewer['id'] not in view['run']['pm_agent_ids']
        assert reviewer['kind'] == 'independent_reviewer' and 'hierarchy' not in reviewer
        assert all(agent['read_only'] and not agent['message_eligibility']['allowed'] for agent in view['agents'])
        assert not view['agents'][0]['hierarchy']['can_delegate']
        assert view['run']['formation']['phase'] == 'accepted'
        assert saved == value  # Opening an archive cannot mutate its candidate or start it.
    finally:
        store.close()


def test_redaction_preserves_validated_linkage_and_hashes_but_masks_prose():
    value = formation_document()
    redactor = SecretRedactor()
    redactor.remember(['a'])
    masked = redact_document(value, redactor.redact)
    assert validate(masked) is masked
    before, after = value['run']['formation'], masked['run']['formation']
    for key in ('phase', 'difficulty', 'worker_ids', 'reviewer_id'):
        assert after[key] == before[key]
    for key in ('id', 'summary_sha256', 'manifest_sha256'):
        assert after['candidate'][key] == before['candidate'][key]
    assert after['reason'] != before['reason'] and '[redacted]' in after['reason']
    assert after['candidate']['feedback'] != before['candidate']['feedback']
    assert masked['agents'][1]['name'] != value['agents'][1]['name']
    assert [agent['kind'] for agent in masked['agents']] == ['author', 'author', 'independent_reviewer']


@pytest.mark.parametrize('phase', ['unplanned', 'working', 'reviewing', 'accepted', 'revise', 'stale', 'blocked', 'complete'])
def test_bounded_phase_evidence_can_be_saved_without_changing_the_phase(phase):
    value = formation_document(phase)
    if phase == 'unplanned':
        value['agents'] = value['agents'][:1]
        pm = value['agents'][0]
        pm['hierarchy']['direct_children'] = []
        value['run']['agent_ids'] = [pm['id']]
        value['run']['formation'].update(difficulty=None, reason='', worker_ids=[], reviewer_id=None,
                                         candidate_count=0, candidate=None)
    assert validate(value)['run']['formation']['phase'] == phase


def test_summary_only_candidate_is_explicit_and_does_not_invent_file_reads():
    value = formation_document('accepted', artifacts=0)
    candidate = validate(value)['run']['formation']['candidate']
    assert candidate['summary_only'] is True
    assert candidate['artifact_count'] == candidate['read_count'] == candidate['consumed_read_count'] == 0


@pytest.mark.parametrize('bad', [
    'missing_mode', 'false_mode', 'unknown_field', 'phase_object', 'version_bool',
    'count_bool', 'too_many_rounds', 'duplicate_worker', 'missing_worker', 'reviewer_pm',
    'reviewer_child', 'reviewer_hierarchy', 'reviewer_spawns', 'forged_kind', 'manual_kind',
    'candidate_missing', 'candidate_id', 'candidate_hash', 'candidate_count_bool',
    'read_ahead', 'consume_ahead', 'summary_only_lie', 'accept_without_decision',
    'feedback_oversize', 'private_candidate', 'reason_oversize'])
def test_malformed_or_authority_confused_archives_fail_closed(bad):
    value = formation_document('accepted')
    run, agents = value['run'], value['agents']
    formation, candidate = run['formation'], run['formation']['candidate']
    if bad == 'missing_mode': run.pop('adaptive_team')
    elif bad == 'false_mode': run['adaptive_team'] = False
    elif bad == 'unknown_field': formation['capability'] = True
    elif bad == 'phase_object': formation['phase'] = {}
    elif bad == 'version_bool': formation['version'] = True
    elif bad == 'count_bool': formation['candidate_count'] = True
    elif bad == 'too_many_rounds': formation['candidate_count'] = 4
    elif bad == 'duplicate_worker': formation['worker_ids'] *= 2
    elif bad == 'missing_worker': formation['worker_ids'] = ['a-' + '9' * 16]
    elif bad == 'reviewer_pm': run['pm_agent_ids'].append(agents[2]['id'])
    elif bad == 'reviewer_child': agents[2]['parent_id'] = agents[0]['id']
    elif bad == 'reviewer_hierarchy': agents[2]['hierarchy'] = copy.deepcopy(agents[0]['hierarchy'])
    elif bad == 'reviewer_spawns': agents[1]['parent_id'] = agents[2]['id']
    elif bad == 'forged_kind': agents[1]['kind'] = 'independent_reviewer'
    elif bad == 'manual_kind':
        value = document()
        value['agents'][0]['kind'] = 'independent_reviewer'
    elif bad == 'candidate_missing': formation['candidate'] = None
    elif bad == 'candidate_id': candidate['id'] = 'human-approved'
    elif bad == 'candidate_hash': candidate['manifest_sha256'] = 'a' * 63
    elif bad == 'candidate_count_bool': candidate['artifact_count'] = True
    elif bad == 'read_ahead': candidate['read_count'] = 2
    elif bad == 'consume_ahead': candidate['read_count'] = 0
    elif bad == 'summary_only_lie': candidate['summary_only'] = True
    elif bad == 'accept_without_decision': candidate['decision'] = None
    elif bad == 'feedback_oversize': candidate['feedback'] = 'x' * 4001
    elif bad == 'private_candidate': candidate['artifact_paths'] = ['private/path']
    elif bad == 'reason_oversize': formation['reason'] = 'x' * 2001
    with pytest.raises(HistoryError):
        validate(value)


def test_private_internal_formation_state_is_not_projected_as_display_data():
    value = formation_document()
    value['run']['_formation'] = {'artifact_paths': ['private/path'], 'read_tokens': ['private-token']}
    value['agents'][2]['_candidate_token'] = 'private-token'
    projected = public_document(value['run'], value['agents'], [], [])
    assert validate(projected)
    assert 'private-token' not in json.dumps(projected) and 'private/path' not in json.dumps(projected)
