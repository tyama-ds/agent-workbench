"""Production polling/render callbacks; synthetic DOM focus-removal semantics only."""
import pytest

from test_frontend import APP, run_javascript
from test_compact_frontend import DOM, FIXTURES


FOCUS_DOM = r'''
// Model the browser rule missing from the compact fixture: replacing the focused
// descendant removes it from the document and makes BODY the active element.
Node.prototype.contains=function(target){return this===target||this.children.some(node=>node.contains(target));};
Node.prototype.append=function(...items){for(const node of items){node.parentElement=this;this.children.push(node);}};
Node.prototype.replaceChildren=function(...items){
  if(this.children.some(node=>node.contains(document.activeElement)))document.activeElement=document.body;
  for(const node of this.children)node.parentElement=null;
  this.children=[];this.append(...items);
};
const baseQuery=Node.prototype.querySelectorAll;
Node.prototype.querySelectorAll=function(selector){
  if(selector==='details.thinking > summary')return baseQuery.call(this,'*').filter(node=>node.tagName==='SUMMARY'&&node.parentElement?.tagName==='DETAILS'&&node.parentElement.className==='thinking');
  return baseQuery.call(this,selector);
};
Node.prototype.focus=function(options){this.lastFocusOptions=options;document.activeElement=this;};
Node.prototype.clientTop=0;
Node.prototype.getBoundingClientRect=function(){return this.rectangle||{top:0,bottom:20};};
Node.prototype.scrollIntoView=function(options){this.lastScrollOptions=options;};
window.innerHeight=768;
function disclosureSummaries(){return $('conversationLog').querySelectorAll('details.thinking > summary');}
function summary(id){return disclosureSummaries().find(node=>node.parentElement.dataset.logId===String(id));}
const log=(id,thinking=true)=>({id,kind:'assistant',text:`Visible answer ${id}`,thinking:thinking?`Synthetic details ${id}`:''});
async function updateLogs(logs){
  const pending=pollState(),request=requests.at(-1),selection=selectionOf(request);
  const state=compactState(selection.run_id,selection.agent_id);
  state.agents.find(agent=>agent.id===selection.agent_id).logs=structuredClone(logs);
  request.resolve(state);await pending;
}
'''


