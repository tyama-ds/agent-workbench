"""Read-only dependency presentation through the real rendering callbacks."""
import pytest

from test_observability_frontend import check as monitor_check


SETUP = r'''
function prepareDependencies(){
 prepareNetwork();const prior={...namedAgent('agent-b'),id:'prior-worker',name:'調査担当',status:'done',status_reason:'done',question:''};
 ui.state.agents.push(prior);getRun().agent_ids.push(prior.id);
 const child=namedAgent('agent-b');child.status='idle';child.status_reason='dependency_wait';child.question='';
 child.worker_dependencies={depends_on:[prior.id],blocked_by:[prior.id],stale:false,accepted_revisions:{}};
 renderRun();return child;
}
function dependencyCard(){return $('agentCards').children.find(node=>node.dataset.agentId==='agent-b');}
'''


def check(source):
    monitor_check(SETUP + source)


def test_waiting_card_inspector_and_hover_show_the_same_blocked_identity():
    check(r'''
const child=prepareDependencies(),before=JSON.stringify(ui.state);
assert.match(stateLabel(child),/前工程の承認待ち/);assert.equal(needsHuman(child),false);
assert.match(monitorText(dependencyCard()),/調査担当 \[prior-worker\]/);
assert.match(monitorText(dependencyCard()),/前工程の承認待ち/);
renderInspector(child);assert.match($('inspectorMonitor').textContent,/調査担当 \[prior-worker\]/);
ui.networkNodes.get(child.id).button.listeners.pointerenter();assert.match($('networkPreviewMonitor').textContent,/調査担当 \[prior-worker\]/);
assert.match(monitorText($('coordinationContent')),/調査担当 \[prior-worker\]/);
assert.equal(JSON.stringify(ui.state),before);assert.equal(requests.length,0);
''')


def test_dependency_only_updates_refresh_cached_roster_and_monitor():
    check(r'''
const child=prepareDependencies(),old=dependencyCard();
child.worker_dependencies.blocked_by=[];child.worker_dependencies.accepted_revisions={'prior-worker':2};renderRun();
assert.notEqual(dependencyCard(),old);assert.match(monitorText(dependencyCard()),/使用した承認版: 調査担当 \[prior-worker\] \/ 2/);
assert.match(monitorText($('coordinationContent')),/使用した承認版/);
assert.doesNotMatch(workerDependencyLabel(child),/前工程の承認待ち/);
assert.equal(child.status_reason,'dependency_wait');assert.match(stateLabel(child),/前工程の承認待ち/);
assert.equal(requests.length,0);
''')


def test_stale_result_explains_pm_reassignment_without_creating_a_human_question():
    check(r'''
const child=prepareDependencies();child.worker_dependencies.stale=true;
child.worker_dependencies.accepted_revisions={'prior-worker':1};child.status_reason='dependency_stale';renderRun();
assert.match(stateLabel(child),/前工程変更・PM再依頼待ち/);
assert.match(monitorText(dependencyCard()),/以前の成果は失効/);
assert.match(monitorText(dependencyCard()),/PMの明示的な再依頼/);
assert.equal(needsHuman(child),false);assert.equal(questionEntries().length,0);assert.equal(requests.length,0);
''')


def test_peer_names_are_scoped_to_the_run_and_ids_remain_visible():
    check(r'''
const child=prepareDependencies();child.worker_dependencies.depends_on=['prior-worker','agent-c'];
child.worker_dependencies.blocked_by=['agent-c'];namedAgent('prior-worker').name='同じ名前';child.name='同じ名前';renderRun();
const text=workerDependencyLabel(child);assert.match(text,/同じ名前 \[prior-worker\]/);
assert.match(text,/担当未取得 \[agent-c\]/);assert.doesNotMatch(text,/PM C/);
namedAgent('prior-worker').name='変更後の担当';renderRun();assert.match(monitorText(dependencyCard()),/変更後の担当/);
assert.equal(requests.length,0);
''')


def test_untrusted_names_and_ids_are_only_text():
    check(r'''
const child=prepareDependencies(),malicious='<img src=x onerror=alert(1)>';
namedAgent('prior-worker').name=malicious;child.worker_dependencies.depends_on.push(malicious);
child.worker_dependencies.blocked_by.push(malicious);renderRun();renderInspector(child);
assert(monitorText(dependencyCard()).includes(malicious));assert($('inspectorMonitor').textContent.includes(malicious));
assert.equal(monitorNodes(dependencyCard()).filter(node=>node.tagName==='IMG').length,0);
assert.equal(requests.length,0);
''')


def test_archived_or_disconnected_display_never_claims_a_current_approval():
    check(r'''
const child=prepareDependencies();child.worker_dependencies.blocked_by=[];child.worker_dependencies.accepted_revisions={'prior-worker':2};
setConnection(false,'offline');renderRun();assert.match(monitorText(dependencyCard()),/最後に取得した依存関係/);
getRun().archived=true;renderRun();renderInspector(child);
assert.match(monitorText(dependencyCard()),/保存時点の依存関係/);assert.match($('inspectorMonitor').textContent,/保存時点の依存関係/);
assert.doesNotMatch(workerDependencyLabel(child),/現在版を承認|実行可能|完了/);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('change', [
    "child.worker_dependencies=null;", "delete child.worker_dependencies.blocked_by;",
    "child.worker_dependencies.depends_on=[];", "child.worker_dependencies.blocked_by=['other'];",
    "child.worker_dependencies.stale='false';", "child.worker_dependencies.accepted_revisions={'prior-worker':true};",
    "child.worker_dependencies.accepted_revisions={'other':1};", "child.worker_dependencies.depends_on.push('prior-worker');",
])
def test_malformed_dependency_details_are_unconfirmed_without_inferred_approval(change):
    check('const child=prepareDependencies();' + change + r'''
renderRun();assert.match(workerDependencyLabel(child),/詳細を確認できません/);
assert.doesNotMatch(workerDependencyLabel(child),/使用した承認版|完了|実行可能/);assert.equal(requests.length,0);
''')


def test_legacy_agents_without_dependencies_keep_the_existing_display():
    check(r'''
prepareNetwork();const child=namedAgent('agent-b');assert.equal(workerDependencyLabel(child),'');
renderRun();assert.equal(monitorNodes(dependencyCard()).filter(node=>node.className==='agent-dependencies').length,0);
assert.equal(requests.length,0);
''')
