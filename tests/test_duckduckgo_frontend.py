"""Search settings callbacks with synthetic DOM/transport; no real requests."""
import pytest

from test_frontend import APP, HTML
from test_settings_save_frontend import check as settings_check


SETUP = r'''
const searchField=key=>$('searchFields').querySelector(`[data-key="${key}"]`);
function repaint(){
 renderSettings();
 for(const id of ['pathFields','pythonFields','seleniumFields'])$(id).querySelectorAll('textarea').forEach(node=>node.classList.add('path-input'));
}
function chooseSearch(value){
 const input=searchField('provider');input.value=value;input.listeners.change();
 $('settingsForm').listeners.change({target:input});
}
'''


def check(source):
    settings_check(SETUP + source)


def test_search_key_controls_removed_while_model_credentials_remain():
    for name in ('searchSecret', 'setSearchSecret', 'searchSecretStatus', 'searchCredentialTarget'):
        assert name not in APP and name not in HTML
    assert 'BRAVE_SEARCH_API_KEY' not in APP
    assert "['brave','Brave Search']" not in APP
    assert "['duckduckgo','DuckDuckGo（API キー不要）']" in APP
    assert "['api_key_env','API キーの環境変数名','text','OPENAI_API_KEY']" in APP
    assert "'/api/secrets'" in APP


def test_ddg_fixed_readonly_endpoint_does_not_enable_search_or_change_saved_config():
    check(r'''
await setup();const before=structuredClone(ui.config);
assert.equal(searchField('provider').value,'duckduckgo');
assert.equal(searchField('endpoint').value,'https://html.duckduckgo.com/html/');
assert.equal(searchField('endpoint').readOnly,true);assert.equal(searchField('enabled').checked,false);
assert.equal(searchField('api_key_env'),null);assert.equal(control('search'),undefined);
assert.deepEqual(collectConfig(),before);assert.deepEqual(ui.config,before);
assert(!ui.settingsDirty);assert.equal(requests.length,0);
setSettingsLock(true);assert.equal(searchField('endpoint').readOnly,true);
assert(!control().input.disabled);
''')


@pytest.mark.parametrize('enabled', [False, True])
def test_explicit_searxng_endpoint_and_switching_draft_are_preserved(enabled):
    check(r'''
await setup();Object.assign(ui.config.search,{provider:'searxng',endpoint:'https://saved.example/search',enabled:ENABLED});repaint();
const before=structuredClone(ui.config),endpoint=searchField('endpoint');
assert.equal(endpoint.readOnly,false);assert.equal(endpoint.value,before.search.endpoint);
assert.deepEqual(collectConfig(),before);
endpoint.value='https://edited.example/search';
chooseSearch('duckduckgo');assert.equal(endpoint.value,DUCKDUCKGO_SEARCH_ENDPOINT);assert(endpoint.readOnly);
assert.equal(searchField('enabled').checked,ENABLED);assert.equal(requests.length,0);
chooseSearch('searxng');assert.equal(endpoint.readOnly,false);assert.equal(endpoint.value,'https://edited.example/search');
assert.equal(collectConfig().search.endpoint,endpoint.value);assert.equal(collectConfig().search.enabled,ENABLED);
assert.deepEqual(ui.config,before);assert(ui.settingsDirty);assert.equal(requests.length,0);
'''.replace('ENABLED', str(enabled).lower()))


def test_save_ddg_fixed_endpoint_clears_retired_search_env_only_and_captures_revision():
    check(r'''
await setup();ui.config.search.api_key_env='RETIRED_SEARCH_KEY';
$('profilesEditor').querySelector('[data-key="api_key_env"]').value='MODEL_API_KEY';
searchField('endpoint').value='https://must-not-be-sent.example/search';
searchField('proxy_url').value='http://127.0.0.1:8080';markSettingsDirty();
const pending=submit();assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config');
const submitted=requests[0].options.body;
assert.equal(submitted.config_revision,4);assert.equal(submitted.config.search.endpoint,DUCKDUCKGO_SEARCH_ENDPOINT);
assert.equal(submitted.config.search.api_key_env,'');assert.equal(submitted.config.search.proxy_url,'http://127.0.0.1:8080');
assert.equal(submitted.config.search.enabled,false);assert.equal(submitted.config.providers[0].api_key_env,'MODEL_API_KEY');
assert(searchField('provider').disabled&&searchField('endpoint').readOnly);
accept();await pending;assert.equal(ui.configRevision,5);assert(!ui.settingsDirty);
assert.equal(ui.config.search.endpoint,DUCKDUCKGO_SEARCH_ENDPOINT);assert.equal(ui.config.search.api_key_env,'');
assert(!control().input.disabled);assert.equal(requests.length,1);
''')


