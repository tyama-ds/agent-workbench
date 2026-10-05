"""Actual credential/settings callbacks with synthetic DOM and deferred transport."""
import json

import pytest

from test_frontend import APP, run_javascript
from test_run_action_frontend import ACTION_DOM
from workbench.config import DEFAULT


CONFIG = json.loads(json.dumps(DEFAULT))
CONFIG['providers'] = [dict(CONFIG['providers'][0], model='fixture', api_key_env='')]
CONFIG['search'].update(provider='brave', endpoint='https://saved.example/search', api_key_env='')

DOM = ACTION_DOM + r'''
function matches(node,selector){
 if(selector==='*')return true;
 if(selector.includes(':checked'))return node.checked&&matches(node,selector.replace(':checked',''));
 if(selector.startsWith('.'))return selector.slice(1).split('.').every(name=>(node.className||'').split(/\s+/).includes(name)||node.classes.has(name));
 const attr=selector.match(/^(\w+)?\[([^=\]]+)(?:="([^"]*)")?\]$/);
 if(attr){if(attr[1]&&node.tagName!==attr[1].toUpperCase())return false;
  const name=attr[2],key=name.startsWith('data-')?name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()):name;
  const value=name.startsWith('data-')?node.dataset[key]:node[key];
  return attr[3]===undefined?value!==undefined:value===attr[3];}
 return node.tagName===selector.toUpperCase();
}
Node.prototype.querySelectorAll=function(selector){const all=this.children.flatMap(node=>[node,...node.querySelectorAll('*')]);return all.filter(node=>selector.split(',').some(part=>matches(node,part)));};
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
const requests=[];
async function wire(){
 await initialize();ui.authenticated=true;ui.config=structuredClone(CONFIG);ui.configRevision=4;
 $('settingsForm').append($('profilesEditor'),$('searchFields'),$('pathFields'),$('localFields'),$('budgetFields'),$('searchSecret'),$('setSearchSecret'),$('systemPolicy'));
 $('searchSecret').dataset.credential='true';$('setSearchSecret').dataset.credential='true';
 $('searchSecret').type='password';$('taskInput').value='Exact task draft';$('pmProfile').value='local';$('maxWorkers').value='1';
 renderSettings();renderProfileChoices();showView('settings');
 api=(path,options)=>new Promise((resolve,reject)=>requests.push({path,options,resolve,reject}));
}
function control(id='local'){return credentialControls().find(item=>item.id===id);}
function press(id='local'){return control(id).button.listeners.click();}
function accepted(index,id='local'){requests[index].resolve({ok:true,id,config_revision:4,configured:true});}
'''


