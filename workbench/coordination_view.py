"""Bounded display projections of canonical collaboration state.

No returned field grants authority. Archived values are observations only and
must never be passed to OrderedWork, mail intake, or report-review operations.
"""
from __future__ import annotations

import copy
import math
import re

from .ordered_audit import current_reference_report_approval


PHASES = {'ready', 'pending_review', 'complete'}
STATUSES = {'idle', 'queued', 'working', 'running', 'waiting', 'stopping', 'stopped', 'done', 'error', 'interrupted'}
DEPENDENCIES = {'human_input', 'error', 'inbox_pending', 'pm_review', 'turn', 'submit', 'report_review', 'completed'}
PROJECTION_COUNTS = ('raw_message_count', 'projected_message_count', 'raw_group_count',
                     'kept_group_count', 'omitted_group_count', 'omitted_message_count', 'trimmed_message_count')


def projection_summary(agent):
    """Latest actual provider projection counts; no record IDs or trusted pins."""
    value = getattr(agent, '_ordered_projection_observation', None)
    if not isinstance(value, dict):
        return None
    if (value.get('mode') != 'ordered_bounded_projection' or
            any(type(value.get(key)) is not int or not 0 <= value[key] <= 1000000 for key in PROJECTION_COUNTS) or
            any(type(value.get(key)) is not bool for key in ('projection_changed', 'detail_truncated')) or
            not isinstance(value.get('missing_trusted_record_ids'), list)):
        return None
    return {'mode': 'ordered_bounded_projection', **{key: value[key] for key in PROJECTION_COUNTS},
            'projection_changed': value['projection_changed'], 'detail_truncated': value['detail_truncated'],
            'missing_record_count': len(value['missing_trusted_record_ids'])}


def _report(child, pm, box=None, *, redact=None):
    review = pm.worker_report_reviews.get(child.id)
    reviewed = review.get('result_revision') if isinstance(review, dict) else None
    accepted = bool(review == {'result_revision': child.result_revision, 'decision': 'accept'}
        and child.finished_revision == child.result_revision
        and pm.worker_report_deliveries.get(child.id) == child.result_revision
        and pm.worker_report_consumed.get(child.id) == child.result_revision
        and child.status == 'done' and not child.pending and not child.question and not child.last_error
        and current_reference_report_approval(box, child, pm, redact=redact))
    return {'agent_id': child.id, 'participant_key': child.participant_key,
            'current_revision': child.result_revision, 'formal_revision': child.finished_revision,
            'delivered_revision': pm.worker_report_deliveries.get(child.id),
            'consumed_revision': pm.worker_report_consumed.get(child.id),
            'reviewed_revision': reviewed, 'accepted_current': accepted}


