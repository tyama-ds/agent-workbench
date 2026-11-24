"""An operation that waits for the human's approval is announced like a question; synthetic DOM only."""
from test_frontend import HTML
from test_question_notice_frontend import SETUP
from test_questions_frontend import check as question_check

APPROVALS = r'''
const aid='ap-'+'a'.repeat(24),aid2='ap-'+'b'.repeat(24);
function setApproval(index=0,id=aid,overrides={}){
  const now=Date.now()/1000;
  Object.assign(summaries[index],{status:'waiting',approval:{id,tool:'screen_view',summary:'Private screen summary',requested_at:now,expires_at:now+180,...overrides}});
  const current=ui.state.agents.find(agent=>agent.id===summaries[index].id);
  if(current)Object.assign(current,structuredClone(summaries[index]));
}
function clearApproval(index=0){
  summaries[index].approval=null;const current=ui.state.agents.find(agent=>agent.id===summaries[index].id);if(current)current.approval=null;
}
async function prepareApproval(){
  await wire();setBriefOpen(false);ui.instanceId='instance-a';ui.networkConnected=true;ui.detailError=false;
}
'''


def check(source):
    question_check(SETUP + APPROVALS + source)


def test_a_waiting_approval_is_announced_once_and_says_nothing_of_its_content():
    check(r'''
installNotifications();await prepareApproval();setApproval();renderState();renderState();
setConnection(false,'offline');setConnection(true,'online');
assert.equal(osNotices.length,1);assert.equal(permissionCalls,0);
assert.equal(osNotices[0].title,'Workbench: 承認待ちの操作があります');
assert.equal(osNotices[0].options.body,'アプリを開いて内容を確認してください。期限までに応答がないと、却下として扱われます。');
assert.doesNotMatch(JSON.stringify(osNotices[0].options),/Private|screen_view|First task|PM A/);
assert.equal($('approvalQueue').hidden,false);assert.equal(requests.length,0);
// Answered (the request is gone): its announcement is closed. Another request is announced on its own.
clearApproval();renderState();assert.equal(osNotices[0].closed,true);
setApproval(0,aid2,{expires_at:0});renderState();
assert.equal(osNotices.length,2);assert.equal(osNotices[1].options.body,'アプリを開いて内容を確認してください。');
// The first request again (the same id): not announced a second time in this page session.
setApproval(0,aid);renderState();assert.equal(osNotices.length,2);
''')


def test_nothing_is_announced_without_permission_or_for_a_stopped_or_saved_run():
    check(r'''
installNotifications('default');await prepareApproval();setApproval();renderState();
assert.equal(osNotices.length,0);assert.equal(permissionCalls,0);
installNotifications('denied');renderState();assert.equal(osNotices.length,0);
installNotifications();ui.state.runs.find(run=>run.id===ui.selectedRun).status='stopped';setApproval(0,aid2);renderState();
assert.equal(osNotices.length,0);
''')
    assert '<summary>質問と承認のブラウザー通知</summary>' in HTML
