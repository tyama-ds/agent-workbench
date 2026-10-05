"""Contract tests for the test-only browser server's deterministic model."""
import asyncio
from pathlib import Path
import shutil
import subprocess

import pytest

from workbench.config import Settings
from workbench.engine import Engine
from tools.browser_fixture import SyntheticClient


def test_browser_run_wait_awaits_completed_reads_and_returns_matching_snapshot():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the browser-helper contract')
    script = r"""
const assert=require('node:assert/strict');
const {waitForRunState}=require('./tools/browser-tests/redaction_acceptance.cjs');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const snapshot=(status,agents=[])=>({runs:status?[{id:'run',status}]:[],agents});
const worker=(results=[],output_receipts=[],run_id='run')=>({id:'worker',run_id,parent_id:'pm',results,output_receipts});
(async()=>{
  // An async false/empty result must cause another read, rather than resolving
  // because the returned Promise is truthy. No extra read follows readiness.
  const ready=snapshot('done'),states=[snapshot(),snapshot('running'),ready];let calls=0;
  const returned=await waitForRunState(async()=>{await sleep(2);return states[calls++];},'run','done',{pollMs:1});
  assert.strictEqual(returned,ready);assert.equal(calls,3);

  // A waiting PM does not mean its worker's report and receipt are ready.
  const waiting=[snapshot('waiting',[worker()]),
    snapshot('waiting',[worker([{id:1}]),worker([{id:1}],[{id:2}],'other-run')]),
    snapshot('waiting',[worker([{id:1}],[{id:2}])])];calls=0;
  const complete=await waitForRunState(async()=>{await sleep(2);return waiting[calls++];},'run','waiting',{pollMs:1});
  assert.strictEqual(complete,waiting[2]);assert.equal(calls,3);

  // Both an unchanged incomplete state and a hung read have a hard deadline.
  await assert.rejects(waitForRunState(async()=>snapshot('waiting',[worker()]),'run','waiting',
    {timeoutMs:15,pollMs:1}),/Timed out waiting for synthetic run/);
  await assert.rejects(waitForRunState(()=>new Promise(()=>{}),'run','done',
    {timeoutMs:15,pollMs:1}),/Timed out waiting for synthetic run/);
  console.log('awaited readiness, exact snapshot, worker receipt and timeout checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, '-'], input=script, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'worker receipt and timeout checks passed' in result.stdout


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


async def test_browser_fixture_has_actual_saved_receipt_and_terminal_response(tmp_path):
    settings = Settings(tmp_path / 'state')
    workspace = tmp_path / 'files'
    workspace.mkdir()
    settings.value['providers'][0]['model'] = 'synthetic-no-network'
    settings.value['paths']['write_roots'] = [str(workspace)]
    engine = Engine(settings, client=SyntheticClient())
    try:
        await engine.start_run({'task': '[SYNTHETIC] Save result.', 'pm_profile': 'local',
                                'worker_profiles': ['local'], 'max_workers': 0})
        for _ in range(100):
            await asyncio.sleep(.01)
            if not engine.active():
                break
        agent = engine.snapshot()['agents'][0]
        assert len(agent['results']) == len(agent['output_receipts']) == 1
        assert agent['results'][0]['source'] == 'assistant_response'
        assert agent['results'][0]['text'] == '[SYNTHETIC] Terminal answer 日本語.'
        assert 'PRIVATE' not in str(agent['results'])
        assert agent['output_receipts'][0]['path'] == str(workspace / 'browser-result.txt')
        assert (workspace / 'browser-result.txt').read_text(encoding='utf-8') == '[SYNTHETIC] Saved text 日本語.'
    finally:
        await engine.close()
