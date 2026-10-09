"""Deferred mutation callbacks, with the real app and synthetic DOM/transport only."""
import pytest

from test_frontend import APP, run_javascript
from test_compact_frontend import DOM, FIXTURES


ACTION_DOM = DOM.replace(
    "addEventListener(){}",
    "addEventListener(type,callback){(this.listeners??={})[type]=callback;}", 1,
).replace("close(){this.open=false;}", "close(){this.open=false;this.listeners?.close?.();}")

ACTION_FIXTURES = FIXTURES + r"""
// initialize registers production callbacks before bootstrap. This DOM-only
// fixture has no location, so its normal caught initialization failure prevents
// any network bootstrap. Browser acceptance exercises actual initialization.
async function wire(){
  await initialize();seedSelection();
  $('taskInput').value='Submitted task';$('pmProfile').value='local';$('maxWorkers').value='0';
  setBriefOpen(true);clearTimeout(ui.preflightTimer);trackTaskDraft();
}
function submit(){return $('runForm').listeners.submit({preventDefault(){}});}
function stop(){return $('stopRun').listeners.click();}
function editTask(text){$('taskInput').value=text;trackTaskDraft();}
function addCreated(){
  runs.push({id:'created-run',task:'Submitted task',status:'running',created_at:3,agent_ids:['created-agent'],max_workers:0});
  summaries.push({...summaries[0],id:'created-agent',run_id:'created-run',name:'Created PM'});
}
function stateFor(request){
  const selection=selectionOf(request);
  return compactState(selection.run_id??null,selection.agent_id??null);
}
async function drainStates(){
  for(let count=0;count<20;count++){
    const pending=requests.find(request=>!request.done&&request.path.startsWith('/api/state'));
    if(!pending){await flush();if(!ui.polling)return;continue;}
    pending.done=true;pending.resolve(stateFor(pending));await flush();
  }
  throw Error('State did not settle');
}
function resolve(index,value){requests[index].done=true;requests[index].resolve(value);}
function reject(index,error){requests[index].done=true;requests[index].reject(error);}
"""


def check(source):
    result = run_javascript(ACTION_DOM + APP + "\nconst productionApi=api;\n" + ACTION_FIXTURES + "\n(async()=>{\n" + source + r"""
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
""")
    assert result == {"ok": True}


def test_accepted_start_survives_failed_and_missing_state_until_observed_without_repost():
    check(r"""
await wire();const pending=submit();assert.equal(requests[0].path,'/api/runs');
await submit();assert.equal(requests.length,1);assert.equal($('startRun').disabled,true);
resolve(0,{ok:true,run:{id:'created-run'}});await flush();
reject(1,new Error('Synthetic state failure'));await pending;
assert.equal(ui.startOperation.runId,'created-run');assert.equal(ui.startingRun,true);
assert.equal($('taskDialog').open,true);assert.equal(ui.selectedRun,'run-a');
assert.match($('runFormStatus').textContent,/開始は受け付けられました/);
assert.match($('runFormStatus').textContent,/再送信は不要/);assert.equal($('startRun').disabled,true);
const missing=pollState();resolve(2,stateFor(requests[2]));await missing;
assert.equal(ui.startOperation.runId,'created-run');await submit();
assert.equal(requests.filter(r=>r.path==='/api/runs').length,1);
addCreated();const observed=pollState();await drainStates();await observed;
assert.equal(ui.startOperation,null);assert.equal(ui.startingRun,false);
assert.equal(ui.selectedRun,'created-run');assert.equal($('taskDialog').open,false);
assert.equal($('taskInput').value,'Submitted task');
assert.equal(requests.filter(r=>r.path==='/api/runs').length,1);
""")


def test_first_start_reconciles_before_automatic_selection_changes_generation():
    check(r"""
await wire();ui.state={runs:[],agents:[],events:[],resources:{}};changeSelection(null,null);
const pending=submit();addCreated();resolve(0,{run:{id:'created-run'}});await flush();await drainStates();await pending;
assert.equal(ui.selectedRun,'created-run');assert.equal($('taskDialog').open,false);
assert.equal(ui.startOperation,null);assert.equal(ui.startingRun,false);
""")


def test_start_does_not_override_selection_aba_or_newer_global_notice():
    check(r"""
await wire();const pending=submit();setBriefOpen(false);selectRun('run-b');selectRun('run-a');
notice('Newer unrelated notice');addCreated();resolve(0,{run:{id:'created-run'}});await flush();await drainStates();await pending;
assert.equal(ui.selectedRun,'run-a');assert.equal($('taskDialog').open,false);
assert.equal($('globalNotice').textContent,'Newer unrelated notice');assert.equal(ui.startOperation,null);
""")


