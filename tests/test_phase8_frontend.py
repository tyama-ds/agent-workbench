"""Phase 8 UI: the new-task worker cap starts at the saved cap, and a request
that names more people than the cap says so before the run starts."""
from test_frontend import HTML
from test_phase7_frontend import check_settings


def test_the_untouched_default_in_app_js_matches_the_html_default():
    assert 'id="maxWorkers" type="number" min="0" max="16" step="1" value="3"' in HTML


def test_worker_cap_starts_at_the_saved_cap_and_keeps_a_typed_value():
    check_settings(r'''
await setup();$('maxWorkers').value='3';  // the real page's HTML default
ui.config.limits.max_workers=8;renderProfileChoices(false);
assert.equal($('maxWorkers').value,'8','the field follows the saved cap, not the HTML default 3');
assert.equal($('maxWorkers').max,'8');
$('maxWorkers').value='5';renderProfileChoices(false);assert.equal($('maxWorkers').value,'5','a typed value is kept');
ui.config.limits.max_workers=4;renderProfileChoices(false);assert.equal($('maxWorkers').value,'4','but never above the cap');
''')


def test_a_request_for_more_people_than_the_cap_is_pointed_out():
    check_settings(r'''
await setup();
ui.config.limits.max_workers=8;renderProfileChoices(false);$('maxWorkers').value='3';
$('taskInput').value='５人雇って、みんなでしりとりして。';renderTaskOrchestration();
assert.match($('delegationStatus').textContent,/依頼文に「5人」とあります。この作業の作業者の上限は 3 人です。5人で進めるには上限を 5 以上にしてください。/);
assert.equal(taskOrchestrationIssue(),'','the hint does not block the start');
$('maxWorkers').value='5';renderTaskOrchestration();assert.doesNotMatch($('delegationStatus').textContent,/依頼文に/);
$('taskInput').value='三人で議論して';$('maxWorkers').value='2';renderTaskOrchestration();
assert.match($('delegationStatus').textContent,/依頼文に「3人」/);
$('taskInput').value='12人で議論して';$('maxWorkers').value='8';renderTaskOrchestration();
assert.match($('delegationStatus').textContent,/設定の「作業の上限」は 8 人です/);
$('taskInput').value='顧客1人の記録を要約して';renderTaskOrchestration();assert.doesNotMatch($('delegationStatus').textContent,/依頼文に/);
''')