def coordination_projection(run, agents, observed_at, *, redact=None):
    """Read one live flow without touching messages, counters, or acceptance."""
    box = run.get('_ordered_work')
    if not box:
        return None, {}
    state = box['flow'].view()
    journal = box['flow'].journal
    pm = agents[box['pm_id']]
    reports = [_report(agents[ident], pm, box, redact=redact) for ident in box['participants'].values()]
    current, candidate = state['current'], state['pending']
    reference = state.get('reference')
    # Catalog descriptors can also include source prose; only identity/count/scope
    # are needed here. Never copy the catalog, current grant, or receipt tokens.
    catalog = run.get('_ordered_reference')
    descriptor = catalog.descriptor() if catalog is not None and state['validator'] == 'reference_text_chain' else None
    pending = None if candidate is None else {
        'step': candidate['step'], 'actor_id': candidate['actor_id'], 'value': candidate['value'],
        'summary': candidate['summary'][:240], 'summary_truncated': len(candidate['summary']) > 240,
        'semantic_status': candidate['checks']['semantic_status']}
    result = {'schema_version': 1, 'kind': 'ordered_work', 'observed_at': observed_at,
        'workflow_id': box['id'], 'phase': state['phase'], 'generation': state['generation'],
        'state_version': state['state_version'], 'step': current['step'] if current else None,
        'total_steps': len(state['order']) * state['rounds'], 'accepted_steps': len(state['accepted']),
        'current_actor_id': current['actor_id'] if current else None, 'pending': pending,
        'corrections': {'revisions': sum(row['kind'] == 'review' and row['decision'] == 'revise' for row in journal),
                        'rollbacks': sum(row['kind'] == 'rollback' for row in journal)},
        'reference': ({key: descriptor[key] for key in ('catalog_sha256', 'entry_count', 'semantic_scope')}
                      if descriptor else None),
        'reports': reports, 'pm_completion': {'status': pm.status,
            'completed': bool(state['complete'] and pm.status == 'done' and not pm.pending and not pm.question
                              and not pm.last_error and all(row['accepted_current'] for row in reports))},
        'history_only': False, 'read_only': True}
    per_agent = {}
    for ident in (box['pm_id'], *box['participants'].values()):
        agent = agents[ident]
        report = next((row for row in reports if row['agent_id'] == ident), None)
        if agent.question:
            reason, owner = 'human_input', None
        elif agent.status == 'error':
            reason, owner = 'error', ident
        elif agent.pending:
            reason, owner = 'inbox_pending', ident
        elif result['pm_completion']['completed']:
            reason, owner = 'completed', None
        elif state['complete']:
            reason, owner = 'report_review', pm.id
        elif candidate:
            reason, owner = 'pm_review', pm.id
        elif current['actor_id'] == ident:
            reason, owner = 'submit', ident
        else:
            reason, owner = 'turn', current['actor_id']
        per_agent[ident] = {'schema_version': 1, 'workflow_id': box['id'],
            'participant_key': agent.participant_key, 'role': 'pm' if ident == pm.id else 'worker',
            'step': result['step'], 'current_actor': current is not None and current['actor_id'] == ident,
            'dependency': {'reason': reason, 'actor_id': owner}, 'report': copy.deepcopy(report),
            'context_projection': projection_summary(agent), 'history_only': False, 'read_only': True}
    validate_coordination(result)
    for row in per_agent.values():
        validate_coordination(row, agent=True)
    return result, per_agent


