"""Phase 7 UI: tool-call approval, team memo and proposals, and history search.

Production app.js with a synthetic DOM and deferred transport; no model request.
"""
import json

import pytest

from test_frontend import APP, HTML, run_javascript
from test_run_action_frontend import ACTION_DOM, ACTION_FIXTURES
from test_credential_recovery_frontend import CONFIG, DOM as SETTINGS_DOM


PHASE7_FIXTURES = r"""
const fixtureApi=api;
api=(path,options={})=>{const pending=fixtureApi(path,options);requests[requests.length-1].options=options;return pending;};
let pendingProposals=[];
const fixtureFullState=fullState;
fullState=(marker='current')=>({...fixtureFullState(marker),memo_proposals:structuredClone(pendingProposals)});
function allNodes(node){return [node,...node.children.flatMap(allNodes)];}
function byFocusKey(root,key){return allNodes(root).find(node=>node.dataset.focusKey===key);}
function card(id){return $('agentCards').children.find(node=>node.dataset.agentId===id);}
function askApproval(index,approval){Object.assign(summaries[index],{status:'waiting',status_reason:'approval',approval});}
async function ready(){await wire();setBriefOpen(false);assert.equal(requests.length,0);}
"""


def check(source):
    result = run_javascript(ACTION_DOM + APP + "\nconst productionApi=api;\n" + ACTION_FIXTURES + PHASE7_FIXTURES + "\n(async()=>{\n" + source + r"""
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
""")
    assert result == {"ok": True}


SETTINGS_SETUP = r'''
async function setup(withCloud=false){
 await wire(withCloud);$('systemPolicy').tagName='TEXTAREA';
 for(const id of ['pathFields','pythonFields','seleniumFields'])$(id).querySelectorAll('textarea').forEach(node=>node.classList.add('path-input'));
 const bottom=element('button');bottom.type='submit';$('settingsForm').append(bottom);
 $('teamMemo').dataset.memo='true';$('saveMemo').dataset.memo='true';
}
function submit(){return $('settingsForm').listeners.submit({preventDefault(){}});}
function receipt(index=0){const config=structuredClone(requests[index].options.body.config);return {config,config_revision:requests[index].options.body.config_revision+1,secret_status:{...Object.fromEntries(config.providers.map(p=>[p.id,false])),search:false}};}
function radio(value){return $('approvalFields').querySelectorAll('[data-key="mode"]').find(node=>node.value===value);}
function field(container,key){return $(container).querySelector(`[data-key="${key}"]`);}
function fallback(index){return $('profilesEditor').children[index].querySelector('[data-key="fallback_profile_id"]');}
'''


