"""Message acceptance receipts through production parsing and deferred callbacks."""
import json

import pytest

from test_frontend import APP, run_javascript
from test_disclosure_focus_frontend import FOCUS_DOM
from test_questions_frontend import SETUP
from test_run_action_frontend import ACTION_DOM, ACTION_FIXTURES


TRANSPORT = r'''
const httpRequests=[];
async function wireHttp(){
  await wire();setBriefOpen(false);
  const fixtureApi=api;
  api=(path,options={})=>path.endsWith('/message')?productionApi(path,options):fixtureApi(path,options);
  globalThis.fetch=(path,options)=>new Promise((resolve,reject)=>httpRequests.push({path,options,resolve,reject}));
}
function respond(index,status,raw,delayJson=false,bodyFailure=false){
  const request=httpRequests[index],response=new Response(status===204?null:raw,{status,headers:{'Content-Type':'application/json'}});
  const parse=response.json.bind(response);
  if(delayJson||bodyFailure)response.json=()=>{
    request.bodyStarted=true;
    return new Promise((resolve,reject)=>{
      request.finishBody=()=>bodyFailure?reject(new Error('Synthetic body interruption')):resolve(parse());
      if(!delayJson)request.finishBody();
    });
  };
  request.resolve(response);
}
function assertPost(text){
  assert.equal(httpRequests.length,1);
  assert.equal(httpRequests[0].path,'/api/agents/agent-a/message');
  assert.equal(httpRequests[0].options.method,'POST');
  assert.equal(httpRequests[0].options.body,JSON.stringify({text}));
  assert.equal(httpRequests[0].options.credentials,'same-origin');
}
async function settle(pending){await flush();await drainStates();await pending;}
'''


