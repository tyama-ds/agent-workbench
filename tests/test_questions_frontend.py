"""All-session human pauses, exact navigation and draft ownership; no inference."""
import pytest

from test_frontend import APP, HTML, STATIC, run_javascript
from test_disclosure_focus_frontend import FOCUS_DOM
from test_run_action_frontend import ACTION_DOM, ACTION_FIXTURES


SETUP = r'''
function seedQuestions(){
  runs[0].created_at=2;runs[1].created_at=1;runs[1].status='waiting';
  for(const agent of summaries)Object.assign(agent,{status:'waiting',status_reason:'human_input',question:'Question '+agent.id});
  summaries[2].message_eligibility={allowed:false,reason:'time_limit',message:'実行時間の上限です'};
  seedSelection();ui.needsOnly=true;renderState();
}
function cards(){return $('agentCards').children;}
function ids(){return cards().map(card=>card.dataset.agentId);}
function editReply(value){$('messageInput').value=value;$('messageInput').listeners.input({type:'input'});}
function send(){return $('messageForm').listeners.submit({preventDefault(){}});}
'''


def check(source):
    fixtures = ACTION_FIXTURES.replace('api=(path)=>{', 'api=(path,options={})=>{').replace(
        'requests.push({path,resolve', 'requests.push({path,options,resolve')
    result = run_javascript(ACTION_DOM + FOCUS_DOM + APP + fixtures + SETUP + '\n(async()=>{\n' + source + r'''
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_global_membership_order_provenance_and_eligibility_are_independent():
    check(r'''
seedQuestions();
assert.deepEqual(ids(),['agent-c','agent-a','agent-b']);
assert.equal($('questionCount').textContent,'3');
assert.match($('questionQueueStatus').textContent,/回答可能 2件、回答不可 1件/);
assert.match(renderedText(cards()[0]),/Second task/);assert.match(renderedText(cards()[0]),/回答不可/);
assert.match(renderedText(cards()[0]),/実行時間の上限/);
assert.match(renderedText($('runList')),/質問 2件/);
assert.equal(ui.selectedRun,'run-a');assert.equal(ui.selectedAgent,'agent-a');
assert.match($('activeRunTitle').textContent,/表示中のチーム/);
assert.equal($('activeRunTask').textContent,'First task');
assert.match($('rosterScope').textContent,/全チーム/);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('change', [
    "agent.question='';", "agent.question='  \\n  ';", "agent.status_reason='teammates';",
    "agent.status_reason='error';agent.status='error';", "agent.status_reason='teammate_error';",
    "agent.status_reason='collaboration_limit';", "agent.status='stopped';", "agent.status='stopping';",
    "run.status='stopped';", "run.status='stopping';", "agent.status='error';", "delete agent.status_reason;",
])
def test_nonquestions_and_stopped_residue_do_not_enter_global_view(change):
    check(r'''
seedQuestions();const agent=ui.state.agents[2],run=ui.state.runs[1];
CHANGE
renderState();assert(!ids().includes('agent-c'));assert.equal(requests.length,0);
'''.replace('CHANGE', change))


def test_question_in_running_team_and_unknown_eligibility_stays_visible_fail_closed():
    check(r'''
seedQuestions();const agent=ui.state.agents[0];delete agent.message_eligibility;renderState();
assert(ids().includes(agent.id));assert.equal(ui.state.runs[0].status,'running');
assert.match(renderedText(cards()[1]),/送信可否未確認/);
assert.equal($('messageInput').disabled,true);assert.equal($('sendMessage').disabled,true);
assert.match($('messageEligibility').textContent,/確認できません/);
''')


def test_search_has_global_scope_independent_count_and_separate_retained_drafts():
    check(r'''
seedQuestions();$('agentSearch').value='Second task';renderRun();assert.deepEqual(ids(),['agent-c']);
assert.equal($('questionCount').textContent,'3');assert.equal($('agentCount').textContent,'1 / 3');
$('agentSearch').value='Question agent-b';renderRun();assert.deepEqual(ids(),['agent-b']);
$('agentSearch').value='Missing';renderRun();assert.deepEqual(ids(),[]);
assert.match($('rosterEmpty').textContent,/検索条件/);
toggleQuestionView();assert.equal($('agentSearch').value,'');$('agentSearch').value='Worker B';renderRun();
toggleQuestionView();assert.equal($('agentSearch').value,'Missing');toggleQuestionView();
assert.equal($('agentSearch').value,'Worker B');assert.equal(requests.length,0);
''')


def test_nonmatching_question_arrival_updates_denominator_without_switching_context():
    check(r'''
seedQuestions();$('agentSearch').value='Second task';renderRun();const old=cards()[0];
ui.state.agents[1].status_reason='working';ui.state.agents[1].question='';renderState();
assert.equal($('agentCount').textContent,'1 / 2');assert.equal($('questionCount').textContent,'2');
assert.equal(ui.selectedAgent,'agent-a');assert.equal(requests.length,0);
''')


def test_direct_cross_team_open_preserves_drafts_and_only_requests_target_detail():
    check(r'''
seedQuestions();$('messageInput').value='  Exact A\n draft  ';$('conversationLog').scrollTop=70;
openQuestion('agent-c');assert.equal(ui.selectedRun,'run-b');assert.equal(ui.selectedAgent,'agent-c');
assert.deepEqual(selectionOf(requests[0]),{view:'selected',run_id:'run-b',agent_id:'agent-c'});
assert.equal(requests.length,1);assert.equal(document.activeElement,$('humanQuestion'));
assert.equal(ui.drafts.get('agent-a'),'  Exact A\n draft  ');assert.equal($('messageInput').disabled,true);
await drainStates();openQuestion('agent-a');await drainStates();
assert.equal($('messageInput').value,'  Exact A\n draft  ');
assert(requests.every(request=>request.path.startsWith('/api/state')));
assert.equal($('questionCount').textContent,'3');
''')


def test_queue_navigation_rejects_aba_detail_and_never_loads_an_intermediate_root():
    check(r'''
seedQuestions();const pending=pollState();openQuestion('agent-c');openQuestion('agent-b');
requests[0].done=true;requests[0].resolve(compactState('run-a','agent-a','obsolete'));await flush();
assert.equal(requests.length,2);assert.deepEqual(selectionOf(requests[1]),{view:'selected',run_id:'run-a',agent_id:'agent-b'});
assert(!renderedText($('conversationLog')).includes('obsolete'));
await drainStates();await pending;assert.equal(ui.selectedAgent,'agent-b');
assert.equal(maxInFlight,1);assert.equal(document.activeElement,$('humanQuestion'));
''')


def test_focused_question_survives_changes_and_eviction_has_nearby_fallback():
    check(r'''
seedQuestions();cards()[0].focus();const first=cards()[0];renderState();assert.equal(document.activeElement,first);
ui.state.agents[2].message_eligibility={allowed:true,reason:'',message:''};renderState();
assert.equal(document.activeElement,cards()[0]);assert.notEqual(cards()[0],first);
ui.state.agents[2].question='';renderState();assert.equal(document.activeElement,cards()[0]);
assert.equal(document.activeElement.dataset.agentId,'agent-a');
for(const agent of ui.state.agents)agent.question='';renderState();
assert.equal(document.activeElement,$('needsYou'));assert.equal($('questionCount').textContent,'0');
assert.match($('rosterEmpty').textContent,/現在、人への質問/);
''')


def test_arrival_never_steals_composer_focus_or_draft_and_changed_eligibility_is_visible():
    check(r'''
seedQuestions();$('messageInput').value='Keep draft';$('messageInput').focus();
const agent=ui.state.agents[0];agent.message_eligibility={allowed:false,reason:'time_limit',message:'Deadline passed'};renderState();
assert.equal(document.activeElement,$('messageInput'));assert.equal($('messageInput').value,'Keep draft');
assert(ids().includes(agent.id));assert.equal($('sendMessage').disabled,true);
assert.match(renderedText(cards()[1]),/Deadline passed/);assert.equal(requests.length,0);
''')


def test_untrusted_question_and_identity_remain_plain_text_and_loading_does_not_fake_resolution():
    check(r'''
seedQuestions();const agent=ui.state.agents[2];agent.question='<script>alert(1)</script>';ui.state.runs[1].task='<img src=x onerror=alert(1)>';
renderState();assert.match(renderedText(cards()[0]),/<script>/);assert.match(renderedText(cards()[0]),/<img/);
ui.compactState=true;openQuestion(agent.id);requests[0].done=true;requests[0].reject(new Error('Detail failed'));await flush();
assert.equal($('questionCount').textContent,'3');assert.match($('detailStatus').textContent,/取得できません/);
assert.equal(ui.selectedAgent,agent.id);assert.equal(document.activeElement,$('humanQuestion'));
''')


@pytest.mark.parametrize('eligibility', ['undefined', '{allowed:false}', '{allowed:"true"}', '{}'])
def test_unknown_or_blocked_reply_never_submits_even_with_direct_submit(eligibility):
    check(r'''
await wire();getAgent().message_eligibility=ELIGIBILITY;editReply('Do not send');await send();
assert.equal(requests.length,0);assert.equal($('messageInput').value,'Do not send');
'''.replace('ELIGIBILITY', eligibility))


@pytest.mark.parametrize('outcome', ['success', 'failure', 'unknown'])
@pytest.mark.parametrize('edit', ['none', 'same', 'different'])
def test_old_send_after_aba_keeps_current_draft_and_feedback(outcome, edit):
    navigation = {
        'none': '',
        'same': "editReply('Interim');editReply('  Submitted\\n  ');",
        'different': "editReply('Newer draft');",
    }[edit]
    resolve = {'success': "resolve(0,{ok:true});", 'failure': "reject(0,new Error('Old failed'));",
               'unknown': "reject(0,Object.assign(new Error('Old uncertain'),{outcomeUnknown:true}));"}[outcome]
    check(r'''
await wire();setBriefOpen(false);editReply('  Submitted\n  ');const pending=send();
assert.equal(requests[0].path,'/api/agents/agent-a/message');assert.deepEqual(requests[0].options.body,{text:'  Submitted\n  '});
await send();assert.equal(requests.length,1);
selectAgent('agent-b');await drainStates();selectAgent('agent-a');await drainStates();
EDIT
const draft=$('messageInput').value;inlineStatus($('messageStatus'),'Newer feedback');
RESOLVE
await flush();await drainStates();await pending;
assert.equal($('messageInput').value,draft);assert.equal(ui.drafts.get('agent-a'),draft);
assert.equal($('messageStatus').textContent,'Newer feedback');assert.equal(ui.busyMessage,false);
assert.equal(requests.filter(request=>request.path.endsWith('/message')).length,1);
'''.replace('EDIT', navigation).replace('RESOLVE', resolve))


def test_success_only_clears_unchanged_submitted_draft_and_failure_retains_it():
    check(r'''
await wire();editReply('Exact original');const sent=send();resolve(0,{ok:true});await flush();await drainStates();await sent;
assert.equal($('messageInput').value,'');assert.equal(ui.drafts.has('agent-a'),false);assert.equal($('messageStatus').textContent,'送信しました。');
editReply('Keep rejected');const failed=send();reject(requests.length-1,new Error('Rejected'));await failed;
assert.equal($('messageInput').value,'Keep rejected');assert.equal(ui.drafts.get('agent-a'),'Keep rejected');
assert.equal($('messageStatus').textContent,'Rejected');
''')


def test_same_text_reedit_without_navigation_is_a_newer_draft():
    check(r'''
await wire();editReply('Same');const pending=send();editReply('Else');editReply('Same');
inlineStatus($('messageStatus'),'Current');resolve(0,{ok:true});await flush();await drainStates();await pending;
assert.equal($('messageInput').value,'Same');assert.equal(ui.drafts.get('agent-a'),'Same');assert.equal($('messageStatus').textContent,'Current');
''')


def test_native_question_controls_and_no_new_persistence_or_queue_endpoint():
    assert 'aria-controls="agentCards"' in HTML
    assert 'id="questionCount" aria-hidden="true"' in HTML
    assert 'id="questionQueueStatus" class="sr-only" role="status" aria-live="polite" aria-atomic="true"' in HTML
    assert 'aria-label="選択したエージェントへの質問" tabindex="0"' in HTML
    assert 'min-height:52px;overflow:auto;flex:0 1 auto' in (STATIC / 'styles.css').read_text()
    assert '/api/questions' not in APP
    assert 'localStorage' not in APP and 'sessionStorage' not in APP


def test_full_question_reading_position_is_stable_only_for_the_same_owner_and_question():
    check(r'''
seedQuestions();$('humanQuestion').scrollTop=71;$('humanQuestion').focus();renderState();
assert.equal($('humanQuestion').scrollTop,71);assert.equal(document.activeElement,$('humanQuestion'));
ui.state.agents[0].question='Updated question';renderState();assert.equal($('humanQuestion').scrollTop,0);
$('humanQuestion').scrollTop=33;openQuestion('agent-c');assert.equal($('humanQuestion').scrollTop,0);
await drainStates();ui.state.agents[2].question='';renderState();assert.equal(document.activeElement,$('conversationHeading'));
''')