def _shape(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise ValueError('Invalid coordination display fields')


def _integer(value, maximum=1000000, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid coordination display number')


def _text(value, limit):
    # Permit bounded redaction expansion in stored display prose.
    if type(value) is not str or len(value) > limit:
        raise ValueError('Invalid coordination display text')


def _enum(value, values):
    if type(value) is not str or value not in values:
        raise ValueError('Invalid coordination display enum')


def _id(value, *, workflow=False, optional=False):
    if optional and value is None:
        return
    if type(value) is not str or re.fullmatch(r'ow-[0-9a-f]{24}' if workflow else r'a-[0-9a-f]{16}', value) is None:
        raise ValueError('Invalid coordination display identity')


def _bool(value):
    if type(value) is not bool:
        raise ValueError('Invalid coordination display boolean')


def _report_valid(value):
    _shape(value, 'agent_id participant_key current_revision formal_revision delivered_revision consumed_revision reviewed_revision accepted_current')
    _id(value['agent_id']); _text(value['participant_key'], 240)
    _integer(value['current_revision'])
    for key in ('formal_revision', 'delivered_revision', 'consumed_revision', 'reviewed_revision'):
        _integer(value[key], optional=True)
    _bool(value['accepted_current'])
    if value['accepted_current'] and any(value[key] != value['current_revision'] for key in
            ('formal_revision', 'delivered_revision', 'consumed_revision', 'reviewed_revision')):
        raise ValueError('Accepted report revisions disagree')


def validate_coordination(value, *, agent=False):
    """Strict optional display schema. None means unavailable, never success."""
    if value is None:
        return
    common = 'schema_version workflow_id history_only read_only'
    _shape(value, common + (' participant_key role step current_actor dependency report context_projection' if agent else
        ' kind observed_at phase generation state_version step total_steps accepted_steps current_actor_id pending corrections reference reports pm_completion'))
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unsupported coordination display version')
    _id(value['workflow_id'], workflow=True)
    _bool(value['history_only'])
    if value['read_only'] is not True:
        raise ValueError('Coordination display cannot grant actions')
    _integer(value['step'], 64, optional=True)
    if agent:
        _text(value['participant_key'], 240); _enum(value['role'], {'pm', 'worker'}); _bool(value['current_actor'])
        _shape(value['dependency'], 'reason actor_id')
        _enum(value['dependency']['reason'], DEPENDENCIES); _id(value['dependency']['actor_id'], optional=True)
        if value['report'] is not None:
            _report_valid(value['report'])
        item = value['context_projection']
        if item is not None:
            _shape(item, 'mode projection_changed detail_truncated missing_record_count ' + ' '.join(PROJECTION_COUNTS))
            _enum(item['mode'], {'ordered_bounded_projection'})
            for key in (*PROJECTION_COUNTS, 'missing_record_count'):
                _integer(item[key])
            _bool(item['projection_changed']); _bool(item['detail_truncated'])
        return
    _enum(value['kind'], {'ordered_work'}); _enum(value['phase'], PHASES)
    if type(value['observed_at']) not in (int, float) or not math.isfinite(value['observed_at']) or not 0 <= value['observed_at'] <= 253402300799:
        raise ValueError('Invalid coordination observation time')
    _integer(value['generation'], 257); _integer(value['state_version'], 256)
    _integer(value['total_steps'], 64); _integer(value['accepted_steps'], 64)
    if not 1 <= value['total_steps'] or value['accepted_steps'] > value['total_steps']:
        raise ValueError('Invalid coordination progress')
    _id(value['current_actor_id'], optional=True)
    complete = value['phase'] == 'complete'
    if complete != (value['accepted_steps'] == value['total_steps']) or complete != (value['step'] is None) or complete != (value['current_actor_id'] is None):
        raise ValueError('Inconsistent coordination phase')
    if not complete and value['step'] != value['accepted_steps'] + 1:
        raise ValueError('Inconsistent coordination step')
    pending = value['pending']
    if (pending is not None) != (value['phase'] == 'pending_review'):
        raise ValueError('Inconsistent coordination candidate')
    if pending is not None:
        _shape(pending, 'step actor_id value summary summary_truncated semantic_status')
        _id(pending['actor_id']); _integer(pending['step'], 64)
        if pending['step'] != value['step'] or pending['actor_id'] != value['current_actor_id']:
            raise ValueError('Candidate is not current')
        _text(pending['value'], 1280); _text(pending['summary'], 2400); _bool(pending['summary_truncated'])
        _enum(pending['semantic_status'], {'unchecked', 'reference_matched'})
    _shape(value['corrections'], 'revisions rollbacks')
    for number in value['corrections'].values():
        _integer(number, 256)
    reference = value['reference']
    if reference is not None:
        _shape(reference, 'catalog_sha256 entry_count semantic_scope')
        if type(reference['catalog_sha256']) is not str or re.fullmatch('[0-9a-f]{64}', reference['catalog_sha256']) is None:
            raise ValueError('Invalid reference identity')
        _integer(reference['entry_count'], 128)
        _enum(reference['semantic_scope'], {'reference_match_only'})
    if type(value['reports']) is not list or not 1 <= len(value['reports']) <= 16:
        raise ValueError('Invalid coordination reports')
    for report in value['reports']:
        _report_valid(report)
    if len({row['agent_id'] for row in value['reports']}) != len(value['reports']):
        raise ValueError('Duplicate coordination report')
    _shape(value['pm_completion'], 'status completed')
    _enum(value['pm_completion']['status'], STATUSES); _bool(value['pm_completion']['completed'])
    if value['pm_completion']['completed'] and (not complete or value['pm_completion']['status'] != 'done' or not all(row['accepted_current'] for row in value['reports'])):
        raise ValueError('Incomplete coordination cannot claim PM completion')


def restore_coordination_metadata(before, after):
    """Restore validated opaque IDs/enums after history's prose redaction.

    Participant labels, candidate values and summaries always stay masked.
    The caller validates the original display schema first.
    """
    fields = {'workflow_id', 'agent_id', 'actor_id', 'current_actor_id', 'catalog_sha256',
              'kind', 'phase', 'role', 'reason', 'semantic_status', 'semantic_scope', 'status', 'mode'}
    if isinstance(before, dict) and isinstance(after, dict):
        for key, value in before.items():
            if key in fields:
                after[key] = copy.deepcopy(value)
            elif key in after:
                restore_coordination_metadata(value, after[key])
    elif isinstance(before, list) and isinstance(after, list):
        for old, new in zip(before, after):
            restore_coordination_metadata(old, new)
