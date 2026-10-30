"""Question notices and captured reply ownership; synthetic DOM/transport only."""
import json

import pytest

from test_frontend import HTML, STATIC
from test_questions_frontend import check as question_check


SETUP = r'''
const originalFullState=fullState;
fullState=(...args)=>({...originalFullState(...args),instance_id:'instance-a'});
const qid='q-'+'a'.repeat(32),qid2='q-'+'b'.repeat(32),osNotices=[];
let permissionCalls=0;
function installNotifications(permission='granted'){
  globalThis.Notification=class {
    static permission=permission;
    static async requestPermission(){permissionCalls++;this.permission='granted';return 'granted';}
    constructor(title,options){this.title=title;this.options=options;this.closed=false;osNotices.push(this);}
    close(){this.closed=true;}
  };
}
function timedQuestion(id=qid,overrides={}){
  const now=Date.now()/1000;
  return {question_id:id,kind:'consultation',recommendation:'Recommended private option',asked_at:now,
    deadline_at:now+90,resolution:'pending',resolved_at:null,reason:'',...overrides};
}
function setQuestion(index=0,id=qid,overrides={}){
  Object.assign(summaries[index],{status:'waiting',status_reason:'human_input',question:'Private human question',question_state:timedQuestion(id,overrides)});
  const current=ui.state.agents.find(agent=>agent.id===summaries[index].id);
  if(current)Object.assign(current,structuredClone(summaries[index]));
}
async function prepareNotice(){
  await wire();setBriefOpen(false);ui.instanceId='instance-a';ui.networkConnected=true;ui.detailError=false;
  setQuestion();renderState();
}
'''


def check(source):
    question_check(SETUP + source)


def test_arrival_is_prominent_across_runs_without_stealing_draft_or_focus():
    check(r'''
installNotifications();await prepareNotice();editReply('Original draft');$('messageInput').focus();
setQuestion(2,qid2);renderState();renderState();
assert.equal($('questionNotice').hidden,false);assert.match($('questionNoticeTitle').textContent,/2 件/);
assert.match($('questionNoticeBody').textContent,/推奨回答/);
assert.equal($('messageInput').value,'Original draft');assert.equal(document.activeElement,$('messageInput'));
assert.equal(ui.selectedAgent,'agent-a');assert.equal(osNotices.length,2);assert.equal(requests.length,0);
''')


def test_os_notification_is_generic_and_one_attempt_per_question():
    check(r'''
installNotifications();await prepareNotice();renderState();setConnection(false,'offline');setConnection(true,'online');
assert.equal(osNotices.length,1);assert.equal(permissionCalls,0);
assert.equal(osNotices[0].title,'Workbench: 回答待ちの質問があります');
assert.equal(osNotices[0].options.body,'アプリを開いて質問と回答期限を確認してください。');
assert.doesNotMatch(JSON.stringify(osNotices[0].options),/Private|Recommended|First task|PM A/);
setQuestion(0,qid2);renderState();assert.equal(osNotices.length,2);assert.equal(osNotices[0].closed,true);
''')


def test_permission_is_requested_only_by_explicit_button_click():
    check(r'''
installNotifications('default');await prepareNotice();renderState();
assert.equal(permissionCalls,0);assert.equal(osNotices.length,0);
assert.match($('questionNotificationStatus').textContent,/未許可/);
await $('enableQuestionNotifications').listeners.click();
assert.equal(permissionCalls,1);assert.equal(osNotices.length,1);
await $('enableQuestionNotifications').listeners.click();assert.equal(permissionCalls,1);
assert.match($('questionNotificationStatus').textContent,/OS側の表示は保証されません/);
''')


