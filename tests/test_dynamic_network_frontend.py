"""Actual network callbacks with fake DOM/timers; no inference or browser traffic."""
from pathlib import Path
import re

import pytest

from test_cockpit_frontend import FOCUS
from test_compact_frontend import FIXTURES
from test_frontend import APP, HTML, run_javascript
from test_run_action_frontend import ACTION_DOM


DYNAMIC = r'''
Node.prototype.remove=function(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(node=>node!==this);this.parentElement=null;}};
Node.prototype.beginElement=function(){this.started=(this.started||0)+1;};
const timerJobs=new Map();let timerId=0;
globalThis.setTimeout=(callback,delay)=>{const id=++timerId;timerJobs.set(id,{callback,delay});return id;};
globalThis.clearTimeout=id=>timerJobs.delete(id);
window.setTimeout=setTimeout;window.clearTimeout=clearTimeout;
function advanceTimers(delta){for(const [id,job] of [...timerJobs]){job.delay-=delta;if(job.delay<=0){timerJobs.delete(id);job.callback();}}}
const motionPreference={matches:false,listeners:{},addEventListener(type,callback){this.listeners[type]=callback;}};
window.matchMedia=query=>query.includes('prefers-reduced-motion')?motionPreference:{matches:false};
document.hidden=false;document.listeners={};document.addEventListener=(type,callback)=>document.listeners[type]=callback;
function setReduced(value){motionPreference.matches=value;motionPreference.listeners.change();}
function setHidden(value){document.hidden=value;document.listeners.visibilitychange();}
function prepareNetwork(events=[]){initializeNetworkControls();seedSelection();applyState({...ui.state,events},{run:ui.selectedRun,agent:ui.selectedAgent});setConnection(true,'fixture online');renderRun();}
function pulseValues(){return [...ui.networkPulses.values()];}
function appendMail(event){ui.state.events.push(event);renderRun();}
'''


