/* Production UI + real synthetic loopback app. No model inference or user data. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {closeSettingsDialog} = require('./credential_recovery_acceptance.cjs');

async function settingsSaveAcceptance({page,context,origin,providerUrl,providerRequests,stateDir,artifacts,
  report,assertLayout,assertDialogLayout}) {
  const pending=new Set(),handlers=new Set(),mutations=[],providerBefore=structuredClone(providerRequests);
  const externalBefore=[...report.externalRequests],settingsFile=path.join(stateDir,'settings.json');
  let sibling,activeRunId;
  const paint=target=>target.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const observe=request=>{
    const url=new URL(request.url()),method=request.method();
    if(url.origin!==origin||!url.pathname.startsWith('/api/')||['GET','HEAD','OPTIONS'].includes(method))return;
    const body=request.postDataJSON();
    mutations.push({method,path:url.pathname,
      body:url.pathname==='/api/secrets'?{id:body.id,config_revision:body.config_revision}:body});
  };
  const writes=()=>mutations.filter(item=>item.path==='/api/config'&&item.method==='PUT');
  // Setup uses an explicitly fresh revision, independently of either UI client.
  // Acceptance Save requests must retain their own original loaded revision.
  const api=async(route,method='GET',body,expected=200)=>{
    const response=await context.request.fetch(origin+route,{method,headers:{Origin:origin},
      ...(body===undefined?{}:{data:body})});
    assert.equal(response.status(),expected,method+' '+route+' status');
    return response.json();
  };
  const setup=async config=>{
    const {config_revision}=await api('/api/config');
    return api('/api/config','PUT',{config_revision,config});
  };
  const poll=async(target=page,count=1)=>{
    for(let i=0;i<count;i++){
      const request=await target.waitForRequest(request=>new URL(request.url()).pathname==='/api/state');
      const response=await request.response();assert(response);assert.equal(response.status(),200);
      await response.finished();await paint(target);
    }
  };
  const openSettings=async(target=page)=>{
    await target.locator('#navSettings').focus();await target.keyboard.press('Enter');
    await target.locator('#settingsDialog').waitFor({state:'visible'});
  };
  const taskSnapshot=(target=page)=>target.evaluate(()=>({task:document.querySelector('#taskInput').value,
    pm_profile:document.querySelector('#pmProfile').value,max_workers:document.querySelector('#maxWorkers').value,
    worker_profiles:[...document.querySelectorAll('#workerProfiles input:checked')].map(input=>input.value)}));
  const viewSnapshot=(target=page)=>target.evaluate(()=>({status:document.querySelector('#settingsStatus').textContent,
    notice:document.querySelector('#globalNotice').textContent,noticeHidden:document.querySelector('#globalNotice').hidden,
    noticeError:document.querySelector('#globalNotice').classList.contains('error'),
    focused:document.activeElement.id||document.activeElement.getAttribute('aria-controls')||document.activeElement.dataset.focusKey,
    message:document.querySelector('#messageInput').value}));
  const controls=target=>target.locator('#settingsDialog button[type="submit"]');
  const keyButton=target=>target.locator('.profile-editor').first().getByRole('button',{name:'キーをセット',exact:true});
  const probeButton=target=>target.locator('.profile-editor').first().getByRole('button',{name:'モデル一覧を確認',exact:true});
  const disclosure=target=>target.locator('.profile-editor').first().locator('button[data-readonly="true"]');
  const checkSaveDisabled=async(target=page)=>{
    assert.equal(await controls(target).count(),2,'Both native Save affordances are covered');
    for(const button of await controls(target).all())assert.equal(await button.isDisabled(),true);
  };
  const checkPending=async()=>{
    await checkSaveDisabled();
    for(const selector of ['#discardSettings','#profile-0-label','#limits-max_model_calls','#addProfile','#profile-0-secret','#searchSecret'])
      assert.equal(await page.locator(selector).isDisabled(),true,'Pending Save locks '+selector);
    assert.equal(await keyButton(page).isDisabled(),true);assert.equal(await probeButton(page).isDisabled(),true);
    assert.equal(await disclosure(page).isEnabled(),true,'Read-only disclosure remains accessible');
  };
  const checkStale=async()=>{
    await checkSaveDisabled();
    assert.equal(await page.locator('#discardSettings').isEnabled(),true);
    assert.equal(await keyButton(page).isDisabled(),true);assert.equal(await probeButton(page).isDisabled(),true);
    assert.match(await page.locator('#settingsLockStatus').textContent(),/読み直/);
  };
  const pointerAttempt=async button=>{
    await button.scrollIntoViewIfNeeded();const box=await button.boundingBox();assert(box);
    await page.mouse.click(box.x+box.width/2,box.y+box.height/2,{clickCount:2});await paint(page);
  };
  const save=async(target=page,expected=200)=>{
    const response=target.waitForResponse(response=>new URL(response.url()).pathname==='/api/config'&&response.request().method()==='PUT');
    await target.locator('#saveSettings').focus();await target.keyboard.press('Enter');
    const received=await response;assert.equal(received.status(),expected);const body=await received.json();
    await received.finished();await paint(target);
    return {response:body,request:received.request().postDataJSON()};
  };
  const discard=async()=>{
    const draft=await taskSnapshot(),message=await page.locator('#messageInput').inputValue(),before=writes().length;
    const response=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/config'&&response.request().method()==='GET');
    await page.locator('#discardSettings').focus();await page.keyboard.press('Enter');
    assert.equal((await response).status(),200);
    await page.locator('#settingsStatus').filter({hasText:'保存済み設定を読み直しました'}).waitFor();
    assert.deepEqual(await taskSnapshot(),draft,'Explicit reload preserves exact task, PM, worker IDs and raw count');
    assert.equal(await page.locator('#messageInput').inputValue(),message,'Explicit reload preserves the conversation draft');
    assert.equal(writes().length,before,'Explicit reload is read-only and never replays Save');
  };
  const holdSave=async({commit=true}={})=>{
    let resolve,reject;const captured=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const handler=async route=>{
      if(route.request().method()!=='PUT')return route.fallback();
      const entry={route,upstream:null};pending.add(entry);
      try{if(commit){entry.upstream=await route.fetch();assert.equal(entry.upstream.status(),200);}resolve(entry);}
      catch(error){reject(error);}
    };
    handlers.add(handler);await page.route('**/api/config',handler,{times:1});
    const requested=page.waitForRequest(request=>new URL(request.url()).pathname==='/api/config'&&request.method()==='PUT');
    await page.locator('#saveSettings').click();await requested;return captured;
  };
  const release=async(entry,{status=200,mode='real'}={})=>{
    if(!entry.upstream)entry.upstream=await entry.route.fetch();
    assert.equal(entry.upstream.status(),status,'Held request still reaches the real configuration endpoint');
    if(mode==='abort'){
      const failed=page.waitForEvent('requestfailed',request=>request===entry.route.request());
      await entry.route.abort('connectionreset');await failed;
    }else{
      const received=page.waitForResponse(response=>response.request()===entry.route.request());
      if(mode==='malformed')await entry.route.fulfill({status:200,contentType:'application/json',body:'{"ok":true}'});
      else await entry.route.fulfill({response:entry.upstream});
      await (await received).finished();
    }
    pending.delete(entry);await paint(page);
    await page.waitForFunction(()=>!document.querySelector('#discardSettings').disabled);
  };
  const screenshot=async(name,dialog='#settingsDialog')=>{
    if(dialog)await assertDialogLayout(page,dialog,name);else await assertLayout(page,name);
    await page.screenshot({path:path.join(artifacts,'workbench-settings-save-'+name+'.png'),fullPage:true,animations:'disabled'});
  };
  const newTask=async({task,pm_profile='local',max_workers='0',worker_profiles=[]})=>{
    await page.locator('#newRun').click();await page.locator('#pmProfile').selectOption(pm_profile);
    await page.locator('#maxWorkers').fill(max_workers);
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.setChecked(worker_profiles.includes(await checkbox.inputValue()));
    await page.locator('#taskInput').fill(task);
  };
  const waitRun=async(id,status)=>{
    const deadline=Date.now()+10000;
    for(;;){const state=await api('/api/state'),run=state.runs.find(item=>item.id===id);
      if(run?.status===status)return {run,agents:state.agents.filter(item=>item.run_id===id)};
      assert(Date.now()<deadline,'Real synthetic run did not reach '+status);await new Promise(resolve=>setTimeout(resolve,25));}
  };
  context.on('request',observe);
  try {
    await page.setViewportSize({width:1366,height:768});
    const initial=await api('/api/config'),config=structuredClone(initial.config);
    const profile={...config.providers[0],id:'local',label:'[SYNTHETIC] Settings Save baseline',kind:'local',
      enabled:true,model:'settings-save-no-network',base_url:providerUrl,api_key_env:'',proxy_url:'',request_timeout_seconds:30};
    config.providers=[profile,{...profile,id:'save-removed',label:'[SYNTHETIC] Explicit unavailable choice'}];
    Object.assign(config.limits,{max_workers:3,max_turns_per_agent:8,max_model_calls:20,max_tool_calls:30,
      max_auto_collaborations:7,max_run_seconds:600,max_context_chars:200000});
    config.search.enabled=false;
    const baseline=await setup(config);
    await page.reload();await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    sibling=await context.newPage();sibling.setDefaultTimeout(10000);
    sibling.on('pageerror',error=>report.pageErrors.push(error.message));
    sibling.on('console',message=>{if(/Content Security Policy|violates.*directive/i.test(message.text()))report.cspErrors.push(message.text());});
    sibling.on('request',request=>{const url=new URL(request.url());if(url.protocol.startsWith('http')&&url.origin!==origin)report.externalRequests.push(url.origin+url.pathname);});
    await sibling.goto(origin);await sibling.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    const emptyDraft={task:'[SYNTHETIC] Keep empty workers through Settings Save.',pm_profile:'local',max_workers:'0',worker_profiles:[]};
    await newTask(emptyDraft);await page.keyboard.press('Escape');await openSettings();await openSettings(sibling);
    const staleLabel='[SYNTHETIC] Tab B unrelated label draft';
    await page.locator('#profile-0-label').fill(staleLabel);
    await sibling.locator('#limits-max_model_calls').fill('5');
    const accepted=await save(sibling);assert.equal(accepted.request.config_revision,baseline.config_revision);
    assert.deepEqual(Object.keys(accepted.request).sort(),['config','config_revision']);
    assert.equal(accepted.response.config_revision,baseline.config_revision+1);
    assert.equal(accepted.request.config.limits.max_model_calls,5);
    const persisted=fs.readFileSync(settingsFile,'utf8'),beforeConflict=writes().length;
    const rejected=await save(page,409);
    assert.equal(rejected.request.config_revision,baseline.config_revision,'Tab B submits its loaded revision, never a fresh retry');
    assert.equal(rejected.request.config.limits.max_model_calls,20);assert.equal(rejected.request.config.providers[0].label,staleLabel);
    assert.equal(rejected.response.code,'settings_changed');
    assert.equal(fs.readFileSync(settingsFile,'utf8'),persisted,'Stale unrelated-label Save cannot restore a lowered budget');
    const current=await api('/api/config');assert.equal(current.config_revision,accepted.response.config_revision);
    assert.equal(current.config.limits.max_model_calls,5);assert.equal(current.config.providers[0].label,profile.label);
    assert.equal(await page.locator('#profile-0-label').inputValue(),staleLabel);
    assert.equal(await page.locator('#limits-max_model_calls').inputValue(),'20');
    assert.equal(await page.locator('#profile-0-label').isEnabled(),true,'Stale editable draft remains available for correction');
    await checkStale();assert.match(await page.locator('#settingsStatus').textContent(),/保存済み設定を読み直/);
    await pointerAttempt(page.locator('#saveSettings'));await page.locator('#profile-0-label').focus();await page.keyboard.press('Enter');
    await poll(page,2);assert.equal(writes().length,beforeConflict+1,'Stale Save never auto-replays through keyboard, pointer or polls');
    await page.locator('#profile-0-label').scrollIntoViewIfNeeded();await screenshot('conflict-draft-desktop');
    await page.locator('#settingsStatus').scrollIntoViewIfNeeded();await screenshot('conflict-desktop');
    await page.setViewportSize({width:390,height:844});await page.locator('#settingsStatus').scrollIntoViewIfNeeded();await screenshot('conflict-narrow');
    await closeSettingsDialog(page);await openSettings();await checkStale();
    assert.equal(await page.locator('#profile-0-label').inputValue(),staleLabel);
    await discard();assert.equal(await page.locator('#limits-max_model_calls').inputValue(),'5');
    assert.equal(await page.locator('#profile-0-label').inputValue(),profile.label);
    assert.deepEqual(await taskSnapshot(),emptyDraft,'Empty worker selection remains empty after recovery');
    assert.equal(await page.locator('#saveSettings').isEnabled(),true);
    await sibling.close();sibling=null;
    report.checks.push('settings-save: two authenticated tabs use captured revisions; tab A lowers max_model_calls and stale tab B unrelated-label Save gets real 409/settings_changed without overwriting file/revision; editable draft remains; both Save buttons, credentials and diagnostics blocked until explicit read-only Discard; no automatic replay; empty-worker task draft survives; desktop/narrow conflict screenshots');

    // The server commits while delivery waits. The newer task deliberately uses
    // the saved-then-removed profile, producing a real rejection/newer notice.
    await page.setViewportSize({width:1366,height:768});await closeSettingsDialog(page);
    const unavailable={task:'[SYNTHETIC] New task after delayed Save.',pm_profile:'save-removed',max_workers:'3',worker_profiles:['save-removed']};
    await newTask({...unavailable,task:'[SYNTHETIC] Initial unavailable-choice task.'});await page.keyboard.press('Escape');await openSettings();
    const delayedLabel='[SYNTHETIC] Committed while dialog was closed';
    await page.locator('#profile-0-label').fill(delayedLabel);await page.locator('#limits-max_workers').fill('0');
    await page.locator('.profile-editor').nth(1).getByRole('button',{name:'削除',exact:true}).click();
    const beforeDeferred=writes().length,held=await holdSave();await checkPending();
    await pointerAttempt(page.locator('#saveSettings'));await page.keyboard.press('Enter');await page.keyboard.press('Space');await poll(page,2);
    assert.equal(writes().length,beforeDeferred+1,'Pending Save stays one request across native duplicate activation and polling');
    const committed=await api('/api/config');assert.equal(committed.config.providers[0].label,delayedLabel);
    assert.equal(committed.config.providers.length,1);assert.equal(committed.config.limits.max_workers,0);
    await closeSettingsDialog(page);await newTask(unavailable);
    const rejectedStart=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
    await page.locator('#startRun').click();assert.equal((await rejectedStart).status(),400);
    await page.locator('#globalNotice.error').waitFor({state:'visible'});
    const taskAfterRejection=await taskSnapshot();assert.deepEqual(taskAfterRejection,unavailable);
    await page.keyboard.press('Escape');await openSettings();await checkPending();
    assert.match(await page.locator('#settingsStatus').textContent(),/閉じても保存要求は取り消されません/);
    await disclosure(page).focus();const newerView=await viewSnapshot();
    await release(held);await poll();
    assert.deepEqual(await viewSnapshot(),newerView,'Late success cannot overwrite reopened status, newer notice, focus or message draft');
    assert.deepEqual(await taskSnapshot(),unavailable,'Late success cannot clamp or rebuild a newer task draft');
    assert.equal(await page.locator('#saveSettings').isEnabled(),true,'Known successful late save reconciles the saved baseline');
    assert.equal(await keyButton(page).isEnabled(),true,'Exact unchanged submitted generation becomes a clean saved target');
    assert.equal(writes().length,beforeDeferred+1);
    await page.locator('#settingsStatus').scrollIntoViewIfNeeded();await screenshot('late-success-desktop');
    await discard();assert.deepEqual(await taskSnapshot(),unavailable);
    assert.match(await page.locator('#pmProfile option[value="save-removed"]').textContent(),/利用不可/);
    assert.equal(await page.locator('#workerProfiles input[value="save-removed"]').isChecked(),true);
    assert.equal(await page.locator('#maxWorkers').getAttribute('max'),'0');assert.equal(await page.locator('#maxWorkers').inputValue(),'3');
    await closeSettingsDialog(page);await page.locator('#newRun').click();
    await page.locator('#pmProfile').focus();await screenshot('unavailable-draft-desktop','#taskDialog');
    await page.setViewportSize({width:390,height:844});
    await page.locator('#pmProfile').scrollIntoViewIfNeeded();await screenshot('unavailable-draft-narrow','#taskDialog');
    await page.keyboard.press('Escape');await openSettings();
    report.checks.push('settings-save: real committed Save response delayed across native queued close and reopen retains pending controls; a newer real Start rejection, reopened status and native focus survive late success; saved baseline reconciles without task overwrite; explicit reload retains removed PM/worker selections as unavailable and raw above-limit count for explicit correction; desktop/narrow screenshots');

    // Real Save settlement replaces the task's checkbox nodes. Native focus
    // belongs to that newer task, even though the request began in Settings.
    await page.setViewportSize({width:1366,height:768});
    await page.locator('#profile-0-label').fill('[SYNTHETIC] Retained worker focus Save');
    const retainedSave=await holdSave();await closeSettingsDialog(page);
    const focusedDraft={task:'[SYNTHETIC] Keep focused worker and exact task draft.',
      pm_profile:'local',max_workers:'0',worker_profiles:['local']};
    await newTask(focusedDraft);
    const retainedWorker=page.locator('#workerProfiles input[value="local"]');
    await page.locator('#maxWorkers').focus();await page.keyboard.press('Tab');
    assert.equal(await retainedWorker.evaluate(node=>node===document.activeElement),true,'Native Tab reaches the retained worker checkbox');
    await retainedWorker.evaluate(node=>{window.settingsSaveFocusedWorker=node;});
    const retainedView=await viewSnapshot(),beforeRetainedRelease=writes().length;
    await release(retainedSave);await poll();
    assert.equal(await page.evaluate(()=>window.settingsSaveFocusedWorker.isConnected),false,'Successful Save actually replaced the original worker node');
    assert.equal(await retainedWorker.evaluate(node=>node===document.activeElement),true,'The matching replacement checkbox retains native focus');
    assert.equal(await retainedWorker.isChecked(),true);
    assert.deepEqual(await taskSnapshot(),focusedDraft);assert.deepEqual(await viewSnapshot(),retainedView);
    assert.equal(await page.locator('#taskDialog').isVisible(),true);assert.equal(writes().length,beforeRetainedRelease);
    await screenshot('retained-worker-focus-desktop','#taskDialog');
    await page.keyboard.press('Space');assert.equal(await retainedWorker.isChecked(),false);
    await page.keyboard.press('Space');assert.equal(await retainedWorker.isChecked(),true);
    assert.deepEqual(await taskSnapshot(),focusedDraft,'The retained native checkbox remains keyboard-operable');
    await page.keyboard.press('Escape');await openSettings();

    // Unchecked removed workers need not survive as unavailable choices. When
    // their focused node disappears, the task's PM selector is the safe fallback.
    await page.locator('#addProfile').click();
    await page.locator('#profile-1-id').fill('focus-removed');
    await page.locator('#profile-1-label').fill('[SYNTHETIC] Removed unchecked focus');
    await page.locator('#profile-1-base_url').fill(providerUrl);
    await page.locator('#profile-1-model').fill('settings-focus-no-network');
    await save();
    await page.locator('.profile-editor').nth(1).getByRole('button',{name:'削除',exact:true}).click();
    const removedSave=await holdSave();await closeSettingsDialog(page);
    const removedDraft={...focusedDraft,task:'[SYNTHETIC] Removed unchecked worker focus falls back to PM.'};
    await page.setViewportSize({width:390,height:844});await newTask(removedDraft);
    const removedWorker=page.locator('#workerProfiles input[value="focus-removed"]');
    assert.equal(await removedWorker.isChecked(),false);
    await page.locator('#maxWorkers').focus();await page.keyboard.press('Tab');await page.keyboard.press('Tab');
    assert.equal(await removedWorker.evaluate(node=>node===document.activeElement),true,'Native Tab reaches the unchecked worker about to disappear');
    await removedWorker.evaluate(node=>{window.settingsSaveFocusedWorker=node;});
    const removedView=await viewSnapshot(),beforeRemovedRelease=writes().length;
    await release(removedSave);await poll();
    assert.equal(await page.evaluate(()=>window.settingsSaveFocusedWorker.isConnected),false);
    assert.equal(await removedWorker.count(),0,'An unchecked removed worker is not silently selected or retained');
    assert.equal(await page.locator('#pmProfile').evaluate(node=>node===document.activeElement),true,'Removed unchecked worker focus falls back to the PM selector');
    assert.deepEqual(await taskSnapshot(),removedDraft);
    assert.deepEqual(await viewSnapshot(),{...removedView,focused:'pmProfile'});
    assert.equal(await page.locator('#taskDialog').isVisible(),true);assert.equal(writes().length,beforeRemovedRelease);
    await screenshot('removed-worker-focus-narrow','#taskDialog');
    await page.evaluate(()=>{delete window.settingsSaveFocusedWorker;});
    await page.keyboard.press('Escape');await openSettings();
    report.checks.push('settings-save: actual held successful saves settle while native Tab focus belongs to task worker checkboxes; replaced checked worker preserves its logical focus and exact draft and remains Space-operable; removed unchecked focused worker disappears and falls back to PM without changing draft, newer notice/status or replaying Save; desktop/narrow focus screenshots');

    // A second writer wins before the held request reaches the server. Even the
    // late conflict must block future Save without repainting the reopened view.
    await page.setViewportSize({width:1366,height:768});
    const lateConflictLabel='[SYNTHETIC] Keep late conflict draft';await page.locator('#profile-0-label').fill(lateConflictLabel);
    const lateConflict=await holdSave({commit:false});await closeSettingsDialog(page);await openSettings();
    await disclosure(page).focus();const beforeLateConflict=await viewSnapshot();
    const replacement=structuredClone((await api('/api/config')).config);replacement.limits.max_model_calls=4;
    await setup(replacement);const replacementBytes=fs.readFileSync(settingsFile,'utf8');
    await release(lateConflict,{status:409});await poll();
    assert.deepEqual(await viewSnapshot(),beforeLateConflict,'Late conflict does not repaint reopened status/notice/focus');
    assert.equal(await page.locator('#profile-0-label').inputValue(),lateConflictLabel);
    assert.equal(fs.readFileSync(settingsFile,'utf8'),replacementBytes);await checkStale();await discard();
    assert.equal(await page.locator('#limits-max_model_calls').inputValue(),'4');

    // Lose the response after an actual commit, and separately deliver a malformed
    // success. Neither outcome permits replay, even if the dialog was reopened.
    for(const mode of ['abort','malformed']) {
      const label='[SYNTHETIC] Unknown outcome '+mode;await page.locator('#profile-0-label').fill(label);
      const before=writes().length,draft=await taskSnapshot(),unknown=await holdSave();
      if(mode==='abort'){
        await closeSettingsDialog(page);await openSettings();await disclosure(page).focus();
        const view=await viewSnapshot();await release(unknown,{mode});assert.deepEqual(await viewSnapshot(),view);
      }else await release(unknown,{mode});
      await checkStale();assert.equal(await page.locator('#profile-0-label').inputValue(),label);
      assert.deepEqual(await taskSnapshot(),draft);
      if(mode==='malformed')assert.match(await page.locator('#settingsStatus').textContent(),/保存済み設定を読み直/);
      assert.equal((await api('/api/config')).config.providers[0].label,label,'Unknown delivery does not undo the actual commit');
      await pointerAttempt(page.locator('#saveSettings'));await poll(page,2);assert.equal(writes().length,before+1,'Unknown outcome must never retry Save');
      await page.locator(mode==='abort'?'#settingsLockStatus':'#settingsStatus').scrollIntoViewIfNeeded();
      await screenshot('unknown-'+mode+'-desktop');
      if(mode==='abort'){
        await discard();assert.equal(await page.locator('#profile-0-label').inputValue(),label);
        assert.equal(await page.locator('#saveSettings').isEnabled(),true);
      }
    }
    await page.setViewportSize({width:390,height:844});await page.locator('#settingsStatus').scrollIntoViewIfNeeded();
    await screenshot('unknown-malformed-narrow');await page.setViewportSize({width:1366,height:768});
    report.checks.push('settings-save: late real 409 cannot repaint reopened status/focus; aborted delivery after real commit and malformed successful response both preserve draft, block both Save controls/credentials/diagnostics and never replay; only explicit read-only reload resolves unknown state');

    // Explicitly correct the preserved task and start one real synthetic run.
    // Unknown Save cannot accidentally grant credential access during that run.
    await closeSettingsDialog(page);
    await newTask({task:'[SYNTHETIC] Settings Save active-run credential boundary.'});
    const started=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
    await page.locator('#startRun').click();const startResponse=await started;assert.equal(startResponse.status(),200);
    activeRunId=(await startResponse.json()).run.id;
    const waiting=await waitRun(activeRunId,'waiting');
    await page.locator(`#runList .run-link.selected[data-focus-key="run:${activeRunId}"]`).waitFor();
    await page.locator('#taskDialog').waitFor({state:'hidden'});await poll();await openSettings();
    await checkStale();assert.equal(await page.locator('#profile-0-label').isDisabled(),true);
    await discard();await checkSaveDisabled();assert.equal(await page.locator('#profile-0-label').isDisabled(),true);
    assert.equal(await keyButton(page).isEnabled(),true,'Explicit reload enables only saved credentials during the active run');
    const credentialRevision=(await api('/api/config')).config_revision,beforeKey=writes().length;
    await page.locator('#profile-0-secret').fill('WB20-synthetic-settings-save-key');
    const keyResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/secrets');
    await keyButton(page).focus();await page.keyboard.press('Space');const keyResult=await keyResponse;
    assert.equal(keyResult.status(),200);assert.equal(keyResult.request().postDataJSON().config_revision,credentialRevision);
    await page.locator('.credential-result').first().filter({hasText:'キーをセットしました'}).waitFor();
    await checkSaveDisabled();assert.equal(writes().length,beforeKey);
    assert.equal((await api('/api/config')).config_revision,credentialRevision);
    assert.deepEqual(await waitRun(activeRunId,'waiting'),waiting,'Credential recovery never resumes or resets the active run');
    await page.locator('#settingsLockStatus').scrollIntoViewIfNeeded();await screenshot('active-lock-desktop');
    await page.setViewportSize({width:390,height:844});await page.locator('#settingsLockStatus').scrollIntoViewIfNeeded();await screenshot('active-lock-narrow');
    await closeSettingsDialog(page);await page.locator('#stopRun').click();await waitRun(activeRunId,'stopped');activeRunId=null;
    await page.locator('#activeRunStatus').filter({hasText:'停止'}).waitFor();await openSettings();
    assert.equal(await page.locator('#saveSettings').isEnabled(),true);await closeSettingsDialog(page);
    assert.deepEqual(providerRequests,providerBefore,'Settings-save acceptance sends no provider network traffic');
    assert.deepEqual(report.externalRequests,externalBefore);assert.equal(pending.size,0);
    assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
    report.checks.push('settings-save: explicit correction starts one real synthetic waiting run; stale/unknown state blocks credentials until explicit reload, active run still locks configuration, saved-target key replacement preserves revision and complete run/agent budgets/history without replay, explicit Stop unlocks Save; desktop/narrow lock screenshots; no external/provider requests or browser storage');
  } finally {
    context.off('request',observe);
    for(const entry of pending)await entry.route.abort('aborted').catch(()=>{});
    for(const handler of handlers)await page.unroute('**/api/config',handler).catch(()=>{});
    if(sibling)await sibling.close().catch(()=>{});
    if(activeRunId)await api('/api/runs/'+activeRunId+'/stop','POST',{}).catch(()=>{});
  }
}

module.exports={settingsSaveAcceptance};
