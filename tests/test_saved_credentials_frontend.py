"""Saved-key UI contract using real callbacks and synthetic transport only."""
import json

import pytest

from test_credential_recovery_frontend import check

PREPARE = r'''
const READY={supported:true,available:true,status:'ready',error:'',path:'C:/synthetic/state/secrets/credentials.json',protection:'windows-dpapi-current-user',affected_ids:[]};
function metadata(storage=READY,sources={}){acceptCredentialMetadata({credential_storage:storage,secret_sources:sources});refreshSecretStatus(Object.fromEntries(Object.entries(sources).map(([id,x])=>[id,x.source!=='none'])));}
function receipt(index,source='saved',configured=true,storage='saved',extra={}){requests[index].resolve({ok:true,id:'local',config_revision:4,configured,storage,source,saved:source==='saved',credential_storage:READY,...extra});}
'''


def run(source):
    check(PREPARE + source)


def test_default_is_session_and_unknown_capability_disables_saved():
    run(r'''
await wire();const c=control();assert.equal(c.storage.value,'session');assert(c.savedOption.disabled);assert(!c.input.disabled&&!c.button.disabled);
assert.equal(c.input.value,'');assert.equal(c.input.type,'password');assert.equal(c.input.autocomplete,'new-password');
assert(c.modeHelp.textContent.includes('以前に暗号化保存したキーは削除'));assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('available', [False, True])
def test_saved_option_uses_observed_support_and_availability(available):
    run(r'''
await wire();metadata({...READY,available:''' + json.dumps(available) + r'''});const c=control();c.storage.value='saved';c.storage.listeners.change();
assert.equal(c.savedOption.disabled,''' + json.dumps(not available) + r''');assert.equal(c.button.disabled,''' + json.dumps(not available) + r''');
assert.equal(c.button.textContent,'キーを暗号化保存');assert.equal(ui.settingsDirty,false);assert.equal(requests.length,0);
assert($('credentialStoragePath').textContent.includes(READY.path));assert.equal(c.input.value,'');
''')


def test_selection_is_not_a_config_edit_or_key_operation():
    run(r'''
await wire();metadata();const c=control(),generation=ui.settingsDraftGeneration;
c.storage.value='saved';c.storage.listeners.change();$('settingsForm').listeners.change({target:c.storage});
assert(!ui.settingsDirty);assert.equal(ui.settingsDraftGeneration,generation);assert.equal(requests.length,0);
assert(c.modeHelp.textContent.includes('別PCや別ユーザー'));assert(!c.savedOption.disabled);
''')


def test_saved_set_requires_exact_enriched_receipt_and_never_echoes_input():
    run(r'''
await wire();metadata();const c=control();c.storage.value='saved';c.storage.listeners.change();c.input.value='SYNTHETIC-saved-key';const pending=press();
assert.deepEqual(requests[0].options.body,{id:'local',key:'SYNTHETIC-saved-key',storage:'saved',config_revision:4});
assert.equal(c.input.value,'');assert(c.button.disabled&&c.clear.disabled&&c.storage.disabled);await press();assert.equal(requests.length,1);
receipt(0);await pending;assert.equal(ui.secretSources.local.source,'saved');assert(ui.secretSources.local.saved);
assert(c.status.textContent.includes('暗号化保存'));assert(c.result.textContent.includes('次回起動'));assert(c.result.textContent.includes('有効性は未確認'));
assert(!c.result.textContent.includes('SYNTHETIC'));assert.equal(requests.length,1);assert.equal(c.input.value,'');assert(!c.clear.disabled);
''')


def test_session_replacement_changes_saved_status_only_after_acceptance():
    run(r'''
await wire();metadata(READY,{local:{source:'saved',saved:true}});const c=control();c.input.value='SYNTHETIC-session';const pending=press();
assert.equal(requests[0].options.body.storage,'session');assert.equal(ui.secretSources.local.source,'saved');
receipt(0,'session',true,'session');await pending;assert.deepEqual(ui.secretSources.local,{source:'session',saved:false});
assert(c.result.textContent.includes('以前の暗号化保存は削除'));assert(c.status.textContent.includes('今回の起動中'));assert.equal(requests.length,1);
''')


def test_failed_session_replacement_keeps_saved_status_and_never_replays():
    run(r'''
await wire();metadata(READY,{local:{source:'saved',saved:true}});const c=control();c.input.value='SYNTHETIC-session';const pending=press();
requests[0].reject(new Error('Synthetic vault removal denied'));await pending;
assert.deepEqual(ui.secretSources.local,{source:'saved',saved:true});assert(c.status.textContent.includes('暗号化保存'));assert(!c.result.textContent.includes('削除しました'));assert.equal(requests.length,1);
''')


@pytest.mark.parametrize('source', ['none', 'environment'])
def test_explicit_clear_deletes_both_direct_modes_and_retains_environment_fallback(source):
    run(r'''
await wire();metadata(READY,{local:{source:'saved',saved:true}});const c=control();c.storage.value='saved';c.input.value='SYNTHETIC-never-set';const pending=c.clear.listeners.click();
assert.deepEqual(requests[0].options.body,{id:'local',key:'',storage:'saved',config_revision:4});assert.equal(c.input.value,'');
receipt(0,''' + json.dumps(source) + ',' + json.dumps(source != 'none') + r''');await pending;
assert.equal(ui.secretSources.local.source,''' + json.dumps(source) + r''');assert.equal(ui.secretSources.local.saved,false);
assert.equal(ui.secretStatus.local,''' + json.dumps(source != 'none') + r''');assert(c.result.textContent.includes('入力・保存したキーを削除しました'));assert.equal(requests.length,1);
''')


@pytest.mark.parametrize('patch', [
    {'storage':'session'}, {'source':'session'}, {'saved':False}, {'configured':False},
    {'source':'invalid'}, {'credential_storage':{}},
    {'credential_storage':{'supported':True,'available':False}},
    {'credential_storage':{'supported':False,'available':True}},
])
def test_invalid_saved_acceptance_never_invents_success_or_replays(patch):
    run(r'''
await wire();metadata(READY,{local:{source:'environment',saved:false}});const c=control();c.storage.value='saved';c.input.value='SYNTHETIC-key';const pending=press();
receipt(0,'saved',true,'saved', ''' + json.dumps(patch) + r''');await pending;
assert(c.result.textContent.includes('未確認'));assert(c.result.textContent.includes('自動再送信はしません'));
assert.equal(ui.secretSources.local.source,'environment');assert.equal(requests.length,1);
''')


def test_blank_submit_is_not_implicit_delete():
    run(r'''
await wire();metadata(READY,{local:{source:'saved',saved:true}});const c=control();await press();
assert.equal(requests.length,0);assert.equal(ui.secretSources.local.source,'saved');assert(c.result.textContent.includes('入力してください'));
''')


def test_orphan_identity_recovery_is_explicit_id_only_and_uses_guarded_clear():
    run(r'''
await wire();metadata({...READY,available:false,status:'identity_mismatch',affected_ids:['old-profile']});
assert.equal(savedCredentialTarget('old-profile'),null);assert(!canSetCredential('old-profile'));assert(canClearCredential('old-profile'));
const c=ui.credentialRecoveryControls[0];assert(c);assert(!c.button.disabled);const pending=c.button.listeners.click();
assert.deepEqual(requests[0].options.body,{id:'old-profile',key:'',storage:'session',config_revision:4});
receipt(0,'none',false,'session',{id:'old-profile'});await pending;
assert($('credentialRecovery').hidden);assert($('credentialStorageActionStatus').textContent.includes('削除しました'));assert.equal(requests.length,1);
''')


@pytest.mark.parametrize('status', ['unsupported', 'unavailable', 'ready'])
def test_unreadable_or_unknown_storage_does_not_offer_destructive_reset(status):
    run(r'''
await wire();metadata({...READY,available:false,status:''' + json.dumps(status) + r''',affected_ids:['not-an-authorized-orphan']});
assert.equal(ui.credentialRecoveryControls.length,0);assert(!canClearCredential('not-an-authorized-orphan'));
await setCredential({id:'not-an-authorized-orphan',input:{value:''}},true);assert.equal(requests.length,0);
''')


def test_mismatch_recovery_is_locked_by_dirty_settings_and_exact_current_context():
    run(r'''
await wire();metadata({...READY,available:false,status:'identity_mismatch',affected_ids:['orphan']});const c=ui.credentialRecoveryControls[0];
markSettingsDirty();assert(c.button.disabled);await c.button.listeners.click();assert.equal(requests.length,0);
''')


def test_old_saved_response_cannot_repaint_new_server_instance():
    run(r'''
await wire();ui.instanceId='instance-a';metadata();const c=control();c.storage.value='saved';c.input.value='SYNTHETIC-key';const pending=press();
acceptServerInstance({instance_id:'instance-b'});metadata(READY,{local:{source:'none',saved:false}});c.result.textContent='New server';receipt(0);await pending;
assert.equal(ui.secretSources.local.source,'none');assert.equal(c.result.textContent,'New server');assert.equal(requests.length,1);
''')


def test_source_metadata_is_value_free_text_and_password_remains_empty():
    run(r'''
await wire();metadata(READY,{local:{source:'saved',saved:true}});const c=control();assert.equal(c.input.value,'');
assert(c.status.textContent.includes('値は取得・再表示しません'));assert(!c.status.textContent.includes('undefined'));
assert.equal(requests.length,0);assert.equal(ui.config.providers[0].enabled,true);
''')


def test_programmatic_saved_choice_cannot_bypass_unsupported_platform():
    run(r'''
await wire();metadata({...READY,supported:false,available:false,status:'unsupported'});const c=control();c.storage.value='saved';c.input.value='SYNTHETIC-never-sent';await press();
assert.equal(requests.length,0);assert(c.result.textContent.includes('利用できません'));assert.equal(ui.secretSources.local,undefined);
''')


def test_saved_identity_change_error_preserves_config_draft_and_requires_explicit_clear():
    run(r'''
await wire();metadata(READY,{local:{source:'saved',saved:true}});const card=$('profilesEditor').querySelector('.profile-editor');
card.querySelector('[data-key="base_url"]').value='https://new.example/v1';markSettingsDirty();
const pending=$('settingsForm').listeners.submit({preventDefault(){}});assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config');
const error=new Error('Saved credential identity changed');error.code='saved_credential_identity_change';requests[0].reject(error);await pending;
assert(ui.settingsDirty);assert.equal(card.querySelector('[data-key="base_url"]').value,'https://new.example/v1');
assert.equal(ui.config.providers[0].base_url,CONFIG.providers[0].base_url);assert.equal(ui.secretSources.local.source,'saved');
assert($('settingsStatus').textContent.includes('下書きは保存していません'));assert($('settingsStatus').textContent.includes('キーを削除'));assert.equal(requests.length,1);
''')
