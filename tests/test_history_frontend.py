"""Saved-history UI contracts using synthetic DOM and transport only."""
import pytest

from test_frontend import APP, HTML, run_javascript
from test_run_action_frontend import ACTION_DOM
from test_compact_frontend import FIXTURES
from test_cockpit_frontend import FOCUS
from test_task_reuse_frontend import check as reuse_check
from test_work_board_frontend import check as board_check
from test_task_guidance import Elements


HISTORY = r'''
function archiveCurrent(status='interrupted') {
  Object.assign(getRun(),{archived:true,read_only:true,status,original_status:'working',history_saved_at:1});
  ui.state.agents.filter(a=>a.run_id===getRun().id).forEach(a=>Object.assign(a,{archived:true,read_only:true,status,original_status:'working',message_eligibility:{allowed:false,reason:'archived_read_only'}}));
}
function storage(extra={}) {return {enabled:true,path:'C:\\private\\history\\work-history.sqlite3',status:'ready',error:'',archived_runs:1,max_runs:500,max_run_bytes:16777216,max_total_bytes:268435456,...extra};}
async function setupHistory() {await initialize();clearTimeout(ui.preflightTimer);seedSelection();}
'''


def check(source):
    result = run_javascript(ACTION_DOM + APP + '\nconst productionApi=api;\n' + FIXTURES + FOCUS + HISTORY + '\n(async()=>{\n' + source + r'''
clearTimeout(ui.preflightTimer);
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_history_notice_path_and_archive_guidance_have_accessible_unique_ids():
    tree = Elements()
    for ident in ('historyStorageError', 'historyStoragePath', 'historyStorageLimits', 'archiveNotice', 'workspaceMode'):
        assert HTML.count(f'id="{ident}"') == 1
    assert tree.ids['historyStorageError']['attrs']['role'] == 'alert'
    assert tree.ids['archiveNotice']['attrs']['role'] == 'status'
    assert '旧版ですでに消えた履歴は復元できません' in HTML
    assert 'モデル用の私的な会話文脈' in HTML
    assert '表示用の思考テキストは含みます' in HTML
    for phrase in ('表示から外れた後も保存履歴へ蓄積', '各一覧50,000件', 'タイムラインは最新100件', '掲示板は最大200件'):
        assert phrase in HTML


def test_storage_unknown_does_not_promise_durable_history():
    check(r'''
await setupHistory();renderHistoryStorage();
assert.match($('historyRetention').textContent,/保存状態を確認中/);
assert.doesNotMatch($('historyRetention').textContent,/自動保存します/);
assert.equal($('historyStoragePath').textContent,'保存先は未確認です');
assert($('historyStorageError').hidden);assert.equal(requests.length,0);
''')


def test_storage_ready_and_error_use_literal_text_and_keep_records_visible():
    check(r'''
await setupHistory();const records=structuredClone(ui.state);
acceptHistoryStorage({history_storage:storage({path:'<script>private path</script>'})});
assert.equal($('historyStoragePath').textContent,'<script>private path</script>');
assert.match($('historyRetention').textContent,/自動保存/);assert.match($('historyStorageLimits').textContent,/500/);
acceptHistoryStorage({history_storage:storage({status:'error',error:'履歴ファイルを読み込めません。'})});
assert(!$('historyStorageError').hidden);assert.match($('historyStorageError').textContent,/読み込めません/);
assert.match($('historyStorageError').textContent,/.txt 保存/);assert.deepEqual(ui.state,records);
acceptHistoryStorage({history_storage:storage()});assert($('historyStorageError').hidden);
assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('status', ['interrupted', 'done', 'stopped', 'error'])
def test_archived_run_is_selectable_and_distinguished_from_current_quota(status):
    check("await setupHistory();archiveCurrent('" + status + r"""');renderState();
assert.equal(ui.selectedRun,'run-a');assert.equal(ui.selectedAgent,'agent-a');
assert.equal($('runCount').textContent,'1 / 20 · 保存 1');
assert.match($('runCount').getAttribute('aria-label'),/保存履歴 1件/);
assert.match(renderedText($('runList')),/保存履歴/);
assert(!$('archiveNotice').hidden);assert.match($('archiveNotice').textContent,/閲覧専用/);
assert.match($('archiveNotice').textContent,/自動再開はしません/);
assert.equal($('workspaceMode').textContent,'SAVED HISTORY');assert($('stopRun').disabled);
assert.equal(requests.length,0);
""")


@pytest.mark.parametrize('flag', ['archived', 'read_only'])
def test_archive_flags_independently_block_stale_live_status_and_allowed_mutations(flag):
    check("await setupHistory();getRun()." + flag + r'''=true;
getRun().status='running';getAgent().status='waiting';getAgent().status_reason='human_input';getAgent().question='Past question';
getAgent().message_eligibility={allowed:true};$('messageInput').value='Do not send';renderState();
assert.equal(displayStatus(getRun()),'interrupted');assert.equal(needsHuman(getAgent()),false);
assert.equal(questionEntries().length,0);assert.equal(hasMessageInput(getAgent()),false);
assert.equal(canStopRun(getRun()),false);assert($('sendMessage').disabled);assert($('messageInput').disabled);
assert.match($('humanQuestion').textContent,/保存時点の質問（回答不可）/);
assert.match($('messageEligibility').textContent,/閲覧専用/);
assert.match($('networkCounts').textContent,/現在は実行していません/);
await $('messageForm').listeners.submit({preventDefault(){}});await $('stopRun').listeners.click();
assert.equal(requests.length,0);
''')


def test_archived_logs_thinking_reports_receipts_and_mail_remain_readable():
    check(r'''
await setupHistory();archiveCurrent('done');
ui.state.events=[{id:'saved-mail',run_id:'run-a',kind:'mail',from:'PM A',to:'Worker B',from_agent_id:'agent-a',to_agent_id:'agent-b',text:'Saved mail body',subject:'Saved subject',at:1}];
renderState();assert.match(renderedText($('conversationLog')),/seed log agent-a/);
assert.match(renderedText($('conversationLog')),/Reasoning agent-a/);
assert.equal(outputRecords(getAgent()).length,2);assert.equal(selectedOutput().record.text,'seed result agent-a');
assert.match(renderedText($('activityFeed')),/Saved mail body/);assert.match(renderedText($('activityFeed')),/Saved subject/);
const reply=$('activityFeed').querySelectorAll('*').find(n=>n.dataset.focusKey==='mail-reply:saved-mail');
assert(reply.disabled);reply.listeners.click();assert.equal(requests.length,0);
assert.equal(ui.selectedAgent,'agent-a');
''')


def test_archive_only_state_does_not_lock_settings():
    check(r'''
await setupHistory();ui.config={};ui.state.runs.forEach(r=>Object.assign(r,{archived:true,status:'running'}));
setSettingsLock();assert.equal(ui.settingsLocked,false);
''')


def test_archived_task_can_become_a_new_draft_without_starting_or_restoring_context():
    reuse_check(r'''
await setup();Object.assign(getRun(),{archived:true,read_only:true,status:'interrupted'});
const before=structuredClone(ui.state),payload=runPayload();reuse();
assert.equal($('taskInput').value,before.runs[0].task);assert.deepEqual(ui.state,before);
assert.deepEqual(runPayload(),{...payload,task:before.runs[0].task});
assert.match($('taskReuseStatus').textContent,/まだ開始していません/);assert.equal(requests.length,0);
''')


def test_archived_board_reads_saved_enabled_state_but_disables_post_reply_and_retry():
    board_check(r'''
await bootBoard();Object.assign(getRun(),{archived:true,read_only:true,status:'interrupted'});
ui.config={work_board:{enabled:false}};await received([post(1,{body:'Saved discussion'})],{can_post:false,archived:true,read_only:true});
assert(boardText().includes('Saved discussion'));assert($('workBoardForm').hidden);assert($('workBoardInput').disabled);
assert($('workBoardSend').disabled);assert(workBoardState('run-a').nodes.get(1).reply.disabled);
assert.match($('workBoardMode').textContent,/保存した掲示板/);
const board=workBoardState('run-a');board.operation={id:'old',status:'unknown',body:'Old pending',reply_to:null};
renderWorkBoardControls(getRun());assert($('workBoardRetry').disabled);assert($('workBoardUncertain').hidden);
const before=requests.length;await submitWorkBoardPost();await submitWorkBoardPost(true);assert.equal(requests.length,before);
''')


def test_new_server_instance_drops_caches_pending_actions_and_old_redaction_epoch():
    check(r'''
await setupHistory();acceptServerInstance({instance_id:'instance-a'});
ui.boardRedactionRevision=7;const board=workBoardState('run-a');board.posts.set(1,{body:'Old text'});board.draft.body='Old draft';board.operation={status:'unknown',body:'Old pending'};
$('workBoardReplyBody').textContent='Old quote';$('workBoardUncertainBody').textContent='Old pending';
ui.drafts.set('agent-a','Old instruction');ui.startOperation={runId:'old'};ui.startingRun=true;
const generation=ui.selectionGeneration;assert(acceptServerInstance({instance_id:'instance-b'}));
assert.equal(ui.boardRedactionRevision,null);assert.equal(ui.workBoards.size,0);assert.equal(ui.drafts.size,0);
assert.equal($('workBoardReplyBody').textContent,'');assert.equal($('workBoardUncertainBody').textContent,'');
assert.equal($('conversationLog').children.length,1);assert.match(renderedText($('conversationLog')),/エージェントを選ぶ/);
assert.doesNotMatch(renderedText($('conversationLog')),/seed log|Reasoning|Old instruction/);assert.equal(ui.loadedDetail,null);assert.equal($('resultText').textContent,'');
assert.equal(ui.startOperation,null);assert.equal(ui.startingRun,false);
assert.equal(ui.selectedRun,null);assert.equal(ui.selectedAgent,null);assert(ui.selectionGeneration>generation);
assert.equal(ui.configStale,true);assert.equal(requests.length,0);
assert.throws(()=>acceptServerInstance({instance_id:'instance-a'}),/以前のサーバー/);
assert.equal(ui.instanceId,'instance-b');
''')


@pytest.mark.parametrize('bad', ["{}", "{instance_id:''}", "{instance_id:3}"])
def test_known_instance_cannot_silently_downgrade_or_accept_invalid_identity(bad):
    check("await setupHistory();acceptServerInstance({instance_id:'instance-a'});assert.throws(()=>acceptServerInstance(" + bad + "));assert.equal(ui.instanceId,'instance-a');")


def test_new_instance_allows_new_redaction_epoch_and_preserves_new_selected_detail_contract():
    check(r'''
await setupHistory();acceptServerInstance({instance_id:'instance-a'});ui.boardRedactionRevision=12;
const response=compactState('run-a','agent-a','Restored');response.instance_id='instance-b';response.redaction_revision=0;
response.runs.forEach(r=>Object.assign(r,{archived:true,read_only:true,status:'done'}));
response.agents.forEach(a=>Object.assign(a,{archived:true,read_only:true,status:'done'}));
response.history_storage=storage();
applyState(response,{run:'run-a',agent:'agent-a',generation:ui.selectionGeneration});renderState();
assert.equal(ui.instanceId,'instance-b');assert.equal(ui.boardRedactionRevision,0);
assert.equal($('runCount').textContent,'0 / 20 · 保存 2');assert.match($('historyRetention').textContent,/自動保存/);
assert.equal(requests.length,0);
''')


def test_inflight_old_board_page_cannot_repopulate_new_instance_cache():
    board_check(r'''
await bootBoard();acceptServerInstance({instance_id:'instance-a'});
const first=requests.at(-1);acceptServerInstance({instance_id:'instance-b'});
first.resolve(page([post(1,{body:'Stale old server body'})],{instance_id:'instance-a'}));await flush();
assert.equal(ui.workBoards.size,0);assert(!boardText().includes('Stale old server body'));
assert.equal(ui.instanceId,'instance-b');
''')


def test_old_board_post_receipt_cannot_repopulate_or_confirm_in_the_new_instance():
    board_check(r'''
await bootBoard();await received();acceptServerInstance({instance_id:'instance-a'});
editBoard('Original pending post');const pending=submitWorkBoardPost(),index=requests.length-1;
acceptServerInstance({instance_id:'instance-b'});confirmed(index);await pending;
assert.equal(ui.workBoards.size,0);assert.equal(ui.selectedRun,null);
assert.equal($('workBoardInput').value,'');assert(!boardText().includes('Original pending post'));
assert.equal(requests.length,index+1);
''')


def test_delayed_old_http_error_does_not_revoke_new_instance_authentication():
    check(r'''
await setupHistory();acceptServerInstance({instance_id:'instance-a'});
let release;globalThis.fetch=()=>new Promise(resolve=>release=resolve);
const pending=productionApi('/api/config').catch(error=>error);
acceptServerInstance({instance_id:'instance-b'});ui.authenticated=true;
release({ok:false,status:401,json:async()=>({ok:false,error:'old session'})});
const failure=await pending;assert.match(failure.message,/以前のサーバー/);
assert.equal(ui.authenticated,true);assert.equal(ui.instanceId,'instance-b');
''')


def test_retired_instance_config_is_rejected_before_callers_receive_fields():
    check(r'''
await setupHistory();acceptServerInstance({instance_id:'instance-a'});acceptServerInstance({instance_id:'instance-b'});
globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({instance_id:'instance-a',config:{old:true}})});
await assert.rejects(()=>productionApi('/api/config'),/以前のサーバー/);
assert.equal(ui.instanceId,'instance-b');
''')


@pytest.mark.parametrize('old_outcome', ['success', 'failure'])
def test_old_instance_message_cannot_unlock_a_new_pending_message(old_outcome):
    check(r'''
await setupHistory();acceptServerInstance({instance_id:'instance-a'});
$('messageInput').value='Old A request';const oldPending=$('messageForm').listeners.submit({preventDefault(){}});
assert.equal(requests.length,1);acceptServerInstance({instance_id:'instance-b'});seedSelection();
$('messageInput').value='New B request';const newPending=$('messageForm').listeners.submit({preventDefault(){}});
assert.equal(requests.length,2);const owned=ui.messageOperation;
''' + ("requests[0].resolve({ok:true});" if old_outcome == 'success' else "requests[0].reject(new Error('Old A failed'));") + r'''
await oldPending;assert.equal(ui.messageOperation,owned);assert.equal(ui.busyMessage,true);
assert($('sendMessage').disabled);assert.equal($('messageInput').value,'New B request');
await $('messageForm').listeners.submit({preventDefault(){}});assert.equal(requests.length,2);
requests[1].reject(new Error('B outcome'));await newPending;
assert.equal(ui.busyMessage,false);assert.equal(ui.messageOperation,null);
assert.equal($('messageInput').value,'New B request');
''')


@pytest.mark.parametrize('method', ['POST', 'PUT', 'DELETE', 'PATCH'])
def test_mutations_bind_the_observed_server_instance_without_changing_payload(method):
    check("await setupHistory();acceptServerInstance({instance_id:'instance-a'});const method='" + method + r"""';
const seen=[];globalThis.fetch=async(path,options)=>{seen.push({path,options});return {ok:true,status:200,json:async()=>({ok:true})};};
const body={config_revision:0,synthetic:'unchanged'};
await productionApi('/api/synthetic',{method,body});
assert.equal(seen.length,1);assert.equal(seen[0].options.headers['X-Workbench-Instance'],'instance-a');
assert.deepEqual(JSON.parse(seen[0].options.body),body);
await productionApi('/api/state');assert.equal(seen[1].options.headers['X-Workbench-Instance'],undefined);
await productionApi('/api/bootstrap',{method:'POST',headers:{'X-Workbench-Bootstrap':'synthetic'},body:{}});
assert.equal(seen[2].options.headers['X-Workbench-Instance'],undefined);
assert.equal(seen[2].options.headers['X-Workbench-Bootstrap'],'synthetic');
""")


def test_rejected_stale_mutation_refreshes_current_state_without_replay():
    check(r"""
await setupHistory();acceptServerInstance({instance_id:'instance-a'});ui.authenticated=true;
ui.drafts.set('agent-a','Old secret-containing draft');workBoardState('run-a').posts.set(1,{body:'Old quote'});
const seen=[];globalThis.fetch=async(path,options)=>{seen.push({path,options});return {ok:false,status:409,json:async()=>({ok:false,code:'instance_changed',instance_id:'instance-b',error:'Server restarted'})};};
let refreshed=0;pollState=async fresh=>{assert.equal(fresh,true);assert.equal(ui.instanceId,'instance-b');assert.equal(ui.drafts.size,0);refreshed++;};
const failure=await productionApi('/api/config',{method:'PUT',body:{config_revision:0,config:{old:true}}}).catch(error=>error);
assert.equal(seen.length,1);assert.equal(seen[0].options.headers['X-Workbench-Instance'],'instance-a');
assert.equal(refreshed,1);assert.equal(ui.instanceId,'instance-b');assert.equal(ui.configStale,true);
assert.equal(failure.code,'instance_changed');assert.equal(failure.outcomeUnknown,false);
assert.match($('globalNotice').textContent,/処理は実行されませんでした/);assert.match($('globalNotice').textContent,/自動再送信はしません/);
assert.equal(ui.workBoards.size,0);assert.equal(ui.selectedAgent,null);assert.equal(ui.selectedRun,null);
""")


def test_delayed_retired_instance_rejection_cannot_adopt_it_or_refresh_again():
    check(r"""
await setupHistory();acceptServerInstance({instance_id:'instance-a'});
let release;globalThis.fetch=()=>new Promise(resolve=>release=resolve);
const pending=productionApi('/api/runs',{method:'POST',body:{task:'Old start'}}).catch(error=>error);
acceptServerInstance({instance_id:'instance-b'});acceptServerInstance({instance_id:'instance-c'});
let refreshed=0;pollState=async()=>refreshed++;
release({ok:false,status:409,json:async()=>({ok:false,code:'instance_changed',instance_id:'instance-b'})});
assert.match((await pending).message,/以前のサーバー/);
assert.equal(ui.instanceId,'instance-c');assert.equal(refreshed,0);
""")
