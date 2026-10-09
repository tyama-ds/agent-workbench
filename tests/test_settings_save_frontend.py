"""Settings Save ownership through production callbacks and deferred transport."""
import json

import pytest

from test_credential_recovery_frontend import check as credential_check


SETUP = r'''
async function setup(){
 await wire();$('systemPolicy').tagName='TEXTAREA';
 $('pathFields').querySelectorAll('textarea').forEach(node=>node.classList.add('path-input'));
 const bottom=element('button');bottom.type='submit';$('settingsForm').append(bottom);
 $('settingsForm').append($('discardSettings'));$('discardSettings').tagName='BUTTON';$('discardSettings').dataset.readonly='true';
}
function submit(){return $('settingsForm').listeners.submit({preventDefault(){}});}
function edit(key,value){$('profilesEditor').querySelector(`[data-key="${key}"]`).value=value;markSettingsDirty();}
function receipt(index=0){const config=structuredClone(requests[index].options.body.config);return {config,config_revision:requests[index].options.body.config_revision+1,secret_status:{...Object.fromEntries(config.providers.map(p=>[p.id,false])),search:false}};}
function accept(index=0){requests[index].resolve(receipt(index));}
'''


def check(source):
    credential_check(SETUP + source)


def test_save_captures_revision_and_config_and_keeps_pending_controls_locked():
    check(r'''
await setup();edit('label','Saved label');const pending=submit();
assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config');
assert.equal(requests[0].options.body.config_revision,4);assert.equal(requests[0].options.body.config.providers[0].label,'Saved label');
assert(ui.settingsSaving&&$('saveSettings').disabled&&$('systemPolicy').disabled&&$('discardSettings').disabled);
assert($('settingsForm').querySelector('button[type="submit"]').disabled);assert(control().input.disabled);
setSettingsLock();await submit();await discardSettings();assert.equal(requests.length,1);
accept();await pending;assert.equal(ui.configRevision,5);assert.equal(ui.config.providers[0].label,'Saved label');
assert(!ui.settingsDirty&&!ui.settingsSaving&&!ui.configStale&&!$('saveSettings').disabled&&!control().input.disabled);
assert.equal($('settingsStatus').textContent,'設定を保存しました。');assert.equal(ui.settingsSaveOperation,null);
''')


def test_save_preserves_exact_task_and_chat_drafts_empty_workers_and_over_limit():
    check(r'''
await setup();$('taskInput').value='  Exact\n task  ';$('messageInput').value='  Exact chat  ';ui.drafts.set('agent-a','  Stored chat  ');
$('workerProfiles').querySelectorAll('input').forEach(input=>{input.checked=false;});$('maxWorkers').value='3';
$('budgetFields').querySelector('[data-key="max_workers"]').value='0';markSettingsDirty();const before=runPayload();const pending=submit();
accept();await pending;assert.deepEqual(runPayload(),before);assert.equal($('maxWorkers').max,'0');
assert.equal($('messageInput').value,'  Exact chat  ');assert.equal(ui.drafts.get('agent-a'),'  Stored chat  ');
''')


def test_save_preserves_removed_profiles_as_unavailable_selected_drafts():
    check(r'''
await setup();$('maxWorkers').value='3';const before=runPayload();edit('id','replacement');const pending=submit();accept();await pending;
assert.deepEqual(runPayload(),before);assert($('pmProfile').children.some(option=>option.value==='local'&&option.textContent.includes('利用不可')));
assert($('workerProfiles').querySelectorAll('input:checked').some(input=>input.value==='local'));
assert.equal(control('replacement').id,'replacement');
''')


