"""Preparing a displayed request never resumes an Engine or copies its authority."""
import copy

from test_engine import configured, ScriptClient, start


async def test_public_task_preflight_has_no_run_queue_budget_settings_or_model_effect(tmp_path):
    client = ScriptClient([])
    engine, work = configured(tmp_path, client)
    engine.kick = lambda _: None
    try:
        engine.settings.secrets['local'] = 'synthetic-reuse-key'
        run, agent = await start(engine, task='  Original\nsynthetic-reuse-key  ', max_workers=2)
        run['status'] = agent.status = 'stopped'
        run['model_calls'], run['tool_calls'], run['auto_collaborations'] = 5, 7, 3
        agent.conversation = [{'role': 'user', 'content': 'Do not copy private conversation'}]
        before = engine.snapshot()
        queue = copy.deepcopy(list(agent.pending))
        config = copy.deepcopy(engine.settings.value)
        secrets = copy.deepcopy(engine.settings.secrets)
        files = {p.name: p.read_bytes() for p in engine.settings.directory.iterdir() if p.is_file()}
        displayed = before['runs'][0]['task']
        assert displayed == '  Original\n[redacted]  '
        payload = {'task': displayed, 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0}
        preview = engine.preflight(payload)
        assert preview['can_start'] and not preview['inference_tested'] and not preview['tools_tested']
        after = engine.snapshot()
        for field in ('runs', 'agents', 'events'):
            assert after[field] == before[field]
        assert list(agent.pending) == queue and client.calls == []
        assert engine.settings.value == config and engine.settings.secrets == secrets
        assert {p.name: p.read_bytes() for p in engine.settings.directory.iterdir() if p.is_file()} == files
        assert list(work.iterdir()) == []
        assert payload == {'task': displayed, 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0}
    finally:
        await engine.close()
