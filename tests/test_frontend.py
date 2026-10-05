"""UI contract and browser JavaScript checks without any model request."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def run_javascript(source):
    if not NODE:
        pytest.skip("Node is required for JavaScript checks")
    result = subprocess.run([NODE, "-e", source], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_javascript_parses():
    if not NODE:
        pytest.skip("Node is required")
    result = subprocess.run([NODE, "--check", str(STATIC / "app.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_assets_are_local_and_untrusted_content_has_no_html_sink():
    assert not re.search(r'<script[^>]*>(?!\s*</script>)', HTML)
    assert re.findall(r'<script[^>]+src="([^"]+)"', HTML) == ["/app.js"]
    assert re.findall(r'<link[^>]+href="([^"]+)"', HTML) == ["/styles.css"]
    assert not re.search(r"\son(?:click|load|error|submit)\s*=", HTML)
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function(", "localStorage", "sessionStorage"):
        assert sink not in APP
    assert ".textContent=" in APP


def test_settings_ui_covers_every_interface_field_without_persisting_raw_keys():
    prefix = APP[:APP.index("const STATUS_LABELS")]
    result = run_javascript(prefix + "console.log(JSON.stringify({groups:FIELD_GROUPS,profiles:PROFILE_FIELDS}));")
    config = json.loads((ROOT / "docs/interface.json").read_text(encoding="utf-8"))["config"]
    for section in ("paths", "local", "search", "limits"):
        assert {field[0] for field in result["groups"][section]} == set(config[section])
    assert {field[0] for field in result["profiles"]} | {"enabled"} == set(config["providers"][0])
    assert 'id="systemPolicy"' in HTML and 'id="policyPreview"' in HTML
    assert "config.system_policy=$('systemPolicy').value" in APP
    assert "'/api/secrets'" in APP and "secret.value=''" in APP
    assert not any(field[0] == "api_key" for field in result["profiles"])


def test_resource_summary_distinguishes_slots_from_workers_and_gpu_admission():
    function = re.search(r"function resourceLabel\(.*?\n\}", APP, re.S).group()
    result = run_javascript(function + r"""
console.log(JSON.stringify({empty:resourceLabel({}),state:resourceLabel({active:1,queued:2,gpu_readings:[{index:0,used_mb:7168,utilization_percent:35}]})}));
""")
    assert result["empty"] == "リソース情報なし"
    assert result["state"] == "Local 実行 1 · 待機 2 · VRAM 7168 MB · GPU 35%"
    assert "強制的に制限する機能ではありません" in HTML
    assert 'id="maxWorkers" type="number" min="0"' in HTML


def test_bootstrap_drops_token_before_authenticated_requests():
    drop = APP.index("history.replaceState(null,'',location.pathname+location.search)")
    bootstrap = APP.index("await api('/api/bootstrap'")
    config = APP.index("const response=await api('/api/config')")
    assert drop < bootstrap < config
    assert "'X-Workbench-Bootstrap':token},body:{}" in APP
    assert "credentials:'same-origin'" in APP


def test_auto_collaboration_limit_exposes_integer_bounds_and_blocked_run_state():
    prefix = APP[:APP.index("const ACTIVE_STATUSES")]
    result = run_javascript(prefix + "console.log(JSON.stringify({field:FIELD_GROUPS.limits.find(field=>field[0]==='max_auto_collaborations'),bounds:NUMBER_BOUNDS.limits.max_auto_collaborations}));")
    assert result["bounds"] == [0, 1000]
    assert result["field"][2] == "number"
    assert result["field"][4] == "1"
    assert "24" in result["field"][5]
    assert 'id="collaborationLimitNotice"' in HTML
    assert "run.auto_collaborations??0" in APP
    assert "run.max_auto_collaborations??24" in APP
    assert "run.collaboration_limit_reached===true" in APP


def test_run_and_reply_preserve_exact_visible_text_and_default_thinking_is_collapsed():
    assert "const task=$('taskInput').value" in APP
    assert "body:{task,pm_profile:" in APP
    assert "body:{text}" in APP
    assert "detail.open=expanded.has(id)" in APP
    assert "$('messageInput').value===text" in APP
    assert "ui.drafts.get(id)||''" in APP
    assert "if(ui.polling){await ui.pollPromise;if(fresh)return pollState();return;}" in APP


def test_cockpit_has_unique_targets_and_original_local_assets():
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids))
    assert set(re.findall(r"\$\('([^']+)'\)", APP)) <= set(ids)
    for target in ('taskDialog', 'settingsDialog', 'agentTabs', 'teamMap', 'needsYou', 'agentSearch'):
        assert target in ids
    assert '<dialog id="taskDialog"' in HTML
    assert '<dialog id="settingsDialog"' in HTML
    assert 'content="dark"' in HTML
    css = (STATIC / 'styles.css').read_text(encoding='utf-8')
    assert 'align-items:safe center' in css
    assert 'min-width:max-content' in css
    assert 'prefers-reduced-motion' in css


def test_cockpit_filter_is_searchable_and_only_flags_real_questions():
    source = re.search(r"function needsHuman\(.*?\n\}", APP, re.S).group()
    result = run_javascript("""
