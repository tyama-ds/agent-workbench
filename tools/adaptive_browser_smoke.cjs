/* Fresh owned Edge + real application, finite synthetic provider, no model network. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {spawn,spawnSync}=require('node:child_process');
const ROOT=path.resolve(__dirname,'..');
const {chromium}=require('node:module').createRequire(path.join(__dirname,'browser-tests/package.json'))('playwright');
const argv=process.argv.slice(2);
assert.equal(argv.length,2);assert.equal(argv[0],'--output');
const OUT=path.resolve(argv[1]);
assert(path.isAbsolute(argv[1]),'An explicit absolute output path is required');
assert(OUT!==ROOT&&!OUT.startsWith(ROOT+path.sep),'Output/state/work/profile must be outside application resources');
for(let current=path.dirname(OUT);;current=path.dirname(current)){
  if(fs.existsSync(current))assert(!fs.lstatSync(current).isSymbolicLink(),'No reparse workspace');
  if(current===path.dirname(current))break;
}
assert(!fs.existsSync(OUT),'Never reuse an invocation or output');
assert(fs.statSync(path.dirname(OUT)).isDirectory(),'Create the intended parent explicitly before invocation');
const python=process.env.WORKBENCH_TEST_PYTHON;
assert(python&&path.isAbsolute(python)&&fs.statSync(python).isFile(),'Explicit existing WORKBENCH_TEST_PYTHON required');
const nonce=crypto.randomBytes(32).toString('hex'),profile=path.join(OUT,'browser-profile');
const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function sourceRefs(){
  const result=spawnSync('git',['ls-files','-z','--cached','--others','--exclude-standard'],{cwd:ROOT,encoding:'utf8',windowsHide:true});
  assert.equal(result.status,0,'Cannot inventory source');
  return [...new Set(result.stdout.split('\0').filter(Boolean))].sort().map(name=>{
    const bytes=fs.readFileSync(path.join(ROOT,name));return {path:name,bytes:bytes.length,sha256:digest(bytes)};
  });
}
const before=sourceRefs();
fs.mkdirSync(OUT);
const save=(name,value)=>fs.writeFileSync(path.join(OUT,name),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
save('launch-claim.json',{nonce,pid:process.pid,started_at:new Date().toISOString(),source:before,once_only:true});
const report={kind:'synthetic_adaptive_browser',ok:false,checks:[],errors:[],pageErrors:[],consoleErrors:[],externalRequests:[],
  frames:[],snapshots:[],screenshots:[],requests:[],nativeControls:[],ownership:[],censusChildren:[],
  archiveObservation:{started:false,navigationComplete:false,bootstrap:[],mutations:[]},
  realModelInference:false,routeMocks:false,clockOverrides:false,deletedFiles:0,forcedTermination:false,
  lifecycle:{contextClosed:false,browserClosed:false,fixtureAck:false,wrapperExit:null,remainingOwned:null},
  limitations:['Synthetic decisions do not prove difficulty or review judgment quality.',
    'Node observes its child wrapper exit; actual Python exit is supported by its closure ACK and fresh identity absence, not a separately held process handle.']};
let child,childExit,context,browser,page,origin,actualPid,actualIdentity,shutdownSent=false,censusPending=null,stopping=false;
const frames=[],waiters=[],owned=new Map();
const clean=value=>String(value).split(nonce).join('[nonce]').replace(/#token=[A-Za-z0-9_-]+/g,'#token=[bootstrap]');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function bounded(promise,ms,label){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>timer=setTimeout(()=>reject(new Error(label+' exceeded '+ms+'ms; no forced termination')),ms))]);}finally{clearTimeout(timer);}}
function acceptFrame(value){
  assert.equal(value.nonce,nonce,'Fixture protocol nonce mismatch');frames.push(value);
  report.frames.push({...value,nonce:'[nonce]',...(value.url?{url:clean(value.url)}:{})});
  for(const waiter of [...waiters])if(waiter.matches(value)){waiters.splice(waiters.indexOf(waiter),1);waiter.resolve(value);}
}
async function frame(matches,label,timeout=25000){
  const previous=frames.find(matches);if(previous)return previous;
  let waiter;const pending=new Promise(resolve=>{waiter={matches,resolve};waiters.push(waiter);});
  try{return await bounded(pending,timeout,label);}finally{const i=waiters.indexOf(waiter);if(i>=0)waiters.splice(i,1);}
}
async function command(name){
  assert(name==='shutdown'||!stopping,'Work has stopped; no more fixture releases');
  assert(child&&!child.stdin.destroyed,'Fixture stdin is unavailable');
  const pending=frame(row=>row.kind==='ack'&&row.command===name,name+' ACK');
  const line=JSON.stringify({command:name,nonce})+'\n';
  if(name==='shutdown'){assert(!shutdownSent);shutdownSent=true;child.stdin.end(line);}else child.stdin.write(line);
  const receipt=await pending;assert.equal(receipt.ok,true,receipt.error);return receipt;
}
async function census(label){
  if(process.platform!=='win32'){report.ownership.push({label,platform:process.platform,unsupported:true});return null;}
  assert(!censusPending,'Do not replace an unfinished process census');
  const script=`$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
@(Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='node.exe' OR Name='python.exe' OR Name='pythonw.exe'" -Property ProcessId,ParentProcessId,CreationDate,Name,CommandLine | ForEach-Object {
[pscustomobject]@{pid=[int]$_.ProcessId;ppid=[int]$_.ParentProcessId;created=$_.CreationDate.ToUniversalTime().ToString('o');name=$_.Name;profile=([string]$_.CommandLine).IndexOf($env:AWB_ADAPTIVE_PROFILE,[StringComparison]::OrdinalIgnoreCase)-ge 0}
}) | ConvertTo-Json -Depth 3 -Compress`;
  const processRecord={label,pid:null,exit:null,ended:false};report.censusChildren.push(processRecord);
  censusPending=new Promise((resolve,reject)=>{
    const observer=spawn('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,stdio:['ignore','pipe','pipe'],env:{...process.env,AWB_ADAPTIVE_PROFILE:profile}});
    processRecord.pid=observer.pid;let stdout='',stderr='';observer.stdout.setEncoding('utf8');observer.stderr.setEncoding('utf8');
    observer.stdout.on('data',value=>stdout+=value);observer.stderr.on('data',value=>stderr+=value);
    observer.on('error',reject);observer.on('close',code=>{processRecord.exit=code;processRecord.ended=true;code===0?resolve(stdout):reject(new Error('Census failed: '+stderr));});
  });
  let raw;try{raw=await bounded(censusPending,10000,'Read-only process census');}finally{if(processRecord.ended)censusPending=null;}
  const parsed=JSON.parse(raw.replace(/^\uFEFF/,'')),rows=Array.isArray(parsed)?parsed:[parsed];
  const me=rows.find(row=>row.pid===process.pid);assert(me&&me.created,'Current Node identity must be observed');
  const pids=new Set([process.pid]);let changed=true;
  while(changed){changed=false;for(const row of rows)if(pids.has(row.ppid)&&!pids.has(row.pid)){pids.add(row.pid);changed=true;}}
  const actual=rows.find(row=>row.pid===actualPid);
  if(!actualIdentity&&actual){actualIdentity={pid:actual.pid,created:actual.created};report.actualIdentity=actualIdentity;}
  const related=rows.filter(row=>pids.has(row.pid)||row.profile||
    (actualIdentity&&row.pid===actualIdentity.pid&&row.created===actualIdentity.created)||owned.has(`${row.pid}:${row.created}`));
  for(const row of related){assert(row.created);owned.set(`${row.pid}:${row.created}`,row);}
  report.ownership.push({label,rows:related});return related.filter(row=>row.pid!==process.pid);
}
async function state(label){
  assert(!stopping,'Work has stopped');
  const response=await context.request.get(origin+'/api/state',{timeout:10000,maxRetries:0});assert.equal(response.status(),200);
  const value=await response.json();if(label)report.snapshots.push({label,value});return value;
}
async function until(label,test){
  const deadline=Date.now()+10000;let value;
  do{value=await state();if(test(value)){report.snapshots.push({label,value});return value;}await sleep(80);}while(Date.now()<deadline);
  report.snapshots.push({label:label+'-timeout',value});throw Error(label+' did not reach its state');
}
async function text(selector,expected){assert(!stopping,'Work has stopped');await page.waitForFunction(({selector,expected})=>document.querySelector(selector)?.textContent.includes(expected),{selector,expected},{timeout:10000});}
async function nativeTab(selector,label){
  assert(!stopping,'Work has stopped');
  const start=await page.locator(selector).evaluate(target=>{
    const scope=target.closest('dialog[open]')||document;
    const candidates=[...scope.querySelectorAll('button,input,select,textarea,summary,a[href],[tabindex]')].filter(node=>
      !node.disabled&&node.tabIndex>=0&&node.getClientRects().length&&getComputedStyle(node).visibility!=='hidden').filter(node=>{
        for(let parent=node.parentElement;parent;parent=parent.parentElement){
          if(parent.tagName==='DETAILS'&&!parent.open){
            const summary=[...parent.children].find(child=>child.tagName==='SUMMARY');
            if(!summary||!(summary===node||summary.contains(node)))return false;
          }
        }return true;
      });
    const index=candidates.indexOf(target);if(index<=0)throw Error('No preceding native Tab target');
    const predecessor=candidates[index-1];predecessor.focus();
    const describe=node=>({id:node.id,tag:node.tagName,key:node.dataset.focusKey||null});
    return {predecessor:describe(predecessor),active:describe(document.activeElement),focusSucceeded:document.activeElement===predecessor};
  });
  (report.tabStarts??=[]).push({label,...start});assert(start.focusSucceeded,label+' predecessor could not receive focus');
  await page.keyboard.press('Tab');
  report.tabStarts.at(-1).afterTab=await page.evaluate(()=>({id:document.activeElement.id,tag:document.activeElement.tagName,key:document.activeElement.dataset.focusKey||null}));
  await page.waitForFunction(selector=>document.querySelector(selector)===document.activeElement,selector);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const observed=await page.locator(selector).evaluate(node=>{
    const box=node.getBoundingClientRect(),clip={left:0,top:0,right:innerWidth,bottom:innerHeight};
    for(let parent=node.parentElement;parent;parent=parent.parentElement){const style=getComputedStyle(parent),rect=parent.getBoundingClientRect();
      if(/hidden|auto|scroll|clip/.test(style.overflowX)){clip.left=Math.max(clip.left,rect.left+parent.clientLeft);clip.right=Math.min(clip.right,rect.left+parent.clientLeft+parent.clientWidth);}
      if(/hidden|auto|scroll|clip/.test(style.overflowY)){clip.top=Math.max(clip.top,rect.top+parent.clientTop);clip.bottom=Math.min(clip.bottom,rect.top+parent.clientTop+parent.clientHeight);}}
    const hit=document.elementFromPoint((box.left+box.right)/2,(box.top+box.bottom)/2);
    return {box:box.toJSON(),clip,focused:document.activeElement===node,hit:hit===node||node.contains(hit),width:innerWidth,scrollWidth:document.documentElement.scrollWidth};
  });
  report.nativeControls.push({label,...observed});const {box,clip}=observed;
  assert(observed.focused&&observed.hit&&box.width>0&&box.height>0,label+' unusable native control');
  assert(box.left>=clip.left-1&&box.top>=clip.top-1&&box.right<=clip.right+1&&box.bottom<=clip.bottom+1,label+' clipped');
  assert(observed.scrollWidth<=observed.width,label+' horizontal document overflow');
}
async function startRun(task,adaptive){
  assert(!stopping,'Work has stopped');
  await page.locator('#newRun').click();await page.locator('#taskInput').fill(task);
  await page.locator('#pmProfile').selectOption('local');await page.locator('#workerProfiles input[value="local"]').check();
  await page.locator('#maxWorkers').fill(adaptive?'2':'0');
  await page.locator('#delegationLevel').evaluate(node=>{node.value='0';node.dispatchEvent(new Event('input',{bubbles:true}));});
  await page.locator('#maxDelegationDepth').fill('3');
  await page.locator('#adaptiveTeam').setChecked(adaptive);
  const response=page.waitForResponse(value=>value.request().method()==='POST'&&new URL(value.url()).pathname==='/api/runs');
  await page.locator('#startRun').click();const result=await response;assert.equal(result.status(),200);
  const body=result.request().postDataJSON();assert.equal(body.max_workers,adaptive?2:0);
  if(adaptive)assert.equal(body.adaptive_team,true);else assert(!Object.hasOwn(body,'adaptive_team'));
  const receipt=await result.json();report.requests.push({kind:'run-start',body,run_id:receipt.run.id});return receipt.run;
}
async function execute(){
  const env={...process.env};for(const name of Object.keys(env))if(/^(OPENAI_API_KEY|ANTHROPIC_API_KEY|BRAVE_SEARCH_API_KEY|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY)$/i.test(name))delete env[name];
  const temp=path.join(OUT,'temp');fs.mkdirSync(temp);Object.assign(env,{TEMP:temp,TMP:temp,TMPDIR:temp});
  child=spawn(python,['-u','-m','tools.adaptive_browser_fixture','--output',OUT,'--nonce',nonce],{cwd:ROOT,windowsHide:true,stdio:['pipe','pipe','pipe'],env});
  childExit=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',(code,signal)=>resolve({code,signal}));});
  child.stdin.on('error',error=>report.errors.push('stdin: '+clean(error.message)));
  let pending='';child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
  child.stdout.on('data',part=>{pending+=part;let split;while((split=pending.indexOf('\n'))>=0){const line=pending.slice(0,split);pending=pending.slice(split+1);if(!line.trim())continue;try{acceptFrame(JSON.parse(line));}catch(error){report.errors.push('protocol: '+clean(error.message));}}});
  child.stderr.on('data',part=>fs.appendFileSync(path.join(OUT,'fixture.stderr.log'),clean(part)));
  const ready=await frame(row=>row.kind==='ready'&&row.phase==='live','Live fixture ready');assert(!stopping,'Work has stopped');actualPid=ready.pid;
  origin=new URL(ready.url).origin;assert(/^http:\/\/127\.0\.0\.1:\d+$/.test(origin));
  context=await chromium.launchPersistentContext(profile,{env,headless:true,viewport:{width:1366,height:768},locale:'ja-JP',reducedMotion:'reduce',
    timeout:20000,...(process.env.WORKBENCH_BROWSER_EXECUTABLE?{executablePath:process.env.WORKBENCH_BROWSER_EXECUTABLE}:process.platform==='win32'?{channel:'msedge'}:{})});
  browser=context.browser();assert(!stopping,'Work has stopped');page=context.pages()[0]||await context.newPage();page.setDefaultTimeout(10000);
  context.on('request',request=>{const url=new URL(request.url());if(url.protocol.startsWith('http')&&url.origin!==origin)report.externalRequests.push(url.origin+url.pathname);});
  page.on('pageerror',error=>report.pageErrors.push(error.message));page.on('console',entry=>{if(entry.type()==='error')report.consoleErrors.push(entry.text());});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort('blockedbyclient'));
  await page.goto(ready.url);await page.locator('#connectionDot.online').waitFor();
  const identities=await census('live');if(process.platform==='win32'){
    assert(identities.some(row=>row.pid===actualPid&&/^python/.test(row.name)),'Actual server identity absent');
    assert(identities.some(row=>row.profile&&/^msedge/i.test(row.name)),'Owned Edge profile identity absent');}
  await page.locator('#newRun').click();assert(!(await page.locator('#adaptiveTeam').isChecked()));
  const savedConfig=await (await context.request.get(origin+'/api/config')).json();
  await page.locator('#workersPerPM').evaluate(node=>{node.value='2';node.dispatchEvent(new Event('input',{bubbles:true}));});
  await nativeTab('#adaptiveTeam','adaptive-checkbox');await page.keyboard.press('Space');
  assert(await page.locator('#workersPerPM').isDisabled());assert.equal(await page.locator('#workersPerPM').inputValue(),'2');
  await page.locator('#useOrchestrationDefaults').click();assert(await page.locator('#adaptiveTeam').isChecked());
  await page.locator('#adaptiveTeam').uncheck();assert(!(await page.locator('#workersPerPM').isDisabled()));
  const afterConfig=await (await context.request.get(origin+'/api/config')).json();assert.deepEqual(afterConfig,savedConfig);
  await page.locator('#toggleBrief').click();
  const manual=await startRun(ready.tasks.manual,false);
  let snapshot=await until('manual-complete',value=>value.runs.find(run=>run.id===manual.id)?.status==='done');
  assert(!Object.hasOwn(snapshot.runs.find(run=>run.id===manual.id),'formation'));
  assert(snapshot.agents.filter(agent=>agent.run_id===manual.id).every(agent=>!Object.hasOwn(agent,'kind')));
  assert(await page.locator('#formationPanel').isHidden());report.checks.push('manual-mode-and-run-only-draft');
  const adaptive=await startRun(ready.tasks.adaptive,true);
  snapshot=await until('reviewing',value=>value.runs.find(run=>run.id===adaptive.id)?.formation?.phase==='reviewing');
  const current=snapshot.runs.find(run=>run.id===adaptive.id),reviewer=snapshot.agents.find(agent=>agent.id===current.formation.reviewer_id);
  assert.equal(current.agent_ids.length,3);assert.equal(current.pm_agent_ids.length,1);assert.equal(current.formation.worker_ids.length,1);
  assert.equal(reviewer.parent_id,null);assert(!current.pm_agent_ids.includes(reviewer.id));assert(!Object.hasOwn(reviewer,'hierarchy'));
  assert.equal(reviewer.kind,'independent_reviewer');assert.equal(reviewer.message_eligibility.allowed,false);assert.notEqual(current.status,'done');
  await text('#formationSummary','独立レビュー中');
  for(const viewport of [{width:1366,height:768},{width:820,height:768},{width:390,height:844}]){
    await page.setViewportSize(viewport);await nativeTab('#formationDetails > summary','formation-details-'+viewport.width);
    await page.keyboard.press('Space');assert(await page.locator('#formationDetails').evaluate(node=>node.open));
    await text('#formationContent','次のモデル要求へ取込 0 件');
    await page.screenshot({path:path.join(OUT,'reviewing-'+viewport.width+'.png'),caret:'initial'});report.screenshots.push('reviewing-'+viewport.width+'.png');
    await page.keyboard.press('Space');assert(!(await page.locator('#formationDetails').evaluate(node=>node.open)));
  }
  await page.setViewportSize({width:1366,height:768});
  await nativeTab(`#agentCards [data-agent-id="${reviewer.id}"]`,'independent-reviewer-card');await page.keyboard.press('Enter');
  await text('#conversationMeta','独立レビュワー');assert(await page.locator('#sendMessage').isDisabled());
  await page.locator(`#agentCards [data-agent-id="${current.pm_agent_ids[0]}"]`).click();
  await page.locator('#messageInput').fill('Unsent human draft remains with PM.');
  await page.locator('#formationDetails > summary').click();await page.locator('#formationDetails > summary').focus();
  const stable=()=>page.evaluate(()=>({open:document.querySelector('#formationDetails').open,draft:document.querySelector('#messageInput').value,
    focus:document.activeElement===document.querySelector('#formationDetails > summary'),x:scrollX,y:scrollY,
    details:document.querySelector('#formationContent').scrollTop,sidebar:document.querySelector('.sidebar').scrollTop}));
  const baseline=await stable();
  const polled=await page.waitForResponse(response=>response.request().method()==='GET'&&new URL(response.url()).pathname==='/api/state');
  await polled.finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));assert.deepEqual(await stable(),baseline);
  report.checks.push('mandatory-independent-reviewer-and-native-disclosure');
  await command('review');snapshot=await until('accepted-not-complete',value=>value.runs.find(run=>run.id===adaptive.id)?.formation?.phase==='accepted');
  const accepted=snapshot.runs.find(run=>run.id===adaptive.id);assert.notEqual(accepted.status,'done');
  assert.equal(accepted.formation.candidate.read_count,1);assert.equal(accepted.formation.candidate.consumed_read_count,1);
  await text('#formationSummary','PM完了待ち');assert.equal(await page.locator('#messageInput').inputValue(),baseline.draft);
  await command('finish');snapshot=await until('adaptive-complete',value=>value.runs.some(run=>run.id===adaptive.id&&run.formation?.phase==='complete'&&run.status==='done'));
  const completed=snapshot.runs.find(run=>run.id===adaptive.id);assert.equal(completed.status,'done');
  await text('#formationSummary','PM完了を確認');report.checks.push('current-artifact-read-consumed-accepted-exact-finish');
  await page.goto('about:blank');await command('archive');
  const archivedReady=await frame(row=>row.kind==='ready'&&row.phase==='archive','Archive fixture ready');assert(!stopping,'Work has stopped');origin=new URL(archivedReady.url).origin;
  assert.equal(archivedReady.pid,actualPid);
  const archiveOrigin=origin,archiveLaunch=new URL(archivedReady.url),archiveToken=new URLSearchParams(archiveLaunch.hash.slice(1)).get('token');
  assert(archiveToken&&archiveToken!==new URLSearchParams(new URL(ready.url).hash.slice(1)).get('token'),'Fresh archive bootstrap token required');
  const archiveObservation=report.archiveObservation;
  context.on('request',request=>{
    if(['GET','HEAD','OPTIONS'].includes(request.method()))return;
    const url=new URL(request.url());
    const entry={method:request.method(),path:url.pathname,expectedOrigin:url.origin===archiveOrigin,hasQuery:Boolean(url.search)};
    // Authentication is the only allowed mutation. Never retain its token/header/body.
    let emptyBody=false;
    try{const body=request.postDataJSON();emptyBody=body!==null&&typeof body==='object'&&!Array.isArray(body)&&Object.keys(body).length===0;}catch{}
    const exact=request.method()==='POST'&&request.url()===archiveOrigin+'/api/bootstrap'&&
      request.headers()['x-workbench-bootstrap']===archiveToken&&emptyBody;
    if(exact&&archiveObservation.bootstrap.length===0)archiveObservation.bootstrap.push({...entry,tokenVerified:true,emptyBodyVerified:true});
    else archiveObservation.mutations.push({...entry,reason:exact?'duplicate_bootstrap':'not_exact_bootstrap'});
  });
  archiveObservation.started=true;
  await page.goto(archivedReady.url);await page.locator('#connectionDot.online').waitFor();
  snapshot=await until('archive-loaded',value=>value.runs.some(run=>run.id===adaptive.id&&run.archived));
  const archived=snapshot.runs.find(run=>run.id===adaptive.id);assert.deepEqual(archived.formation,completed.formation);assert(archived.read_only);
  await page.locator(`#runList [data-focus-key="run:${adaptive.id}"]`).click();await text('#formationSummary','保存時点');
  assert(await page.locator('#stopRun').isDisabled());await page.locator(`#agentCards [data-agent-id="${reviewer.id}"]`).click();
  assert(await page.locator('#sendMessage').isDisabled());await text('#conversationMeta','独立レビュワー');
  await page.locator('#formationDetails > summary').click();await page.locator(`#agentTabs [data-focus-key="tab:${current.pm_agent_ids[0]}"]`).click();
  const archivePoll=await page.waitForResponse(response=>response.request().method()==='GET'&&new URL(response.url()).pathname==='/api/state');await archivePoll.finished();
  await page.screenshot({path:path.join(OUT,'archive.png'),caret:'initial'});report.screenshots.push('archive.png');
  archiveObservation.navigationComplete=true;assert.equal(archiveObservation.bootstrap.length,1);assert.deepEqual(archiveObservation.mutations,[]);
  report.checks.push('persisted-archive-readonly-no-execution');
}
async function main(){
  try{await bounded(execute(),200000,'Adaptive browser session');}
  catch(error){report.errors.push(clean(error.stack||error));}
  finally{
    stopping=true;
    try{if(context){await bounded(context.close(),20000,'Owned context close');report.lifecycle.contextClosed=true;}
      if(browser){if(browser.isConnected())await bounded(browser.close(),10000,'Owned browser close');report.lifecycle.browserClosed=!browser.isConnected();}
      else report.lifecycle.browserClosed=report.lifecycle.contextClosed;
    }catch(error){report.errors.push(clean(error.stack||error));}
    try{if(child&&!shutdownSent&&child.exitCode===null)await command('shutdown');
      if(childExit){const exited=await bounded(childExit,25000,'Fixture normal exit');report.lifecycle.wrapperExit=exited;assert.equal(exited.code,0);}
      const closed=frames.find(row=>row.kind==='closed');assert(closed?.ok===true,'Fixture normal closure ACK missing');
      const ack=JSON.parse(fs.readFileSync(path.join(OUT,'fixture/closure-ack.json'),'utf8'));assert.equal(ack.ok,true);assert.equal(ack.stdin_valid,true);assert.equal(ack.lifecycles.length,2);
      report.lifecycle.fixtureAck=true;
    }catch(error){report.errors.push(clean(error.stack||error));}
    try{if(censusPending){await bounded(censusPending,20000,'Pending census exit');censusPending=null;}
      const remaining=await census('after-normal-close');report.lifecycle.remainingOwned=remaining;
      if(process.platform==='win32')assert.deepEqual(remaining,[],'Owned browser/server processes remain');
      else report.limitations.push('Fresh OS process absence was not measured on this non-Windows host.');
    }catch(error){report.errors.push(clean(error.stack||error));}
    try{assert.deepEqual(sourceRefs(),before,'Source changed during verification');report.sourcePreserved=true;}catch(error){report.errors.push(clean(error.stack||error));}
    const expected=['manual-mode-and-run-only-draft','mandatory-independent-reviewer-and-native-disclosure',
      'current-artifact-read-consumed-accepted-exact-finish','persisted-archive-readonly-no-execution'];
    try{assert.deepEqual(report.checks,expected);assert.deepEqual(report.pageErrors,[]);assert.deepEqual(report.consoleErrors,[]);assert.deepEqual(report.externalRequests,[]);
      assert(report.lifecycle.contextClosed&&report.lifecycle.browserClosed&&report.lifecycle.fixtureAck);
      assert(report.archiveObservation.started&&report.archiveObservation.navigationComplete);
      assert.equal(report.archiveObservation.bootstrap.length,1);assert.deepEqual(report.archiveObservation.mutations,[]);
      assert(report.censusChildren.every(child=>child.ended&&child.exit===0));
    }catch(error){report.errors.push(clean(error.stack||error));}
    report.ok=report.errors.length===0;report.finished_at=new Date().toISOString();save('result.json',report);
  }
  console.log(JSON.stringify({ok:report.ok,result:path.join(OUT,'result.json'),realModelInference:false}));process.exitCode=report.ok?0:1;
}
main().catch(error=>{console.error(clean(error.stack||error));process.exitCode=1;});
