/* Browser-only controller races. All teams/responses are synthetic; no inference. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

async function lifecycleAcceptance({page,agentContract,artifacts,report,assertLayout,assertDialogLayout}) {
  const fixture={runs:[],agents:[],events:[],resources:{active:0,queued:0}};
  const requests={start:[],stop:[]},waiters={},pending=new Set();
  let stateFailure=false,stateResponses=0;
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const runLink=id=>page.locator(`#runList .run-link[data-focus-key="run:${id}"]`);
  const selectedRun=()=>page.locator('#runList .run-link.selected').getAttribute('data-focus-key');
  const focused=selector=>page.locator(selector).evaluate(element=>element===document.activeElement);
  const team=(id,task,status='running')=>{
    const agentId=id+'-pm',at=1791169200+fixture.runs.length;
    return {run:{id,task,pm_profile:'local',worker_profiles:[],max_workers:0,status,status_reason:status,
      created_at:at,model_calls:0,tool_calls:0,auto_collaborations:0,max_auto_collaborations:7,
      collaboration_limit_reached:false,agent_ids:[agentId]},
    agent:{...structuredClone(agentContract),id:agentId,run_id:id,name:'[SYNTHETIC] '+id+' PM',role:'pm',
      profile_id:'local',status:status==='running'?'working':status,status_reason:status==='running'?'working':status,
      assignment:task,question:'',turns:1,logs:[{id:1,kind:'assistant',text:'[SYNTHETIC] Lifecycle log '+id,at}],
      results:[],output_receipts:[],configured_profile:{id:'local',label:'[SYNTHETIC] Local',kind:'local',model:'synthetic-lifecycle'},
      message_eligibility:{allowed:status!=='stopped',reason:status==='stopped'?'stopped':'',message:status==='stopped'?'[SYNTHETIC] Stopped.':''}}};
  };
  const publish=entry=>{fixture.runs.push(entry.run);fixture.agents.push(entry.agent);};
  const setStatus=(id,status)=>{
    const run=fixture.runs.find(item=>item.id===id);assert(run);run.status=status;run.status_reason=status;
    for(const agent of fixture.agents.filter(item=>item.run_id===id)){
      agent.status=status==='running'?'working':status;agent.status_reason=agent.status;
      agent.message_eligibility={allowed:status!=='stopped',reason:status==='stopped'?'stopped':'',message:status==='stopped'?'[SYNTHETIC] Stopped.':''};
    }
  };
  const snapshot=request=>{
    const query=new URL(request.url()).searchParams;
    if(query.get('view')!=='selected')return structuredClone(fixture);
    const runId=query.get('run_id'),agentId=query.get('agent_id');
    return {...structuredClone(fixture),agents:fixture.agents.map(agent=>{
      const value=structuredClone(agent);if(agent.id!==agentId)for(const key of ['logs','results','output_receipts'])delete value[key];return value;
    }),events:[],selection:{run_id:runId,agent_id:agentId,detail_loaded:Boolean(agentId)}};
  };
  const stateRoute=async route=>{
    stateResponses++;
    await route.fulfill({status:stateFailure?503:200,contentType:'application/json',
      body:JSON.stringify(stateFailure?{ok:false,error:'[SYNTHETIC] Lifecycle state temporarily unavailable.'}:snapshot(route.request()))});
  };
  const capture=kind=>route=>{
    assert.equal(route.request().method(),'POST');
    const entry={route,payload:route.request().postDataJSON(),url:route.request().url()};
    requests[kind].push(entry);pending.add(entry);
    if(waiters[kind]){const resolve=waiters[kind];delete waiters[kind];resolve(entry);}
  };
  const startRoute=capture('start'),stopRoute=capture('stop');
  const takePost=async(kind,action)=>{
    assert(!waiters[kind]);let timer;
    const captured=new Promise((resolve,reject)=>{
      waiters[kind]=resolve;timer=setTimeout(()=>reject(new Error('No explicit lifecycle '+kind+' POST')),10000);
    });
    try {const [entry]=await Promise.all([captured,action()]);return entry;}
    finally {clearTimeout(timer);delete waiters[kind];}
  };
  const release=async(entry,body,status=200)=>{
    assert(pending.has(entry),'Each deferred response is released exactly once');
    const response=page.waitForResponse(response=>response.request()===entry.route.request());
    await entry.route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    pending.delete(entry);await (await response).finished();await paint();
  };
  // Await actual interval-driven HTTP polling, not direct calls to app internals.
  const poll=async(count=1)=>{
    for(let i=0;i<count;i++){
      const before=stateResponses;
      const request=await page.waitForRequest(request=>new URL(request.url()).pathname==='/api/state');
      const response=await request.response();assert(response);await response.finished();await paint();
      assert(stateResponses>before,'A real state request reached the synthetic controller');
    }
  };
  const select=async id=>{
    await runLink(id).click();await page.locator(`#runList .run-link.selected[data-focus-key="run:${id}"]`).waitFor();
    await page.locator('#conversationLog').filter({hasText:'Lifecycle log '+id}).waitFor();
  };
  const openTask=async task=>{
    await page.locator('#newRun').click();await page.locator('#pmProfile').selectOption('local');
    await page.locator('#maxWorkers').fill('0');
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.uncheck();
    await page.locator('#taskInput').fill(task);await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
  };
  const pointerAttempt=async selector=>{
    const button=page.locator(selector);await button.scrollIntoViewIfNeeded();const box=await button.boundingBox();assert(box);
    // mouse.click, unlike locator.click, really attempts a disabled native control.
    await page.mouse.click(box.x+box.width/2,box.y+box.height/2,{clickCount:2});await paint();
  };
  const assertPendingStart=async(label,expectedCount)=>{
    assert.equal(await page.locator('#startRun').isDisabled(),true,label+': Start stays disabled');
    assert.equal(await page.locator('#taskDialog').isVisible(),true,label+': task remains open');
    assert.equal(requests.start.length,expectedCount,label+': no automatic/repeated start');
  };
  const screenshot=async(name,dialog=false)=>{
    if(dialog){await page.locator('#runFormStatus').scrollIntoViewIfNeeded();await assertDialogLayout(page,'#taskDialog',name);}
    else await assertLayout(page,name);
    await page.screenshot({path:path.join(artifacts,'workbench-lifecycle-'+name+'.png'),fullPage:true,animations:'disabled'});
  };
  for(const [id,status] of [['lifecycle-a','running'],['lifecycle-b','running'],['lifecycle-done','done'],['lifecycle-stopped','stopped']])
    publish(team(id,'[SYNTHETIC] '+id,status));
  await page.route('**/api/state*',stateRoute);await page.route('**/api/runs',startRoute);await page.route('**/api/runs/*/stop',stopRoute);
  try {
    await page.setViewportSize({width:1366,height:768});await page.reload();await runLink('lifecycle-a').waitFor();await select('lifecycle-a');
    const original='[SYNTHETIC] Accepted start survives state failure.';
    await openTask(original);
    const first=await takePost('start',()=>page.locator('#startRun').click());
    assert.deepEqual(first.payload,{task:original,pm_profile:'local',worker_profiles:[],max_workers:0});
    await page.keyboard.press('Enter');await page.keyboard.press('Space');await pointerAttempt('#startRun');await poll(2);
    await assertPendingStart('Deferred POST with keyboard and multiple pointer activation',1);
    assert.equal(await selectedRun(),'run:lifecycle-a');
    stateFailure=true;
    const accepted=team('lifecycle-accepted',original);
    await release(first,{ok:true,run:accepted.run});await poll();
    await page.locator('#connectionStatus').filter({hasText:'接続を確認してください'}).waitFor();
    await assertPendingStart('Accepted POST plus failed state',1);
    assert.match(await page.locator('#runFormStatus').textContent(),/受付|受け付|開始要求/,'Accepted status distinguishes successful POST from an unobserved run');
    assert.match(await page.locator('#runFormStatus').textContent(),/確認|反映|待/,'Accepted status explains the observation wait');
    assert((await page.locator('#runFormStatus').textContent()).includes(accepted.run.id),'Pending status retains the accepted run ID');
    assert.match(await page.locator('#runFormStatus').textContent(),/再送信は不要/);
    assert.equal(await runLink(accepted.run.id).count(),0,'POST alone cannot manufacture an observed team');
    await screenshot('start-awaiting-desktop',true);
    await page.setViewportSize({width:390,height:844});await screenshot('start-awaiting-narrow',true);
    stateFailure=false;await poll(2);
    await assertPendingStart('Healthy poll still missing accepted ID',1);
    await pointerAttempt('#startRun');await page.keyboard.press('Enter');await paint();
    assert.equal(requests.start.length,1);
    // No explicit refresh or second submit: the regular interval discovers it.
    publish(accepted);
    await page.locator(`#runList .run-link.selected[data-focus-key="run:${accepted.run.id}"]`).waitFor();
    await page.locator('#taskDialog').waitFor({state:'hidden'});
    await page.locator('#conversationLog').filter({hasText:'Lifecycle log '+accepted.run.id}).waitFor();
    assert.equal(requests.start.length,1,'Recovered acceptance never replays POST');
    await screenshot('start-recovered-narrow');
    await page.setViewportSize({width:1366,height:768});await screenshot('start-recovered-desktop');
    report.checks.push('lifecycle: deferred native pointer/keyboard Start admits one POST; successful ID stays pending through 503 and healthy missing-ID polls; interval recovery selects/closes only the unchanged owner; no automatic replay; desktop/narrow pending and recovery screenshots');

    // A visible draft edited away and back is still a new editing generation.
    await select('lifecycle-a');
    const abaTask='[SYNTHETIC] Draft ABA ownership.';await openTask(abaTask);
    const aba=await takePost('start',async()=>{await page.locator('#startRun').focus();await page.keyboard.press('Enter');});
    await page.locator('#taskInput').fill('[SYNTHETIC] Intermediate draft.');await page.locator('#taskInput').fill(abaTask);
    await page.locator('#taskInput').focus();
    const abaTeam=team('lifecycle-draft-aba',abaTask);publish(abaTeam);await release(aba,{ok:true,run:abaTeam.run});await poll();
    await runLink(abaTeam.run.id).waitFor();
    assert.equal(await page.locator('#taskDialog').isVisible(),true,'Draft ABA invalidates automatic dialog close');
    assert.equal(await selectedRun(),'run:lifecycle-a','Draft ABA invalidates automatic selection');
    assert.equal(await page.locator('#taskInput').inputValue(),abaTask);
    assert.equal(await focused('#taskInput'),true,'Late Start preserves the newer editing focus');
    assert.equal(await page.locator('#startRun').isEnabled(),true,'Observed operation frees explicit next Start');
    assert.equal(requests.start.length,2);
    await page.keyboard.press('Escape');
    report.checks.push('lifecycle: keyboard Start plus task draft A → B → A retains the edited dialog, selected team and native textarea focus when the original POST succeeds');

    // Close/reopen with exactly the same content is also a different dialog.
    const reopenTask='[SYNTHETIC] Reopened original draft.';await openTask(reopenTask);
    const reopened=await takePost('start',()=>page.locator('#startRun').click());
    await page.keyboard.press('Escape');await page.locator('#newRun').click();await page.locator('#taskInput').focus();
    assert.equal(await page.locator('#taskInput').inputValue(),reopenTask);
    const reopenedTeam=team('lifecycle-reopened',reopenTask);publish(reopenedTeam);await release(reopened,{ok:true,run:reopenedTeam.run});await poll();
    await runLink(reopenedTeam.run.id).waitFor();
    assert.equal(await page.locator('#taskDialog').isVisible(),true,'A late POST cannot close a reopened modal with identical content');
    assert.equal(await selectedRun(),'run:lifecycle-a');assert.equal(await focused('#taskInput'),true);
    assert.equal(await page.locator('#startRun').isEnabled(),true);
    await page.keyboard.press('Escape');

    // The user returns to the same team, but their newer draft/selection owns UI.
    const navTask='[SYNTHETIC] Selection ABA start.';await openTask(navTask);
    const navigated=await takePost('start',()=>page.locator('#startRun').click());
    await page.keyboard.press('Escape');await select('lifecycle-b');await select('lifecycle-a');
    await page.locator('#messageInput').fill('[SYNTHETIC] Keep selected agent draft.');
    await page.locator('#newRun').click();
    const newerTask='[SYNTHETIC] New draft while old Start is unresolved.';
    await page.locator('#taskInput').fill(newerTask);await page.locator('#taskInput').focus();
    const navTeam=team('lifecycle-navigation',navTask);await release(navigated,{ok:true,run:navTeam.run});await poll();
    await assertPendingStart('Newer dialog while accepted ID is absent',4);
    assert.equal(await page.locator('#taskInput').inputValue(),newerTask);
    assert.match(await page.locator('#runFormStatus').textContent(),/現在の下書きは送信していません/);
    publish(navTeam);await runLink(navTeam.run.id).waitFor();await poll();
    assert.equal(await selectedRun(),'run:lifecycle-a','Run A → B → A does not restore old ownership');
    assert.equal(await page.locator('#taskDialog').isVisible(),true);
    assert.equal(await page.locator('#taskInput').inputValue(),newerTask);
    assert.equal(await focused('#taskInput'),true,'Recovery must not move focus from newer draft');
    assert.equal(await page.locator('#startRun').isEnabled(),true);assert.equal(requests.start.length,4);
    await page.setViewportSize({width:390,height:844});await screenshot('new-draft-recovery-narrow',true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#messageInput').inputValue(),'[SYNTHETIC] Keep selected agent draft.');
    await page.setViewportSize({width:1366,height:768});
    report.checks.push('lifecycle: dismissed/reopened identical dialog and team A → B → A with a newer task draft survive late POST/state recovery; no selection, dialog, draft or focus theft');

    // Failure is retryable only by a new explicit user activation.
    await openTask('[SYNTHETIC] Rejected Start can be explicitly retried.');
    const rejected=await takePost('start',()=>page.locator('#startRun').click());
    const retryTask='[SYNTHETIC] New draft after rejected earlier Start.';
    await page.locator('#taskInput').fill(retryTask);await page.locator('#taskInput').focus();
    await release(rejected,{ok:false,error:'[SYNTHETIC] Delayed Start rejection.'},400);
    await page.locator('#runFormStatus').filter({hasText:'Delayed Start rejection.'}).waitFor();
    assert.equal(await page.locator('#taskInput').inputValue(),retryTask);assert.equal(await focused('#taskInput'),true);
    assert.match(await page.locator('#runFormStatus').textContent(),/現在の下書きは送信していません/);
    assert.equal(await page.locator('#startRun').isEnabled(),true);await poll();assert.equal(requests.start.length,5);
    const retry=await takePost('start',async()=>{await page.locator('#startRun').focus();await page.keyboard.press('Space');});
    assert.equal(retry.payload.task,retryTask,'Explicit retry uses the newer visible draft');
    const retryTeam=team('lifecycle-explicit-retry',retry.payload.task);publish(retryTeam);await release(retry,{ok:true,run:retryTeam.run});
    await page.locator('#taskDialog').waitFor({state:'hidden'});
    await page.locator(`#runList .run-link.selected[data-focus-key="run:${retryTeam.run.id}"]`).waitFor();
    assert.equal(requests.start.length,6);
    report.checks.push('lifecycle: late rejected Start preserves the newer draft/focus and labels it unsent, unlocks after failure, never retries on polling, and a new native Space activation submits that newer draft exactly once');

    await openTask('[SYNTHETIC] Unknown Start response outcome.');
    const unknown=await takePost('start',()=>page.locator('#startRun').click());
    await release(unknown,{ok:false,error:'[SYNTHETIC] Start response unavailable.'},503);
    await page.locator('#runFormStatus').filter({hasText:'開始したかどうかは未確認'}).waitFor();
    assert.equal(await page.locator('#taskInput').inputValue(),unknown.payload.task);
    assert.equal(await selectedRun(),'run:lifecycle-explicit-retry');
    await poll(2);assert.equal(requests.start.length,7,'Uncertain POST outcome never triggers automatic replay');
    assert.equal(await page.locator('#taskDialog').isVisible(),true);await page.keyboard.press('Escape');
    report.checks.push('lifecycle: 503 Start outcome is explicitly unconfirmed, keeps the task draft and current selection, and regular polling never replays its POST');

    // Distinct selected runs may each have one pending Stop. Neither a healthy
    // running snapshot nor another operation's response can erase their guard.
    await select('lifecycle-a');
    const stopA=await takePost('stop',()=>page.locator('#stopRun').click());
    assert.equal(new URL(stopA.url).pathname,'/api/runs/lifecycle-a/stop');
    await page.keyboard.press('Enter');await pointerAttempt('#stopRun');await poll(2);
    assert.equal(await page.locator('#stopRun').isDisabled(),true,'Polling cannot unlock a pending Stop');
    assert.equal(requests.stop.length,1);
    await select('lifecycle-b');assert.equal(await page.locator('#stopRun').isEnabled(),true,'Pending A does not block an eligible B');
    const stopB=await takePost('stop',async()=>{await page.locator('#stopRun').focus();await page.keyboard.press('Enter');});
    assert.equal(new URL(stopB.url).pathname,'/api/runs/lifecycle-b/stop');
    await select('lifecycle-a');assert.equal(await page.locator('#stopRun').isDisabled(),true,'Returning to A retains its pending guard');
    await poll();assert.equal(await page.locator('#stopRun').isDisabled(),true);assert.equal(requests.stop.length,2);
    await select('lifecycle-done');assert.equal(await page.locator('#stopRun').isDisabled(),true);
    await page.locator('#messageInput').fill('[SYNTHETIC] Finished-team draft survives late Stop.');
    const beforeNotice=await page.locator('#globalNotice').textContent();
    await release(stopA,{ok:false,error:'[SYNTHETIC] Delayed Stop A rejection.'},400);await poll();
    assert.equal(await page.locator('#stopRun').isDisabled(),true,'Late A failure cannot enable Stop on completed team');
    assert.equal(await selectedRun(),'run:lifecycle-done');assert.equal(await focused('#messageInput'),true);
    assert.equal(await page.locator('#globalNotice').textContent(),beforeNotice,'Late A failure cannot replace another team notice');
    await pointerAttempt('#stopRun');assert.equal(requests.stop.length,2);
    await select('lifecycle-stopped');setStatus('lifecycle-b','stopped');
    await release(stopB,{ok:true});await poll();
    assert.equal(await page.locator('#stopRun').isDisabled(),true,'Late B success cannot enable Stop on another stopped team');
    assert.equal(await selectedRun(),'run:lifecycle-stopped');
    assert.match(await page.locator('#globalNotice').textContent(),/lifecycle-b.*停止/,'Global late success clearly identifies the affected B team');
    assert.doesNotMatch(await page.locator('#globalNotice').textContent(),/lifecycle-stopped/,'Global success cannot be mistaken for selected stopped team');
    await select('lifecycle-b');assert.equal(await page.locator('#stopRun').isDisabled(),true,'B is stopped after its deferred response');
    await select('lifecycle-a');assert.equal(await page.locator('#stopRun').isEnabled(),true,'Failed A Stop is retryable while A remains active');
    const stopRetry=await takePost('stop',()=>page.locator('#stopRun').click());
    setStatus('lifecycle-a','done');await page.locator('#activeRunStatus').filter({hasText:'完了'}).waitFor();
    assert.equal(await page.locator('#stopRun').isDisabled(),true);
    await release(stopRetry,{ok:false,error:'[SYNTHETIC] Team completed during pending Stop.'},400);
    assert.equal(await page.locator('#stopRun').isDisabled(),true,'Same-owner late failure respects newly completed state');
    await poll();await pointerAttempt('#stopRun');assert.equal(requests.stop.length,3);
    await screenshot('stop-recovery-desktop');
    await page.setViewportSize({width:390,height:844});await screenshot('stop-recovery-narrow');
    report.checks.push('lifecycle: duplicate pointer/keyboard Stop blocked across polls; independent pending guards for A/B; late success/failure cannot enable completed/stopped selections or take focus/drafts; notices name their target and older failures cannot overwrite a newer operation; explicit retry still respects a team completing while response is pending; desktop/narrow screenshots');
    assert.equal(pending.size,0,'Every deferred lifecycle response was settled');
  } finally {
    // Only remove this phase's handlers. The parent removes its original mocks
    // separately before its existing real HTTP + injected Engine acceptance.
    for(const entry of pending)await entry.route.abort('aborted').catch(()=>{});
    await page.unroute('**/api/state*',stateRoute);await page.unroute('**/api/runs',startRoute);await page.unroute('**/api/runs/*/stop',stopRoute);
  }
}

module.exports={lifecycleAcceptance};
