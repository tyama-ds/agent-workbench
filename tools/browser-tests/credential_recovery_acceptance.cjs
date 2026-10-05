/* Real local HTTP + native Edge controls; every credential is synthetic. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function closeSettingsDialog(page) {
  // Removing the native dialog's open flag is synchronous; its close event is
  // queued. Wait for the existing application close handler before reopening
  // and capturing a baseline for a separately delayed network response.
  await page.locator('#settingsDialog').evaluate(dialog=>{
    if(!dialog.open)throw new Error('Settings must be open before testing native close');
    dialog.dataset.acceptanceCloseObserved='false';
    dialog.addEventListener('close',()=>{dialog.dataset.acceptanceCloseObserved='true';},{once:true});
  });
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>document.querySelector('#settingsDialog').dataset.acceptanceCloseObserved==='true');
  await page.locator('#settingsDialog').evaluate(dialog=>{delete dialog.dataset.acceptanceCloseObserved;});
}

async function credentialRecoveryAcceptance({page,origin,providerUrl,providerRequests,stateDir,artifacts,
  scenario,report,assertLayout,assertDialogLayout}) {
  const keys=['old','new','search_old','search_new','other'].map(name=>scenario[name]);
  const secretPosts=[],configPuts=[],pending=new Set(),externalBefore=[...report.externalRequests];
  const providerBefore=structuredClone(providerRequests);
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const masked=(value,label)=>{
    const serialized=typeof value==='string'?value:JSON.stringify(value);
    for(const key of keys)assert(!serialized.includes(key),label+': synthetic exact credential leaked');
  };
  const onRequest=request=>{
    const pathname=new URL(request.url()).pathname;
    if(pathname==='/api/secrets'&&request.method()==='POST'){
      const payload=request.postDataJSON();
      secretPosts.push({id:payload.id,config_revision:payload.config_revision});
    }
    if(pathname==='/api/config'&&request.method()==='PUT')configPuts.push(request);
  };
  const api=async(url,method='GET',body,expected=200)=>{
    // Fixture-only writes read their revision immediately before writing. UI
    // acceptance always submits the revision captured by the real form instead.
    if(url==='/api/config'&&method==='PUT')body={config_revision:(await api('/api/config')).config_revision,config:body};
    const response=await page.evaluate(async({url,method,body})=>{
      const response=await fetch(url,{method,credentials:'same-origin',cache:'no-store',
        ...(body===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
      return {status:response.status,text:await response.text()};
    },{url,method,body});
    masked(response.text,method+' '+url);assert.equal(response.status,expected,method+' '+url+' status');
    return JSON.parse(response.text);
  };
  const waitForState=async(runId,status,agentStatus)=>{
    const deadline=Date.now()+10000;
    for(;;){
      const state=await api('/api/state'),run=state.runs.find(item=>item.id===runId);
      const lead=state.agents.find(item=>item.run_id===runId&&!item.parent_id);
      if(run?.status===status&&(!agentStatus||lead?.status===agentStatus))return {state,run,lead};
      assert(Date.now()<deadline,'Synthetic credential run did not reach '+status+'/'+agentStatus);
      await new Promise(resolve=>setTimeout(resolve,25));
    }
  };
  const budget=({run,lead})=>({runId:run.id,agentId:lead.id,status:run.status,agentStatus:lead.status,
    created_at:run.created_at,model_calls:run.model_calls,tool_calls:run.tool_calls,
    auto_collaborations:run.auto_collaborations,max_auto_collaborations:run.max_auto_collaborations,
    max_workers:run.max_workers,turns:lead.turns,results:lead.results,output_receipts:lead.output_receipts});
  const poll=async(count=1)=>{
    for(let i=0;i<count;i++){
      const response=await page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state');
      await response.finished();await paint();
    }
  };
  const card=index=>page.locator('.profile-editor').nth(index);
  const keyButton=index=>card(index).getByRole('button',{name:'キーをセット',exact:true});
  const openSettings=async()=>{
    await page.locator('#navSettings').focus();await page.keyboard.press('Enter');
    await page.locator('#settingsDialog').waitFor({state:'visible'});
  };
  const expand=async index=>{
    if(await card(index).locator('.profile-content').isHidden())await card(index).getByRole('button',{name:'編集',exact:true}).click();
  };
  const fillKey=async(input,button,key)=>{
    await input.focus();await page.keyboard.insertText(key);await page.keyboard.press('Tab');
    assert.equal(await button.evaluate(node=>node===document.activeElement),true,'Tab reaches the native credential submit button');
    await page.keyboard.press('Space');
  };
  const submitKey=async(id,key,index=0)=>{
    const input=id==='search'?page.locator('#searchSecret'):card(index).locator('input[type="password"]');
    const button=id==='search'?page.locator('#setSearchSecret'):keyButton(index);
    const response=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/secrets'&&
      response.request().postDataJSON().id===id);
    await fillKey(input,button,key);const received=await response;
    const payload=received.request().postDataJSON();assert.equal(typeof payload.config_revision,'number');
    assert(Number.isInteger(payload.config_revision));assert.equal(payload.id,id);assert.equal(payload.key,key);
    const body=await received.json();masked(body,'Credential response');
    assert.equal(received.status(),200);assert.deepEqual(body,{ok:true,id,config_revision:payload.config_revision,configured:true});
    await (id==='search'?page.locator('#searchSecretStatus'):card(index).locator('.credential-result'))
      .filter({hasText:'キーをセットしました'}).waitFor();
    assert.equal(await input.inputValue(),'','Submitted passwords clear without being echoed');return body;
  };
  const holdKey=async(id,key,index=0)=>{
    let capture;const captured=new Promise(resolve=>{capture=resolve;});
    await page.route('**/api/secrets',route=>{pending.add(route);capture(route);},{times:1});
    const requested=page.waitForRequest(request=>new URL(request.url()).pathname==='/api/secrets');
    await fillKey(id==='search'?page.locator('#searchSecret'):card(index).locator('input[type="password"]'),
      id==='search'?page.locator('#setSearchSecret'):keyButton(index),key);
    await requested;return captured;
  };
  const releaseReal=async(route,status=200)=>{
    // The credential write still reaches the actual server. Only delivery of
    // its response is deferred, so race coverage cannot fabricate success.
    const received=page.waitForResponse(response=>response.request()===route.request());
    const upstream=await route.fetch();assert.equal(upstream.status(),status);masked(await upstream.text(),'Deferred credential response');
    await route.fulfill({response:upstream});pending.delete(route);
    await (await received).finished();await paint();
  };
  const pointerAttempt=async button=>{
    await button.scrollIntoViewIfNeeded();const box=await button.boundingBox();assert(box);
    await page.mouse.click(box.x+box.width/2,box.y+box.height/2,{clickCount:2});await paint();
  };
  const taskDraftSnapshot=()=>page.evaluate(()=>({task:document.querySelector('#taskInput').value,
    pm_profile:document.querySelector('#pmProfile').value,max_workers:document.querySelector('#maxWorkers').value,
    worker_profiles:[...document.querySelectorAll('#workerProfiles input:checked')].map(input=>input.value)}));
  const discard=async()=>{
    const task=await taskDraftSnapshot(),message=await page.locator('#messageInput').inputValue();
    const response=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/config'&&response.request().method()==='GET');
    await page.locator('#discardSettings').focus();await page.keyboard.press('Enter');
    assert.equal((await response).status(),200);await paint();
    await page.waitForFunction(()=>!document.querySelector('#discardSettings').disabled);
    assert.deepEqual(await taskDraftSnapshot(),task,'Discard preserves task text, PM, exact worker count and checked worker IDs');
    assert.equal(await page.locator('#messageInput').inputValue(),message,'Discard preserves the separate conversation draft');
  };
  const saveSettings=async()=>{
    const response=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/config'&&response.request().method()==='PUT');
    await page.locator('#saveSettings').click();assert.equal((await response).status(),200);
    await page.locator('#settingsStatus').filter({hasText:'設定を保存しました'}).waitFor();
  };
  const screenshot=async(name,dialog=true)=>{
    if(dialog){
      await assertDialogLayout(page,'#settingsDialog',name);masked(await page.locator('#settingsDialog').innerText(),'Credential dialog');
      const layout=await page.locator('#settingsDialog').evaluate(dialog=>({dialog:dialog.getBoundingClientRect().toJSON(),
        targets:[...dialog.querySelectorAll('.credential-target,#credentialNotice')].filter(node=>node.getClientRects().length)
          .map(node=>({id:node.id||node.className,box:node.getBoundingClientRect().toJSON(),
            scrollWidth:node.scrollWidth,clientWidth:node.clientWidth}))}));
      assert(layout.targets.length>0,name+': saved credential destination text is rendered');
      for(const target of layout.targets){
        assert(target.box.width>0&&target.box.height>0,name+': '+target.id+' has readable area');
        assert(target.scrollWidth<=target.clientWidth+1,name+': '+target.id+' text overflows horizontally');
        assert(target.box.left>=layout.dialog.left&&target.box.right<=layout.dialog.right+1,
          name+': '+target.id+' is clipped by the settings dialog');
      }
    }
    else await assertLayout(page,name);
    await page.screenshot({path:path.join(artifacts,'workbench-credential-'+name+'.png'),fullPage:true,animations:'disabled'});
  };
  page.on('request',onRequest);
  try {
    await page.setViewportSize({width:1366,height:768});
    const config=(await api('/api/config')).config;
    const providerId='credential-recovery',otherId='credential-other',proxy='http://127.0.0.1:9';
    config.providers=[
      {id:providerId,label:'Synthetic credential recovery',kind:'openai',enabled:true,model:'synthetic-recovery-no-network',
        base_url:providerUrl,api_key_env:'',proxy_url:proxy,request_timeout_seconds:30},
      {id:otherId,label:'Synthetic independent provider',kind:'local',enabled:true,model:'synthetic-other-no-network',
        base_url:providerUrl+'/other',api_key_env:'',proxy_url:'',request_timeout_seconds:30},
    ];
    Object.assign(config.search,{enabled:false,provider:'brave',endpoint:providerUrl+'/search',api_key_env:'',proxy_url:proxy});
    Object.assign(config.limits,{max_workers:3,max_turns_per_agent:8,max_model_calls:20,max_tool_calls:30,
      max_auto_collaborations:7,max_run_seconds:600,max_context_chars:200000});
    const saved=await api('/api/config','PUT',config);assert(Number.isInteger(saved.config_revision));
    const savedBytes=fs.readFileSync(path.join(stateDir,'settings.json'),'utf8'),putBaseline=configPuts.length;
    await page.reload();await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});await openSettings();
    const target=await card(0).locator('.credential-target').textContent();
    for(const part of [providerId,'OpenAI',providerUrl,proxy])assert(target.includes(part),'Provider target names saved '+part);
    const searchTarget=await page.locator('#searchCredentialTarget').textContent();
    for(const part of ['Brave',providerUrl+'/search',proxy])assert(searchTarget.includes(part),'Search target names saved '+part);
    assert.match(await page.locator('#credentialNotice').textContent(),/起動中/);
    assert.match(await page.locator('#credentialNotice').textContent(),/すべてのチーム|全.*チーム/);
    assert.match(await page.locator('#credentialNotice').textContent(),/以降|次|後/);
    assert.match(await page.locator('#credentialNotice').textContent(),/自動.*再|再.*自動/);
    await submitKey(providerId,scenario.old);
    assert.equal((await api('/api/config')).secret_status.search,false,'Provider key does not configure search');
    await submitKey('search',scenario.search_old);
    await expand(1);await submitKey(otherId,scenario.other,1);
    assert.equal((await api('/api/config')).config_revision,saved.config_revision,'Credential writes do not revise configuration');

    // A new unsaved card is not a destination. Discard cannot accidentally
    // persist it or send its password to an existing provider with the same ID.
    const postsBeforeDraft=secretPosts.length;
    await page.locator('#addProfile').click();
    assert.equal(await card(2).locator('input[type="password"]').isDisabled(),true);
    assert.equal(await keyButton(2).isDisabled(),true);assert.equal(await keyButton(0).isDisabled(),true);
    assert.equal(await page.locator('#setSearchSecret').isDisabled(),true);
    await pointerAttempt(keyButton(2));await discard();
    assert.equal(await page.locator('.profile-editor').count(),2);assert.equal(secretPosts.length,postsBeforeDraft);
    assert.equal(configPuts.length,putBaseline,'Discard is read-only, including unsaved profile removal');

    // Deliberately leave dirty destination/configuration drafts before starting
    // the real run. Admission must continue to use the saved destination.
    await page.locator('#profile-0-id').fill('unsaved-wrong-provider');
    await page.locator('#profile-0-base_url').fill(providerUrl+'/unsaved');
    await page.locator('#profile-0-proxy_url').fill('http://127.0.0.1:10');
    await page.locator('#search-endpoint').fill(providerUrl+'/unsaved-search');
    await page.locator('#limits-max_model_calls').fill('99');
    assert.equal(await card(0).locator('.credential-target').textContent(),target,'Dirty fields cannot relabel the saved credential destination');
    assert.equal(await page.locator('#searchCredentialTarget').textContent(),searchTarget);
    for(const selector of ['#profile-0-secret','#searchSecret'])assert.equal(await page.locator(selector).isDisabled(),true);
    await pointerAttempt(keyButton(0));await pointerAttempt(page.locator('#setSearchSecret'));
    assert.equal(secretPosts.length,postsBeforeDraft,'Dirty provider/search fields never produce a credential POST');
    await page.keyboard.press('Escape');await page.locator('#newRun').click();
    await page.locator('#pmProfile').selectOption(providerId);await page.locator('#maxWorkers').fill('0');
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.uncheck();
    await page.locator('#taskInput').fill(scenario.task);
    const startedResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
    await page.locator('#startRun').focus();await page.keyboard.press('Enter');
    const started=await (await startedResponse).json(),runId=started.run.id;
    const failed=await waitForState(runId,'waiting','error');
    assert.equal(failed.run.model_calls,1);assert.equal(failed.run.tool_calls,0);assert.equal(failed.lead.turns,1);
    assert.match(failed.lead.last_error,/HTTP 401/);assert.equal(failed.lead.message_eligibility.allowed,true);
    await page.locator(`#runList .run-link.selected[data-focus-key="run:${runId}"]`).waitFor();
    await page.locator('#taskDialog').waitFor({state:'hidden'});
    await page.locator('#conversationLog').filter({hasText:'HTTP 401'}).waitFor();
    const draft='[SYNTHETIC] Keep this unsent conversation draft.',taskDraft='[SYNTHETIC] Keep a separate new-task draft.';
    await page.locator('#messageInput').fill(draft);await page.locator('#newRun').click();
    await page.locator('#taskInput').fill(taskDraft);
    const preservedTask={task:taskDraft,pm_profile:providerId,max_workers:'0',worker_profiles:[]};
    assert.deepEqual(await taskDraftSnapshot(),preservedTask,'Recovery task draft deliberately has no selected workers');
    await page.keyboard.press('Escape');await openSettings();
    assert.equal(await page.locator('#saveSettings').isDisabled(),true);
    assert.equal(await page.locator('#profile-0-base_url').isDisabled(),true);
    assert.equal(await page.locator('#limits-max_model_calls').isDisabled(),true);
    assert.equal(await keyButton(0).isDisabled(),true,'Active run does not bypass dirty-destination guard');
    assert.equal(await page.locator('#discardSettings').isEnabled(),true,'Discard remains available while an errored run waits');
    await screenshot('dirty-active-desktop');
    await discard();
    assert.equal(await page.locator('#profile-0-id').inputValue(),providerId);
    assert.equal(await page.locator('#profile-0-base_url').inputValue(),providerUrl);
    assert.equal(await page.locator('#profile-0-proxy_url').inputValue(),proxy);
    assert.equal(await page.locator('#search-endpoint').inputValue(),providerUrl+'/search');
    assert.equal(await page.locator('#limits-max_model_calls').inputValue(),'20');
    assert.equal(await keyButton(0).isEnabled(),true,'Clean saved-target recovery is available during a waiting/error run');
    assert.equal(await page.locator('#setSearchSecret').isEnabled(),true);
    assert.equal(await page.locator('#saveSettings').isDisabled(),true,'Credential recovery cannot unlock active-run configuration');
    assert.equal(configPuts.length,putBaseline);assert.equal(fs.readFileSync(path.join(stateDir,'settings.json'),'utf8'),savedBytes);
    await page.keyboard.press('Escape');assert.equal(await page.locator('#messageInput').inputValue(),draft);
    await page.locator('#newRun').click();assert.equal(await page.locator('#taskInput').inputValue(),taskDraft);
    assert.deepEqual(await taskDraftSnapshot(),preservedTask,'Reopened task preserves PM, zero workers and all worker checkboxes unchecked');
    assert.equal(await page.locator('#workerProfiles input:checked').count(),0);
    await page.keyboard.press('Escape');await openSettings();
    report.checks.push('credentials: real saved-destination 401 becomes waiting/error; dirty/new provider and search guards prevent all key POSTs; active-run keyboard Discard performs GET only, restores saved IDs/endpoints/proxy/budgets, and preserves conversation/new-task drafts');

    const beforeRecovery=budget(failed),postsBeforePending=secretPosts.length;
    const deferred=await holdKey(providerId,scenario.old);
    assert.equal(await card(0).locator('input[type="password"]').inputValue(),'');
    assert.equal(await keyButton(0).isDisabled(),true);assert.equal(await page.locator('#discardSettings').isDisabled(),true);
    assert.equal(await page.locator('#saveSettings').isDisabled(),true);
    await page.keyboard.press('Enter');await page.keyboard.press('Space');await pointerAttempt(keyButton(0));await poll(2);
    assert.equal(secretPosts.length,postsBeforePending+1,'Pending provider write ignores duplicate native activation across polls');
    assert.equal(await page.locator('#setSearchSecret').isEnabled(),true,'An independent saved search target remains usable');
    await submitKey('search',scenario.search_new);
    assert.equal(await keyButton(0).isDisabled(),true,'Search completion cannot release the provider pending guard');
    assert.equal(await page.locator('#discardSettings').isDisabled(),true);
    await closeSettingsDialog(page);assert.equal(await page.locator('#settingsDialog').isVisible(),false);
    await openSettings();assert.equal(await keyButton(0).isDisabled(),true,'Pending guard survives close/reopen');
    const reopenedResult=await card(0).locator('.credential-result').textContent();
    assert.equal(reopenedResult,'','Native close has cleared the old pending notice');
    assert.match(await card(0).locator('.secret-status').textContent(),/更新結果は未確認/);
    await releaseReal(deferred);assert.equal(await card(0).locator('.credential-result').textContent(),reopenedResult,
      'A late success cannot repaint a reopened credential dialog');
    assert.equal(await keyButton(0).isEnabled(),true);await poll(2);
    assert.deepEqual(budget(await waitForState(runId,'waiting','error')),beforeRecovery,'Key writes/polling neither retry nor refill budgets');

    await page.locator('#searchCredentialTarget').scrollIntoViewIfNeeded();await screenshot('search-target-desktop');
    await page.setViewportSize({width:390,height:844});
    await card(0).locator('.credential-target').scrollIntoViewIfNeeded();await screenshot('recovery-ready-narrow');
    const replacement=await submitKey(providerId,scenario.new);
    assert.equal(replacement.config_revision,saved.config_revision);
    await card(0).locator('.credential-result').scrollIntoViewIfNeeded();await screenshot('replacement-narrow');
    await page.setViewportSize({width:1366,height:768});
    await card(0).locator('.credential-result').scrollIntoViewIfNeeded();await screenshot('replacement-desktop');
    await poll(2);
    assert.deepEqual(budget(await waitForState(runId,'waiting','error')),beforeRecovery,'Replacement itself cannot retry, create results, or reset counters');
    const afterKey=await api('/api/config');assert.deepEqual(afterKey.config,saved.config);
    assert.equal(afterKey.config_revision,saved.config_revision);assert.equal(afterKey.secret_status[otherId],true);
    assert.equal(afterKey.secret_status.search,true);assert.equal(configPuts.length,putBaseline);
    assert.equal(fs.readFileSync(path.join(stateDir,'settings.json'),'utf8'),savedBytes);
    await page.keyboard.press('Escape');assert.equal(await page.locator('#messageInput').inputValue(),draft);
    await page.locator('#messageInput').fill(scenario.resume);
    const resumedResponse=page.waitForResponse(response=>new URL(response.url()).pathname===`/api/agents/${failed.lead.id}/message`);
    await page.locator('#sendMessage').focus();await page.keyboard.press('Enter');assert.equal((await resumedResponse).status(),200);
    const resumed=await waitForState(runId,'done','done');
    assert.equal(resumed.lead.id,failed.lead.id);assert.equal(resumed.run.model_calls,2);assert.equal(resumed.lead.turns,2);
    assert.equal(resumed.run.tool_calls,0);assert.equal(resumed.run.auto_collaborations,failed.run.auto_collaborations);
    assert.equal(resumed.run.max_auto_collaborations,7);assert.equal(resumed.run.created_at,failed.run.created_at);
    assert.equal(resumed.state.runs.length,failed.state.runs.length,'Explicit recovery continues the same run without creating a replacement');
    assert(resumed.lead.results.some(result=>result.text.includes('Same run resumed with the replacement provider key.')));
    await page.locator('#activeRunStatus').filter({hasText:'完了'}).waitFor();await screenshot('resumed-desktop',false);
    await page.setViewportSize({width:390,height:844});await screenshot('resumed-narrow',false);
    report.checks.push('credentials: native keyboard replacement during active error keeps configuration, revision, time/call/turn/collaboration budgets and drafts; provider/search writes stay distinct; per-target pending guards survive polls and close/reopen while independent search completes; late success cannot repaint; only explicit same-agent message resumes the same real run with the verified new key; desktop/narrow screenshots');

    // A second settings client can advance revision while the browser is idle.
    // A real 409, delayed across close/reopen, must not repaint newer UI.
    await page.setViewportSize({width:1366,height:768});await openSettings();
    const stale=await holdKey(providerId,scenario.new);
    assert.equal(await page.locator('#saveSettings').isDisabled(),true,'Pending key also locks configuration after a run is done');
    assert.equal(await page.locator('#profile-0-model').isDisabled(),true);
    await closeSettingsDialog(page);await openSettings();
    const beforeFailure=await card(0).locator('.credential-result').textContent();
    assert.equal(beforeFailure,'','Native close has cleared the old pending notice');
    assert.match(await card(0).locator('.secret-status').textContent(),/更新結果は未確認/);
    const changed=await api('/api/config','PUT',saved.config);assert(changed.config_revision>saved.config_revision);
    await releaseReal(stale,409);assert.equal(await card(0).locator('.credential-result').textContent(),beforeFailure,
      'A late rejection cannot repaint a reopened dialog');
    await discard();assert.equal(await keyButton(0).isEnabled(),true);
    const current=await submitKey(providerId,scenario.new);assert.equal(current.config_revision,changed.config_revision);
    assert.deepEqual(budget(await waitForState(runId,'done','done')),budget(resumed),'Stale response/reload/key resubmission never replay a completed run');

    // Read-only reload must also preserve a draft that the newer saved config
    // cannot admit. Keep unavailable selections visible for the user to fix.
    await page.keyboard.press('Escape');await page.locator('#newRun').click();
    await page.locator('#pmProfile').selectOption(otherId);await page.locator('#maxWorkers').fill('3');
    await page.locator(`#workerProfiles input[value="${otherId}"]`).check();
    const unavailableDraft=await taskDraftSnapshot();await page.keyboard.press('Escape');
    const reduced=structuredClone(saved.config);reduced.providers=reduced.providers.filter(profile=>profile.id!==otherId);
    reduced.limits.max_workers=0;
    await api('/api/config','PUT',reduced);await openSettings();await discard();
    assert.deepEqual(await taskDraftSnapshot(),unavailableDraft);
    assert.match(await page.locator(`#pmProfile option[value="${otherId}"]`).textContent(),/利用不可/);
    assert.equal(await page.locator(`#workerProfiles input[value="${otherId}"]`).isChecked(),true);
    assert.equal(await page.locator('#maxWorkers').getAttribute('max'),'0');
    assert.equal(await page.locator('#maxWorkers').inputValue(),'3','Discard does not clamp the user draft to a changed saved limit');
    await api('/api/config','PUT',saved.config);await discard();
    assert.deepEqual(await taskDraftSnapshot(),unavailableDraft,'Restoring the saved profiles also preserves the same draft');
    assert.deepEqual(budget(await waitForState(runId,'done','done')),budget(resumed));
    report.checks.push('credentials: every Discard preserves exact task text, PM, raw worker count, selected worker IDs and conversation draft; empty worker selection stays empty; changed saved configuration retains unavailable PM/worker choices and an out-of-limit draft without clamping or starting work');

    // Search credentials have their own applicability rules, even when a
    // provider credential is configured and the overall form is clean.
    await page.locator('#search-provider').selectOption('searxng');
    assert.equal(await keyButton(0).isDisabled(),true,'Dirty search settings guard provider credentials too');
    await saveSettings();
    assert.equal(await page.locator('#searchSecret').isDisabled(),true);
    assert.equal(await page.locator('#setSearchSecret').isDisabled(),true);
    assert.match((await page.locator('#searchCredentialTarget').textContent())+' '+(await page.locator('#searchSecretStatus').textContent()),/SearXNG/);
    assert.match((await page.locator('#searchCredentialTarget').textContent())+' '+(await page.locator('#searchSecretStatus').textContent()),/使用しません|使いません|対応していません|不要/);
    const beforeUnsupported=secretPosts.length;await pointerAttempt(page.locator('#setSearchSecret'));
    assert.equal(secretPosts.length,beforeUnsupported);assert.equal(await keyButton(0).isEnabled(),true);
    await page.locator('#search-provider').selectOption('brave');await page.locator('#search-endpoint').clear();await saveSettings();
    assert.equal(await page.locator('#searchSecret').isDisabled(),true,'Brave requires an explicit saved nonempty destination');
    assert.equal(await page.locator('#setSearchSecret').isDisabled(),true);
    assert.match((await page.locator('#searchCredentialTarget').textContent())+' '+(await page.locator('#searchSecretStatus').textContent()),/接続先|endpoint/i);
    await page.locator('#search-endpoint').fill(providerUrl+'/search');
    assert.equal(await page.locator('#setSearchSecret').isDisabled(),true,'An unsaved Brave endpoint cannot receive a key');
    await saveSettings();await submitKey('search',scenario.search_new);
    assert.equal((await api('/api/config')).secret_status[providerId],true);
    await page.setViewportSize({width:390,height:844});
    await page.locator('#searchCredentialTarget').scrollIntoViewIfNeeded();await screenshot('search-target-narrow');
    await page.keyboard.press('Escape');
    masked(fs.readFileSync(path.join(stateDir,'settings.json'),'utf8'),'Persisted configuration');
    masked(await page.locator('body').innerText(),'Final visible UI');
    assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
    assert.deepEqual(providerRequests,providerBefore,'Credential/settings/recovery flows never contact the real fixture provider HTTP server');
    assert.deepEqual(report.externalRequests,externalBefore,'Credential recovery causes zero off-origin page requests');
    assert.equal(new URL(page.url()).origin,origin);
    assert.equal(pending.size,0);
    report.checks.push('credentials: real revision conflict and late failure cannot repaint reopened settings; explicit saved-config reload recovers ownership; SearXNG key disabled with explanation, empty/unsaved Brave endpoint blocked, saved Brave target enabled; password values absent from response/UI/settings/browser storage; no external browser or provider requests');
  } finally {
    page.off('request',onRequest);
    for(const route of pending)await route.abort('aborted').catch(()=>{});
  }
}

module.exports={credentialRecoveryAcceptance,closeSettingsDialog};
