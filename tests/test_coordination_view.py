"""Read-only collaboration observations; synthetic providers and temporary state."""
import copy
import json
from types import SimpleNamespace

import pytest

from workbench.coordination_view import coordination_projection, projection_summary, validate_coordination
from workbench.history import HistoryError, archived_view, public_document, redact_document, validate
from workbench.ordered_work import OrderedWork
from workbench.redaction import SecretRedactor
from test_history_persistence import document
from test_ordered_engine import no_operator_credentials


PM, A, B = ('a-' + digit * 16 for digit in ('1', '2', '3'))
WORKFLOW = 'ow-' + '4' * 24


def fixture():
    flow = OrderedWork.declare({'order': ['A', 'B'], 'rounds': 1, 'seed': 'りんご', 'validator': 'text_chain'},
        {'A': A, 'B': B}, run_id='r-' + '1' * 16, workflow_id=WORKFLOW)
    def actor(ident, key):
        return SimpleNamespace(id=ident, participant_key=key, result_revision=1, finished_revision=None,
            status='idle', pending=[], question='', last_error='', worker_report_reviews={},
            worker_report_deliveries={}, worker_report_consumed={})
    agents = {PM: actor(PM, ''), A: actor(A, 'A'), B: actor(B, 'B')}
    run = {'_ordered_work': {'id': WORKFLOW, 'flow': flow, 'pm_id': PM, 'participants': {'A': A, 'B': B}}}
    return run, agents, flow


def propose(flow, word='ごま', summary='Synthetic meaning'):
    current = flow.view()['current']
    args = {key: current[key] for key in ('step', 'generation', 'dependency_receipt', 'dependency_sha256')}
    flow.submit(flow.validate_submission(current['actor_id'], args | {'value': word, 'summary': summary}))


def review(flow, decision='accept'):
    pending = flow.view()['pending']
    flow.commit_review(flow.validate_review(pending['id'], pending['sha256'], decision, 'Synthetic audit'))


def test_projection_is_detached_canonical_and_does_not_expose_grants():
    run, agents, flow = fixture()
    propose(flow, summary='x' * 300)
    before, journal = flow.view(), flow.journal
    result, members = coordination_projection(run, agents, 100)
    assert result['phase'] == 'pending_review' and result['accepted_steps'] == 0
    assert result['pending']['summary'] == 'x' * 240 and result['pending']['summary_truncated']
    assert result['pending']['semantic_status'] == 'unchecked'
    assert members[A]['dependency'] == {'reason': 'pm_review', 'actor_id': PM}
    encoded = json.dumps([result, members])
    for forbidden in ('dependency_receipt', 'dependency_sha256', 'report_id', 'dispatch', 'conversation', 'trusted_record_ids'):
        assert forbidden not in encoded
    result['pending']['value'] = 'changed'
    members[A]['report']['current_revision'] = 100
    assert flow.view() == before and flow.journal == journal and agents[A].result_revision == 1


def test_revise_and_rollback_are_counts_not_accumulated_success():
    run, agents, flow = fixture()
    propose(flow); review(flow, 'revise')
    result, _ = coordination_projection(run, agents, 100)
    assert result['corrections'] == {'revisions': 1, 'rollbacks': 0}
    assert result['generation'] == 2 and result['step'] == 1 and result['accepted_steps'] == 0
    propose(flow); review(flow)
    accepted = flow.view()['accepted'][0]
    flow.commit_rollback(flow.validate_rollback(1, accepted['id'], flow.view()['generation'], 'Synthetic correction'))
    result, _ = coordination_projection(run, agents, 101)
    assert result['generation'] == 3 and result['accepted_steps'] == 0
    assert result['corrections'] == {'revisions': 1, 'rollbacks': 1}


@pytest.mark.parametrize('stale', ['formal', 'delivered', 'consumed', 'reviewed', 'pending', 'question', 'error'])
def test_current_report_acceptance_requires_every_current_boundary(stale):
    run, agents, _ = fixture()
    child, pm = agents[A], agents[PM]
    child.status = 'done'; child.finished_revision = 1
    pm.worker_report_deliveries[A] = pm.worker_report_consumed[A] = 1
    pm.worker_report_reviews[A] = {'result_revision': 1, 'decision': 'accept'}
    assert coordination_projection(run, agents, 100)[0]['reports'][0]['accepted_current']
    if stale == 'formal': child.finished_revision = None
    elif stale == 'delivered': pm.worker_report_deliveries[A] = 0
    elif stale == 'consumed': pm.worker_report_consumed[A] = 0
    elif stale == 'reviewed': pm.worker_report_reviews[A]['result_revision'] = 0
    elif stale == 'pending': child.pending.append('unread')
    elif stale == 'question': child.question = 'Human input needed'
    else: child.last_error = 'Failed'
    assert not coordination_projection(run, agents, 101)[0]['reports'][0]['accepted_current']


