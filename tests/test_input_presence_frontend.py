"""Neutral local input discovery without inferring delivery or submission state."""
import pytest

from test_frontend import APP, HTML, STATIC
from test_questions_frontend import check


def test_presence_counts_exact_nonempty_input_and_never_the_task_editor():
    check(r'''
await wire();setBriefOpen(false);renderState();
assert.equal($('messageInputCount').textContent,'0');assert.equal($('nextMessageInput').disabled,true);
$('taskInput').value='Already submitted task text';renderState();assert.equal(messageInputEntries().length,0);
editReply(' \n\t ');ui.drafts.set('agent-b','  日本語 😀\nexact  ');ui.drafts.set('agent-c','');renderState();
assert.deepEqual(messageInputEntries().map(({agent})=>agent.id),['agent-a','agent-b']);
assert.equal($('messageInputCount').textContent,'2');assert.equal($('nextMessageInput').disabled,false);
assert.match(renderedText($('runList')),/入力 2人/);
assert.equal($('messageInput').value,' \n\t ');assert.equal(ui.drafts.get('agent-b'),'  日本語 😀\nexact  ');
assert.equal($('agentCards').children.filter(card=>renderedText(card).includes('入力あり')).length,2);
assert(!renderedText($('agentCards')).includes('日本語 😀'));assert.equal(requests.length,0);
''')


def test_known_membership_is_required_and_orphaned_text_is_not_deleted():
    check(r'''
seedSelection();ui.drafts.set('orphan','Do not delete');ui.drafts.set('agent-c','Other team');
ui.drafts.set('agent-b','Member');ui.state.runs[0].agent_ids=['agent-a','agent-a','agent-c','missing'];
renderState();assert.deepEqual(messageInputEntries().map(({agent})=>agent.id),['agent-c']);
assert.equal($('messageInputCount').textContent,'1');
assert.equal(ui.drafts.get('orphan'),'Do not delete');assert.equal(ui.drafts.get('agent-b'),'Member');
assert(!renderedText($('agentCards').children[1]).includes('入力あり'));
ui.state.runs=ui.state.runs.filter(run=>run.id!=='run-b');renderState();
assert.equal($('messageInputCount').textContent,'0');assert.equal(ui.drafts.get('agent-c'),'Other team');
ui.state=fullState();renderState();assert.equal($('messageInputCount').textContent,'2');
assert.equal(requests.length,0);
''')


def test_presence_is_independent_of_status_or_send_eligibility():
    check(r'''
seedSelection();for(const agent of ui.state.agents)ui.drafts.set(agent.id,'Retained '+agent.id);
$('messageInput').value='Retained agent-a';ui.state.runs[1].status='stopped';
ui.state.agents[0].message_eligibility={allowed:false};delete ui.state.agents[1].message_eligibility;
ui.state.agents[2].status='stopped';renderState();
assert.equal($('messageInputCount').textContent,'3');assert.match(renderedText($('runList')),/入力 1人/);
assert.equal($('sendMessage').disabled,true);assert.equal($('messageInput').value,'Retained agent-a');
assert.equal(requests.length,0);
''')


def test_current_textarea_is_authoritative_without_rewriting_the_stored_draft():
    check(r'''
seedSelection();ui.drafts.set('agent-a','Older stored text');$('messageInput').value='';renderState();
assert.equal($('messageInputCount').textContent,'0');assert.equal(ui.drafts.get('agent-a'),'Older stored text');
$('messageInput').value='Current direct value';renderState();assert.equal($('messageInputCount').textContent,'1');
assert.equal(ui.drafts.get('agent-a'),'Older stored text');assert.equal($('messageInput').value,'Current direct value');
''')


