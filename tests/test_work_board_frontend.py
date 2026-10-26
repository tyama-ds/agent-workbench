"""Run-owned work board callbacks with synthetic DOM and deferred transport.

No model, real user settings, or browser is required by this module.
"""
import pytest

from test_frontend import APP, HTML, run_javascript
from test_run_action_frontend import ACTION_DOM
from test_compact_frontend import FIXTURES
from test_cockpit_frontend import FOCUS
from test_settings_transfer_frontend import check as transfer_check
from test_credential_recovery_frontend import check as credential_check
from test_task_guidance import Elements


BOARD = r'''
const crypto=require('node:crypto').webcrypto;
Node.prototype.scrollIntoView=function(){this.scrolled=true;};
function post(seq,extra={}){return {seq,run_id:'run-a',author_kind:'agent',author_id:'agent-b',author_name:'技術担当',body:`メモ ${seq}`,reply_to:null,created_at:seq,...extra};}
function page(posts=[],extra={}){const last=posts.at(-1)?.seq||0;return {enabled:true,run_id:'run-a',posts,last_seq:last,next_after_seq:last,has_more:false,can_post:true,remaining_posts:200-last,redaction_revision:0,...extra};}
async function bootBoard(enabled=true){
 await initialize();clearTimeout(ui.preflightTimer);seedSelection();
 ui.state.runs.forEach(run=>run.work_board={enabled,post_count:0,last_seq:0});
 api=(path,options)=>new Promise((resolve,reject)=>requests.push({path,options,resolve,reject}));
 setCockpitView('board');
}
async function received(posts=[],extra={}){const index=requests.length-1;requests[index].resolve(page(posts,extra));await flush();}
function editBoard(value){$('workBoardInput').value=value;$('workBoardInput').listeners.input({type:'input'});}
function boardText(){return renderedText($('workBoardFeed'));}
function switchBoard(id){changeSelection(id,id==='run-a'?'agent-a':'agent-c');renderWorkBoard(getRun());}
function confirmed(index,seq=1){requests[index].resolve({ok:true,duplicate:false,post:post(seq,{author_kind:'human',author_id:null,author_name:'あなた',body:requests[index].options.body.body,reply_to:requests[index].options.body.reply_to??null})});}
'''


