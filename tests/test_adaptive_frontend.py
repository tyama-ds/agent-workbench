"""Production formation UI callbacks with synthetic DOM and transport only."""
import json

import pytest

from test_frontend import HTML
from test_observability_frontend import check as monitor_check
from test_orchestration_frontend import check as orchestration_check
from test_task_guidance import Elements


FORM = r'''
function toggleAdaptive(value){
 $('adaptiveTeam').checked=value;
 $('runForm').listeners.change({type:'change',target:$('adaptiveTeam')});
 clearTimeout(ui.preflightTimer);
}
'''

DISPLAY = r'''
function adaptiveFixture(){
 prepareNetwork();const run=getRun(),pm=namedAgent('agent-a'),worker=namedAgent('agent-b');
 pm.kind='author';worker.kind='author';
 const reviewer={...structuredClone(pm),id:'agent-r',name:'Independent Reviewer',kind:'independent_reviewer',role:'review',parent_id:null,
   message_eligibility:{allowed:false,reason:'independent_reviewer',message:'独立レビュー専用です。'}};
 delete reviewer.hierarchy;ui.state.agents.push(reviewer);run.agent_ids.push(reviewer.id);run.pm_agent_ids=[pm.id];
 run.adaptive_team=true;run.formation={version:1,phase:'reviewing',difficulty:'low',reason:'One bounded artifact',worker_ids:[worker.id],reviewer_id:reviewer.id,
   reviewer_slots:1,candidate_count:1,stale_reason:'',candidate:{id:'c-'+'a'.repeat(32),round:1,summary_sha256:'a'.repeat(64),manifest_sha256:'b'.repeat(64),
   artifact_count:1,summary_only:false,read_count:1,consumed_read_count:0,decision:null,feedback:''}};
 renderRun();return {run,pm,worker,reviewer};
}
'''


def form_check(source):
    orchestration_check(FORM + source)


def display_check(source):
    monitor_check(DISPLAY + source)


def test_adaptive_mode_is_accessible_unchecked_and_run_scoped():
    tree = Elements()
    attrs = tree.ids['adaptiveTeam']['attrs']
    assert attrs['type'] == 'checkbox' and 'checked' not in attrs
    assert attrs['aria-describedby'] == 'adaptiveTeamHelp'
    assert tree.ids['formationPanel']['attrs']['aria-labelledby'] == 'formationTitle'
    assert '独立レビュワーも作業者上限に含め' in HTML
    assert '難易度の正確さを自動保証する設定ではありません' in HTML


def test_optin_changes_only_task_payload_and_toggle_restores_manual_values():
    form_check(r'''
await setupOrchestration();taskControl('delegationLevel',2);taskControl('workersPerPM',16);
const manual=runPayload(),saved=structuredClone(ui.config),generation=ui.taskDraftGeneration;
assert(!Object.hasOwn(manual,'adaptive_team'));toggleAdaptive(true);
assert.deepEqual(runPayload(),{...manual,adaptive_team:true});assert(ui.taskDraftGeneration>generation);
assert.equal(taskOrchestrationIssue(),'');assert($('delegationLevel').disabled&&$('workersPerPM').disabled);
assert.match($('workersPerPMValue').textContent,/未使用/);assert.match($('delegationStatus').textContent,/独立レビュワー1人/);
renderProfileChoices(true);assert($('adaptiveTeam').checked);assert.deepEqual(ui.config,saved);
toggleAdaptive(false);assert.deepEqual(runPayload(),manual);assert(!$('delegationLevel').disabled&&!$('workersPerPM').disabled);
assert.match(taskOrchestrationIssue(),/16 人/);assert.equal(requests.length,0);
''')


def test_explicit_saved_defaults_restore_manual_values_without_changing_mode():
    form_check(r'''
await setupOrchestration();const saved=structuredClone(ui.config);toggleAdaptive(true);
taskControl('delegationLevel',0);taskControl('workersPerPM',9);taskControl('maxDelegationDepth',1);
$('useOrchestrationDefaults').listeners.click();clearTimeout(ui.preflightTimer);
assert($('adaptiveTeam').checked);assert.equal(runPayload().adaptive_team,true);
assert.equal(runPayload().delegation_level,saved.orchestration.delegation_level);
assert.equal(runPayload().workers_per_pm,saved.orchestration.workers_per_pm);
assert.equal(runPayload().max_delegation_depth,saved.orchestration.max_delegation_depth);
assert($('delegationLevel').disabled&&$('workersPerPM').disabled);assert.deepEqual(ui.config,saved);assert.equal(requests.length,0);
toggleAdaptive(false);assert(!Object.hasOwn(runPayload(),'adaptive_team'));
assert.equal(runPayload().workers_per_pm,saved.orchestration.workers_per_pm);
''')


