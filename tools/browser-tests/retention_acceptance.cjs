/* Retained real synthetic Engine output + native help. No provider inference. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// Ignore changing GPU readings, but preserve every public history field, ID,
// budget/call counter, report, receipt and event in a detached baseline.
function retainedStateSnapshot(state) {
  assert(Array.isArray(state.runs)&&Array.isArray(state.agents)&&Array.isArray(state.events),
    'Retention requires a full server history snapshot');
  return structuredClone({runs:state.runs,agents:state.agents,events:state.events});
}

async function retentionAcceptance({page,context,origin,workspace,stateDir,providerRequests,artifacts,report,
  assertLayout,resultOption,receiptOption,exported,receiptExport}) {
  const readState=async target=>{
    const response=await target.evaluate(async()=>{
      const response=await fetch('/api/state',{credentials:'same-origin',cache:'no-store'});
      return {status:response.status,state:await response.json()};
    });
    assert.equal(response.status,200,'Retained history remains authenticated');
    return retainedStateSnapshot(response.state);
  };
  const before=await readState(page),run=before.runs.find(item=>item.task==='[SYNTHETIC] Save result.');
  assert(run&&run.status==='done','Reuse the existing completed real synthetic file-writing run');
  const agent=before.agents.find(item=>item.run_id===run.id&&!item.parent_id);
  assert(agent&&agent.results.length===1&&agent.output_receipts.length===1);
  assert(before.runs.some(item=>item.status==='stopped'),'Earlier stopped history also remains available');
  const recordKeys=[resultOption,receiptOption].sort();
  assert.equal(resultOption,'result:'+agent.results[0].id);assert.equal(receiptOption,'receipt:'+agent.output_receipts[0].id);
  const originalView=await page.evaluate(()=>({run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey,
    agent:document.querySelector('#agentCards [aria-pressed="true"]')?.dataset.agentId,
    selected:document.querySelector('#resultSelection').value,draft:document.querySelector('#messageInput').value}));
  const settingsFile=path.join(stateDir,'settings.json'),outputFile=path.join(workspace,'browser-result.txt');
  const settingsBefore=fs.readFileSync(settingsFile,'utf8'),fileBefore=fs.readFileSync(outputFile,'utf8');
  const providersBefore=structuredClone(providerRequests),cookiesBefore=await context.cookies(origin);
  assert(cookiesBefore.some(cookie=>cookie.name.startsWith('workbench_')),'Use the existing authenticated session');
  const mutations=[],downloads=[],helpRequests=[];
  let inspectingHelp=false,sibling;
  const observe=request=>{
    const url=new URL(request.url()),entry={method:request.method(),pathname:url.pathname};
    if(!['GET','HEAD','OPTIONS'].includes(entry.method))mutations.push(entry);
    if(inspectingHelp&&(entry.method!=='GET'||url.origin!==origin||url.pathname!=='/api/state'))helpRequests.push(entry);
  };
  const downloaded=download=>downloads.push(download.suggestedFilename());
  context.on('request',observe);page.on('download',downloaded);
  const newSibling=async()=>{
    const target=await context.newPage();target.setDefaultTimeout(10000);
    // Keep the main smoke's error/network coverage on every reopened tab.
    target.on('pageerror',error=>report.pageErrors.push(error.message));
    target.on('console',message=>{if(/Content Security Policy|violates.*directive/i.test(message.text()))report.cspErrors.push(message.text());});
    target.on('request',request=>{const url=new URL(request.url());if(url.protocol.startsWith('http')&&url.origin!==origin)report.externalRequests.push(url.origin+url.pathname);});
    target.on('download',downloaded);
    await target.addInitScript(()=>{
      window.retentionActions={clipboardWrites:0,objectUrls:0};
      const write=navigator.clipboard.writeText.bind(navigator.clipboard),create=URL.createObjectURL.bind(URL);
      navigator.clipboard.writeText=(...args)=>{window.retentionActions.clipboardWrites++;return write(...args);};
      URL.createObjectURL=(...args)=>{window.retentionActions.objectUrls++;return create(...args);};
    });
    return target;
  };
  const selectRetained=async()=>{
    await sibling.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    assert.equal(new URL(sibling.url()).hash,'','Reopening cannot reuse the one-use bootstrap token');
    await sibling.locator(`#runList .run-link[data-focus-key="run:${run.id}"]`).click();
    await sibling.locator(`#agentCards [data-agent-id="${agent.id}"]`).click();
    await sibling.waitForFunction(id=>document.querySelector(`#agentCards [data-agent-id="${id}"]`)?.getAttribute('aria-pressed')==='true'&&
      !document.querySelector('#resultSelection').disabled,agent.id);
    if(!await sibling.locator('#resultsPanel').evaluate(element=>element.open))await sibling.locator('#resultsPanel > summary').click();
    assert.deepEqual((await sibling.locator('#resultSelection option').evaluateAll(options=>options.map(option=>option.value))).sort(),recordKeys);
    assert.equal(await sibling.locator('#runCount').textContent(),before.runs.length+' / 20');
    assert.match(await sibling.locator('#runCount').getAttribute('aria-label'),/この起動中.*20/);
    await sibling.locator('#resultSelection').selectOption(resultOption);
    assert.equal(await sibling.locator('#resultText').textContent(),agent.results[0].text);
    await sibling.locator('#resultSelection').selectOption(receiptOption);
    assert((await sibling.locator('#resultText').textContent()).includes(agent.output_receipts[0].path));
    assert.match(await sibling.locator('#resultNotice').textContent(),/未確認/);
    await sibling.locator('#resultSelection').selectOption(resultOption);
  };
  const unchanged=async(label,{exports=0}={})=>{
    assert.deepEqual(await readState(sibling),before,label+': server IDs, reports, receipts, logs, events and call counters are unchanged');
    assert.deepEqual(mutations,[],label+': no implicit start, stop, message, settings, key, probe or bootstrap writes');
    assert.deepEqual(helpRequests,[],label+': native help permits only normal state GETs');
    assert.deepEqual(providerRequests,providersBefore,label+': no provider traffic or inference');
    assert.equal(fs.readFileSync(settingsFile,'utf8'),settingsBefore,label+': no settings writes');
    assert.equal(fs.readFileSync(outputFile,'utf8'),fileBefore,label+': saved file remains byte-identical');
    assert.equal(downloads.length,exports,label+': exactly the explicitly requested local downloads');
    assert.deepEqual(await sibling.evaluate(()=>window.retentionActions),{clipboardWrites:0,objectUrls:exports},
      label+': no hidden clipboard or Blob export actions');
    assert.equal(JSON.stringify(await context.cookies(origin))===JSON.stringify(cookiesBefore),true,
      label+': same session cookies (values intentionally omitted from diagnostics)');
    assert.equal(await sibling.evaluate(()=>localStorage.length+sessionStorage.length),0,label+': no browser history persistence');
  };
  const paint=()=>sibling.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const poll=async()=>{
    const response=await sibling.waitForResponse(response=>new URL(response.url()).pathname==='/api/state'&&response.request().method()==='GET');
    assert.equal(response.status(),200);await response.finished();await paint();
  };
  const reachable=async(selector,label)=>{
    const target=sibling.locator(selector);await target.evaluate(element=>element.scrollIntoView({block:'center',inline:'nearest'}));await paint();
    const box=await target.evaluate(element=>{
      const rect=element.getBoundingClientRect();let left=0,right=innerWidth,top=0,bottom=innerHeight;
      for(let parent=element.parentElement;parent;parent=parent.parentElement){
        const style=getComputedStyle(parent),area=parent.getBoundingClientRect();
        if(/auto|scroll|hidden|clip/.test(style.overflowX)){left=Math.max(left,area.left+parent.clientLeft);right=Math.min(right,area.left+parent.clientLeft+parent.clientWidth);}
        if(/auto|scroll|hidden|clip/.test(style.overflowY)){top=Math.max(top,area.top+parent.clientTop);bottom=Math.min(bottom,area.top+parent.clientTop+parent.clientHeight);}
      }
      const hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
      return {x:rect.left,y:rect.top,right:rect.right,bottom:rect.bottom,width:rect.width,height:rect.height,
        left,top,maxRight:right,maxBottom:bottom,hit:hit===element||element.contains(hit)};
    });
    assert(box.width>0&&box.height>0,label+': usable area for '+selector);
    assert(box.x>=box.left-1&&box.right<=box.maxRight+1,label+': horizontal clipping: '+selector);
    assert(box.y>=box.top-1&&box.bottom<=box.maxBottom+1,label+': unreachable by native scrolling: '+selector);
    assert.equal(box.hit,true,label+': obscured center: '+selector);
  };
  const essentialHelp=async()=>{
    const essential=sibling.locator('#historyRetention'),resultHelp=sibling.locator('#resultRetentionHelp');
    assert.equal(await essential.isVisible(),true);
    assert.equal(await essential.evaluate(element=>element.closest('details')===null),true,'Essential lifetime note is always outside optional help');
    assert.match(await essential.textContent(),/サーバー終了で消えます/);assert.match(await essential.textContent(),/報告・保存記録.*\.txt 保存/);
    assert.equal(await resultHelp.isVisible(),true);
    assert.equal(await resultHelp.evaluate(element=>element.closest('details').id),'resultsPanel','Export scope is not hidden inside history details');
    assert.match(await resultHelp.textContent(),/選択中の1件だけ/);assert.match(await resultHelp.textContent(),/ファイル本体は含みません/);
    assert((await sibling.locator('#exportResult').getAttribute('aria-describedby')||'').split(/\s+/).includes('resultRetentionHelp'));
  };
  try {
    sibling=await newSibling();await sibling.goto(origin+'/');await selectRetained();
    await unchanged('Same-context sibling open');
    await sibling.reload();await selectRetained();await unchanged('Reload retains completed and stopped histories');
    // Close only this sibling. The original page and BrowserContext stay alive;
    // this deliberately makes no browser-restart/session-restoration claim.
    await sibling.close();sibling=await newSibling();await sibling.goto(origin+'/');await selectRetained();
    await unchanged('Tab close/reopen retains the same server history and session');
    const details=sibling.locator('#historyDetails'),summary=details.locator(':scope > summary');
    assert.equal(await details.evaluate(element=>element.localName),'details');
    assert.equal(await details.evaluate(element=>element.firstElementChild.localName),'summary');
    assert.equal(await details.evaluate(element=>element.closest('.results-content')!==null),true);
    assert.equal(await details.evaluate(element=>element.open),false,'Optional history details start collapsed');
    assert.equal(await summary.textContent(),'履歴の保持・終了について');
    const help=await sibling.locator('#historyLifetimeHelp').textContent();
    for(const phrase of ['担当者ごとに最新20件','各24,000文字まで','64件の保存記録','200件のログ',
      '上限を超えた記録や本文は、表示用の履歴から省略します','ダウンロード完了を確認','タブを閉じたり再読み込みしても',
      'サーバーと実行中の作業は停止しません','選択したチームだけを止め、履歴は保持',
      'コンソールを閉じるか Ctrl+C','すべてのチームの履歴と入力した API キーは失われます',
      '設定ファイルは残り','環境変数のキーは次の起動時の環境','未送信の下書き','再接続は保証しません',
      'サーバーの終了では削除しません','現在のファイルの存在・内容は未確認'])assert(help.includes(phrase),'Missing retention boundary: '+phrase);
    assert.equal(await sibling.locator('#historyLifetimeHelp').locator('a,button,input,textarea,select,summary,[tabindex],[contenteditable],[role="button"]').count(),0,
      'History guidance contains no actions or extra tab stops');
    inspectingHelp=true;
    await essentialHelp();
    await sibling.locator('#resultText').focus();await sibling.keyboard.press('Tab');
    assert.equal(await summary.evaluate(element=>element===document.activeElement),true,'Native disclosure follows selected result text in keyboard order');
    await sibling.keyboard.press('Enter');assert.equal(await details.evaluate(element=>element.open),true);
    await sibling.keyboard.press('Space');assert.equal(await details.evaluate(element=>element.open),false);
    await sibling.keyboard.press('Enter');await poll();
    assert.equal(await details.evaluate(element=>element.open),true,'Normal polling preserves expanded help');
    assert.equal(await summary.evaluate(element=>element===document.activeElement),true,'Polling preserves native disclosure focus');
    await sibling.keyboard.press('Shift+Tab');
    assert.equal(await sibling.locator('#resultText').evaluate(element=>element===document.activeElement),true,
      'Native backward navigation returns to the existing selected result text');
    await sibling.keyboard.press('Tab');await sibling.keyboard.press('Tab');
    assert.equal(await details.evaluate(element=>element.contains(document.activeElement)),false,
      'Text-only help adds no keyboard stops before existing conversation controls');
    for(const [name,width,height] of [['desktop',1366,768],['tablet',820,900],['narrow',390,844]]) {
      await sibling.setViewportSize({width,height});
      for(const expanded of [false,true]) {
        const state=expanded?'expanded':'collapsed',label=`retention ${name} ${state}`;
        if(await details.evaluate(element=>element.open)!==expanded)await summary.click();
        assert.equal(await details.evaluate(element=>element.open),expanded);
        assert.equal(await sibling.locator('#historyLifetimeHelp').isVisible(),expanded);
        await essentialHelp();await assertLayout(sibling,label);
        const textUnclipped=await sibling.locator('#historyRetention,#resultRetentionHelp,#historyDetails > summary'+
          (expanded?',#historyLifetimeHelp p':'')).evaluateAll(elements=>elements.every(element=>element.scrollWidth<=element.clientWidth+1&&element.scrollHeight<=element.clientHeight+1));
        assert.equal(textUnclipped,true,label+': guidance text wraps without clipping');
        await reachable('#historyRetention',label);
        await sibling.screenshot({path:path.join(artifacts,`workbench-retention-${name}-${state}-sessions.png`),fullPage:false,animations:'disabled'});
        // Every retained run remains pointer reachable; long sidebar guidance
        // must never consume the entire existing scrollable session list.
        for(const retained of before.runs)await reachable(`#runList .run-link[data-focus-key="run:${retained.id}"]`,label);
        for(const selector of ['#resultSelection','#copyResult','#exportResult','#resultRetentionHelp'])await reachable(selector,label);
        if(!expanded)await sibling.screenshot({path:path.join(artifacts,`workbench-retention-${name}-export-scope.png`),fullPage:false,animations:'disabled'});
        await reachable('#historyDetails > summary',label);
        await sibling.screenshot({path:path.join(artifacts,`workbench-retention-${name}-${state}-help.png`),fullPage:false,animations:'disabled'});
        if(expanded)for(let index=0;index<await sibling.locator('#historyLifetimeHelp p').count();index++){
          await reachable(`#historyLifetimeHelp p:nth-child(${index+1})`,label);
          await sibling.screenshot({path:path.join(artifacts,`workbench-retention-${name}-expanded-detail-${index+1}.png`),fullPage:false,animations:'disabled'});
        }
        await reachable('#messageInput',label);await assertLayout(sibling,label+' controls');
        await unchanged(label);
      }
    }
    await sibling.setViewportSize({width:1366,height:768});
    await unchanged('Native help has no copy, export, settings, run or network side effects');
    inspectingHelp=false;
    const saveSelected=async(key,name,expected)=>{
      await sibling.locator('#resultSelection').selectOption(key);
      const pending=sibling.waitForEvent('download');await sibling.locator('#exportResult').click();
      const download=await pending;assert.equal(download.suggestedFilename(),name);
      assert.equal(fs.readFileSync(await download.path(),'utf8'),expected,'Reload/reopen export is byte-identical to the original single selected record');
    };
    await saveSelected(resultOption,'workbench-result.txt',exported);
    assert(!exported.includes(agent.output_receipts[0].path),'Report export cannot aggregate the separate save receipt');
    await saveSelected(receiptOption,'workbench-save-receipt.txt',receiptExport);
    assert(!receiptExport.includes(agent.results[0].text),'Receipt export cannot aggregate the separate report');
    assert(!receiptExport.includes(fileBefore),'Receipt export is metadata, not saved file bytes');
    assert.deepEqual(downloads,['workbench-result.txt','workbench-save-receipt.txt']);
    await unchanged('Two explicit single-record exports',{exports:2});
    assert.deepEqual(await page.evaluate(()=>({run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey,
      agent:document.querySelector('#agentCards [aria-pressed="true"]')?.dataset.agentId,
      selected:document.querySelector('#resultSelection').value,draft:document.querySelector('#messageInput').value})),originalView,
    'Sibling retention checks preserve the existing smoke page, selection and unsent draft');
    report.checks.push('retention: actual completed synthetic Engine report/receipt and earlier stopped history survive reload and same-cookie tab close/reopen with identical IDs, logs, events, calls and file bytes; native help states server lifetime, 20-run cap, per-agent 20 reports/24,000 chars/64 receipts/200 logs, stop versus exit, memory-key versus environment scope and single-selected metadata exports; Enter/Space/poll-stable focus, all run links and existing controls reachable at desktop/tablet/narrow sizes; screenshots; no implicit mutation, probe, inference, copy, Blob or download; exactly two explicit byte-identical .txt exports');
  } catch(error) {
    if(sibling&&!sibling.isClosed())await sibling.screenshot({path:path.join(artifacts,'workbench-retention-failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});
    throw error;
  } finally {
    inspectingHelp=false;
    if(sibling&&!sibling.isClosed())await sibling.close();
    context.off('request',observe);page.off('download',downloaded);
  }
}

module.exports={retentionAcceptance,retainedStateSnapshot};
