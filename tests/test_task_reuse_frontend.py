"""Displayed request preparation only; real callbacks and deferred transport."""
import pytest

from test_frontend import APP, run_javascript
from test_disclosure_focus_frontend import FOCUS_DOM
from test_run_action_frontend import ACTION_DOM, ACTION_FIXTURES
from test_task_guidance import Elements


SETUP = r'''
async function setup(){
  await wire();setBriefOpen(false);clearTimeout(ui.preflightTimer);
  $('taskInput').value='';trackTaskDraft();
  getRun().task='  Displayed <script>request</script>\n[redacted]\t  ';
  getRun().pm_profile='old-profile';getRun().worker_profiles=['old-worker'];getRun().max_workers=16;
  $('pmProfile').value='current';$('maxWorkers').value='0';trackTaskDraft();
  $('messageInput').value='  Separate agent draft  ';saveAgentDraft({type:'input'});
  $('agentSearch').value='Current search';ui.needsOnly=true;
  $('conversationLog').scrollTop=75;renderRun();
}
function reuse(){return $('reuseTask').listeners.click();}
function replace(){return $('replaceTaskDraft').listeners.click();}
function keep(){return $('keepTaskDraft').listeners.click();}
function task(value){$('taskInput').value=value;trackTaskDraft();}
'''


def check(source):
    fixtures = ACTION_FIXTURES.replace('api=(path)=>{', 'api=(path,options={})=>{').replace(
        'requests.push({path,resolve', 'requests.push({path,options,resolve')
    result = run_javascript(ACTION_DOM + FOCUS_DOM + APP + fixtures + SETUP + '\n(async()=>{\n' + source + r'''
clearTimeout(ui.preflightTimer);
})().then(()=>console.log(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
''')
    assert result == {'ok': True}


def test_reuse_controls_are_non_submit_and_preview_is_keyboard_readable():
    tree = Elements()
    for ident in ('reuseTask', 'keepTaskDraft', 'replaceTaskDraft'):
        assert tree.ids[ident]['attrs']['type'] == 'button'
    assert tree.ids['taskReusePreview']['attrs']['tabindex'] == '0'
    assert tree.ids['taskReuseStatus']['attrs']['role'] == 'status'
    help_text = tree.ids['taskReuseHelp']['text']
    for text in ('開始時の保存済み設定', '会話・成果・設定は引き継ぎません', '伏せ字', 'LF', '空白'):
        assert text in help_text


