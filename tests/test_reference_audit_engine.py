"""Synthetic native Engine calls with source facts read from actual PM input."""
import copy
import hashlib
import json

import pytest

from workbench.coordination_view import coordination_projection, validate_coordination
from workbench.engine import TEAM_TOOLS
from workbench.ordered_audit import current_reference_report_approval
from test_engine import reply, configured, settled, start as start_regular
from test_grounded_engine import (
    PATH, catalogue, grounded_team, begin_grounded, install_scripts, advance_grounded,
    ordered_request_state,
)
from test_ordered_engine import drive, effects, no_operator_credentials, tool_results
from tools.browser_fixture import COMPACTION_CASE, SyntheticClient


pytestmark = pytest.mark.asyncio


# Frozen dev44 JSON bytes, independently read from engine.py SHA256
# ee198d532be5aa913037d531dd97737f36a0b76ae2b5a0e14689975136dd1f3f.
# Tests never read runtime artifacts or regenerate expected hashes from product.
LEGACY_TEAM_TOOLS_SHA256 = 'f4582fdfeca0a2acb7031e5106b4bc4b300df8df1cd9ddf4a35bc25ce585044c'
LEGACY_REVIEW_SHA256 = {
    'review_work_step': '63d760a1eaa06b34b78826dc78946ac615d859778b2934516ff695517171b3ca',
    'review_worker_report': '3ba4b9b29b4051edd19491a1456b659631f9f017115208873a641a6d551ac706',
}


def schema_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def assert_legacy_review_tools(tools, names):
    selected = {row['name']: row for row in tools}
    for name in names:
        assert schema_digest(selected[name]) == LEGACY_REVIEW_SHA256[name]
    assert all('audit' not in row['parameters']['properties'] for row in tools)


async def prepared(tmp_path, *, on_complete=None, fail_result_history=False):
    engine, run, pm, workers, client, work = await grounded_team(tmp_path)
    try:
        await install_scripts(engine, run, pm, workers, client, finish=False)
        if fail_result_history:
            original_record = engine.record_result

            def record(agent, source, text, **kwargs):
                if source == 'submit_work_step':
                    raise OSError('Synthetic result persistence failure')
                return original_record(agent, source, text, **kwargs)

            engine.record_result = record
        observed = []

        async def review(request):
            state = ordered_request_state(request)
            observed.append(copy.deepcopy(state))
            if state['pending']:
                return reply(calls=[('review_work_step', {'decision': 'accept',
                    'feedback': 'Synthetic source comparison; no semantic-understanding claim.',
                    'audit': copy.deepcopy(state['pending_audit'])})])
            return on_complete(state) if on_complete else reply(calls=[('wait_for_message', {})])

        client.handlers[pm.id] = review
        await begin_grounded(engine, run, pm)
        await advance_grounded(engine, run, pm, workers, 6)
        assert not pm.last_error and observed[-1]['complete']
        return engine, run, pm, workers, client, observed[-1]
    except BaseException as exc:
        try:
            await engine.close()
        except BaseException as cleanup_error:
            exc.add_note('prepared failure cleanup also failed: ' + type(cleanup_error).__name__[:80])
        raise


def report_args(state, key, *, comment='Synthetic reference match only'):
    report = next(row for row in state['formal_reports'] if row['participant_key'] == key)
    return {'worker_id': report['worker_id'], 'result_revision': report['result_revision'],
            'decision': 'accept', 'feedback': comment, 'audit': copy.deepcopy(report['audit'])}


