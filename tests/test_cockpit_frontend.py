"""Cockpit contracts with production callbacks and synthetic DOM only.

Prepared without execution while the independent matrix trial is running.
These checks do not establish native layout, screen-reader or browser behavior.
"""
from pathlib import Path

import pytest

from test_frontend import APP, HTML, run_javascript
from test_run_action_frontend import ACTION_DOM
from test_compact_frontend import FIXTURES
from test_task_guidance import Elements


FOCUS = r'''
Node.prototype.contains=function(target){return this===target||this.children.some(node=>node.contains(target));};
Node.prototype.append=function(...items){for(const node of items){node.parentElement=this;this.children.push(node);}};
Node.prototype.replaceChildren=function(...items){
 if(this.children.some(node=>node.contains(document.activeElement)))document.activeElement=document.body;
 this.children=[];this.append(...items);
};
window.matchMedia=()=>({matches:false});
// Send the shared synthetic full state through the production acceptance path.
const originalNetworkSeed=seedSelection;
seedSelection=()=>{originalNetworkSeed();applyState({...ui.state,...(ui.instanceId?{instance_id:ui.instanceId}:{})},{run:ui.selectedRun,agent:ui.selectedAgent});renderNetworkPreview();};
function namedAgent(id){return ui.state.agents.find(agent=>agent.id===id);}
function mail(id,from='agent-a',to='agent-b',extra={}){
 return {id,run_id:'run-a',kind:'mail',mail_id:`m${id}`,from_agent_id:from,to_agent_id:to,
  from:from,to:to,text:`message ${id}`,subject:`subject ${id}`,message_type:'peer_message',delivery_state:'queued',at:id,...extra};
}
'''


