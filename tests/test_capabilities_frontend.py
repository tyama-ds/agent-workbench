"""Real GUI callbacks for optional multiple PMs and bounded Python settings."""
from test_credential_recovery_frontend import check as credential_check
from test_frontend import APP, run_javascript
from test_task_guidance import Elements
from workbench.config import DEFAULT


SETUP = r'''
Node.prototype.append=function(...items){for(const node of items){node.parentElement=this;this.children.push(node);}};
Node.prototype.remove=function(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(node=>node!==this);this.parentElement=null;};
async function setup(){
  await wire();
  $('pythonFields').querySelectorAll('textarea').forEach(node=>node.classList.add('path-input'));
  ui.config.providers.push({...ui.config.providers[0],id:'alternate',label:'Alternate'});
  renderProfileChoices();showView('work');setBriefOpen(true);clearTimeout(ui.preflightTimer);
  $('maxWorkers').value='0';trackTaskDraft();
}
function add(){addPM();clearTimeout(ui.preflightTimer);}
function remove(index){$('additionalPMs').children[index].querySelector('button').listeners.click();clearTimeout(ui.preflightTimer);}
function selectExtra(index,value){$('additionalPMs').querySelectorAll('select')[index].value=value;$('runForm').listeners.change({type:'change'});clearTimeout(ui.preflightTimer);}
function submit(){return $('runForm').listeners.submit({preventDefault(){}});}
'''


def check(source):
    credential_check(SETUP + source + '\nclearTimeout(ui.preflightTimer);')


def test_extra_pm_controls_start_collapsed_and_do_not_submit():
    tree = Elements()
    assert tree.ids['additionalPMSettings']['tag'] == 'details'
    assert 'open' not in tree.ids['additionalPMSettings']['attrs']
    assert tree.ids['addPM']['attrs']['type'] == 'button'
    assert all(word in tree.ids['runForm']['text'] for word in ('全PMで共有する作業者数', 'PMは含みません'))
    assert all(word in tree.ids['additionalPMSettings']['text'] for word in ('通常は PM 1 人', '最大16人', '同じ API', 'チーム全体で共有'))


def test_pm_selection_defaults_to_one_allows_duplicates_and_enforces_sixteen():
    check(r'''
await setup();assert.equal(runPayload().pm_profiles,undefined);
const initial=ui.taskDraftGeneration;for(let i=0;i<15;i++)add();
assert.deepEqual(runPayload().pm_profiles,Array(16).fill('local'));assert($('addPM').disabled);
assert.equal($('additionalPMCount').textContent,'PM 16 人');assert.equal($('additionalPMSettings').open,true);
addPM();assert.equal($('additionalPMs').children.length,15);assert(ui.taskDraftGeneration>initial);
remove(0);assert.equal(runPayload().pm_profiles.length,15);assert(!$('addPM').disabled);
assert.equal($('additionalPMs').children[0].querySelector('label').textContent,'PM 2 のプロファイル');
assert.equal(document.activeElement,$('additionalPMs').children[0].querySelector('select'));
while($('additionalPMs').children.length)remove(0);
assert.equal(runPayload().pm_profiles,undefined);assert.equal(document.activeElement,$('addPM'));
assert.equal(requests.length,0);
''')


def test_setting_refresh_preserves_extra_pm_draft_and_marks_removed_profiles_unavailable():
    check(r'''
await setup();add();add();selectExtra(1,'alternate');
const before=runPayload(),focused=$('additionalPMs').querySelectorAll('select')[0];focused.focus();
ui.config.providers=ui.config.providers.filter(profile=>profile.id==='alternate');
renderProfileChoices(true);assert.deepEqual(runPayload(),before);assert.equal(document.activeElement,focused);
assert(focused.children.some(option=>option.value==='local'&&option.textContent.includes('利用不可')));
setBriefOpen(false);setBriefOpen(true);clearTimeout(ui.preflightTimer);assert.deepEqual(runPayload(),before);
selectExtra(0,'');assert($('startRun').disabled);
selectExtra(0,'alternate');assert(!$('startRun').disabled);
''')