@pytest.mark.parametrize('capability', ['denied', 'missing', 'insecure'])
def test_unavailable_notifications_are_honestly_labeled_and_never_prompt(capability):
    code = {'denied': "installNotifications('denied');", 'missing': 'delete globalThis.Notification;',
            'insecure': "installNotifications();window.isSecureContext=false;"}[capability]
    check(code + r'''
await prepareNotice();await $('enableQuestionNotifications').listeners.click();
assert.equal(permissionCalls,0);assert.equal(osNotices.length,0);assert.equal($('enableQuestionNotifications').disabled,true);
assert.match($('questionNotificationStatus').textContent,/利用できません|拒否/);assert.equal($('questionNotice').hidden,false);
''')


def test_os_failure_does_not_replay_or_claim_delivery():
    check(r'''
installNotifications();let attempts=0;
globalThis.Notification=class {static permission='granted';constructor(){attempts++;throw Error('unsupported');}};
await prepareNotice();renderState();assert.equal(attempts,1);
assert.match($('questionNotificationStatus').textContent,/表示できません/);
assert.equal($('questionNotice').hidden,false);assert.equal(requests.length,0);
''')


def test_notification_click_refreshes_and_opens_only_the_exact_pending_question():
    check(r'''
installNotifications();await prepareNotice();setQuestion(2,qid2);renderState();
const owner={instance:'instance-a',run:'run-b',agent:'agent-c',question:qid2};
const pending=openNotifiedQuestion(owner);assert.equal(ui.selectedAgent,'agent-a');
await drainStates();await pending;await drainStates();
assert.equal(ui.selectedRun,'run-b');assert.equal(ui.selectedAgent,'agent-c');
assert.equal(document.activeElement,$('humanQuestion'));assert(requests.every(item=>item.path.startsWith('/api/state')));
''')


@pytest.mark.parametrize('change', [
    "setQuestion(2,'q-'+'c'.repeat(32));",
    "Object.assign(summaries[2],{question:'',status:'working',status_reason:'model'});",
])
def test_old_os_click_cannot_select_a_replaced_or_finished_question(change):
    check(r'''
installNotifications();await prepareNotice();setQuestion(2,qid2);renderState();
const pending=openNotifiedQuestion({instance:'instance-a',run:'run-b',agent:'agent-c',question:qid2});
CHANGE
await drainStates();await pending;assert.equal(ui.selectedAgent,'agent-a');assert.equal(ui.selectedRun,'run-a');
'''.replace('CHANGE', change))


def test_notification_click_is_inert_after_instance_change_or_during_a_dialog():
    check(r'''
installNotifications();await prepareNotice();
await openNotifiedQuestion({instance:'retired-instance',run:'run-a',agent:'agent-a',question:qid});
$('settingsDialog').open=true;
await openNotifiedQuestion({instance:'instance-a',run:'run-a',agent:'agent-a',question:qid});
assert.equal(requests.length,0);assert.equal(ui.selectedAgent,'agent-a');
''')


def test_server_restart_closes_old_notifications_and_drops_draft_identity():
    check(r'''
installNotifications();await prepareNotice();editReply('Old server draft');
acceptServerInstance({instance_id:'instance-b'},true);
assert.equal(osNotices[0].closed,true);assert.equal(ui.questionNotifications.size,0);
assert.equal(ui.draftQuestions.size,0);assert.equal($('messageInput').value,'');
await openNotifiedQuestion({instance:'instance-a',run:'run-a',agent:'agent-a',question:qid});
assert.equal(requests.length,0);
''')


def test_resolved_notice_returns_only_its_own_hidden_focus_to_question_control():
    check(r'''
await prepareNotice();$('openQuestionNotice').focus();getAgent().question='';getAgent().status='working';getAgent().status_reason='model';
renderState();assert.equal($('questionNotice').hidden,true);assert.equal(document.activeElement,$('needsYou'));
''')


def test_question_reply_posts_the_captured_id_and_clears_only_accepted_draft():
    check(r'''
await prepareNotice();editReply('  Exact answer\n  ');const pending=send();
assert.deepEqual(requests[0].options.body,{text:'  Exact answer\n  ',question_id:qid});
resolve(0,{ok:true});await flush();await drainStates();await pending;
assert.equal($('messageInput').value,'');assert.equal(ui.draftQuestions.has('agent-a'),false);
assert.equal(requests.filter(item=>item.path.endsWith('/message')).length,1);
''')


