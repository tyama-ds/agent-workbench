"""Behavioral compact-state polling and selection tests with deferred transport."""
from test_frontend import APP, run_javascript


DOM = r"""
const assert=require('node:assert/strict');
class Node {
  constructor(tag='div') {
    this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};
    this.textContent='';this.value='';this.hidden=false;this.disabled=false;this.open=false;
    this.scrollTop=0;this.scrollHeight=800;this.clientHeight=200;this.className='';
    this.classes=new Set();this.classList={
      toggle:(name,force)=>{if(force===undefined)force=!this.classes.has(name);if(force)this.classes.add(name);else this.classes.delete(name);},
      add:(...names)=>names.forEach(name=>this.classes.add(name)),
      remove:(...names)=>names.forEach(name=>this.classes.delete(name)),contains:name=>this.classes.has(name)};
  }
  append(...nodes){this.children.push(...nodes);}
  appendChild(node){this.append(node);return node;}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=String(value);}
  getAttribute(key){return this.attributes[key]??null;}
  addEventListener(){}
  showModal(){this.open=true;}
  close(){this.open=false;}
  focus(){document.activeElement=this;}
  querySelectorAll(selector){
    const all=this.children.flatMap(node=>[node,...node.querySelectorAll('*')]);
    if(selector==='*')return all;
    if(selector==='details[open]')return all.filter(node=>node.tagName==='DETAILS'&&node.open);
    if(selector==='[data-focus-key]')return all.filter(node=>node.dataset.focusKey);
    return [];
  }
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  click(){}
  remove(){}
}
const nodes=new Map();
const document={body:new Node('body'),activeElement:null,addEventListener(){},
  createElement:tag=>new Node(tag),getElementById(id){if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);},
  querySelector(selector){return this.getElementById(selector);},
  querySelectorAll(selector){return [...nodes.values()].flatMap(node=>node.querySelectorAll(selector));}};
document.activeElement=document.body;
const window={setTimeout,clearTimeout,setInterval(){},addEventListener(){}};
"""


FIXTURES = r"""
const runs=[
  {id:'run-a',task:'First task',status:'running',created_at:1,agent_ids:['agent-a','agent-b'],max_workers:2},
  {id:'run-b',task:'Second task',status:'running',created_at:2,agent_ids:['agent-c'],max_workers:0}];
const summaries=[
  {id:'agent-a',run_id:'run-a',name:'PM A',parent_id:null},
  {id:'agent-b',run_id:'run-a',name:'Worker B',parent_id:'agent-a'},
  {id:'agent-c',run_id:'run-b',name:'PM C',parent_id:null},
].map(agent=>({...agent,profile_id:'local',configured_profile:{id:'local',label:'Original fixture '+agent.id,kind:'local',model:'configured-'+agent.id},assignment:'Visible assignment',status:'done',status_reason:'done',
  question:'',last_error:'',turns:1,result_revision:1,results_omitted:0,receipts_omitted:0,
  message_eligibility:{allowed:true,reason:'',message:''}}));
function details(agent,marker='current') {
  return {logs:[{id:`log-${agent.id}`,kind:'assistant',text:`${marker} log ${agent.id}`,thinking:`Reasoning ${agent.id}`,at:1}],
    results:[{id:`result-${agent.id}`,source:'assistant_response',text:`${marker} result ${agent.id}`,at:1,turn:1,revision:1}],
    output_receipts:[{id:`receipt-${agent.id}`,tool:'write_text',path:`${agent.id}.txt`,bytes:10,sha256:'a'.repeat(64),operation:'created',at:1,turn:1}]};
}
function fullState(marker='current') {
  return {runs:structuredClone(runs),agents:summaries.map(agent=>({...structuredClone(agent),...details(agent,marker)})),
    events:runs.map(run=>({id:run.id,run_id:run.id,kind:'mail',text:`${marker} event ${run.id}`,at:1})),resources:{active:1,queued:0}};
}
function compactState(runId,agentId,marker='current') {
  const state=fullState(marker);
  state.agents=state.agents.map(agent=>agent.id===agentId?agent:((({logs,results,output_receipts,...summary})=>summary)(agent)));
  state.events=state.events.filter(event=>event.run_id===runId);
  state.selection={run_id:runId,agent_id:agentId,detail_loaded:agentId!==null};
  return state;
}
function seedSelection() {
  ui.authenticated=true;ui.state=fullState('seed');ui.selectedRun='run-a';ui.selectedAgent='agent-a';renderState();
}
const requests=[];let inFlight=0,maxInFlight=0;
api=(path)=>{
  inFlight++;maxInFlight=Math.max(maxInFlight,inFlight);
  return new Promise((resolve,reject)=>requests.push({path,resolve(value){inFlight--;resolve(value);},reject(error){inFlight--;reject(error);}}));
};
const flush=async()=>{for(let index=0;index<20;index++)await Promise.resolve();};
function selectionOf(request){const url=new URL(request.path,'http://local.test');return Object.fromEntries(url.searchParams);}
function renderedText(node){return [node.textContent,...node.children.map(renderedText)].join('\n');}
async function loadInitialSelection() {
  seedSelection();const pending=pollState();assert.equal(requests.length,1);
  requests[0].resolve(compactState('run-a','agent-a'));await pending;
  assert.equal(selectedOutput().record.text,'current result agent-a');
}
"""


