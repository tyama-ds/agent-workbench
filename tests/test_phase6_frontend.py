"""Phase 6 UI: per-worker stop, read-only worker badge, and receipt restore."""
import pytest

from test_frontend import APP, HTML, run_javascript
from test_run_action_frontend import ACTION_DOM, ACTION_FIXTURES


PHASE6_FIXTURES = r"""
const confirms=[];let confirmAnswer=true;window.confirm=text=>{confirms.push(text);return confirmAnswer;};
const fixtureApi=api;
api=(path,options={})=>{const pending=fixtureApi(path,options);requests[requests.length-1].options=options;return pending;};
const RESTORABLE={id:7,tool:'write_text',path:'out/report.txt',bytes:10,sha256:'b'.repeat(64),operation:'updated',previous_sha256:'c'.repeat(64),restorable:true,at:2,turn:1};
let workerReceipts=null;
const fixtureDetails=details;
details=(agent,marker='current')=>{const value=fixtureDetails(agent,marker);if(agent.id==='agent-b'&&workerReceipts)value.output_receipts=structuredClone(workerReceipts);return value;};
function worker(){return ui.state.agents.find(agent=>agent.id==='agent-b');}
async function wireWorker(status='working'){
  summaries[1].status=status;await wire();setBriefOpen(false);
  ui.selectedAgent='agent-b';renderState();assert.equal(requests.length,0);
}
function card(id){return $('agentCards').children.find(node=>node.dataset.agentId===id);}
function stopClick(){return $('stopAgent').listeners.click();}
function restoreClick(){return $('restoreReceipt').listeners.click();}
function selectReceipt(key='receipt:7'){ui.outputSelections.set(outputOwner(),key);renderState();}
"""


def check(source):
    result = run_javascript(ACTION_DOM + APP + "\nconst productionApi=api;\n" + ACTION_FIXTURES + PHASE6_FIXTURES + "\n(async()=>{\n" + source + r"""
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
""")
    assert result == {"ok": True}


def test_static_controls_exist_and_use_no_html_sinks():
    for ident in ('stopAgent', 'agentControls', 'restoreReceipt', 'conversationReadOnly'):
        assert f'id="{ident}"' in HTML
    assert 'この担当を停止' in HTML and '元に戻す' in HTML and '読み取り専用' in HTML


@pytest.mark.parametrize("status", ['idle', 'queued', 'working', 'waiting'])
def test_stop_button_is_shown_for_live_running_worker_statuses(status):
    check(f"await wireWorker('{status}');" + r"""
assert.equal($('agentControls').hidden,false);assert.equal($('stopAgent').disabled,false);
""")


@pytest.mark.parametrize("change", [
    "worker().status='stopped';", "worker().status='stopping';", "worker().status='done';",
    "worker().status='error';", "worker().status='waiting_human';",
    "ui.selectedAgent='agent-a';getAgent().status='working';",
    "getRun().status='stopping';", "getRun().status='stopped';",
    "getRun().adaptive_team=true;", "getRun().archived=true;", "getRun().read_only=true;",
    "worker().archived=true;", "worker().kind='independent_reviewer';",
])
def test_stop_button_is_hidden_for_pm_terminal_stopping_adaptive_and_history(change):
    check("await wireWorker('working');" + change + r"""
renderState();assert.equal($('agentControls').hidden,true);assert.equal($('stopAgent').disabled,true);
await stopClick();assert.equal(requests.length,0);assert.equal(confirms.length,0);
""")


def test_stop_confirms_posts_once_refreshes_and_labels_human_stop():
    check(r"""
await wireWorker('working');
confirmAnswer=false;await stopClick();assert.equal(requests.length,0);assert.equal(confirms.length,1);
confirmAnswer=true;const pending=stopClick();
assert.equal(confirms[1],'この担当を停止しますか？保存済みのファイルは残ります。PM に停止が伝わります。');
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/agents/agent-b/stop');
assert.equal(requests[0].options.method,'POST');assert.deepEqual(requests[0].options.body,{});
assert.equal($('stopAgent').disabled,true);await stopClick();renderState();
assert.equal($('stopAgent').disabled,true);assert.equal(requests.length,1);
Object.assign(summaries[1],{status:'stopped',stop_reason:'human_stop',
  message_eligibility:{allowed:false,reason:'agent_stopped',message:'停止した担当は再開できません。続きは PM に依頼してください'}});
resolve(0,{ok:true,stopped:['agent-b']});await flush();await drainStates();await pending;
assert.equal(requests.filter(r=>r.path.endsWith('/stop')).length,1);assert.equal(ui.stoppingAgents.size,0);
assert.match($('globalNotice').textContent,/担当 Worker B の停止を受け付けました/);
assert.equal($('agentControls').hidden,true);
assert.equal(stateLabel(getAgent()),'人が停止');assert.equal($('conversationStatus').textContent,'人が停止');
assert.match(renderedText(card('agent-b')),/人が停止/);
assert.equal($('messageEligibility').hidden,false);
assert.equal($('messageEligibility').textContent,'停止した担当は再開できません。続きは PM に依頼してください');
assert.equal($('sendMessage').disabled,true);assert.equal($('messageInput').disabled,true);
""")


def test_stop_error_is_shown_as_action_error_and_allows_explicit_retry():
    check(r"""
await wireWorker('waiting');const pending=stopClick();
reject(0,new Error('PM は個別に停止できません。チーム全体を停止してください'));await pending;
assert.match($('globalNotice').textContent,/担当 Worker B の停止要求: PM は個別に停止できません/);
assert.ok($('globalNotice').classes.has('error'));assert.equal($('stopAgent').disabled,false);
const retry=stopClick();assert.equal(requests.length,2);reject(1,new Error('again'));await retry;
""")