@pytest.mark.parametrize('transition', ['replacement', 'fallback'])
def test_late_question_draft_is_kept_and_cannot_answer_the_next_question(transition):
    change = "setQuestion(0,qid2);" if transition == 'replacement' else r'''
setQuestion(0,qid,{resolution:'fallback',resolved_at:Date.now()/1000});
getAgent().question='';getAgent().status='working';getAgent().status_reason='model';
'''
    check(r'''
await prepareNotice();editReply('Original question answer');$('messageInput').focus();
CHANGE
renderState();await send();assert.equal(requests.length,0);
assert.equal($('messageInput').value,'Original question answer');assert.equal(ui.draftQuestions.get('agent-a'),qid);
assert.equal(document.activeElement,$('messageInput'));assert.equal($('sendMessage').disabled,true);
assert.match($('messageEligibility').textContent,/入力を始めた質問は終了または変更/);
'''.replace('CHANGE', change))


def test_clearing_then_rewriting_explicitly_starts_a_new_question_draft():
    check(r'''
await prepareNotice();editReply('Old');setQuestion(0,qid2);renderState();
editReply('');editReply('New answer');const pending=send();
assert.deepEqual(requests[0].options.body,{text:'New answer',question_id:qid2});
reject(0,new Error('Rejected'));await pending;assert.equal($('messageInput').value,'New answer');
''')


def test_blocked_fallback_keeps_the_same_question_draft_answerable():
    check(r'''
await prepareNotice();editReply('Human answer');setQuestion(0,qid,{resolution:'blocked',reason:'new_input'});renderState();
assert.equal(staleQuestionDraft(getAgent()),false);assert.equal($('sendMessage').disabled,false);
assert.match($('questionTiming').textContent,/同じ質問への人の回答を待ちます/);
const pending=send();assert.deepEqual(requests[0].options.body,{text:'Human answer',question_id:qid});
reject(0,new Error('Synthetic rejection'));await pending;
''')


def test_server_deadline_conflict_keeps_exact_text_without_retry_or_fallback_post():
    check(r'''
await prepareNotice();setQuestion(0,qid,{asked_at:1,deadline_at:91});renderState();
editReply('Late exact answer');const pending=send();assert.equal(requests[0].options.body.question_id,qid);
reject(0,Object.assign(new Error('Question has expired'),{code:'question_changed'}));await pending;
assert.equal($('messageInput').value,'Late exact answer');assert.equal(requests.length,1);
assert.match($('questionTiming').textContent,/サーバーの確定を確認中/);
assert.equal(getAgent().question_state.resolution,'pending');
''')


def test_reply_receipt_for_an_old_question_never_clears_or_labels_a_new_context():
    check(r'''
await prepareNotice();editReply('Old answer');const pending=send();
setQuestion(0,qid2);renderState();inlineStatus($('messageStatus'),'New question');
resolve(0,{ok:true});await flush();await drainStates();await pending;
assert.equal($('messageInput').value,'Old answer');assert.equal(ui.draftQuestions.get('agent-a'),qid);
assert.equal($('messageStatus').textContent,'New question');
assert.equal(requests.filter(item=>item.path.endsWith('/message')).length,1);
''')


def test_ordinary_draft_cannot_be_reinterpreted_as_an_answer_when_question_arrives():
    check(r'''
await wire();setBriefOpen(false);editReply('Ordinary instruction');setQuestion();renderState();await send();
assert.equal(ui.draftQuestions.get('agent-a'),null);assert.equal(requests.length,0);
assert.equal($('messageInput').value,'Ordinary instruction');
''')