async def test_final_actual_pm_input_keeps_all_six_source_rows_and_does_not_finish_implicitly(tmp_path):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        entries = {row['id']: row for row in catalogue()['entries']}
        previous = 'りんご'
        for index, row in enumerate(state['accepted'], 1):
            source = entries[PATH[index - 1]]
            assert row['step'] == index and row['reference']['entry_id'] == source['id']
            assert row['value'] == source['value'] and row['meaning'] == source['meaning']
            assert row['predecessor']['value'] == previous and row['expected_head'] == previous[-1]
            previous = source['value']
        assert len(state['accepted']) == 6
        assert [row['reference']['entry_id'] for row in state['accepted'][:3]] == list(PATH[:3])
        assert len(client.calls) <= 24 and run['tool_calls'] <= 60
        assert not pm.worker_report_reviews and pm.finished_revision is None
        assert not any(row['source'] == 'finish_work' for row in pm.results)
        for key, expected in [('A', [1, 4]), ('B', [2, 5]), ('C', [3, 6])]:
            assert [row['step'] for row in report_args(state, key)['audit']['rows']] == expected
        response = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Not yet audited'})
        assert response['ok'] is False and response['code'] == 'worker_review_pending'
        assert pm.finished_revision is None
    finally:
        await engine.close()


@pytest.mark.parametrize('damage', ['missing', 'old_predecessor', 'missing_first_step', 'other_worker', 'old_revision'])
async def test_report_audit_binds_all_own_steps_and_current_formal_revision_before_mutation(tmp_path, damage):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        args = report_args(state, 'A')
        if damage == 'missing':
            args.pop('audit')
        elif damage == 'old_predecessor':
            args['audit']['rows'][1]['predecessor']['value'] = 'りんご'
        elif damage == 'missing_first_step':
            args['audit']['rows'].pop(0)
        elif damage == 'other_worker':
            args['audit'] = report_args(state, 'B')['audit']
        else:
            args['result_revision'] -= 1
        before = await effects(engine, run, pm)
        try:
            response = await engine.execute_tool(run, pm, 'review_worker_report', args)
        except ValueError:
            assert damage == 'old_revision'
        else:
            assert response['ok'] is False
        assert await effects(engine, run, pm) == before
        assert not run['_ordered_work'].get('reference_approvals')
    finally:
        await engine.close()


async def test_false_comment_is_preserved_as_unverified_and_never_used_as_canonical_fact(tmp_path):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        false = 'The predecessor of A final is りんご and its last character is お.'
        response = await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, 'A', comment=false))
        assert response['ok']
        payload = json.loads([event for event in engine.events if event['kind'] == 'reference_audit'][-1]['text'])
        assert payload['source'] == 'application' and payload['scope'] == 'worker_report'
        assert payload['comment'] == {'text': false, 'verified': False}
        assert payload['facts'][1]['predecessor']['value'] == 'めだか'
        assert payload['facts'][1]['expected_head'] == 'か'
        assert payload['semantic_scope'] == 'reference_match_only'
        assert pm.worker_report_reviews[workers['A'].id] == {
            'result_revision': workers['A'].result_revision, 'decision': 'accept'}
        # This tests separation, not a semantic QA pass: the false statement
        # remains false and a real trial with it uncorrected must still fail.
        projection, _ = coordination_projection(run, engine.agents, 123.0)
        validate_coordination(projection)
        assert projection['schema_version'] == 1
        assert next(row for row in projection['reports'] if row['agent_id'] == workers['A'].id)['accepted_current']
        assert not projection['pm_completion']['completed'] and pm.finished_revision is None
    finally:
        await engine.close()


@pytest.mark.parametrize('field', ['delivery', 'consumption', 'revision', 'formal', 'proof'])
async def test_current_approval_predicate_rechecks_report_metadata_even_if_cleanup_is_missed(tmp_path, field):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        child = workers['A']
        assert (await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, 'A')))['ok']
        box = run['_ordered_work']
        assert current_reference_report_approval(box, child, pm)
        if field == 'delivery':
            pm.worker_report_deliveries.pop(child.id)
        elif field == 'consumption':
            pm.worker_report_consumed.pop(child.id)
        elif field == 'revision':
            child.result_revision += 1
        elif field == 'formal':
            child.finished_revision = None
        else:
            box['reference_approvals'].pop(child.id)
        assert not current_reference_report_approval(box, child, pm)
        roster = await engine.execute_tool(run, pm, 'list_team', {})
        assert not next(row for row in roster['agents'] if row['id'] == child.id)['report']['review']['current']
        projection, _ = coordination_projection(run, engine.agents, 123.0)
        assert not next(row for row in projection['reports'] if row['agent_id'] == child.id)['accepted_current']
        try:
            result = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Must not finish'})
        except ValueError:
            pass  # Existing delegation errors remain errors, never completion.
        else:
            assert result.get('ok') is False
    finally:
        await engine.close()