def check_behavior(source):
    result = run_javascript(DOM + APP + FIXTURES + "\n(async()=>{\n" + source + r"""
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
""")
    assert result == {'ok': True}


def test_compact_query_bootstrap_drains_to_selected_detail_without_overlap():
    check_behavior(r"""
ui.authenticated=true;
const pending=pollState();
assert.deepEqual(selectionOf(requests[0]),{view:'selected'});
requests[0].resolve(compactState(null,null));await flush();
assert.equal(requests.length,2);
assert.deepEqual(selectionOf(requests[1]),{view:'selected',run_id:'run-b',agent_id:'agent-c'});
assert.equal(ui.selectedRun,'run-b');assert.equal(ui.selectedAgent,'agent-c');
assert.equal(selectedOutput(),null);assert.equal($('copyResult').disabled,true);
requests[1].resolve(compactState('run-b','agent-c'));await pending;
assert.equal(selectedOutput().record.text,'current result agent-c');
assert.equal(ui.polling,false);assert.equal(inFlight,0);assert.equal(maxInFlight,1);
""")


def test_single_flight_polls_coalesce_and_fresh_requests_drain_once():
    check_behavior(r"""
await loadInitialSelection();
const first=pollState(),ordinary=pollState(),fresh=pollState(true),alsoFresh=pollState(true);
assert.equal(requests.length,2);assert.equal(maxInFlight,1);
requests[1].resolve(compactState('run-a','agent-a','first'));await flush();
assert.equal(requests.length,3);assert.equal(inFlight,1);
requests[2].resolve(compactState('run-a','agent-a','fresh'));await Promise.all([first,ordinary,fresh,alsoFresh]);
assert.equal(requests.length,3);assert.equal(maxInFlight,1);assert.equal(inFlight,0);assert.equal(ui.polling,false);
assert.equal(selectedOutput().record.text,'fresh result agent-a');
""")


def test_selection_generation_rejects_stale_a_response_after_a_b_a():
    check_behavior(r"""
await loadInitialSelection();
const generation=ui.selectionGeneration;
$('messageInput').value='Exact A draft';
const pending=pollState();selectAgent('agent-b');$('messageInput').value='Exact B draft';selectAgent('agent-a');
assert.equal(ui.selectionGeneration,generation+2);assert.equal(requests.length,2);
assert.equal($('messageInput').value,'Exact A draft');assert.equal(ui.drafts.get('agent-b'),'Exact B draft');
assert.equal(selectedOutput(),null);assert.equal($('resultText').textContent,'');
const stateBeforeStale=JSON.stringify(ui.state);
const stale=compactState('run-a','agent-a','STALE');stale.agents[0].configured_profile.model='WRONG-STALE-MODEL';
requests[1].resolve(stale);await flush();
assert.equal(requests.length,3);assert.deepEqual(selectionOf(requests[2]),{view:'selected',run_id:'run-a',agent_id:'agent-a'});
assert.equal(selectedOutput(),null);
assert.equal(JSON.stringify(ui.state),stateBeforeStale);
assert.ok(!renderedText($('conversationLog')).includes('STALE'));
assert.ok(!renderedText($('activityFeed')).includes('STALE'));
assert.ok(!$('conversationProfile').textContent.includes('WRONG-STALE-MODEL'));
requests[2].resolve(compactState('run-a','agent-a','LATEST'));await pending;
assert.equal(selectedOutput().record.text,'LATEST result agent-a');assert.equal(maxInFlight,1);
assert.equal($('messageInput').value,'Exact A draft');
const exported=exportOutputText(getAgent(),selectedOutput());
assert.ok(exported.includes('作業 ID: run-a'));assert.ok(exported.includes('エージェント ID: agent-a'));
assert.ok(exported.includes('開始時のモデル設定: "configured-agent-a"'));assert.ok(!exported.includes('WRONG-STALE-MODEL'));
""")


