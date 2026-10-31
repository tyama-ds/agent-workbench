"""Run-only adaptive formation must preserve manual admission and hard limits."""
import pytest

from test_engine import ScriptClient, configured


@pytest.fixture
async def idle_engine(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        yield engine
    finally:
        await engine.close()


def request(**changes):
    return {'task': 'Read sources and produce a verified result', 'pm_profile': 'local',
            'worker_profiles': ['local'], 'max_workers': 2, 'adaptive_team': True,
            **changes}


async def test_adaptive_preflight_is_readonly_and_accepts_one_worker_plus_reviewer(idle_engine):
    engine = idle_engine
    preview = engine.preflight(request())
    assert preview['can_start'] is True
    assert preview['adaptive_team'] is True
    assert preview['formation_rules'] == {
        'workers': {'low': 1, 'medium': 2, 'high': 3}, 'reviewer_slots': 1,
        'min_cap': 2, 'manual_counts_used': False}
    assert not engine.runs and not engine.agents and not engine.client.calls


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
async def test_adaptive_flag_requires_real_boolean(idle_engine, value):
    assert idle_engine.preflight(request(adaptive_team=value))['can_start'] is False
    assert not idle_engine.runs and not idle_engine.agents


@pytest.mark.parametrize('count', [0, 1])
async def test_adaptive_never_drops_reviewer_to_fit_cap(idle_engine, count):
    assert idle_engine.preflight(request(max_workers=count))['can_start'] is False
    assert not idle_engine.runs and not idle_engine.agents


async def test_adaptive_multiple_pms_is_explicitly_unsupported(idle_engine):
    assert idle_engine.preflight(request(pm_profiles=['local', 'local']))['can_start'] is False
    assert not idle_engine.runs


async def test_manual_policy_count_is_unused_only_in_adaptive_mode(idle_engine):
    adaptive = request(delegation_level=2, workers_per_pm=16)
    assert idle_engine.preflight(adaptive)['can_start'] is True
    assert idle_engine.preflight({**adaptive, 'adaptive_team': False})['can_start'] is False


async def test_manual_payload_without_optin_remains_compatible(idle_engine):
    payload = request(adaptive_team=False, max_workers=0, delegation_level=0)
    assert idle_engine.preflight(payload)['can_start'] is True
    payload.pop('adaptive_team')
    preview = idle_engine.preflight(payload)
    assert preview['can_start'] is True
    assert 'adaptive_team' not in preview and 'formation_rules' not in preview


async def test_adaptive_preflight_does_not_raise_limits_or_change_settings(idle_engine):
    import copy
    before = copy.deepcopy(idle_engine.settings.value)
    assert idle_engine.preflight(request(max_workers=3))['can_start'] is True
    assert idle_engine.settings.value == before
    assert not idle_engine.runs and not idle_engine.agents and not idle_engine.client.calls


async def test_http_adaptive_is_run_only_and_starts_with_a_plan_gate(tmp_path):
    import copy
    from test_session_transitions import session
    async with session(tmp_path) as case:
        case.engine.kick = lambda agent: None
        before = copy.deepcopy(case.engine.settings.value)
        preview = await case.api('post', '/api/run-preflight', request())
        assert preview['can_start'] and not case.engine.runs and not case.provider.history
        response = await case.api('post', '/api/runs', request())
        run = response['run']
        assert run['adaptive_team'] is True
        assert run['formation']['phase'] == 'unplanned'
        assert run['formation']['candidate'] is None
        assert len(run['agent_ids']) == len(run['pm_agent_ids']) == 1
        assert run['model_calls'] == run['tool_calls'] == run['auto_collaborations'] == 0
        assert case.engine.settings.value == before
        assert not case.provider.history
