"""Public monitoring behavior; no authority, polling requests or model calls."""
from test_dynamic_network_frontend import check as network_check


def check(source):
    # The shared fake DOM stores own text only and supports a small selector
    # subset. Walk its child nodes to assert the browser's aggregate text/tree.
    network_check(r'''
function monitorNodes(node){return [node,...node.children.flatMap(monitorNodes)];}
function monitorText(node){return monitorNodes(node).map(n=>n.textContent).join(' ');}
''' + source)


def test_provider_phase_is_observed_not_inferred_from_working():
    check(r'''
prepareNetwork();const a=namedAgent('agent-a');a.status='working';
assert.equal(providerObservationLabel(a),'');
a.provider_observation={schema_version:1,phase:'queue_wait',purpose:'work',admission_kind:'local',phase_elapsed_seconds:13.8,queue_timeout_seconds:120,observed_at:100};
assert.match(providerObservationLabel(a),/受付待ち/);assert.match(providerObservationLabel(a),/13秒/);assert.doesNotMatch(providerObservationLabel(a),/API応答待ち/);
a.provider_observation={...a.provider_observation,phase:'response_wait',phase_elapsed_seconds:31,request_timeout_seconds:600};
assert.match(providerObservationLabel(a),/API応答待ち/);assert.match(providerObservationLabel(a),/上限 600秒/);
a.provider_observation.purpose='compaction';assert.match(providerObservationLabel(a),/文脈要約/);
a.provider_observation.phase='guess';assert.equal(providerObservationLabel(a),'');
''')


def test_disconnection_and_archive_do_not_advance_or_claim_live_observation():
    check(r'''
prepareNetwork();const a=namedAgent('agent-a');a.provider_observation={schema_version:1,phase:'response_wait',purpose:'work',phase_elapsed_seconds:9.2,observed_at:100};
renderRun();assert.match(monitorText($('coordinationContent')),/9秒/);
setConnection(false,'offline');assert.match($('coordinationFreshness').textContent,/最後/);assert.match(providerObservationLabel(a),/最後の観測/);
advanceTimers(10000);assert.equal(a.provider_observation.phase_elapsed_seconds,9.2);
a.archived=true;assert.match(providerObservationLabel(a),/保存時点/);
''')


def test_mail_identity_includes_run_and_endpoints_and_missing_half_is_unknown():
    check(r'''
const events=[
{id:1,run_id:'r1',kind:'mail',mail_id:'m',from_agent_id:'a',to_agent_id:'b',delivery_state:'queued',at:10},
{id:2,run_id:'r2',kind:'mail_consumed',mail_id:'m',from_agent_id:'a',to_agent_id:'b',delivery_state:'context_consumed',at:12},
{id:3,run_id:'r1',kind:'mail_consumed',mail_id:'m',from_agent_id:'a',to_agent_id:'c',delivery_state:'context_consumed',at:13}];
let rows=mailLifecycles(events,'r1');assert.equal(rows.length,2);assert.match(mailLifecycleLabel(rows.find(x=>x.to==='b')),/未確認/);assert.match(mailLifecycleLabel(rows.find(x=>x.to==='c')),/保持範囲外/);
events.push({...events[1],run_id:'r1',at:15});rows=mailLifecycles(events,'r1');assert.match(mailLifecycleLabel(rows.find(x=>x.to==='b')),/間隔 5秒/);
assert.equal(mailLifecycles(events.map(x=>({...x,mail_id:null})),'r1').length,0);
''')


def test_canonical_pending_review_and_current_report_are_distinct():
    check(r'''
prepareNetwork();const r=getRun();r.coordination={schema_version:1,kind:'ordered_work',phase:'pending_review',accepted_steps:2,total_steps:6,step:3,current_actor_id:'agent-b',pending:{value:'<script>literal</script>',summary:'meaning',semantic_status:'reference_matched'},corrections:{revisions:1,rollbacks:0},reports:[{agent_id:'agent-b',current_revision:2,formal_revision:1,delivered_revision:1,consumed_revision:1,accepted_current:false}],pm_completion:{completed:false}};
renderRun();assert.match(monitorText($('coordinationContent')),/PM監査待ち/);assert.match(monitorText($('coordinationContent')),/採用 2 \/ 6/);assert.match(monitorText($('coordinationContent')),/PM承認 未完了/);assert.match(monitorText($('coordinationContent')),/一般的な意味の正しさを保証しません/);
assert.match(monitorText($('coordinationContent')),/<script>literal<\/script>/);assert.equal(monitorNodes($('coordinationContent')).filter(n=>n.tagName==='SCRIPT').length,0);
assert.equal(requests.length,0);
''')


def test_monitor_selection_preserves_draft_and_preview_shows_same_dependency():
    check(r'''
prepareNetwork();$('messageInput').value='Keep PM draft';saveAgentDraft({type:'input'});
const a=namedAgent('agent-b');a.coordination={schema_version:1,participant_key:'B',step:2,dependency:{reason:'pm_review',actor_id:'agent-a'}};renderRun();
ui.networkNodes.get(a.id).button.listeners.pointerenter();assert.match($('networkPreviewMonitor').textContent,/PMの候補監査待ち/);assert.equal(ui.selectedAgent,'agent-a');assert.equal($('messageInput').value,'Keep PM draft');
const button=monitorNodes($('coordinationContent')).find(n=>n.tagName==='BUTTON');button.listeners.click();assert.equal(ui.selectedAgent,'agent-b');assert.equal(ui.drafts.get('agent-a'),'Keep PM draft');
''')


def test_projection_is_not_called_semantic_summary():
    check(r'''
prepareNetwork();const a=namedAgent('agent-a');a.context_memory={compactions:0,history_records:33,history_omitted:0,ordered_projection:{mode:'ordered_bounded_projection',raw_message_count:33,projected_message_count:8,omitted_message_count:25,trimmed_message_count:2}};
renderConversation(a);assert.match($('contextMemoryStatus').textContent,/33 → 8/);assert.match($('contextMemoryStatus').textContent,/AI要約ではなく/);assert.match($('contextMemoryStatus').textContent,/保持上限/);
''')


def test_connection_rebuild_restores_focused_monitor_without_sending():
    check(r'''
prepareNetwork();const a=namedAgent('agent-b');a.coordination={schema_version:1,participant_key:'B',step:2,dependency:{reason:'turn',actor_id:'agent-a'}};renderRun();
const button=monitorNodes($('coordinationContent')).find(n=>n.tagName==='BUTTON');button.focus();const key=button.dataset.focusKey;
setConnection(false,'offline');assert.equal(document.activeElement.dataset.focusKey,key);assert.notEqual(document.activeElement,button);
setConnection(true,'online');assert.equal(document.activeElement.dataset.focusKey,key);assert.equal(requests.length,0);
''')


def test_lifecycle_from_board_switches_to_visible_network_without_sending():
    check(r'''
prepareNetwork([mail(1)]);setCockpitView('board');renderRun();
const row=monitorNodes($('mailLifecycleList')).find(n=>n.tagName==='BUTTON');row.listeners.click();
assert.equal(ui.cockpitView,'network');assert.deepEqual(ui.activityPair,{from:'agent-a',to:'agent-b'});assert.equal(document.activeElement,$('activityTitle'));assert.equal(requests.length,0);
''')