@pytest.mark.parametrize('close', ['showView', 'native', 'queued_native'])
@pytest.mark.parametrize('outcome', ['success', 'known_failure', 'unknown', 'conflict', 'malformed'])
def test_late_save_settlement_cannot_repaint_reopened_status_notices_or_newer_task(close, outcome):
    close_code = {'showView': "showView('work');", 'native': "$('settingsDialog').close();",
                  'queued_native': "$('settingsDialog').open=false;await new Promise(resolve=>setTimeout(()=>{$('settingsDialog').listeners.close();resolve();},0));"}[close]
    settlement = {'success': 'accept();', 'known_failure': "requests[0].reject(new Error('Old failure'));",
                  'unknown': "requests[0].reject(Object.assign(new Error('Old lost response'),{outcomeUnknown:true}));",
                  'conflict': "requests[0].reject(Object.assign(new Error('Old conflict'),{code:'settings_changed'}));",
                  'malformed': 'requests[0].resolve({});'}[outcome]
    check(r'''
await setup();edit('label','Submitted');const pending=submit();
''' + close_code + r'''
setBriefOpen(true);clearTimeout(ui.preflightTimer);$('taskInput').value='  New task draft  ';
$('workerProfiles').querySelectorAll('input').forEach(input=>{input.checked=false;});$('maxWorkers').value='0';trackTaskDraft();
const draft=runPayload();showView('settings');const newerStatus='Newer dialog feedback';$('settingsStatus').textContent=newerStatus;
const diagnostic=$('profilesEditor').querySelector('[data-probe-result]');diagnostic.textContent='Newer diagnostic feedback';
notice('Newer unrelated notice',true);const focused=$('profilesEditor').querySelector('[data-readonly]');focused.focus();
''' + settlement + r'''
await pending;clearTimeout(ui.preflightTimer);assert.deepEqual(runPayload(),draft);
assert.equal($('settingsStatus').textContent,newerStatus);assert.equal(diagnostic.textContent,'Newer diagnostic feedback');
assert.equal($('globalNotice').textContent,'Newer unrelated notice');assert.equal(document.activeElement,focused);
assert(!ui.settingsSaving);assert.equal(requests.length,1);
''' + ("assert.equal(ui.configRevision,5);assert(!ui.settingsDirty&&!ui.configStale);" if outcome == 'success' else
       "assert.equal(ui.configRevision,4);assert(ui.settingsDirty);" + ("assert(ui.configStale&&$('saveSettings').disabled);" if outcome in ['unknown', 'conflict', 'malformed'] else "assert(!ui.configStale&&!$('saveSettings').disabled);")))


def test_native_close_does_not_make_identical_saved_settings_falsely_dirty():
    check(r'''
await setup();edit('label','Submitted');const draftGeneration=ui.settingsDraftGeneration;const pending=submit();
$('settingsDialog').close();assert.equal(ui.settingsDraftGeneration,draftGeneration);
const status=$('settingsStatus').textContent;assert(status.includes('閉じても保存要求は取り消されません'));
accept();await pending;assert(!ui.settingsDirty&&!ui.configStale);assert.equal(ui.configRevision,5);
showView('settings');assert.equal($('settingsStatus').textContent,status);assert(!control().input.disabled);
''')


@pytest.mark.parametrize('mutate', ["edit('label','Newer draft');", "edit('label','Intermediate');edit('label','Submitted');",
                                  "$('profilesEditor').querySelector('[data-key=\"label\"]').value='Unsignaled draft';"])
def test_accepted_baseline_does_not_mark_a_newer_settings_draft_clean(mutate):
    check(r'''
await setup();edit('label','Submitted');const pending=submit();
''' + mutate + r'''
const status=$('settingsStatus').textContent;accept();await pending;
assert.equal(ui.config.providers[0].label,'Submitted');assert.equal(ui.configRevision,5);assert(ui.settingsDirty);
assert.equal($('settingsStatus').textContent,status);assert(control().input.disabled);
''')


@pytest.mark.parametrize('response', [{}, {'config_revision': -1}, {'config_revision': 5.5},
    {'config_revision': 4}, {'config_revision': 6}, {'config_revision': 9007199254740992},
    {'config': None}, {'config': []}, {'secret_status': {}}, {'secret_status': {'local': 'yes', 'search': False}}])