const ui={needsOnly:false};let search='';const $=()=>({value:search});
""" + source + """
const agents=[{id:'pm',name:'PM',status:'waiting',question:'Which team?'},{id:'w',name:'レビュー担当',assignment:'仕様の確認',status:'working'},{id:'q',name:'Queue',status:'queued'}];
search='レビュー';const searched=filteredAgents(agents).map(a=>a.id);
search='仕様の確認';const assignment=filteredAgents(agents).map(a=>a.id);
search='';ui.needsOnly=true;const needed=filteredAgents(agents).map(a=>a.id);
console.log(JSON.stringify({searched,assignment,needed}));
""")
    assert result == {'searched': ['w'], 'assignment': ['w'], 'needed': ['pm']}


def test_dialog_repeated_open_close_preserves_drafts_and_focus():
    source = APP[APP.index('function showView('):APP.index('function filteredAgents(')]
    result = run_javascript("""
const nodes={taskDialog:{open:false,opens:0,closes:0,showModal(){this.open=true;this.opens++},close(){this.open=false;this.closes++}},settingsDialog:{open:false,opens:0,closes:0,showModal(){this.open=true;this.opens++},close(){this.open=false;this.closes++}}};const $=id=>nodes[id];
""" + source + """
const ui={preflightRequest:0};schedulePreflight=()=>{};
setBriefOpen(true);setBriefOpen(true);setBriefOpen(false);setBriefOpen(false);
showView('settings');showView('settings');showView('work');showView('work');
console.log(JSON.stringify(Object.fromEntries(Object.entries(nodes).map(([k,v])=>[k,{open:v.open,opens:v.opens,closes:v.closes}]))));
""")
    assert all(value == {'open': False, 'opens': 1, 'closes': 1} for value in result.values())
    assert 'ui.startingRun=true' in APP and '||ui.startingRun' in APP
    assert 'ui.settingsLocked||ui.settingsSaving' in APP
    assert "window.addEventListener('popstate'" in APP
    assert 'dialog.close()' in APP


def test_poll_restores_same_logical_keyboard_control_and_does_not_steal_other_focus():
    source = re.search(r"function preserveControlFocus\(.*?\n\}", APP, re.S).group()
    result = run_javascript("""
const body={};let calls=0;const replacement={dataset:{focusKey:'agent:pm'},focus(){calls++}};
const document={body,activeElement:{dataset:{focusKey:'agent:pm'}},querySelectorAll:()=>[replacement]};
""" + source + """
preserveControlFocus(()=>{document.activeElement=body});
document.activeElement={dataset:{focusKey:'agent:pm'}};
preserveControlFocus(()=>{document.activeElement={dataset:{},id:'messageInput'}});
console.log(JSON.stringify({calls}));
""")
    assert result['calls'] == 1
    assert 'if(signature===ui.rosterSignature)return' in APP
    assert 'if(signature===ui.mapSignature)return' in APP
    assert 'if(signature===ui.tabsSignature)return' in APP
    assert 'if(signature===ui.runsSignature)return' in APP


def test_truthful_status_labels_never_infer_a_human_question_from_generic_waiting():
    labels = re.search(r"const STATUS_LABELS = .*?;", APP).group()
    reason_labels = re.search(r"const REASON_LABELS = .*?;", APP).group()
    status = re.search(r"function statusLabel\(.*?\}", APP).group()
    state = re.search(r"function stateLabel\(.*?\}", APP).group()
    result = run_javascript(labels + reason_labels + status + state + """
