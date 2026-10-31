"""Native completion publication must follow successful PM result recording."""
import pytest

from test_adaptive_workflow import FINAL, WorkflowProvider, joined
from test_engine import configured, reply


@pytest.mark.parametrize('failure_point', ['log', 'record_result'])
async def test_failed_native_pm_result_never_publishes_complete(tmp_path, monkeypatch, failure_point):
    provider = WorkflowProvider()
    engine, _ = configured(tmp_path, provider)
    provider.engine = engine
    reached = []
    original_complete = provider.complete

    async def stop_after_injection(profile, messages, tools, system, limits, *, conversation_id=None):
        actor = engine.agents[conversation_id.split('/')[-1]]
        if reached and actor.id in engine.runs[actor.run_id]['pm_agent_ids']:
            return reply('Synthetic result recording failed; no completion is claimed.')
        return await original_complete(profile, messages, tools, system, limits, conversation_id=conversation_id)

    original_operation = getattr(engine, failure_point)

    def fail_pm_result(actor, source, value, *args, **kwargs):
        run = engine.runs[actor.run_id]
        expected_source = 'result' if failure_point == 'log' else 'finish_work'
        if actor.id in run['pm_agent_ids'] and source == expected_source:
            assert value == FINAL
            assert run['formation']['candidate']['decision'] == 'accept'
            assert actor._review_control_candidate == run['formation']['candidate']['id']
            reached.append({'phase_at_failure': run['formation']['phase'], 'source': source})
            raise OSError('Synthetic PM completion-record failure')
        return original_operation(actor, source, value, *args, **kwargs)

    monkeypatch.setattr(provider, 'complete', stop_after_injection)
    monkeypatch.setattr(engine, failure_point, fail_pm_result)
    try:
        response = await engine.start_run({'task': 'Save result.txt containing the fixture value 42, then verify it.',
            'pm_profile': 'local', 'worker_profiles': ['local'], 'max_workers': 2, 'adaptive_team': True})
        run = engine.runs[response['run']['id']]
        await joined(engine)
        pm = engine.agents[run['pm_agent_ids'][0]]
        assert len(reached) == 1, 'The intended native PM finish failure must actually be reached once.'
        assert reached[0]['phase_at_failure'] == 'accepted'
        assert pm.finished_revision is None
        assert run['status'] != 'done'
        assert run['formation']['phase'] == 'accepted'
        live = next(row for row in engine.snapshot()['runs'] if row['id'] == run['id'])
        assert live['formation']['phase'] == 'accepted'
        assert not engine.history.error
        saved, _ = engine.history.read(run['id'])
        assert saved['run']['formation']['phase'] == 'accepted'
        assert not any(result['source'] == 'finish_work' for result in pm.results)
    finally:
        await engine.close()