def test_presence_updates_do_not_rebuild_cards_or_announce_each_character():
    check(r'''
await wire();setBriefOpen(false);let writes=0,value=$('messageInputNavigationStatus').textContent,countWrites=0,countValue=$('messageInputCount').textContent,labels=0,refreshes=0;
Object.defineProperty($('messageInputNavigationStatus'),'textContent',{get(){return value;},set(next){writes++;value=next;},configurable:true});
Object.defineProperty($('messageInputCount'),'textContent',{get(){return countValue;},set(next){countWrites++;countValue=next;},configurable:true});
const setAttribute=$('nextMessageInput').setAttribute.bind($('nextMessageInput'));
$('nextMessageInput').setAttribute=(key,value)=>{if(key==='aria-label')labels++;setAttribute(key,value);};
const refresh=renderMessageInputPresence;renderMessageInputPresence=()=>{refreshes++;refresh();};
editReply('First');const card=$('agentCards').children[0],session=$('runList').children[1];
assert.equal(writes,1);$('messageInput').focus();
editReply('First plus more');renderState();editReply(' \n ');renderState();
assert.equal(writes,1);assert.equal(countWrites,1);assert.equal(labels,1);assert.equal(refreshes,1);
assert.equal($('agentCards').children[0],card);assert.equal($('runList').children[1],session);
assert.equal(document.activeElement,$('messageInput'));
editReply('');assert.equal(writes,2);assert.equal($('messageInputCount').textContent,'0');
assert.equal(document.activeElement,$('messageInput'));assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('dialog', ['taskDialog', 'settingsDialog'])
def test_direct_navigation_during_a_modal_is_a_noop(dialog):
    check(r'''
seedSelection();$('messageInput').value='Exact A';ui.drafts.set('agent-c','Other input');
$('DIALOG').showModal();$('taskInput').focus();
const selection=ui.selectionGeneration,navigation=ui.navigationGeneration,drafts=JSON.stringify([...ui.drafts]);
openNextMessageInput();assert.equal(ui.selectionGeneration,selection);assert.equal(ui.navigationGeneration,navigation);
assert.equal(ui.selectedAgent,'agent-a');assert.equal(document.activeElement,$('taskInput'));
assert.equal(JSON.stringify([...ui.drafts]),drafts);assert.equal($('messageInput').value,'Exact A');assert.equal(requests.length,0);
'''.replace('DIALOG', dialog))


def test_navigation_is_global_while_question_and_crew_searches_remain_independent():
    check(r'''
seedQuestions();ui.drafts.set('agent-c','Never index this draft-only-token');
$('agentSearch').value='draft-only-token';renderRun();assert.deepEqual(ids(),[]);
ui.questionSearch='draft-only-token';toggleQuestionView();$('agentSearch').value='No crew match';renderRun();
ui.crewSearch='No crew match';toggleQuestionView();
openNextMessageInput();assert.equal(ui.needsOnly,true);assert.equal($('agentSearch').value,'draft-only-token');
assert.equal(ui.questionSearch,'draft-only-token');assert.equal(ui.crewSearch,'No crew match');
assert.equal(ui.selectedRun,'run-b');assert.equal(ui.selectedAgent,'agent-c');
assert.deepEqual(selectionOf(requests[0]),{view:'selected',run_id:'run-b',agent_id:'agent-c'});
assert.equal(requests.length,1);assert.equal(document.activeElement,$('conversationHeading'));
await drainStates();toggleQuestionView();assert.equal($('agentSearch').value,'No crew match');
assert.equal($('messageInput').value,'Never index this draft-only-token');
assert(requests.every(request=>request.path.startsWith('/api/state')));
''')


def test_cyclic_navigation_uses_session_list_and_declared_member_order_atomically():
    check(r'''
seedSelection();ui.state.runs[0].agent_ids=['agent-b','agent-a'];
ui.drafts.set('agent-b','  B\n ');ui.drafts.set('agent-c',' C ');$('messageInput').value=' A ';
assert.deepEqual(messageInputEntries().map(({agent})=>agent.id),['agent-c','agent-b','agent-a']);
const generation=ui.selectionGeneration;openNextMessageInput();
assert.equal(ui.selectedRun,'run-b');assert.equal(ui.selectedAgent,'agent-c');
assert.equal(ui.selectionGeneration,generation+1);assert.equal($('messageInput').value,' C ');
assert.equal(document.activeElement,$('messageInput'));assert.equal(requests.length,1);
assert.deepEqual(selectionOf(requests[0]),{view:'selected',run_id:'run-b',agent_id:'agent-c'});
await drainStates();ui.state.runs[0].agent_ids=['agent-b','agent-a'];openNextMessageInput();await drainStates();
assert.equal(ui.selectedAgent,'agent-b');assert.equal($('messageInput').value,'  B\n ');
ui.state.runs[0].agent_ids=['agent-b','agent-a'];openNextMessageInput();await drainStates();
assert.equal(ui.selectedAgent,'agent-a');assert.equal($('messageInput').value,' A ');
assert.equal(ui.drafts.get('agent-c'),' C ');assert(requests.every(request=>request.path.startsWith('/api/state')));
''')


def test_only_current_owner_focuses_without_epoch_churn_or_invalidating_pending_send():
    check(r'''
await wire();setBriefOpen(false);editReply('One current input');const pending=send();
const selection=ui.selectionGeneration,navigation=ui.navigationGeneration,draft=ui.draftRevisions.get('agent-a');
openNextMessageInput();openNextMessageInput();assert.equal(document.activeElement,$('messageInput'));
assert.equal(ui.selectionGeneration,selection);assert.equal(ui.navigationGeneration,navigation);
assert.equal(ui.draftRevisions.get('agent-a'),draft);assert.equal(requests.length,1);
resolve(0,{ok:true});await flush();await drainStates();await pending;
assert.equal($('messageInput').value,'');assert.equal($('messageInputCount').textContent,'0');
assert.equal($('messageStatus').textContent,'送信しました。');
''')


def test_empty_direct_navigation_does_not_select_or_mutate_and_focused_zero_has_fallback():
    check(r'''
seedSelection();const selection=ui.selectionGeneration,navigation=ui.navigationGeneration;
$('nextMessageInput').focus();openNextMessageInput();
assert.equal(ui.selectionGeneration,selection);assert.equal(ui.navigationGeneration,navigation);
assert.equal(ui.selectedAgent,'agent-a');assert.equal(document.activeElement,$('agentSearch'));
assert.equal(requests.length,0);
''')


def test_blocked_input_opens_heading_without_sending_or_changing_eligibility():
    check(r'''
await wire();setBriefOpen(false);runs[1].status='stopped';summaries[2].message_eligibility={allowed:false,reason:'stopped',message:'Cannot resume'};
ui.state=fullState();ui.drafts.set('agent-c','  Retain blocked text\n');openNextMessageInput();
assert.equal(document.activeElement,$('conversationHeading'));assert.equal($('messageInput').disabled,true);
assert.equal($('sendMessage').disabled,true);assert.equal($('messageInput').value,'  Retain blocked text\n');
await send();assert.equal(requests.length,1);assert(requests[0].path.startsWith('/api/state'));await drainStates();
assert.equal(document.activeElement,$('conversationHeading'));assert.equal($('messageInputCount').textContent,'1');
''')


@pytest.mark.parametrize('outcome', ['success', 'failure', 'unknown'])
@pytest.mark.parametrize('edit', ['none', 'same', 'different'])
def test_old_send_after_aba_keeps_neutral_presence_and_newer_feedback(outcome, edit):
    editing = {
        'none': '',
        'same': "editReply('Interim');editReply('  Submitted\\n  ');",
        'different': "editReply('Newer content');",
    }[edit]
    finish = {
        'success': "resolve(0,{ok:true});",
        'failure': "reject(0,new Error('Rejected'));",
        'unknown': "reject(0,Object.assign(new Error('Unknown'),{outcomeUnknown:true}));",
    }[outcome]
    check(r'''
await wire();setBriefOpen(false);editReply('  Submitted\n  ');const pending=send();
assert.equal($('messageInputCount').textContent,'1');selectAgent('agent-b');await drainStates();selectAgent('agent-a');await drainStates();
EDIT
inlineStatus($('messageStatus'),'Current feedback');const current=$('messageInput').value;
FINISH
await flush();await drainStates();await pending;
assert.equal($('messageInput').value,current);assert.equal($('messageInputCount').textContent,'1');
assert.equal($('messageStatus').textContent,'Current feedback');
const marker=$('agentCards').children[0].querySelectorAll('*').find(node=>node.className==='input-presence-badge');
assert.equal(marker.textContent,'入力あり');assert.equal(requests.filter(request=>request.path.endsWith('/message')).length,1);
'''.replace('EDIT', editing).replace('FINISH', finish))


def test_successful_old_owner_clear_updates_counts_without_touching_current_input():
    check(r'''
await wire();setBriefOpen(false);editReply('Submitted A');const pending=send();
selectAgent('agent-b');await drainStates();editReply('  Current B\n ');inlineStatus($('messageStatus'),'B feedback');
assert.equal($('messageInputCount').textContent,'2');resolve(0,{ok:true});await flush();await drainStates();await pending;
assert.equal($('messageInputCount').textContent,'1');assert.equal(ui.drafts.has('agent-a'),false);
assert.equal($('messageInput').value,'  Current B\n ');assert.equal($('messageStatus').textContent,'B feedback');
assert(!renderedText($('agentCards').children[0]).includes('入力あり'));
assert(renderedText($('agentCards').children[1]).includes('入力あり'));
''')


def test_successful_clear_refreshes_presence_before_the_following_state_response():
    check(r'''
await wire();setBriefOpen(false);editReply('Submitted');const pending=send();
resolve(0,{ok:true});await flush();
assert.equal($('messageInput').value,'');assert.equal($('messageInputCount').textContent,'0');
assert.equal($('nextMessageInput').disabled,true);assert(!renderedText($('agentCards')).includes('入力あり'));
assert.equal(requests.length,2);assert(requests[1].path.startsWith('/api/state'));assert.equal(requests[1].done,undefined);
await drainStates();await pending;
''')


def test_late_detail_and_failed_refresh_never_steal_focus_or_erase_presence():
    check(r'''
seedSelection();$('messageInput').value=' A ';ui.drafts.set('agent-b',' B ');ui.drafts.set('agent-c',' C ');
const pending=pollState();openNextMessageInput();openNextMessageInput();
assert.equal(ui.selectedAgent,'agent-c');assert.equal(document.activeElement,$('messageInput'));
requests[0].done=true;requests[0].resolve(compactState('run-a','agent-a','OLD'));await flush();
assert.equal(requests.length,2);assert.deepEqual(selectionOf(requests[1]),{view:'selected',run_id:'run-b',agent_id:'agent-c'});
$('agentSearch').focus();requests[1].done=true;requests[1].reject(new Error('Temporary failure'));await pending;
assert.equal(document.activeElement,$('agentSearch'));assert.equal($('messageInput').value,' C ');
assert.equal($('messageInputCount').textContent,'3');assert(!renderedText($('conversationLog')).includes('OLD'));
assert.equal(maxInFlight,1);
''')


def test_question_badge_keeps_plain_text_identity_and_does_not_index_input_content():
    check(r'''
seedQuestions();ui.drafts.set('agent-c','<script>private-input-token</script>');renderState();
const first=cards()[0];assert.match(renderedText(first),/入力あり/);assert(!renderedText(first).includes('private-input-token'));
assert.equal(first.querySelectorAll('*').filter(node=>node.className==='question-run-id').length,1);
$('agentSearch').value='private-input-token';renderRun();assert.deepEqual(ids(),[]);
assert.equal($('messageInputCount').textContent,'1');assert.equal($('questionCount').textContent,'3');
''')


def test_native_presence_controls_do_not_add_storage_send_state_or_endpoints():
    assert 'id="nextMessageInput" class="button minor" type="button"' in HTML
    assert 'aria-describedby="messageInputHelp"' in HTML
    assert 'id="messageInputCount" aria-hidden="true"' in HTML
    assert 'id="messageInputNavigationStatus" class="sr-only" role="status" aria-live="polite" aria-atomic="true"' in HTML
    assert '送信済みの文が残っている場合もあります' in HTML
    assert '.question-run-line' in (STATIC / 'styles.css').read_text()
    assert '/api/drafts' not in APP and 'localStorage' not in APP and 'sessionStorage' not in APP