def check(source):
    result = run_javascript(ACTION_DOM + APP + FIXTURES + FOCUS + BOARD + '\n(async()=>{\n' + source + r'''
clearTimeout(ui.preflightTimer);
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_board_controls_have_unique_ids_accessible_roles_and_snapshot_explanation():
    tree = Elements()
    for ident in ('boardView', 'workBoardPanel', 'workBoardFeed', 'workBoardInput', 'workBoardSend', 'workBoardRetry', 'workBoardFields'):
        assert HTML.count(f'id="{ident}"') == 1
    assert tree.ids['workBoardFeed']['attrs']['role'] == 'log'
    assert tree.ids['workBoardFeed']['attrs']['aria-live'] == 'off'
    assert tree.ids['workBoardInput']['attrs']['maxlength'] == '2000'
    assert '開始済みの作業は開始時のオン／オフを保持' in HTML
    assert 'モデルの既読・理解を示しません' in HTML


@pytest.mark.parametrize('snapshot', ['off', 'legacy'])
def test_disabled_or_legacy_run_has_no_feed_composer_or_request(snapshot):
    check(r'''
await bootBoard(false);
''' + ("delete getRun().work_board;renderWorkBoard(getRun());" if snapshot == 'legacy' else '') + r'''
assert.equal(requests.length,0);assert($('workBoardFeed').hidden);assert($('workBoardForm').hidden);
assert($('workBoardMode').textContent.includes('オフ'));assert($('workBoardBadge').hidden);
ui.config={work_board:{enabled:true}};renderWorkBoard(getRun());assert.equal(requests.length,0);
''')


def test_network_poll_does_not_fetch_enabled_board_until_opened():
    check(r'''
await initialize();seedSelection();getRun().work_board={enabled:true,last_seq:3,post_count:3};renderState();
assert.equal(requests.length,0);assert.equal($('workBoardBadge').textContent,'未表示 3');
setCockpitView('board');assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/runs/run-a/work-board?after_seq=0&limit=50');
''')


def test_short_pages_follow_actual_cursor_until_complete_and_preserve_exact_text():
    check(r'''
await bootBoard();await received([post(1,{body:'  行1\n行2  '})],{last_seq:3,has_more:true});
assert.equal(requests.length,2);assert(requests[1].path.includes('after_seq=1'));
await received([post(2)],{last_seq:3,has_more:true});assert.equal(requests.length,3);
assert(requests[2].path.includes('after_seq=2'));await received([post(3)]);
assert.equal(workBoardState('run-a').cursor,3);assert.equal($('workBoardFeed').children.length,3);
assert(boardText().includes('  行1\n行2  '));assert.equal(requests.length,3);
''')


@pytest.mark.parametrize('mutation', [
    "value.run_id='run-b'", "value.posts[0].run_id='run-b'", "value.posts[0].seq=2",
    "value.posts[0].author_kind='system'", "value.next_after_seq=0", "value.has_more=true",
    "value.last_seq=201", "value.posts=[];value.has_more=true;value.next_after_seq=0",
])
def test_bad_feed_response_never_inserts_unverified_posts_or_loops(mutation):
    check("await bootBoard();const value=page([post(1)]);" + mutation + r''';
requests[0].resolve(value);await flush();assert(workBoardState('run-a').error);
assert.equal(workBoardState('run-a').posts.size,0);assert.equal(requests.length,1);
renderState();assert.equal(requests.length,1);
''')


def test_same_owner_poll_preserves_composer_focus_node_and_user_scroll():
    check(r'''
await bootBoard();await received([post(1)]);editBoard('下書き');$('workBoardInput').focus();
const old=$('workBoardFeed').children[0];$('workBoardFeed').scrollTop=30;rememberWorkBoardView();
renderState();renderState();assert.equal($('workBoardFeed').children[0],old);
assert.equal(document.activeElement,$('workBoardInput'));assert.equal($('workBoardInput').value,'下書き');
getRun().work_board={enabled:true,last_seq:2,post_count:2};renderState();await received([post(2)]);
assert.equal($('workBoardFeed').scrollTop,30);assert(!$('workBoardNew').hidden);
assert.equal(document.activeElement,$('workBoardInput'));assert.equal($('workBoardFeed').children[0],old);
$('workBoardNew').listeners.click();assert.equal($('workBoardFeed').scrollTop,$('workBoardFeed').scrollHeight);assert($('workBoardNew').hidden);
''')


def test_bottom_view_follows_new_posts_without_replacing_existing_nodes():
    check(r'''
await bootBoard();await received([post(1)]);const old=$('workBoardFeed').children[0];
getRun().work_board.last_seq=2;renderWorkBoard(getRun());await received([post(2)]);
assert.equal($('workBoardFeed').children[0],old);assert.equal($('workBoardFeed').scrollTop,$('workBoardFeed').scrollHeight);
assert($('workBoardBadge').hidden);
''')


def test_drafts_and_reply_targets_belong_to_run_and_survive_view_switch():
    check(r'''
await bootBoard();await received([post(1)]);workBoardState('run-a').nodes.get(1).reply.listeners.click();editBoard('Aの入力');
setCockpitView('network');setCockpitView('board');assert.equal($('workBoardInput').value,'Aの入力');
switchBoard('run-b');await received([],{run_id:'run-b'});editBoard('Bの入力');
switchBoard('run-a');assert.equal($('workBoardInput').value,'Aの入力');assert.equal(workBoardState('run-a').draft.reply_to,1);
assert.equal(workBoardState('run-b').draft.body,'Bの入力');assert.equal(requests.length,2);
''')


def test_late_get_after_run_switch_and_aba_is_discarded():
    check(r'''
await bootBoard();switchBoard('run-b');switchBoard('run-a');
requests[0].resolve(page([post(1,{body:'古いA応答'})]));await flush();
assert(!boardText().includes('古いA応答'));assert.equal(workBoardState('run-a').posts.size,0);
assert.equal(requests.length,3);requests[1].resolve(page([],{run_id:'run-b'}));await flush();
requests[2].resolve(page([post(1,{body:'新しいA応答'})]));await flush();assert(boardText().includes('新しいA応答'));
''')


def test_plain_text_post_and_quote_never_create_html_or_claim_model_read():
    check(r'''
await bootBoard();const payload='<img src=x onerror=alert(1)> & "';
await received([post(1,{body:payload,author_name:payload}),post(2,{reply_to:1,body:'返信'})]);
assert(boardText().includes(payload));assert.equal($('workBoardFeed').querySelectorAll('*').filter(n=>['IMG','SCRIPT'].includes(n.tagName)).length,0);
const node=workBoardState('run-a').nodes.get(2);assert(node.quote.textContent.includes(payload));node.quote.listeners.click();
assert.equal(document.activeElement,workBoardState('run-a').nodes.get(1).row);
assert(!boardText().includes('既読'));
''')


def test_missing_reply_parent_is_explicit_and_never_fabricates_quote():
    check(r'''
await bootBoard();await received();const board=workBoardState('run-a');board.posts.set(2,post(2,{reply_to:1}));
board.lastSeq=2;board.cursor=2;renderWorkBoard(getRun());const quote=board.nodes.get(2).quote;
assert(quote.textContent.includes('参照 #1'));assert(quote.textContent.includes('まだ取得'));assert(quote.disabled);
board.posts.set(1,post(1,{body:'実際の親'}));renderWorkBoard(getRun());assert(quote.textContent.includes('実際の親'));assert(!quote.disabled);
''')


@pytest.mark.parametrize('state', ['terminal', 'full', 'stopping'])
def test_no_new_posts_when_terminal_full_or_stopping_but_history_remains(state):
    setup = {'terminal': "getRun().status='done';", 'stopping': "getRun().status='stopping';", 'full': "workBoardState('run-a').remaining=0;workBoardState('run-a').canPost=false;"}[state]
    check("await bootBoard();await received([post(1)]);" + setup + r'''
renderWorkBoard(getRun());editBoard('新しい投稿');await submitWorkBoardPost();
assert.equal(requests.length,1);assert($('workBoardSend').disabled);assert(boardText().includes('メモ 1'));
''')


def test_submit_captures_human_payload_reply_and_id_and_prevents_double_submit():
    check(r'''
await bootBoard();await received([post(1)]);workBoardState('run-a').nodes.get(1).reply.listeners.click();editBoard('  返信\n本文  ');
const pending=submitWorkBoardPost();await submitWorkBoardPost();assert.equal(requests.length,2);
const body=requests[1].options.body;assert.equal(body.body,'  返信\n本文  ');assert.equal(body.reply_to,1);
assert.match(body.client_post_id,/^[A-Za-z0-9_-]{16,128}$/);assert.deepEqual(Object.keys(body).sort(),['body','client_post_id','reply_to']);
confirmed(1,2);await pending;assert.equal($('workBoardInput').value,'');assert.equal(workBoardState('run-a').draft.reply_to,null);
assert.equal(requests.length,3);assert.equal(requests[2].options,undefined);assert(requests[2].path.includes('after_seq=1'));
assert($('workBoardStatus').textContent.includes('閲覧・理解は未確認'));
''')


@pytest.mark.parametrize('change', ['typing', 'ime'])
def test_late_post_ack_preserves_newer_draft_and_ime(change):
    alter = "editBoard('新しい下書き');" if change == 'typing' else "$('workBoardInput').listeners.compositionstart();$('workBoardInput').value='変換中';"
    check("await bootBoard();await received();editBoard('送信する文');const pending=submitWorkBoardPost();" + alter + r'''
confirmed(1);await pending;assert.notEqual($('workBoardInput').value,'');assert.equal(workBoardState('run-a').operation,null);
''')


def test_old_post_response_never_changes_other_run_draft_or_status():
    check(r'''
await bootBoard();await received();editBoard('A投稿');const pending=submitWorkBoardPost();switchBoard('run-b');
await received([],{run_id:'run-b'});editBoard('B下書き');const status=$('workBoardStatus').textContent;
confirmed(1);await pending;assert.equal($('workBoardInput').value,'B下書き');assert.equal($('workBoardStatus').textContent,status);
assert.equal(workBoardState('run-a').operation,null);assert.equal(workBoardState('run-b').posts.size,0);
''')


@pytest.mark.parametrize('condition', ['terminal', 'full'])
def test_unknown_outcome_retry_preserves_old_payload_id_after_new_draft_and_stop(condition):
    setup = "getRun().status='done';" if condition == 'terminal' else "workBoardState('run-a').canPost=false;workBoardState('run-a').remaining=0;"
    check(r'''
await bootBoard();await received();editBoard('未確認の元投稿');let pending=submitWorkBoardPost();
const original=structuredClone(requests[1].options.body);requests[1].reject(Object.assign(new Error('503'),{outcomeUnknown:true}));await pending;
editBoard('別の新しい下書き');
''' + setup + r'''
renderWorkBoard(getRun());assert(!$('workBoardUncertain').hidden);assert(!$('workBoardRetry').disabled);
await submitWorkBoardPost();assert.equal(requests.length,2);
pending=submitWorkBoardPost(true);assert.deepEqual(requests[2].options.body,original);
requests[2].resolve({ok:true,duplicate:true,post:post(1,{author_kind:'human',author_id:null,author_name:'あなた',body:original.body})});await pending;
assert.equal($('workBoardInput').value,'別の新しい下書き');assert.equal(workBoardState('run-a').operation,null);
''')


def test_malformed_success_is_unknown_not_safe_to_resend_new_id():
    check(r'''
await bootBoard();await received();editBoard('本文');const pending=submitWorkBoardPost();
requests[1].resolve({ok:true,duplicate:false,post:post(1,{run_id:'run-b',author_kind:'human',author_id:null})});await pending;
assert.equal(workBoardState('run-a').operation.status,'unknown');assert.equal($('workBoardInput').value,'本文');
assert.equal(workBoardState('run-a').posts.size,0);assert.equal(requests.length,2);
''')


@pytest.mark.parametrize('code', ['work_board_disabled', 'work_board_read_only', 'work_board_full', 'work_board_conflict'])
def test_known_rejection_retains_draft_but_not_uncertain_retry(code):
    check("await bootBoard();await received();editBoard('本文');const pending=submitWorkBoardPost();requests[1].reject(Object.assign(new Error('拒否'),{code:" + repr(code) + r'''}));await pending;