def test_start_preserves_reopened_dialog_draft_focus_and_accepted_identity():
    check(r"""
await wire();const pending=submit();setBriefOpen(false);setBriefOpen(true);clearTimeout(ui.preflightTimer);
editTask('New unsent draft');$('taskInput').focus();
resolve(0,{run:{id:'created-run'}});await flush();reject(1,new Error('Synthetic state failure'));await pending;
assert.equal($('taskDialog').open,true);assert.equal($('taskInput').value,'New unsent draft');
assert.match($('runFormStatus').textContent,/現在の下書きは送信していません/);
assert.equal(ui.startOperation.runId,'created-run');assert.equal($('startRun').disabled,true);
addCreated();const observed=pollState();await drainStates();await observed;
assert.equal(ui.selectedRun,'run-a');assert.equal($('taskDialog').open,true);
assert.equal($('taskInput').value,'New unsent draft');assert.equal(document.activeElement,$('taskInput'));
assert.match($('runFormStatus').textContent,/現在の下書きは送信していません/);
""")


def test_start_draft_aba_and_settings_dialog_aba_invalidate_old_navigation():
    check(r"""
await wire();const pending=submit();editTask('Intermediate edit');editTask('Submitted task');
showView('settings');showView('work');addCreated();resolve(0,{run:{id:'created-run'}});await flush();await drainStates();await pending;
assert.equal(ui.selectedRun,'run-a');assert.equal($('taskDialog').open,true);
assert.equal($('taskInput').value,'Submitted task');assert.equal(ui.startOperation,null);
""")


@pytest.mark.parametrize("change", [
    "setBriefOpen(false);setBriefOpen(true);clearTimeout(ui.preflightTimer);",
    "editTask('Intermediate edit');editTask('Submitted task');",
    "showView('settings');showView('work');",
])
def test_each_independent_aba_generation_invalidates_old_start(change):
    check(r"""
await wire();const pending=submit();
""" + change + r"""
addCreated();resolve(0,{run:{id:'created-run'}});await flush();await drainStates();await pending;
assert.equal(ui.selectedRun,'run-a');assert.equal($('taskDialog').open,true);
assert.equal($('taskInput').value,'Submitted task');assert.equal(ui.startOperation,null);
""")


@pytest.mark.parametrize("initially_empty", [False, True])
def test_state_may_observe_created_run_before_post_response(initially_empty):
    reset = "ui.state={runs:[],agents:[],events:[],resources:{}};changeSelection(null,null);" if initially_empty else ""
    check(r"""
await wire();
""" + reset + r"""
const pending=submit();addCreated();const polling=pollState();await drainStates();await polling;
assert.equal(ui.startOperation.runId,null);assert.equal($('startRun').disabled,true);
resolve(0,{run:{id:'created-run'}});await flush();await drainStates();await pending;
assert.equal(ui.selectedRun,'created-run');assert.equal($('taskDialog').open,false);
assert.equal(ui.startOperation,null);assert.equal(requests.filter(r=>r.path==='/api/runs').length,1);
""")


def test_start_does_not_close_new_settings_and_pending_controls_survive_profile_render():
    check(r"""
await wire();const pending=submit();setBriefOpen(false);showView('settings');
ui.config={providers:[{id:'local',label:'Fixture',model:'model',base_url:'http://127.0.0.1:11434/v1'}],limits:{max_workers:0}};
renderProfileChoices();assert.equal($('startRun').disabled,true);
addCreated();resolve(0,{run:{id:'created-run'}});await flush();await drainStates();await pending;
assert.equal(ui.selectedRun,'run-a');assert.equal($('settingsDialog').open,true);
assert.equal($('taskDialog').open,false);assert.equal(ui.startingRun,false);
""")


def test_rejected_start_allows_explicit_retry_without_replaying_automatically():
    check(r"""
await wire();const pending=submit();reject(0,new Error('Synthetic admission failure'));await pending;
assert.equal($('startRun').disabled,false);assert.equal(ui.startOperation,null);
assert.match($('runFormStatus').textContent,/Synthetic admission failure/);assert.equal(requests.length,1);
const retry=submit();assert.equal(requests.length,2);addCreated();resolve(1,{run:{id:'created-run'}});await flush();await drainStates();await retry;
assert.equal(ui.selectedRun,'created-run');assert.equal(requests.filter(r=>r.path==='/api/runs').length,2);
""")


def test_unknown_creation_outcome_and_malformed_success_are_explicit_never_replayed():
    check(r"""
await wire();let pending=submit();const failure=new Error('Synthetic disconnected response');failure.outcomeUnknown=true;
reject(0,failure);await pending;assert.match($('runFormStatus').textContent,/開始したかどうかは未確認/);
assert.equal(requests.length,1);assert.equal(ui.startOperation,null);
pending=submit();resolve(1,{ok:true});await pending;
assert.match($('runFormStatus').textContent,/実行 ID を確認できません/);
assert.match($('runFormStatus').textContent,/開始したかどうかは未確認/);
assert.equal(requests.length,2);assert.equal(ui.startingRun,false);
""")