def check(source):
    result = run_javascript(ACTION_DOM + APP + FIXTURES + FOCUS + DYNAMIC + '\n(async()=>{\n' + source + r'''
stopNetworkMotion();
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_circular_nodes_preview_controls_and_motion_are_local_accessible_assets():
    css = (Path(__file__).resolve().parents[1] / 'static/styles.css').read_text(encoding='utf-8')
    blocks = re.findall(r'\.network-node\{([^}]*)\}', css)
    assert any('width:112px' in block and 'height:112px' in block and 'border-radius:50%' in block for block in blocks)
    for ident in ('networkPreview', 'networkPreviewTitle', 'networkPreviewRole', 'networkPreviewState',
                  'networkPreviewAssignment', 'networkPreviewLatest', 'networkPreviewCounts',
                  'networkPreviewError', 'networkPreviewMode', 'networkPreviewClose', 'networkPreviewOpen', 'networkMotion'):
        assert HTML.count(f'id="{ident}"') == 1
    assert '.network-mail-pulse' in css and 'pointer-events:none' in css
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert 'animation:none!important' in css
    assert 'requestAnimationFrame' not in APP[APP.index('function startNetworkMailPulse('):APP.index('function observeNetworkMail(')]
    check(r'''
prepareNetwork();const second={...namedAgent('agent-b'),id:'agent-d',name:'Same prefix second worker'};
namedAgent('agent-a').name='Same prefix PM';namedAgent('agent-b').name='Same prefix first worker';
ui.state.agents.push(second);getRun().agent_ids.push(second.id);renderRun();
assert.deepEqual(['agent-a','agent-b','agent-d'].map(id=>ui.networkNodes.get(id).monogram.textContent),['PM','W1','W2']);
for(const id of ['agent-a','agent-b','agent-d']){
  const node=ui.networkNodes.get(id);assert.equal(node.name.textContent,namedAgent(id).name);assert.equal(node.button.dataset.agentId,id);
}
''')


def test_hover_and_focus_preview_do_not_select_fetch_or_change_human_draft():
    check(r'''
prepareNetwork();$('messageInput').value='Human draft remains assigned to PM';saveAgentDraft({type:'input'});
const before=JSON.stringify(ui.state),selected=ui.selectedAgent,node=ui.networkNodes.get('agent-b').button;
namedAgent('agent-b').assignment='<img src=x onerror=alert(1)> literal task';
node.listeners.pointerenter();assert.equal($('networkPreview').hidden,false);
assert.equal($('networkPreviewTitle').textContent,'Worker B');assert.equal($('networkPreviewAssignment').textContent,namedAgent('agent-b').assignment);
assert.equal($('networkPreviewAssignment').children.length,0);assert.match($('networkPreviewCounts').textContent,/未取得/);
assert.equal(ui.selectedAgent,selected);assert.equal(requests.length,0);assert.equal($('messageInput').value,'Human draft remains assigned to PM');
node.listeners.pointerleave({relatedTarget:null});advanceTimers(240);assert.equal($('networkPreview').hidden,true);
node.listeners.focus();assert.equal($('networkPreview').hidden,false);assert.equal(node.getAttribute('aria-controls'),'networkPreview');
node.listeners.blur({relatedTarget:null});advanceTimers(240);assert.equal($('networkPreview').hidden,true);assert.equal(ui.selectedAgent,selected);assert.equal(requests.length,0);
assert.equal(networkViewState().pinnedAgent,null);assert.equal(ui.drafts.get(selected),'Human draft remains assigned to PM');
''')


def test_pin_precedes_hover_and_reads_fresh_public_state_on_every_poll():
    check(r'''
prepareNetwork();const selected=ui.selectedAgent,node=ui.networkNodes.get('agent-b').button;
node.listeners.click({detail:1});assert.equal(networkViewState().pinnedAgent,'agent-b');
assert.equal(node.getAttribute('aria-pressed'),'true');assert.match($('networkPreviewMode').textContent,/固定中/);
node.listeners.pointerleave({relatedTarget:null});ui.networkNodes.get('agent-a').button.listeners.pointerenter();
assert.equal($('networkPreviewTitle').textContent,'Worker B');assert.equal(ui.selectedAgent,selected);assert.equal(requests.length,0);
ui.state.agents=ui.state.agents.map(agent=>agent.id==='agent-b'?{...agent,name:'Fresh worker name',assignment:'Fresh assignment',status:'working',status_reason:'working',last_error:'Exact error record',activity:{latest_log:{at:3,text:'Fresh observed activity'},pending_count:2,result_count:4,output_receipt_count:1}}:agent);
renderRun();assert.equal($('networkPreviewTitle').textContent,'Fresh worker name');assert.equal($('networkPreviewAssignment').textContent,'Fresh assignment');
assert.match($('networkPreviewLatest').textContent,/Fresh observed activity/);assert.match($('networkPreviewCounts').textContent,/待機入力 2 · 結果 4 · 保存記録 1/);
assert.equal($('networkPreviewError').textContent,'Exact error record');assert(!$('networkPreviewError').hidden);
assert.equal(ui.selectedAgent,selected);assert.equal(requests.length,0);assert.equal(networkViewState().pinnedAgent,'agent-b');
assert(!JSON.stringify([...ui.networkViews]).includes('Fresh assignment'));node.listeners.click({detail:1});assert.equal(networkViewState().pinnedAgent,null);assert($('networkPreview').hidden);
''')


def test_pins_are_per_run_and_removed_agents_redaction_and_restart_clear_public_preview():
    check(r'''
prepareNetwork();toggleNetworkPin('agent-b');changeSelection('run-b','agent-c');renderRun();assert($('networkPreview').hidden);
toggleNetworkPin('agent-c');changeSelection('run-a','agent-a');renderRun();assert.equal(networkViewState().pinnedAgent,'agent-b');assert.equal($('networkPreviewTitle').textContent,'Worker B');
ui.state.agents=ui.state.agents.filter(agent=>agent.id!=='agent-b');renderRun();assert.equal(networkViewState().pinnedAgent,null);assert($('networkPreview').hidden);
toggleNetworkPin('agent-a');invalidateWorkBoardContent();assert($('networkPreview').hidden);assert([...ui.networkViews.values()].every(view=>view.pinnedAgent===null));
toggleNetworkPin('agent-a');ui.instanceId='original';acceptServerInstance({instance_id:'new-instance'});
assert($('networkPreview').hidden);assert.equal($('networkPreviewAssignment').textContent,'');assert.equal(ui.networkViews.size,0);assert.equal(ui.networkPulses.size,0);
''')


def test_preview_close_escape_and_explicit_open_are_separate_native_actions():
    check(r'''
prepareNetwork();const node=ui.networkNodes.get('agent-b').button;
networkNodeClick({detail:0},'agent-b');assert.equal(ui.selectedAgent,'agent-a');assert.equal(requests.length,0);
$('networkPreviewClose').listeners.click();assert($('networkPreview').hidden);assert.equal(document.activeElement,node);assert.equal(networkViewState().pinnedAgent,null);
networkNodeClick({detail:0},'agent-b');let prevented=0;
$('networkPreview').listeners.keydown({key:'Escape',preventDefault(){prevented++}});assert.equal(prevented,1);assert($('networkPreview').hidden);
networkNodeClick({detail:0},'agent-b');$('networkPreviewOpen').listeners.click();assert.equal(ui.selectedAgent,'agent-b');
assert.equal(requests.length,1);assert.deepEqual(selectionOf(requests[0]),{view:'selected',run_id:'run-a',agent_id:'agent-b'});
requests[0].resolve(compactState('run-a','agent-b'));await flush();assert.equal(selectedOutput().record.text,'current result agent-b');
''')


def test_hover_card_pointer_and_keyboard_focus_remain_operable_without_auto_selection():
    check(r'''
prepareNetwork();const node=ui.networkNodes.get('agent-b').button,panel=$('networkPreview'),open=$('networkPreviewOpen');
panel.append(open);node.listeners.pointerenter();node.listeners.pointerleave({relatedTarget:panel});
panel.listeners.pointerenter();advanceTimers(500);assert(!panel.hidden);assert.equal(ui.selectedAgent,'agent-a');assert.equal(networkViewState().pinnedAgent,null);
panel.listeners.pointerleave({relatedTarget:null});advanceTimers(239);assert(!panel.hidden);advanceTimers(1);assert(panel.hidden);
node.listeners.focus();let prevented=0;node.listeners.keydown({key:'F2',preventDefault(){prevented++},stopPropagation(){}});
assert.equal(prevented,1);assert.equal(document.activeElement,open);panel.listeners.focusin();advanceTimers(500);assert(!panel.hidden);
assert.equal(ui.selectedAgent,'agent-a');assert.equal(requests.length,0);
panel.listeners.keydown({key:'Escape',preventDefault(){}});assert(panel.hidden);assert.equal(document.activeElement,node);assert.equal(networkViewState().pinnedAgent,null);
''')


@pytest.mark.parametrize('invalidate', ['redaction', 'disconnect'])
def test_invalidated_public_content_cannot_reappear_until_fresh_accepted_state(invalidate):
    action = 'invalidateWorkBoardContent();' if invalidate == 'redaction' else "setConnection(false,'fixture lost');"
    check(r'''
prepareNetwork();namedAgent('agent-b').assignment='OLD PUBLIC SECRET';toggleNetworkPin('agent-b');assert.equal($('networkPreviewAssignment').textContent,'OLD PUBLIC SECRET');
''' + action + r'''
assert($('networkPreview').hidden);const node=ui.networkNodes.get('agent-b').button;node.listeners.pointerenter();node.listeners.focus();renderRun();
assert($('networkPreview').hidden);assert.equal($('networkPreviewAssignment').textContent,'');setConnection(true,'transport alone restored');renderNetworkPreview();assert($('networkPreview').hidden);
const fresh=structuredClone(ui.state);fresh.agents.find(agent=>agent.id==='agent-b').assignment='[masked] public task';
applyState(fresh,{run:'run-a',agent:'agent-a'});renderRun();ui.networkNodes.get('agent-b').button.listeners.pointerenter();
assert(!$('networkPreview').hidden);assert.equal($('networkPreviewAssignment').textContent,'[masked] public task');assert(!renderedText($('networkPreview')).includes('OLD PUBLIC SECRET'));
''')


def test_only_new_actual_mail_stages_animate_once_and_finish_without_replay():
    check(r'''
const manualStarts=[];
Node.prototype.beginElement=function(){
  assert.equal(this.getAttribute('begin'),'indefinite','Insertion must not start an implicit interval on the existing SVG timeline');
  assert.equal(this.started,undefined,'Each finite effect has one explicit start');
  assert.equal(this.parentElement.parentElement,ui.networkPulseLayer);assert.equal(typeof this.listeners.endEvent,'function');
  this.started=1;manualStarts.push(this);
};
prepareNetwork([mail(1)]);assert.equal(ui.networkPulses.size,0);assert.equal(networkViewState().mailCursor,1);
appendMail(mail(2));assert.equal(ui.networkPulses.size,1);let pulse=pulseValues()[0];
assert.equal(pulse.stage,'queued');assert.equal(pulse.node.dataset.eventId,'2');assert.equal(pulse.motion.tagName,'ANIMATEMOTION');
assert.equal(pulse.motion.getAttribute('repeatCount'),'1');assert.equal(pulse.motion.getAttribute('dur'),'1200ms');assert.equal(pulse.motion.started,1);
const firstNode=pulse.node;renderRun();assert.equal(ui.networkPulses.size,1);assert.equal(pulseValues()[0].node,firstNode);assert.equal(manualStarts.length,1);
appendMail(mail(3,'agent-a','agent-b',{kind:'mail_consumed',delivery_state:'context_consumed',mail_id:'m2'}));
assert.equal(ui.networkPulses.size,2);const consumed=pulseValues().find(item=>item.stage==='consumed');assert(consumed);
assert.equal(consumed.motion.tagName,'ANIMATE');assert.equal(consumed.motion.getAttribute('repeatCount'),'1');
assert.equal(consumed.motion.getAttribute('begin'),'indefinite');assert.equal(consumed.motion.getAttribute('dur'),'1200ms');assert.equal(consumed.motion.started,1);
assert.deepEqual(manualStarts,[pulse.motion,consumed.motion]);assert.equal(requests.length,0);
assert.match(ui.networkMailLines[0].line.getAttribute('aria-label'),/会話へ取り込み済み/);assert.match(ui.networkMailLines[0].line.getAttribute('aria-label'),/理解や完了の確認ではありません/);
pulse.motion.listeners.endEvent();assert.equal(ui.networkPulses.size,1);assert(!firstNode.parentElement);
advanceTimers(1299);assert.equal(ui.networkPulses.size,1);advanceTimers(1);assert.equal(ui.networkPulses.size,0);
renderRun();assert.equal(ui.networkPulses.size,0);assert.equal(timerJobs.size,0);assert.equal(manualStarts.length,2);assert.equal(requests.length,0);
''')


def test_invalid_cross_run_legacy_and_duplicate_records_cannot_invent_motion():
    check(r'''
prepareNetwork([mail(1)]);
ui.state.events.push(mail(2,'agent-a','agent-b',{kind:'tool'}),mail(3,'agent-a','agent-b',{delivery_state:'unknown'}),
 mail(4,'agent-a','agent-b',{mail_id:''}),mail(5,'agent-a','agent-b',{run_id:'run-b'}),mail(6,'agent-c','agent-a'),mail(7,'agent-a','agent-a'),
 mail(8,'agent-a','agent-b',{from_agent_id:null}),mail(9,'agent-a','agent-b',{mail_id:'x'.repeat(257)}),mail('10'),mail(NaN),mail(-1));
renderRun();assert.equal(ui.networkPulses.size,0);
const latest=mail(20);ui.state.events.push(latest,{...latest});renderRun();assert.equal(ui.networkPulses.size,1);
advanceTimers(1300);renderRun();assert.equal(ui.networkPulses.size,0);
ui.state.events=[mail(1),mail(20),mail(2)];renderRun();assert.equal(ui.networkPulses.size,0);
''')


@pytest.mark.parametrize('mode', ['toggle', 'reduce', 'hidden', 'disconnect', 'inspector', 'archive', 'done'])
def test_pause_conditions_stop_motion_and_resume_seeds_history_without_replaying_it(mode):
    changes = {
        'toggle': ("$('networkMotion').listeners.click();", "$('networkMotion').listeners.click();"),
        'reduce': ('setReduced(true);', 'setReduced(false);'),
        'hidden': ('setHidden(true);', 'setHidden(false);'),
        'disconnect': ("setConnection(false,'fixture disconnected');", "setConnection(true,'fixture reconnected');applyState(structuredClone(ui.state),{run:ui.selectedRun,agent:ui.selectedAgent});"),
        'inspector': ("setCockpitView('inspector');", "setCockpitView('network');"),
        'archive': ("getRun().archived=true;renderRun();", "getRun().archived=false;"),
        'done': ("getRun().status='done';renderRun();", "getRun().status='running';"),
    }
    pause, resume = changes[mode]
    check(r'''
prepareNetwork([mail(1)]);namedAgent('agent-b').status='working';appendMail(mail(2));assert.equal(ui.networkPulses.size,1);
''' + pause + r'''
assert.equal(ui.networkPulses.size,0);assert(!ui.networkNodes.get('agent-b').button.classList.contains('is-live'));
appendMail(mail(3));assert.equal(ui.networkPulses.size,0);
''' + resume + r'''
renderRun();assert.equal(ui.networkPulses.size,0);appendMail(mail(4));assert.equal(ui.networkPulses.size,1);
assert.equal(pulseValues()[0].node.dataset.eventId,'4');assert.equal(requests.length,0);
''')


def test_run_return_and_unloaded_compact_events_do_not_replay_old_mail():
    check(r'''
prepareNetwork([mail(1)]);appendMail(mail(2));assert.equal(ui.networkPulses.size,1);
changeSelection('run-b','agent-c');renderRun();assert.equal(ui.networkPulses.size,0);
ui.state.events.push(mail(3));changeSelection('run-a','agent-a');renderRun();assert.equal(ui.networkPulses.size,0);
appendMail(mail(4));assert.equal(ui.networkPulses.size,1);
ui.compactState=true;ui.loadedEventsRun='run-b';renderRun();assert.equal(ui.networkPulses.size,0);
ui.state.events.push(mail(5));ui.loadedEventsRun='run-a';renderRun();assert.equal(ui.networkPulses.size,0);
appendMail(mail(6));assert.equal(ui.networkPulses.size,1);assert.equal(pulseValues()[0].node.dataset.eventId,'6');
''')


def test_motion_queue_and_seen_cache_are_bounded_and_evicted_old_ids_never_replay():
    check(r'''
prepareNetwork([mail(1)]);
for(let batch=0;batch<4;batch++){ui.state.events=Array.from({length:100},(_,i)=>mail(2+batch*100+i));renderRun();assert(ui.networkPulses.size<=16);}
assert.equal(ui.networkPulses.size,16);assert.equal(networkViewState().mailSeen.size,200);assert.equal(networkViewState().mailCursor,401);
assert.equal(timerJobs.size,16);advanceTimers(1300);assert.equal(ui.networkPulses.size,0);assert.equal(timerJobs.size,0);
ui.state.events=[mail(2)];renderRun();assert.equal(ui.networkPulses.size,0);assert.equal(networkViewState().mailCursor,401);
''')


def test_drag_updates_packet_path_and_consumed_destination_without_new_activity():
    check(r'''
prepareNetwork([mail(1)]);appendMail(mail(2));appendMail(mail(3,'agent-a','agent-b',{kind:'mail_consumed',delivery_state:'context_consumed',mail_id:'m2'}));
const queued=pulseValues().find(p=>p.stage==='queued'),consumed=pulseValues().find(p=>p.stage==='consumed'),path=queued.motion.getAttribute('path'),sequence=ui.networkPulseSequence;
moveNetworkNode('agent-b',550,410);assert.notEqual(queued.motion.getAttribute('path'),path);
assert.equal(queued.motion.getAttribute('path'),networkMailPath(ui.networkLayout.positions.get('agent-a'),ui.networkLayout.positions.get('agent-b'),queued.index));
const center=networkNodeCenter(ui.networkLayout.positions.get('agent-b'));assert.equal(Number(consumed.node.getAttribute('cx')),center.x);assert.equal(Number(consumed.node.getAttribute('cy')),center.y);
assert.equal(ui.networkPulseSequence,sequence);assert.equal(ui.networkPulses.size,2);
''')
