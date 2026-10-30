"""Reference audit presentation only; synthetic DOM and deferred transport.

These cases define UI regressions, not dictionary truth or real-model success.
"""
import pytest

from test_dynamic_network_frontend import check as network_check


FIXTURE = r'''
function auditNodes(node){return [node,...node.children.flatMap(auditNodes)];}
function auditText(node){return auditNodes(node).map(node=>node.textContent).join(' ');}
function auditClass(name){return auditNodes($('activityFeed')).filter(node=>node.className.split(' ').includes(name));}
function auditFact(step=1){return {step,participant_key:'A',submission_generation:1,
 predecessor:{kind:step===1?'seed':'accepted_step',step:step-1,value:step===1?'りんご':'めだか'},
 expected_head:step===1?'ご':'か',value:step===1?'ごま':'かさ',meaning:step===1?'小さな種を食用にする植物':'雨や日差しをよける道具',
 reference:{entry_id:step===1?'word01':'word44',entry_sha256:'a'.repeat(64),catalog_sha256:'b'.repeat(64),semantic_scope:'reference_match_only'}};}
function auditPayload(scope='step'){return {schema_version:1,source:'application',scope,workflow_id:'workflow-1',generation:1,decision:'accept',
 facts:scope==='step'?[auditFact()]:[auditFact(),auditFact(4)],comment:{text:'りんごの末尾は「お」です（誤った原文）',verified:false},semantic_scope:'reference_match_only',
 ...(scope==='worker_report'?{worker_id:'agent-b',result_revision:2}:{})};}
function auditEvent(payload=auditPayload(),extra={}){return {id:31,run_id:'run-a',agent_id:'agent-a',kind:'reference_audit',text:JSON.stringify(payload),at:100,...extra};}
function prepareAudit(event=auditEvent()){prepareNetwork([event]);getRun().pm_agent_ids=['agent-a'];renderRun();}
'''


def check(source):
    network_check(FIXTURE + source)


def test_canonical_facts_and_false_pm_comment_are_visibly_separate():
    check(r'''
prepareAudit();const before=JSON.stringify(ui.state),facts=auditClass('reference-audit')[0],comment=auditClass('reference-audit-comment')[0];
assert(facts);assert(comment);assert.notEqual(facts,comment);assert.equal(auditClass('reference-audit-fact').length,1);
assert.match(auditText(facts),/固定参照との構造化照合/);assert.match(auditText(facts),/前の語（開始語）：りんご/);
assert.match(auditText(facts),/必要な先頭文字：ご → 実値：ごま/);assert.match(auditText(facts),/小さな種を食用にする植物/);
assert.match(auditText(facts),/word01/);assert(auditText(facts).includes('a'.repeat(64)));assert(auditText(facts).includes('b'.repeat(64)));
assert.match(auditText(facts),/一般辞書の正しさ・PMの意味理解・現在の承認や完了は確認しません/);
assert.doesNotMatch(auditText(facts),/誤った原文/);assert.match(auditText(comment),/文章の正しさは未検証/);
assert(auditText(comment).includes(auditPayload().comment.text));renderRun();assert.equal(JSON.stringify(ui.state),before);assert.equal(requests.length,0);
''')