def test_real_api_classifies_transport_and_http_failures_and_malformed_success():
    check(r"""
await wire();let calls=0;
globalThis.fetch=async()=>{calls++;const error=new Error('Synthetic timeout');error.name='TimeoutError';throw error;};
await assert.rejects(()=>productionApi('/api/runs',{method:'POST',body:{}}),error=>error.outcomeUnknown===true);
fetch=async()=>{calls++;return {ok:false,status:500,json:async()=>({error:'Synthetic server failure'})};};
await assert.rejects(()=>productionApi('/api/runs',{method:'POST',body:{}}),error=>error.outcomeUnknown===true);
fetch=async()=>{calls++;return {ok:false,status:400,json:async()=>({error:'Synthetic admission failure'})};};
await assert.rejects(()=>productionApi('/api/runs',{method:'POST',body:{}}),error=>error.outcomeUnknown===false);
fetch=async()=>{calls++;return {ok:true,status:200,json:async()=>{throw new Error('Synthetic invalid JSON');}};};
api=productionApi;await submit();assert.match($('runFormStatus').textContent,/開始したかどうかは未確認/);
for(const body of [null,[],42,'invalid']){
  fetch=async()=>{calls++;return {ok:true,status:200,json:async()=>body};};
  await submit();assert.match($('runFormStatus').textContent,/開始したかどうかは未確認/);
}
assert.equal(calls,8);assert.equal(ui.startOperation,null);
""")


def test_late_start_failure_labels_original_request_without_claiming_new_draft_sent():
    check(r"""
await wire();const pending=submit();setBriefOpen(false);setBriefOpen(true);clearTimeout(ui.preflightTimer);editTask('New draft');
reject(0,new Error('Synthetic rejection'));await pending;
assert.equal($('taskInput').value,'New draft');assert.equal($('taskDialog').open,true);
assert.match($('runFormStatus').textContent,/以前に送信した開始要求/);
assert.match($('runFormStatus').textContent,/現在の下書きは送信していません/);
""")


def test_pending_stop_guards_click_and_poll_until_mutation_settles():
    check(r"""
await wire();setBriefOpen(false);const pending=stop();await stop();
assert.equal(requests.length,1);assert.equal($('stopRun').disabled,true);
renderState();assert.equal($('stopRun').disabled,true);
const polling=pollState();resolve(1,stateFor(requests[1]));await polling;
assert.equal($('stopRun').disabled,true);await stop();assert.equal(requests.length,2);
resolve(0,{ok:true});await flush();runs[0].status='stopped';await drainStates();await pending;
assert.equal($('stopRun').disabled,true);assert.equal(ui.stoppingRuns.size,0);
assert.equal(requests.filter(r=>r.path.endsWith('/stop')).length,1);
""")


def test_late_stop_failure_cannot_enable_completed_or_stopped_current_run():
    check(r"""
await wire();setBriefOpen(false);const pending=stop();ui.state.runs[1].status='done';selectRun('run-b');
$('messageInput').focus();reject(0,new Error('Synthetic late stop failure'));await pending;
assert.equal(getRun().status,'done');assert.equal($('stopRun').disabled,true);
assert.equal(document.activeElement,$('messageInput'));assert.match($('globalNotice').textContent,/作業 run-a の停止要求/);
await stop();assert.equal(requests.filter(r=>r.path.endsWith('/stop')).length,1);
getRun().status='stopped';renderRun();await stop();assert.equal($('stopRun').disabled,true);
assert.equal(requests.filter(r=>r.path.endsWith('/stop')).length,1);
""")


def test_stop_rederives_same_run_after_aba_and_changed_terminal_state():
    check(r"""
await wire();setBriefOpen(false);const pending=stop();selectRun('run-b');selectRun('run-a');
getRun().status='stopping';renderRun();assert.equal($('stopRun').disabled,true);
notice('Newer notice');reject(0,new Error('Synthetic late failure'));await pending;
assert.equal(ui.selectedRun,'run-a');assert.equal($('stopRun').disabled,true);
assert.equal($('globalNotice').textContent,'Newer notice');
getRun().status='done';renderRun();await stop();assert.equal(requests.filter(r=>r.path.endsWith('/stop')).length,1);
""")


def test_distinct_pending_stops_are_independent_and_newest_notice_wins():
    check(r"""
await wire();setBriefOpen(false);const first=stop();selectRun('run-b');const second=stop();
assert.equal(ui.stoppingRuns.size,2);selectRun('run-a');assert.equal($('stopRun').disabled,true);
const stops=requests.filter(r=>r.path.endsWith('/stop'));assert.equal(stops.length,2);
stops[0].done=true;stops[0].reject(new Error('Older failure'));await first;
assert.equal(ui.stoppingRuns.size,1);assert.ok(!$('globalNotice').textContent.includes('Older failure'));
selectRun('run-b');assert.equal($('stopRun').disabled,true);
stops[1].done=true;stops[1].reject(new Error('Newer failure'));await second;
assert.equal(ui.stoppingRuns.size,0);assert.equal($('stopRun').disabled,false);
assert.match($('globalNotice').textContent,/作業 run-b の停止要求/);
""")
