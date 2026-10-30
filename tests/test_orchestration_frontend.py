"""Real UI callbacks with synthetic DOM/transport; no models or browser processes."""
import pytest

from test_frontend import APP, HTML
from test_settings_save_frontend import check as settings_check
from test_run_action_frontend import check as action_check
from test_task_guidance import Elements


SETUP = r'''
async function setupOrchestration(){
 await setup();$('settingsForm').append($('orchestrationFields'),$('copilotAgentFields'));
 $('maxWorkers').value='3';syncStartControl();clearTimeout(ui.preflightTimer);
}
function taskControl(id,value,event='input'){
 const node=$(id);node.value=String(value);
 $('runForm').listeners[event]({type:event,target:node});clearTimeout(ui.preflightTimer);
}
function settingControl(group,key,value){
 const input=$(group).querySelector(`[data-key="${key}"]`);input.value=String(value);input.listeners.input();
 $('settingsForm').listeners.input({type:'input',target:input});return input;
}
function start(){return $('runForm').listeners.submit({preventDefault(){}});}
'''


def check(source):
    settings_check(SETUP + source + '\nclearTimeout(ui.preflightTimer);')


def test_explicit_sliders_have_accessible_bounds_and_worker_vs_request_guidance():
    tree = Elements()
    for ident, minimum, maximum, value in [('delegationLevel', '0', '2', '1'), ('workersPerPM', '1', '16', '2')]:
        attrs = tree.ids[ident]['attrs']
        assert attrs['type'] == 'range'
        assert (attrs['min'], attrs['max'], attrs['step'], attrs['value']) == (minimum, maximum, '1', value)
        assert attrs['aria-describedby'] == 'delegationHelp'
    assert tree.ids['useOrchestrationDefaults']['attrs']['type'] == 'button'
    assert tree.ids['delegationStatus']['attrs']['role'] == 'status'
    assert 'プロファイル1つにつき1人という指定ではありません' in HTML
    assert '会話とIDはそれぞれ別' in HTML
    assert 'Bridge 側の容量にも制限されます' in HTML
    assert '必要なキーを設定します' not in HTML


def test_defaults_are_explicit_in_task_payload_and_have_human_labels():
    check(r'''
await setupOrchestration();const payload=runPayload();
assert.equal(payload.delegation_level,1);assert.equal(payload.workers_per_pm,2);
assert.equal($('delegationLevelValue').textContent,'委任優先');assert.equal($('workersPerPMValue').textContent,'2 人');
assert.equal($('delegationLevel').getAttribute('aria-valuetext'),'委任優先');
assert.equal(requests.length,0);assert.equal(payload.worker_profiles.length,1);
''')