console.log(JSON.stringify(['waiting','human_input','error','collaboration_limit','needs_attention','teammates','teammate_error'].map(reason=>stateLabel({status:'waiting',status_reason:reason}))));
""")
    assert result == ['待機', '回答待ち', 'エラー', '連携上限', '要確認', '作業者待ち', '作業者エラー']
    assert 'agent.task' not in APP
    assert "agent.role==='pm'" not in APP
    assert 'message_eligibility' in APP and 'messageEligibility' in HTML
    assert '開始済み・待機中の作業は続行できます。' not in APP
    assert 'この連携上限だけでは、開始済み・待機中の作業は停止しません。停止したチームは再開できません。' in APP


def test_message_feedback_stays_with_its_selected_agent_and_clears_on_run_change():
    assert "if(ui.selectedAgent===agent.id)inlineStatus($('messageStatus'),'送信しました。')" in APP
    assert "if(ui.selectedAgent===agent.id)inlineStatus($('messageStatus'),errorText(error),true)" in APP
    select = re.search(r"function selectRun\(.*?\n", APP).group()
    assert "inlineStatus($('messageStatus'),'')" in select


OUTPUT_SOURCE = APP[APP.index('function outputRecords('):APP.index('function renderConversation(')]
OUTPUT_DOM = r"""
class Node {
  constructor(tag='div'){this.tag=tag;this.children=[];this.textContent='';this.value='';this.scrollTop=0;this.hidden=false;this.disabled=false;this.className='';this.classList={toggle(){}};}
  appendChild(node){this.children.push(node);return node;}
  replaceChildren(...nodes){this.children=nodes;}
  click(){}
  remove(){}
}
const ids=['resultsPanel','resultsCount','resultSelection','resultMeta','resultText','resultNotice','resultsOmitted','copyResult','exportResult','resultActionStatus'];
const nodes=Object.fromEntries(ids.map(id=>[id,new Node()]));
const $=id=>nodes[id];
const document={createElement:tag=>new Node(tag),body:new Node('body')};
function element(tag,className,text){const node=document.createElement(tag);node.className=className||'';if(text!==undefined)node.textContent=String(text);return node;}
function inlineStatus(node,text,error=false){node.textContent=text;node.error=error;}
function localTime(){return '12:30';}
const ui={selectedRun:'run-a',selectedAgent:'agent-a',outputSelections:new Map(),outputContext:'',outputRequest:0,outputSignature:''};
const agent={id:'agent-a',turns:2,result_revision:3,status:'idle',results:[{id:'r1',source:'assistant_response',text:'<img src=x onerror=alert(1)> 日本語',at:1,turn:2,revision:3,truncated:false}],output_receipts:[{id:'f1',tool:'write_text_file',path:'../unsafe/name.html',bytes:42,sha256:'a'.repeat(64),operation:'created',at:2,turn:2}],results_omitted:4,receipts_omitted:5};
function getAgent(){return agent;}
"""


def test_results_panel_is_explicit_text_only_and_located_above_logs():
    assert HTML.index('id="resultsPanel"') < HTML.index('id="conversationLog"')
    assert '<details id="resultsPanel" class="results-panel" hidden>' in HTML
    assert 'id="resultActionStatus" class="inline-status" role="status" aria-live="polite"' in HTML
    assert "new Blob([text],{type:'text/plain;charset=utf-8'})" in APP
    assert "URL.revokeObjectURL(url)" in APP
    assert "'workbench-save-receipt.txt':'workbench-result.txt'" in APP
    assert "addEventListener('click',copySelectedOutput)" in APP
    assert "addEventListener('click',exportSelectedOutput)" in APP
    assert "fetch(" not in OUTPUT_SOURCE
    assert 'agent.logs' not in OUTPUT_SOURCE and 'ui.config' not in OUTPUT_SOURCE
    assert 'thinking' not in OUTPUT_SOURCE and 'protocol' not in OUTPUT_SOURCE


def test_results_label_history_by_revision_turn_and_in_progress_status():
    result = run_javascript(OUTPUT_DOM + OUTPUT_SOURCE + r"""