assert.equal(workBoardState('run-a').operation,null);assert.equal($('workBoardInput').value,'本文');assert($('workBoardUncertain').hidden);
''')


@pytest.mark.parametrize('value', ['', '   ', 'x' * 2001])
def test_empty_or_oversize_message_never_posts(value):
    import json
    check("await bootBoard();await received();editBoard(" + json.dumps(value) + r''');await submitWorkBoardPost();assert.equal(requests.length,1);assert($('workBoardSend').disabled);
''')


def test_redaction_revision_clears_unchanged_count_quote_and_reloads_from_start():
    check(r'''
await bootBoard();await received([post(1,{body:'secret old'}),post(2,{reply_to:1})]);
workBoardState('run-a').nodes.get(1).reply.listeners.click();ui.boardRedactionRevision=0;
const state=fullState();state.runs[0].work_board={enabled:true,post_count:2,last_seq:2};state.redaction_revision=1;
applyState(state,{run:'run-a',agent:'agent-a',generation:ui.selectionGeneration});renderState();
assert(!boardText().includes('secret old'));assert(!$('workBoardReplyBody').textContent.includes('secret old'));
assert(requests[1].path.includes('after_seq=0'));requests[1].reject(new Error('取得失敗'));await flush();
assert(!boardText().includes('secret old'));assert(workBoardState('run-a').error);
''')


def test_redaction_epoch_rejects_old_inflight_get_and_old_unknown_preview():
    check(r'''
