"""Hierarchy presentation and depth drafts using synthetic DOM/transport only."""
import json

import pytest

from test_frontend import HTML
from test_observability_frontend import check as monitor_check
from test_orchestration_frontend import check as orchestration_check
from test_task_guidance import Elements


TREE = r'''
function prepareHierarchy(){
  prepareNetwork();const root=namedAgent('agent-a'),child=namedAgent('agent-b');
  const grand={...structuredClone(child),id:'grand',parent_id:child.id,name:'孫のまとめ役',question:'',status:'working',status_reason:''};
  const great={...structuredClone(child),id:'great',parent_id:grand.id,name:'ひ孫の担当',question:'',status:'working',status_reason:''};
  ui.state.agents.push(grand,great);getRun().agent_ids.push(grand.id,great.id);getRun().max_delegation_depth=3;
  const members=[root,child,grand,great];
  for(let depth=0;depth<members.length;depth++){
    const agent=members[depth];agent.hierarchy={depth,root_pm_id:root.id,unit_id:agent.parent_id||agent.id,
      direct_children:members.filter(item=>item.parent_id===agent.id).map(item=>item.id),can_delegate:depth<3};
  }
  renderRun();return {root,child,grand,great};
}
function hierarchyCard(id){return $('agentCards').children.find(node=>node.dataset.agentId===id);}
'''


def check(source):
    monitor_check(TREE + source)


def test_roles_units_and_direct_reporting_are_visible_without_promoting_workers_to_pm():
    check(r'''
const {root,child,grand,great}=prepareHierarchy(),before=JSON.stringify(ui.state);
assert.equal(agentRoleLabel(root),'PM');assert.equal(agentRoleLabel(child),'作業者・単位まとめ役');
assert.equal(agentRoleLabel(grand),'作業者・単位まとめ役');assert.equal(agentRoleLabel(great),'作業者');
assert.match(monitorText(hierarchyCard('grand')),/深さ 2（孫）/);
assert.match(agentHierarchyLabel(grand),/所属単位: Worker B \[agent-b\]/);
assert.match(agentHierarchyLabel(grand),/管理する子単位: 孫のまとめ役 \[grand\]/);
assert.match(agentHierarchyLabel(great),/報告先: 孫のまとめ役 \[grand\]/);
assert.equal(ui.networkNodes.get('grand').button.dataset.networkRole,'worker');
assert.equal(ui.networkNodes.get('grand').role.textContent,'LEAD · D2');
assert.equal(ui.networkNodes.get('great').role.textContent,'WORKER · D3');
assert.equal(JSON.stringify(ui.state),before);assert.equal(requests.length,0);
''')


def test_preview_inspector_roster_and_advisory_updates_share_one_current_hierarchy():
    check(r'''
const {grand}=prepareHierarchy();ui.networkNodes.get('grand').button.listeners.pointerenter();renderInspector(grand);
const label=agentHierarchyLabel(grand);
assert($('networkPreviewMonitor').textContent.includes(label));assert($('inspectorMonitor').textContent.includes(label));
assert(monitorText(hierarchyCard('grand')).includes(label));
grand.hierarchy.can_delegate=false;renderRun();renderInspector(grand);
assert.match($('networkPreviewMonitor').textContent,/不可との表示/);
assert.match($('inspectorMonitor').textContent,/実行時にサーバーが再確認/);
assert.equal(requests.length,0);assert.equal(grand.parent_id,'agent-b');
''')