def test_workflow_complete_is_separate_from_formal_reviews_and_pm_completion():
    run, agents, flow = fixture()
    propose(flow); review(flow); propose(flow, 'まめ'); review(flow)
    result, _ = coordination_projection(run, agents, 100)
    assert result['phase'] == 'complete' and result['step'] is None and result['current_actor_id'] is None
    assert result['accepted_steps'] == 2 and not result['pm_completion']['completed']
    for ident in (A, B):
        agents[ident].status = 'done'; agents[ident].finished_revision = 1
        agents[PM].worker_report_deliveries[ident] = agents[PM].worker_report_consumed[ident] = 1
        agents[PM].worker_report_reviews[ident] = {'result_revision': 1, 'decision': 'accept'}
    assert not coordination_projection(run, agents, 101)[0]['pm_completion']['completed']
    agents[PM].status = 'done'
    result, members = coordination_projection(run, agents, 102)
    assert result['pm_completion']['completed'] and members[A]['dependency']['reason'] == 'completed'


def test_dependencies_do_not_label_error_or_human_question_as_healthy_waiting():
    run, agents, _ = fixture()
    _, members = coordination_projection(run, agents, 100)
    assert members[A]['dependency']['reason'] == 'submit' and members[B]['dependency']['actor_id'] == A
    agents[A].pending = ['grant']
    assert coordination_projection(run, agents, 100)[1][A]['dependency']['reason'] == 'inbox_pending'
    agents[A].question = 'Question'
    assert coordination_projection(run, agents, 100)[1][A]['dependency']['reason'] == 'human_input'
    agents[A].question = ''; agents[A].status = 'error'
    assert coordination_projection(run, agents, 100)[1][A]['dependency']['reason'] == 'error'


def test_context_projection_summary_is_numeric_and_does_not_expose_record_pins():
    _, agents, _ = fixture()
    observation = {'mode': 'ordered_bounded_projection', 'raw_message_count': 30, 'projected_message_count': 12,
        'raw_group_count': 10, 'kept_group_count': 4, 'omitted_group_count': 6, 'omitted_message_count': 18,
        'trimmed_message_count': 3, 'projection_changed': True, 'detail_truncated': False,
        'missing_trusted_record_ids': [], 'trimmed_record_ids': [7], 'private_extra': 'never public'}
    agents[A]._ordered_projection_observation = observation
    summary = projection_summary(agents[A])
    assert summary['raw_message_count'] == 30 and summary['missing_record_count'] == 0
    assert 'record_ids' not in json.dumps(summary) and 'private_extra' not in summary
    summary['raw_message_count'] = 0
    assert observation['raw_message_count'] == 30
    observation['raw_message_count'] = float('nan')
    assert projection_summary(agents[A]) is None


def test_unconfigured_run_and_optional_null_are_unavailable_not_completion():
    assert coordination_projection({}, {}, 100) == (None, {})
    validate_coordination(None)
    value = document(); value['run']['coordination'] = None; value['agents'][0]['coordination'] = None
    assert validate(value) == value


@pytest.mark.parametrize('mutation', ['version', 'extra_token', 'nan', 'bool_count', 'oversize', 'phase', 'candidate', 'reports', 'completion', 'identity'])
def test_malformed_display_history_is_rejected(mutation):
    run, agents, _ = fixture(); result, _ = coordination_projection(run, agents, 100)
    if mutation == 'version': result['schema_version'] = 99
    elif mutation == 'extra_token': result['grant'] = 'not allowed'
    elif mutation == 'nan': result['observed_at'] = float('nan')
    elif mutation == 'bool_count': result['accepted_steps'] = True
    elif mutation == 'oversize': result['reports'][0]['participant_key'] = 'x' * 241
    elif mutation == 'phase': result['phase'] = 'complete'
    elif mutation == 'candidate': result['pending'] = {}
    elif mutation == 'reports': result['reports'].append(copy.deepcopy(result['reports'][0]))
    elif mutation == 'completion': result['pm_completion'] = {'status': 'done', 'completed': True}
    else: result['current_actor_id'] = 'arbitrary peer'
    with pytest.raises(ValueError): validate_coordination(result)