await bootBoard();const board=workBoardState('run-a');board.operation={id:'old-client-id-123456',body:'hidden secret',reply_to:null,status:'unknown',revision:0};
invalidateWorkBoardContent();renderWorkBoard(getRun());assert.equal(requests.length,2);
requests[0].resolve(page([post(1,{body:'hidden secret'})]));await flush();assert(!boardText().includes('hidden secret'));
assert(!$('workBoardUncertainBody').textContent.includes('hidden secret'));
requests[1].resolve(page([post(1,{body:'[REDACTED]'})]));await flush();assert(boardText().includes('[REDACTED]'));
assert.equal(board.operation.body,'hidden secret'); // Retry identity remains immutable, not displayed.
''')


def test_feed_mask_revision_change_restarts_at_zero_without_mixed_public_text():
    check(r'''
await bootBoard();await received([post(1,{body:'old secret'})]);
getRun().work_board.last_seq=2;renderWorkBoard(getRun());
await received([post(2)],{redaction_revision:1});assert(!boardText().includes('old secret'));
assert(requests[2].path.includes('after_seq=0'));await received([post(1,{body:'[MASK]'}),post(2)],{redaction_revision:1});
assert(boardText().includes('[MASK]'));assert.equal(workBoardState('run-a').cursor,2);
''')


@pytest.mark.parametrize('route', ['state', 'feed'])
def test_redaction_capacity_failure_hides_old_body_quote_without_erasing_draft(route):
    action = "const pending=pollState();" if route == 'state' else "const pending=loadWorkBoard(getRun(),true);"
    check(r'''
