"""Copilot selection/settings behavior through the real UI, with no bridge launch."""
import json

from test_frontend import APP, HTML, run_javascript
from test_settings_save_frontend import check as settings_check


SETUP = r'''
const COPILOT={enabled:false,bridge_directory:'C:\\Bridge',python_executable:'C:\\Python\\python.exe',base_url:'http://127.0.0.1:8800/v1',model:'copilot',startup_timeout_seconds:600,max_concurrent_requests:1};
const bridgeProfile=()=>({...ui.config.providers[0],id:'copilot-agent',label:'Copilot Agent',kind:'local',base_url:COPILOT.base_url,model:'copilot',enabled:true});
function status(state='starting'){return {enabled:true,state,ready:state==='ready',message:'Bridge fixture',owned:true};}
async function boot(){await setup();ui.config.copilot_agent=structuredClone(COPILOT);renderSettings();for(const id of ['pathFields','pythonFields','seleniumFields'])$(id).querySelectorAll('textarea').forEach(node=>node.classList.add('path-input'));$('settingsForm').append($('copilotAgentFields'),$('reconnectCopilotAgent'));}
function saved(enabled=true,state='starting'){
  const config=structuredClone(ui.config);config.copilot_agent={...COPILOT,enabled};
  return {config,effective_providers:enabled?[bridgeProfile(),...config.providers]:config.providers,copilot_agent_status:{...status(state),enabled},secret_status:{local:false,search:false},config_revision:5};
}
function install(response){ui.config=response.config;acceptConnectionSettings(response);renderProfileChoices(true);}
function chosenWorkers(){return $('workerProfiles').querySelectorAll('input:checked').map(node=>node.value);}
'''


def check(source):
    settings_check(SETUP + source + '\nclearTimeout(ui.preflightTimer);')


def test_copilot_fields_and_bounds_are_explicit_and_not_credential_controls():
    prefix = APP[:APP.index('const $ =')]
    value = run_javascript(prefix + "console.log(JSON.stringify({fields:FIELD_GROUPS.copilot_agent,defaults:COPILOT_AGENT_DEFAULTS,bounds:NUMBER_BOUNDS.copilot_agent}));")
    assert {row[0] for row in value['fields']} == {'enabled', 'bridge_directory', 'python_executable', 'base_url', 'model', 'startup_timeout_seconds', 'max_concurrent_requests'}
    assert value['defaults']['enabled'] is False
    assert value['defaults']['startup_timeout_seconds'] == 600
    assert value['bounds']['startup_timeout_seconds'] == [5, 1200]
    assert value['defaults']['max_concurrent_requests'] == 1
    assert value['bounds']['max_concurrent_requests'] == [1, 16]
    assert 'id="copilotAgentFields"' in HTML
    assert 'id="copilotAgentStatus"' in HTML and 'id="taskCopilotAgentStatus"' in HTML
    assert 'Copilotは外部サービスです' in HTML


def test_enabling_mode_saves_only_explicit_configuration_and_keeps_persisted_profiles():
    check(r'''
await boot();const before=structuredClone(ui.config.providers),fields=$('copilotAgentFields');
fields.querySelector('[data-key="enabled"]').checked=true;
$('settingsForm').listeners.change({target:fields.querySelector('[data-key="enabled"]')});
assert.equal(requests.length,0);assert.equal(ui.config.copilot_agent.enabled,false);
const pending=submit();assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config');
assert.deepEqual(requests[0].options.body.config.providers,before);
assert.equal(requests[0].options.body.config.copilot_agent.enabled,true);
const response=receipt();response.effective_providers=[bridgeProfile(),...response.config.providers];response.copilot_agent_status=status();requests[0].resolve(response);await pending;
assert.deepEqual(ui.config.providers,before);assert.equal($('profilesEditor').children.length,1);
assert.equal($('pmProfile').children[0].value,'copilot-agent');
assert.equal($('pmProfile').value,'local','An existing task draft is preserved');
assert($('copilotAgentStatus').textContent.includes('起動中'));assert(!$('copilotAgentStatus').textContent.includes('接続可能'));
assert.equal(requests.length,1,'Saving does not perform a model call or extra launch request');
''')