@pytest.mark.parametrize('stored', [None, '', 'Older stored text'])
def test_poll_binds_unsaved_question_text_without_mutating_or_rebinding_the_draft(stored):
    stored_setup = "ui.drafts.delete('agent-a');" if stored is None else (
        "ui.drafts.set('agent-a'," + json.dumps(stored) + ');')
    check(r'''
await prepareNotice();STORED_SETUP
const storedBefore=ui.drafts.get('agent-a');$('messageInput').value='Current unsaved answer';
renderState();assert.equal(ui.drafts.get('agent-a'),storedBefore);assert.equal(ui.draftQuestions.get('agent-a'),qid);
setQuestion(0,qid2);renderState();renderState();
assert.equal(ui.drafts.get('agent-a'),storedBefore);assert.equal($('messageInput').value,'Current unsaved answer');
assert.equal(ui.draftQuestions.get('agent-a'),qid);assert.equal(staleQuestionDraft(getAgent()),true);
await send();assert.equal(requests.length,0);assert.equal(ui.draftQuestions.get('agent-a'),qid);
assert.equal($('messageInput').value,'Current unsaved answer');
'''.replace('STORED_SETUP', stored_setup))


def test_empty_visible_question_input_does_not_claim_a_stale_stored_draft():
    check(r'''
await prepareNotice();editReply('Older stored answer');setQuestion(0,qid2);
$('messageInput').value='';renderState();
assert.equal(ui.drafts.get('agent-a'),'Older stored answer');assert.equal(ui.draftQuestions.get('agent-a'),qid);
assert.equal(staleQuestionDraft(getAgent()),false);assert.equal($('messageInputCount').textContent,'0');
assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('bad', ['null', '{}', "{question_id:'wrong'}", "timedQuestion(qid,{deadline_at:'soon'})"])
def test_malformed_current_question_identity_fails_closed_without_os_notice(bad):
    check(r'''
installNotifications();await wire();setBriefOpen(false);ui.instanceId='instance-a';ui.networkConnected=true;
setQuestion();getAgent().question_state=BAD;renderState();editReply('Keep');await send();
assert.equal(requests.length,0);assert.equal(osNotices.length,0);assert.equal($('messageInput').value,'Keep');
assert.equal($('sendMessage').disabled,true);assert.match($('messageEligibility').textContent,/識別情報/);
'''.replace('BAD', bad))


def test_permission_and_legacy_questions_do_not_claim_automatic_approval():
    check(r'''
await prepareNotice();setQuestion(0,qid,{kind:'permission',deadline_at:null});renderState();
assert.match($('questionTiming').textContent,/自動回答せず/);assert.doesNotMatch($('questionTiming').textContent,/90秒/);
delete getAgent().question_state;renderState();assert.match($('questionTiming').textContent,/設定されていません/);
editReply('Legacy answer');const pending=send();assert.deepEqual(requests[0].options.body,{text:'Legacy answer'});
reject(0,new Error('Synthetic rejection'));await pending;
''')


def test_untrusted_recommendation_is_text_and_unchanged_question_keeps_reading_focus():
    check(r'''
await prepareNotice();setQuestion(0,qid,{recommendation:'<img src=x onerror=alert(1)>'});renderState();
$('humanQuestion').scrollTop=40;$('humanQuestion').focus();renderState();
assert.equal($('humanQuestion').scrollTop,40);assert.equal(document.activeElement,$('humanQuestion'));
assert.match($('questionTiming').textContent,/<img/);assert.equal($('questionTiming').children.length,0);
assert.equal(requests.length,0);
''')


def test_notice_controls_are_explicit_and_server_owns_the_only_fallback_timer():
    assert 'id="enableQuestionNotifications"' in HTML
    assert 'id="questionNoticeTitle" role="status" aria-live="polite"' in HTML
    assert 'id="questionTiming"' in HTML
    css = (STATIC / 'styles.css').read_text(encoding='utf-8')
    assert '.question-notifications{' in css and 'overflow-wrap:anywhere' in css