def check_settings(source):
    result = run_javascript(SETTINGS_DOM + '\nconst CONFIG=' + json.dumps(CONFIG) + ';\n' + APP + SETTINGS_SETUP + '\n(async()=>{\n' + source + r'''
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_static_controls_exist_in_plain_japanese():
    for ident in ('approvalCard', 'approvalSummary', 'approvalNote', 'approveAction', 'rejectAction', 'approvalQueue',
                  'approvalAlwaysAllow', 'approvalFields', 'memoFields', 'historySearchFields', 'teamMemo', 'saveMemo',
                  'memoProposalNotice', 'memoProposalDialog', 'historySearchForm', 'historySearchInput', 'historySearchResults'):
        assert f'id="{ident}"' in HTML
    for text in ('操作の承認が必要です', '理由（任意）', '承認して実行', '却下', '承認待ち',
                 'この作業では操作の承認を求めない（常に許可）', 'チームのメモ', 'メモを保存',
                 'すべての作業の担当者に渡す、長く使う指示です。権限は増えません。',
                 '新しいファイルの作成や読み取りは確認しません。', '過去の作業の検索',
                 '検索できるのは過去の依頼文と報告だけです。', '過去の作業を検索', 'メモへの追加提案'):
        assert text in HTML
    for text in ('実行前に確認する', '確認せずに実行する（常に許可）', 'Python の実行', 'ブラウザ操作',
                 '既存ファイルの上書き・編集', 'PM がメモへの追加を提案できる', 'PM が過去の作業を検索できる', '障害時の代替モデル'):
        assert text in APP
    assert 'innerHTML' not in APP and 'insertAdjacentHTML' not in APP


@pytest.mark.parametrize("tool,label", [
    ('python_execute', 'Python の実行'), ('selenium_browse', 'ブラウザ操作'),
    *[(tool, '既存ファイルの変更') for tool in ('write_text', 'patch_text', 'docx_edit', 'docx_write', 'xlsx_write', 'pptx_edit', 'pptx_write')],
])
def test_approval_tool_labels(tool, label):
    check(f"assert.equal(approvalToolLabel({tool!r}),{label!r});")


def test_approval_card_renders_untrusted_text_and_approves_once_with_note():
    check(r"""
askApproval(1,{id:'ap-1',tool:'python_execute',summary:'<img src=x onerror=alert(1)>\nprint(1)',requested_at:5});
await ready();ui.selectedAgent='agent-b';renderState();
assert.equal($('approvalCard').hidden,false);assert.equal($('approvalTool').textContent,'操作: Python の実行');
assert.equal($('approvalSummary').textContent,'<img src=x onerror=alert(1)>\nprint(1)');
assert.equal(stateLabel(getAgent()),'承認待ち');assert.equal($('conversationStatus').textContent,'承認待ち');
assert.match(renderedText(card('agent-b')),/承認待ち/);
assert.equal($('approveAction').disabled,false);assert.equal($('rejectAction').disabled,false);
$('approvalNote').value='  確認しました  ';renderState();assert.equal($('approvalNote').value,'  確認しました  ');
const pending=$('approveAction').listeners.click();
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/agents/agent-b/approval');
assert.equal(requests[0].options.method,'POST');
assert.deepEqual(requests[0].options.body,{approval_id:'ap-1',decision:'approve',note:'確認しました'});
assert.equal($('approveAction').disabled,true);assert.equal($('rejectAction').disabled,true);
await $('approveAction').listeners.click();await $('rejectAction').listeners.click();renderState();
assert.equal(requests.length,1);assert.equal($('approveAction').disabled,true);
delete summaries[1].approval;Object.assign(summaries[1],{status:'working',status_reason:''});
resolve(0,{ok:true,decision:'approve'});await flush();await drainStates();await pending;
assert.equal(requests.filter(r=>r.path.endsWith('/approval')).length,1);assert.equal(ui.approvalOperation,null);
assert.equal($('approvalCard').hidden,true);assert.match($('globalNotice').textContent,/Worker B の操作を承認しました/);
assert.equal($('approvalQueue').hidden,true);
""")


def test_reject_without_note_and_error_reenables_buttons():
    check(r"""
askApproval(1,{id:'ap-2',tool:'write_text',summary:'out/report.txt を上書き',requested_at:5});
await ready();ui.selectedAgent='agent-b';renderState();
assert.equal($('approvalTool').textContent,'操作: 既存ファイルの変更');
const pending=$('rejectAction').listeners.click();
assert.deepEqual(requests[0].options.body,{approval_id:'ap-2',decision:'reject'});
reject(0,new Error('この承認はすでに終了しています'));await pending;
assert.equal($('approvalStatus').textContent,'送信できませんでした: この承認はすでに終了しています');
assert.ok($('approvalStatus').classes.has('error'));
assert.equal($('approveAction').disabled,false);assert.equal($('rejectAction').disabled,false);
const retry=$('rejectAction').listeners.click();assert.equal(requests.length,2);reject(1,new Error('again'));await retry;
""")


def test_waiting_indicator_counts_live_runs_and_cycles_through_agents():
    check(r"""
askApproval(1,{id:'ap-b',tool:'selenium_browse',summary:'open page',requested_at:5});
askApproval(2,{id:'ap-c',tool:'python_execute',summary:'run',requested_at:6});
await ready();
assert.equal($('approvalQueue').hidden,false);assert.equal($('approvalCount').textContent,'2');
assert.match(renderedText($('runList')),/承認待ち 1件/);
assert.equal(ui.selectedAgent,'agent-a');assert.equal($('approvalCard').hidden,true);
$('approvalQueue').listeners.click();
assert.equal(ui.selectedRun,'run-a');assert.equal(ui.selectedAgent,'agent-b');
assert.equal(document.activeElement,$('approvalCard'));assert.equal($('approvalCard').hidden,false);
await drainStates();
$('approvalQueue').listeners.click();assert.equal(ui.selectedRun,'run-b');assert.equal(ui.selectedAgent,'agent-c');
assert.equal($('approvalTool').textContent,'操作: Python の実行');await drainStates();
$('approvalQueue').listeners.click();assert.equal(ui.selectedAgent,'agent-b');await drainStates();
getRun().status='stopped';ui.state.runs.find(run=>run.id==='run-b').archived=true;renderState();
assert.equal($('approvalQueue').hidden,true);assert.equal($('approvalCount').textContent,'0');
""")


def test_new_task_sends_approval_mode_and_run_metrics_show_it():
    check(r"""
await wire();
assert.ok(!$('approvalAlwaysAllow').checked);assert.equal(runPayload().approval_mode,'ask');
$('approvalAlwaysAllow').checked=true;trackTaskDraft({type:'change',target:$('approvalAlwaysAllow')});
assert.equal(ui.approvalChoiceTouched,true);
const pending=submit();assert.equal(requests[0].path,'/api/runs');
assert.equal(requests[0].options.body.approval_mode,'always_allow');
reject(0,new Error('stop here'));await pending;
setBriefOpen(false);getRun().approval_mode='always_allow';renderRun();
assert.match(renderedText($('runMetrics')),/操作の承認\n常に許可/);
getRun().approval_mode='ask';renderRun();assert.match(renderedText($('runMetrics')),/操作の承認\n毎回確認/);
delete getRun().approval_mode;renderRun();assert.doesNotMatch(renderedText($('runMetrics')),/操作の承認/);
""")


def test_new_task_checkbox_follows_saved_mode_until_touched():
    check_settings(r'''
await setup();assert.equal($('approvalAlwaysAllow').checked,false);
ui.config.approvals.mode='always_allow';renderProfileChoices(true);assert.equal($('approvalAlwaysAllow').checked,true);
assert.equal(runPayload().approval_mode,'always_allow');
$('approvalAlwaysAllow').checked=false;trackTaskDraft({type:'change',target:$('approvalAlwaysAllow')});
renderProfileChoices(true);assert.equal($('approvalAlwaysAllow').checked,false);assert.equal(runPayload().approval_mode,'ask');
''')


def test_settings_round_trip_for_approvals_memo_history_and_fallback():
    check_settings(r'''
await setup(true);
assert.equal(radio('ask').checked,true);assert.equal(radio('always_allow').checked,false);
assert.equal(field('approvalFields','python').checked,true);assert.equal(field('memoFields','proposals_enabled').checked,true);
assert.equal(field('historySearchFields','pm_enabled').checked,false);
const options=fallback(0).children.map(node=>[node.value,node.textContent]);
assert.deepEqual(options,[['','なし'],['cloud','Cloud fixture（cloud）']]);
assert.deepEqual(fallback(1).children.map(node=>node.value),['','local']);
radio('ask').checked=false;radio('always_allow').checked=true;field('approvalFields','python').checked=false;
field('memoFields','proposals_enabled').checked=false;field('historySearchFields','pm_enabled').checked=true;
fallback(0).value='cloud';fallback(0).listeners.change();
$('settingsForm').listeners.change({target:field('historySearchFields','pm_enabled')});assert(ui.settingsDirty);
const pending=submit();assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config');
const config=requests[0].options.body.config;
assert.deepEqual(config.approvals,{mode:'always_allow',python:false,selenium:true,overwrite:true});
assert.deepEqual(config.memo,{proposals_enabled:false});assert.deepEqual(config.history_search,{pm_enabled:true});
assert.equal(config.providers[0].fallback_profile_id,'cloud');assert.equal(config.providers[1].fallback_profile_id,'');
requests[0].resolve(receipt());await pending;assert.equal($('settingsStatus').textContent,'設定を保存しました。');
assert.deepEqual(ui.config.approvals,config.approvals);
renderSettings();
assert.equal(radio('always_allow').checked,true);assert.equal(radio('ask').checked,false);
assert.equal(field('approvalFields','python').checked,false);assert.equal(field('historySearchFields','pm_enabled').checked,true);
assert.equal(fallback(0).value,'cloud');
$('profilesEditor').children[1].querySelector('[data-key="id"]').value='cloud-2';refreshFallbackChoices();
assert.equal(fallback(0).value,'cloud');
assert.deepEqual(fallback(0).children.map(node=>node.textContent),['なし','Cloud fixture（cloud-2）','cloud（見つかりません）']);
''')


def test_saved_config_without_new_groups_stays_valid_and_is_not_expanded():
    check_settings(r'''
await setup();const legacy=structuredClone(ui.config);delete legacy.approvals;delete legacy.memo;delete legacy.history_search;
delete legacy.providers[0].fallback_profile_id;
assert(validSavedSettings({config:legacy,config_revision:4,secret_status:{local:false,search:false}},4));
ui.config=legacy;renderSettings();for(const id of ['pathFields','pythonFields','seleniumFields'])$(id).querySelectorAll('textarea').forEach(node=>node.classList.add('path-input'));
assert.equal(radio('ask').checked,true);
const config=collectConfig();
assert(!Object.hasOwn(config,'approvals')&&!Object.hasOwn(config,'memo')&&!Object.hasOwn(config,'history_search'));
assert.equal(config.providers[0].fallback_profile_id,'');
''')


def test_memo_loads_on_open_and_saves_separately_from_settings():
    check_settings(r'''
await setup();$('settingsDialog').close();openSettings();
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/memo');
assert.equal($('saveMemo').disabled,true);await $('saveMemo').listeners.click();assert.equal(requests.length,1);
requests[0].resolve({memo:{text:'既存のメモ',updated_at:1,max_chars:4000},proposals:[]});await flush();
assert.equal($('teamMemo').value,'既存のメモ');assert.equal($('teamMemo').disabled,false);assert.equal($('saveMemo').disabled,true);
$('teamMemo').value='新しいメモ';$('settingsForm').listeners.input({target:$('teamMemo')});
assert.equal(ui.settingsDirty,false);assert.equal($('saveMemo').disabled,false);
const pending=$('saveMemo').listeners.click();await $('saveMemo').listeners.click();
assert.equal(requests.length,2);assert.equal(requests[1].path,'/api/memo');
assert.equal(requests[1].options.method,'POST');assert.deepEqual(requests[1].options.body,{text:'新しいメモ'});
requests[1].resolve({ok:true,memo:{text:'新しいメモ',updated_at:2,max_chars:4000},proposals:[]});await pending;
assert.equal($('memoStatus').textContent,'メモを保存しました。');assert.equal($('saveMemo').disabled,true);
assert(!requests.some(request=>request.path==='/api/config'));
$('settingsDialog').close();openSettings();requests[2].reject(new Error('読めません'));await flush();
assert.match($('memoStatus').textContent,/メモを読み込めませんでした: 読めません/);assert.equal($('saveMemo').disabled,true);
await saveMemo();assert.equal(requests.length,3);
''')


def test_memo_proposals_notice_dialog_and_decisions():
    check(r"""
pendingProposals=[
  {id:'mp-1',run_id:'run-a',agent_id:'agent-a',agent_name:'PM A',text:'<i>表で報告する</i>',reason:'毎回指示されるため',status:'pending',created_at:1},
  {id:'mp-2',run_id:'run-b',agent_id:'agent-c',agent_name:'PM C',text:'日付は西暦',reason:'',status:'pending',created_at:2}];
await ready();
assert.equal($('memoProposalNotice').hidden,false);assert.equal($('memoProposalCount').textContent,'2');
$('memoProposalNotice').listeners.click();assert.equal($('memoProposalDialog').open,true);
const text=renderedText($('memoProposalList'));
assert.match(text,/PM A からの提案/);assert(text.includes('<i>表で報告する</i>'));assert.match(text,/理由: 毎回指示されるため/);
const approve=byFocusKey($('memoProposalList'),'memo-proposal:mp-1:approve');assert.equal(approve.textContent,'メモに追加');
const pending=approve.listeners.click();
assert.equal(requests[0].path,'/api/memo/proposals/mp-1');assert.equal(requests[0].options.method,'POST');
assert.deepEqual(requests[0].options.body,{decision:'approve'});
assert.equal(byFocusKey($('memoProposalList'),'memo-proposal:mp-2:reject').disabled,true);
await byFocusKey($('memoProposalList'),'memo-proposal:mp-2:reject').listeners.click();assert.equal(requests.length,1);
pendingProposals.shift();resolve(0,{ok:true,memo:{text:'表で報告する',updated_at:2,max_chars:4000},proposals:structuredClone(pendingProposals)});
await flush();await drainStates();await pending;
assert.equal($('memoProposalCount').textContent,'1');assert.equal($('memoProposalStatus').textContent,'メモに追加しました。');
const reject=byFocusKey($('memoProposalList'),'memo-proposal:mp-2:reject');assert.equal(reject.textContent,'却下');assert.equal(reject.disabled,false);
const rejected=reject.listeners.click();const index=requests.length-1;
assert.equal(requests[index].path,'/api/memo/proposals/mp-2');assert.deepEqual(requests[index].options.body,{decision:'reject'});
pendingProposals=[];resolve(index,{ok:true,memo:{text:'表で報告する',updated_at:2,max_chars:4000},proposals:[]});
await flush();await drainStates();await rejected;
assert.equal($('memoProposalNotice').hidden,true);assert.equal($('memoProposalStatus').textContent,'提案を却下しました。');
assert.match(renderedText($('memoProposalList')),/確認を待っている提案はありません/);
""")


def test_memo_proposal_error_is_shown_and_retry_allowed():
    check(r"""
pendingProposals=[{id:'mp-1',run_id:'run-a',agent_id:'agent-a',agent_name:'PM A',text:'追記',reason:'r',status:'pending',created_at:1}];
await ready();$('memoProposalNotice').listeners.click();
const pending=byFocusKey($('memoProposalList'),'memo-proposal:mp-1:approve').listeners.click();
reject(0,new Error('メモが上限を超えます'));await pending;
assert.equal($('memoProposalStatus').textContent,'送信できませんでした: メモが上限を超えます');
assert.ok($('memoProposalStatus').classes.has('error'));
assert.equal(byFocusKey($('memoProposalList'),'memo-proposal:mp-1:approve').disabled,false);
""")


def test_history_search_requests_renders_results_and_selects_run():
    check(r"""
await ready();const form=$('historySearchForm').listeners;
$('historySearchInput').value='   ';await form.submit({preventDefault(){}});assert.equal(requests.length,0);
assert.ok($('historySearchStatus').classes.has('error'));
$('historySearchInput').value='  報告書 & 表  ';const pending=form.submit({preventDefault(){}});
assert.equal(requests[0].path,'/api/history/search?q='+encodeURIComponent('報告書 & 表'));
assert.equal($('historySearchButton').disabled,true);await form.submit({preventDefault(){}});assert.equal(requests.length,1);
resolve(0,{ok:true,query:'報告書 & 表',runs:[
  {run_id:'run-b',saved_at:1700000000,task:'Second task\nhidden second line',status:'done',matches:[
    {source:'task',agent:'',text:'<script>x</script>'},{source:'result',agent:'PM C',text:'報告の抜粋'},{source:'log',agent:'PM C',text:'third match is not shown'}]},
  {run_id:'gone-run',saved_at:1700000000,task:'Old task',status:'stopped',matches:[{source:'log',agent:'W',text:'ログの抜粋'}]}]});
await pending;
const results=$('historySearchResults').children;assert.equal(results.length,2);
const first=renderedText(results[0]);
assert.match(first,/Second task/);assert.doesNotMatch(first,/hidden second line/);
assert(first.includes('依頼: <script>x</script>'));assert(first.includes('報告 · PM C: 報告の抜粋'));
assert.doesNotMatch(first,/third match/);assert(first.includes(new Date(1700000000*1000).toLocaleDateString('ja-JP')));
assert.match(renderedText(results[1]),/ログ · W: ログの抜粋/);
assert.equal($('historySearchStatus').textContent,'2件見つかりました。');assert.equal($('historySearchButton').disabled,false);
results[0].listeners.click();assert.equal(ui.selectedRun,'run-b');await drainStates();
results[1].listeners.click();assert.equal(ui.selectedRun,'run-b');assert.ok($('historySearchStatus').classes.has('error'));
assert.match($('historySearchStatus').textContent,/今の作業履歴にありません/);
const empty=form.submit({preventDefault(){}});const index=requests.length-1;resolve(index,{ok:true,query:'報告書 & 表',runs:[]});await empty;
assert.equal($('historySearchStatus').textContent,'見つかりませんでした');assert.equal($('historySearchResults').children.length,0);
const failed=form.submit({preventDefault(){}});reject(requests.length-1,new Error('検索語が長すぎます'));await failed;
assert.equal($('historySearchStatus').textContent,'検索できませんでした: 検索語が長すぎます');
assert.ok($('historySearchStatus').classes.has('error'));
""")