def test_enabled_new_empty_task_defaults_pm_and_workers_to_bridge():
    check(r'''
await boot();$('taskInput').value='';install(saved());setBriefOpen(true,false);
assert.equal($('pmProfile').value,'copilot-agent');assert.deepEqual(chosenWorkers(),['copilot-agent']);
assert.equal(availableProfiles()[0].id,'copilot-agent');
addPM();assert.equal($('additionalPMs').querySelector('select').value,'copilot-agent');
assert.equal(runPayload().pm_profiles[1],'copilot-agent');
''')


def test_explicit_pm_and_empty_worker_selection_survive_enable_refresh_and_poll():
    check(r'''
await boot();$('taskInput').value='';$('pmProfile').value='local';
$('runForm').listeners.change({type:'change',target:$('pmProfile')});
$('workerProfiles').querySelectorAll('input').forEach(input=>{input.checked=false;});
const before=runPayload();install(saved());assert.deepEqual(runPayload(),before);
ui.copilotAgentStatus=status('ready');renderCopilotStatus();renderProfileChoices(true);
assert.deepEqual(runPayload(),before);assert.equal($('pmProfile').children[0].value,'copilot-agent');
''')


def test_explicit_worker_only_choice_does_not_get_replaced_by_copilot_defaults():
    check(r'''
await boot();$('taskInput').value='';const worker=$('workerProfiles').querySelector('input');worker.checked=false;
$('runForm').listeners.change({type:'change',target:worker});install(saved());
assert.equal($('pmProfile').value,'local');assert.deepEqual(chosenWorkers(),[]);
''')


def test_off_removes_bridge_candidate_without_silently_retargeting_a_draft():
    check(r'''
await boot();$('taskInput').value='';install(saved());setBriefOpen(true,false);$('taskInput').value='Keep this draft';const before=runPayload();
install(saved(false,'disabled'));assert.deepEqual(runPayload(),before);
assert(!availableProfiles().some(p=>p.id==='copilot-agent'));
assert($('pmProfile').children.some(option=>option.value==='copilot-agent'&&option.textContent.includes('利用不可')));
assert($('taskCopilotAgentStatus').hidden);assert.deepEqual(ui.config.providers,CONFIG.providers);
''')


def test_status_poll_never_mutates_settings_or_selected_profiles_and_rechecks_preflight():
    check(r'''
await boot();install(saved());const config=JSON.stringify(ui.config),before=runPayload();
$('taskDialog').open=true;ui.preflightKey='previous';
applyState({runs:[],agents:[],events:[],copilot_agent_status:status('ready')},{run:null,agent:null});
assert($('taskCopilotAgentStatus').textContent.includes('接続可能'));assert.equal(JSON.stringify(ui.config),config);
assert.deepEqual(runPayload(),before);assert.notEqual(ui.preflightKey,'previous');assert.equal(requests.length,0);
clearTimeout(ui.preflightTimer);applyState({runs:[],agents:[],events:[]},{run:null,agent:null});
assert($('taskCopilotAgentStatus').textContent.includes('接続可能'));
''')


def test_error_message_is_text_and_not_inferred_auth_failure():
    check(r'''
await boot();const response=saved(true,'error');response.copilot_agent_status.message='<img src=x onerror=alert(1)> Startup timed out';install(response);
assert($('copilotAgentStatus').classList.contains('error'));assert($('copilotAgentStatus').textContent.includes('<img'));
assert.equal($('copilotAgentStatus').children.length,0);assert(!$('copilotAgentStatus').textContent.includes('認証失敗'));
assert(!$('copilotAgentStatus').textContent.includes('接続可能'));
''')


def test_mismatched_or_unconfirmed_ready_status_does_not_claim_connection():
    check(r'''
await boot();const response=saved(true,'ready');response.copilot_agent_status.ready=false;install(response);
assert($('copilotAgentStatus').textContent.includes('状態未確認'));
ui.copilotAgentStatus={...status('ready'),enabled:false};renderCopilotStatus();
assert($('copilotAgentStatus').textContent.includes('状態未確認'));
''')