const report=agent.results[0];
const current=resultPosition(agent,report);
const states=['queued','working','running','waiting','waiting_human','needs_input','stopping'].map(status=>historicalResult({...agent,status},report));
const revision=historicalResult({...agent,result_revision:4},report);
const turn=historicalResult({...agent,turns:3},report);
console.log(JSON.stringify({current,states,revision,turn,terminal:['idle','done','stopped','error'].map(status=>resultPosition({...agent,status},report))}));
""")
    assert result['current'] == 'このターンの報告'
    assert all(result['states']) and result['revision'] and result['turn']
    assert result['terminal'] == ['このターンの報告'] * 4


def test_results_render_safe_text_preserve_poll_selection_and_scroll_and_explain_limits():
    result = run_javascript(OUTPUT_DOM + OUTPUT_SOURCE + r"""
renderResults(agent);nodes.resultsPanel.open=true;
const first={text:nodes.resultText.textContent,meta:nodes.resultMeta.textContent,notice:nodes.resultNotice.textContent,omissions:nodes.resultsOmitted.textContent,count:nodes.resultsCount.textContent};
nodes.resultText.scrollTop=75;nodes.resultsPanel.scrollTop=20;
agent.results.push({...agent.results[0],id:'r2',text:'new report'});renderResults(agent);
const poll={key:selectedOutput().key,scroll:nodes.resultText.scrollTop,panelScroll:nodes.resultsPanel.scrollTop,open:nodes.resultsPanel.open};
ui.outputSelections.set(outputOwner(),'receipt:f1');renderResults(agent);
const receipt={text:nodes.resultText.textContent,copy:nodes.copyResult.textContent,export:nodes.exportResult.textContent,notice:nodes.resultNotice.textContent,scroll:nodes.resultText.scrollTop};
agent.results=[];agent.output_receipts=[];agent.results_omitted=0;agent.receipts_omitted=0;renderResults(agent);
const empty={copyDisabled:nodes.copyResult.disabled,exportDisabled:nodes.exportResult.disabled,omissionsHidden:nodes.resultsOmitted.hidden,textHidden:nodes.resultText.hidden};
console.log(JSON.stringify({first,poll,receipt,empty}));
""")
    assert result['first']['text'] == '<img src=x onerror=alert(1)> 日本語'
    assert 'assistant_response' in result['first']['meta']
    assert '検証したものではありません' in result['first']['notice']
    assert '古い報告 4 件' in result['first']['omissions'] and '古い保存記録 5 件' in result['first']['omissions']
    assert result['first']['count'] == '報告 1 · 保存 1'
    assert result['poll'] == {'key': 'result:r1', 'scroll': 75, 'panelScroll': 20, 'open': True}
    assert result['receipt']['copy'] == 'パスをコピー'
    assert result['receipt']['export'] == '記録を .txt 保存'
    assert '現在のファイルの存在・内容は未確認' in result['receipt']['notice']
    assert 'ファイル本体のダウンロードはできません' in result['receipt']['notice']
    assert '../unsafe/name.html' in result['receipt']['text'] and 'a' * 64 in result['receipt']['text']
    assert result['receipt']['scroll'] == 0
    assert all(result['empty'].values())


def test_selected_plain_text_export_has_only_public_selected_record_and_fixed_filenames():
    result = run_javascript(OUTPUT_DOM + OUTPUT_SOURCE + r"""