def test_human_stop_labels_in_history_and_run_stop_reasons():
    check(r"""
await wireWorker('working');
assert.equal(stateLabel({id:'x',run_id:'run-a',status:'stopped',stop_reason:'human_stop'}),'人が停止');
assert.equal(stateLabel({id:'x',run_id:'run-a',archived:true,read_only:true,status:'stopped',stop_reason:'human_stop'}),'保存履歴 · 人が停止');
assert.deepEqual(runtimeStopMetrics({stop_reasons:['human_stop','model_limit']}),[['担当の停止理由','人が停止 / モデル呼び出し回数の上限']]);
""")


def test_read_only_worker_badge_on_card_and_detail_without_becoming_history():
    check(r"""
await wireWorker('working');
assert.equal($('conversationReadOnly').hidden,true);assert.doesNotMatch(renderedText(card('agent-b')),/読み取り専用/);
worker().read_only_worker=true;renderState();
assert.match(renderedText(card('agent-b')),/読み取り専用/);assert.equal($('conversationReadOnly').hidden,false);
assert.equal(archivedAgent(worker()),false);assert.doesNotMatch(stateLabel(worker()),/保存履歴/);
assert.equal(displayStatus(worker()),'working');assert.equal($('messageInput').disabled,false);
assert.equal($('agentControls').hidden,false);
assert.doesNotMatch(renderedText(card('agent-a')),/読み取り専用/);
getRun().archived=true;getRun().read_only=true;Object.assign(worker(),{archived:true,read_only:true});renderState();
assert.equal($('conversationReadOnly').hidden,true);assert.doesNotMatch(renderedText(card('agent-b')),/読み取り専用/);
assert.equal(archivedAgent(worker()),true);
""")


@pytest.mark.parametrize("change,hidden,disabled,title", [
    ("getRun().status='running';", False, True, '実行中は戻せません。待機・完了・停止後に使えます'),
    ("getRun().status='waiting';", False, False, ''),
    ("getRun().status='done';", False, False, ''),
    ("getRun().status='stopped';", False, False, ''),
    ("getRun().status='stopping';", False, True, '実行中は戻せません。待機・完了・停止後に使えます'),
    ("getRun().status='done';worker().output_receipts[0].restorable=false;", True, True, ''),
    ("getRun().status='done';delete worker().output_receipts[0].restorable;", True, True, ''),
    ("getRun().status='done';getRun().archived=true;getRun().read_only=true;", True, True, ''),
    ("getRun().status='done';ui.outputSelections.set(outputOwner(),'result:result-agent-b');", True, True, ''),
])
def test_restore_button_visibility(change, hidden, disabled, title):
    check(r"""
workerReceipts=[RESTORABLE];await wireWorker('waiting');selectReceipt();
""" + change + r"""
renderState();
assert.equal($('restoreReceipt').hidden,""" + str(hidden).lower() + r""");
assert.equal($('restoreReceipt').disabled,""" + str(disabled).lower() + r""");
assert.equal($('restoreReceipt').title??'',""" + repr(title) + r""");
if($('restoreReceipt').hidden||$('restoreReceipt').disabled){await restoreClick();assert.equal(requests.length,0);assert.equal(confirms.length,0);}
""")


def test_restore_confirms_posts_receipt_id_once_and_refreshes_with_human_restore_label():
    check(r"""
workerReceipts=[RESTORABLE];runs[0].status='done';await wireWorker('waiting');selectReceipt();
assert.equal($('restoreReceipt').hidden,false);
confirmAnswer=false;await restoreClick();assert.equal(requests.length,0);
confirmAnswer=true;const pending=restoreClick();
assert.equal(confirms[1],'out/report.txt をこの保存の前の内容に戻しますか？この保存の後に変更されている場合は戻せません。');
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/runs/run-a/restore');
assert.equal(requests[0].options.method,'POST');assert.deepEqual(requests[0].options.body,{receipt_id:7});
assert.equal($('restoreReceipt').disabled,true);await restoreClick();renderState();
assert.equal($('restoreReceipt').disabled,true);assert.equal(requests.length,1);
workerReceipts=[{...RESTORABLE,restorable:false},{id:8,tool:'human_restore',path:'out/report.txt',bytes:4,sha256:'d'.repeat(64),operation:'updated',previous_sha256:'b'.repeat(64),restorable:true,at:3,turn:1}];
resolve(0,{ok:true,path:'out/report.txt',sha256:'d'.repeat(64)});await flush();await drainStates();await pending;
assert.equal(requests.filter(r=>r.path.endsWith('/restore')).length,1);assert.equal(ui.restoringReceipt,null);
assert.equal(selectedOutput().key,'receipt:7');assert.equal($('restoreReceipt').hidden,true);
assert.equal($('resultActionStatus').textContent,'out/report.txt を保存前の内容に戻しました。');
assert.match(renderedText($('resultSelection')),/人が元に戻した · out\/report\.txt · 元に戻せる/);
selectReceipt('receipt:8');assert.match($('resultText').textContent,/ツール: 人が元に戻した/);
assert.doesNotMatch($('resultText').textContent,/human_restore/);assert.equal($('restoreReceipt').hidden,false);
""")


def test_restore_error_is_shown_and_button_reenabled():
    check(r"""
workerReceipts=[RESTORABLE];runs[0].status='done';await wireWorker('waiting');selectReceipt();
const pending=restoreClick();reject(0,new Error('この保存の後にファイルが変更されているため戻せません'));await pending;
assert.equal($('resultActionStatus').textContent,'元に戻せませんでした: この保存の後にファイルが変更されているため戻せません');
assert.ok($('resultActionStatus').classes.has('error'));assert.equal($('restoreReceipt').disabled,false);
""")