def test_legacy_config_without_new_fields_keeps_legacy_profile_and_exact_save_shape():
    check(r'''
await boot();delete ui.config.copilot_agent;ui.effectiveProviders=null;ui.copilotAgentStatus=null;renderSettings();
const response={config:structuredClone(ui.config),config_revision:4,secret_status:{local:false,search:false}};
assert(validSavedSettings(response,4));acceptConnectionSettings(response);renderProfileChoices(true);
assert.equal($('pmProfile').value,'local');assert.equal(availableProfiles().length,1);
assert(!Object.hasOwn(collectConfig(),'copilot_agent'));assert($('copilotAgentStatus').textContent.includes('オフ'));
''')


def test_copilot_settings_controls_share_active_run_lock():
    check(r'''
await boot();ui.state.runs=[{id:'running',status:'working'}];setSettingsLock(true);
assert($('copilotAgentFields').querySelectorAll('input').every(node=>node.disabled));
await submit();assert.equal(requests.length,0);
''')


def test_preflight_and_start_payload_use_the_same_explicit_effective_profile_ids():
    check(r'''
await boot();$('taskInput').value='';install(saved());setBriefOpen(true,false);$('taskInput').value='Task';
const payload=runPayload();assert.equal(payload.pm_profile,'copilot-agent');assert.deepEqual(payload.worker_profiles,['copilot-agent']);
$('pmProfile').value='local';$('runForm').listeners.change({type:'change',target:$('pmProfile')});
assert.equal(runPayload().pm_profile,'local');assert.deepEqual(runPayload().worker_profiles,['copilot-agent']);
assert(!Object.hasOwn(runPayload(),'effective_providers'));assert(!Object.hasOwn(runPayload(),'copilot_agent'));
''')


def test_reconnect_is_explicit_revision_bound_single_request_and_preserves_task():
    check(r'''
await boot();install(saved(true,'error'));const before=runPayload();renderCopilotStatus();
assert(!$('reconnectCopilotAgent').disabled);
const pending=$('reconnectCopilotAgent').listeners.click();await reconnectCopilotAgent();
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/copilot-agent-start');
assert.deepEqual(requests[0].options.body,{config_revision:4});assert($('reconnectCopilotAgent').disabled);
const response=saved(true,'starting');response.config_revision=4;requests[0].resolve(response);await pending;
assert.deepEqual(runPayload(),before);assert($('copilotAgentStatus').textContent.includes('起動中'));
assert($('reconnectCopilotAgent').disabled);assert.equal(requests.length,1);
''')


def test_reconnect_unknown_outcome_does_not_retry_or_mark_ready():
    check(r'''
await boot();install(saved(true,'error'));const pending=reconnectCopilotAgent();
requests[0].reject(Object.assign(new Error('Lost response'),{outcomeUnknown:true}));await pending;
assert.equal(requests.length,1);assert($('copilotReconnectStatus').textContent.includes('自動で再送信しません'));
assert(!$('copilotAgentStatus').textContent.includes('接続可能'));
''')


def test_reconnect_blocked_for_off_dirty_active_ready_and_starting_modes():
    check(r'''
await boot();await reconnectCopilotAgent();assert.equal(requests.length,0);
for(const state of ['ready','starting','pending','stopping']){install(saved(true,state));await reconnectCopilotAgent();}
install(saved(true,'error'));ui.settingsDirty=true;await reconnectCopilotAgent();ui.settingsDirty=false;
ui.state.runs=[{id:'active',status:'working'}];setSettingsLock(true);await reconnectCopilotAgent();
assert.equal(requests.length,0);
''')


def test_late_reconnect_receipt_does_not_replace_new_settings_or_status():
    check(r'''
await boot();install(saved(true,'error'));const pending=reconnectCopilotAgent();
ui.configRevision=5;const off=saved(false,'disabled');install(off);
const old=saved(true,'ready');old.config_revision=4;requests[0].resolve(old);await pending;
assert.equal(ui.config.copilot_agent.enabled,false);assert($('copilotAgentStatus').textContent.includes('オフ'));
assert.equal(requests.length,1);
''')


def test_save_acceptance_does_not_change_an_already_open_empty_task_draft():
    check(r'''
await boot();$('taskInput').value='';setBriefOpen(true,false);clearTimeout(ui.preflightTimer);
const before=runPayload();install(saved());assert.deepEqual(runPayload(),before);
setBriefOpen(false);setBriefOpen(true,false);assert.equal($('pmProfile').value,'copilot-agent');
''')