def check(source):
    fixtures = ACTION_FIXTURES.replace('api=(path)=>{', 'api=(path,options={})=>{').replace(
        'requests.push({path,resolve', 'requests.push({path,options,resolve')
    result = run_javascript(ACTION_DOM + FOCUS_DOM + APP + '\nconst productionApi=api;\n' +
                            fixtures + SETUP + TRANSPORT + '\n(async()=>{\n' + source + r'''
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


RESPONSES = [
    (200, '{"ok":true}', 'accepted'),
    (200, '{"ok":true,"extra":"ignored"}', 'accepted'),
    (200, '{}', 'unknown'),
    (200, '{"message":"accepted"}', 'unknown'),
    *[(200, json.dumps({'ok': value}), 'unknown')
      for value in (None, 0, 1, '', 'true', 'false', [], {})],
    (200, '{"ok":false,"error":"Synthetic rejection"}', 'rejected'),
    *[(200, json.dumps(value), 'unknown')
      for value in (None, False, True, 0, 1, '', 'true', [], [{'ok': True}])],
    (200, '', 'unknown'), (200, '{', 'unknown'), (204, '', 'unknown'),
    (400, '{"ok":false,"error":"Synthetic rejection"}', 'rejected'),
    (409, '{"ok":false,"error":"Synthetic rejection"}', 'rejected'),
    (401, '{"ok":false,"error":"Synthetic rejection"}', 'auth'),
    (500, '{"ok":false,"error":"Synthetic server failure"}', 'unknown'),
    (503, '{', 'unknown'),
    (400, '{"ok":true}', 'rejected'),
]


@pytest.mark.parametrize('status,raw,outcome', RESPONSES)
def test_actual_api_and_submit_require_literal_positive_receipt(status, raw, outcome):
    check(r'''
await wireHttp();const text='  Exact 日本語 😀\n\t  ';editReply(text);$('messageInput').focus();
const pending=send();await send();assertPost(text);assert.equal(ui.busyMessage,true);
respond(0,STATUS,RAW);await settle(pending);
const accepted=OUTCOME==='accepted';
assert.equal($('messageInput').value,accepted?'':text);
assert.equal(ui.drafts.has('agent-a'),!accepted);
if(!accepted)assert.equal(ui.drafts.get('agent-a'),text);
assert.equal($('messageInputCount').textContent,accepted?'0':'1');
assert.equal(ui.busyMessage,false);assert.equal(document.activeElement,$('messageInput'));
const feedback=$('messageStatus').textContent;
if(accepted)assert.equal(feedback,'送信しました。');
else {assert(feedback);assert(!feedback.includes('送信しました'));assert(!/未送信|送信されていません/.test(feedback));}
assert.equal(feedback.includes('送信結果は未確認です。'),OUTCOME==='unknown');
assert.equal(requests.filter(request=>request.path.startsWith('/api/state')).length,accepted?1:0);
if(OUTCOME==='auth')assert.equal(ui.authenticated,false);
else {const poll=pollState();await drainStates();await poll;}
assertPost(text);
'''.replace('STATUS', str(status)).replace('RAW', json.dumps(raw))
          .replace('OUTCOME', json.dumps(outcome)))


@pytest.mark.parametrize('failure', ['TimeoutError', 'TypeError', 'body'])
def test_transport_or_body_failure_keeps_exact_text_without_replay(failure):
    finish = ("respond(0,200,'{\"ok\":true}',false,true);" if failure == 'body' else
              f"httpRequests[0].reject(Object.assign(new Error('Synthetic interruption'),{{name:{json.dumps(failure)}}}));")
    check(r'''
await wireHttp();const text='  Retain exact\n日本語  ';editReply(text);const pending=send();
FINISH
await settle(pending);assertPost(text);assert.equal($('messageInput').value,text);
assert.equal(ui.drafts.get('agent-a'),text);assert.equal($('messageInputCount').textContent,'1');
assert.match($('messageStatus').textContent,/送信結果は未確認です。/);
assert(!/送信しました|未送信|送信されていません/.test($('messageStatus').textContent));
assert.equal(requests.filter(request=>request.path.startsWith('/api/state')).length,0);
const poll=pollState();await drainStates();await poll;assertPost(text);
'''.replace('FINISH', finish))


OWNERS = {
    'current': '',
    'different_edit': "editReply('Newer text');",
    'same_text_edit': "editReply('Interim');editReply(text);",
    'other_agent': "selectAgent('agent-b');await drainStates();editReply('Current B');",
    'other_team': "selectRun('run-b');await drainStates();editReply('Current C');",
    'agent_aba': "selectAgent('agent-b');await drainStates();selectAgent('agent-a');await drainStates();",
    'edited_aba': "selectAgent('agent-b');await drainStates();selectAgent('agent-a');await drainStates();editReply('Interim');editReply(text);",
    'team_aba': "selectRun('run-b');await drainStates();selectRun('run-a');await drainStates();",
}
OUTCOMES = {
    'accepted': 'resolve(0,{ok:true});',
    'missing': 'resolve(0,{});',
    'rejected': "reject(0,new Error('Synthetic rejection'));",
    'unknown': "reject(0,Object.assign(new Error('Synthetic unknown'),{outcomeUnknown:true}));",
}


@pytest.mark.parametrize('owner', OWNERS)
@pytest.mark.parametrize('outcome', OUTCOMES)
def test_deferred_callback_obeys_existing_selection_and_draft_epochs(owner, outcome):
    check(r'''
await wire();setBriefOpen(false);const text='  Submitted 日本語\n  ';editReply(text);const pending=send();
assert.equal(requests[0].path,'/api/agents/agent-a/message');assert.deepEqual(requests[0].options.body,{text});
OWNER
$('messageInput').focus();inlineStatus($('messageStatus'),'Newer feedback');const current=$('messageInput').value;
await send();assert.equal(requests.filter(request=>request.path.endsWith('/message')).length,1);
FINISH
await settle(pending);
const currentClear=OWNER_NAME==='current'&&OUTCOME==='accepted';
const otherClear=['other_agent','other_team'].includes(OWNER_NAME)&&OUTCOME==='accepted';
assert.equal($('messageInput').value,currentClear?'':current);
assert.equal(ui.drafts.has('agent-a'),!(currentClear||otherClear));
if(!currentClear&&!otherClear)assert.equal(ui.drafts.get('agent-a'),OWNER_NAME==='different_edit'?'Newer text':text);
if(OWNER_NAME!=='current')assert.equal($('messageStatus').textContent,'Newer feedback');
else if(currentClear)assert.equal($('messageStatus').textContent,'送信しました。');
else {assert(!/送信しました|未送信|送信されていません/.test($('messageStatus').textContent));
  assert.equal($('messageStatus').textContent.includes('送信結果は未確認です。'),['missing','unknown'].includes(OUTCOME));}
assert.equal(document.activeElement,$('messageInput'));assert.equal(ui.busyMessage,false);
const count=['other_agent','other_team'].includes(OWNER_NAME)?(otherClear?1:2):(currentClear?0:1);
assert.equal($('messageInputCount').textContent,String(count));
const poll=pollState();await drainStates();await poll;
assert.equal(requests.filter(request=>request.path.endsWith('/message')).length,1);
'''.replace('OWNER_NAME', json.dumps(owner)).replace('OUTCOME', json.dumps(outcome))
          .replace('OWNER', OWNERS[owner]).replace('FINISH', OUTCOMES[outcome]))


@pytest.mark.parametrize('phase', ['fetch', 'json'])
@pytest.mark.parametrize('raw', ['{"ok":true}', '{}'])
@pytest.mark.parametrize('aba', [False, True])
def test_production_response_and_json_waits_keep_one_flight_and_current_ownership(phase, raw, aba):
    check(r'''
await wireHttp();const text='  Same text\n  ';editReply(text);const pending=send();
if(PHASE==='json'){respond(0,200,RAW,true);await flush();assert.equal(httpRequests[0].bodyStarted,true);}
if(ABA){selectAgent('agent-b');await drainStates();selectAgent('agent-a');await drainStates();editReply('Interim');editReply(text);}
inlineStatus($('messageStatus'),'Current feedback');$('messageInput').focus();await send();assertPost(text);
if(PHASE==='json')httpRequests[0].finishBody();else respond(0,200,RAW);
await flush();
const clears=!ABA&&RAW==='{"ok":true}';
assert.equal($('messageInput').value,clears?'':text);assert.equal($('messageInputCount').textContent,clears?'0':'1');
if(clears){assert.equal(ui.busyMessage,true);assert.equal($('sendMessage').disabled,true);await send();assertPost(text);}
await settle(pending);assertPost(text);
if(ABA)assert.equal($('messageStatus').textContent,'Current feedback');
else assert.equal($('messageStatus').textContent.includes('送信結果は未確認です。'),!clears);
assert.equal(document.activeElement,$('messageInput'));assert.equal(ui.busyMessage,false);
'''.replace('PHASE', json.dumps(phase)).replace('RAW', json.dumps(raw)).replace('ABA', json.dumps(aba)))


def test_message_ack_gate_does_not_change_shared_api_for_state_objects():
    check(r'''
await wireHttp();globalThis.fetch=async()=>new Response('{"runs":[],"agents":[]}');
assert.deepEqual(await productionApi('/api/state'),{runs:[],agents:[]});
''')