async def test_suffix_rollback_invalidates_approvals_but_retains_unaffected_formal_prefix(tmp_path):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        for key in 'ABC':
            assert (await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, key)))['ok']
        box = run['_ordered_work']
        a = workers['A']
        original_binding = copy.deepcopy(box['reference_reports'][a.id])
        rollback = await engine.execute_tool(run, pm, 'rollback_work_step', {'step': 5, 'reason': 'Synthetic suffix correction'})
        assert rollback['ok'] and not box['reference_approvals']
        assert box['reference_reports'] == {a.id: original_binding}
        assert a.finished_revision == a.result_revision and pm.worker_report_consumed[a.id] == a.result_revision
        assert workers['B'].finished_revision is None and workers['C'].finished_revision is None
        old = report_args(state, 'A')
        assert (await engine.execute_tool(run, pm, 'review_worker_report', old))['code'] == 'audit_stale'
        current = copy.deepcopy(old)
        current['audit']['expected_generation'] = rollback['ordered_work']['generation']
        assert [row['submission_generation'] for row in current['audit']['rows']] == [1, 1]
        assert (await engine.execute_tool(run, pm, 'review_worker_report', current))['ok']
        assert current_reference_report_approval(box, a, pm)
        assert (await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Still incomplete'}))['code'] == 'ordered_work_pending'
    finally:
        await engine.close()


async def test_enqueue_drops_formal_binding_and_approval_for_new_revision(tmp_path):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        child = workers['A']
        assert (await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, 'A')))['ok']
        engine.enqueue(child, 'New explicit input requires current report', human=True)
        box = run['_ordered_work']
        assert child.id not in box['reference_reports'] and child.id not in box['reference_approvals']
        assert child.id not in pm.worker_report_reviews and child.finished_revision is None
    finally:
        await engine.close()


async def test_masked_audit_facts_rejected_before_acceptance_or_mail(tmp_path, monkeypatch):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        original = engine._redact_tree

        def mask_required_fact(value):
            masked = original(value)
            if isinstance(masked, dict) and 'rows' in masked:
                masked = copy.deepcopy(masked)
                masked['rows'][0]['meaning'] = '[redacted]'
            return masked

        monkeypatch.setattr(engine, '_redact_tree', mask_required_fact)
        before = await effects(engine, run, pm)
        response = await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, 'A'))
        assert response['ok'] is False and response['code'] == 'audit_source_unavailable'
        assert await effects(engine, run, pm) == before
    finally:
        await engine.close()


async def test_report_commit_revalidates_revision_after_preparation(tmp_path, monkeypatch):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        original = engine.redact
        feedback = 'Trigger a revision change during preparation'
        changed = False

        def change_revision(text):
            nonlocal changed
            if text == feedback and not changed:
                changed = True
                engine.enqueue(workers['A'], 'New input during preparation', human=True)
            return original(text)

        monkeypatch.setattr(engine, 'redact', change_revision)
        response = await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, 'A', comment=feedback))
        assert response['ok'] is False and changed
        assert workers['A'].id not in pm.worker_report_reviews
        assert not run['_ordered_work'].get('reference_approvals')
    finally:
        await engine.close()