def test_deeper_nodes_have_later_rows_and_exact_direct_parent_edges():
    check(r'''
prepareHierarchy();const p=ui.networkLayout.positions;
assert(p.get('agent-a').y<p.get('agent-b').y);assert(p.get('agent-b').y<p.get('grand').y);assert(p.get('grand').y<p.get('great').y);
assert.deepEqual(ui.networkParentLines.map(edge=>[edge.id,edge.parentId]),[['agent-b','agent-a'],['grand','agent-b'],['great','grand']]);
const layout=networkLayout(ui.state.agents.filter(agent=>agent.run_id==='run-a'));
assert.equal(new Set([...layout.positions.values()].map(point=>JSON.stringify(point))).size,4);
assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('children', [0, 1, 2, 3, 4, 8, 16])
def test_one_level_geometry_keeps_original_balanced_coordinates(children):
    check(r'''
const n=CHILDREN,agents=[{id:'p',parent_id:null},...Array.from({length:n},(_,i)=>({id:'w'+i,parent_id:'p'}))];
const layout=networkLayout(agents);assert.deepEqual(layout.positions.get('p'),{x:304,y:32});
for(let i=0;i<n;i++){
 const last=n%3,offset=last&&i>=n-last?(3-last)*212/2:0;
 assert.deepEqual(layout.positions.get('w'+i),{x:92+(i%3)*212+offset,y:208+Math.floor(i/3)*164});
}
assert.equal(layout.height,Math.max(360,32+176+Math.ceil(n/3)*164+40));
'''.replace('CHILDREN', str(children)))


def test_dragged_geometry_camera_draft_and_focus_survive_hierarchy_poll_updates():
    check(r'''
const {grand}=prepareHierarchy();moveNetworkNode('grand',620,510);panNetwork(20,10);
const camera={...networkViewState().camera},node=ui.networkNodes.get('grand').button;
$('messageInput').value='Keep exact PM draft';saveAgentDraft({type:'input'});$('messageInput').focus();
grand.hierarchy.can_delegate=false;renderRun();
assert.deepEqual(ui.networkLayout.positions.get('grand'),{x:620,y:510});assert.deepEqual(networkViewState().camera,camera);
assert.equal(ui.networkNodes.get('grand').button,node);assert.equal(document.activeElement,$('messageInput'));
assert.equal($('messageInput').value,'Keep exact PM draft');assert.equal(requests.length,0);
''')


def test_relation_actions_use_existing_pair_history_and_selected_agent_routes():
    check(r'''
prepareHierarchy();changeSelection('run-a','grand');renderRun();const before=JSON.stringify(ui.state);
const rows=$('hierarchyRelations').children;
assert.equal(rows.length,2);assert.match(monitorText(rows[0]),/報告先: Worker B \[agent-b\]/);
rows[0].children[1].listeners.click();assert.equal(ui.activityFilter,'pair');
assert.deepEqual(ui.activityPair,{from:'grand',to:'agent-b'});assert.equal(ui.selectedAgent,'grand');
assert.equal(JSON.stringify(ui.state),before);assert.equal(requests.length,0);
rows[1].children[0].listeners.click();assert.equal(ui.selectedAgent,'great');
assert(requests.every(request=>request.path.startsWith('/api/state')));
''')


def test_stale_relationship_buttons_cannot_act_after_selection_or_instance_changes():
    check(r'''
prepareHierarchy();changeSelection('run-a','grand');renderRun();const click=$('hierarchyRelations').children[0].children[1].listeners.click;
changeSelection('run-a','agent-a');click();assert.notEqual(ui.activityFilter,'pair');
changeSelection('run-a','grand');ui.instanceId='different-instance';click();assert.notEqual(ui.activityFilter,'pair');
assert.equal(requests.length,0);
''')


def test_same_relation_poll_retains_actual_buttons_scroll_and_focus():
    check(r'''
const {grand}=prepareHierarchy();changeSelection('run-a','grand');renderRun();
const panel=$('hierarchyRelations'),button=panel.children[0].children[0];panel.scrollTop=38;button.focus();
renderRun();assert.equal(panel.children[0].children[0],button);assert.equal(panel.scrollTop,38);assert.equal(document.activeElement,button);
namedAgent('agent-b').name='Updated parent';renderRun();
assert.equal(document.activeElement.dataset.focusKey,button.dataset.focusKey);assert.equal(panel.scrollTop,38);
assert.match(monitorText(panel),/Updated parent/);assert.equal(requests.length,0);
''')


def test_dependency_retry_names_the_actual_parent_without_changing_legacy_pm_wording():
    check(r'''
const {child,grand}=prepareHierarchy();
for(const agent of [child,grand]){agent.status_reason='dependency_stale';agent.worker_dependencies={depends_on:['great'],blocked_by:['great'],stale:true,accepted_revisions:{}};}
renderRun();assert.match(stateLabel(child),/PM再依頼/);assert.match(stateLabel(grand),/直属親の再依頼/);
assert.match(workerDependencyLabel(child),/PMの明示的/);assert.match(workerDependencyLabel(grand),/直属親の明示的/);
grand.status_reason='unit_stale';renderRun();assert.match(monitorText(hierarchyCard('grand')),/親の再依頼待ち/);
assert.equal(needsHuman(grand),false);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('change', [
    'grand.hierarchy=null;', 'grand.hierarchy.depth=1;', "grand.hierarchy.unit_id='agent-a';",
    "grand.hierarchy.root_pm_id='agent-c';", "grand.hierarchy.direct_children=['agent-c'];",
    "grand.hierarchy.direct_children.push('great');", "grand.hierarchy.can_delegate='true';",
    "grand.parent_id='great';", "grand.parent_id='agent-c';",
])
def test_malformed_or_cross_run_hierarchy_is_unconfirmed_and_has_no_unit_controls(change):
    check('const {grand}=prepareHierarchy();' + change + r'''
changeSelection('run-a','grand');renderRun();
assert.equal(agentHierarchy(grand),null);assert.match(agentHierarchyLabel(grand),/詳細を確認できません/);
assert.equal($('hierarchyRelations').hidden,true);assert.doesNotMatch(agentHierarchyLabel(grand),/可能との表示/);
assert.equal(requests.length,0);
''')


def test_untrusted_names_stay_text_and_identity_is_scoped_to_the_same_run():
    check(r'''
const {grand}=prepareHierarchy();namedAgent('agent-b').name='<img src=x onerror=alert(1)>';
changeSelection('run-a','grand');renderRun();
assert.match($('inspectorMonitor').textContent,/<img/);assert.match(monitorText($('hierarchyRelations')),/\[agent-b\]/);
assert.equal(monitorNodes($('hierarchyRelations')).filter(node=>node.tagName==='IMG').length,0);
assert.equal(requests.length,0);
''')


def test_archive_disconnection_and_legacy_absence_never_claim_current_permission():
    check(r'''
const {grand}=prepareHierarchy();setConnection(false,'offline');assert.match(agentHierarchyLabel(grand),/最後に取得/);
getRun().archived=true;assert.match(agentHierarchyLabel(grand),/保存時点/);
delete grand.hierarchy;assert.equal(agentHierarchyLabel(grand),'');assert.equal(agentRoleLabel(grand),'作業者');
renderInspector(grand);assert.equal($('hierarchyRelations').hidden,true);assert.equal(requests.length,0);
''')


def test_depth_control_is_explicit_bounded_and_explains_shared_descendant_budget():
    tree = Elements()
    attrs = tree.ids['maxDelegationDepth']['attrs']
    assert (attrs['type'], attrs['min'], attrs['max'], attrs['step'], attrs['value']) == ('number', '1', '3', '1', '3')
    assert attrs['aria-describedby'] == 'delegationDepthHelp'
    assert '子・孫・ひ孫の合計人数' in HTML
    assert '委任人数はroot PMごとの直属の子だけに適用' in HTML


@pytest.mark.parametrize('value', ['', '0', '4', '1.5', 'NaN'])
def test_invalid_depth_blocks_start_without_touching_other_draft_fields(value):
    orchestration_check(r'''
CONFIG.orchestration={delegation_level:1,workers_per_pm:2,max_delegation_depth:3};await setupOrchestration();
const task=$('taskInput').value,workers=$('maxWorkers').value;taskControl('maxDelegationDepth',VALUE);
assert.match(taskOrchestrationIssue(),/委任深さ/);assert.equal($('startRun').disabled,true);
await start();assert.equal(requests.length,0);assert.equal($('taskInput').value,task);assert.equal($('maxWorkers').value,workers);
'''.replace('VALUE', json.dumps(value)))


@pytest.mark.parametrize('cap', [None, 0, 4, '3'])
def test_present_invalid_saved_cap_is_not_replaced_with_default_authority(cap):
    orchestration_check(r'''
CONFIG.orchestration={delegation_level:1,workers_per_pm:2,max_delegation_depth:3};await setupOrchestration();
ui.config.orchestration.max_delegation_depth=CAP;syncStartControl();
assert.equal(savedDelegationDepth(),null);assert.equal($('startRun').disabled,true);
assert.equal($('maxDelegationDepth').value,'3');await start();assert.equal(requests.length,0);
'''.replace('CAP', json.dumps(cap)))


def test_saved_depth_cap_is_default_and_explicit_run_override_cannot_exceed_it():
    orchestration_check(r'''
CONFIG.orchestration={delegation_level:1,workers_per_pm:2,max_delegation_depth:2};await setupOrchestration();
assert.equal(runPayload().max_delegation_depth,2);assert.equal($('maxDelegationDepth').max,'2');
taskControl('maxDelegationDepth',1);assert.equal(runPayload().max_delegation_depth,1);assert.equal(taskOrchestrationIssue(),'');
taskControl('maxDelegationDepth',3);assert.equal($('maxDelegationDepth').value,'3');assert.match(taskOrchestrationIssue(),/保存済み上限/);
assert.equal(requests.length,0);
''')


def test_lower_saved_cap_retains_live_draft_until_explicit_defaults_action():
    orchestration_check(r'''
CONFIG.orchestration={delegation_level:1,workers_per_pm:2,max_delegation_depth:3};await setupOrchestration();
taskControl('maxDelegationDepth',3);const draft=runPayload();
ui.config.orchestration.max_delegation_depth=1;renderProfileChoices(true);syncStartControl();
assert.equal($('maxDelegationDepth').value,'3');assert.equal($('maxDelegationDepth').max,'1');assert.deepEqual(runPayload(),draft);
assert.equal($('startRun').disabled,true);$('useOrchestrationDefaults').listeners.click();clearTimeout(ui.preflightTimer);
assert.equal(runPayload().max_delegation_depth,1);assert.equal(runPayload().task,draft.task);assert.equal(runPayload().max_workers,draft.max_workers);
assert.equal(requests.length,0);
''')


def test_legacy_reload_accepts_absent_depth_without_mutating_raw_settings_or_task_draft():
    orchestration_check(r'''
CONFIG.orchestration={delegation_level:1,workers_per_pm:2,max_delegation_depth:3};await setupOrchestration();
taskControl('maxDelegationDepth',1);taskControl('workersPerPM',7);const draft=runPayload();
const pending=discardSettings(),config=structuredClone(CONFIG);config.orchestration={delegation_level:2,workers_per_pm:3};
requests[0].resolve({config,config_revision:5,secret_status:{local:false,search:false}});await pending;
assert.deepEqual(ui.config.orchestration,{delegation_level:2,workers_per_pm:3});
assert.equal(Object.hasOwn(ui.config.orchestration,'max_delegation_depth'),false);assert.equal(savedDelegationDepth(),3);
assert.deepEqual(runPayload(),draft);assert.equal(ui.configRevision,5);assert.equal(requests.length,1);
''')


@pytest.mark.parametrize('bad', ['null', 'undefined', '0', '4', '1.5', "'3'", 'true'])
def test_reload_rejects_present_invalid_depth_and_retains_settings_and_task_draft(bad):
    orchestration_check(r'''
CONFIG.orchestration={delegation_level:1,workers_per_pm:2,max_delegation_depth:3};await setupOrchestration();
taskControl('maxDelegationDepth',2);const before=structuredClone(ui.config),draft=runPayload(),revision=ui.configRevision;
const pending=discardSettings(),config=structuredClone(CONFIG);
config.orchestration={delegation_level:2,workers_per_pm:3,max_delegation_depth:BAD};
requests[0].resolve({config,config_revision:5,secret_status:{local:false,search:false}});await pending;
assert.deepEqual(ui.config,before);assert.equal(ui.configRevision,revision);assert.deepEqual(runPayload(),draft);
assert.match($('settingsStatus').textContent,/保存済み設定を確認できません/);assert.equal(requests.length,1);
'''.replace('BAD', bad))


def test_settings_depth_save_is_explicit_and_does_not_overwrite_task_depth():
    orchestration_check(r'''
CONFIG.orchestration={delegation_level:1,workers_per_pm:2,max_delegation_depth:3};await setupOrchestration();
taskControl('maxDelegationDepth',2);const draft=runPayload();
const input=settingControl('orchestrationFields','max_delegation_depth',1);assert.equal(input.min,'1');assert.equal(input.max,'3');
const pending=submit();assert.equal(requests[0].options.body.config.orchestration.max_delegation_depth,1);accept();await pending;
assert.deepEqual(runPayload(),draft);assert.equal($('maxDelegationDepth').value,'2');assert.equal($('startRun').disabled,true);
assert.equal(requests.length,1);
''')


def test_run_metrics_use_the_saved_run_depth_and_old_history_stays_unrecorded():
    check(r'''
prepareHierarchy();const text=()=>monitorText($('runMetrics'));assert.match(text(),/委任深さ上限.*3（ひ孫まで）/);
$('maxDelegationDepth').value='1';renderRun();assert.match(text(),/3（ひ孫まで）/);
delete getRun().max_delegation_depth;renderRun();assert.match(text(),/委任深さ上限.*未記録/);
assert.equal(requests.length,0);
''')