def test_empty_draft_adopts_only_display_text_and_preserves_current_choices_and_context():
    check(r'''
await setup();const before=structuredClone(ui.state),payload=runPayload(),generation=ui.taskDraftGeneration;
reuse();assert.equal($('taskInput').value,before.runs[0].task);
assert.equal(ui.taskDraftGeneration,generation+1);assert.equal(document.activeElement,$('taskInput'));
assert.deepEqual(runPayload(),{...payload,task:before.runs[0].task});assert.deepEqual(ui.state,before);
assert.equal(ui.selectedRun,'run-a');assert.equal(ui.selectedAgent,'agent-a');
assert.equal($('messageInput').value,'  Separate agent draft  ');assert.equal($('conversationLog').scrollTop,75);
assert.equal($('agentSearch').value,'Current search');assert.equal(ui.needsOnly,true);
assert.equal($('taskDialog').open,true);assert.equal($('taskReuseConfirm').hidden,true);
assert.match($('taskReuseProvenance').textContent,/run-a/);assert.match($('taskReuseStatus').textContent,/まだ開始していません/);
assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('ending', [r'\n', r'\r\n', r'\r'])
def test_only_native_newlines_are_normalized_and_identical_has_no_epoch_churn(ending):
    check(r'''
await setup();getRun().task='  AENDINGB\t ';task('  A\nB\t ');const before=ui.taskDraftGeneration;
reuse();assert.equal(ui.taskDraftGeneration,before);assert.equal(ui.taskReuseCandidate,null);
assert.equal($('taskInput').value,'  A\nB\t ');assert.equal(requests.length,0);
'''.replace('ENDING', ending))


@pytest.mark.parametrize('existing', [r'  Current\n draft  ', ' ', r'\t\n'])
def test_nonempty_current_input_requires_choice_and_keep_is_nondestructive(existing):
    check(r'''
await setup();task('EXISTING');const payload=runPayload(),generation=ui.taskDraftGeneration;
reuse();assert.equal($('taskInput').value,payload.task);assert.equal($('taskReuseConfirm').hidden,false);
assert.equal($('taskReusePreview').textContent,getRun().task);assert.equal(document.activeElement,$('keepTaskDraft'));
assert.equal($('startRun').disabled,true);await submit();assert.equal(requests.length,0);
assert.equal(ui.preflightTimer?true:false,true);assert.equal($('preflightStatus').getAttribute('aria-busy'),'false');
schedulePreflight();assert.equal(requests.length,0);keep();
assert.deepEqual(runPayload(),payload);assert.equal(ui.taskDraftGeneration,generation);
assert.equal(ui.taskReuseCandidate,null);assert.equal($('taskReuseConfirm').hidden,true);
assert.equal(document.activeElement,$('taskInput'));assert.equal($('startRun').disabled,false);
'''.replace('EXISTING', existing))


def test_replace_adopts_once_then_only_reviewed_explicit_start_posts():
    check(r'''
await setup();task('Existing draft');const choices=runPayload();reuse();replace();replace();
assert.deepEqual(runPayload(),{...choices,task:getRun().task});assert.equal(requests.length,0);
const pending=submit();assert.equal(requests.length,1);assert.equal(requests[0].path,'/api/runs');
assert.equal(requests[0].options.method,'POST');assert.deepEqual(requests[0].options.body,runPayload());
reject(0,new Error('Synthetic rejection'));await pending;
assert.equal($('taskInput').value,getRun().task);
''')


@pytest.mark.parametrize('change', [
    "task('New draft');", "task('Intermediate');task('Existing draft');",
    "$('taskInput').value='Unsignaled edit';", "$('pmProfile').value='Unsignaled profile';",
    "selectAgent('agent-b');selectAgent('agent-a');",
    "setBriefOpen(false);setBriefOpen(true);",
    "showView('settings');showView('work');",
    "getRun().task='Changed display';", "getRun().task='[redacted]';",
    "ui.state.runs=[];", "ui.workspaceGeneration++;", "ui.startingRun=true;",
])
def test_stale_choice_and_each_independent_aba_never_overwrite(change):
    check(r'''
await setup();task('Existing draft');reuse();const candidate=ui.taskReuseCandidate;
CHANGE
const before=runPayload();replace();assert.deepEqual(runPayload(),before);assert.equal(ui.taskReuseCandidate,null);
assert.equal($('taskReuseConfirm').hidden,true);assert.notEqual(ui.taskReuseSource?.text,candidate.text);
assert(requests.every(request=>request.path.startsWith('/api/state')));
'''.replace('CHANGE', change))


def test_raw_source_newline_change_invalidates_even_if_editor_candidate_matches():
    check(r'''
await setup();getRun().task='One\r\nTwo';task('Existing draft');reuse();
getRun().task='One\nTwo';renderRun();replace();assert.equal($('taskInput').value,'Existing draft');
assert.equal(ui.taskReuseCandidate,null);assert.match($('taskReuseStatus').textContent,/取り消しました/);
''')


@pytest.mark.parametrize('change', [
    "$('maxWorkers').value='';",
    "$('maxWorkers').value='';$('runForm').listeners.input({type:'input'});$('maxWorkers').value='0';",
    "$('runForm').listeners.input({type:'input'});",
    "$('runForm').listeners.change({type:'change'});",
])
def test_raw_numeric_edit_and_same_value_events_invalidate_replacement(change):
    check(r'''
await setup();task('Existing draft');reuse();CHANGE
replace();assert.equal($('taskInput').value,'Existing draft');assert.equal(ui.taskReuseCandidate,null);
'''.replace('CHANGE', change))


@pytest.mark.parametrize('text', ['undefined', 'null', '17', "''", "'   '", "'a\\0b'", "'x'.repeat(16001)", "'😀'.repeat(8001)"])
def test_unavailable_and_oversize_sources_never_truncate_or_replace(text):
    check(r'''
await setup();task('Existing draft');getRun().task=TEXT;renderRun();reuse();
assert.equal($('reuseTask').disabled,true);assert.equal($('taskReuseAvailability').hidden,false);
assert.equal($('taskInput').value,'Existing draft');assert.equal($('taskDialog').open,false);assert.equal(requests.length,0);
'''.replace('TEXT', text))


def test_normalized_utf16_boundary_is_checked_after_newline_conversion():
    check(r'''
await setup();getRun().task='😀'.repeat(7999)+'\r\nx';reuse();
assert.equal($('taskInput').value.length,16000);assert.equal($('taskInput').value,'😀'.repeat(7999)+'\nx');
assert.equal(requests.length,0);
''')


@pytest.mark.parametrize('status', ['running', 'waiting', 'done', 'stopping', 'stopped', 'error'])
def test_any_retained_display_can_prepare_a_draft_without_resuming(status):
    check(r'''
await setup();getRun().status='STATUS';ui.detailError=true;ui.authenticated=false;const before=structuredClone(ui.state);
reuse();assert.equal($('taskInput').value,getRun().task);assert.deepEqual(ui.state,before);assert.equal(requests.length,0);
'''.replace('STATUS', status))


@pytest.mark.parametrize('pending', ['ui.startingRun=true;', "ui.startOperation={runId:'accepted-run'};"])
def test_pending_start_blocks_entry_and_is_not_modified(pending):
    check(r'''
await setup();task('Existing draft');PENDING
const operation=ui.startOperation;renderRun();reuse();assert.equal($('reuseTask').disabled,true);
assert.equal(ui.startOperation,operation);assert.equal($('taskInput').value,'Existing draft');assert.equal(requests.length,0);
'''.replace('PENDING', pending))


def test_pending_choice_invalidates_previous_preflight_and_adoption_only_preflights():
    check(r'''
await setup();task('Existing draft');setBriefOpen(true);clearTimeout(ui.preflightTimer);
const old=refreshPreflight(ui.preflightRequest);assert.equal(requests[0].path,'/api/run-preflight');
reuse();resolve(0,{can_start:true,blockers:[],warnings:[]});await old;
assert.match($('preflightStatus').textContent,/依頼文を選んだ後/);assert.equal(requests.length,1);
replace();clearTimeout(ui.preflightTimer);const current=refreshPreflight(ui.preflightRequest);
assert.equal(requests[1].path,'/api/run-preflight');assert.deepEqual(requests[1].options.body,runPayload());
resolve(1,{can_start:true,blockers:[],warnings:[]});await current;
assert(requests.every(request=>request.path==='/api/run-preflight'));assert.equal(ui.startOperation,null);
''')


def test_unchanged_poll_keeps_preview_focus_scroll_and_newer_feedback():
    check(r'''
await setup();task('Existing draft');reuse();$('taskReusePreview').focus();$('taskReusePreview').scrollTop=50;
inlineStatus($('runFormStatus'),'Newer feedback');const candidate=ui.taskReuseCandidate;
renderState();assert.equal(ui.taskReuseCandidate,candidate);assert.equal(document.activeElement,$('taskReusePreview'));
assert.equal($('taskReusePreview').scrollTop,50);assert.equal($('runFormStatus').textContent,'Newer feedback');
getRun().task='Remasked';renderRun();assert.equal(document.activeElement,$('taskInput'));
assert.equal($('taskInput').value,'Existing draft');
''')


def test_polled_source_change_resumes_only_current_draft_preflight_after_cancel():
    check(r'''
await setup();task('Existing draft');reuse();getRun().task='Changed source';renderRun();
assert.equal(ui.taskReuseCandidate,null);assert.equal($('taskInput').value,'Existing draft');
assert.equal($('preflightStatus').getAttribute('aria-busy'),'true');clearTimeout(ui.preflightTimer);
const pending=refreshPreflight(ui.preflightRequest);assert.equal(requests[0].path,'/api/run-preflight');
assert.equal(requests[0].options.body.task,'Existing draft');
resolve(0,{can_start:true,blockers:[],warnings:[]});await pending;
assert.match($('preflightStatus').textContent,/開始に必要な設定を確認しました/);assert.equal(requests.length,1);
''')


def test_close_and_settings_cancel_without_scheduling_preview_in_hidden_context():
    check(r'''
await setup();task('Existing draft');reuse();const before=ui.preflightRequest;
showView('settings');assert.equal(ui.taskReuseCandidate,null);assert.equal(ui.preflightRequest,before);
assert.equal(ui.preflightKey,'');assert.equal($('taskReuseStatus').textContent,'');
showView('work');clearTimeout(ui.preflightTimer);reuse();const closing=ui.preflightRequest;
setBriefOpen(false);assert.equal(ui.taskReuseCandidate,null);assert.equal(ui.preflightRequest,closing+1);
assert.equal(ui.preflightKey,'');assert.equal($('taskReuseStatus').textContent,'');assert.equal(requests.length,0);
''')