def history_fixture():
    run, agents, flow = fixture(); propose(flow, summary='secret-meaning a')
    result, members = coordination_projection(run, agents, 100)
    value = document(); value['run']['agent_ids'] = [PM, A, B]; value['run']['pm_agent_ids'] = [PM]
    template = value['agents'][0]
    value['agents'] = []
    for ident in (PM, A, B):
        row = copy.deepcopy(template)
        row.update(id=ident, parent_id=None if ident == PM else PM, coordination=members[ident])
        value['agents'].append(row)
    value['run']['coordination'] = result
    return value


@pytest.mark.parametrize('secret', ['secret-meaning', 'a', 'reference', 'pm_review'])
def test_history_masks_prose_but_preserves_validated_metadata_and_frozen_observation(secret):
    value = history_fixture()
    value['run']['coordination']['pending']['summary'] += ' ' + secret
    original = copy.deepcopy(value)
    mask = SecretRedactor(); mask.remember([secret])
    masked = redact_document(value, mask.redact)
    validate(masked)
    assert masked['run']['coordination']['pending']['summary'] == mask.redact(original['run']['coordination']['pending']['summary'])
    assert masked['run']['coordination']['pending']['summary'] != original['run']['coordination']['pending']['summary']
    archived = archived_view(masked, 200)
    assert archived['run']['coordination']['observed_at'] == 100
    assert archived['run']['coordination']['history_only'] and archived['run']['coordination']['read_only']
    assert all(row['coordination']['history_only'] for row in archived['agents'])
    assert value == original


def test_history_rejects_cross_run_projection_and_unknown_authority_fields():
    value = history_fixture()
    value['run']['coordination']['reports'][0]['agent_id'] = 'a-' + '9' * 16
    with pytest.raises(HistoryError): validate(value)
    value = history_fixture(); value['agents'][0]['coordination']['report_token'] = 'private'
    with pytest.raises(HistoryError): validate(value)


@pytest.mark.asyncio
async def test_real_engine_snapshot_and_archive_are_readonly_and_preserve_current_reports(tmp_path):
    from test_grounded_engine import grounded_team, begin_grounded, install_scripts, advance_grounded
    from workbench.config import Settings
    from workbench.engine import Engine
    from test_ordered_engine import ObservedClient
    engine, run, pm, workers, client, _ = await grounded_team(tmp_path)
    try:
        assert 'coordination' not in engine.snapshot()['runs'][0]
        await install_scripts(engine, run, pm, workers, client, finish=True)
        await begin_grounded(engine, run, pm)
        original = (run['model_calls'], run['tool_calls'], run['auto_collaborations'], run['_ordered_work']['flow'].view())
        full = engine.snapshot(); selected = engine.selected_snapshot(run_id=run['id'], agent_id=workers['A'].id)
        full_view, selected_view = (value['runs'][0]['coordination'] for value in (full, selected))
        full_view.pop('observed_at'); selected_view.pop('observed_at')
        assert full_view == selected_view and full_view['accepted_steps'] == 0
        assert (run['model_calls'], run['tool_calls'], run['auto_collaborations'], run['_ordered_work']['flow'].view()) == original
        await advance_grounded(engine, run, pm, workers, 6)
        live = engine.snapshot()
        current = live['runs'][0]['coordination']
        assert current['accepted_steps'] == current['total_steps'] == 6 and current['pm_completion']['completed']
        assert current['reference']['semantic_scope'] == 'reference_match_only'
        assert all(row['accepted_current'] for row in current['reports'])
        assert any('ordered_projection' in row['context_memory'] for row in live['agents'])
        assert 'entries' not in json.dumps(current) and not engine.history.error
        saved, _ = engine.history.read(run['id'])
        assert saved['run']['coordination']['phase'] == 'complete'
    finally:
        await engine.close()
    other = Engine(Settings(tmp_path / 'state'), ObservedClient())
    try:
        archived = next(row for row in other.snapshot()['runs'] if row['id'] == run['id'])
        assert archived['coordination']['history_only'] and archived['coordination']['read_only']
        assert not other.runs and not other.agents and not other.client.calls
        assert '_ordered_work' not in archived
    finally:
        await other.close()