@pytest.mark.parametrize('cap', [0, 1])
def test_adaptive_minimum_reserves_reviewer_without_silent_budget_increase(cap):
    form_check(r'''
await setupOrchestration();toggleAdaptive(true);taskControl('maxWorkers',CAP);
const saved=structuredClone(ui.config);assert.match(taskOrchestrationIssue(),/計2人以上/);assert($('startRun').disabled);
await start();assert.equal(requests.length,0);assert.equal(runPayload().max_workers,CAP);assert.deepEqual(ui.config,saved);
'''.replace('CAP', str(cap)))


def test_multiple_pms_block_optin_without_deleting_existing_draft_rows():
    form_check(r'''
await setupOrchestration();addPM();clearTimeout(ui.preflightTimer);const before=runPayload();toggleAdaptive(true);
assert.match(taskOrchestrationIssue(),/PM 1人/);assert($('startRun').disabled);
assert.deepEqual(runPayload().pm_profiles,before.pm_profiles);await start();assert.equal(requests.length,0);
toggleAdaptive(false);assert.deepEqual(runPayload(),before);
''')


def test_adaptive_preflight_and_start_share_optin_and_display_unused_manual_counts():
    form_check(r'''
await setupOrchestration();showView('work');setBriefOpen(true,false);toggleAdaptive(true);
taskControl('delegationLevel',2);taskControl('workersPerPM',16);const expected=runPayload();
const pending=refreshPreflight(ui.preflightRequest);assert.deepEqual(requests[0].options.body,expected);
requests[0].resolve({can_start:true,blockers:[],warnings:[],adaptive_team:true,
 formation_rules:{workers:{low:1,medium:2,high:3},reviewer_slots:1,min_cap:2,manual_counts_used:false},
 orchestration:{delegation_level:2,workers_per_pm:16,max_delegation_depth:3}});await pending;
const text=$('preflightDetails').children.map(node=>node.textContent).join(' ');
assert.match(text,/独立レビュワー1人/);assert.match(text,/手動の分担方針・人数は使用しません/);assert.doesNotMatch(text,/PM1人あたり 16/);
const sending=start();assert.deepEqual(requests[1].options.body,expected);requests[1].reject(new Error('Synthetic rejection'));await sending;
assert.equal(requests.length,2);assert($('adaptiveTeam').checked);
''')


def test_reviewer_has_distinct_root_display_and_is_not_selected_as_pm():
    display_check(r'''
const {run,pm,reviewer}=adaptiveFixture();const node=ui.networkNodes.get(reviewer.id);
assert.equal(node.button.dataset.networkRole,'reviewer');assert.equal(node.monogram.textContent,'R');assert.equal(node.role.textContent,'REVIEWER');
assert.match(node.button.getAttribute('aria-label'),/独立レビュワー/);assert.equal(agentHierarchy(reviewer),null);
assert.match(agentHierarchyLabel(reviewer),/作成者とは別の系統/);assert.equal(agentRoleLabel(reviewer),'独立レビュワー');
node.button.listeners.pointerenter();assert.match($('networkPreviewRole').textContent,/独立レビュワー/);assert.doesNotMatch($('networkPreviewRole').textContent,/^PM/);
ui.state.agents=[reviewer,...ui.state.agents.filter(agent=>agent.id!==reviewer.id)];ui.selectedAgent=null;renderState();
assert.equal(ui.selectedAgent,pm.id);assert.equal(reviewer.parent_id,null);assert(!run.pm_agent_ids.includes(reviewer.id));assert.equal(requests.length,0);
''')