def check(source):
    result = run_javascript(ACTION_DOM + APP + FIXTURES + FOCUS + '\n(async()=>{\n' + source + r'''
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_network_owns_central_stage_and_existing_detail_ids_move_together():
    tree = Elements()
    for ident in ('teamMap', 'activityFeed'):
        assert any(node['attrs'].get('id') == 'main' for node in tree.ids[ident]['ancestors'])
    for ident in ('agentTabs', 'conversationLog', 'resultsPanel', 'humanQuestion', 'messageForm', 'messageInput'):
        assert any(node['attrs'].get('id') == 'agentInspector' for node in tree.ids[ident]['ancestors'])
    assert tree.ids['teamMap']['attrs']['tabindex'] == '0'
    assert tree.ids['networkView']['attrs']['aria-controls'] == 'main'
    assert tree.ids['inspectorView']['attrs']['aria-controls'] == 'agentInspector'
    assert HTML.count('id="messageInput"') == HTML.count('id="conversationLog"') == 1


def test_native_local_assets_and_reduced_motion_contract():
    css = (Path(__file__).resolve().parents[1] / 'static/styles.css').read_text(encoding='utf-8')
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert '.network-node{transition:none}' in css
    assert '.network-mail-line' in css and 'stroke-dasharray:6 5' in css
    assert 'Math.random' not in APP and 'setInterval(()=>renderTeamMap' not in APP
    assert '<iframe' not in HTML and 'https://agentstack' not in HTML


def test_layout_is_deterministic_and_uses_parent_ids_even_for_misleading_role():
    check(r'''
const agents=[{id:'p',parent_id:null},{id:'w',parent_id:'p',role:'pm'},
 {id:'q',parent_id:null},{id:'v',parent_id:'q'},{id:'cycle1',parent_id:'cycle2'},{id:'cycle2',parent_id:'cycle1'}];
const a=networkLayout(agents),b=networkLayout(agents);
assert.deepEqual([...a.positions],[...b.positions]);assert.equal(a.positions.size,agents.length);
assert(a.positions.get('w').y>a.positions.get('p').y);assert(a.positions.get('v').y>a.positions.get('q').y);
assert.equal(NETWORK_NODE_SIZE,112);assert.equal(NETWORK_NODE_RADIUS,56);
for(const position of a.positions.values())assert(position.x+NETWORK_NODE_SIZE<a.width);
''')


def test_network_positions_use_cssom_without_csp_blocked_style_attributes():
    check(r'''
const originalSetAttribute=Node.prototype.setAttribute;
Node.prototype.setAttribute=function(name,value){
 assert.notEqual(name,'style','Strict CSP blocks style attributes; set individual CSSOM properties');
 return originalSetAttribute.call(this,name,value);
};
seedSelection();
const agents=ui.state.agents.filter(agent=>agent.run_id==='run-a'),layout=networkLayout(agents);
const canvas=$('teamMap').children[0];
assert.equal(canvas.style.width,`${layout.width}px`);assert.equal(canvas.style.height,`${layout.height}px`);
for(const agent of agents){
 const button=ui.networkNodes.get(agent.id).button,position=layout.positions.get(agent.id);
 assert.equal(button.style.left,`${position.x}px`);assert.equal(button.style.top,`${position.y}px`);
}
assert.notDeepEqual(ui.networkNodes.get('agent-a').button.style,ui.networkNodes.get('agent-b').button.style);
''')


@pytest.mark.parametrize('count', range(1, 9))
def test_each_pm_final_worker_row_is_centered_and_cards_do_not_overlap(count):
    check(f'const count={count};\n' + r'''
const agents=['p','q'].flatMap(pm=>[{id:pm,parent_id:null},...Array.from({length:count},(_,i)=>({id:`${pm}-${i}`,parent_id:pm}))]);
const layout=networkLayout(agents);
for(const pm of ['p','q']){
 const parent=layout.positions.get(pm),rows=new Map();
 for(let i=0;i<count;i++){const p=layout.positions.get(`${pm}-${i}`);if(!rows.has(p.y))rows.set(p.y,[]);rows.get(p.y).push(p);}
 assert.equal(rows.size,Math.ceil(count/3));
 for(const [y,points] of rows){
  assert(y>parent.y+NETWORK_NODE_SIZE);assert.equal((points[0].x+points.at(-1).x+NETWORK_NODE_SIZE)/2,parent.x+NETWORK_NODE_RADIUS);
  for(let i=0;i<points.length;i++){assert(points[i].x>=0&&points[i].x+NETWORK_NODE_SIZE<layout.width);if(i)assert(points[i].x-points[i-1].x>=NETWORK_NODE_SIZE+24);}
 }
}
assert(layout.positions.get('q').y>layout.positions.get(`p-${count-1}`).y+NETWORK_NODE_SIZE);
''')


def test_centered_card_parent_and_mail_edges_share_actual_coordinates():
    check(r'''
seedSelection();
const agents=[{id:'pm',run_id:'run-a',parent_id:null,name:'PM'},...Array.from({length:5},(_,i)=>({id:`w${i}`,run_id:'run-a',parent_id:'pm',name:`W${i}`}))];
ui.state.agents=agents;renderTeamMap(agents);
const layout=ui.networkLayout,canvas=$('teamMap').children[0],svg=canvas.children[0];
const edges=svg.children.filter(node=>node.getAttribute('class')==='network-parent-line');
assert.equal(edges.length,5);
agents.slice(1).forEach((agent,index)=>{
 const parent=layout.positions.get('pm'),point=layout.positions.get(agent.id),v=edges[index].getAttribute('d').match(/-?\d+(?:\.\d+)?/g).map(Number);
 const a=networkNodeCenter(parent),b=networkNodeCenter(point);
 assert(Math.abs(Math.hypot(v[0]-a.x,v[1]-a.y)-NETWORK_NODE_RADIUS)<.01);
 assert(Math.abs(Math.hypot(v[6]-b.x,v[7]-b.y)-NETWORK_NODE_RADIUS)<.01);
 assert.equal(edges[index].getAttribute('d'),networkLinkGeometry(parent,point,0,true).path);
 assert.equal(ui.networkNodes.get(agent.id).button.style.left,`${point.x}px`);
});
const a=layout.positions.get('w3'),b=layout.positions.get('w4'),mail=networkMailPath(a,b,0).match(/-?\d+(?:\.\d+)?/g).map(Number);
const ac=networkNodeCenter(a),bc=networkNodeCenter(b);
assert(Math.abs(Math.hypot(mail[0]-ac.x,mail[1]-ac.y)-NETWORK_NODE_RADIUS)<.01);
assert(Math.abs(Math.hypot(mail[6]-bc.x,mail[7]-bc.y)-NETWORK_NODE_RADIUS)<.01);
''')


def test_mail_directions_require_real_scoped_ids_and_never_guess_names():
    check(r'''
seedSelection();const agents=ui.state.agents.filter(a=>a.run_id==='run-a');
const legacy={kind:'mail',from:'PM A',to:'Worker B',text:'legacy'};
const rows=[legacy,mail(1),mail(2),mail(3,'agent-b','agent-a'),mail(4,'agent-c','agent-a'),
 mail(5,'agent-a','agent-a'),mail(6,'agent-b','agent-a',{kind:'mail_consumed',delivery_state:'context_consumed'})];
assert.deepEqual(currentMailLinks(agents,rows),[{from:'agent-a',to:'agent-b',stage:'queued',queued:2,consumed:0},{from:'agent-b',to:'agent-a',stage:'consumed',queued:1,consumed:1}]);
ui.state.events=[mail(1),{...mail(2),run_id:'run-b'}];assert.equal(retainedTeamEvents(getRun()).length,1);
ui.compactState=true;ui.loadedEventsRun='run-b';assert.deepEqual(retainedTeamEvents(getRun()),[]);
''')


def test_waiting_count_excludes_human_questions_without_hiding_them():
    check(r'''
seedSelection();namedAgent('agent-a').status='waiting';namedAgent('agent-a').status_reason='human_input';namedAgent('agent-a').question='Please decide';
namedAgent('agent-b').status='waiting';namedAgent('agent-b').status_reason='teammates';renderRun();
assert.equal($('networkCounts').textContent,'作業中 0  /  待機 1  /  要回答 1');
assert.match(ui.networkNodes.get('agent-a').button.className,/human-input/);
''')


@pytest.mark.parametrize('route', ['siblings_forward', 'siblings_reverse', 'different_rows'])
def test_mail_curve_is_outside_sibling_cards_and_inside_viewbox(route):
    from_point, to_point = {
        'siblings_forward': ('{x:36,y:356}', '{x:524,y:356}'),
        'siblings_reverse': ('{x:524,y:356}', '{x:36,y:356}'),
        'different_rows': ('{x:524,y:204}', '{x:280,y:32}'),
    }[route]
    check(f'const from={from_point},to={to_point};\n' + r'''
const values=networkMailPath(from,to,2).match(/-?\d+(?:\.\d+)?/g).map(Number);
assert.equal(values.length,8);for(let i=0;i<8;i+=2)assert(values[i]>=0&&values[i]<840);
for(let i=1;i<8;i+=2)assert(values[i]>=0);
const a=networkNodeCenter(from),b=networkNodeCenter(to);
assert(Math.abs(Math.hypot(values[0]-a.x,values[1]-a.y)-NETWORK_NODE_RADIUS)<.01);
assert(Math.abs(Math.hypot(values[6]-b.x,values[7]-b.y)-NETWORK_NODE_RADIUS)<.01);
for(let i=1;i<20;i++){const t=i/20,s=1-t,x=s*s*s*values[0]+3*s*s*t*values[2]+3*s*t*t*values[4]+t*t*t*values[6],y=s*s*s*values[1]+3*s*s*t*values[3]+3*s*t*t*values[5]+t*t*t*values[7];
 assert(Math.hypot(x-a.x,y-a.y)>=NETWORK_NODE_RADIUS-.01);assert(Math.hypot(x-b.x,y-b.y)>=NETWORK_NODE_RADIUS-.01);
}
''')


def test_poll_updates_existing_nodes_without_recreating_listeners_or_scroll():
    check(r'''
seedSelection();const before=ui.networkNodes.get('agent-b').button,listener=before.listeners.click;
$('teamMap').scrollTop=145;before.focus();
namedAgent('agent-b').status='working';namedAgent('agent-b').activity={latest_log:{kind:'tool',text:'Reading actual.txt',at:9}};
renderRun();assert.equal(ui.networkNodes.get('agent-b').button,before);assert.equal(before.listeners.click,listener);
assert.equal(document.activeElement,before);assert.equal($('teamMap').scrollTop,145);
ui.networkHoverAgent='agent-b';renderNetworkPreview();
assert.match($('networkPreviewLatest').textContent,/Reading actual.txt/);assert.match(before.getAttribute('aria-label'),/作業中/);
''')


@pytest.mark.parametrize('focus', ['node', 'composer'])
def test_topology_change_preserves_existing_focus_and_human_draft(focus):
    check(r'''
seedSelection();$('messageInput').value='unsent human draft';saveAgentDraft({type:'input'});
const composer=$('messageInput');
''' + ("ui.networkNodes.get('agent-b').button.focus();" if focus == 'node' else 'composer.focus();') + r'''
ui.state.agents.push({...summaries[1],id:'new-worker',name:'New worker'});renderRun();
assert.equal($('messageInput'),composer);assert.equal(composer.value,'unsent human draft');
assert.equal(ui.drafts.get('agent-a'),'unsent human draft');
''' + ("assert.equal(document.activeElement,ui.networkNodes.get('agent-b').button);" if focus == 'node' else 'assert.equal(document.activeElement,composer);'))


def test_native_node_click_selects_agent_and_requests_only_its_owned_detail():
    check(r'''
initializeNetworkControls();seedSelection();$('messageInput').value='PM draft';saveAgentDraft({type:'input'});
ui.networkNodes.get('agent-b').button.listeners.click();assert.equal(ui.selectedAgent,'agent-a');
assert.equal(networkViewState().pinnedAgent,'agent-b');assert.equal(requests.length,0);
$('networkPreviewOpen').listeners.click();assert.equal(ui.selectedAgent,'agent-b');
assert.equal(requests.length,1);assert.deepEqual(selectionOf(requests[0]),{view:'selected',run_id:'run-a',agent_id:'agent-b'});
requests[0].resolve(compactState('run-a','agent-b'));await flush();
assert.equal(ui.drafts.get('agent-a'),'PM draft');assert.equal(selectedOutput().record.text,'current result agent-b');
''')


def test_view_toggle_preserves_nodes_drafts_and_selection_without_requests():
    check(r'''
seedSelection();const log=$('conversationLog'),composer=$('messageInput'),generation=ui.selectionGeneration;
composer.value='日本語 composition';composer.focus();
setCockpitView('inspector');setCockpitView('network');
assert.equal($('conversationLog'),log);assert.equal($('messageInput'),composer);assert.equal(composer.value,'日本語 composition');
assert.equal(ui.selectionGeneration,generation);assert.equal(requests.length,0);
assert.equal($('networkView').getAttribute('aria-pressed'),'true');
window.matchMedia=()=>({matches:true});revealInspector();assert.equal(ui.cockpitView,'inspector');
''')


@pytest.mark.parametrize('navigation', ['question', 'draft'])
def test_cross_team_question_and_draft_navigation_reveals_narrow_inspector(navigation):
    check(r'''
seedSelection();window.matchMedia=()=>({matches:true});setCockpitView('network');
namedAgent('agent-c').status='waiting';namedAgent('agent-c').status_reason='human_input';namedAgent('agent-c').question='Exact human question';
ui.drafts.set('agent-c','Existing answer draft');
''' + ("openQuestion('agent-c');" if navigation == 'question' else 'openNextMessageInput();') + r'''
assert.equal(ui.cockpitView,'inspector');assert.equal(ui.selectedAgent,'agent-c');
assert.equal($('messageInput').value,'Existing answer draft');assert.equal(requests.length,1);
''' + ("assert.equal(document.activeElement,$('humanQuestion'));" if navigation == 'question' else "assert.equal(document.activeElement,$('messageInput'));") + r'''
requests[0].resolve(compactState('run-b','agent-c'));await flush();
''')


def test_inspector_reports_records_without_claiming_current_work_or_file_existence():
    check(r'''
seedSelection();const agent=getAgent();agent.assignment='<img src=x onerror=alert(1)> literal';agent.last_error='saved error';
agent.activity={latest_log:{kind:'tool',text:'actual earlier read',at:3},pending_count:2,result_count:5,output_receipt_count:4};
renderConversation(agent);assert.equal($('inspectorAssignment').textContent,agent.assignment);
assert.equal($('inspectorAssignment').children.length,0);assert.match($('inspectorCounts').textContent,/待機入力 2 · 報告 5 · 保存 4/);
assert.match($('inspectorLatest').textContent,/actual earlier read/);assert.equal($('inspectorError').hidden,false);
delete agent.activity;renderConversation(agent);assert.match($('inspectorCounts').textContent,/未取得/);
assert.match($('inspectorLatest').textContent,/まだありません/);
''')


def test_mail_filter_is_bounded_and_queue_receipt_does_not_claim_read_or_success():
    check(r'''
seedSelection();ui.state.events=Array.from({length:105},(_,index)=>mail(index+1));
ui.state.events.push(mail(106,'agent-a','agent-b',{kind:'mail_consumed',delivery_state:'context_consumed',message_type:'worker_report'}));
renderActivity(getRun());assert.equal($('activityFeed').children.length,100);
const visible=renderedText($('activityFeed'));assert.match(visible,/送信キューに受理（記録時点）/);
assert.match(visible,/会話へ取り込み済み/);assert.match(visible,/理解・完了の確認ではありません/);
assert.match(visible,/作業者の報告/);assert.match($('activityScope').textContent,/最新100イベント内/);
assert(!visible.includes('subject 1\n'));ui.activityFilter='selected';ui.selectedAgent='agent-c';renderActivity(getRun());
assert.match(renderedText($('activityFeed')),/この表示範囲に記録はありません/);
''')


@pytest.mark.parametrize('key', ['Enter', ' '])
def test_mail_arrow_keyboard_opens_real_pair_without_changing_human_recipient(key):
    check(r'''
seedSelection();ui.state.events=[mail(1),mail(2,'agent-b','agent-a')];renderRun();
const selected=ui.selectedAgent,line=ui.networkSvg.children[0];let prevented=false;
''' + f"line.listeners.keydown({{key:{key!r},preventDefault(){{prevented=true;}}}});" + r'''
assert(prevented);assert.equal(ui.activityFilter,'pair');assert.equal(ui.selectedAgent,selected);
assert.deepEqual(ui.activityPair,{from:'agent-a',to:'agent-b'});assert.equal(requests.length,0);
assert.equal(document.activeElement,$('activityTitle'));assert.equal($('activityFeed').children.length,2);
''')


def test_mail_subject_and_body_remain_text_and_human_reply_never_impersonates_agent():
    check(r'''
seedSelection();ui.state.events=[mail(1,'agent-b','agent-a',{subject:'<script>literal</script>',text:'<a href=evil>literal</a>'})];
$('messageInput').value='PM unsent';saveAgentDraft({type:'input'});renderActivity(getRun());
const feed=$('activityFeed');assert.match(renderedText(feed),/<script>literal<\/script>/);
assert(!feed.querySelectorAll('*').some(node=>['SCRIPT','A'].includes(node.tagName)));
const reply=feed.querySelectorAll('*').find(node=>node.dataset.focusKey==='mail-reply:1');
assert.match(reply.textContent,/人の指示/);reply.listeners.click();
assert.equal(ui.selectedAgent,'agent-b');assert.equal(ui.drafts.get('agent-a'),'PM unsent');assert.equal($('messageInput').value,'');
assert.equal(requests.length,1);assert(requests[0].path.startsWith('/api/state?'));
requests[0].resolve(compactState('run-a','agent-b'));await flush();
''')
