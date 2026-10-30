"""Skill catalog UI callbacks with a synthetic DOM and deferred HTTP only."""
import pytest

from test_frontend import HTML
from test_settings_save_frontend import check as settings_check


SETUP = r'''
async function bootSkills(){
 await setup();ui.instanceId='skills-instance';
 $('reloadSkills').tagName='BUTTON';$('reloadSkills').type='button';$('reloadSkills').dataset.readonly='true';
 $('settingsForm').append($('reloadSkills'));renderSkillControls();
}
function skill(extra={}){return {id:'skill-1',name:'weather-table',description:'天気を表へまとめる',path:'C:/workspace/skills/weather-table/SKILL.md',base_directory:'C:/workspace/skills/weather-table',sha256:'a'.repeat(64),...extra};}
function catalog(extra={}){return {skills:[skill()],errors:[],config_revision:4,instance_id:'skills-instance',...extra};}
function reload(){return $('reloadSkills').listeners.click();}
function skillText(node){return [node.textContent,...node.children.map(skillText)].join('\n');}
'''


def check(source):
    settings_check(SETUP + source + '\nclearTimeout(ui.preflightTimer);')


def test_catalog_controls_explain_saved_scope_and_are_accessible():
    for ident in ('skillsTitle', 'skillsHelp', 'reloadSkills', 'skillsStatus', 'skillsList', 'skillsErrors'):
        assert f'id="{ident}"' in HTML
    assert 'skills/&lt;name&gt;/SKILL.md' in HTML
    assert '.agents/skills/&lt;name&gt;/SKILL.md' in HTML
    assert '未保存の設定は使いません' in HTML
    assert 'スクリプトの自動実行はありません' in HTML
    assert 'id="skillsStatus" class="inline-status" role="status" aria-live="polite"' in HTML
    assert 'id="reloadSkills" class="button secondary" type="button" data-readonly="true"' in HTML


def test_catalog_is_explicit_only_and_does_not_scan_on_open_or_state_render():
    check(r'''
await bootSkills();assert.equal(requests.length,0);
showView('work');showView('settings');renderState();renderSettings();setSettingsLock();
assert.equal(requests.length,0);assert.equal(ui.skillsCatalog,null);
assert($('skillsStatus').textContent.includes('未確認'));
''')


def test_refresh_uses_saved_config_and_renders_untrusted_fields_as_text():
    check(r'''
await bootSkills();edit('label','Unsaved draft');const saved=structuredClone(ui.config),task=runPayload();
const pending=reload();assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/skills');
assert.equal(requests[0].options,undefined);assert($('reloadSkills').disabled);
assert.equal($('skillsList').getAttribute('aria-busy'),'true');
await reload();setSettingsLock();assert.equal(requests.length,1);assert($('reloadSkills').disabled);
const malicious='<img src=x onerror=alert(1)>';
requests[0].resolve(catalog({skills:[skill({name:malicious,description:malicious,path:malicious,base_directory:malicious})],errors:[{path:malicious,error:malicious}]}));
await pending;
assert.equal(ui.skillsCatalog.skills.length,1);assert.equal($('skillsList').children.length,1);assert.equal($('skillsErrors').children.length,1);
assert(skillText($('skillsList')).includes(malicious));assert(skillText($('skillsErrors')).includes(malicious));
assert.equal($('skillsList').querySelectorAll('img').length,0);assert.equal($('skillsErrors').querySelectorAll('img').length,0);
assert($('skillsStatus').textContent.includes('読込エラー 1 件'));assert($('skillsStatus').classList.contains('error'));
assert($('skillsStatus').textContent.includes('保存済み設定'));assert.equal($('skillsList').getAttribute('aria-busy'),'false');
assert(!ui.skillsOperation&&!$('reloadSkills').disabled);assert(ui.settingsDirty);
assert.deepEqual(ui.config,saved);assert.deepEqual(runPayload(),task);assert.equal(collectConfig().providers[0].label,'Unsaved draft');
''')


def test_empty_catalog_and_read_errors_are_distinguished():
    check(r'''
await bootSkills();let pending=reload();requests[0].resolve(catalog({skills:[]}));await pending;
assert($('skillsStatus').textContent.includes('読み込めるスキルはありません'));assert(!$('skillsStatus').classList.contains('error'));
pending=reload();requests[1].resolve(catalog({skills:[],errors:[{path:'',error:'探索上限に達しました'}]}));await pending;
assert($('skillsStatus').classList.contains('error'));assert(skillText($('skillsErrors')).includes('探索上限'));
assert(skillText($('skillsErrors')).includes('スキルの探索'));
''')