async def test_independent_review_batch_rechecks_each_audit_and_blocks_finish_after_partial_failure(tmp_path):
    def batch(state):
        wrong = report_args(state, 'B')
        wrong['audit']['rows'][0]['meaning'] = 'Unsupported comment copied as fact'
        return reply(calls=[('review_worker_report', report_args(state, 'A')),
            ('review_worker_report', wrong), ('review_worker_report', report_args(state, 'C')),
            ('finish_work', {'summary': 'Must fail while B lacks source-bound approval'}),
            ('wait_for_message', {})])

    engine, run, pm, workers, client, state = await prepared(tmp_path, on_complete=batch)
    try:
        results = tool_results(pm, 'review_worker_report')
        assert [row['ok'] for row in results] == [True, False, True]
        assert results[1]['code'] == 'audit_mismatch'
        assert set(pm.worker_report_reviews) == {workers['A'].id, workers['C'].id}
        assert tool_results(pm, 'finish_work')[-1]['code'] == 'worker_review_pending'
        assert pm.finished_revision is None and len(client.calls) <= 24
    finally:
        await engine.close()


async def test_final_native_binding_survives_result_history_warning(tmp_path):
    engine, run, pm, workers, client, state = await prepared(tmp_path, fail_result_history=True)
    try:
        box = run['_ordered_work']
        for key, child in workers.items():
            assert not child.results and child.finished_revision == child.result_revision
            assert box['reference_reports'][child.id]['result_revision'] == child.result_revision
            assert (await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, key)))['ok']
        assert not pm.finished_revision  # Persistence failure did not auto-complete PM.
        assert len([event for event in engine.events if event['kind'] == 'mail'
                    and event.get('message_type') == 'worker_report']) == 3
    finally:
        await engine.close()


