"""Settings transfer through production callbacks; no account or live browser."""
import pytest

from test_frontend import HTML
from test_settings_save_frontend import check as settings_check


SETUP = r'''
async function boot(){await setup();for(const id of ['exportSettings','importSettings','settingsImportFile'])$('settingsForm').append($(id));$('settingsImportFile').type='file';$('settingsImportFile').id='settingsImportFile';}
function backup(config=CONFIG){return {format:'agent-workbench-settings',format_version:1,config:structuredClone(config)};}
function selected(value=backup()){return {size:200,text:async()=>JSON.stringify(value)};}
function preview(index=0){return {config:{...structuredClone(CONFIG),system_policy:'Restored policy'},config_revision:4,warnings:[]};}
function paths(){for(const id of ['pathFields','pythonFields','seleniumFields'])$(id).querySelectorAll('textarea').forEach(node=>node.classList.add('path-input'));}
'''


def check(source):
    settings_check(SETUP + source + '\nclearTimeout(ui.preflightTimer);')


def test_transfer_controls_are_accessible_and_explain_saved_only():
    for ident in ('settingsTransferTitle', 'settingsStorage', 'settingsRecovery', 'exportSettings', 'importSettings', 'settingsImportFile', 'settingsTransferStatus'):
        assert f'id="{ident}"' in HTML
    assert '以前の settings.json' in HTML
    assert '直接入力したAPIキー・会話・実行履歴は含みません' in HTML


def test_export_uses_server_saved_config_not_dirty_fields_or_credentials():
    check(r'''
await boot();edit('label','Unsaved');control().input.value='SECRET-INPUT';let download;
downloadSettingsJson=(...args)=>{download=args;};const pending=$('exportSettings').listeners.click();
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config/export');
requests[0].resolve(backup());await pending;assert.deepEqual(JSON.parse(download[0]),backup());
assert.equal(download[1],'AgentWorkbench-settings.json');
assert(!download[0].includes('Unsaved')&&!download[0].includes('SECRET-INPUT'));assert(ui.settingsDirty);
assert($('settingsTransferStatus').textContent.includes('未保存の編集は含みません'));
''')


def test_import_is_only_a_draft_until_normal_revision_guarded_save():
    check(r'''
await boot();const saved=structuredClone(ui.config),task=runPayload();const pending=importSettingsFile(selected());await flush();
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config/import-preview');assert.equal(requests[0].options.body.config_revision,4);
assert(ui.settingsReloading&&$('saveSettings').disabled&&$('discardSettings').disabled&&control().input.disabled);
requests[0].resolve(preview());await pending;assert.deepEqual(ui.config,saved);assert.deepEqual(runPayload(),task);
assert.equal($('systemPolicy').value,'Restored policy');assert(ui.settingsDirty&&!ui.settingsReloading);assert(control().input.disabled);
paths();const saving=submit();assert.equal(requests.length,2);assert.equal(requests[1].path,'/api/config');
assert.equal(requests[1].options.body.config.system_policy,'Restored policy');assert.equal(requests[1].options.body.config_revision,4);
accept(1);await saving;assert.equal(ui.config.system_policy,'Restored policy');assert(!ui.settingsDirty);
''')


def test_import_cancel_and_invalid_json_leave_draft_untouched():
    check(r'''
await boot();edit('label','Existing draft');const draft=collectConfig();await importSettingsFile(null);
await importSettingsFile({size:10,text:async()=>'{bad'});assert.equal(requests.length,0);assert.deepEqual(collectConfig(),draft);
assert(ui.settingsDirty&&!ui.settingsReloading);assert($('settingsTransferStatus').textContent.includes('JSON'));
await importSettingsFile({size:512*1024+1,text:async()=>{throw Error('must not read');}});assert.equal(requests.length,0);
assert($('settingsTransferStatus').textContent.includes('512 KB'));assert.deepEqual(collectConfig(),draft);
''')


@pytest.mark.parametrize('stage', ['reading', 'request'])
def test_late_import_does_not_overwrite_reopened_dialog(stage):
    check(r'''
await boot();let read;const file={size:200,text:()=>new Promise(resolve=>{read=resolve;})};
const pending=importSettingsFile(file);
''' + ("read(JSON.stringify(backup()));await flush();assert.equal(requests.length,1);" if stage == 'request' else '') + r'''
$('settingsDialog').close();showView('settings');$('systemPolicy').value='New draft';markSettingsDirty();
$('settingsTransferStatus').textContent='New feedback';
''' + ("requests[0].resolve(preview());" if stage == 'request' else "read(JSON.stringify(backup()));") + r'''
await pending;assert.equal($('systemPolicy').value,'New draft');assert.equal($('settingsTransferStatus').textContent,'New feedback');assert(!ui.settingsReloading);
''')


@pytest.mark.parametrize('condition', ['active', 'stale', 'saving', 'credential'])
def test_import_and_export_respect_operation_locks(condition):
    setup = {'active': "ui.state.runs=[{id:'r',status:'working'}];setSettingsLock(true);", 'stale': 'ui.configStale=true;',
             'saving': 'ui.settingsSaving=true;', 'credential': "ui.credentialOperations.set('local',{});"}[condition]
    check("await boot();" + setup + r'''
await importSettingsFile(selected());await exportSettings();assert.equal(requests.length,0);
''')