def test_revision_conflict_requires_reloading_saved_settings_before_another_scan():
    check(r'''
await bootSkills();const pending=reload(),error=new Error('Saved settings changed');error.code='settings_changed';
requests[0].reject(error);await pending;
assert(ui.configStale);assert($('reloadSkills').disabled);assert($('saveSettings').disabled);
await reload();assert.equal(requests.length,1);assert.equal(ui.skillsCatalog,null);
''')


def test_failure_clears_previous_catalog_and_retries_only_on_another_click():
    check(r'''
await bootSkills();let pending=reload();requests[0].resolve(catalog());await pending;
pending=reload();assert.equal($('skillsList').children.length,0);requests[1].reject(new Error('Read failed'));await pending;
assert.equal(ui.skillsCatalog,null);assert($('skillsStatus').textContent.includes('Read failed'));
await flush();renderState();setSettingsLock();assert.equal(requests.length,2);
pending=reload();requests[2].resolve(catalog());await pending;assert.equal(ui.skillsCatalog.skills.length,1);
''')


@pytest.mark.parametrize('change', [
    "value.config_revision=5;", "value.instance_id='other-instance';", "delete value.skills;",
    "value.errors=[{path:'x'}];", "value.skills[0].sha256='invalid';",
    "delete value.skills[0].base_directory;", "value.skills.push({...value.skills[0]});",
])
def test_malformed_or_mismatched_receipt_is_not_accepted(change):
    check(r'''
await bootSkills();const pending=reload(),value=catalog();
''' + change + r'''
requests[0].resolve(value);await pending;
assert.equal(ui.skillsCatalog,null);assert.equal($('skillsList').children.length,0);
assert($('skillsStatus').classList.contains('error'));assert(!ui.skillsOperation);assert.equal(requests.length,1);
''')


def test_close_reopen_ignores_late_result_without_releasing_new_request():
    check(r'''
await bootSkills();const old=reload();$('settingsDialog').close();showView('settings');
const current=reload();assert.equal(requests.length,2);
requests[0].resolve(catalog({skills:[skill({name:'Old answer'})]}));await old;
assert.equal(ui.skillsCatalog,null);assert($('reloadSkills').disabled);assert(ui.skillsOperation);
requests[1].resolve(catalog({skills:[skill({name:'Current answer'})]}));await current;
assert(skillText($('skillsList')).includes('Current answer'));assert(!skillText($('skillsList')).includes('Old answer'));
''')


def test_saved_settings_invalidate_catalog_and_pending_response_without_auto_reload():
    check(r'''
await bootSkills();const pending=reload();edit('label','New saved label');const saving=submit();
assert.equal(requests[1].path,'/api/config');requests[1].resolve({...receipt(1),instance_id:ui.instanceId});await saving;
assert.equal($('settingsStatus').textContent,'設定を保存しました。');assert(!ui.configStale);
assert.equal(ui.configRevision,5);assert.equal(ui.skillsCatalog,null);assert($('skillsStatus').textContent.includes('未確認'));
requests[0].resolve(catalog());await pending;assert.equal(ui.skillsCatalog,null);assert.equal($('skillsList').children.length,0);
assert.equal(requests.filter(r=>r.path==='/api/skills').length,1);
''')


def test_server_change_invalidates_catalog_and_late_response():
    check(r'''
await bootSkills();const pending=reload();acceptServerInstance({instance_id:'next-instance'});
requests[0].resolve(catalog());await pending;
assert.equal(ui.skillsCatalog,null);assert.equal($('skillsList').children.length,0);
assert(ui.configStale);assert($('reloadSkills').disabled);assert.equal(requests.length,1);
''')


@pytest.mark.parametrize('condition', [
    'ui.configStale=true;', 'ui.settingsSaving=true;', 'ui.settingsReloading=true;',
    'ui.authenticated=false;', "$('settingsDialog').close();",
])
def test_unready_or_closed_settings_do_not_scan(condition):
    check('await bootSkills();' + condition + r'''
renderSkillControls();await reload();assert.equal(requests.length,0);
''')


def test_read_only_refresh_during_run_does_not_change_the_run_or_draft():
    check(r'''
await bootSkills();ui.state.runs=[{id:'active',status:'working',skills:{skills:[skill({name:'Run snapshot'})],errors:[]}}];
setSettingsLock();const before=structuredClone(ui.state.runs),draft=collectConfig();
assert(!ui.settingsSaving&&ui.settingsLocked);assert(!$('reloadSkills').disabled);
const pending=reload();requests[0].resolve(catalog({skills:[skill({name:'New file version'})]}));await pending;
assert.deepEqual(ui.state.runs,before);assert.deepEqual(collectConfig(),draft);assert.equal(requests.length,1);
''')