def test_role_string_alone_cannot_turn_author_into_independent_reviewer():
    display_check(r'''
const {worker}=adaptiveFixture();worker.role='independent_reviewer';renderRun();
assert.equal(independentReviewer(worker),false);assert.equal(agentRoleLabel(worker),'作業者');
assert.equal(ui.networkNodes.get(worker.id).button.dataset.networkRole,'worker');assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('phase,word', [('unplanned', '編成前'), ('working', '作成中'), ('reviewing', '独立レビュー中'),
    ('accepted', 'PM完了待ち'), ('revise', '修正依頼'), ('stale', '再提出待ち'), ('blocked', '未完了'), ('complete', 'PM完了を確認')])
def test_distinct_observed_phases_do_not_turn_acceptance_into_pm_completion(phase, word):
    display_check(r'''
const {run}=adaptiveFixture();run.formation.phase=PHASE;
run.formation.candidate.decision=['accepted','complete'].includes(PHASE)?'accept':PHASE==='revise'?'revise':null;
if(PHASE==='unplanned')Object.assign(run.formation,{difficulty:null,reason:'',worker_ids:[],reviewer_id:null,candidate_count:0,candidate:null});
renderRun();assert.match($('formationSummary').textContent,new RegExp(WORD));assert.equal(run.status,'running');assert.equal(requests.length,0);
'''.replace('PHASE', json.dumps(phase)).replace('WORD', json.dumps(word)))


def test_read_and_consumed_counts_and_summary_only_scope_are_explained_separately():
    display_check(r'''
const {run}=adaptiveFixture();assert.match(monitorText($('formationContent')),/本文読取 1 件 \/ 次のモデル要求へ取込 0 件/);
assert.match(monitorText($('formationContent')),/全セル・全ページ/);assert.match(monitorText($('formationContent')),/正しさの保証ではありません/);
Object.assign(run.formation.candidate,{artifact_count:0,summary_only:true,read_count:0,consumed_read_count:0});renderRun();
assert.match(monitorText($('formationContent')),/本文のみ（ファイル成果物なし）/);assert.equal(requests.length,0);
''')


def test_reason_feedback_and_staleness_are_literal_text_without_html_execution():
    display_check(r'''
const {run}=adaptiveFixture();run.formation.reason='<img src=x onerror=alert(1)>';
run.formation.candidate.feedback='<script>unsafe()</script>';run.formation.phase='stale';run.formation.stale_reason='Author input changed';renderRun();
const text=monitorText($('formationContent'));assert(text.includes(run.formation.reason));assert(text.includes(run.formation.candidate.feedback));assert(text.includes('Author input changed'));
assert.equal(monitorNodes($('formationContent')).filter(node=>['IMG','SCRIPT'].includes(node.tagName)).length,0);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('mutation', ["run.formation.candidate.id='forged';", "run.formation.candidate.read_count=true;",
    "run.formation.candidate.consumed_read_count=2;", "run.formation.phase='accepted';",
    "run.formation.worker_ids=['agent-b','agent-b'];", "run.formation.candidate.summary_only=true;"])
def test_invalid_public_formation_does_not_render_acceptance_or_authority(mutation):
    display_check(r'''
const {run}=adaptiveFixture();
''' + mutation + r'''
renderRun();assert.equal(formationView(run),null);assert.match($('formationSummary').textContent,/確認できません/);
assert.equal($('formationContent').children.length,0);assert.equal(requests.length,0);
''')


def test_unchanged_refresh_preserves_disclosure_focus_scroll_and_human_draft():
    display_check(r'''
const {run}=adaptiveFixture();const content=$('formationContent'),first=content.children[0],details=$('formationDetails');
details.open=true;content.scrollTop=17;$('messageInput').value='Keep human draft';saveAgentDraft({type:'input'});details.focus();
renderRun();assert.equal(content.children[0],first);assert(details.open);assert.equal(content.scrollTop,17);assert.equal(document.activeElement,details);
run.formation.phase='stale';run.formation.stale_reason='Current artifact changed';renderRun();
assert(details.open);assert.equal(content.scrollTop,17);assert.equal($('messageInput').value,'Keep human draft');assert.equal(ui.drafts.get('agent-a'),'Keep human draft');assert.equal(requests.length,0);
''')


def test_archive_and_disconnect_label_saved_evidence_without_restarting_review():
    display_check(r'''
const {run,reviewer}=adaptiveFixture();setConnection(false,'offline');assert.match($('formationSummary').textContent,/最後に取得した状態/);
run.archived=true;run.read_only=true;reviewer.archived=true;renderRun();assert.match($('formationSummary').textContent,/保存時点/);
assert.match(agentHierarchyLabel(reviewer),/保存時点/);assert.equal(run.formation.phase,'reviewing');assert.equal(requests.length,0);
''')


def test_switching_to_manual_run_hides_old_review_evidence():
    display_check(r'''
adaptiveFixture();assert(!$('formationPanel').hidden);renderFormation(ui.state.runs.find(run=>run.id==='run-b'));
assert($('formationPanel').hidden);assert.equal($('formationSummary').textContent,'');assert.equal($('formationContent').children.length,0);assert.equal(requests.length,0);
''')
