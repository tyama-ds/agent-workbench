/* Existing readiness, repeated Local/mixed selection and copy-only focus/layout. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

async function dataUseAcceptance({page,stateDir,providerRequests,artifacts,report,assertDialogLayout,preflightAfter}) {
  const snapshot=()=>page.evaluate(()=>({task:document.querySelector('#taskInput').value,
    pm:document.querySelector('#pmProfile').value,maxWorkers:document.querySelector('#maxWorkers').value,
    workers:[...document.querySelectorAll('#workerProfiles input')].map(input=>({value:input.value,checked:input.checked})),
    settings:[...document.querySelectorAll('#settingsForm input,#settingsForm select,#settingsForm textarea')]
      .map(input=>({id:input.id,value:input.value,checked:input.checked??null}))}));
  const before=await snapshot(),settingsFile=path.join(stateDir,'settings.json'),saved=fs.readFileSync(settingsFile,'utf8');
  const providerBefore=structuredClone(providerRequests),mutations=[];
  const observe=request=>{const pathname=new URL(request.url()).pathname;if(!['GET','HEAD','OPTIONS'].includes(request.method())&&pathname!=='/api/run-preflight')mutations.push({method:request.method(),pathname});};
  page.on('request',observe);
  const note=page.locator('#preflightDetails > p').filter({hasText:/^LOCAL APP は/});
  const checkCopy=async()=>{
    assert.equal(await note.count(),1,'Exactly one data-use note after each preview');
    assert.equal(await note.locator('a,button,input,textarea,select,[tabindex]').count(),0,'Copy adds no focus target');
    const text=await note.textContent();
    for(const phrase of ['アプリの実行場所','プライベート LAN','別の PC','別のモデル接続先','PM・作業者すべての接続先・プロキシ','保存・再転送・学習利用','社内の承認範囲','判定しません'])assert(text.includes(phrase));
    assert.match(await page.locator('#preflightDetails').textContent(),/依頼・会話・作業方針・許可パス.*ファイル内容やツール結果.*検索語・取得 URL/s);
  };
  try {
    assert.equal(before.maxWorkers,'1');await checkCopy();
    for(const count of ['0','1','0','1']) {
      const ready=await preflightAfter(page,async()=>{await page.locator('#maxWorkers').fill(count);await page.locator('#taskInput').focus();},data=>data.max_workers===Number(count));
      assert.equal(ready.destinations.length,count==='0'?1:2);
      assert.equal(await page.locator('#taskInput').evaluate(node=>node===document.activeElement),true,'Readiness copy cannot steal focus');
      await checkCopy();
    }
    await page.locator('.readiness-scope summary').click();
    assert.equal(await page.locator('.readiness-scope').evaluate(node=>node.open),true);
    for(const [name,width,height] of [['desktop',1366,768],['narrow',390,844]]) {
      await page.setViewportSize({width,height});await assertDialogLayout(page,'#taskDialog','data-use '+name);
      await note.scrollIntoViewIfNeeded();
      const widthCheck=await note.evaluate(node=>({scroll:node.scrollWidth,client:node.clientWidth}));
      assert(widthCheck.scroll<=widthCheck.client+1,'Data-use note wraps at '+name+' width');
      await page.screenshot({path:path.join(artifacts,`workbench-data-use-${name}.png`),fullPage:false,animations:'disabled'});
      for(const selector of ['#toggleBrief','#taskInput','#pmProfile','#maxWorkers','#workerProfiles input','#preflightSettings','#startRun']) {
        for(const control of await page.locator(selector).all()) {
          await control.scrollIntoViewIfNeeded();
          const usable=await control.evaluate(node=>{const r=node.getBoundingClientRect(),d=node.closest('dialog').getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return r.width>0&&r.height>0&&r.left>=Math.max(0,d.left)-1&&r.right<=Math.min(innerWidth,d.right)+1&&r.top>=Math.max(0,d.top)-1&&r.bottom<=Math.min(innerHeight,d.bottom)+1&&(node===hit||node.contains(hit));});
          assert(usable,name+': control reachable and unobscured '+selector);
        }
      }
      await page.locator('#preflightSettings').focus();await page.keyboard.press('Tab');
      assert.equal(await page.locator('.policy-preview > summary').evaluate(node=>node===document.activeElement),true,'Copy adds no keyboard stops');
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('#startRun').evaluate(node=>node===document.activeElement),true,'Start remains keyboard reachable');
      await page.screenshot({path:path.join(artifacts,`workbench-data-use-${name}-controls.png`),fullPage:false,animations:'disabled'});
    }
    await page.setViewportSize({width:1366,height:768});
    // Leave the original scope-activation sequence exactly where it began.
    await page.locator('.readiness-scope summary').click();
    assert.equal(await page.locator('.readiness-scope').evaluate(node=>node.open),false);
    await page.locator('#taskInput').focus();
    assert.deepEqual(await snapshot(),before,'Guidance preserves all original form drafts and selections');
    assert.equal(fs.readFileSync(settingsFile,'utf8'),saved,'No settings persistence');
    assert.deepEqual(providerRequests,providerBefore,'No provider requests');assert.deepEqual(mutations,[],'No mutations beyond read-only preflight');
    report.checks.push('data-use note stays single across repeated Local-only/mixed previews, explains other-PC/teammate/downstream limits without approval claims, wraps on desktop/narrow, preserves native control reachability/focus and drafts, and adds no provider traffic or settings writes');
  } finally {page.off('request',observe);}
}
module.exports={dataUseAcceptance};