def test_preflight_and_explicit_start_send_identical_multi_pm_choices():
    check(r'''
await setup();add();add();selectExtra(1,'alternate');const expected=runPayload();
const preview=refreshPreflight(ui.preflightRequest);
assert.equal(requests[0].path,'/api/run-preflight');assert.deepEqual(requests[0].options.body,expected);
requests[0].resolve({can_start:true,blockers:[],warnings:[],destinations:[{role:'PM',pm_count:2,worker_available:true,label:'Local',model:'fixture',endpoint:'http://127.0.0.1'}],scope:{},web:{}});await preview;
assert($('preflightDetails').children.some(node=>node.textContent.includes('PM 2 人 / 作業者候補')));
const started=submit();assert.equal(requests[1].path,'/api/runs');assert.deepEqual(requests[1].options.body,expected);
const action=ui.startOperation;selectExtra(1,'local');assert(!ownsTaskDialog(action));
requests[1].reject(new Error('Synthetic rejection'));await started;
assert.deepEqual(runPayload().pm_profiles,['local','local','local']);
assert($('runFormStatus').textContent.includes('現在の下書きは送信していません'));
''')


def test_add_remove_and_change_pm_invalidate_pending_task_reuse_without_losing_text():
    check(r'''
await setup();ui.state.runs=[{id:'source',task:'Displayed earlier task'}];ui.selectedRun='source';
const draft=$('taskInput').value;beginTaskReuse();assert(ui.taskReuseCandidate);add();
assert.equal(ui.taskReuseCandidate,null);assert.equal($('taskInput').value,draft);
beginTaskReuse();selectExtra(0,'alternate');assert.equal(ui.taskReuseCandidate,null);
beginTaskReuse();remove(0);assert.equal(ui.taskReuseCandidate,null);assert.equal($('taskInput').value,draft);
add();const payload=runPayload();$('taskInput').value='';beginTaskReuse();
assert.deepEqual(runPayload(),{...payload,task:'Displayed earlier task'});assert.equal(requests.length,0);
''')


def test_topology_displays_independent_pm_roots_with_their_own_workers():
    check(r'''
await setup();const agents=[{id:'p1',parent_id:null,name:'PM 1'},{id:'p2',parent_id:null,name:'PM 2'},
{id:'w1',parent_id:'p1',name:'Writer',role:'pm'},{id:'w2',parent_id:'p2',name:'Reviewer'}];
renderTeamMap(agents);assert.equal($('teamMap').children.length,2);
const branches=$('teamMap').children;
assert.equal(branches[0].querySelector('.map-root').dataset.focusKey,'map:p1');
assert.equal(branches[1].querySelector('.map-root').dataset.focusKey,'map:p2');
assert.equal(branches[0].querySelector('.map-node').dataset.focusKey,'map:w1');
assert.equal(branches[1].querySelector('.map-node').dataset.focusKey,'map:w2');
assert.equal(branches[0].querySelector('.map-node').children[0].textContent,'W');
''')


def test_python_settings_cover_config_and_numeric_bounds():
    prefix = APP[:APP.index('const $ =')]
    fields = run_javascript(prefix + 'console.log(JSON.stringify({fields:FIELD_GROUPS.python,bounds:NUMBER_BOUNDS.python}));')
    assert {field[0] for field in fields['fields']} == set(DEFAULT['python'])
    assert fields['bounds'] == {'timeout_seconds': [1, 600], 'max_memory_mb': [128, 8192], 'max_output_bytes': [1024, 1048576]}
    check(r'''
await setup();const fields=$('pythonFields');assert.equal(fields.querySelectorAll('[data-key]').length,6);
assert.equal(fields.querySelector('[data-key="enabled"]').checked,false);
fields.querySelector('[data-key="enabled"]').checked=true;
fields.querySelector('[data-key="executable"]').value='C:\\ExistingPython\\python.exe';
fields.querySelector('[data-key="library_paths"]').value='C:\\Library One\nC:\\Library Two';
fields.querySelector('[data-key="timeout_seconds"]').value='90';
const config=collectConfig();assert(config.python.enabled);assert.equal(config.python.timeout_seconds,90);
assert.deepEqual(config.python.library_paths,['C:\\Library One','C:\\Library Two']);
assert.equal(fields.querySelector('[data-key="max_memory_mb"]').max,'8192');
ui.state.runs=[{id:'working',status:'running'}];setSettingsLock();assert(fields.querySelectorAll('[data-key]').every(node=>node.disabled));
ui.state.runs=[];setSettingsLock();assert(fields.querySelectorAll('[data-key]').every(node=>!node.disabled));
''')


def test_python_help_explains_existing_runtime_and_explicit_file_access():
    tree = Elements()
    panel = tree.ids['pythonFields']['ancestors'][-1]['text']
    for term in ('既定は無効', '同梱・自動インストールは行いません', '隔離実行', '停止', '無制限な実行へ切り替えません',
                 'ネットワーク通信', '子プロセス', '読み取り制限の例外', '明示した入力', '明示した出力'):
        assert term in panel