agent.results.push({...agent.results[0],id:'r2',text:'DO NOT EXPORT OTHER RESULT'});
agent.logs=[{thinking:'PRIVATE REASONING',text:'PRIVATE LOG'}];agent.protocol=[{secret:'PRIVATE PROTOCOL'}];ui.config={key:'PRIVATE SETTINGS'};
const captures=[],timers=[],urls=[];let downloads=0;
class Blob {constructor(parts,options){this.parts=parts;this.options=options;captures.push(this);}}
const URL={createObjectURL(){return 'blob:test'},revokeObjectURL(url){urls.push(url)}};
const window={setTimeout(callback,delay){timers.push(delay);callback();}};
document.createElement=tag=>{const node=new Node(tag);node.click=()=>{downloads++;captures.at(-1).filename=node.download};return node};
renderResults(agent);ui.outputSelections.set(outputOwner(),'result:r1');renderResults(agent);exportSelectedOutput();
ui.outputSelections.set(outputOwner(),'receipt:f1');renderResults(agent);exportSelectedOutput();
agent.results[0].truncated=true;agent.result_revision=4;
const historical=exportOutputText(agent,outputRecords(agent).find(item=>item.key==='result:r1'));
console.log(JSON.stringify({captures,timers,urls,downloads,historical,status:nodes.resultActionStatus.textContent}));
""")
    assert result['downloads'] == 2
    assert [item['filename'] for item in result['captures']] == ['workbench-result.txt', 'workbench-save-receipt.txt']
    assert all(item['options'] == {'type': 'text/plain;charset=utf-8'} for item in result['captures'])
    assert result['timers'] == [1000, 1000] and result['urls'] == ['blob:test', 'blob:test']
    report, receipt = [item['parts'][0] for item in result['captures']]
    assert '日本語' in report and 'assistant_response' in report and '検証したものではありません' in report
    assert '../unsafe/name.html' not in report
    assert '../unsafe/name.html' in receipt and '現在のファイルの存在・内容は未確認' in receipt
    assert '日本語' not in receipt
    assert '過去の報告' in result['historical'] and '本文の省略: あり' in result['historical']
    assert not any(forbidden in report + receipt for forbidden in ('PRIVATE', 'DO NOT EXPORT OTHER RESULT'))
    assert 'ダウンロードを開始しました' in result['status']


def test_clipboard_feedback_is_truthful_and_scoped_to_latest_run_agent_record_and_request():
    result = run_javascript(OUTPUT_DOM + OUTPUT_SOURCE + r"""
(async()=>{
 const pending=[],writes=[];
 Object.defineProperty(globalThis,'navigator',{value:{clipboard:{writeText(text){writes.push(text);return new Promise((resolve,reject)=>pending.push({resolve,reject}));}}},configurable:true});
 renderResults(agent);
 const first=copySelectedOutput();const newer=copySelectedOutput();pending[1].resolve();await newer;const newSuccess=nodes.resultActionStatus.textContent;
 pending[0].reject(new Error('late error'));await first;const staleError=nodes.resultActionStatus.textContent;
 const failure=copySelectedOutput();pending[2].reject(new Error('blocked'));await failure;const visibleFailure={text:nodes.resultActionStatus.textContent,error:nodes.resultActionStatus.error};
 const record=copySelectedOutput();ui.outputSelections.set(outputOwner(),'receipt:f1');renderResults(agent);pending[3].resolve();await record;const changedRecord=nodes.resultActionStatus.textContent;
 const path=copySelectedOutput();pending[4].resolve();await path;const pathSuccess=nodes.resultActionStatus.textContent;
 const movedAgent=copySelectedOutput();ui.selectedAgent='agent-b';renderResults(agent);ui.selectedAgent='agent-a';renderResults(agent);pending[5].resolve();await movedAgent;const changedAgent=nodes.resultActionStatus.textContent;
 const movedRun=copySelectedOutput();ui.selectedRun='run-b';renderResults(agent);ui.selectedRun='run-a';renderResults(agent);pending[6].reject(new Error('late'));await movedRun;const changedRun=nodes.resultActionStatus.textContent;
 navigator.clipboard=null;await copySelectedOutput();const unsupported=nodes.resultActionStatus.textContent;
 console.log(JSON.stringify({writes,newSuccess,staleError,visibleFailure,changedRecord,pathSuccess,changedAgent,changedRun,unsupported}));
})();
""")
    assert result['newSuccess'] == result['staleError'] == '本文をコピーしました。'
    assert result['visibleFailure']['error'] is True and 'コピーできませんでした' in result['visibleFailure']['text']
    assert result['changedRecord'] == result['changedAgent'] == result['changedRun'] == ''
    assert result['pathSuccess'] == 'パスをコピーしました。'
    assert result['writes'][4] == '../unsafe/name.html'
    assert 'コピーできませんでした' in result['unsupported']


def test_export_failure_revokes_blob_url_and_cannot_be_overwritten_by_pending_copy():
    result = run_javascript(OUTPUT_DOM + OUTPUT_SOURCE + r"""