def check(source):
    result = run_javascript(DOM + FOCUS_DOM + APP + FIXTURES + "\n(async()=>{\n" + source + r'''
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


@pytest.mark.parametrize('expanded', [False, True])
@pytest.mark.parametrize('change', ['append', 'text', 'direct'])
def test_focused_disclosure_survives_changed_logs_and_direct_render(expanded, change):
    action = {
        'append': 'await updateLogs([log(1),log(2),log(3,false)]);',
        'text': "await updateLogs([{...log(1),text:'Changed answer'},log(2)]);",
        'direct': "getAgent().logs.push(log(3,false));renderConversation(getAgent());",
    }[change]
    check(r'''
await loadInitialSelection();await updateLogs([log(1),log(2)]);
const first=summary(1);first.parentElement.open=EXPANDED;first.focus();
$('messageInput').value='Unsent draft';$('conversationLog').scrollTop=570;
await updateLogs([log(1),log(2)]);assert.equal(document.activeElement,first,'Unchanged poll keeps actual node');
ACTION
assert.notEqual(summary(1),first);assert.equal(document.activeElement,summary(1));
assert.equal(summary(1).parentElement.open,EXPANDED);
assert.deepEqual(summary(1).lastFocusOptions,{preventScroll:true});
assert.equal($('conversationLog').scrollTop,570,'Focused disclosure suppresses bottom auto-follow');
assert.equal($('messageInput').value,'Unsent draft');
'''.replace('EXPANDED', str(expanded).lower()).replace('ACTION', action))


@pytest.mark.parametrize('target', ['messageInput', 'conversationHeading', 'taskInput', 'searchSecret'])
def test_log_update_never_steals_another_controls_focus(target):
    check(r'''
await loadInitialSelection();await updateLogs([log(1),log(2)]);
const input=$('TARGET');input.value='Keep this exact draft';input.focus();
$('conversationLog').scrollTop=570;
await updateLogs([log(2),log(3)]);
assert.equal(document.activeElement,input);assert.equal(input.value,'Keep this exact draft');
assert.equal($('conversationLog').scrollTop,800,'Ordinary near-bottom auto-follow stays unchanged');
'''.replace('TARGET', target))


@pytest.mark.parametrize(('before', 'focused', 'after', 'expected'), [
    ('[log(1),log(2),log(3)]', 1, '[log(2),log(3),log(4)]', 2),
    ('[log(1),log(2),log(3)]', 3, '[log(1),log(2)]', 2),
    ('[log(1)]', 1, '[log(4)]', 4),
    ('[log(1)]', 1, '[log(4,false)]', None),
    ('[log(1)]', 1, '[]', None),
])
def test_focused_eviction_has_same_owner_nearby_fallback(before, focused, after, expected):
    check(r'''
await loadInitialSelection();await updateLogs(BEFORE);summary(FOCUSED).focus();
await updateLogs(AFTER);
const expected=EXPECTED;assert.equal(document.activeElement,expected);
assert.deepEqual(expected.lastFocusOptions,{preventScroll:true});
'''.replace('BEFORE', before).replace('FOCUSED', str(focused)).replace('AFTER', after)
          .replace('EXPECTED', f'summary({expected})' if expected else "$('conversationHeading')"))


def test_real_retention_window_evicts_only_focused_record_and_preserves_draft():
    check(r'''
await loadInitialSelection();const logs=Array.from({length:200},(_,i)=>log(i+1));
await updateLogs(logs);summary(1).focus();summary(2).parentElement.open=true;
$('messageInput').value='Retained draft';$('conversationLog').scrollTop=0;
await updateLogs([...logs.slice(1),log(201)]);
assert.equal(disclosureSummaries().length,200);assert.equal(document.activeElement,summary(2));
assert.equal(summary(2).parentElement.open,true);assert.equal($('messageInput').value,'Retained draft');
assert.equal($('conversationLog').scrollTop,0);
''')


@pytest.mark.parametrize(('pane_top', 'rectangle', 'expected'), [(0, '{top:-70,bottom:-50}', 230), (0, '{top:240,bottom:260}', 360), (-80, '{top:-30,bottom:-10}', 270)])
def test_eviction_reveals_clipped_fallback_only_within_log_pane(pane_top, rectangle, expected):
    check(r'''
await loadInitialSelection();await updateLogs([log(1),log(2)]);summary(1).focus();
$('conversationLog').scrollTop=300;
$('conversationLog').rectangle={top:PANE_TOP,bottom:PANE_TOP+200};
const bounds=Node.prototype.getBoundingClientRect;
Node.prototype.getBoundingClientRect=function(){if(this.tagName!=='SUMMARY')return bounds.call(this);const box=RECTANGLE,delta=$('conversationLog').scrollTop-300;return {top:box.top-delta,bottom:box.bottom-delta};};
await updateLogs([log(2)]);
assert.equal(document.activeElement,summary(2));assert.equal($('conversationLog').scrollTop,EXPECTED);
assert.equal(summary(2).lastScrollOptions,undefined,'Summary fallback scrolls only its own pane');
'''.replace('RECTANGLE', rectangle).replace('EXPECTED', str(expected)).replace('PANE_TOP', str(pane_top)))


def test_eviction_reveals_viewport_clipped_fallback_after_pane_scroll_clamps():
    check(r'''
await loadInitialSelection();await updateLogs([log(1),log(2)]);summary(1).focus();
const container=$('conversationLog');container.rectangle={top:-100,bottom:100};
let scroll=0;Object.defineProperty(container,'scrollTop',{get:()=>scroll,set:value=>{scroll=Math.max(0,value);}});
const bounds=Node.prototype.getBoundingClientRect;
Node.prototype.getBoundingClientRect=function(){return this.tagName==='SUMMARY'?{top:-90-scroll,bottom:-70-scroll}:bounds.call(this);};
await updateLogs([log(2)]);
assert.equal(container.scrollTop,0);assert.equal(document.activeElement,summary(2));
assert.deepEqual(summary(2).lastScrollOptions,{block:'nearest',inline:'nearest'});
assert.deepEqual(summary(2).lastFocusOptions,{preventScroll:true});
''')


@pytest.mark.parametrize(('run_id', 'agent_id'), [('run-a', 'agent-b'), ('run-b', 'agent-c')])
def test_repeated_log_id_cannot_restore_across_agent_or_run(run_id, agent_id):
    check(r'''
await loadInitialSelection();await updateLogs([log(1)]);const old=summary(1);old.focus();
ui.compactState=false;ui.state=fullState();for(const agent of ui.state.agents)agent.logs=[log(1)];
changeSelection('RUN','AGENT');renderRun();
assert.notEqual(summary(1).dataset.focusKey,old.dataset.focusKey);
assert.equal(document.activeElement,document.body,'Navigation cannot restore old-owner focus');
'''.replace('RUN', run_id).replace('AGENT', agent_id))


def test_obsolete_poll_aba_does_not_restore_abandoned_disclosure_or_steal_input():
    check(r'''
await loadInitialSelection();await updateLogs([log(1)]);summary(1).focus();
const pending=pollState(),old=requests.at(-1),oldSelection=selectionOf(old);
selectAgent('agent-b');selectAgent('agent-a');
$('messageInput').value='Newer ABA draft';$('messageInput').focus();
const stale=compactState(oldSelection.run_id,oldSelection.agent_id);stale.agents[0].logs=[log(1)];
old.resolve(stale);await flush();
const latest=requests.at(-1);assert.notEqual(latest,old);
const current=compactState('run-a','agent-a');current.agents[0].logs=[log(1),log(2)];
latest.resolve(current);await pending;
assert.equal(document.activeElement,$('messageInput'));assert.equal($('messageInput').value,'Newer ABA draft');
''')


@pytest.mark.parametrize('logs', [
    "[{kind:'assistant',text:'Idless one',thinking:'Details'},{kind:'assistant',text:'Idless two',thinking:'Details'}]",
    '[log(1),log(1)]', '[log(1),log("1")]', '[log(null)]', '[log(Number.MAX_SAFE_INTEGER+1)]',
])
def test_missing_or_ambiguous_ids_are_not_used_as_focus_identity(logs):
    check(r'''
await loadInitialSelection();await updateLogs(LOGS);
assert(disclosureSummaries().every(node=>!node.dataset.focusKey));
disclosureSummaries()[0].focus();await updateLogs([log(2)]);
assert.equal(document.activeElement,document.body,'Cannot infer identity from an index or duplicate');
'''.replace('LOGS', logs))


def test_same_id_losing_disclosure_is_not_misreported_as_history_eviction():
    check(r'''
await loadInitialSelection();await updateLogs([log(1),log(2)]);summary(1).focus();
await updateLogs([log(1,false),log(2)]);
assert.equal(document.activeElement,document.body,'Record remains; eviction fallback does not apply');
''')


def test_nested_render_cannot_steal_focus_deliberately_moved_during_replacement():
    check(r'''
await loadInitialSelection();await updateLogs([log(1)]);summary(1).focus();
const container=$('conversationLog'),replace=container.replaceChildren;
container.replaceChildren=function(...nodes){replace.call(this,...nodes);$('messageInput').focus();};
await updateLogs([log(2)]);
assert.equal(document.activeElement,$('messageInput'));
''')
