/* First-task guidance on the real page; no runs, settings writes or inference. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// The caller keeps its existing preflight and modal lifecycle actions. These
// checkpoints only add guidance assertions and leave the later scenarios intact.
async function firstTaskAcceptance({page,stateDir,providerRequests,artifacts,report,assertDialogLayout,phase='fresh'}) {
  const details=page.locator('#taskExamples'),summary=details.locator(':scope > summary');
  const settingsFile=path.join(stateDir,'settings.json');
  const savedSettings=()=>fs.existsSync(settingsFile)?fs.readFileSync(settingsFile,'utf8'):null;
  const snapshot=()=>page.evaluate(()=>({
    task:document.querySelector('#taskInput').value,
    pm:document.querySelector('#pmProfile').value,
    workers:[...document.querySelectorAll('#workerProfiles input')].map(input=>({value:input.value,checked:input.checked})),
    maxWorkers:document.querySelector('#maxWorkers').value,
    settings:[...document.querySelectorAll('#settingsForm input,#settingsForm select,#settingsForm textarea')]
      .map(input=>({id:input.id,value:input.value,checked:input.checked??null})),
  }));
  const before=await snapshot(),persisted=savedSettings(),providerBefore=structuredClone(providerRequests);
  const mutations=[];
  const observe=request=>{
    const pathname=new URL(request.url()).pathname;
    if(!['GET','HEAD','OPTIONS'].includes(request.method())&&pathname!=='/api/run-preflight')
      mutations.push({method:request.method(),pathname});
  };
  page.on('request',observe);
  let task=before.task;
  const unchanged=async label=>{
    assert.deepEqual(await snapshot(),{...before,task},label+': guidance cannot change the draft, PM, workers, worker limit or settings');
    assert.equal(savedSettings(),persisted,label+': persisted settings cannot change');
    assert.deepEqual(mutations,[],label+': no implicit config, credential, provider-test or run writes');
    assert.deepEqual(providerRequests,providerBefore,label+': no provider traffic');
    assert.equal(await page.locator('#runList .run-link').count(),0,label+': no implicit run');
  };
  const helpVisible=async()=>{
    const help=page.locator('#taskHelp');
    assert.equal(await help.isVisible(),true,'Essential guidance remains visible after typing and when examples are closed');
    assert.equal(await help.evaluate(element=>element.closest('details')===null),true,'Essential limits cannot be hidden inside a disclosure');
    assert.match(await help.textContent(),/文章.*ファイル.*読み書き/);
    assert.match(await help.textContent(),/コマンド・ビルド・テストは実行できません/);
    assert((await page.locator('#taskInput').getAttribute('aria-describedby')||'').split(/\s+/).includes('taskHelp'),
      'Task input has persistent accessible help, not only a disappearing placeholder');
  };
  const assertPreserved=async label=>{
    assert.equal(await details.evaluate(element=>element.open),true,label+': examples remain expanded');
    await helpVisible();await unchanged(label);
  };
  const assertDraft=async draft=>{task=draft;await assertPreserved(phase+' real draft preflight');};
  const reachable=async(selector,label)=>{
    for(const control of await page.locator(selector).all()) {
      await control.scrollIntoViewIfNeeded();
      const box=await control.evaluate(element=>{
        const rect=element.getBoundingClientRect(),dialog=element.closest('dialog').getBoundingClientRect();
        const hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
        return {width:rect.width,height:rect.height,left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,
          minX:Math.max(0,dialog.left),maxX:Math.min(innerWidth,dialog.right),
          minY:Math.max(0,dialog.top),maxY:Math.min(innerHeight,dialog.bottom),hit:element===hit||element.contains(hit)};
      });
      assert(box.width>0&&box.height>0,label+': control has a usable area: '+selector);
      assert(box.left>=box.minX-1&&box.right<=box.maxX+1,label+': control clipped horizontally: '+selector);
      assert(box.top>=box.minY-1&&box.bottom<=box.maxY+1,label+': control unreachable by dialog scroll: '+selector);
      assert.equal(box.hit,true,label+': control is obscured: '+selector);
    }
  };
  const capture=async draft=>{
    await assertDraft(draft);
    for(const [name,width,height] of [['desktop',1366,768],['tablet',820,900],['narrow',390,844]]) {
      await page.setViewportSize({width,height});
      for(const expanded of [false,true]) {
        const state=expanded?'expanded':'collapsed',label=`first task ${name} ${state}`;
        if(await details.evaluate(element=>element.open)!==expanded)await summary.click();
        assert.equal(await details.evaluate(element=>element.open),expanded,label+': native pointer disclosure');
        assert.equal(await details.locator('.task-example-list').isVisible(),expanded,label+': examples visibility');
        await helpVisible();await unchanged(label);await assertDialogLayout(page,'#taskDialog',label);
        const unclipped=await page.locator('#taskHelp,#taskExamples > summary,#taskExamples[open] .task-example-list > section')
          .evaluateAll(elements=>elements.every(element=>element.scrollWidth<=element.clientWidth+1&&element.scrollHeight<=element.clientHeight+1));
        assert.equal(unclipped,true,label+': guidance text is not clipped');
        await page.locator('#taskDialog').evaluate(dialog=>{dialog.scrollTop=0;});
        const framed=await page.locator('#taskInput,#taskHelp,#taskExamples > summary').evaluateAll(elements=>elements.every(element=>{
          const box=element.getBoundingClientRect(),dialog=element.closest('dialog').getBoundingClientRect();
          return box.top>=Math.max(0,dialog.top)-1&&box.bottom<=Math.min(innerHeight,dialog.bottom)+1;
        }));
        assert.equal(framed,true,label+': screenshot must frame the input, essential limits and disclosure');
        await page.screenshot({path:path.join(artifacts,`workbench-first-task-${name}-${state}.png`),fullPage:false,animations:'disabled'});
        if(expanded) {
          await details.evaluate(element=>element.scrollIntoView({block:'start'}));
          await page.screenshot({path:path.join(artifacts,`workbench-first-task-${name}-expanded-examples.png`),fullPage:false,animations:'disabled'});
        }
        // Native modal scrolling is allowed, but all existing controls must be
        // genuinely reachable, including the Start/settings actions below it.
        for(const selector of ['#toggleBrief','#taskInput','#taskExamples > summary','#pmProfile','#maxWorkers','#workerProfiles input','#preflightSettings','#startRun'])
          await reachable(selector,label);
        await assertDialogLayout(page,'#taskDialog',label+' controls');
        await page.screenshot({path:path.join(artifacts,`workbench-first-task-${name}-${state}-controls.png`),fullPage:false,animations:'disabled'});
      }
    }
    await page.setViewportSize({width:1366,height:768});
    await assertPreserved('Responsive guidance');
  };

  assert.equal(await details.evaluate(element=>element.localName),'details');
  assert.equal(await details.evaluate(element=>element.firstElementChild.localName),'summary');
  assert.equal(await summary.textContent(),'依頼例と必要な設定');
  assert.equal(await details.evaluate(element=>element.open),false,phase+': examples begin collapsed');
  const examples=details.locator('.task-example-list > section');
  assert.equal(await examples.count(),3,'Exactly three examples');
  assert.deepEqual(await examples.locator('h3').allTextContents(),['文章だけで始める','許可したファイルを使う','公開 Web の資料を調べる']);
  assert.equal(await details.locator('.task-example-list').locator('a,button,input,textarea,select,summary,[tabindex],[contenteditable],[role="button"]').count(),0,
    'Examples are text, not preset buttons or settings controls');
  await helpVisible();
  await page.locator('#taskInput').focus();await page.keyboard.press('Tab');
  assert.equal(await summary.evaluate(element=>element===document.activeElement),true,'Disclosure is reachable immediately after the task input');
  await page.keyboard.press('Enter');assert.equal(await details.evaluate(element=>element.open),true,'Enter opens native details');
  await page.keyboard.press('Space');assert.equal(await details.evaluate(element=>element.open),false,'Space closes native details');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Tab');assert.equal(await page.locator('#pmProfile').evaluate(element=>element===document.activeElement),true,
    'Expanded textual examples do not add tab stops or replace PM selection');
  await assertPreserved('Keyboard disclosure');

  return {capture,assertDraft,assertPreserved,finish:async()=>{
    await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    await assertPreserved('Settings-to-task round trip');
    await summary.click();assert.equal(await details.evaluate(element=>element.open),false);
    await helpVisible();await unchanged('Guidance complete');page.off('request',observe);
    report.checks.push(phase==='fresh'?
      'fresh first-task guidance: persistent accessible capabilities and command/build/test limit after typing; exactly three text-only examples; native Enter/Space and pointer disclosure; unchanged draft, PM, workers, limit and config with no implicit run/provider traffic; expansion survives real preflight, close/reopen and settings round trip; collapsed/expanded 1366x768, 820x900, 390x844 screenshots plus examples/reachable controls with no horizontal clipping':
      'configured first-task guidance: local PM, local+openai workers, max 1 and exact draft survive native guidance toggles, real ready preflight, Escape/reopen and settings shortcut round trip; examples stay expanded and settings stay unchanged with no implicit run/provider traffic');
  }};
}

module.exports={firstTaskAcceptance};