def test_missing_detail_shows_loading_preserves_output_choice_and_blocks_actions():
    check_behavior(r"""
await loadInitialSelection();
const aOwner=outputOwner();ui.outputSelections.set(aOwner,'receipt:receipt-agent-a');renderResults(getAgent());
assert.equal(selectedOutput().kind,'receipt');
const bOwner=JSON.stringify(['run-a','agent-b']);ui.outputSelections.set(bOwner,'receipt:receipt-agent-b');
selectAgent('agent-b');
assert.equal(requests.length,2);assert.equal(selectedOutput(),null);
assert.equal(ui.outputSelections.get(aOwner),'receipt:receipt-agent-a');
assert.equal(ui.outputSelections.get(bOwner),'receipt:receipt-agent-b');
assert.equal($('copyResult').disabled,true);assert.equal($('exportResult').disabled,true);
assert.equal($('resultText').textContent,'');assert.ok($('resultsCount').textContent.includes('読み込み'));
assert.ok(!renderedText($('conversationLog')).includes('まだログはありません'));
let copied=0,exported=0;
Object.defineProperty(globalThis,'navigator',{value:{clipboard:{writeText(){copied++;return Promise.resolve();}}},configurable:true});
downloadPlainText=()=>exported++;
await copySelectedOutput();exportSelectedOutput();assert.equal(copied,0);assert.equal(exported,0);
requests[1].resolve(compactState('run-a','agent-b'));await ui.pollPromise;
assert.equal(selectedOutput().key,'receipt:receipt-agent-b');assert.equal($('copyResult').disabled,false);
assert.equal(ui.outputSelections.get(aOwner),'receipt:receipt-agent-a');
""")


def test_same_selection_network_error_retains_last_good_detail_and_view_state():
    check_behavior(r"""
await loadInitialSelection();
ui.outputSelections.set(outputOwner(),'receipt:receipt-agent-a');renderResults(getAgent());
$('messageInput').value='Unsent draft';$('resultText').scrollTop=73;$('resultsPanel').open=true;
$('conversationLog').scrollTop=94;const reasoning=$('conversationLog').querySelectorAll('*').find(node=>node.tagName==='DETAILS');reasoning.open=true;
const state=JSON.stringify(ui.state),pending=pollState();requests[1].reject(new Error('temporary failure'));await pending;
assert.equal(JSON.stringify(ui.state),state);assert.equal(selectedOutput().key,'receipt:receipt-agent-a');
assert.equal($('copyResult').disabled,false);assert.equal($('messageInput').value,'Unsent draft');
assert.equal($('resultText').scrollTop,73);assert.equal($('resultsPanel').open,true);
assert.equal($('conversationLog').scrollTop,94);assert.equal(reasoning.open,true);
assert.ok($('connectionStatus').textContent.includes('接続'));
const retry=pollState();requests[2].resolve(compactState('run-a','agent-a','recovered'));await retry;
assert.equal(selectedOutput().key,'receipt:receipt-agent-a');assert.equal(ui.polling,false);
""")


def test_selection_change_during_failed_request_still_drains_latest_target():
    check_behavior(r"""
await loadInitialSelection();
const pending=pollState();selectRun('run-b');
assert.equal(ui.selectedRun,'run-b');assert.equal(ui.selectedAgent,'agent-c');assert.equal(selectedOutput(),null);
requests[1].reject(new Error('old request failed'));await flush();
assert.equal(requests.length,3);assert.deepEqual(selectionOf(requests[2]),{view:'selected',run_id:'run-b',agent_id:'agent-c'});
requests[2].resolve(compactState('run-b','agent-c'));await pending;
assert.equal(selectedOutput().record.text,'current result agent-c');assert.equal(maxInFlight,1);
assert.ok(!renderedText($('activityFeed')).includes('run-a'));
""")


def test_malformed_compact_selection_is_rejected_without_overwriting_good_state():
    check_behavior(r"""
await loadInitialSelection();
const mutations=[
  state=>state.selection=null,
  state=>delete state.selection.agent_id,
  state=>state.selection.run_id='run-b',
  state=>state.selection.agent_id='agent-b',
  state=>state.selection.detail_loaded='true',
  state=>state.selection.detail_loaded=false,
  state=>delete state.agents[0].logs,
  state=>state.agents[0].results={},
  state=>state.agents[0].output_receipts=null,
];
for(const mutate of mutations){
  const before=JSON.stringify(ui.state),response=compactState('run-a','agent-a','MALFORMED');mutate(response);
  const request=pollState();requests.at(-1).resolve(response);await request;
  assert.equal(JSON.stringify(ui.state),before);assert.equal(selectedOutput().record.text,'current result agent-a');
  assert.ok(!renderedText($('conversationLog')).includes('MALFORMED'));
}
assert.equal(maxInFlight,1);
""")