(async()=>{
 let resolveCopy;const revoked=[];
 Object.defineProperty(globalThis,'navigator',{value:{clipboard:{writeText(){return new Promise(resolve=>{resolveCopy=resolve})}}},configurable:true});
 const URL={createObjectURL(){return 'blob:failed'},revokeObjectURL(url){revoked.push(url)}};
 const window={setTimeout(callback){callback();}};
 document.createElement=tag=>{const node=new Node(tag);if(tag==='a')node.click=()=>{throw new Error('download failed')};return node;};
 // The production download helper closes over the page's URL/window globals.
 globalThis.URL=URL;globalThis.window=window;
 renderResults(agent);const copy=copySelectedOutput();exportSelectedOutput();const failed=nodes.resultActionStatus.textContent;resolveCopy();await copy;
 console.log(JSON.stringify({failed,after:nodes.resultActionStatus.textContent,error:nodes.resultActionStatus.error,revoked}));
})();
""")
    assert result['failed'] == result['after']
    assert 'ダウンロードを開始できませんでした' in result['failed']
    assert result['error'] is True
    assert result['revoked'] == ['blob:failed']


def test_preflight_deduplicates_native_blur_and_keeps_existing_content():
    source = re.search(r"function schedulePreflight\(\).*?\n\}", APP, re.S).group()
    result = run_javascript("""
const ui={settingsRevision:0,settingsDirty:false,preflightRequest:0,preflightKey:''};
let task='first',scheduled=0,cleared=0;
const nodes={runFormStatus:{textContent:'Previous attempt'},preflightPending:{textContent:''},taskDialog:{open:true},preflightStatus:{textContent:'Existing scope',setAttribute(){}},preflightDetails:{replaceChildren(){throw Error('Preview was cleared during a pointer action')}}};
const $=id=>nodes[id];const runPayload=()=>({task});
const clearTimeout=()=>{cleared++};const setTimeout=()=>{scheduled++;return scheduled};
const inlineStatus=(node,text)=>{if(node!==nodes.runFormStatus)throw Error('Existing guidance should remain stable while pending');node.textContent=text};
""" + source + """
schedulePreflight();schedulePreflight(); // input, then native change on blur
const deduplicated=scheduled===1&&ui.preflightRequest===1;
task='second';schedulePreflight();ui.settingsRevision++;schedulePreflight();
nodes.taskDialog.open=false;schedulePreflight();
console.log(JSON.stringify({deduplicated,scheduled,cleared,request:ui.preflightRequest}));
""")
    assert result == {'deduplicated': True, 'scheduled': 3, 'cleared': 3, 'request': 3}
    assert "details.open=scopeOpen" in APP
    assert "ui.preflightKey=''" in APP


def test_preflight_render_waits_for_native_start_pointer_release_only():
    source = APP[APP.index('async function settleStartPointer('):APP.index('async function refreshPreflight(')]
    result = run_javascript("""
const ui={startPointerActive:true,startPointerWaiters:[]};const callbacks=[];
const window={setTimeout:callback=>callbacks.push(callback)};
""" + source + """
(async()=>{
let rendered=false;const waiting=settleStartPointer().then(()=>{rendered=true});
await Promise.resolve();const held=!rendered&&ui.startPointerWaiters.length===1;
releaseStartPointer();const beforeDefaultAction=!rendered&&ui.startPointerActive;
callbacks.shift()();await waiting;
console.log(JSON.stringify({held,beforeDefaultAction,rendered,active:ui.startPointerActive,waiters:ui.startPointerWaiters.length}));
})();
""")
    assert result == {'held': True, 'beforeDefaultAction': True, 'rendered': True, 'active': False, 'waiters': 0}
    assert '.submit(' not in source and 'requestSubmit(' not in source