def test_initial_task_uses_saved_defaults_instead_of_overriding_them_with_html_values():
    check(r'''
CONFIG.orchestration={delegation_level:0,workers_per_pm:4};await setupOrchestration();
assert.equal(runPayload().delegation_level,0);assert.equal(runPayload().workers_per_pm,4);
assert.equal($('delegationLevelValue').textContent,'PM中心');assert($('workersPerPMValue').textContent.includes('未使用'));
assert.deepEqual(ui.config.orchestration,CONFIG.orchestration);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('level,label', [(0, 'PM中心'), (1, '委任優先'), (2, '委任必須')])
def test_slider_input_updates_payload_and_label_without_mutating_saved_settings(level, label):
    check(r'''
await setupOrchestration();const saved=structuredClone(ui.config),generation=ui.taskDraftGeneration;
taskControl('workersPerPM',3);taskControl('delegationLevel',LEVEL);
assert.equal(runPayload().delegation_level,LEVEL);assert.equal(runPayload().workers_per_pm,3);
assert.equal($('delegationLevelValue').textContent,LABEL);assert.equal($('delegationLevel').getAttribute('aria-valuetext'),LABEL);
assert(ui.taskDraftGeneration>generation);assert.deepEqual(ui.config,saved);assert.equal(requests.length,0);
'''.replace('LEVEL', str(level)).replace('LABEL', repr(label)))


def test_required_delegation_accounts_for_all_pms_and_never_increases_budget():
    check(r'''
await setupOrchestration();addPM();clearTimeout(ui.preflightTimer);taskControl('delegationLevel',2);
assert($('startRun').disabled);assert($('delegationStatus').textContent.includes('PM 2 人 × 2 人 = 4 人'));
assert.equal($('maxWorkers').value,'3');const count=ui.config.limits.max_workers;
await start();assert.equal(requests.length,0);assert($('runFormStatus').textContent.includes('4 人'));
ui.config.limits.max_workers=4;renderProfileChoices(true);taskControl('maxWorkers',4);
assert(!$('startRun').disabled);assert.equal(runPayload().max_workers,4);assert.equal(runPayload().workers_per_pm,2);
assert.equal(count,3);assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('level', [0, 1])
def test_centered_or_soft_delegation_does_not_enforce_target_slots(level):
    check(r'''
await setupOrchestration();taskControl('workersPerPM',16);taskControl('maxWorkers',0);taskControl('delegationLevel',LEVEL);
assert.equal(taskOrchestrationIssue(),'');assert(!$('startRun').disabled);
assert.equal(runPayload().max_workers,0);assert.equal(runPayload().workers_per_pm,16);
if(LEVEL===0)assert($('workersPerPMValue').textContent.includes('未使用'));
assert.equal(requests.length,0);
'''.replace('LEVEL', str(level)))


@pytest.mark.parametrize('ident,value', [('delegationLevel', ''), ('delegationLevel', '3'), ('delegationLevel', '1.5'), ('workersPerPM', '0'), ('workersPerPM', '17'), ('workersPerPM', 'NaN')])
def test_invalid_programmatic_task_values_cannot_bypass_submit_guard(ident, value):
    check(r'''
await setupOrchestration();taskControl(ID,VALUE);assert($('startRun').disabled);
await start();assert.equal(requests.length,0);assert($('runFormStatus').textContent.includes('確認してください'));
'''.replace('ID', repr(ident)).replace('VALUE', repr(value)))


def test_preflight_and_start_share_exact_policy_and_one_allowed_model_for_three_workers():
    check(r'''
await setupOrchestration();showView('work');setBriefOpen(true,false);
taskControl('workersPerPM',3);taskControl('delegationLevel',2);const expected=runPayload();
assert.deepEqual(expected.worker_profiles,['local']);assert.equal(expected.max_workers,3);
const preview=refreshPreflight(ui.preflightRequest);assert.equal(requests[0].path,'/api/run-preflight');
assert.deepEqual(requests[0].options.body,expected);requests[0].resolve({can_start:true,blockers:[],warnings:[],orchestration:{delegation_level:2,workers_per_pm:3}});await preview;
assert($('preflightDetails').children.some(node=>node.textContent.includes('委任必須')&&node.textContent.includes('3 人')));
const pending=start();assert.equal(requests[1].path,'/api/runs');assert.deepEqual(requests[1].options.body,expected);
taskControl('workersPerPM',2);assert.equal(requests[1].options.body.workers_per_pm,3);
requests[1].reject(new Error('Synthetic rejection'));await pending;
assert.equal(runPayload().workers_per_pm,2);assert($('runFormStatus').textContent.includes('現在の下書きは送信していません'));
''')


def test_saved_defaults_and_independent_request_caps_roundtrip_without_overwriting_task():
    check(r'''
await setupOrchestration();taskControl('delegationLevel',0);taskControl('workersPerPM',5);const draft=runPayload(),before=structuredClone(ui.config);
settingControl('orchestrationFields','delegation_level',2);settingControl('orchestrationFields','workers_per_pm',3);
const local=settingControl('localFields','max_concurrent_requests',4),copilot=settingControl('copilotAgentFields','max_concurrent_requests',2);
assert.equal(local.type,'range');assert.equal(local.min,'1');assert.equal(local.max,'16');assert.equal(copilot.type,'range');
assert.equal(local.getAttribute('aria-valuetext'),'4 リクエスト');assert.equal(copilot.getAttribute('aria-valuetext'),'2 リクエスト');
const pending=submit(),body=requests[0].options.body;
assert.equal(body.config_revision,4);assert.deepEqual(body.config.orchestration,{delegation_level:2,workers_per_pm:3,max_delegation_depth:3});
assert.equal(body.config.local.max_concurrent_requests,4);assert.equal(body.config.copilot_agent.max_concurrent_requests,2);
assert.deepEqual(body.config.providers,before.providers);assert.deepEqual(body.config.search,before.search);
assert.deepEqual(body.config.limits,before.limits);assert(local.disabled&&copilot.disabled);
$('taskInput').value='  入力中の依頼  ';$('runForm').listeners.input({type:'input',target:$('taskInput'),isComposing:true});
draft.task=$('taskInput').value;accept();await pending;assert.equal(ui.configRevision,5);assert.deepEqual(runPayload(),draft);assert(!ui.settingsDirty);
$('useOrchestrationDefaults').listeners.click();clearTimeout(ui.preflightTimer);
assert.equal(runPayload().delegation_level,2);assert.equal(runPayload().workers_per_pm,3);
assert.equal(runPayload().task,draft.task);assert.equal(runPayload().max_workers,draft.max_workers);assert.equal(requests.length,1);
''')


@pytest.mark.parametrize('event', ['input', 'change'])
def test_late_settings_save_preserves_newer_default_slider_and_task_draft(event):
    check(r'''
await setupOrchestration();settingControl('orchestrationFields','delegation_level',2);const pending=submit();
const field=$('orchestrationFields').querySelector('[data-key="delegation_level"]');field.value='0';field.listeners[EVENT]();
$('settingsForm').listeners[EVENT]({type:EVENT,target:field,isComposing:true});
taskControl('workersPerPM',6);const draft=runPayload();accept();await pending;
assert.equal(ui.config.orchestration.delegation_level,2);assert.equal(collectConfig().orchestration.delegation_level,0);
assert(ui.settingsDirty);assert.deepEqual(runPayload(),draft);assert.equal(requests.length,1);
'''.replace('EVENT', repr(event)))


def test_settings_reload_and_task_dialog_reopen_keep_current_task_sliders():
    check(r'''
await setupOrchestration();taskControl('workersPerPM',7);taskControl('delegationLevel',0);const draft=runPayload();
const pending=discardSettings();const config=structuredClone(CONFIG);config.orchestration={delegation_level:2,workers_per_pm:3};
requests[0].resolve({config,config_revision:5,secret_status:{local:false,search:false}});await pending;
assert.deepEqual(runPayload(),draft);assert.deepEqual(ui.config.orchestration,config.orchestration);
showView('work');setBriefOpen(true,false);setBriefOpen(false);setBriefOpen(true,false);renderProfileChoices(true);
assert.deepEqual(runPayload(),draft);assert.equal(requests.length,1);
''')


def test_late_accepted_start_preserves_new_slider_draft_and_focus():
    action_check(r'''
await wire();const originalApi=api;let submitted;
api=(path,options)=>{if(path==='/api/runs')submitted=structuredClone(options.body);return originalApi(path,options);};
const pending=submit();$('workersPerPM').value='4';$('delegationLevel').value='0';
$('runForm').listeners.input({type:'input',target:$('workersPerPM')});clearTimeout(ui.preflightTimer);$('workersPerPM').focus();
assert.equal(submitted.workers_per_pm,2);resolve(0,{run:{id:'created-run'}});await flush();
reject(1,new Error('Synthetic state failure'));await pending;addCreated();const observed=pollState();await drainStates();await observed;
assert.equal($('workersPerPM').value,'4');assert.equal($('delegationLevel').value,'0');assert.equal(document.activeElement,$('workersPerPM'));
assert($('taskDialog').open);assert.equal(ui.selectedRun,'run-a');assert.equal(requests.filter(r=>r.path==='/api/runs').length,1);
''')


def test_run_metrics_show_saved_policy_not_the_current_task_draft():
    action_check(r'''
await wire();getRun().delegation_level=2;getRun().workers_per_pm=3;renderRun();
const text=()=>JSON.stringify($('runMetrics').children.map(node=>[node.textContent,...node.children.map(child=>child.textContent)]));
assert(text().includes('委任必須')&&text().includes('3 人'));const before=text();
$('delegationLevel').value='0';$('workersPerPM').value='1';syncStartControl();renderRun();assert.equal(text(),before);
assert.equal(stateLabel({status:'waiting',status_reason:'delegation_incomplete'}),'委任手順が未完了');
assert(!needsHuman({status:'waiting',status_reason:'delegation_incomplete'}));
delete getRun().delegation_level;delete getRun().workers_per_pm;renderRun();assert(text().includes('未記録'));
''')