def test_full_fixture_without_selection_metadata_remains_compatible():
    check_behavior(r"""
seedSelection();const pending=pollState();requests[0].resolve(fullState('legacy'));await pending;
assert.equal(selectedOutput().record.text,'legacy result agent-a');
assert.equal($('copyResult').disabled,false);assert.ok(renderedText($('conversationLog')).includes('legacy log agent-a'));
assert.ok(renderedText($('activityFeed')).includes('legacy event run-a'));
assert.ok(!renderedText($('activityFeed')).includes('legacy event run-b'));
assert.equal(ui.polling,false);
""")


def test_summary_metadata_requires_explicit_null_ids_before_selection():
    check_behavior(r"""
const before=JSON.stringify(ui.state),request={run:null,agent:null,generation:0};
for(const missing of ['run_id','agent_id','detail_loaded']) {
  const response=compactState(null,null);delete response.selection[missing];
  assert.throws(()=>applyState(response,request));assert.equal(JSON.stringify(ui.state),before);
}
applyState(compactState(null,null),request);
assert.equal(ui.compactState,true);assert.equal(ui.loadedDetail,null);
""")


def test_lost_auth_stops_queued_selection_drain_without_retrying():
    check_behavior(r"""
await loadInitialSelection();
const pending=pollState();selectAgent('agent-b');
ui.authenticated=false;requests[1].reject(new Error('authentication expired'));await pending;
assert.equal(requests.length,2);assert.equal(inFlight,0);assert.equal(ui.polling,false);
assert.equal(selectedOutput(),null);assert.equal($('copyResult').disabled,true);
await pollState(true);assert.equal(requests.length,2);
""")


def test_empty_run_requests_activity_without_inventing_an_agent_or_empty_detail():
    check_behavior(r"""
ui.authenticated=true;ui.selectedRun='empty-run';
ui.state={runs:[{id:'empty-run',task:'Empty team',status:'done',agent_ids:[]}],agents:[],events:[],resources:{}};
renderState();const pending=pollState();
assert.deepEqual(selectionOf(requests[0]),{view:'selected',run_id:'empty-run'});
requests[0].resolve({...ui.state,events:[{id:1,run_id:'empty-run',kind:'done',text:'Known activity'}],
  selection:{run_id:'empty-run',agent_id:null,detail_loaded:false}});await pending;
assert.equal(ui.selectedAgent,null);assert.equal(selectedOutput(),null);assert.equal($('resultsPanel').hidden,true);
assert.ok(renderedText($('activityFeed')).includes('Known activity'));
assert.equal(requests.length,1);assert.equal(ui.polling,false);
""")


def test_failed_new_selection_keeps_loading_state_and_saved_output_choice_until_retry():
    check_behavior(r"""
await loadInitialSelection();
const owner=JSON.stringify(['run-a','agent-b']);ui.outputSelections.set(owner,'receipt:receipt-agent-b');
selectAgent('agent-b');requests[1].reject(new Error('temporary failure'));await ui.pollPromise;
assert.equal(ui.outputSelections.get(owner),'receipt:receipt-agent-b');assert.equal(selectedOutput(),null);
assert.equal($('copyResult').disabled,true);assert.equal($('resultText').textContent,'');
assert.equal($('detailStatus').hidden,false);assert.ok($('detailStatus').textContent.includes('取得できません'));
assert.ok(!renderedText($('conversationLog')).includes('まだログはありません'));
const retry=pollState();requests[2].resolve(compactState('run-a','agent-b'));await retry;
assert.equal(selectedOutput().key,'receipt:receipt-agent-b');assert.equal($('detailStatus').hidden,true);
""")


def test_returning_to_agent_restores_draft_log_scroll_and_expanded_reasoning():
    check_behavior(r"""
await loadInitialSelection();
$('messageInput').value='Keep this draft';$('conversationLog').scrollTop=88;
$('conversationLog').querySelectorAll('*').find(node=>node.tagName==='DETAILS').open=true;
selectAgent('agent-b');requests[1].resolve(compactState('run-a','agent-b'));await ui.pollPromise;
selectAgent('agent-a');requests[2].resolve(compactState('run-a','agent-a'));await ui.pollPromise;
assert.equal($('messageInput').value,'Keep this draft');assert.equal($('conversationLog').scrollTop,88);
assert.equal($('conversationLog').querySelectorAll('*').find(node=>node.tagName==='DETAILS').open,true);
""")


def test_pending_clipboard_feedback_cannot_attach_after_selection_generation_changes():
    check_behavior(r"""
await loadInitialSelection();
let finishCopy;Object.defineProperty(globalThis,'navigator',{value:{clipboard:{writeText(){return new Promise(resolve=>finishCopy=resolve);}}},configurable:true});
const copying=copySelectedOutput();selectAgent('agent-b');selectAgent('agent-a');
requests[1].resolve(compactState('run-a','agent-b'));await flush();
requests[2].resolve(compactState('run-a','agent-a'));await ui.pollPromise;
finishCopy();await copying;assert.equal($('resultActionStatus').textContent,'');
""")
