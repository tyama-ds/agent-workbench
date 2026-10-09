/* Fresh Workbench UI acceptance: real loopback server, simulated team, no inference. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {spawn,spawnSync} = require('node:child_process');
const {chromium} = require('node:module').createRequire(path.join(__dirname,'browser-tests','package.json'))('playwright');
const {retainedRedactionAcceptance} = require('./browser-tests/redaction_acceptance.cjs');
const {lifecycleAcceptance} = require('./browser-tests/lifecycle_acceptance.cjs');
const {credentialRecoveryAcceptance} = require('./browser-tests/credential_recovery_acceptance.cjs');
const {firstTaskAcceptance} = require('./browser-tests/first_task_acceptance.cjs');
const {retentionAcceptance} = require('./browser-tests/retention_acceptance.cjs');
const {disclosureFocusAcceptance} = require('./browser-tests/disclosure_focus_acceptance.cjs');
const {settingsSaveAcceptance} = require('./browser-tests/settings_save_acceptance.cjs');
const {dataUseAcceptance} = require('./browser-tests/data_use_acceptance.cjs');
const {allQuestionsAcceptance} = require('./browser-tests/questions_acceptance.cjs');
const {taskReuseAcceptance} = require('./browser-tests/task_reuse_acceptance.cjs');
const {inputPresenceAcceptance} = require('./browser-tests/input_presence_acceptance.cjs');
const {messageReceiptAcceptance} = require('./browser-tests/message_receipt_acceptance.cjs');
const {contextCompactionAcceptance} = require('./browser-tests/context_compaction_acceptance.cjs');

async function assertLayout(page,label) {
  const metrics=await page.evaluate(()=>{
    const rect=selector=>document.querySelector(selector).getBoundingClientRect().toJSON();
    return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
      sidebar:rect('.sidebar'),main:rect('main'),panel:rect('.conversation-panel'),
      send:rect('#sendMessage'),input:rect('#messageInput')};
  });
  assert(metrics.scrollWidth<=metrics.width,label+': document horizontal overflow');
  if(metrics.width<=600)assert(metrics.sidebar.bottom<=metrics.main.top+1,label+': sidebar overlaps workspace');
  for(const [name,box] of [['send',metrics.send],['input',metrics.input]]) {
    assert(box.width>0&&box.height>0,label+': '+name+' has no usable area');
    assert(box.bottom<=metrics.panel.bottom+1&&box.right<=metrics.panel.right+1&&box.left>=metrics.panel.left-1,
      label+': '+name+' clipped by conversation panel');
    if(metrics.width>600)assert(box.bottom<=metrics.main.bottom+1&&box.right<=metrics.main.right+1&&box.left>=metrics.main.left-1,
      label+': '+name+' clipped by workspace ancestor');
  }
}

// Await the actual preview for the edited form, rather than a prior debounced request.
async function preflightAfter(page,action,matches) {
  const responsePromise=page.waitForResponse(response=>response.url().endsWith('/api/run-preflight')&&
    response.request().method()==='POST'&&matches(response.request().postDataJSON()));
  await action();const response=await responsePromise;assert.equal(response.status(),200);
  const result=await response.json();
  assert.equal(result.inference_tested,false);assert.equal(result.tools_tested,false);
  await page.locator('#preflightStatus').filter({hasText:result.can_start?'開始に必要な設定を確認しました':'開始前に修正が必要です'}).waitFor();
  await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
  return result;
}

// Keep one response pending until the test deliberately changes or closes its UI.
async function holdNextRequest(page,pattern,action) {
  let captured;const pending=new Promise(resolve=>{captured=resolve;});
  await page.route(pattern,route=>captured(route),{times:1});
  const requested=page.waitForRequest(pattern);await action();await requested;
  return pending;
}
async function releaseResponse(page,route,body) {
  const responded=page.waitForResponse(response=>response.request()===route.request());
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  await (await responded).finished();
  // Let the fetch JSON continuation and the next UI paint finish before asserting absence.
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
}
async function assertDialogLayout(page,id,label) {
  const size=await page.locator(id).evaluate(dialog=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
    clientWidth:dialog.clientWidth,contentWidth:dialog.scrollWidth,left:dialog.getBoundingClientRect().left,right:dialog.getBoundingClientRect().right}));
  assert(size.scrollWidth<=size.width,label+': document horizontal overflow');
  assert(size.contentWidth<=size.clientWidth+1,label+': dialog horizontal overflow');
  assert(size.left>=0&&size.right<=size.width+1,label+': dialog clipped horizontally');
}

async function main() {
  const root=path.resolve(__dirname,'..'),sandbox=fs.mkdtempSync(path.join(os.tmpdir(),'workbench-ui-'));
  const workspace=path.join(sandbox,'project'),stateDir=path.join(sandbox,'state');
  fs.mkdirSync(workspace);fs.mkdirSync(path.join(workspace,'private'));
  const artifacts=path.join(root,'runtime','verification');fs.mkdirSync(artifacts,{recursive:true});
  const python=process.env.WORKBENCH_TEST_PYTHON||path.join(root,'.venv',process.platform==='win32'?'Scripts':'bin',process.platform==='win32'?'python.exe':'python');
  const contractResult=spawnSync(python,['-m','tools.browser_fixture','--agent-contract'],{cwd:root,encoding:'utf8'});
  assert.equal(contractResult.status,0,contractResult.stderr);
  const agentContract=JSON.parse(contractResult.stdout);
  const redactionResult=spawnSync(python,['-m','tools.browser_fixture','--redaction-contract'],{cwd:root,encoding:'utf8'});
  assert.equal(redactionResult.status,0,redactionResult.stderr);
  const redactionCases=JSON.parse(redactionResult.stdout);
  const credentialResult=spawnSync(python,['-m','tools.browser_fixture','--credential-contract'],{cwd:root,encoding:'utf8'});
  assert.equal(credentialResult.status,0,credentialResult.stderr);
  const credentialScenario=JSON.parse(credentialResult.stdout);
  const providerRequests=[],report={schemaVersion:1,fixture:'SYNTHETIC: no inference or user data',commit:process.env.GITHUB_SHA||null,runId:process.env.GITHUB_RUN_ID||null,checks:[],pageErrors:[],externalRequests:[],cspErrors:[]};
  const provider=http.createServer((request,response)=>{
    providerRequests.push({method:request.method,path:request.url});
    response.writeHead(request.url==='/v1/models'?200:400,{'Content-Type':'application/json'});
    response.end(JSON.stringify(request.url==='/v1/models'?{data:[{id:'fixture-local-model'}]}:{error:'No inference endpoint in this test'}));
  });
  await new Promise(resolve=>provider.listen(0,'127.0.0.1',resolve));
  const providerUrl=`http://127.0.0.1:${provider.address().port}/v1`;
  const server=spawn(python,['-m','tools.browser_fixture','--state-dir',stateDir],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe'],
    env:{...process.env,[redactionCases.environment.old_env]:redactionCases.environment.old,
      [redactionCases.environment.new_env]:redactionCases.environment.new}});
  let stdout='',stderr='',browser,page,context;
  server.stdout.on('data',chunk=>{stdout+=chunk;});server.stderr.on('data',chunk=>{stderr+=chunk;});
  try {
    const deadline=Date.now()+25000;let launch;
    while(!(launch=stdout.match(/http:\/\/127\.0\.0\.1:\d+\/#token=[A-Za-z0-9_-]+/)?.[0])){
      if(Date.now()>deadline||server.exitCode!==null)throw new Error('Fixture server did not start: '+stderr);
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    const origin=new URL(launch).origin;
    browser=await chromium.launch({headless:true,...(process.env.WORKBENCH_BROWSER_EXECUTABLE?{executablePath:process.env.WORKBENCH_BROWSER_EXECUTABLE}:process.platform==='win32'?{channel:'msedge'}:{})});
    report.browserVersion=browser.version();report.platform=process.platform;
    context=await browser.newContext({viewport:{width:1366,height:768},reducedMotion:'reduce',locale:'ja-JP',timezoneId:'UTC'});
    await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort('blockedbyclient'));
    page=await context.newPage();page.setDefaultTimeout(10000);
    page.on('pageerror',error=>report.pageErrors.push(error.message));
    page.on('console',message=>{if(/Content Security Policy|violates.*directive/i.test(message.text()))report.cspErrors.push(message.text());});
    page.on('request',request=>{const url=new URL(request.url());if(url.protocol.startsWith('http')&&url.origin!==origin)report.externalRequests.push(url.origin+url.pathname);});
    await page.goto(launch);await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    assert.equal(new URL(page.url()).hash,'');
    assert.equal(await page.locator('#startRun').isDisabled(),true);
    report.checks.push('real one-use bootstrap, cookie session, fragment removal, same-origin assets');
    await page.screenshot({path:path.join(artifacts,'workbench-empty.png'),fullPage:true,animations:'disabled'});
    await page.locator('#newRun').click();
    assert.equal(await page.locator('#taskDialog').evaluate(dialog=>dialog.contains(document.activeElement)),true,'Opening a native modal moves focus inside');
    await page.locator('#taskInput').focus();
    await page.keyboard.press('Shift+Tab');assert.equal(await page.locator('#taskDialog').evaluate(dialog=>dialog.contains(document.activeElement)),true);
    await page.keyboard.press('Tab');
    await page.locator('#newRun').evaluate(button=>button.focus());
    assert.equal(await page.locator('#taskDialog').evaluate(dialog=>dialog.contains(document.activeElement)),true,'Modal background must stay inert');
    const firstTask=await firstTaskAcceptance({page,stateDir,providerRequests,artifacts,report,assertDialogLayout});
    const incomplete=await preflightAfter(page,()=>page.locator('#taskInput').fill('閉じても残る下書き'),data=>data.task==='閉じても残る下書き');
    assert.equal(incomplete.can_start,false);assert.equal(incomplete.blockers.length>0,true);
    assert.deepEqual(providerRequests,[],'Opening preflight cannot probe any provider');
    await firstTask.capture('閉じても残る下書き');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#newRun').evaluate(button=>button===document.activeElement),true);
    assert.equal(await page.locator('#taskDialog').isVisible(),false);await page.locator('#newRun').click();assert.equal(await page.locator('#taskInput').inputValue(),'閉じても残る下書き');
    await firstTask.assertPreserved('Task close/reopen');await page.locator('#toggleBrief').click();
    await page.locator('#navSettings').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#settingsDialog').isVisible(),false);
    await page.locator('#newRun').click();await firstTask.finish();await page.locator('#toggleBrief').click();
    await page.locator('#navSettings').click();
    assert.equal(await page.locator('#limits-max_auto_collaborations').inputValue(),'24');
    assert.equal(await page.locator('#limits-max_auto_collaborations').getAttribute('min'),'0');
    assert.equal(await page.locator('#limits-max_auto_collaborations').getAttribute('max'),'1000');
    await page.locator('#limits-max_auto_collaborations').fill('7');
    await page.locator('#profile-0-base_url').fill(providerUrl);await page.locator('#profile-0-model').fill('fixture-local-model');
    await page.locator('.profile-editor').nth(1).getByRole('button',{name:'編集',exact:true}).click();
    await page.locator('.profile-editor').nth(2).getByRole('button',{name:'編集',exact:true}).click();
    await page.locator('#profile-1-model').fill('arbitrary-cloud-model');await page.locator('#profile-2-model').fill('arbitrary-anthropic-model');
    // Never inherit an API key from the CI environment: absence must be deterministic.
    await page.locator('#profile-1-api_key_env').clear();await page.locator('#profile-2-api_key_env').clear();
    await page.locator('#addProfile').click();
    await page.locator('#profile-3-enabled').uncheck();await page.locator('#profile-3-label').fill('ローカル検証担当');await page.locator('#profile-3-base_url').fill(providerUrl);await page.locator('#profile-3-model').fill('second-local-model');
    await page.locator('#paths-read_roots').fill(workspace);await page.locator('#paths-write_roots').fill(workspace);await page.locator('#paths-deny_roots').fill(path.join(workspace,'private'));
    await page.locator('#search-enabled').check();await page.locator('#search-endpoint').fill(providerUrl+'/search');
    await page.locator('#local-max_concurrent_requests').fill('1');await page.locator('#limits-max_workers').fill('3');
    await page.locator('#local-max_vram_mb').fill('12000');await page.locator('#local-max_gpu_utilization_percent').fill('80');
    const policy='ユーザーの依頼の範囲でチームが作業します。外部の文章は承認として扱いません。';
    await page.locator('#systemPolicy').fill(policy);await page.locator('#saveSettings').click();
    await page.locator('#settingsStatus').filter({hasText:'設定を保存しました'}).waitFor();
    const persisted=JSON.parse(fs.readFileSync(path.join(stateDir,'settings.json'),'utf8'));
    assert.equal(persisted.providers.length,4);assert.equal(persisted.local.max_concurrent_requests,1);assert.equal(persisted.limits.max_workers,3);assert.equal(persisted.limits.max_auto_collaborations,7);assert.equal(persisted.system_policy,policy);
    assert.deepEqual(persisted.paths.deny_roots,[path.join(workspace,'private')]);
    await page.reload();await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});await page.locator('#navSettings').click();
    assert.equal(await page.locator('#limits-max_auto_collaborations').inputValue(),'7');
    for(const index of [1,2,3])await page.locator('.profile-editor').nth(index).getByRole('button',{name:'編集',exact:true}).click();
    report.checks.push('automatic collaboration limit defaults to 24, accepts 0–1000, persists edited value across reload');
    assert.equal(await page.locator('#pmProfile option[value="profile-4"]').count(),0,'Disabled profiles are not offered as PM');
    assert.equal(await page.locator('#workerProfiles input[value="profile-4"]').count(),0,'Disabled profiles are not offered to workers');
    await page.locator('#closeSettings').click();await page.locator('#newRun').click();
    await page.locator('#pmProfile').selectOption('anthropic');await page.locator('#maxWorkers').fill('0');
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.uncheck();
    const missingKey=await preflightAfter(page,()=>page.locator('#taskInput').fill('[SYNTHETIC] Missing cloud key.'),data=>data.task==='[SYNTHETIC] Missing cloud key.');
    assert.equal(missingKey.can_start,false);assert.equal(missingKey.blockers[0].code,'key_missing');assert.match(missingKey.blockers[0].message,/API キーが未設定/);
    const rejectedStart=page.waitForResponse(response=>response.url().endsWith('/api/runs')&&response.request().method()==='POST');
    await page.locator('#startRun').click();const rejected=await rejectedStart;assert.equal(rejected.status(),400);
    assert.equal((await rejected.json()).error,missingKey.blockers[0].message,'Preview and actual admission reject the same missing key');
    await page.locator('#runFormStatus').filter({hasText:'API キーが未設定'}).waitFor();
    assert.equal(await page.locator('#runList .run-link').count(),0);assert.deepEqual(providerRequests,[]);
    await page.locator('#preflightSettings').click();assert.equal(await page.locator('#taskDialog').isVisible(),false);
    assert.equal(await page.locator('#settingsDialog').isVisible(),true);
    assert.equal(await page.locator('#taskInput').inputValue(),'[SYNTHETIC] Missing cloud key.');
    report.checks.push('real preflight blocks incomplete selection and a deterministic missing cloud key; disabled profiles are excluded; start rechecks the same blocker; settings shortcut retains task draft; no provider traffic');
    await page.locator('#profile-1-secret').fill('fixture-memory-secret');
    await page.locator('.profile-editor').nth(1).getByRole('button',{name:'キーをセット',exact:true}).click();
    await page.locator('.profile-editor').nth(1).locator('.inline-status').filter({hasText:'キーをセットしました'}).waitFor();
    assert.equal(await page.locator('#profile-1-secret').inputValue(),'');
    assert(!fs.readFileSync(path.join(stateDir,'settings.json'),'utf8').includes('fixture-memory-secret'));
    await page.locator('.profile-editor').nth(0).getByRole('button',{name:'モデル一覧を確認',exact:true}).click();
    await page.locator('.profile-editor').nth(0).locator('.inline-status').filter({hasText:'fixture-local-model'}).waitFor();
    assert.deepEqual(providerRequests,[{method:'GET',path:'/v1/models'}]);
    report.checks.push('real config persistence, four arbitrary model profiles, file scopes, separate local slots, memory-only key, models-only connection test');
    const localCard=page.locator('.profile-editor').nth(0),localProbe=localCard.getByRole('button',{name:'モデル一覧を確認',exact:true});
    const probeResult=localCard.locator('[data-probe-result]');
    assert.match(await probeResult.textContent(),/指定モデルが一覧にあります/);
    assert.match(await probeResult.textContent(),/推論・ツール動作は未確認/);
    const delayedProbe={ok:true,models:['STALE-PROVIDER-SUCCESS'],selected_model:'observed',list_incomplete:false};
    const editProbe=await holdNextRequest(page,'**/api/provider-test',()=>localProbe.click());
    await page.locator('#profile-0-model').fill('manual-unlisted-alias');
    await releaseResponse(page,editProbe,delayedProbe);
    assert.match(await probeResult.textContent(),/設定または画面が変わりました/);
    assert.doesNotMatch(await probeResult.textContent(),/STALE-PROVIDER-SUCCESS|モデル一覧を取得しました/);
    await localProbe.click();await probeResult.filter({hasText:'設定を保存してください'}).waitFor();
    assert.deepEqual(providerRequests,[{method:'GET',path:'/v1/models'}],'Dirty settings cannot trigger provider network');
    await page.locator('#closeSettings').click();await page.locator('#newRun').click();await page.locator('#pmProfile').selectOption('local');
    const savedOnly=await preflightAfter(page,()=>page.locator('#taskInput').fill('[SYNTHETIC] Unsaved edit preview.'),data=>data.task==='[SYNTHETIC] Unsaved edit preview.');
    assert.equal(savedOnly.can_start,true);assert.equal(savedOnly.destinations[0].model,'fixture-local-model');
    assert.match(await page.locator('#preflightStatus').textContent(),/未保存の変更は含みません/);
    await page.keyboard.press('Escape');await page.locator('#navSettings').click();
    assert.equal(await page.locator('#profile-0-model').inputValue(),'manual-unlisted-alias','Preview leaves unsaved settings intact');
    await page.locator('#saveSettings').click();await page.locator('#settingsStatus').filter({hasText:'設定を保存しました'}).waitFor();
    await localProbe.click();await probeResult.filter({hasText:'手入力の別名も使用できます'}).waitFor();
    assert.match(await probeResult.textContent(),/利用可否は一覧だけでは判断できません/);
    assert.equal(await page.locator('#profile-0-model').inputValue(),'manual-unlisted-alias','Listing cannot replace a manual model alias');
    const closeProbe=await holdNextRequest(page,'**/api/provider-test',()=>localProbe.click());
    await page.keyboard.press('Escape');await page.locator('#navSettings').click();
    await releaseResponse(page,closeProbe,delayedProbe);
    assert.match(await probeResult.textContent(),/設定または画面が変わりました/);
    assert.doesNotMatch(await probeResult.textContent(),/STALE-PROVIDER-SUCCESS|モデル一覧を取得しました/);
    report.checks.push('models-only diagnostics identify observed versus unlisted manual aliases, never replace the model, refuse unsaved edits, preview only saved configuration, and ignore delayed success after settings edits or close/reopen');

    await page.locator('#closeSettings').click();await page.locator('#newRun').click();
    await page.locator('#pmProfile').selectOption('local');await page.locator('#maxWorkers').fill('1');
    await page.locator('#workerProfiles input[value="local"]').check();await page.locator('#workerProfiles input[value="openai"]').check();
    const configuredGuidance=await firstTaskAcceptance({page,stateDir,providerRequests,artifacts,report,assertDialogLayout,phase:'configured'});
    const ready=await preflightAfter(page,()=>page.locator('#taskInput').fill('[SYNTHETIC] Preflight overview.'),data=>data.task==='[SYNTHETIC] Preflight overview.');
    assert.equal(ready.can_start,true);assert.equal(ready.destinations.length,2);
    assert.equal(ready.destinations.find(item=>item.profile_id==='local').model,'manual-unlisted-alias');
    assert.equal(ready.destinations.find(item=>item.profile_id==='local').endpoint,providerUrl+'/chat/completions');
    assert.equal(ready.destinations.find(item=>item.profile_id==='openai').protocol,'/responses');
    assert(ready.scope.deny_roots.includes(fs.realpathSync.native(path.join(workspace,'private'))));
    assert(ready.scope.deny_roots.includes(fs.realpathSync.native(stateDir)));
    assert.equal(ready.web.search_endpoint,providerUrl+'/search');
    assert.match(await page.locator('#preflightStatus').textContent(),/外部通信・推論テストは行っていません/);
    assert.match(await page.locator('#preflightDetails').textContent(),/実際の呼び出し記録ではありません/);
    assert.doesNotMatch(await page.locator('#preflightDetails').textContent(),/fixture-memory-secret/);
    assert.equal(await page.locator('#preflightStatus').getAttribute('aria-busy'),'false');
    await configuredGuidance.assertDraft('[SYNTHETIC] Preflight overview.');
    await dataUseAcceptance({page,stateDir,providerRequests,artifacts,report,assertDialogLayout,preflightAfter});
    let redundantPreflights=0;
    const countBlurPreflights=request=>{if(request.url().endsWith('/api/run-preflight'))redundantPreflights++;};
    page.on('request',countBlurPreflights);
    // Clicking the disclosure blurs the edited textarea. Its duplicate change
    // event must neither refetch nor rebuild and close the disclosure.
    await page.locator('.readiness-scope summary').click();
    assert.equal(await page.locator('.readiness-scope').evaluate(scope=>scope.open),true);
    await page.waitForTimeout(250);page.off('request',countBlurPreflights);
    assert.equal(redundantPreflights,0,'Unchanged textarea blur cannot restart preflight');
    assert.equal(await page.locator('#preflightStatus').getAttribute('aria-busy'),'false');
    assert.equal(await page.locator('.readiness-scope').evaluate(scope=>scope.open),true,'Expanded folder scope survives textarea blur');
    await page.keyboard.press('Escape');
    await preflightAfter(page,()=>page.locator('#newRun').click(),data=>data.task==='[SYNTHETIC] Preflight overview.');
    await configuredGuidance.assertPreserved('Configured task close/reopen');
    await page.locator('#preflightSettings').click();
    assert.equal(await page.locator('#taskDialog').isVisible(),false);assert.equal(await page.locator('#settingsDialog').isVisible(),true);
    await page.locator('#closeSettings').click();
    await preflightAfter(page,()=>page.locator('#newRun').click(),data=>data.task==='[SYNTHETIC] Preflight overview.');
    await configuredGuidance.finish();
    assert.equal(await page.locator('.readiness-scope').evaluate(scope=>scope.open),true,'Guidance/settings round trip preserves the existing expanded readiness scope');
    await assertDialogLayout(page,'#taskDialog','desktop readiness');
    await page.locator('.readiness-scope').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(artifacts,'workbench-readiness-desktop.png'),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});await assertDialogLayout(page,'#taskDialog','narrow readiness');
    assert.equal(await page.locator('#preflightStatus').getAttribute('aria-busy'),'false');
    assert.equal(await page.locator('.readiness-scope').evaluate(scope=>scope.open),true);
    await page.locator('.readiness-scope').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(artifacts,'workbench-readiness-narrow.png'),fullPage:true,animations:'disabled'});
    // Exercise actual pointer and keyboard activation while preview responses
    // remain pending. Reject only the start response so no extra engine run is made.
    const pendingPreviewStarts=[];
    const rejectPendingStart=async route=>{pendingPreviewStarts.push(route.request().postDataJSON());await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({ok:false,error:'[SYNTHETIC] Start received while preview pending.'})});};
    await page.route('**/api/runs',rejectPendingStart);
    const pointerStartResponse=page.waitForResponse(response=>response.url().endsWith('/api/runs')&&response.request().method()==='POST');
    const pointerPreview=await holdNextRequest(page,'**/api/run-preflight',async()=>{
      await page.locator('#taskInput').fill('[SYNTHETIC] Immediate pointer start.');
      await page.locator('#startRun').click();
    });
    assert.equal((await pointerStartResponse).status(),400);
    await page.locator('#runFormStatus').filter({hasText:'Start received while preview pending.'}).waitFor();
    assert.equal(await page.locator('#preflightStatus').getAttribute('aria-busy'),'true');
    assert.equal(pendingPreviewStarts.length,1);assert.equal(pendingPreviewStarts[0].task,'[SYNTHETIC] Immediate pointer start.');
    assert.equal(await page.locator('.readiness-scope').evaluate(scope=>scope.open),true,'Pending preview retains expanded scope');
    await releaseResponse(page,pointerPreview,ready);await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    assert.equal(pendingPreviewStarts.length,1,'Late preview cannot submit another run');
    assert.equal(await page.locator('.readiness-scope').evaluate(scope=>scope.open),true,'Refreshed preview retains expanded scope');
    const keyboardStartResponse=page.waitForResponse(response=>response.url().endsWith('/api/runs')&&response.request().method()==='POST');
    const keyboardPreview=await holdNextRequest(page,'**/api/run-preflight',async()=>{
      await page.locator('#taskInput').fill('[SYNTHETIC] Keyboard start.');
      await page.locator('#startRun').focus();await page.keyboard.press('Enter');
    });
    assert.equal((await keyboardStartResponse).status(),400);
    await page.locator('#runFormStatus').filter({hasText:'Start received while preview pending.'}).waitFor();
    assert.equal(pendingPreviewStarts.length,2);assert.equal(pendingPreviewStarts[1].task,'[SYNTHETIC] Keyboard start.');
    await releaseResponse(page,keyboardPreview,ready);await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    assert.equal(pendingPreviewStarts.length,2,'Late preview cannot repeat keyboard submission');
    const changingPreview=await holdNextRequest(page,'**/api/run-preflight',()=>page.locator('#taskInput').fill('[SYNTHETIC] Preview arrives during pointer gesture.'));
    await page.locator('#startRun').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('#startRun').isEnabled(),true);
    const startBox=await page.locator('#startRun').boundingBox();assert(startBox);
    await page.mouse.move(startBox.x+startBox.width/2,startBox.y+startBox.height/2);
    await page.mouse.down();
    const heldStartBox=await page.locator('#startRun').boundingBox();assert(heldStartBox);
    const tallPreview={...ready,warnings:[{code:'synthetic_changed_height',message:'[SYNTHETIC] Changed-height preview details. '.repeat(30)}]};
    await releaseResponse(page,changingPreview,tallPreview);
    const pendingStartBox=await page.locator('#startRun').boundingBox();assert(pendingStartBox);
    for(const key of ['x','y','width','height'])assert(Math.abs(pendingStartBox[key]-heldStartBox[key])<=1,'Preview must not move Start during pointer gesture: '+key);
    assert.doesNotMatch(await page.locator('#preflightStatus').textContent(),/Changed-height preview details/,'Changed-height rendering waits until the pointer gesture ends');
    assert.equal(pendingPreviewStarts.length,2,'Preview completion cannot itself start a run');
    const gestureStartResponse=page.waitForResponse(response=>response.url().endsWith('/api/runs')&&response.request().method()==='POST');
    await page.mouse.up();assert.equal((await gestureStartResponse).status(),400);
    await page.locator('#runFormStatus').filter({hasText:'Start received while preview pending.'}).waitFor();
    await page.locator('#preflightStatus').filter({hasText:'Changed-height preview details.'}).waitFor();
    await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    assert.equal(pendingPreviewStarts.length,3,'One native pointer gesture produces exactly one explicit start');
    assert.equal(pendingPreviewStarts[2].task,'[SYNTHETIC] Preview arrives during pointer gesture.');
    assert.equal(await page.locator('#runList .run-link').count(),0);
    const cancelledPreview=await holdNextRequest(page,'**/api/run-preflight',()=>page.locator('#taskInput').fill('[SYNTHETIC] Cancel held start.'));
    await page.locator('#startRun').scrollIntoViewIfNeeded();const cancelBox=await page.locator('#startRun').boundingBox();assert(cancelBox);
    await page.mouse.move(cancelBox.x+cancelBox.width/2,cancelBox.y+cancelBox.height/2);await page.mouse.down();
    await page.keyboard.press('Escape');assert.equal(await page.locator('#taskDialog').isVisible(),false);
    await page.mouse.up();await releaseResponse(page,cancelledPreview,tallPreview);
    assert.equal(await page.locator('#taskDialog').isVisible(),false,'A late preview cannot reopen a dismissed task');
    assert.equal(pendingPreviewStarts.length,3,'Cancelling a held pointer gesture cannot submit');
    await preflightAfter(page,()=>page.locator('#newRun').click(),data=>data.task==='[SYNTHETIC] Cancel held start.');
    report.checks.push('narrow Start works immediately after typing and by keyboard while preflight is delayed; blur does not refetch or collapse scope; actual refresh preserves expanded scope; changed-height responses cannot move Start between mouse-down/up; late previews never start extra runs');
    await page.setViewportSize({width:1366,height:768});
    const stalePreflight={...ready,warnings:[{code:'synthetic_stale',message:'STALE-PREFLIGHT-SUCCESS'}]};
    const olderPreflight=await holdNextRequest(page,'**/api/run-preflight',()=>page.locator('#taskInput').fill('[SYNTHETIC] Older selection.'));
    await preflightAfter(page,()=>page.locator('#pmProfile').selectOption('anthropic'),data=>data.pm_profile==='anthropic');
    await releaseResponse(page,olderPreflight,stalePreflight);
    assert.match(await page.locator('#preflightStatus').textContent(),/API キーが未設定/);
    assert.doesNotMatch(await page.locator('#preflightStatus').textContent(),/STALE-PREFLIGHT-SUCCESS|開始に必要な設定を確認しました/);
    const closingPreflight=await holdNextRequest(page,'**/api/run-preflight',()=>page.locator('#taskInput').fill('[SYNTHETIC] Closing preview.'));
    await page.keyboard.press('Escape');
    await preflightAfter(page,()=>page.locator('#newRun').click(),data=>data.task==='[SYNTHETIC] Closing preview.');
    await releaseResponse(page,closingPreflight,stalePreflight);
    assert.match(await page.locator('#preflightStatus').textContent(),/API キーが未設定/);
    assert.doesNotMatch(await page.locator('#preflightStatus').textContent(),/STALE-PREFLIGHT-SUCCESS|開始に必要な設定を確認しました/);
    assert.equal(pendingPreviewStarts.length,3,'Stale selection and dismissed/reopened preview responses cannot add starts');
    await page.unroute('**/api/runs',rejectPendingStart);
    await page.keyboard.press('Escape');await page.locator('#navSettings').click();
    assert.deepEqual(providerRequests,[{method:'GET',path:'/v1/models'},{method:'GET',path:'/v1/models'}]);
    report.checks.push('real admission preview shows saved model/protocol destinations, protected folders, web exposure and untested capability limits without provider calls; old selection and closed/reopened dialog responses cannot overwrite newer blockers; desktop/narrow screenshots');
    for(const index of [1,2,3])await page.locator('.profile-editor').nth(index).getByRole('button',{name:'閉じる',exact:true}).click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.locator('#settingsDialog').evaluate(dialog=>{dialog.scrollTop=0;});
    await page.screenshot({path:path.join(artifacts,'workbench-settings.png'),fullPage:true,animations:'disabled'});

    const sentRuns=[],sentMessages=[],stopped=[];let messageDelay=300,messageFailure=false;
    const fixture={runs:[],agents:[],events:[],resources:{active:1,queued:1,gpu_readings:[{index:0,used_mb:7168,total_mb:24576,utilization_percent:35}]}};
    const compactFixture=request=>{
      const query=new URL(request.url()).searchParams;
      if(query.get('view')!=='selected')return structuredClone(fixture);
      const runId=query.get('run_id'),agentId=query.get('agent_id');
      return {...structuredClone(fixture),agents:fixture.agents.map(agent=>{
        const value=structuredClone(agent);if(agent.id!==agentId)for(const key of ['logs','results','output_receipts'])delete value[key];return value;
      }),events:fixture.events.filter(event=>event.run_id===runId).slice(-100),selection:{run_id:runId,agent_id:agentId,detail_loaded:Boolean(agentId)}};
    };
    await page.route('**/api/state*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(compactFixture(route.request()))}));
    await page.route('**/api/runs',async route=>{
      const data=route.request().postDataJSON();sentRuns.push(data);const at=1791169200;
      const run={id:'fixture-run',...data,status:'running',created_at:at,model_calls:4,tool_calls:6,auto_collaborations:3,max_auto_collaborations:7,collaboration_limit_reached:false,agent_ids:['fixture-pm','fixture-worker-1','fixture-worker-2']};fixture.runs=[run];
      fixture.agents=[
        {id:'fixture-pm',run_id:run.id,name:'PM',role:'pm',profile_id:'local',status:'waiting',assignment:data.task,question:'更新した社内FAQを共有する前に、確認対象のチームを指定してください。',turns:2,logs:[{id:1,kind:'assistant',text:'作業を2つに分けました。検索案の整理と、記載内容の確認を並行して進めています。',thinking:'参照する資料と、確認すべき観点を整理しています。',at}]},
        {id:'fixture-worker-1',run_id:run.id,name:'資料・検索担当',role:'worker',profile_id:'openai',parent_id:'fixture-pm',status:'working',assignment:'[SYNTHETIC] Unique assignment search phrase',turns:3,logs:[{id:2,kind:'assistant',text:'資料を確認し、検索案をまとめています。',at}]},
        {id:'fixture-worker-2',run_id:run.id,name:'レビュー担当',role:'worker',profile_id:'local',parent_id:'fixture-pm',status:'done',assignment:'[SYNTHETIC] Review sources',turns:2,logs:[{id:3,kind:'assistant',text:'確認を完了しました。結果をPMへ送信しました。',at}]},
      ];
      for(const agent of fixture.agents){
        for(const key of Object.keys(agent))assert(Object.hasOwn(agentContract,key),'Fixture drift: '+key);
        Object.assign(agent,{...agentContract,...agent,message_eligibility:{allowed:true,reason:'',message:''},status_reason:agent.question?'human_input':agent.status});
        agent.configured_profile={id:agent.profile_id,label:'[SYNTHETIC] '+agent.profile_id,kind:agent.profile_id,model:'[SYNTHETIC] configured-'+agent.profile_id};
        agent.name='[SYNTHETIC] '+agent.name;
      }
      fixture.events=[{id:1,run_id:run.id,kind:'spawn',text:'PM が2人の作業者に担当を割り当てました。',at},{id:2,run_id:run.id,kind:'mail',from:'レビュー担当',to:'PM',text:'確認結果を共有します。参照先の変更は1件です。',at},{id:3,run_id:run.id,kind:'mail',from:'資料・検索担当',to:'PM',text:'<img src=x onerror="window.fixtureInjected=true">',at}];
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,run})});
    });
    await page.route('**/api/agents/*/message',async route=>{
      const data=route.request().postDataJSON();sentMessages.push(data);
      if(messageFailure){await new Promise(resolve=>setTimeout(resolve,messageDelay));await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({ok:false,error:'[SYNTHETIC] Delayed rejected send'})});return;}
      fixture.agents[0].question='';fixture.agents[0].status='working';fixture.agents[0].status_reason='working';fixture.agents[0].logs.push({id:4,kind:'user',text:data.text,at:Date.now()/1000});
      await new Promise(resolve=>setTimeout(resolve,messageDelay));await route.fulfill({status:200,contentType:'application/json',body:'{"ok":true}'});
    });
    await page.route('**/api/runs/*/stop',async route=>{stopped.push(route.request().url());fixture.runs[0].status='stopped';fixture.runs[0].status_reason='stopped';fixture.agents.forEach(agent=>{agent.status='stopped';agent.status_reason='stopped';});await route.fulfill({status:200,contentType:'application/json',body:'{"ok":true}'});});
    await page.locator('#closeSettings').click();await page.locator('#newRun').click();await page.locator('#pmProfile').selectOption('local');
    await page.locator('#workerProfiles input[value="openai"]').check();await page.locator('#maxWorkers').fill('2');
    const task='  [SYNTHETIC] 社内FAQを整理し、検索案と検証結果をまとめてください。\n共有の前に対象チームを確認してください。  ';
    await page.locator('#taskInput').fill(task);await page.locator('#startRun').click();
    await page.locator('#humanQuestion').waitFor({state:'visible'});
    assert.deepEqual(sentRuns,[{task,pm_profile:'local',worker_profiles:['local','openai'],max_workers:2}]);
    assert.equal(await page.locator('.agent-card').count(),3);
    assert.equal(await page.locator('#agentTabs button').count(),3);assert.equal(await page.locator('#teamMap button').count(),3);
    await page.locator('#needsYou').click();assert.equal(await page.locator('.agent-card').count(),1);await page.locator('#needsYou').click();
    await page.locator('#agentSearch').fill('レビュー');assert.equal(await page.locator('.agent-card').count(),1);await page.locator('#agentSearch').clear();
    await page.locator('#agentSearch').fill('Unique assignment search phrase');assert.equal(await page.locator('.agent-card').count(),1);await page.locator('#agentSearch').clear();
    await page.locator('#agentCards [data-agent-id="fixture-pm"]').focus();await page.waitForTimeout(1300);assert.equal(await page.evaluate(()=>document.activeElement.dataset.agentId),'fixture-pm');
    report.checks.push('cockpit roster search, answer-wait filter, true team map, agent tabs, poll-stable keyboard focus, modal Escape/close/reopen and task draft retention');
    // Polling must preserve unchanged DOM and ignore an obsolete A response even
    // when the user has returned A → B → A before it arrives.
    await page.locator('#conversationLog .log-entry').waitFor();
    await page.evaluate(()=>{window.stableNodes={roster:document.querySelector('#agentCards').firstChild,
      log:document.querySelector('#conversationLog').firstChild,activity:document.querySelector('#activityFeed').firstChild,
      metric:document.querySelector('#runMetrics').firstChild};});
    await page.waitForTimeout(1200);
    assert.equal(await page.evaluate(()=>Object.entries(window.stableNodes).every(([key,node])=>node===document.querySelector(
      {roster:'#agentCards',log:'#conversationLog',activity:'#activityFeed',metric:'#runMetrics'}[key]).firstChild)),true,'No-change polling retains nodes');
    const heldState=await holdNextRequest(page,'**/api/state*',async()=>{});
    assert.equal(new URL(heldState.request().url()).searchParams.get('view'),'selected');
    const obsoleteState=compactFixture(heldState.request());
    obsoleteState.agents.find(agent=>agent.id==='fixture-pm').logs[0].text='[SYNTHETIC] OBSOLETE A RESPONSE';
    await page.evaluate(()=>{window.sawObsoleteState=false;window.stateObserver=new MutationObserver(()=>{
      if(document.querySelector('#conversationLog').textContent.includes('OBSOLETE A RESPONSE'))window.sawObsoleteState=true;
    });window.stateObserver.observe(document.querySelector('#conversationLog'),{subtree:true,childList:true,characterData:true});});
    await page.locator('#messageInput').fill('[SYNTHETIC] Selection race draft');
    await page.locator('#agentTabs [data-focus-key="tab:fixture-worker-1"]').click();
    assert.equal(await page.locator('#copyResult').isDisabled(),true);
    assert(!((await page.locator('#conversationLog').textContent()).includes('作業を2つに分けました')),'Loading cannot show prior owner content');
    await page.locator('#agentCards [data-agent-id="fixture-pm"]').click();
    await releaseResponse(page,heldState,obsoleteState);
    await page.locator('#conversationLog').filter({hasText:'作業を2つに分けました'}).waitFor();
    assert.equal(await page.evaluate(()=>window.sawObsoleteState),false,'A → B → A requires a generation guard');
    await page.evaluate(()=>window.stateObserver.disconnect());
    assert.equal(await page.locator('#messageInput').inputValue(),'[SYNTHETIC] Selection race draft');
    report.checks.push('compact polling omits unselected histories, retains no-change roster/log/activity/metric nodes, and rejects delayed A → B → A state without exposing prior-owner content or losing drafts');

    assert.equal(await page.locator('#runMetrics .metric').filter({hasText:'自動連携'}).locator('b').textContent(),'3 / 7');
    assert.equal(await page.locator('#collaborationLimitNotice').isVisible(),false);
    assert.equal(await page.locator('#conversationLog details[open]').count(),0);
    await page.locator('#conversationLog summary').click();assert.equal(await page.locator('#conversationLog details[open]').count(),1);
    await disclosureFocusAcceptance({page,fixture,compactFixture,artifacts,report,holdNextRequest,releaseResponse,assertLayout});
    await allQuestionsAcceptance({page,fixture,compactFixture,artifacts,report,holdNextRequest,releaseResponse,assertLayout});
    await taskReuseAcceptance({page,fixture,compactFixture,providerRequests,artifacts,report,holdNextRequest,releaseResponse,assertLayout,assertDialogLayout});
    await inputPresenceAcceptance({page,fixture,compactFixture,providerRequests,artifacts,report,holdNextRequest,releaseResponse,assertLayout});
    assert.equal(await page.locator('#activityFeed img').count(),0);assert.equal(await page.evaluate(()=>Boolean(window.fixtureInjected)),false);
    assert.equal(await page.locator('#runForm').isVisible(),false);await page.evaluate(()=>window.scrollTo(0,0));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.screenshot({path:path.join(artifacts,'workbench-team.png'),fullPage:true,animations:'disabled'});
    await assertLayout(page,'desktop active');
    fixture.agents[0].question='[SYNTHETIC] 長い確認事項：共有するチームと対象資料を確認してください。'.repeat(5);
    await page.locator('#humanQuestion').filter({hasText:'長い確認事項'}).waitFor();
    await page.setViewportSize({width:390,height:844});await assertLayout(page,'narrow active long question');
    await page.screenshot({path:path.join(artifacts,'workbench-active-narrow.png'),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:820,height:768});await assertLayout(page,'tablet active long question');
    await page.screenshot({path:path.join(artifacts,'workbench-tablet.png'),fullPage:true,animations:'disabled'});
    const ordinaryProfile={...fixture.agents[0].configured_profile};
    fixture.agents[0].configured_profile={...ordinaryProfile,label:'[SYNTHETIC] 最大長表示名 '+ '長'.repeat(180),model:'x'.repeat(200)};
    await page.locator('#conversationProfile').filter({hasText:'最大長表示名'}).waitFor();
    await assertLayout(page,'tablet maximum profile identity and long question');
    assert(await page.locator('#conversationHeading').evaluate(node=>{
      node.scrollTop=0;return document.querySelector('#conversationTitle').getBoundingClientRect().top>=node.getBoundingClientRect().top;
    }),'Beginning of full identity remains reachable above the scroll region');
    await page.locator('#conversationHeading').focus();await page.keyboard.press('End');
    await page.waitForFunction(()=>{const node=document.querySelector('#conversationHeading');return node.scrollTop>0&&node.scrollHeight-node.clientHeight-node.scrollTop<=1;});
    assert(await page.locator('#conversationHeading').evaluate(node=>document.querySelector('#conversationProfile').getBoundingClientRect().bottom<=node.getBoundingClientRect().bottom),'Keyboard reaches full model identity and disclaimer');
    const headingScroll=await page.locator('#conversationHeading').evaluate(node=>node.scrollTop);
    const unchangedProfilePoll=await page.waitForResponse(response=>response.url().includes('/api/state?'));
    await unchangedProfilePoll.finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.locator('#conversationHeading').evaluate(node=>node.scrollTop),headingScroll,'Unchanged polling preserves keyboard metadata scroll');
    await assertLayout(page,'tablet scrolled profile identity');
    await page.screenshot({path:path.join(artifacts,'workbench-attribution-long-tablet.png'),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});await assertLayout(page,'narrow maximum profile identity');
    assert(await page.locator('[data-agent-id="fixture-pm"] .agent-task').evaluate(node=>{
      const task=node.getBoundingClientRect(),card=node.closest('.agent-card').getBoundingClientRect();
      return task.height>0&&task.bottom<=card.bottom&&task.top>=card.top;
    }),'Narrow cards preserve visible assignment space with maximum profile identity');
    await page.screenshot({path:path.join(artifacts,'workbench-attribution-long-narrow.png'),fullPage:true,animations:'disabled'});
    fixture.agents[0].configured_profile=ordinaryProfile;
    await page.waitForFunction(()=>!document.querySelector('#conversationProfile').textContent.includes('最大長表示名'));
    await page.locator('#conversationHeading').evaluate(node=>{node.scrollTop=0;});
    report.checks.push('maximum configured label/model stays in bounded keyboard-scrollable heading; unchanged polling preserves metadata scroll; tablet/narrow long-question composer and narrow assignment text remain visible');
    await page.setViewportSize({width:1366,height:768});
    await page.locator('#navSettings').click();assert.equal(await page.locator('#saveSettings').isDisabled(),true);assert.equal(await page.locator('#systemPolicy').isDisabled(),true);
    await page.locator('#closeSettings').click();
    await page.locator('#messageInput').fill('PMに送る未送信メモ');await page.locator('#agentTabs [data-focus-key="tab:fixture-worker-1"]').click();await page.locator('#messageInput').fill('担当者への未送信メモ');await page.locator('#agentCards [data-agent-id="fixture-pm"]').click();assert.equal(await page.locator('#messageInput').inputValue(),'PMに送る未送信メモ');
    const answer='まず開発チームだけを対象にしてください。外部には共有しません。';
    const heldAnswer=await holdNextRequest(page,'**/api/agents/fixture-pm/message',async()=>{
      await page.locator('#messageInput').fill(answer);await page.locator('#sendMessage').click();
    });
    await page.locator('#messageInput').fill('送信中に編集した次の指示');
    const acceptedAnswer=page.waitForResponse(response=>response.request()===heldAnswer.request());
    await heldAnswer.fallback();const answerResponse=await acceptedAnswer;assert.equal(answerResponse.status(),200);await answerResponse.finished();
    await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);
    assert.equal(await page.locator('#messageStatus').textContent(),'','A completed send cannot label the newer edited draft as sent');
    assert.deepEqual(sentMessages,[{text:answer}]);assert.equal(await page.locator('#messageInput').inputValue(),'送信中に編集した次の指示');
    messageDelay=600;
    await page.locator('#sendMessage').click();await page.locator('#agentTabs [data-focus-key="tab:fixture-worker-2"]').click();
    await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);
    assert.equal(await page.locator('#messageStatus').textContent(),'','Late success belongs to the original agent');
    messageFailure=true;
    await page.locator('#messageInput').fill('[SYNTHETIC] Keep this rejected draft');await page.locator('#sendMessage').click();
    await page.locator('#agentCards [data-agent-id="fixture-pm"]').click();await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);
    assert.equal(await page.locator('#messageStatus').textContent(),'','Late error belongs to the original agent');
    await page.locator('#agentTabs [data-focus-key="tab:fixture-worker-2"]').click();
    assert.equal(await page.locator('#messageInput').inputValue(),'[SYNTHETIC] Keep this rejected draft');
    await page.locator('#agentCards [data-agent-id="fixture-pm"]').click();messageFailure=false;
    report.checks.push('late send success/error never appear on a different selected agent; failed-message draft is retained');
    report.checks.push('simulated multi-provider team: exact visible task, editable policy, worker limit, mail escaping, collapsed model thinking, human reply, draft preservation and settings lock; no inference');
    fixture.runs[0].auto_collaborations=7;fixture.runs[0].collaboration_limit_reached=true;fixture.runs[0].status='waiting';fixture.runs[0].status_reason='collaboration_limit';
    await page.locator('#collaborationLimitNotice').waitFor({state:'visible'});
    assert.equal(await page.locator('#runMetrics .metric').filter({hasText:'自動連携'}).locator('b').textContent(),'7 / 7');
    assert.equal(await page.locator('#activeRunStatus').textContent(),'連携上限');
    assert.match(await page.locator('#collaborationLimitNotice').textContent(),/新しい作業を開始/);
    assert.match(await page.locator('#collaborationLimitNotice').textContent(),/回数はリセットされません/);
    report.checks.push('collaboration counter and blocked-handoff notice distinguish budget exhaustion from completion');
    await page.locator('#stopRun').click();await page.locator('#activeRunStatus').filter({hasText:'停止'}).waitFor();assert.equal(stopped.length,1);assert.equal(await page.locator('#messageInput').isDisabled(),true);
    assert.equal(await page.locator('#collaborationLimitNotice').isVisible(),true);
    assert((await page.locator('#collaborationLimitNotice').textContent()).includes('停止したチームは再開できません'));
    await page.locator('#navSettings').click();assert.equal(await page.locator('#saveSettings').isDisabled(),false);await page.locator('#closeSettings').click();
    await page.setViewportSize({width:390,height:844});await assertLayout(page,'narrow stopped notice');
    await page.screenshot({path:path.join(artifacts,'workbench-mobile.png'),fullPage:true,animations:'disabled'});
    report.checks.push('desktop 1366x768, tablet 820x768, narrow 390x844: no document horizontal overflow, no sidebar/workspace overlap, input and send inside unclipped panels, long Japanese questions and stop notice');
    await lifecycleAcceptance({page,agentContract,artifacts,report,assertLayout,assertDialogLayout});
    // Remove only the UI-state fixtures: the following flow uses real app endpoints
    // and Engine with an injected test client, including real serialization.
    await page.unroute('**/api/state*');await page.unroute('**/api/runs');
    await page.unroute('**/api/agents/*/message');await page.unroute('**/api/runs/*/stop');
    await page.reload();await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    await page.locator('#newRun').click();await page.locator('#taskInput').fill('[SYNTHETIC] Real engine browser integration.');
    await page.locator('#pmProfile').selectOption('local');
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.uncheck();
    await page.locator('#workerProfiles input[value="local"]').check();await page.locator('#maxWorkers').fill('1');
    await page.locator('#startRun').click();
    await page.locator('#humanQuestion').filter({hasText:'[SYNTHETIC] Continue this test run?'}).waitFor();
    await page.waitForFunction(()=>document.querySelectorAll('.agent-card').length===2);
    await page.locator('#activityFeed').filter({hasText:'Worker review complete.'}).waitFor();
    assert.equal(await page.locator('#conversationStatus').textContent(),'回答待ち');
    assert.equal(await page.locator('#activeRunStatus').textContent(),'回答待ち');
    await page.locator('#agentSearch').fill('Review fixture only.');assert.equal(await page.locator('.agent-card').count(),1);
    assert((await page.locator('.agent-task').textContent()).includes('Review fixture only.'));await page.locator('#agentSearch').clear();
    await assertLayout(page,'narrow real engine');
    await page.screenshot({path:path.join(artifacts,'workbench-real-engine-narrow.png'),fullPage:true,animations:'disabled'});
    await page.locator('#navSettings').click();assert.equal(await page.locator('#saveSettings').isDisabled(),true);await page.keyboard.press('Escape');
    await page.locator('#messageInput').fill('[SYNTHETIC] Continue until cancellation.');await page.locator('#sendMessage').click();
    await page.locator('#messageStatus').filter({hasText:'送信しました'}).waitFor();
    await page.locator('#humanQuestion').waitFor({state:'hidden'});
    await page.setViewportSize({width:1366,height:768});
    await page.screenshot({path:path.join(artifacts,'workbench-real-engine-desktop.png'),fullPage:true,animations:'disabled'});
    await page.locator('#stopRun').click();await page.locator('#activeRunStatus').filter({hasText:'停止'}).waitFor();
    assert.equal(await page.locator('#messageInput').isDisabled(),true);
    assert((await page.locator('#messageEligibility').textContent()).includes('新しい仕事'));
    await page.locator('#navSettings').click();assert.equal(await page.locator('#saveSettings').isDisabled(),false);await page.keyboard.press('Escape');
    report.checks.push('real HTTP+engine start, serialized agents, scripted worker spawn/completion mail, ask_user, human reply, actual cancellation and settings unlock at desktop/narrow sizes');
    await page.locator('#navSettings').click();await page.locator('#limits-max_turns_per_agent').fill('1');
    await page.locator('#saveSettings').click();await page.locator('#settingsStatus').filter({hasText:'設定を保存しました。'}).waitFor();await page.keyboard.press('Escape');
    await page.locator('#newRun').click();await page.locator('#taskInput').fill('[SYNTHETIC] Complete immediately.');await page.locator('#maxWorkers').fill('0');await page.locator('#startRun').click();
    await page.locator('#activeRunStatus').filter({hasText:'完了'}).waitFor();
    assert.equal(await page.locator('#messageStatus').textContent(),'','Previous run send confirmation must not leak into a new run');
    assert.equal(await page.locator('#sendMessage').isDisabled(),true);
    await page.locator('#messageEligibility').filter({hasText:'ターン上限'}).waitFor();
    await assertLayout(page,'desktop exhausted budget');
    await page.screenshot({path:path.join(artifacts,'workbench-recovery-budget.png'),fullPage:true,animations:'disabled'});
    await page.locator('#navSettings').click();await page.locator('#limits-max_turns_per_agent').fill('2');
    await page.locator('#saveSettings').click();await page.locator('#settingsStatus').filter({hasText:'設定を保存しました。'}).waitFor();await page.keyboard.press('Escape');
    await page.locator('#messageEligibility').filter({hasText:'設定が変更'}).waitFor();
    assert.equal(await page.locator('#sendMessage').isDisabled(),true);
    await page.setViewportSize({width:390,height:844});await assertLayout(page,'narrow stale settings');
    await page.screenshot({path:path.join(artifacts,'workbench-recovery-settings-narrow.png'),fullPage:true,animations:'disabled'});
    report.checks.push('real assignment display/search and question status; completed run rejects exhausted turn budget, later settings changes show stale-config recovery without resetting budgets');
    // Real engine writes a file and emits an ordinary terminal assistant answer.
    await page.setViewportSize({width:1366,height:768});
    await page.locator('#newRun').click();await page.locator('#taskInput').fill('[SYNTHETIC] Save result.');await page.locator('#maxWorkers').fill('0');await page.locator('#startRun').click();
    await page.locator('#activeRunStatus').filter({hasText:'完了'}).waitFor();
    await page.locator('#resultsPanel > summary').click();
    await page.waitForFunction(()=>document.querySelector('#resultSelection').options.length===2);
    const resultOption=await page.locator('#resultSelection option[value^="result:"]').getAttribute('value');
    const receiptOption=await page.locator('#resultSelection option[value^="receipt:"]').getAttribute('value');
    await page.locator('#resultSelection').selectOption(resultOption);
    assert((await page.locator('#resultText').textContent()).includes('[SYNTHETIC] Terminal answer 日本語.'));
    assert.equal(fs.readFileSync(path.join(workspace,'browser-result.txt'),'utf8'),'[SYNTHETIC] Saved text 日本語.');
    await context.grantPermissions(['clipboard-read','clipboard-write'],{origin});
    await page.locator('#messageInput').fill('結果を確認中の未送信メモ');
    await page.locator('#copyResult').click();await page.locator('#resultActionStatus').filter({hasText:'本文をコピーしました。'}).waitFor();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'[SYNTHETIC] Terminal answer 日本語.');
    const saveText=async(expectedName)=>{const downloadEvent=page.waitForEvent('download');await page.locator('#exportResult').click();const download=await downloadEvent;assert.equal(download.suggestedFilename(),expectedName);return fs.readFileSync(await download.path(),'utf8');};
    const exported=await saveText('workbench-result.txt');
    assert(exported.includes('[SYNTHETIC] Terminal answer 日本語.'));assert(!exported.includes('PRIVATE-REASONING-FIXTURE'));assert(!exported.includes('PRIVATE-PROTOCOL-FIXTURE'));assert(!exported.includes('fixture-memory-secret'));
    await page.locator('#resultSelection').selectOption(receiptOption);
    assert((await page.locator('#resultNotice').textContent()).includes('未確認'));
    await page.locator('#copyResult').click();await page.locator('#resultActionStatus').filter({hasText:'パスをコピーしました。'}).waitFor();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),fs.realpathSync.native(path.join(workspace,'browser-result.txt')));
    const receiptExport=await saveText('workbench-save-receipt.txt');assert(receiptExport.includes('browser-result.txt'));assert(!receiptExport.includes('[SYNTHETIC] Saved text'));
    assert.equal(await saveText('workbench-save-receipt.txt'),receiptExport,'Repeated exports are exact selected metadata');
    assert.equal(await page.locator('#messageInput').inputValue(),'結果を確認中の未送信メモ');
    await assertLayout(page,'desktop results');await page.screenshot({path:path.join(artifacts,'workbench-results-desktop.png'),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});await assertLayout(page,'narrow results');await page.screenshot({path:path.join(artifacts,'workbench-results-narrow.png'),fullPage:true,animations:'disabled'});
    // Controlled clipboard rejection and completion order test real UI handlers.
    await page.evaluate(()=>{window.copyRequests=[];Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:()=>new Promise((resolve,reject)=>window.copyRequests.push({resolve,reject}))});});
    await page.locator('#copyResult').click();await page.locator('#resultSelection').selectOption(resultOption);
    await page.evaluate(()=>window.copyRequests[0].resolve());await page.waitForTimeout(50);
    assert.equal(await page.locator('#resultActionStatus').textContent(),'','Late copy success cannot follow record selection');
    await page.locator('#copyResult').click();await page.locator('#copyResult').click();
    await page.evaluate(()=>window.copyRequests[2].reject(new Error('Synthetic clipboard denial')));
    await page.locator('#resultActionStatus').filter({hasText:'コピーできませんでした'}).waitFor();
    await page.evaluate(()=>window.copyRequests[1].resolve());await page.waitForTimeout(50);
    assert((await page.locator('#resultActionStatus').textContent()).includes('コピーできませんでした'),'Old copy must not overwrite newer failure');
    await page.locator('#copyResult').click();await page.locator('#runList .run-link').last().click();
    await page.evaluate(()=>window.copyRequests[3].resolve());await page.waitForTimeout(50);
    assert.equal(await page.locator('#resultActionStatus').textContent(),'','Late copy cannot follow run selection');
    await page.evaluate(()=>delete navigator.clipboard.writeText);
    report.checks.push('real engine file receipt and terminal response; actual clipboard text/path, exact UTF-8 downloads, repeated export, draft preservation, selected-record/run races, latest-copy failure wins, desktop/narrow result screenshots; no reasoning/protocol export');
    await retentionAcceptance({page,context,origin,workspace,stateDir,providerRequests,artifacts,report,assertLayout,
      resultOption,receiptOption,exported,receiptExport});
    // A fresh text-only PM can start without file scopes, even with an unused
    // cloud worker selected. Preview/settings must preserve earlier outputs.
    await page.locator('#runList .run-link').filter({hasText:'[SYNTHETIC] Save result.'}).click();
    await page.locator('#resultSelection').selectOption(resultOption);
    const retainedDraft=await page.locator('#messageInput').inputValue();
    const retainedRecords=await page.locator('#resultSelection option').evaluateAll(options=>options.map(option=>option.value));
    const storedOutputs=()=>page.evaluate(async()=>{
      const response=await fetch('/api/state',{credentials:'same-origin',cache:'no-store'});const state=await response.json();
      return {runs:state.runs.map(run=>({id:run.id,model_calls:run.model_calls,tool_calls:run.tool_calls})),
        agents:state.agents.map(agent=>({id:agent.id,results:agent.results,output_receipts:agent.output_receipts}))};
    });
    const beforePreview=await storedOutputs();
    await page.locator('#navSettings').click();
    await page.locator('#paths-read_roots').clear();await page.locator('#paths-write_roots').clear();await page.locator('#search-enabled').uncheck();
    await page.locator('#saveSettings').click();await page.locator('#settingsStatus').filter({hasText:'設定を保存しました'}).waitFor();
    await page.keyboard.press('Escape');await page.locator('#newRun').click();
    await page.locator('#pmProfile').selectOption('local');await page.locator('#maxWorkers').fill('0');
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.uncheck();
    await page.locator('#workerProfiles input[value="anthropic"]').check();
    const textOnly=await preflightAfter(page,()=>page.locator('#taskInput').fill('[SYNTHETIC] Complete immediately.'),data=>data.task==='[SYNTHETIC] Complete immediately.'&&data.max_workers===0&&data.worker_profiles.length===1&&data.worker_profiles[0]==='anthropic');
    assert.equal(textOnly.can_start,true);assert.equal(textOnly.destinations.length,1);
    assert.equal(textOnly.destinations[0].profile_id,'local');assert.equal(textOnly.destinations[0].model,'manual-unlisted-alias');
    assert.deepEqual(textOnly.scope.read_roots,[]);assert.deepEqual(textOnly.scope.write_roots,[]);assert.equal(textOnly.web.enabled,false);
    assert(textOnly.warnings.some(warning=>warning.code==='read_scope_empty'));
    assert(textOnly.warnings.some(warning=>warning.code==='write_scope_empty'));
    assert.match(await page.locator('#preflightStatus').textContent(),/文章だけの作業は開始できます/);
    assert.deepEqual(await storedOutputs(),beforePreview,'Settings and read-only preview cannot create a run, call a model, or change saved outputs');
    const pmStartResponse=page.waitForResponse(response=>response.url().endsWith('/api/runs')&&response.request().method()==='POST');
    await page.locator('#startRun').click();const pmStarted=await (await pmStartResponse).json();
    assert.equal(pmStarted.ok,true);assert.deepEqual(pmStarted.run.worker_profiles,[]);assert.equal(pmStarted.run.max_workers,0);
    await page.locator(`#runList .run-link.selected[data-focus-key="run:${pmStarted.run.id}"]`).waitFor();
    await page.locator('#activeRunStatus').filter({hasText:'完了'}).waitFor();
    assert.equal(await page.locator('.agent-card').count(),1,'PM-only admission does not create workers');
    const afterTextRun=await storedOutputs(),textRun=afterTextRun.runs.find(run=>run.id===pmStarted.run.id);
    assert.equal(textRun.model_calls,1);assert.equal(textRun.tool_calls,0);
    assert.deepEqual(afterTextRun.runs.filter(run=>run.id!==textRun.id),beforePreview.runs);
    assert.deepEqual(afterTextRun.agents.filter(agent=>beforePreview.agents.some(prior=>prior.id===agent.id)),beforePreview.agents);
    await page.locator('#runList .run-link').filter({hasText:'[SYNTHETIC] Save result.'}).click();
    await page.waitForFunction(()=>!document.querySelector('#resultSelection').disabled);
    assert.deepEqual(await page.locator('#resultSelection option').evaluateAll(options=>options.map(option=>option.value)),retainedRecords);
    assert.equal(await page.locator('#resultSelection').inputValue(),resultOption);
    assert.equal(await page.locator('#messageInput').inputValue(),retainedDraft);
    assert.match(await page.locator('#resultText').textContent(),/Terminal answer 日本語/);
    assert.equal(fs.readFileSync(path.join(workspace,'browser-result.txt'),'utf8'),'[SYNTHETIC] Saved text 日本語.');
    report.checks.push('real PM-only text run accepts no file roots and an unlisted alias; unused missing-key worker does not block or become a destination; preflight/settings preserve prior report, receipt, selected record, draft and file bytes without model calls');
    // Real retained runs keep the configuration they started with after editing
    // and deleting a profile. No current-settings fallback or model identity claim.
    const originalProfile=await page.evaluate(async()=>{
      const state=await (await fetch('/api/state',{credentials:'same-origin',cache:'no-store'})).json();
      const run=state.runs.find(run=>run.task==='[SYNTHETIC] Save result.');
      return state.agents.find(agent=>agent.run_id===run.id&&!agent.parent_id).configured_profile;
    });
    assert.deepEqual(Object.keys(originalProfile).sort(),['id','kind','label','model']);
    assert.equal(originalProfile.model,'manual-unlisted-alias');
    assert.match(await page.locator('#conversationProfile').textContent(),/manual-unlisted-alias.*応答モデル未確認/);
    assert(exported.includes('開始時のモデル設定: "manual-unlisted-alias"'));
    assert.match(exported,/作業 ID: r-[a-f0-9]+/);assert.match(exported,/エージェント ID: a-[a-f0-9]+/);
    assert(exported.includes('接続先が実際に使ったモデルの確認ではありません'));
    await page.locator('#navSettings').click();await page.locator('#profile-0-label').fill('Cycle7 renamed provider');
    await page.locator('#profile-0-model').fill('cycle7-new-configured-alias');
    await page.locator('#saveSettings').click();await page.locator('#settingsStatus').filter({hasText:'設定を保存しました'}).waitFor();
    await page.keyboard.press('Escape');
    assert.match(await page.locator('#conversationProfile').textContent(),/manual-unlisted-alias/);
    assert(!await page.locator('.agent-card .agent-model').first().textContent().then(text=>text.includes('Cycle7 renamed')));
    assert.equal(await saveText('workbench-result.txt'),exported,'Saved report attribution cannot change with current profile');
    await page.locator('#newRun').click();await page.locator('#taskInput').fill('[SYNTHETIC] Complete immediately.');
    const newRunResponse=page.waitForResponse(response=>response.url().endsWith('/api/runs')&&response.request().method()==='POST');
    await page.locator('#startRun').click();const newRun=(await (await newRunResponse).json()).run;
    await page.locator(`#runList .run-link.selected[data-focus-key="run:${newRun.id}"]`).waitFor();
    await page.locator('#activeRunStatus').filter({hasText:'完了'}).waitFor();
    assert.match(await page.locator('#conversationProfile').textContent(),/Cycle7 renamed provider.*cycle7-new-configured-alias/);
    await page.locator('#navSettings').click();
    await page.locator('.profile-editor').first().getByRole('button',{name:'削除',exact:true}).click();
    await page.locator('#saveSettings').click();await page.locator('#settingsStatus').filter({hasText:'設定を保存しました'}).waitFor();
    await page.keyboard.press('Escape');
    assert.match(await page.locator('#conversationProfile').textContent(),/cycle7-new-configured-alias/);
    await page.locator('#runList .run-link').filter({hasText:'[SYNTHETIC] Save result.'}).click();
    await page.waitForFunction(()=>!document.querySelector('#resultSelection').disabled);
    assert.match(await page.locator('#conversationProfile').textContent(),/manual-unlisted-alias/);
    assert.equal(await saveText('workbench-result.txt'),exported);
    await page.locator('#resultSelection').selectOption(receiptOption);
    assert.equal(await saveText('workbench-save-receipt.txt'),receiptExport);
    await page.setViewportSize({width:1366,height:768});await assertLayout(page,'desktop historical profile');
    await page.screenshot({path:path.join(artifacts,'workbench-attribution-desktop.png'),fullPage:true,animations:'disabled'});
    await page.setViewportSize({width:390,height:844});await assertLayout(page,'narrow historical profile');
    await page.screenshot({path:path.join(artifacts,'workbench-attribution-narrow.png'),fullPage:true,animations:'disabled'});
    report.checks.push('real run-scoped configured identity survives profile rename/model change/removal; new run captures new model; old report and receipt exports remain byte-identical with run/agent attribution; labels distinguish configuration from verified response model; desktop/narrow screenshots');
    await retainedRedactionAcceptance({page,context,origin,workspace,stateDir,artifacts,cases:redactionCases,report});
    await credentialRecoveryAcceptance({page,origin,providerUrl,providerRequests,stateDir,artifacts,
      scenario:credentialScenario,report,assertLayout,assertDialogLayout});
    await settingsSaveAcceptance({page,context,origin,providerUrl,providerRequests,stateDir,artifacts,
      report,assertLayout,assertDialogLayout});
    await messageReceiptAcceptance({context,origin,providerRequests,report});
    await contextCompactionAcceptance({context,origin,providerRequests,stateDir,artifacts,report,assertLayout});
    assert.deepEqual(providerRequests,[{method:'GET',path:'/v1/models'},{method:'GET',path:'/v1/models'}]);
    assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
    assert.deepEqual(report.pageErrors,[]);assert.deepEqual(report.cspErrors,[]);assert.deepEqual(report.externalRequests,[]);
    report.checks.push('stop, settings unlock, narrow-screen layout, zero browser storage and zero external page requests');report.ok=true;
    fs.writeFileSync(path.join(artifacts,'browser-smoke.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  } catch(error) {
    if(page)await page.screenshot({path:path.join(artifacts,'workbench-failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});
    report.ok=false;const redact=value=>[...Object.values(redactionCases).flatMap(item=>[item.old,item.new]),
      ...['old','new','search_old','search_new','other'].map(name=>credentialScenario[name]),'fixture-memory-secret']
      .reduce((text,key)=>text.replaceAll(key,'[REDACTED]'),String(value).replace(/(#token=|X-Workbench-Bootstrap[=: ]+)[A-Za-z0-9_-]+/gi,'$1[REDACTED]'));
    report.error=redact(error.stack||error.message);report.serverError=redact(stderr);
    fs.writeFileSync(path.join(artifacts,'browser-smoke.json'),JSON.stringify(report,null,2));
    console.error(JSON.stringify(report,null,2));process.exitCode=1;
  } finally {
    if(browser)await browser.close();
    if(server.exitCode===null){server.kill();await new Promise(resolve=>{server.once('close',resolve);setTimeout(resolve,4000);});}
    await new Promise(resolve=>provider.close(resolve));
    fs.rmSync(sandbox,{recursive:true,force:true,maxRetries:5,retryDelay:200});
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
