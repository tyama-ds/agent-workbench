/* Real engine and UI; deterministic in-process provider, no model network. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function contextCompactionAcceptance({context,origin,providerRequests,stateDir,artifacts,report,assertLayout}) {
  const beforeProviders=structuredClone(providerRequests),beforeExternal=[...report.externalRequests];
  const releaseFile=path.join(stateDir,'compaction-release');
  const task='[SYNTHETIC] Compact a long conversation; preserve this exact original task.';
  const finalText='[SYNTHETIC] Compaction continued; exact human and assistant originals verified; missing record reported.';
  const edits={max_model_calls:30,max_tool_calls:40,max_context_chars:50000,context_trigger_percent:75,
    context_recent_groups:2,context_summary_chars:1500,context_reserve_tokens:1024,max_history_chars:400000,
    max_output_tokens:2048,max_run_seconds:120};
  let page,originalConfig,restore=false,runId,agentId,failed=false;
  const api=async(route,method='GET',body)=>{
    const response=await context.request.fetch(origin+route,{method,headers:{Origin:origin},maxRetries:0,timeout:10000,
      ...(body===undefined?{}:{data:body})});
    assert.equal(response.status(),200,method+' '+route);return response.json();
  };
  const configure=async config=>{
    const {config_revision}=await api('/api/config');return api('/api/config','PUT',{config_revision,config});
  };
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const poll=async()=>{
    const response=await page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state'&&response.request().method()==='GET');
    assert.equal(response.status(),200);await response.finished();await paint();
  };
  const save=async()=>{
    const saved=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/config'&&response.request().method()==='PUT');
    await page.locator('#saveSettings').focus();await page.keyboard.press('Enter');
    assert.equal((await saved).status(),200);
    await page.locator('#settingsStatus').filter({hasText:'設定を保存しました'}).waitFor();
  };
  try {
    originalConfig=structuredClone((await api('/api/config')).config);
    const initial=await api('/api/state');
    assert(initial.runs.length<20);assert(initial.runs.every(run=>!['running','waiting','stopping'].includes(run.status)));
    assert(!initial.runs.some(run=>run.task===task),'Compaction fixture must run exactly once');
    const localIndex=originalConfig.providers.findIndex(profile=>profile.id==='local');
    assert(localIndex>=0&&originalConfig.providers[localIndex].enabled);
    const setup=structuredClone(originalConfig);setup.search.enabled=false;
    restore=true;await configure(setup);fs.rmSync(releaseFile,{force:true});
    page=await context.newPage();page.setDefaultTimeout(10000);await page.setViewportSize({width:1366,height:768});
    page.on('pageerror',error=>report.pageErrors.push(error.message));
    page.on('console',message=>{if(/Content Security Policy|violates.*directive/i.test(message.text()))report.cspErrors.push(message.text());});
    page.on('request',request=>{
      const url=new URL(request.url());if(url.protocol.startsWith('http')&&url.origin!==origin)report.externalRequests.push(url.origin+url.pathname);
    });
    await page.goto(origin+'/');await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    await page.locator('#navSettings').click();
    const keyPosts=[];
    const watchKeys=request=>{if(new URL(request.url()).pathname==='/api/secrets')keyPosts.push(request.postDataJSON());};
    page.on('request',watchKeys);
    // These are synthetic browser event flags, not native OS IME validation.
    for(const selector of [`#profile-${localIndex}-secret`,'#searchSecret']){
      const input=page.locator(selector);await input.fill('[SYNTHETIC] unfinished composition');
      for(const flags of [{isComposing:true,keyCode:13},{isComposing:true,keyCode:229},{isComposing:false,keyCode:229}]){
        assert.equal(await input.evaluate((node,flags)=>node.dispatchEvent(new KeyboardEvent('keydown',
          {key:'Enter',bubbles:true,cancelable:true,...flags})),flags),true,'Composition shortcut must not cancel Enter');
        await paint();assert.equal(await input.inputValue(),'[SYNTHETIC] unfinished composition');
      }
      await input.clear();
    }
    await poll();assert.deepEqual(keyPosts,[]);page.off('request',watchKeys);
    report.checks.push('credential-composition: real Edge inputs ignore six synthetic isComposing/keyCode-229 Enter cases without canceling events, clearing values or sending key requests; native OS IME remains untested');
    await page.locator('#limits-auto_compact').uncheck();await save();
    assert.equal((await api('/api/config')).config.limits.auto_compact,false);
    await page.reload();await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    await page.locator('#navSettings').click();assert.equal(await page.locator('#limits-auto_compact').isChecked(),false);
    await page.locator('#limits-auto_compact').check();
    for(const [key,value] of Object.entries(edits))await page.locator('#limits-'+key).fill(String(value));
    await page.locator(`#profile-${localIndex}-context_window_tokens`).fill('200000');
    await save();
    const persisted=JSON.parse(fs.readFileSync(path.join(stateDir,'settings.json'),'utf8'));
    assert.equal(persisted.limits.auto_compact,true);
    for(const [key,value] of Object.entries(edits))assert.equal(persisted.limits[key],value);
    assert.equal(persisted.providers[localIndex].context_window_tokens,200000);
    await page.reload();await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    await page.locator('#navSettings').click();
    assert.equal(await page.locator('#limits-auto_compact').isChecked(),true);
    for(const [key,value] of Object.entries(edits))assert.equal(await page.locator('#limits-'+key).inputValue(),String(value));
    assert.equal(await page.locator(`#profile-${localIndex}-context_window_tokens`).inputValue(),'200000');
    await page.locator('#limits-auto_compact').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(artifacts,'workbench-compaction-settings.png'),fullPage:false,animations:'disabled'});
    await page.keyboard.press('Escape');
    report.checks.push('context-compaction: native settings Save persists opt-out and re-enable, threshold/recent groups/summary/archive/character/output/reserve budgets and per-profile estimated-token budget across reload; no provider probe');
    await page.locator('#newRun').click();await page.locator('#taskInput').fill(task);
    await page.locator('#pmProfile').selectOption('local');await page.locator('#maxWorkers').fill('0');
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.uncheck();
    const started=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
    await page.locator('#startRun').focus();await page.keyboard.press('Enter');
    const response=await started;assert.equal(response.status(),200);runId=(await response.json()).run.id;
    await page.locator('#taskDialog').waitFor({state:'hidden'});
    await page.locator('#contextMemoryStatus').filter({hasText:'会話を要約中'}).waitFor();
    const compacting=await api('/api/state'),run=compacting.runs.find(item=>item.id===runId);
    const agents=compacting.agents.filter(item=>item.run_id===runId);assert.equal(agents.length,1);
    const agent=agents[0];agentId=agent.id;
    assert.equal(agent.context_memory.compacting,true);assert.equal(agent.context_memory.compactions,0);
    assert(run.model_calls>1&&run.model_calls<30);
    assert(!Object.hasOwn(agent,'conversation')&&!Object.hasOwn(agent,'original_history'),'State exposes metadata, never raw context archives');
    await page.locator('#conversationHeading').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(artifacts,'workbench-compaction-active.png'),fullPage:false,animations:'disabled'});
    // Only the test provider gate is released. Production context/state is never patched.
    fs.writeFileSync(releaseFile,'synthetic browser observed real summary state\n');
    await page.locator('#activeRunStatus').filter({hasText:'完了'}).waitFor();
    await page.locator('#contextMemoryStatus').filter({hasText:'文脈圧縮 1 回'}).waitFor();
    assert.doesNotMatch(await page.locator('#contextMemoryStatus').textContent(),/会話を要約中/);
    assert.match(await page.locator('#contextMemoryStatus').textContent(),/今回の起動中のみ。要約には情報が抜けることがあります/);
    const completed=await api('/api/state'),done=completed.agents.find(item=>item.id===agentId),doneRun=completed.runs.find(item=>item.id===runId);
    assert.equal(done.status,'done');assert.equal(doneRun.status,'done');assert.equal(done.context_memory.compactions,1);
    assert.equal(done.context_memory.compacting,false);assert.equal(done.context_memory.history_omitted,0);
    assert(done.context_memory.history_records>10);assert(done.context_memory.request_chars<50000);
    assert(done.logs.some(log=>log.text===finalText),'The fake provider verifies exact retained human and assistant originals before its terminal reply');
    const lookup=JSON.parse(done.logs.find(log=>log.kind==='tool'&&log.text.startsWith('read_context_history\n')).text.split('\n').slice(1).join('\n'));
    assert.deepEqual(lookup.unavailable_ids,[999999]);assert.deepEqual(lookup.records.map(record=>record._record_id),[1,2]);
    assert.equal(lookup.records[0]._human,true);assert.equal(lookup.records[0].content,task);
    assert.equal(lookup.records[1]._human,false);assert.equal(lookup.records[1].content,'[SYNTHETIC] Original observation 0: '+'a'.repeat(4000));
    assert.deepEqual(lookup.over_response_limit_ids,[]);
    const snapshots=[];
    for(const [label,size] of [['desktop',{width:1366,height:768}],['narrow',{width:390,height:844}]]){
      await page.setViewportSize(size);await paint();await assertLayout(page,'compaction '+label);
      await page.locator('#conversationHeading').scrollIntoViewIfNeeded();
      const text=await page.locator('#contextMemoryStatus').textContent();await poll();
      assert.equal(await page.locator('#contextMemoryStatus').textContent(),text,'Unchanged polling preserves truthful metadata');
      await page.screenshot({path:path.join(artifacts,`workbench-compaction-${label}.png`),fullPage:false,animations:'disabled'});
      snapshots.push({viewport:size,status:text});
    }
    report.contextCompaction={runId,agentId,modelCalls:doneRun.model_calls,toolCalls:doneRun.tool_calls,
      memory:done.context_memory,lookupRecordIds:lookup.records.map(record=>record._record_id),
      unavailableIds:lookup.unavailable_ids,summaryCalls:1,settings:edits,profileTokenEstimateBudget:200000,snapshots};
    report.checks.push('context-compaction: real engine crosses threshold, exposes held summary state, charges the no-tool synthetic summary, continues using exact retained human/assistant records via read_context_history, reports missing IDs and completes; real unchanged polls and desktop/narrow status screenshots; no raw archive in API state');
    assert.deepEqual(providerRequests,beforeProviders);assert.deepEqual(report.externalRequests,beforeExternal);
    assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
  }catch(error){
    failed=true;if(page)await page.screenshot({path:path.join(artifacts,'workbench-compaction-failure.png'),fullPage:false,animations:'disabled'}).catch(()=>{});
    throw error;
  }finally{
    const errors=[];
    fs.writeFileSync(releaseFile,'release synthetic provider during cleanup\n');
    if(page)await page.close().catch(error=>errors.push(error));
    if(restore){
      try{
        const state=await api('/api/state');
        for(const run of state.runs.filter(item=>item.task===task)){
          assert(!runId||run.id===runId);await api('/api/runs/'+run.id+'/stop','POST',{});
        }
        await configure(originalConfig);assert.deepEqual((await api('/api/config')).config,originalConfig);
      }catch(error){errors.push(error);}
    }
    fs.rmSync(releaseFile,{force:true});
    if(errors.length){report.checks.push('context-compaction cleanup failed: '+errors.map(error=>error.message).join('; '));
      if(!failed)throw new AggregateError(errors,'Context compaction cleanup failed');}
  }
}

module.exports={contextCompactionAcceptance};
