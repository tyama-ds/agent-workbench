"""Contracts for the read-only retention browser acceptance; no browser launch."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/browser-tests/retention_acceptance.cjs'


def test_retention_history_snapshot_keeps_ids_records_counters_and_is_detached():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the browser-helper contract')
    script = r"""
const assert=require('node:assert/strict');
const {retainedStateSnapshot,retentionAcceptance}=require('./tools/browser-tests/retention_acceptance.cjs');
assert.equal(typeof retentionAcceptance,'function');
const state={runs:[{id:'run',status:'done',model_calls:2,tool_calls:1,agent_ids:['agent']}],
  agents:[{id:'agent',run_id:'run',turns:2,results:[{id:8,text:'report 日本語',truncated:false}],
    output_receipts:[{id:7,path:'synthetic.txt',bytes:5,sha256:'synthetic-sha'}],logs:[{id:6,text:'log'}]}],
  events:[{id:9,run_id:'run',text:'done'}],resources:{active:0,gpu_readings:[{used_mb:1}]}};
const saved=retainedStateSnapshot(state);
assert.deepEqual(Object.keys(saved).sort(),['agents','events','runs']);
assert.deepEqual(saved,{runs:state.runs,agents:state.agents,events:state.events});
state.resources.gpu_readings[0].used_mb=2;
assert.deepEqual(retainedStateSnapshot(state),saved,'Live resource sampling is unrelated to history retention');
for(const change of [value=>value.runs[0].id='new-run',value=>value.runs[0].model_calls++,
  value=>value.runs[0].tool_calls++,value=>value.agents[0].id='new-agent',
  value=>value.agents[0].results[0].text='changed',value=>value.agents[0].output_receipts[0].sha256='changed',
  value=>value.agents[0].logs.push({id:10}),value=>value.events.push({id:11})]){
  const changed=structuredClone(state);change(changed);
  assert.notDeepEqual(retainedStateSnapshot(changed),saved,'Detect actual retained-history or inference changes');
}
state.agents[0].results[0].text='mutated after capture';
assert.equal(saved.agents[0].results[0].text,'report 日本語','Baseline is detached from mutable input');
assert.throws(()=>retainedStateSnapshot({runs:[],agents:[]}),/full server history snapshot/);
console.log('retention snapshot contract passed');
"""
    result = subprocess.run([node, '-'], input=script, cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'retention snapshot contract passed' in result.stdout


def test_retention_acceptance_is_after_real_exports_before_later_mutations():
    smoke = (ROOT / 'tools/browser_smoke.cjs').read_text(encoding='utf-8')
    assert smoke.count('await retentionAcceptance(') == 1
    insertion = smoke.index('await retentionAcceptance(')
    assert smoke.index("await page.evaluate(()=>delete navigator.clipboard.writeText)") < insertion
    assert smoke.index('const receiptExport=') < insertion
    assert insertion < smoke.index('// A fresh text-only PM can start without file scopes')
    assert "require('./browser-tests/retention_acceptance.cjs')" in smoke
    assert 'resultOption,receiptOption,exported,receiptExport' in smoke[insertion:insertion + 260]


def test_retention_acceptance_preserves_context_instrumentation_and_action_audits():
    source = HELPER.read_text(encoding='utf-8')
    # Reopening a tab cannot silently discard the smoke's error/security audit.
    assert "const target=await context.newPage()" in source
    for event in ('pageerror', 'console', 'request', 'download'):
        assert f"target.on('{event}'" in source
    assert "context.on('request',observe)" in source
    assert "context.off('request',observe)" in source
    assert 'await sibling.reload()' in source
    assert 'await sibling.close();sibling=await newSibling()' in source
    assert 'await context.cookies(origin)' in source
    assert 'await page.close()' not in source
    assert 'newContext(' not in source and '.route(' not in source
    assert 'retentionActions' in source and 'clipboardWrites' in source and 'objectUrls' in source
    assert 'assert.deepEqual(helpRequests,[])' not in source  # Every audit includes a diagnostic label.
    assert 'assert.deepEqual(helpRequests,[],label+' in source
    assert "['desktop',1366,768],['tablet',820,900],['narrow',390,844]" in source
    assert "keyboard.press('Enter')" in source and "keyboard.press('Space')" in source
    assert "workbench-retention-${name}-${state}-sessions.png" in source
    assert "workbench-retention-${name}-expanded-detail-${index+1}.png" in source
    assert "assert.deepEqual(downloads,['workbench-result.txt','workbench-save-receipt.txt'])" in source