def check(source):
    result = run_javascript(DOM + '\nconst CONFIG=' + json.dumps(CONFIG) + ';\n' + APP + '\n(async()=>{\n' + source + r'''
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_waiting_unlocks_only_saved_credentials_and_preserves_poll_focus():
    check(r'''
await wire();ui.state.runs=[{id:'run',status:'waiting'}];setSettingsLock(true);
const provider=control(),search=control('search');
assert(!provider.input.disabled&&!provider.button.disabled&&!search.input.disabled);
assert($('saveSettings').disabled);assert($('profilesEditor').querySelector('[data-key="base_url"]').disabled);
assert($('budgetFields').querySelector('[data-key="max_model_calls"]').disabled);
assert(provider.target.textContent.includes(CONFIG.providers[0].base_url));assert(provider.target.textContent.includes('local'));
provider.input.focus();provider.input.value='SYNTHETIC-new';
let disabled=false,disabledWhileFocused=false;
Object.defineProperty(provider.input,'disabled',{get:()=>disabled,set:value=>{disabled=value;if(value&&document.activeElement===provider.input)disabledWhileFocused=true;}});
setSettingsLock();setSettingsLock();assert(!disabledWhileFocused);assert.equal(document.activeElement,provider.input);
assert.equal(provider.input.value,'SYNTHETIC-new');assert.equal(requests.length,0);
''')


def test_actual_callbacks_send_captured_revision_and_never_retry_or_probe():
    check(r'''
await wire();const c=control();c.input.value='SYNTHETIC-new';
const revision=ui.settingsRevision,pending=press();assert.equal(c.input.value,'');
assert.equal(requests.length,1);assert.deepEqual(requests[0].options.body,{id:'local',key:'SYNTHETIC-new',config_revision:4});
assert(c.input.disabled&&c.button.disabled&&$('saveSettings').disabled&&$('discardSettings').disabled);
await press();setSettingsLock();await press();assert.equal(requests.length,1);
accepted(0);await pending;
assert(c.result.textContent.includes('有効性は未確認'));assert(c.result.textContent.includes('指示を送って再試行'));
assert.equal(ui.settingsDirty,false);assert(ui.settingsRevision>revision);assert.equal(ui.configRevision,4);
assert.equal(requests.length,1);assert(!c.input.disabled);assert(!c.result.textContent.includes('SYNTHETIC-new'));
''')


def test_dirty_new_target_and_search_guards_clear_abandoned_keys():
    check(r'''
await wire();control().input.value='SYNTHETIC-abandoned';control('search').input.value='SYNTHETIC-search';
$('settingsForm').listeners.input({target:{type:'text'}});
assert(ui.settingsDirty);assert(credentialControls().every(c=>c.input.disabled&&c.button.disabled&&c.input.value===''));
await press();await press('search');assert.equal(requests.length,0);
$('addProfile').listeners.click();const added=[...$('profilesEditor').children].at(-1)._credential;
assert.equal(added.id,null);assert(added.input.disabled);added.input.value='SYNTHETIC-never-sent';await added.button.listeners.click();
assert.equal(requests.length,0);assert(added.target.textContent.includes('設定を保存'));
''')


def test_independent_targets_keep_other_pending_and_configuration_locked():
    check(r'''
await wire();control().input.value='SYNTHETIC-provider';const a=press();
assert(!control('search').input.disabled);control('search').input.value='SYNTHETIC-search';const b=press('search');
assert.equal(requests.length,2);assert.equal(ui.credentialOperations.size,2);
accepted(0);await a;assert.equal(ui.credentialOperations.size,1);
assert(control('search').input.disabled&&$('saveSettings').disabled&&$('discardSettings').disabled);
await $('settingsForm').listeners.submit({preventDefault(){}});await discardSettings();assert.equal(requests.length,2);
requests[1].reject(new Error('Synthetic search failure'));await b;
assert.equal(ui.credentialOperations.size,0);assert(!control().button.disabled&&!control('search').button.disabled);
assert(control().result.textContent.includes('キーをセットしました'));assert(control('search').result.textContent.includes('Synthetic search failure'));
''')


@pytest.mark.parametrize('result', ['success', 'failure', 'unknown'])
def test_old_response_cannot_repaint_reopened_settings_or_clear_new_input(result):
    settlement = {'success': 'accepted(0);', 'failure': "requests[0].reject(new Error('Old failure'));",
                  'unknown': "requests[0].resolve({});"}[result]
    check(r'''
await wire();const c=control();c.input.value='SYNTHETIC-first';const pending=press();
showView('work');showView('settings');c.input.value='SYNTHETIC-next';c.result.textContent='Newer feedback';
const status=c.status.textContent;c.input.focus();
''' + settlement + r'''
await pending;assert.equal(c.input.value,'SYNTHETIC-next');assert.equal(c.result.textContent,'Newer feedback');
assert.equal(c.status.textContent,status);assert.equal(document.activeElement,c.input);assert(!c.input.disabled);
assert.equal(requests.length,1);
''')


@pytest.mark.parametrize('response', [{}, {'ok': True}, {'ok': True, 'id': 'other', 'config_revision': 4, 'configured': True},
                                       {'ok': True, 'id': 'local', 'config_revision': 3, 'configured': True},
                                       {'ok': True, 'id': 'local', 'config_revision': 4, 'configured': False}])
def test_malformed_acceptance_is_unknown_without_replay(response):
    check(r'''
await wire();const c=control();c.input.value='SYNTHETIC-first';const pending=press();
requests[0].resolve(''' + json.dumps(response) + r''');await pending;
assert(c.result.textContent.includes('更新されたかどうかは未確認'));assert(c.result.textContent.includes('自動再送信はしません'));
assert.equal(ui.secretStatus.local,undefined);assert.equal(requests.length,1);
''')


def test_conflict_requires_saved_config_reload_and_search_does_not_bypass_it():
    check(r'''
await wire();control().input.value='SYNTHETIC-first';const pending=press();
const error=new Error('Saved config changed');error.code='settings_changed';requests[0].reject(error);await pending;
assert(ui.configStale);assert(credentialControls().every(c=>c.input.disabled));
await press('search');assert.equal(requests.length,1);
const reload=$('discardSettings').listeners.click();assert.equal(requests[1].path,'/api/config');
requests[1].resolve({config:CONFIG,config_revision:5,secret_status:{local:false,search:false}});await reload;
assert(!ui.configStale&&!ui.settingsDirty);assert.equal(ui.configRevision,5);assert(!control().input.disabled);
''')


def test_discard_preserves_exact_task_and_chat_drafts_including_no_workers():
    check(r'''
await wire();$('workerProfiles').querySelectorAll('input').forEach(node=>{node.checked=false;});
$('taskInput').value='  Exact\n task draft  ';$('messageInput').value='  Exact chat draft  ';ui.drafts.set('agent-a','Saved chat draft');
$('maxWorkers').value='2';const before=runPayload();markSettingsDirty();ui.state.runs=[{status:'waiting'}];setSettingsLock();
const pending=$('discardSettings').listeners.click();assert.equal(requests[0].path,'/api/config');assert($('saveSettings').disabled);
requests[0].resolve({config:CONFIG,config_revision:4,secret_status:{local:false,search:false}});await pending;
assert.deepEqual(runPayload(),before);assert.equal($('messageInput').value,'  Exact chat draft  ');assert.equal(ui.drafts.get('agent-a'),'Saved chat draft');
assert(!ui.settingsDirty);assert($('saveSettings').disabled);assert(!control().input.disabled);assert.equal(requests.length,1);
''')


def test_discard_keeps_removed_task_selections_visible_and_does_not_clamp_draft():
    check(r'''
await wire();$('maxWorkers').value='3';const before=runPayload();markSettingsDirty();
const config=structuredClone(CONFIG);config.providers[0].id='replacement';config.limits.max_workers=0;
const pending=discardSettings();requests[0].resolve({config,config_revision:5,secret_status:{replacement:false,search:false}});await pending;
assert.deepEqual(runPayload(),before);assert($('pmProfile').children.some(option=>option.value==='local'&&option.textContent.includes('利用不可')));
assert($('workerProfiles').querySelectorAll('input:checked').some(input=>input.value==='local'));
''')


def test_discard_response_does_not_repaint_a_reopened_dialog():
    check(r'''
await wire();markSettingsDirty();const pending=discardSettings();showView('work');showView('settings');
$('settingsStatus').textContent='Newer settings context';const before=ui.configRevision;
requests[0].resolve({config:CONFIG,config_revision:8,secret_status:{local:false,search:false}});await pending;
assert.equal(ui.configRevision,before);assert(ui.settingsDirty);assert.equal($('settingsStatus').textContent,'Newer settings context');
assert(!ui.settingsReloading);
''')


@pytest.mark.parametrize('search', [{'provider': 'searxng', 'endpoint': 'https://saved.example/search'}, {'provider': 'brave', 'endpoint': ''}])
def test_unusable_saved_search_target_is_explained_and_cannot_send(search):
    check(r'''
await wire();Object.assign(ui.config.search,''' + json.dumps(search) + r''');refreshCredentialControls();
const c=control('search');assert(c.input.disabled&&c.button.disabled);assert(c.target.textContent.length>10);
c.input.value='SYNTHETIC-never-sent';await press('search');assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('ident', ['local', 'search'])
def test_enter_in_password_submits_only_that_key_not_the_settings_form(ident):
    check(r'''
await wire();const c=control(''' + json.dumps(ident) + r''');let prevented=false;c.input.value='SYNTHETIC-key';
c.input.listeners.keydown({key:'Enter',preventDefault(){prevented=true;}});
assert(prevented);assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/secrets');
assert.equal(requests[0].options.body.id,''' + json.dumps(ident) + r''');
accepted(0,''' + json.dumps(ident) + r''');await flush();assert.equal(ui.credentialOperations.size,0);
assert.equal(requests.length,1);assert.equal(c.input.value,'');
''')
