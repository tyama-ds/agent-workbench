/* Native disclosure keyboard ownership during real polling. Synthetic state only. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

async function disclosureFocusAcceptance({page,fixture,compactFixture,artifacts,report,
  holdNextRequest,releaseResponse,assertLayout}) {
  const original=structuredClone(fixture),viewport=page.viewportSize();
  const pm=fixture.agents[0],worker=fixture.agents[1],run=fixture.runs[0];
  assert(pm&&worker&&run&&pm.run_id===run.id,'Reuse the selected synthetic team');
  const firstId=7101,lastId=7112,mutations=[];
  const before=await page.evaluate(()=>{
    const active=document.activeElement,log=document.querySelector('#conversationLog'),input=document.querySelector('#messageInput');
    return {draft:input.value,start:input.selectionStart,end:input.selectionEnd,direction:input.selectionDirection,
      expanded:[...log.querySelectorAll('details[open]')].map(detail=>detail.dataset.logId),
      scroll:log.scrollTop,x:scrollX,y:scrollY,resultsOpen:document.querySelector('#resultsPanel').open,
      focusId:active.id,focusKey:active.dataset.focusKey,
      focusLog:active.localName==='summary'?active.parentElement.dataset.logId:null};
  });
  const details=id=>page.locator(`#conversationLog details[data-log-id="${id}"]`);
  const summary=id=>details(id).locator(':scope > summary');
  const focused=target=>target.evaluate(element=>element===document.activeElement);
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const logs=owner=>Array.from({length:lastId-firstId+1},(_,index)=>({
    id:firstId+index,kind:'assistant',at:1791169300+index,
    thinking:`[SYNTHETIC] ${owner} の思考 ${index+1}`,
    text:index===lastId-firstId?'[SYNTHETIC] 最後のログ。':
      `[SYNTHETIC] Disclosure ${owner} log ${index+1}\n読み進めている位置と下書きを保持します。\nポーリングで新しいログが届きます。`,
  }));
  const appended=(id,text='新しく届いたログ。')=>({id,kind:'assistant',text:'[SYNTHETIC] '+text,at:1791169400+id});
  const observe=request=>{
    if(new URL(request.url()).pathname.startsWith('/api/')&&!['GET','HEAD','OPTIONS'].includes(request.method()))
      mutations.push({method:request.method(),path:new URL(request.url()).pathname});
  };
  // Observe an interval-driven request that starts after the fixture edit. Do not
  // call render/poll app internals or accept a previously in-flight response.
  const poll=async(change=()=>{})=>{
    const owner=await page.evaluate(()=>({
      run:document.querySelector('#runList .run-link.selected').dataset.focusKey.slice(4),
      agent:document.querySelector('#agentTabs [aria-pressed="true"]').dataset.focusKey.slice(4),
    }));
    const requested=page.waitForRequest(request=>{
      const url=new URL(request.url());return url.pathname==='/api/state'&&request.method()==='GET'&&
        url.searchParams.get('run_id')===owner.run&&url.searchParams.get('agent_id')===owner.agent;
    });
    change();const request=await requested,response=await request.response();
    assert(response,'An actual state request receives a response');assert.equal(response.status(),200);
    await response.finished();await paint();
    assert.equal(await page.locator('#conversationLog').getAttribute('aria-busy'),'false');
  };
  const scroll=()=>page.locator('#conversationLog').evaluate(element=>({
    top:element.scrollTop,left:element.scrollLeft,x:scrollX,y:scrollY,
    bottom:element.scrollHeight-element.clientHeight-element.scrollTop,
  }));
  const sameScroll=async(saved,label)=>{
    const current=await scroll();
    for(const key of ['top','left','x','y'])assert(Math.abs(current[key]-saved[key])<=1,
      `${label}: ${key} changed from ${saved[key]} to ${current[key]}`);
  };
  const visible=async(target,label)=>{
    const area=await target.evaluate(element=>{
      const box=element.getBoundingClientRect();let left=0,top=0,right=innerWidth,bottom=innerHeight;
      for(let parent=element.parentElement;parent;parent=parent.parentElement){
        const style=getComputedStyle(parent),rect=parent.getBoundingClientRect();
        if(/auto|scroll|hidden|clip/.test(style.overflowX)){left=Math.max(left,rect.left+parent.clientLeft);right=Math.min(right,rect.left+parent.clientLeft+parent.clientWidth);}
        if(/auto|scroll|hidden|clip/.test(style.overflowY)){top=Math.max(top,rect.top+parent.clientTop);bottom=Math.min(bottom,rect.top+parent.clientTop+parent.clientHeight);}
      }
      const hit=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2);
      return {width:box.width,height:box.height,left:box.left,top:box.top,right:box.right,bottom:box.bottom,
        clipLeft:left,clipTop:top,clipRight:right,clipBottom:bottom,hit:hit===element||element.contains(hit)};
    });
    assert(area.width>0&&area.height>0,label+': focused control has visible area');
    assert(area.left>=area.clipLeft-1&&area.right<=area.clipRight+1&&
      area.top>=area.clipTop-1&&area.bottom<=area.clipBottom+1,label+': focused control stays inside visible scroll regions');
    assert.equal(area.hit,true,label+': focused control is not obscured');
  };
  const keyboardToggle=async(id,key,open,label)=>{
    assert.equal(await focused(summary(id)),true,label+': keyboard starts on the intended summary');
    await page.keyboard.press(key);await paint();
    assert.equal(await details(id).evaluate(element=>element.open),open,label+': '+key+' toggles native details');
    assert.equal(await focused(summary(id)),true,label+': native activation retains focus');
  };
  const capture=async(name,target)=>{
    // Screenshots must observe production focus placement, never repair it first.
    await paint();await visible(target,name);await assertLayout(page,name);
    await page.screenshot({path:path.join(artifacts,'workbench-disclosure-'+name+'.png'),fullPage:false,animations:'disabled'});
  };
  const selectAgent=async(id,owner)=>{
    const tab=page.locator(`#agentTabs [data-focus-key="tab:${id}"]`);
    await tab.focus();await page.keyboard.press('Enter');
    await page.locator('#conversationLog[aria-busy="false"]').filter({hasText:'Disclosure '+owner+' log 1'}).waitFor();
    assert.equal(await focused(tab),true,'A selection response retains the user-selected agent tab');
  };
  const selectRun=async(id,owner)=>{
    const link=page.locator(`#runList [data-focus-key="run:${id}"]`);
    await link.focus();await page.keyboard.press('Enter');
    await page.locator('#conversationLog[aria-busy="false"]').filter({hasText:'Disclosure '+owner+' log 1'}).waitFor();
    assert.equal(await focused(link),true,'A selection response retains the user-selected team link');
  };
  let held;
  page.on('request',observe);
  try {
    if(before.resultsOpen){await page.locator('#resultsPanel > summary').focus();await page.keyboard.press('Enter');}
    for(const [name,width,height] of [['desktop',1366,768],['narrow',390,844]]) {
      await page.setViewportSize({width,height});
      await poll(()=>{pm.logs=logs('PM');});
      const draft=`[SYNTHETIC] ${name} 未送信の下書き。\n選択範囲も保持します。`;
      await page.locator('#messageInput').fill(draft);
      // Enter the first native summary using Tab, not a synthetic click handler.
      await page.locator('#conversationHeading').focus();await page.keyboard.press('Tab');
      if(await page.locator('#humanQuestion').isVisible()){
        assert.equal(await focused(page.locator('#humanQuestion')),true,'The selected human question is a native keyboard reading region');
        await page.keyboard.press('Tab');
      }
      assert.equal(await focused(page.locator('#resultsPanel > summary')),true,'The existing results disclosure keeps its keyboard position');
      await page.keyboard.press('Tab');
      assert.equal(await focused(summary(firstId)),true,'Native Tab reaches the first disclosure');
      assert.equal(await details(firstId).evaluate(element=>element.open),false);
      await keyboardToggle(firstId,'Enter',true,name+' initial Enter');
      await keyboardToggle(firstId,'Space',false,name+' initial Space');
      await keyboardToggle(firstId,'Enter',true,name+' reopened');
      await summary(firstId).scrollIntoViewIfNeeded();await paint();
      const key=await summary(firstId).getAttribute('data-focus-key');assert(key,'Native summaries have stable focus identities');
      const keys=await page.locator('#conversationLog summary').evaluateAll(elements=>elements.map(element=>element.dataset.focusKey));
      assert(keys.every(Boolean)&&new Set(keys).size===keys.length,'Every rendered disclosure has a distinct focus identity');
      const reading=await scroll();assert(reading.bottom>70,'The read-position case is outside automatic bottom following');
      await summary(firstId).evaluate(element=>{window.disclosureFocusNode=element;});
      await poll();
      assert.equal(await summary(firstId).evaluate(element=>element===window.disclosureFocusNode),true,'Unchanged polling retains the actual native node');
      assert.equal(await focused(summary(firstId)),true);await sameScroll(reading,name+' unchanged poll');
      assert.equal(await details(firstId).evaluate(element=>element.open),true);
      await poll(()=>pm.logs.push(appended(7201)));
      assert.equal(await page.evaluate(()=>window.disclosureFocusNode.isConnected),false,'Changed history really replaced the focused node');
      assert.equal(await summary(firstId).getAttribute('data-focus-key'),key,'A retained log keeps its focus identity');
      assert.equal(await focused(summary(firstId)),true,'Appended history restores the same summary instead of BODY');
      assert.equal(await details(firstId).evaluate(element=>element.open),true,'Appended history retains expanded content');
      await sameScroll(reading,name+' appended log');await visible(summary(firstId),name+' appended log');
      assert.equal(await page.locator('#messageInput').inputValue(),draft);
      await keyboardToggle(firstId,'Space',false,name+' Space after arrival');
      await keyboardToggle(firstId,'Enter',true,name+' Enter after arrival');
      await capture(name+'-retained',summary(firstId));

      // Even within the normal <=70px bottom-follow threshold, a focused summary
      // must not be scrolled away when a large new arrival replaces the history.
      await poll(()=>{pm.logs=logs('PM');});
      await summary(lastId).focus();await keyboardToggle(lastId,'Enter',true,name+' last disclosure');
      await page.locator('#conversationLog').evaluate(element=>{element.scrollTop=element.scrollHeight;});
      await summary(lastId).evaluate(element=>element.scrollIntoView({block:'nearest',inline:'nearest'}));await paint();
      const nearBottom=await scroll();assert(nearBottom.bottom<=70,'Focused-summary case exercises the bottom-follow threshold');
      await visible(summary(lastId),name+' before near-bottom arrival');
      await poll(()=>pm.logs.push(appended(7202,'大きな新着ログ。\n'.repeat(40))));
      assert.equal(await focused(summary(lastId)),true);assert.equal(await details(lastId).evaluate(element=>element.open),true);
      await sameScroll(nearBottom,name+' near-bottom arrival');await visible(summary(lastId),name+' after near-bottom arrival');
      await keyboardToggle(lastId,'Space',false,name+' near-bottom Space');
      await keyboardToggle(lastId,'Enter',true,name+' near-bottom Enter');
      await capture(name+'-near-bottom',summary(lastId));

      // Remove a whole earlier batch while reading in the middle. Keep the tall
      // tail, so preserving/clamping the old scrollTop cannot reveal the fallback.
      const evictedId=firstId+7,fallbackId=evictedId+1;
      await summary(evictedId).focus();
      await summary(evictedId).evaluate(element=>element.scrollIntoView({block:'center',inline:'nearest'}));await paint();
      assert((await scroll()).top>150,'Multi-record eviction begins partway through retained history');
      await poll(()=>{pm.logs=pm.logs.filter(log=>log.id>evictedId);});
      assert.equal(await details(evictedId).count(),0,'Batch eviction removes the focused log from visible history');
      assert.equal(await page.locator('#conversationLog summary').count(),lastId-evictedId);
      assert.equal(await focused(summary(fallbackId)),true,'Batch eviction chooses the next surviving nearby native summary');
      await visible(summary(fallbackId),name+' immediate batch-eviction fallback');
      await keyboardToggle(fallbackId,'Space',true,name+' fallback Space');
      await keyboardToggle(fallbackId,'Enter',false,name+' fallback Enter');
      await capture(name+'-eviction',summary(fallbackId));
      if(name==='narrow'){
        await summary(fallbackId).evaluate(element=>element.scrollIntoView({block:'start',inline:'nearest'}));await paint();
        assert(await page.locator('#conversationHeading').evaluate(element=>element.getBoundingClientRect().top<0),
          'Narrow final eviction starts with the existing heading above the viewport');
      }
      await poll(()=>{pm.logs=[appended(7203,'思考の詳細を持たない長い履歴。\n'.repeat(40))];});
      assert.equal(await page.locator('#conversationLog summary').count(),0);
      assert.equal(await focused(page.locator('#conversationHeading')),true,'When no disclosure survives, focus returns to the existing conversation heading');
      await visible(page.locator('#conversationHeading'),name+' immediate heading fallback');
      await capture(name+'-heading-fallback',page.locator('#conversationHeading'));

      await poll(()=>{pm.logs=logs('PM');});
      assert.equal(await focused(page.locator('#conversationHeading')),true,'New details cannot steal focus from the heading');
      await page.locator('#messageInput').fill(draft);await page.locator('#messageInput').focus();
      await page.locator('#messageInput').evaluate(element=>element.setSelectionRange(4,17,'backward'));
      await page.locator('#conversationLog').evaluate(element=>{element.scrollTop=element.scrollHeight;});
      await poll(()=>pm.logs.push(appended(7204,'入力中に届いたログ。\n'.repeat(20))));
      assert.equal(await focused(page.locator('#messageInput')),true,'Polling never steals focus from message composition');
      assert.deepEqual(await page.locator('#messageInput').evaluate(element=>({value:element.value,start:element.selectionStart,
        end:element.selectionEnd,direction:element.selectionDirection})),{value:draft,start:4,end:17,direction:'backward'},
      'New logs preserve the draft and native text selection');
      assert((await scroll()).bottom<=1,'Ordinary bottom following remains enabled when a summary does not own focus');
      await page.locator('#agentSearch').focus();
      await poll(()=>pm.logs.push(appended(7205)));
      assert.equal(await focused(page.locator('#agentSearch')),true,'New logs cannot steal another control’s focus');
      assert.equal(await page.locator('#messageInput').inputValue(),draft);
      await summary(firstId).focus();await page.locator('#navSettings').click();
      await page.locator('#closeSettings').focus();
      assert.equal(await focused(page.locator('#closeSettings')),true,'Use an enabled native modal control during the active-run settings lock');
      await poll(()=>pm.logs.push(appended(7206,'モーダル表示中に届いたログ。')));
      assert((await page.locator('#conversationLog').textContent()).includes('モーダル表示中に届いたログ。'),
        'Background history really changed while the modal was open');
      assert.equal(await focused(page.locator('#closeSettings')),true,'Changed history cannot steal the modal control’s focus');
      assert.equal(await page.locator('#settingsDialog').evaluate(dialog=>dialog.open&&dialog.contains(document.activeElement)),true,
        'Native modal focus remains inside the dialog');
      await capture(name+'-modal-focus',page.locator('#closeSettings'));
      await page.keyboard.press('Escape');assert.equal(await page.locator('#settingsDialog').isVisible(),false);
      assert.equal(await page.locator('#messageInput').inputValue(),draft,'Closing the modal preserves the conversation draft');
    }

    // Identical log IDs belong to their run and agent, not a global disclosure.
    await page.setViewportSize({width:1366,height:768});
    const otherRun={...structuredClone(run),id:'disclosure-other-run',task:'[SYNTHETIC] Disclosure second team',agent_ids:['disclosure-other-pm']};
    const otherAgent={...structuredClone(pm),id:'disclosure-other-pm',run_id:otherRun.id,name:'[SYNTHETIC] Other PM',logs:logs('Other')};
    await poll(()=>{pm.logs=logs('PM');worker.logs=logs('Worker');fixture.runs.push(otherRun);fixture.agents.push(otherAgent);});
    await summary(firstId).focus();await keyboardToggle(firstId,'Enter',true,'Original owner open');
    const pmKey=await summary(firstId).getAttribute('data-focus-key');
    await selectAgent(worker.id,'Worker');
    assert.equal(await details(firstId).evaluate(element=>element.open),false,'Repeated log IDs in another agent do not inherit expanded state');
    const workerKey=await summary(firstId).getAttribute('data-focus-key');assert.notEqual(workerKey,pmKey,'Agent ownership is part of the focus identity');
    await summary(firstId).focus();await keyboardToggle(firstId,'Space',true,'Other agent native disclosure');
    await selectRun(otherRun.id,'Other');
    assert.equal(await details(firstId).evaluate(element=>element.open),false,'Repeated log IDs in another team do not inherit expanded state');
    const otherKey=await summary(firstId).getAttribute('data-focus-key');assert(otherKey&&otherKey!==pmKey&&otherKey!==workerKey,'Team/agent ownership separates focus identities');
    await selectRun(run.id,'PM');
    assert.equal(await details(firstId).evaluate(element=>element.open),true,'Returning to the original owner restores its expanded state');

    await summary(firstId).focus();
    held=await holdNextRequest(page,'**/api/state*',async()=>{});
    const obsolete=compactFixture(held.request()),marker='[SYNTHETIC] OBSOLETE DISCLOSURE RESPONSE';
    obsolete.agents.find(agent=>agent.id===pm.id).logs=[{...logs('PM')[0],text:marker,thinking:marker}];
    await page.evaluate(marker=>{
      window.disclosureSawObsolete=false;window.disclosureObserver=new MutationObserver(()=>{
        if(document.querySelector('#conversationLog').textContent.includes(marker))window.disclosureSawObsolete=true;
      });window.disclosureObserver.observe(document.querySelector('#conversationLog'),{childList:true,subtree:true,characterData:true});
    },marker);
    // The held A response prevents fresh detail loading. Navigate by the native
    // tabs without waiting for B, then give the newer A draft explicit focus.
    for(const id of [worker.id,pm.id]){
      await page.locator(`#agentTabs [data-focus-key="tab:${id}"]`).focus();await page.keyboard.press('Enter');
    }
    const newerDraft='[SYNTHETIC] A → B → A 後の新しい下書き。';
    await page.locator('#messageInput').fill(newerDraft);await page.locator('#messageInput').focus();
    await releaseResponse(page,held,obsolete);held=null;
    await page.locator('#conversationLog[aria-busy="false"]').filter({hasText:'Disclosure PM log 1'}).waitFor();await paint();
    assert.equal(await page.evaluate(()=>window.disclosureSawObsolete),false,'Obsolete same-ID A → B → A detail never renders');
    assert.equal(await focused(page.locator('#messageInput')),true,'Delayed disclosure response cannot recover an obsolete focus owner');
    assert.equal(await page.locator('#messageInput').inputValue(),newerDraft);
    assert.equal(await details(firstId).evaluate(element=>element.open),true,'Selection ABA preserves the current owner’s expanded state');
    await page.evaluate(()=>window.disclosureObserver.disconnect());
    assert.deepEqual(mutations,[],'Disclosure navigation/toggling/polling sends no start, stop, message, settings or provider mutation');

    // Leave the surrounding acceptance flow with its original team, expanded
    // disclosure, draft, viewport and reading position rather than test history.
    await poll(()=>Object.assign(fixture,structuredClone(original)));
    await page.setViewportSize(viewport);
    for(const detail of await page.locator('#conversationLog details').all()){
      const id=await detail.getAttribute('data-log-id'),open=await detail.evaluate(element=>element.open);
      if(open!==before.expanded.includes(id)){await detail.locator(':scope > summary').focus();await page.keyboard.press('Enter');}
    }
    if(before.resultsOpen){await page.locator('#resultsPanel > summary').focus();await page.keyboard.press('Enter');}
    await page.locator('#messageInput').fill(before.draft);
    await page.evaluate(saved=>{
      const input=document.querySelector('#messageInput'),log=document.querySelector('#conversationLog');
      input.setSelectionRange(saved.start,saved.end,saved.direction);
      const target=saved.focusLog?[...log.querySelectorAll('details > summary')].find(element=>element.parentElement.dataset.logId===saved.focusLog):
        saved.focusId?document.getElementById(saved.focusId):[...document.querySelectorAll('[data-focus-key]')].find(element=>element.dataset.focusKey===saved.focusKey);
      target?.focus({preventScroll:true});log.scrollTop=saved.scroll;window.scrollTo(saved.x,saved.y);
    },before);
    assert.deepEqual(fixture,original,'The surrounding smoke receives its original synthetic state');
    assert.equal(await page.locator('#messageInput').inputValue(),before.draft,'The surrounding smoke receives its original draft');
    assert.deepEqual(await page.locator('#conversationLog details[open]').evaluateAll(elements=>elements.map(element=>element.dataset.logId)),before.expanded,
      'The original expanded disclosures are restored');
    assert.equal(await page.locator('#resultsPanel').evaluate(element=>element.open),before.resultsOpen);
    assert.deepEqual(page.viewportSize(),viewport);
    report.checks.push('disclosure focus: native Tab/Enter/Space at desktop 1366x768 and narrow 390x844; unchanged polls retain nodes; changed/large near-bottom arrivals retain the same owner summary, expanded state, visible reading position and keyboard operation; eviction chooses a nearby surviving summary or the existing heading; repeated log IDs across agents/teams and delayed A → B → A cannot steal focus; message drafts/text selections, other controls and a native settings modal retain focus; ordinary bottom following stays enabled; synthetic-only screenshots and no mutating requests');
  } catch(error) {
    await page.screenshot({path:path.join(artifacts,'workbench-disclosure-failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});
    throw error;
  } finally {
    Object.assign(fixture,structuredClone(original));page.off('request',observe);
    if(held)await held.abort().catch(()=>{});
    await page.evaluate(()=>{window.disclosureObserver?.disconnect();delete window.disclosureObserver;
      delete window.disclosureSawObsolete;delete window.disclosureFocusNode;}).catch(()=>{});
  }
}

module.exports={disclosureFocusAcceptance};