def test_import_receipt_conflict_and_malformed_leave_saved_and_draft_unchanged():
    check(r'''
await boot();edit('label','Keep');const draft=collectConfig(),saved=structuredClone(ui.config);
let pending=importSettingsFile(selected());await flush();requests[0].resolve({config_revision:4,config:{},warnings:[]});await pending;
assert.deepEqual(collectConfig(),draft);assert.deepEqual(ui.config,saved);assert(!ui.settingsReloading);
pending=importSettingsFile(selected());await flush();requests[1].reject(Object.assign(new Error('Reload'),{code:'settings_changed'}));await pending;
assert(ui.configStale&&$('saveSettings').disabled);assert.deepEqual(collectConfig(),draft);assert.deepEqual(ui.config,saved);
''')


def test_import_missing_path_warnings_are_text_and_discard_restores_saved_baseline():
    check(r'''
await boot();const saved=structuredClone(ui.config);let pending=importSettingsFile(selected());await flush();
const value=preview();value.warnings=['python.executable: <missing>'];requests[0].resolve(value);await pending;
assert($('settingsTransferStatus').textContent.includes('<missing>'));pending=discardSettings();requests[1].resolve({config:saved,config_revision:4,secret_status:{local:false,search:false}});await pending;
assert.equal($('systemPolicy').value,saved.system_policy);assert(!ui.settingsDirty);assert.deepEqual(ui.config,saved);
''')


def test_storage_path_and_recovery_warning_display_without_changing_config():
    check(r'''
await boot();const saved=structuredClone(ui.config);acceptSettingsStorage({settings_storage:{path:'C:\\State <user>\\settings.json',warnings:['python.executable']}});
assert($('settingsStorage').textContent.includes('C:\\State <user>'));assert($('settingsRecovery').textContent.includes('python.executable'));
assert.deepEqual(ui.config,saved);acceptSettingsStorage({settings_storage:{path:'C:\\State\\settings.json',warnings:[]}});assert.equal($('settingsRecovery').textContent,'');
''')


def test_file_change_callback_clears_picker_but_does_not_mark_draft_before_preview():
    check(r'''
await boot();$('settingsImportFile').files=[selected()];$('settingsImportFile').value='file.json';
const pending=$('settingsImportFile').listeners.change({target:$('settingsImportFile')});
assert.equal($('settingsImportFile').value,'');$('settingsForm').listeners.change({target:$('settingsImportFile')});assert(!ui.settingsDirty);
await flush();requests[0].resolve(preview());await pending;assert(ui.settingsDirty);
''')


def test_all_settings_groups_and_replaced_profiles_round_trip_without_changing_task():
    check(r'''
await boot();const saved=structuredClone(ui.config),task=runPayload(),value=preview();
value.config.providers=[{...value.config.providers[0],id:'restored',model:'new-model',base_url:'http://127.0.0.1:9999/v1'}];
value.config.paths={read_roots:['C:\\Inputs'],write_roots:['C:\\Outputs'],deny_roots:['C:\\Private']};
value.config.python={...value.config.python,executable:'C:\\Python\\python.exe',library_paths:['C:\\Python\\Lib'],network_enabled:true};
value.config.selenium={...value.config.selenium,library_paths:['C:\\Selenium'],proxy_url:'http://127.0.0.1:8080'};
value.config.search={...value.config.search,enabled:true,provider:'searxng',endpoint:'https://search.example/api'};
value.config.local={...value.config.local,min_interval_seconds:2};value.config.limits={...value.config.limits,max_workers:2};
value.config.copilot_agent={...COPILOT_AGENT_DEFAULTS,base_url:'http://127.0.0.1:8801/v1',model:'restored-model',max_concurrent_requests:3};
value.config.orchestration={delegation_level:2,workers_per_pm:4,max_delegation_depth:2};
const pending=importSettingsFile(selected());await flush();requests[0].resolve(value);await pending;paths();
assert.deepEqual(collectConfig(),value.config);assert.deepEqual(ui.config,saved);assert.deepEqual(runPayload(),task);
const saving=submit();assert.deepEqual(requests[1].options.body.config,value.config);accept(1);await saving;
assert.deepEqual(ui.config,value.config);assert.deepEqual(runPayload(),task);
''')


def test_legacy_import_defaults_only_missing_depth_in_draft_until_explicit_save():
    check(r'''
await boot();const saved=structuredClone(ui.config),task=runPayload(),legacy=backup();
legacy.config.orchestration={delegation_level:2,workers_per_pm:4};
// Older accepted preview shapes may also omit the new depth field. The UI
// normalizes the editable draft, without mutating the response or saved state.
const value={config:structuredClone(legacy.config),config_revision:4,warnings:[]};
const expected=structuredClone(value.config);expected.orchestration.max_delegation_depth=3;
const pending=importSettingsFile(selected(legacy));await flush();
assert.deepEqual(requests[0].options.body.backup,legacy);
requests[0].resolve(value);await pending;paths();
assert.deepEqual(collectConfig(),expected);assert.deepEqual(ui.config,saved);assert.deepEqual(runPayload(),task);
assert.equal(Object.hasOwn(value.config.orchestration,'max_delegation_depth'),false);
assert.equal(Object.hasOwn(legacy.config.orchestration,'max_delegation_depth'),false);assert(ui.settingsDirty);
const saving=submit();assert.deepEqual(requests[1].options.body.config,expected);
assert.equal(requests[1].options.body.config_revision,4);accept(1);await saving;
assert.deepEqual(ui.config,expected);assert.deepEqual(runPayload(),task);assert.equal(requests.length,2);
''')