def test_formal_report_keeps_all_own_steps_revision_and_historical_generation():
    check(r'''
prepareAudit(auditEvent(auditPayload('worker_report')));getRun().coordination={schema_version:1,generation:2};renderRun();
assert.equal(auditClass('reference-audit-fact').length,2);const text=auditText(auditClass('reference-audit')[0]);
assert.match(text,/第1手/);assert.match(text,/第4手/);assert.match(text,/前の語（第3手）：めだか/);
assert.match(text,/正式報告の監査 · 担当ID agent-b · 報告版 2/);assert.match(text,/世代 1/);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('kind', ['mail', 'tool', 'assistant', 'ordered_reviewed', 'worker_report_review'])
def test_similar_json_in_model_or_legacy_events_is_never_promoted(kind):
    check("const kind=" + repr(kind) + r''';prepareAudit(auditEvent(auditPayload(),{kind}));
assert.equal(auditClass('reference-audit').length,0);assert.equal(auditClass('reference-audit-comment').length,0);
assert(auditText($('activityFeed')).includes(JSON.stringify(auditPayload())));
if(['ordered_reviewed','worker_report_review'].includes(kind))assert.match(auditText($('activityFeed')),/過去のPMコメント／構造化照合記録なし/);
assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('change', [
    "payload.source='model';", "payload.schema_version=2;", "payload.extra=true;",
    "payload.semantic_scope='dictionary_truth';", "payload.decision='revise';",
    "payload.comment.verified=true;", "payload.comment.extra='claimed';",
    "payload.generation=true;", "payload.generation=258;", "delete payload.workflow_id;",
    "payload.facts=[];", "payload.facts.push(auditFact());", "payload.facts[0].step=true;",
    "payload.facts[0].submission_generation=2;", "payload.facts[0].participant_key='X'.repeat(25);",
    "delete payload.facts[0].meaning;", "payload.facts[0].meaning='x'.repeat(513);",
    "payload.facts[0].value='x'.repeat(129);", "payload.facts[0].expected_head='ごま';",
    "payload.facts[0].predecessor.step=1;", "payload.facts[0].predecessor.kind='accepted_step';",
    "payload.facts[0].predecessor.extra='receipt';", "payload.facts[0].reference.entry_id='x'.repeat(41);",
    "payload.facts[0].reference.entry_sha256='a'.repeat(63);",
    "payload.facts[0].reference.catalog_sha256='g'.repeat(64);",
    "payload.facts[0].reference.semantic_scope='general_truth';",
    "payload.facts[0].reference.grant='private';", "payload.worker_id='agent-b';",
    "payload.facts[0].meaning='[redacted]';", "payload.workflow_id='[redacted]';",
])
def test_invalid_or_masked_required_facts_fall_back_without_verified_display(change):
    check("const payload=auditPayload();" + change + r'''
const event=auditEvent(payload);prepareAudit(event);assert.equal(auditClass('reference-audit').length,0);
assert.match(auditText($('activityFeed')),/構造化照合を確認できない記録（未検証）/);
assert(auditText($('activityFeed')).includes(event.text));assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('change', [
    "payload.worker_id='agent-a';", "payload.worker_id='unknown-worker';",
    "payload.result_revision=0;", "payload.result_revision=true;",
    "payload.facts.reverse();", "payload.facts[1].step=1;",
    "payload.facts[1].participant_key='B';", "delete payload.worker_id;",
    "payload.facts=Array.from({length:65},(_,index)=>auditFact(index+1));",
])
def test_invalid_report_identity_revision_or_rowset_is_unverified(change):
    check("const payload=auditPayload('worker_report');" + change + r'''
prepareAudit(auditEvent(payload));assert.equal(auditClass('reference-audit').length,0);
assert.match(auditText($('activityFeed')),/未検証/);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('change', [
    "event.agent_id='agent-b';", "event.id='31';", "event.id=0;",
    "event.text='{broken JSON';", "event.text=event.text.slice(0,-10);",
])
def test_untrusted_outer_event_or_truncated_payload_is_unverified(change):
    check("const event=auditEvent();" + change + r'''
prepareAudit(event);assert.equal(auditClass('reference-audit').length,0);
assert.match(auditText($('activityFeed')),/構造化照合を確認できない記録（未検証）/);assert.equal(requests.length,0);
''')


def test_cross_run_or_missing_pm_identity_never_acquires_audit_display():
    check(r'''
prepareAudit();assert.equal(referenceAuditPayload(auditEvent(),{...getRun(),id:'run-b'}),null);
assert.equal(referenceAuditPayload(auditEvent(),{...getRun(),pm_agent_ids:[]}),null);
getRun().pm_agent_ids=['agent-b'];renderRun();assert.equal(auditClass('reference-audit').length,0);
getRun().pm_agent_ids=['agent-a','agent-b'];renderRun();assert.equal(auditClass('reference-audit').length,0);
assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('field', ['run', 'actor'])
@pytest.mark.parametrize('value', ['', ' ', '[redacted]', 'id-[redacted]'])
def test_equal_empty_or_masked_outer_identities_cannot_verify_the_envelope(field, value):
    check("const field=" + repr(field) + ";const value=" + repr(value) + r''';
prepareAudit();const event=auditEvent(),run=structuredClone(getRun());
if(field==='run'){event.run_id=value;run.id=value;}else{event.agent_id=value;run.pm_agent_ids=[value];}
assert.equal(referenceAuditPayload(event,run),null);const content=element('div');assert(appendReferenceAudit(content,event,run));
assert.equal(auditNodes(content).filter(node=>node.className==='reference-audit').length,0);
assert.match(auditText(content),/構造化照合を確認できない記録（未検証）/);assert.equal(requests.length,0);
''')


def test_html_like_values_and_masked_comment_are_literal_and_do_not_restore_secrets():
    check(r'''
const payload=auditPayload();payload.facts[0].meaning='<script>literal only</script>';
payload.comment.text='<img src=x onerror=alert(1)> [redacted]';prepareAudit(auditEvent(payload));
assert.equal(auditClass('reference-audit').length,1);assert(auditText($('activityFeed')).includes(payload.facts[0].meaning));
assert(auditText(auditClass('reference-audit-comment')[0]).includes(payload.comment.text));
assert.equal(auditNodes($('activityFeed')).filter(node=>['SCRIPT','IMG'].includes(node.tagName)).length,0);
const event=auditEvent({...payload,facts:[{...payload.facts[0],meaning:'[redacted]'}]});ui.state.events=[event];renderRun();
assert.equal(auditClass('reference-audit').length,0);assert(!auditText($('activityFeed')).includes('literal only'));assert.equal(requests.length,0);
''')


def test_changed_snapshot_preserves_fact_scroll_keyboard_focus_draft_and_network_pin():
    check(r'''
prepareAudit();$('messageInput').value='Keep human draft';saveAgentDraft({type:'input'});toggleNetworkPin('agent-b');
const list=auditClass('reference-audit-facts')[0];list.scrollTop=71;list.focus();const key=list.dataset.focusKey;
$('activityFeed').scrollTop=41;ui.state.events.push({id:32,run_id:'run-a',kind:'tool',text:'new observation',at:101});renderRun();
const replacement=auditClass('reference-audit-facts')[0];assert.notEqual(replacement,list);assert.equal(replacement.scrollTop,71);
assert.equal(document.activeElement,replacement);assert.equal(document.activeElement.dataset.focusKey,key);assert.equal($('activityFeed').scrollTop,41);
assert.equal($('messageInput').value,'Keep human draft');assert.equal(ui.drafts.get('agent-a'),'Keep human draft');
assert.equal(networkViewState().pinnedAgent,'agent-b');assert.equal(ui.selectedAgent,'agent-a');assert.equal(requests.length,0);
''')


def test_archive_is_saved_evidence_only():
    check(r'''
prepareAudit(auditEvent(auditPayload('worker_report')));getRun().archived=true;getRun().read_only=true;renderRun();
assert.equal(auditClass('reference-audit-fact').length,2);assert.match(auditText(auditClass('reference-audit')[0]),/保存時点/);
assert.equal(auditNodes(auditClass('reference-audit')[0]).filter(node=>node.tagName==='BUTTON').length,0);
assert.equal($('sendMessage').disabled,true);assert.equal(requests.length,0);
''')


def test_row_limit_preserves_64_rows_but_cut_or_oversized_text_is_unavailable():
    check(r'''
const payload=auditPayload('worker_report');payload.comment.text='';
payload.facts=Array.from({length:64},(_,index)=>{const fact=auditFact(index+1);fact.value='a';fact.meaning='b';fact.expected_head='a';fact.predecessor.value='a';fact.reference.entry_id='e';return fact;});
const event=auditEvent(payload);assert(event.text.length<=32000);prepareAudit(event);assert.equal(auditClass('reference-audit-fact').length,64);
ui.state.events=[{...event,text:event.text.slice(0,16000)}];renderRun();assert.equal(auditClass('reference-audit').length,0);
ui.state.events=[{...event,text:event.text+' '.repeat(32001)}];renderRun();assert.equal(auditClass('reference-audit').length,0);assert.equal(requests.length,0);
''')
