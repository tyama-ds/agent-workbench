"""Recovery counters and handoff evidence in a synthetic DOM; no browser/model."""
from test_frontend import APP, run_javascript


SOURCE = APP[APP.index('function setVisibleText('):APP.index('function renderInspector(')]
DOM = r'''
const assert=require('node:assert/strict');
const nodes=new Map();
class Node {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.hidden=false;this.open=false;this.textContent='';}
  set id(value){this._id=value;nodes.set(value,this);}
  get id(){return this._id;}
  append(...children){this.children.push(...children);}
}
function element(tag,classes,text){const node=new Node(tag);node.className=classes||'';node.textContent=text||'';return node;}
const $=id=>nodes.get(id)||null;
const brief=element('details');brief.id='inspectorBrief';
function archivedAgent(agent){return agent?.archived===true;}
function localTime(){return '12:30';}
const ui={selectedRun:'other-run',state:{runs:[{id:'other-run',worker_recoveries:0},{id:'run',worker_recoveries:3}]}};
const worker={id:'worker',run_id:'run',stop_reason:'provider_output_limit',recovery:{
  failure_id:2,attempts:1,max_attempts:2,remaining:1,history:[{
    attempt:1,failure_id:1,action:'handoff',from_profile_id:'local',to_profile_id:'allowed-cloud',at:1,
    task:'<img src=x onerror=alert(1)> Save and read the approved weather table.'}]}};
'''


def test_recovery_details_show_associated_run_budget_and_safe_handoff_history():
    result = run_javascript(DOM + SOURCE + r'''
renderWorkerRecovery(worker);
const panel=$('inspectorRecovery');panel.open=true;
assert.equal(brief.children.length,1);
assert.match(panel.children[0].textContent,/1 \/ 2 回 · 仕事全体 3 \/ 4 回（残り 1 回）/);
assert.match(panel.children[1].textContent,/担当モデルを交代 · local → allowed-cloud/);
assert.ok(panel.children[1].textContent.includes(worker.recovery.history[0].task));
assert.equal(panel.children[1].children.length,0);
renderWorkerRecovery(worker);
assert.equal($('inspectorRecovery'),panel);assert.equal(panel.open,true);assert.equal(brief.children.length,1);
ui.state.runs[1].worker_recoveries=4;
renderWorkerRecovery(worker);
assert.match(panel.children[0].textContent,/仕事全体 4 \/ 4 回（残り 0 回）/);
assert.match(panel.children[1].textContent,/仕事全体の自動復旧回数を使い切りました/);
assert.ok(!panel.children[1].textContent.includes('再開には直属親の復旧判断が必要'));
console.log(JSON.stringify({ok:true}));
''')
    assert result == {'ok': True}


def test_recovery_details_do_not_carry_counts_into_other_or_old_agents():
    result = run_javascript(DOM + SOURCE + r'''
renderWorkerRecovery(worker);
const panel=$('inspectorRecovery');
renderWorkerRecovery({id:'old',run_id:'run'});assert.equal(panel.hidden,true);
renderWorkerRecovery(null);assert.equal(panel.hidden,true);
delete ui.state.runs[1].worker_recoveries;
worker.archived=true;worker.recovery.attempts=2;worker.recovery.remaining=0;
renderWorkerRecovery(worker);
assert.equal(panel.hidden,false);
assert.match(panel.children[0].textContent,/2 \/ 2 回（保存時点）/);
assert.ok(!panel.children[0].textContent.includes('仕事全体'));
assert.match(panel.children[1].textContent,/この担当の自動復旧回数を使い切りました/);
worker.stop_reason='';worker.recovery.attempts=0;
renderWorkerRecovery(worker);assert.equal(panel.hidden,true);
console.log(JSON.stringify({ok:true}));
''')
    assert result == {'ok': True}
