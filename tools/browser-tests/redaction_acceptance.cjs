/* Real local API + Edge UI acceptance. Every credential below is synthetic. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function assertMasked(value,keys,label) {
  const serialized=typeof value==='string'?value:JSON.stringify(value);
  for(const key of keys)assert(!serialized.includes(key),label+': synthetic exact value leaked');
}

// Playwright 1.62.1 tests an async waitForFunction predicate's Promise for
// truthiness before it resolves. Poll completed HTTP reads here instead, and
// return the exact snapshot whose status/readiness was checked.
async function waitForRunState(readState,runId,status,{timeoutMs=10000,pollMs=25}={}) {
  const deadline=Date.now()+timeoutMs;let state;
  const timeout=()=>new Error('Timed out waiting for synthetic run '+JSON.stringify({runId,status,
    run:state?.runs.find(item=>item.id===runId),
    agents:state?.agents.filter(item=>item.run_id===runId).map(item=>({id:item.id,status:item.status,
      turns:item.turns,results:item.results?.slice(-2),output_receipts:item.output_receipts?.slice(-2),last_error:item.last_error}))}));
  for(;;){
    const remaining=deadline-Date.now();if(remaining<=0)throw timeout();
    let timer;
    try {
      state=await Promise.race([Promise.resolve().then(readState),new Promise((resolve,reject)=>{
        timer=setTimeout(()=>reject(timeout()),remaining);
      })]);
    } finally {clearTimeout(timer);}
    const run=state.runs.find(item=>item.id===runId),agents=state.agents.filter(item=>item.run_id===runId);
    if(run?.status===status&&(status!=='waiting'||agents.some(item=>item.parent_id&&item.results?.length&&item.output_receipts?.length)))return state;
    const delay=Math.min(pollMs,deadline-Date.now());if(delay<=0)throw timeout();
    await new Promise(resolve=>setTimeout(resolve,delay));
  }
}

async function retainedRedactionAcceptance({page,context,origin,workspace,stateDir,artifacts,cases,report}) {
  const keys=Object.values(cases).flatMap(item=>[item.old,item.new]);
  const api=async(url,method='GET',body)=>{
    const response=await page.evaluate(async({url,method,body})=>{
      const response=await fetch(url,{method,credentials:'same-origin',cache:'no-store',
        ...(body===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
      return {status:response.status,text:await response.text()};
    },{url,method,body});
    assert.equal(response.status,200,method+' '+url+' must succeed');
    assertMasked(response.text,keys,method+' '+url);
    return JSON.parse(response.text);
  };
  const waitForRun=(runId,status)=>waitForRunState(()=>api('/api/state'),runId,status);
  const select=async(runId,agentId,requireOutput=true)=>{
    await page.locator(`#runList .run-link[data-focus-key="run:${runId}"]`).click();
    await page.locator(`#agentCards [data-agent-id="${agentId}"]`).click();
    await page.waitForFunction(({id,requireOutput})=>document.querySelector(`#agentCards [data-agent-id="${id}"]`)?.getAttribute('aria-pressed')==='true'&&
      (!requireOutput||!document.querySelector('#resultSelection').disabled),{id:agentId,requireOutput});
    if(requireOutput&&!await page.locator('#resultsPanel').evaluate(element=>element.open))await page.locator('#resultsPanel > summary').click();
  };
  const assertHistory=async(runId,state)=>{
    state=state||await api('/api/state');const run=state.runs.find(item=>item.id===runId);
    const agents=state.agents.filter(item=>item.run_id===runId),lead=agents.find(item=>!item.parent_id),worker=agents.find(item=>item.parent_id);
    assert(run.task.includes('[redacted]'));
    assert(lead.assignment.includes('[redacted]'));assert(lead.question.includes('[redacted]'));
    assert(worker.name.includes('[redacted]'));assert(worker.assignment.includes('[redacted]'));
    assert(worker.results.some(item=>item.text.includes('[redacted]')));
    assert(worker.output_receipts.some(item=>item.path.includes('[redacted]')));
    assert(worker.logs.some(item=>item.text.includes('[redacted]')));
    assert(state.events.filter(item=>item.run_id===runId).some(item=>item.text.includes('[redacted]')));
    for(const agent of agents){
      const selected=await api(`/api/state?view=selected&run_id=${runId}&agent_id=${agent.id}`);
      assert.equal(selected.selection.detail_loaded,true);
      assert.deepEqual(selected.agents.find(item=>item.id===agent.id),agent);
    }
    return {lead,worker};
  };
  const outputs=async(runId,agentId,kinds=['result','receipt'])=>{
    await select(runId,agentId);
    const state=await api(`/api/state?view=selected&run_id=${runId}&agent_id=${agentId}`);
    const agent=state.agents.find(item=>item.id===agentId);
    assertMasked(await page.locator('body').innerText(),keys,'Visible historical UI');
    const exported={};
    for(const kind of kinds){
      const option=page.locator(`#resultSelection option[value^="${kind}:"]`).first();
      const selected=await option.getAttribute('value');
      await page.locator('#resultSelection').selectOption(selected);
      assert((await page.locator('#resultText').textContent()).includes('[redacted]'));
      await page.locator('#copyResult').click();
      await page.locator('#resultActionStatus').filter({hasText:kind==='result'?'本文をコピーしました。':'パスをコピーしました。'}).waitFor();
      const copied=await page.evaluate(()=>navigator.clipboard.readText());
      const record=agent[kind==='result'?'results':'output_receipts'].find(item=>String(item.id)===selected.split(':')[1]);
      assert(record);assert.equal(copied,record[kind==='result'?'text':'path']);
      assert(copied.includes('[redacted]'));assertMasked(copied,keys,'Actual clipboard '+kind);
      const downloaded=page.waitForEvent('download');await page.locator('#exportResult').click();
      const download=await downloaded;
      assert.equal(download.suggestedFilename(),kind==='result'?'workbench-result.txt':'workbench-save-receipt.txt');
      exported[kind]=fs.readFileSync(await download.path(),'utf8');
      assert(exported[kind].includes('[redacted]'));assertMasked(exported[kind],keys,'Actual UTF-8 download '+kind);
      assert(!exported[kind].includes('Private historical reasoning'));
    }
    return exported;
  };
  await page.setViewportSize({width:1366,height:768});
  await context.grantPermissions(['clipboard-read','clipboard-write'],{origin});
  const config=(await api('/api/config')).config;
  config.providers=[{id:'local',label:'Synthetic retained-key provider',kind:'local',enabled:true,
    model:'synthetic-retained-no-network',base_url:'http://127.0.0.1:1/v1',api_key_env:'',proxy_url:'',request_timeout_seconds:30}];
  config.search.enabled=false;config.search.api_key_env='';
  config.paths.read_roots=[workspace];config.paths.write_roots=[workspace];
  Object.assign(config.limits,{max_workers:1,max_turns_per_agent:10,max_model_calls:50,max_tool_calls:50,
    max_auto_collaborations:24,max_run_seconds:300,max_context_chars:200000});
  await api('/api/config','PUT',config);
  for(const scenario of ['memory','environment']){
    const item=cases[scenario];
    if(scenario==='memory')await api('/api/secrets','POST',{id:'local',key:item.old});
    else {
      await api('/api/secrets','POST',{id:'local',key:''});
      config.providers[0].api_key_env=item.old_env;
      await api('/api/config','PUT',config);
    }
    const started=await api('/api/runs','POST',{task:`[SYNTHETIC] Retained credential ${scenario} ${item.old}`,
      pm_profile:'local',worker_profiles:['local'],max_workers:1});
    const runId=started.run.id;
    const ready=await waitForRun(runId,'waiting');
    const before=await assertHistory(runId,ready);
    await page.reload();await select(runId,before.lead.id,false);
    await page.locator('#humanQuestion').filter({hasText:'Historical question [redacted]'}).waitFor();
    assertMasked(await page.locator('body').innerText(),keys,'Before credential transition');
    if(scenario==='environment')await api(`/api/runs/${runId}/stop`,'POST',{});
    await waitForRun(runId,scenario==='memory'?'waiting':'stopped');
    const beforeExports=await outputs(runId,before.worker.id);
    if(scenario==='memory')await api('/api/secrets','POST',{id:'local',key:item.new});
    else {
      config.providers[0].api_key_env=item.new_env;
      await api('/api/config','PUT',config);
    }
    await assertHistory(runId);
    await page.reload();
    assert.deepEqual(await outputs(runId,before.worker.id),beforeExports,'Historical copies/exports survive key retirement');
    if(scenario==='memory'){
      await page.locator(`#agentCards [data-agent-id="${before.lead.id}"]`).click();
      await page.locator('#humanQuestion').filter({hasText:'Historical question [redacted]'}).waitFor();
      await api(`/api/agents/${before.lead.id}/message`,'POST',{text:'[SYNTHETIC] Continue after replacement.'});
      const completed=await waitForRun(runId,'done');
      const lead=completed.agents.find(agent=>agent.id===before.lead.id);
      assert(lead.results.some(result=>result.text.includes('current authentication verified.')),
        JSON.stringify({scenario,run:completed.runs.find(run=>run.id===runId),status:lead.status,turns:lead.turns,results:lead.results,logs:lead.logs.slice(-3)}));
      assert(lead.results.every(result=>result.text.includes('[redacted]')));
      await page.reload();await outputs(runId,lead.id,['result']);
    } else {
      const replay=await api('/api/runs','POST',{task:`[SYNTHETIC] Retained replay ${scenario} ${item.old}`,
        pm_profile:'local',worker_profiles:[],max_workers:0});
      const state=await waitForRun(replay.run.id,'done'),lead=state.agents.find(agent=>agent.run_id===replay.run.id);
      assert(lead.results.some(result=>result.text.includes('current authentication verified.')),
        JSON.stringify({scenario,run:state.runs.find(run=>run.id===replay.run.id),status:lead.status,turns:lead.turns,results:lead.results,logs:lead.logs.slice(-3)}));
      await page.reload();await outputs(replay.run.id,lead.id);
    }
    assertMasked(fs.readFileSync(path.join(stateDir,'settings.json'),'utf8'),keys,'Persisted settings');
    assert.equal(fs.readFileSync(path.join(workspace,`browser-retained-${scenario}-${item.old}.txt`),'utf8'),'[SYNTHETIC] Safe saved bytes.');
    report.checks.push(`real ${scenario==='memory'?'memory-key replacement':'environment-key reference change'}: current authentication verified by synthetic provider; retired values masked in full/selected API task, assignment, worker name, question, logs, events, reports and file receipts; actual Edge clipboard/download before and after mutation; new replies replay retired values safely; no live provider calls`);
  }
  await page.locator('#navSettings').click();
  const profile=page.locator('.profile-editor').first();
  if(await profile.locator('.profile-content').isHidden())await profile.getByRole('button',{name:'編集',exact:true}).click();
  await profile.locator('input[type="password"]').fill(cases.memory.new);
  await profile.getByRole('button',{name:'キーをセット',exact:true}).click();
  await profile.locator('.inline-status').filter({hasText:'キーをセットしました'}).waitFor();
  await profile.locator('[data-key="api_key_env"]').fill('');
  await profile.locator('[data-key="base_url"]').fill('http://127.0.0.1:2/v1');
  await page.locator('#saveSettings').click();
  await page.locator('#settingsStatus').filter({hasText:'設定を保存しました。'}).waitFor();
  await profile.locator('.secret-status').filter({hasText:'キー未設定'}).waitFor();
  assert.equal((await api('/api/config')).secret_status.local,false);
  assert(!await profile.locator('.secret-status').textContent().then(text=>text.includes('キー設定あり')));
  await page.locator('#closeSettings').click();
  report.checks.push('real settings identity edit retires memory authentication and immediately refreshes key status without a reload');
  await page.screenshot({path:path.join(artifacts,'workbench-retained-redaction-desktop.png'),fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  assertMasked(await page.locator('body').innerText(),keys,'Narrow retained-key UI');
  await page.screenshot({path:path.join(artifacts,'workbench-retained-redaction-narrow.png'),fullPage:true,animations:'disabled'});
}

module.exports={retainedRedactionAcceptance,waitForRunState};