def test_malformed_acceptance_latches_unknown_until_explicit_reload(response):
    check(r'''
await setup();edit('label','Keep draft');const before=collectConfig();const pending=submit();
const bad={...receipt(),...''' + json.dumps(response) + r'''};
''' + ('delete bad.config;' if response == {} else '') + r'''
requests[0].resolve(bad);await pending;
assert(ui.settingsDirty&&ui.configStale);assert.deepEqual(collectConfig(),before);assert.equal(ui.configRevision,4);
assert($('saveSettings').disabled&&$('settingsForm').querySelector('button[type="submit"]').disabled);
assert(control().input.disabled);assert(!$('systemPolicy').disabled&&!$('discardSettings').disabled);
assert($('settingsStatus').textContent.includes('保存されたかどうかは未確認'));
await submit();assert.equal(requests.length,1);edit('label','Refined retained draft');await submit();assert.equal(requests.length,1);
const reload=discardSettings();requests[1].resolve({config:CONFIG,config_revision:7,secret_status:{local:false,search:false}});await reload;
assert(!ui.configStale&&!ui.settingsDirty&&!$('saveSettings').disabled);assert.equal(ui.configRevision,7);
''')


def test_conflict_keeps_draft_and_disables_save_credentials_and_diagnostics():
    check(r'''
await setup();edit('label','Keep conflict draft');const before=collectConfig(),pending=submit();
requests[0].reject(Object.assign(new Error('Changed elsewhere'),{code:'settings_changed'}));await pending;
assert(ui.configStale&&ui.settingsDirty);assert.deepEqual(collectConfig(),before);assert.equal(ui.configRevision,4);
assert($('settingsLockStatus').textContent.includes('保存済み設定を読み直す'));
assert($('profilesEditor').querySelector('[data-probe]').disabled);assert(control().input.disabled);
await submit();await $('profilesEditor').querySelector('[data-probe]').listeners.click();assert.equal(requests.length,1);
''')


def test_known_rejection_allows_explicit_corrected_retry_without_automatic_replay():
    check(r'''
await setup();edit('label','First');const pending=submit();requests[0].reject(new Error('Known rejection'));await pending;
assert(!ui.configStale&&ui.settingsDirty&&!$('saveSettings').disabled);assert.equal(requests.length,1);
edit('label','Corrected');const retry=submit();assert.equal(requests[1].options.body.config_revision,4);accept(1);await retry;
assert.equal(ui.configRevision,5);assert.equal(ui.config.providers[0].label,'Corrected');assert.equal(requests.length,2);
''')


def test_pending_and_completion_respect_active_run_configuration_lock():
    check(r'''
await setup();edit('label','Submitted');const pending=submit();ui.state.runs=[{id:'active',status:'waiting'}];setSettingsLock();
accept();await pending;assert($('saveSettings').disabled&&$('systemPolicy').disabled);assert(!control().input.disabled);
await submit();assert.equal(requests.length,1);
''')


def test_task_worker_focus_is_restored_only_after_its_dom_replacement():
    check(r'''
await setup();edit('label','Submitted');const pending=submit();showView('work');setBriefOpen(true);clearTimeout(ui.preflightTimer);
const worker=$('workerProfiles').querySelector('input');worker.focus();
const nativeReplace=Node.prototype.replaceChildren;
Node.prototype.replaceChildren=function(...nodes){if(this.querySelectorAll('*').includes(document.activeElement))document.activeElement=document.body;nativeReplace.apply(this,nodes);};
accept();await pending;clearTimeout(ui.preflightTimer);
assert.notEqual(document.activeElement,worker);assert.equal(document.activeElement.dataset.focusKey,'task-worker:local');
''')


def test_failed_reload_does_not_remove_unknown_save_lock_or_draft():
    check(r'''
await setup();edit('label','Keep draft');const pending=submit();requests[0].reject(Object.assign(new Error('Lost'),{outcomeUnknown:true}));await pending;
const before=collectConfig(),reload=discardSettings();requests[1].resolve({config:{},config_revision:8,secret_status:{}});await reload;
assert(ui.configStale&&ui.settingsDirty);assert.deepEqual(collectConfig(),before);assert($('saveSettings').disabled);
''')


def test_pristine_save_with_unsignaled_newer_field_is_marked_dirty_on_acceptance():
    check(r'''
await setup();assert(!ui.settingsDirty);const pending=submit();
$('profilesEditor').querySelector('[data-key="label"]').value='Unsignaled newer field';
accept();await pending;assert(ui.settingsDirty);assert(control().input.disabled);
assert.equal(ui.config.providers[0].label,CONFIG.providers[0].label);
assert.equal($('profilesEditor').querySelector('[data-key="label"]').value,'Unsignaled newer field');
''')