def test_save_searxng_uses_exact_configured_endpoint_without_enabling_it():
    check(r'''
await setup();chooseSearch('searxng');searchField('endpoint').value='https://search.example/search';
const pending=submit(),submitted=requests[0].options.body.config;
assert.equal(submitted.search.provider,'searxng');assert.equal(submitted.search.endpoint,'https://search.example/search');
assert.equal(submitted.search.enabled,false);assert.equal(submitted.search.api_key_env,'');
assert.deepEqual(submitted.providers,CONFIG.providers);assert.deepEqual(submitted.selenium,CONFIG.selenium);
accept();await pending;repaint();assert(!searchField('endpoint').readOnly);
assert.equal(searchField('endpoint').value,submitted.search.endpoint);assert.equal(requests.length,1);
''')


def test_late_save_cannot_discard_a_newer_search_provider_draft():
    check(r'''
await setup();searchField('timeout_seconds').value='12';markSettingsDirty();const pending=submit();
chooseSearch('searxng');searchField('endpoint').value='https://newer.example/search';
accept();await pending;
assert.equal(ui.config.search.provider,'duckduckgo');assert.equal(ui.configRevision,5);
assert.equal(searchField('provider').value,'searxng');assert.equal(searchField('endpoint').value,'https://newer.example/search');
assert.equal(collectConfig().search.provider,'searxng');assert(ui.settingsDirty&&control().input.disabled);
assert.equal(requests.length,1);
''')


def test_normalized_saved_search_syncs_only_the_unchanged_search_fields():
    check(r'''
await setup();chooseSearch('searxng');const endpoint=searchField('endpoint'),provider=searchField('provider'),profile=$('profilesEditor').children[0];
assert.equal(endpoint.value,'');assert.equal(searchField('enabled').checked,false);
$('taskInput').value='Keep task draft';const task=runPayload(),pending=submit(),response=receipt();
Object.assign(response.config.search,{provider:'duckduckgo',endpoint:DUCKDUCKGO_SEARCH_ENDPOINT});
requests[0].resolve(response);await pending;
assert.equal(ui.configRevision,5);assert(!ui.settingsDirty);assert.equal(ui.config.search.provider,'duckduckgo');
assert.equal(provider.value,'duckduckgo');assert.equal(endpoint.value,DUCKDUCKGO_SEARCH_ENDPOINT);assert(endpoint.readOnly);
assert.equal(searchField('enabled').checked,false);assert.deepEqual(collectConfig(),ui.config);
assert.equal(searchField('endpoint'),endpoint);assert.equal(searchField('provider'),provider);assert.equal($('profilesEditor').children[0],profile);
assert.deepEqual(runPayload(),task);assert(!control().input.disabled);assert.equal(requests.length,1);
chooseSearch('searxng');assert.equal(endpoint.value,'');assert(!endpoint.readOnly);
''')


@pytest.mark.parametrize('edit', ['input', 'composition', 'silent'])
def test_normalization_response_never_overwrites_a_newer_search_edit(edit):
    notify = {
        'input': "$('settingsForm').listeners.input({target:endpoint});",
        'composition': "$('settingsForm').listeners.input({target:endpoint,isComposing:true});",
        'silent': '',
    }[edit]
    check(r'''
await setup();chooseSearch('searxng');const endpoint=searchField('endpoint'),pending=submit(),response=receipt();
Object.assign(response.config.search,{provider:'duckduckgo',endpoint:DUCKDUCKGO_SEARCH_ENDPOINT});
endpoint.value='https://newer.example/search';endpoint.focus();NOTIFY
requests[0].resolve(response);await pending;
assert.equal(ui.configRevision,5);assert.equal(ui.config.search.provider,'duckduckgo');
assert.equal(searchField('provider').value,'searxng');assert.equal(endpoint.value,'https://newer.example/search');assert(!endpoint.readOnly);
assert.equal(searchField('endpoint'),endpoint);assert.equal(document.activeElement,endpoint);
assert.equal(collectConfig().search.endpoint,endpoint.value);assert(ui.settingsDirty&&control().input.disabled);assert.equal(requests.length,1);
'''.replace('NOTIFY', notify))


def test_explicit_discard_restores_saved_ddg_and_preserves_task_draft():
    check(r'''
await setup();$('taskInput').value='  Keep task draft  ';const task=runPayload();
chooseSearch('searxng');searchField('endpoint').value='https://unsaved.example/search';
const pending=discardSettings();assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/config');
requests[0].resolve({config:CONFIG,config_revision:5,secret_status:{local:false,search:false}});await pending;
assert.equal(searchField('provider').value,'duckduckgo');assert(searchField('endpoint').readOnly);
assert.equal(searchField('endpoint').value,DUCKDUCKGO_SEARCH_ENDPOINT);assert.equal(searchField('enabled').checked,false);
assert.deepEqual(runPayload(),task);assert(!ui.settingsDirty);assert.equal(requests.length,1);
''')
