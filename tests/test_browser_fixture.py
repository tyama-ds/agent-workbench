"""Contract tests for the test-only browser server's deterministic model."""
import asyncio

from workbench.config import Settings
from workbench.engine import Engine
from tools.browser_fixture import SyntheticClient


async def test_browser_fixture_exercises_real_engine(tmp_path):
    settings = Settings(tmp_path / 'state')
    settings.value['providers'][0]['model'] = 'synthetic-no-network'
    engine = Engine(settings, client=SyntheticClient())
    try:
        response = await engine.start_run({'task': '[SYNTHETIC] test', 'pm_profile': 'local',
                                           'worker_profiles': ['local'], 'max_workers': 1})
        run_id = response['run']['id']
        for _ in range(100):
            await asyncio.sleep(.01)
            if len(engine.agents) == 2 and any(event['kind'] == 'mail' for event in engine.events):
                break
        state = engine.snapshot()
        assert len(state['agents']) == 2
        lead = next(agent for agent in state['agents'] if agent['parent_id'] is None)
        assert lead['question'] == '[SYNTHETIC] Continue this test run?'
        assert state['runs'][0]['status'] == 'waiting'
        assert any('Worker review complete.' in event['text'] for event in state['events'])
        assert all('task' not in agent for agent in state['agents'])
        assert lead['assignment'] == '[SYNTHETIC] test'
        assert next(a for a in state['agents'] if a['parent_id'])['assignment'] == '[SYNTHETIC] Review fixture only.'
        assert lead['status_reason'] == state['runs'][0]['status_reason'] == 'human_input'
        assert lead['message_eligibility']['allowed']
        await engine.human_message(lead['id'], '[SYNTHETIC] Continue.')
        await asyncio.sleep(.01)
        assert engine.snapshot()['runs'][0]['status'] == 'running'
        await engine.stop_run(run_id)
        assert engine.snapshot()['runs'][0]['status'] == 'stopped'
        assert not engine.active()
    finally:
        await engine.close()