await bootBoard();await received([post(1,{body:'old secret'})]);editBoard('my draft');
workBoardState('run-a').nodes.get(1).reply.listeners.click();
''' + action + r'''
requests[1].reject(Object.assign(new Error('capacity'),{code:'redaction_capacity'}));await pending;
assert(!boardText().includes('old secret'));assert(!$('workBoardReplyBody').textContent.includes('old secret'));
assert.equal($('workBoardInput').value,'my draft');assert.equal(workBoardState('run-a').posts.size,0);
assert(workBoardState('run-a').error.includes('秘密情報'));assert.equal(requests.length,2);
''')


def test_board_setting_import_is_draft_and_regular_save_retains_other_groups():
    transfer_check(r'''
await boot();$('settingsForm').append($('workBoardFields'));const saved=structuredClone(ui.config),beforeTask=runPayload();
const pending=importSettingsFile(selected());await flush();const value=preview();value.config.work_board={enabled:true};requests[0].resolve(value);await pending;paths();
assert.equal(ui.config.work_board.enabled,false);assert.equal(collectConfig().work_board.enabled,true);assert(ui.settingsDirty);
assert.deepEqual(runPayload(),beforeTask);const saving=submit();assert.equal(requests[1].options.body.config.work_board.enabled,true);
for(const group of ['orchestration','paths','python','selenium','local','limits'])assert.deepEqual(requests[1].options.body.config[group],saved[group]);
assert.equal(requests[1].options.body.config_revision,4);accept(1);await saving;assert.equal(ui.config.work_board.enabled,true);
''')


def test_credential_update_clears_board_before_request_and_after_unknown_response():
    credential_check(r'''
await wire();const board=workBoardState('r');board.posts.set(1,{body:'old secret'});board.loaded=true;
$('workBoardFeed').append(element('p','','old secret'));const c=control();c.input.value='new secret';const pending=press();
assert.equal(board.posts.size,0);assert.equal($('workBoardFeed').children.length,0);
const epoch=board.epoch;requests[0].reject(Object.assign(new Error('lost'),{outcomeUnknown:true}));await pending;assert(board.epoch>epoch);
''')