async def test_all_report_reviews_persist_one_complete_snapshot_without_finishing_pm(tmp_path):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        for key in 'ABC':
            assert (await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, key)))['ok']
        records = [event for event in engine.events if event['kind'] == 'reference_evidence']
        assert len(records) == 1 and records[0]['agent_id'] == pm.id
        snapshot = json.loads(records[0]['text'])
        assert snapshot['source'] == 'application' and snapshot['audit']['rows'] == state['accepted']
        assert len(snapshot['audit']['rows']) == 6
        assert {row['worker_id'] for row in snapshot['reports']} == {child.id for child in workers.values()}
        assert all(len(row['proof_sha256']) == 64 for row in snapshot['reports'])
        assert pm.finished_revision is None and not any(row['source'] == 'finish_work' for row in pm.results)
        assert engine._delegation_issue(run, pm, finishing=True) is None
        # Display evidence cannot be promoted into authority by finish_work.
        run['_ordered_work'].pop('reference_report_evidence')
        assert (await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Missing current snapshot'}))['code'] == 'worker_review_pending'
        assert pm.finished_revision is None
    finally:
        await engine.close()


async def test_newly_masked_source_after_accept_invalidates_current_display_and_finish(tmp_path, monkeypatch):
    engine, run, pm, workers, client, state = await prepared(tmp_path)
    try:
        for key in 'ABC':
            assert (await engine.execute_tool(run, pm, 'review_worker_report', report_args(state, key)))['ok']
        assert engine._delegation_issue(run, pm, finishing=True) is None
        original = engine._redact_tree

        def later_mask(value):
            masked = original(value)
            if isinstance(masked, dict) and 'rows' in masked:
                masked = copy.deepcopy(masked)
                masked['rows'][0]['meaning'] = '[redacted]'
            return masked

        monkeypatch.setattr(engine, '_redact_tree', later_mask)
        roster = await engine.execute_tool(run, pm, 'list_team', {})
        assert all(not row['report']['review']['current'] for row in roster['agents'] if row['parent_id'] == pm.id)
        context = ordered_request_state({'system': engine._ordered_context(run, pm)})
        assert all(not row['accepted_current'] for row in context['formal_reports'])
        projection, _ = coordination_projection(run, engine.agents, 123.0, redact=engine._redact_tree)
        assert all(not row['accepted_current'] for row in projection['reports'])
        assert not projection['pm_completion']['completed']
        assert (await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Source is now unavailable'}))['code'] == 'worker_review_pending'
        assert pm.finished_revision is None
    finally:
        await engine.close()


async def test_normal_pm_synthetic_requests_keep_dev44_schema_and_one_compaction(tmp_path):
    class CapturingSyntheticClient(SyntheticClient):
        def __init__(self):
            super().__init__()
            self.requests = []

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            self.requests.append(copy.deepcopy({'tools': tools, 'system': system, 'messages': messages}))
            return await super().complete(profile, messages, tools, system, limits, conversation_id=conversation_id)

    client = CapturingSyntheticClient()
    engine, _ = configured(tmp_path, client)
    # Identical to the existing compaction fixture; no relaxed threshold,
    # timeout, call budget or one-summary expectation.
    engine.settings.value['limits'].update(max_context_chars=50000, context_recent_groups=2,
                                          context_summary_chars=1500, max_output_tokens=2048)
    try:
        run, pm = await start_regular(engine, task=COMPACTION_CASE['task'], max_workers=0)
        await settled(engine)
        assert run['status'] == pm.status == 'done'
        assert pm.compactions == client.summary_calls == 1
        assert any(row['text'] == COMPACTION_CASE['result'] for row in pm.logs)
        ordinary = [request for request in client.requests if request['tools']]
        assert ordinary
        for request in ordinary:
            assert_legacy_review_tools(request['tools'], ['review_worker_report'])
        assert schema_digest(TEAM_TOOLS) == LEGACY_TEAM_TOOLS_SHA256
        # The execution validator also keeps the legacy argument contract.
        with pytest.raises(ValueError, match='ツール引数'):
            await engine.execute_tool(run, pm, 'review_worker_report', {
                'worker_id': 'not-a-worker', 'result_revision': 1, 'decision': 'accept',
                'feedback': 'Cannot add reference-only arguments', 'audit': {}})
    finally:
        await engine.close()


async def test_reference_pm_native_requests_and_validation_are_scoped_without_worker_or_cross_run_leaks(tmp_path):
    def batch(state):
        return reply(calls=[*[('review_worker_report', report_args(state, key)) for key in 'ABC'],
                             ('wait_for_message', {})])

    engine, run, pm, workers, client, state = await prepared(tmp_path, on_complete=batch)
    try:
        assert all(row['ok'] for row in tool_results(pm, 'review_work_step'))
        assert len(tool_results(pm, 'review_work_step')) == 6
        assert [row['ok'] for row in tool_results(pm, 'review_worker_report')] == [True, True, True]
        pm_requests = [request for request in client.calls if request['conversation_id'].endswith('/' + pm.id)]
        worker_requests = [request for request in client.calls if not request['conversation_id'].endswith('/' + pm.id)]
        assert pm_requests and worker_requests
        for request in pm_requests:
            tools = {row['name']: row for row in request['tools']}
            for name in LEGACY_REVIEW_SHA256:
                assert 'audit' in tools[name]['parameters']['properties']
                assert 'Reference-mode accept requires audit' in tools[name]['description']
        for request in worker_requests:
            assert not set(LEGACY_REVIEW_SHA256) & {row['name'] for row in request['tools']}
            assert all('audit' not in row['parameters']['properties'] for row in request['tools'])

        changed = {row['name']: row for row in engine._model_tools(run, pm)}
        changed['review_work_step']['parameters']['properties']['audit']['properties']['rows']['maxItems'] = 999
        fresh = {row['name']: row for row in engine._model_tools(run, pm)}
        assert fresh['review_work_step']['parameters']['properties']['audit']['properties']['rows']['maxItems'] == 64
        assert schema_digest(TEAM_TOOLS) == LEGACY_TEAM_TOOLS_SHA256

        started = await engine.start_run({'task': 'Synthetic unrelated PM request', 'pm_profile': 'local',
            'worker_profiles': ['local'], 'max_workers': 0, 'delegation_level': 0})
        other_run = engine.runs[started['run']['id']]
        other_pm = engine.agents[other_run['pm_agent_ids'][0]]
        other_pm._test_engine = engine

        async def wait(request):
            assert_legacy_review_tools(request['tools'], ['review_worker_report'])
            return reply(calls=[('wait_for_message', {})])

        client.handlers[other_pm.id] = wait
        await drive(other_pm)
        assert not other_pm.last_error
        assert_legacy_review_tools(client.calls[-1]['tools'], ['review_worker_report'])
        assert schema_digest(TEAM_TOOLS) == LEGACY_TEAM_TOOLS_SHA256
    finally:
        await engine.close()


async def test_legacy_text_chain_pm_actual_request_keeps_old_review_schemas(tmp_path):
    from test_ordered_engine import team, begin, bind_driver

    engine, run, pm, workers, client, _ = await team(tmp_path)
    captured = []

    async def submit_word(request):
        return reply(calls=[('submit_work_step', {'value': 'ごま', 'summary': 'Synthetic free-word meaning'})])

    async def review(request):
        captured.append(copy.deepcopy(request))
        assert_legacy_review_tools(request['tools'], ['review_work_step', 'review_worker_report'])
        return reply(calls=[('review_work_step', {'decision': 'accept', 'feedback': 'Legacy explicit judgment'})])

    try:
        bind_driver(engine)
        client.handlers[workers['A'].id] = submit_word
        client.handlers[pm.id] = review
        await begin(engine, run, pm)
        await drive(workers['A'])
        await drive(pm)
        assert captured and not pm.last_error
        assert tool_results(pm, 'review_work_step')[-1]['ok']
        assert run['_ordered_work']['flow'].view()['accepted'][0]['value'] == 'ごま'
        assert schema_digest(TEAM_TOOLS) == LEGACY_TEAM_TOOLS_SHA256
    finally:
        await engine.close()


async def test_reference_step_feedback_contract_is_visible_before_native_review(tmp_path):
    engine, run, pm, workers, client, _ = await grounded_team(tmp_path)
    observed = []
    try:
        await install_scripts(engine, run, pm, workers, client, finish=False)

        async def review(request):
            state = ordered_request_state(request)
            tool = next(row for row in request['tools'] if row['name'] == 'review_work_step')
            feedback = tool['parameters']['properties']['feedback']
            assert feedback == {'type': 'string', 'minLength': 1,
                                'maxLength': 512, 'pattern': r'\S'}
            assert 'Both accept and revise require nonblank feedback' in tool['description']
            assert schema_digest(TEAM_TOOLS) == LEGACY_TEAM_TOOLS_SHA256
            args = {'decision': 'accept', 'feedback': 'Value and meaning match the supplied entry.',
                    'audit': copy.deepcopy(state['pending_audit'])}
            before = await effects(engine, run, pm)
            for decision in ('accept', 'revise'):
                for empty in ('', ' \n\t'):
                    rejected = await engine.execute_tool(run, pm, 'review_work_step',
                        {**args, 'decision': decision, 'feedback': empty})
                    assert rejected['ok'] is False and rejected['code'] == 'invalid_text'
                    assert await effects(engine, run, pm) == before
            damaged = copy.deepcopy(args)
            damaged['audit']['rows'][0]['meaning'] = 'A mismatched reference meaning'
            rejected = await engine.execute_tool(run, pm, 'review_work_step', damaged)
            assert rejected['ok'] is False and rejected['code'] == 'audit_mismatch'
            assert await effects(engine, run, pm) == before
            observed.append(copy.deepcopy(tool))
            return reply(calls=[('review_work_step', args)])

        client.handlers[pm.id] = review
        await begin_grounded(engine, run, pm)
        await advance_grounded(engine, run, pm, workers, 1)
        assert len(observed) == 1
        assert [row['ok'] for row in tool_results(pm, 'review_work_step')] == [True]
        assert len(run['_ordered_work']['flow'].view()['accepted']) == 1
        assert len(client.calls) == 2  # One worker request and one PM request.
    finally:
        await engine.close()
