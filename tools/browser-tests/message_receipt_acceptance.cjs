/* Real loopback message acceptance; SyntheticClient only, never model network. */
'use strict';
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');

async function messageReceiptAcceptance({context,origin,providerRequests,report}) {
  const providerBefore=structuredClone(providerRequests),externalBefore=[...report.externalRequests];
  const pending=new Set(),handlers=new Set(),posts=[],texts=[];
  const runTask='[SYNTHETIC] Strict message receipts '+randomUUID()+'.';
  let page,originalConfig,restoreNeeded=false,runId,source,other,upstreamPosts=0,failed=false;
  const api=async(route,method='GET',body)=>{
    const response=await context.request.fetch(origin+route,{method,headers:{Origin:origin},maxRetries:0,timeout:10000,
      ...(body===undefined?{}:{data:body})});
    assert.equal(response.status(),200,method+' '+route+' status');return response.json();
  };
  const configure=async config=>{
    const {config_revision}=await api('/api/config');
    return api('/api/config','PUT',{config_revision,config});
  };
  const waitState=async(test,label)=>{
    const deadline=Date.now()+10000;
    for(;;){
      const state=await api('/api/state');if(test(state))return state;
      assert(Date.now()<deadline,label);await new Promise(resolve=>setTimeout(resolve,25));
    }
  };
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const poll=async(count=1)=>{
    for(let i=0;i<count;i++){
      // These are the application's existing selected-state polls, never a
      // test-injected browser fetch or a replacement for server evidence.
      const response=await page.waitForResponse(response=>{
        const url=new URL(response.url());
        return url.origin===origin&&url.pathname==='/api/state'&&url.searchParams.get('view')==='selected'&&
          response.request().method()==='GET';
      });
      assert.equal(response.status(),200);await response.finished();await paint();
    }
  };
  const owner=()=>page.evaluate(()=>({
    run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey,
    agent:document.querySelector('#agentTabs [aria-pressed="true"]')?.dataset.focusKey,
  }));
  const view=()=>page.evaluate(()=>({
    draft:document.querySelector('#messageInput').value,
    selectionStart:document.querySelector('#messageInput').selectionStart,
    selectionEnd:document.querySelector('#messageInput').selectionEnd,
    selectionDirection:document.querySelector('#messageInput').selectionDirection,
    status:document.querySelector('#messageStatus').textContent,
    error:document.querySelector('#messageStatus').classList.contains('error'),
    hidden:document.querySelector('#messageStatus').hidden,
    focused:document.activeElement.id||document.activeElement.dataset.focusKey||document.activeElement.tagName,
  }));
  const select=async agent=>{
    await page.locator(`#agentTabs [data-focus-key="tab:${agent.id}"]`).click();
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();await paint();
    assert.deepEqual(await owner(),{run:'run:'+runId,agent:'tab:'+agent.id});
  };
  const assertPresence=async(sourcePresent,otherText)=>{
    for(const [agent,present] of [[source,sourcePresent],[other,true]]){
      const marker=page.locator(`#agentCards [data-agent-id="${agent.id}"] .input-presence-badge`);
      assert.equal(await marker.count(),present?1:0,'Input presence belongs to its exact composer owner');
      if(present)assert.equal(await marker.textContent(),'入力あり');
    }
    const count=sourcePresent?2:1;
    assert.equal(await page.locator('#messageInputCount').textContent(),String(count));
    assert.match(await page.locator(`#runList [data-focus-key="run:${runId}"] .run-link-meta`).textContent(),
      new RegExp('入力 '+count+'人'));
    assert.match(await page.locator('#messageInputNavigationStatus').textContent(),/入力の有無のみで、送信状態を示すものではありません/);
    const markers=await page.locator('#nextMessageInput, .input-presence-badge').allTextContents();
    assert.doesNotMatch(markers.join('\n'),/未送信|保存済み|送信済み|送信失敗|unsent|saved|failed|sent/i,
      'Receipt ambiguity cannot turn presence markers into delivery or persistence claims');
    const sidebar=await page.locator('.sidebar').textContent();
    for(const text of [...texts,otherText])assert(!sidebar.includes(text.trim()),'Presence discovery never exposes message snippets');
  };
  const exactLogs=(agent,text)=>agent.logs.filter(log=>log.kind==='user'&&log.text===text);
  const acceptedState=async(text,revision)=>{
    const state=await waitState(state=>{
      const agent=state.agents.find(item=>item.id===source.id);
      return agent?.status==='done'&&exactLogs(agent,text).length===1;
    },'The real SyntheticClient worker must consume exactly the original accepted message');
    const agent=state.agents.find(item=>item.id===source.id);
    assert.equal(agent.result_revision,revision+1,'Exactly one real enqueue advances the source revision');
    for(const item of state.agents.filter(item=>item.id!==source.id))
      assert.equal(exactLogs(item,text).length,0,'The message cannot be accepted by another owner');
    return agent;
  };
  const visibleLog=async text=>{
    await page.waitForFunction(text=>[...document.querySelectorAll('#conversationLog .log-entry.user .log-text')]
      .filter(node=>node.textContent===text).length===1,text);
    assert.equal((await page.locator('#conversationLog .log-entry.user .log-text').allTextContents())
      .filter(value=>value===text).length,1,'The actual accepted source text is visible exactly once');
  };
  const observe=request=>{
    const url=new URL(request.url());
    if(url.origin===origin&&/^\/api\/agents\/[^/]+\/message$/.test(url.pathname)&&request.method()==='POST')
      posts.push({path:url.pathname,body:request.postDataJSON()});
  };
  const holdMessage=async text=>{
    const url=origin+'/api/agents/'+encodeURIComponent(source.id)+'/message';
    let resolve,reject;const captured=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const handler=async route=>{
      if(route.request().method()!=='POST')return route.fallback();
      const entry={route,upstream:null,fetches:0};pending.add(entry);
      try {
        assert.equal(route.request().url(),url,'Intercept only the exact real message endpoint');
        assert.deepEqual(route.request().postDataJSON(),{text},'Native send preserves every source character');
        entry.fetches++;upstreamPosts++;
        // One actual POST, with both transport retries and redirects disabled.
        // Nothing in release() is allowed to send this request a second time.
        entry.upstream=await route.fetch({maxRetries:0,maxRedirects:0,timeout:10000});
        assert.equal(entry.upstream.status(),200,'The real server accepted the original message');
        assert.deepEqual(await entry.upstream.json(),{ok:true},'Verify the actual engine receipt before altering delivery');
        resolve(entry);
      }catch(error){reject(error);}
    };
    handlers.add({url,handler});await page.route(url,handler,{times:1});
    const timeout=setTimeout(()=>reject(new Error('Native message POST did not reach a verified upstream receipt within 10 seconds')),10000);
    try {
      const [,entry]=await Promise.all([(async()=>{
        await page.locator('#sendMessage').focus();await page.keyboard.press('Enter');
      })(),captured]);
      return entry;
    }finally{clearTimeout(timeout);}
  };
  const release=async(entry,mode)=>{
    assert(entry.upstream,'Delivery manipulation must follow verified real server acceptance');
    assert.equal(entry.fetches,1);
    if(mode==='abort'){
      const failedRequest=page.waitForEvent('requestfailed',request=>request===entry.route.request());
      await entry.route.abort('connectionreset');assert((await failedRequest).failure());
    }else{
      const response=page.waitForResponse(response=>response.request()===entry.route.request());
      if(mode==='accepted')await entry.route.fulfill({response:entry.upstream});
      else await entry.route.fulfill({status:200,contentType:'application/json',body:mode==='empty'?'{}':'{"ok":'});
      const delivered=await response;assert.equal(delivered.status(),200);await delivered.finished();
      if(mode==='accepted')assert.deepEqual(await delivered.json(),{ok:true});
      else assert.equal(await delivered.text(),mode==='empty'?'{}':'{"ok":');
    }
    pending.delete(entry);await paint();
    await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);
  };
  try {
    const initial=await api('/api/config');originalConfig=structuredClone(initial.config);
    const state=await api('/api/state');
    assert(state.runs.length<20,'The receipt module needs one retained-history slot');
    assert(state.runs.every(run=>!['running','waiting','stopping'].includes(run.status)),
      'Receipt acceptance must not change settings around another active run');
    const config=structuredClone(originalConfig),local=config.providers.find(profile=>profile.id==='local');
    assert(local?.enabled&&local.kind==='local','Reuse the existing synthetic local profile without changing credential identity');
    Object.assign(config.limits,{max_workers:1,max_turns_per_agent:20,max_model_calls:30,max_tool_calls:50,
      max_auto_collaborations:30,max_run_seconds:600,max_context_chars:200000});
    config.search.enabled=false;restoreNeeded=true;await configure(config);
    // A same-session sibling isolates all task/message drafts and selection from
    // the enclosing smoke; no production globals or application handlers change.
    page=await context.newPage();page.setDefaultTimeout(10000);
    page.on('pageerror',error=>report.pageErrors.push(error.message));
    page.on('console',message=>{if(/Content Security Policy|violates.*directive/i.test(message.text()))report.cspErrors.push(message.text());});
    page.on('request',request=>{
      const url=new URL(request.url());
      if(url.protocol.startsWith('http')&&url.origin!==origin)report.externalRequests.push(url.origin+url.pathname);
    });
    page.on('request',observe);await page.goto(origin+'/');
    await page.getByText('Workbench 接続中',{exact:true}).waitFor({state:'attached'});
    await page.locator('#newRun').click();await page.locator('#taskInput').fill(runTask);
    await page.locator('#pmProfile').selectOption('local');await page.locator('#maxWorkers').fill('1');
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.uncheck();
    await page.locator('#workerProfiles input[value="local"]').check();
    const started=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
    await page.locator('#startRun').focus();await page.keyboard.press('Enter');
    const response=await started;assert.equal(response.status(),200);runId=(await response.json()).run.id;
    const ready=await waitState(state=>{
      const agents=state.agents.filter(agent=>agent.run_id===runId);
      return agents.length===2&&agents.some(agent=>!agent.parent_id&&agent.status==='waiting')&&
        agents.some(agent=>agent.parent_id&&agent.status==='done');
    },'The existing no-network SyntheticClient must create its waiting PM and completed worker');
    source=ready.agents.find(agent=>agent.run_id===runId&&agent.parent_id);
    other=ready.agents.find(agent=>agent.run_id===runId&&!agent.parent_id);
    await page.locator('#taskDialog').waitFor({state:'hidden'});
    await page.locator(`#runList .run-link.selected[data-focus-key="run:${runId}"]`).waitFor();
    await poll();await select(other);
    let otherText='  [SYNTHETIC] Other owner input '+randomUUID()+'\n  ';
    await page.locator('#messageInput').fill(otherText);
    const scenarios=[
      {name:'accepted-unchanged',mode:'accepted'},
      {name:'empty-unchanged',mode:'empty'},
      {name:'empty-selection-aba-edit-restore',mode:'empty',navigation:'aba'},
      {name:'empty-different-owner',mode:'empty',navigation:'other'},
      {name:'invalid-json-unchanged',mode:'invalid'},
      {name:'aborted-after-acceptance-unchanged',mode:'abort'},
    ];
    for(const scenario of scenarios){
      await select(other);assert.equal(await page.locator('#messageInput').inputValue(),otherText);
      await select(source);assert.equal(await page.locator('#messageStatus').textContent(),'');
      const text=' \t[SYNTHETIC] '+scenario.name+' '+randomUUID()+'\n日本語の完全一致メッセージ\n  ';
      texts.push(text);await page.locator('#messageInput').fill(text);await assertPresence(true,otherText);
      const before=await api('/api/state'),revision=before.agents.find(agent=>agent.id===source.id).result_revision;
      const browserBefore=posts.length,upstreamBefore=upstreamPosts,entry=await holdMessage(text);
      await acceptedState(text,revision);
      assert.equal(await page.locator('#sendMessage').isDisabled(),true,'One message owns the pending native submit control');
      // Native duplicate activation while delivery is held must not dispatch a
      // second message. Do not synthesize submit events or call app internals.
      const send=page.locator('#sendMessage');await send.scrollIntoViewIfNeeded();const box=await send.boundingBox();assert(box);
      await page.mouse.click(box.x+box.width/2,box.y+box.height/2,{clickCount:2});
      await page.keyboard.press('Enter');await page.keyboard.press('Space');await paint();
      assert.equal(await page.locator('#messageInput').inputValue(),text);
      assert.equal(posts.length,browserBefore+1);assert.equal(upstreamPosts,upstreamBefore+1);
      if(scenario.navigation){
        await select(other);
        if(scenario.navigation==='aba'){
          await select(source);await page.locator('#messageInput').fill(text+'[temporary edit]');
          await page.locator('#messageInput').fill(text);
        }else{
          otherText=' \t[SYNTHETIC] Newer owner input '+randomUUID()+'\n  ';
          await page.locator('#messageInput').fill(otherText);
        }
      }
      await page.locator('#messageInput').focus();
      await page.locator('#messageInput').evaluate(input=>input.setSelectionRange(3,17,'backward'));
      const heldView=await view(),heldOwner=await owner();
      await poll();assert.equal(await page.locator('#sendMessage').isDisabled(),true);
      assert.deepEqual(await view(),heldView,'Ordinary polling cannot settle a pending browser receipt');
      await assertPresence(true,otherText);await release(entry,scenario.mode);
      if(scenario.navigation){
        assert.deepEqual(await owner(),heldOwner,'Late receipt cannot change the newer selected owner');
        assert.deepEqual(await view(),heldView,'Late unknown receipt cannot label, clear or focus the newer owner/draft generation');
      }else if(scenario.mode==='accepted'){
        assert.equal(await page.locator('#messageInput').inputValue(),'','Only the unchanged draft with an explicit true receipt clears');
        assert.equal(await page.locator('#messageStatus').textContent(),'送信しました。');
        assert.equal(await page.locator('#messageStatus').evaluate(node=>node.classList.contains('error')),false);
      }else{
        const unknownView=await view();
        for(const field of ['focused','selectionStart','selectionEnd','selectionDirection'])
          assert.equal(unknownView[field],heldView[field],'Unknown receipt settlement preserves composer '+field);
        assert.equal(await page.locator('#messageInput').inputValue(),text,'Unknown delivery preserves the exact accepted source draft');
        assert.match(await page.locator('#messageStatus').textContent(),/送信結果は未確認/);
        assert.match(await page.locator('#messageStatus').textContent(),/作業ログを確認/);
        assert.doesNotMatch(await page.locator('#messageStatus').textContent(),/送信しました/);
        assert.equal(await page.locator('#messageStatus').evaluate(node=>node.classList.contains('error')),true);
      }
      const settledView=await view();await poll(2);
      assert.deepEqual(await view(),settledView,'Two later existing polls cannot clear or relabel a settled composer');
      assert.equal(posts.length,browserBefore+1,'No automatic browser POST retry after acceptance or unknown delivery');
      assert.equal(upstreamPosts,upstreamBefore+1,'Response release and polling never replay the real POST');
      assert.equal(entry.fetches,1);await acceptedState(text,revision);
      await assertPresence(scenario.mode!=='accepted',otherText);
      if(scenario.navigation==='other'){
        await select(source);assert.equal(await page.locator('#messageInput').inputValue(),text,'The original owner also retains its exact draft');
        assert.equal(await page.locator('#messageStatus').textContent(),'','Unknown receipt feedback never migrates between owners');
      }
      await visibleLog(text);
      await select(other);assert.equal(await page.locator('#messageInput').inputValue(),otherText,'The unrelated owner keeps every input character');
      await select(source);assert.equal(await page.locator('#messageInput').inputValue(),scenario.mode==='accepted'?'':text,
        'Owner round trip preserves the receipt-dependent draft result');
      report.checks.push('message-receipt: '+scenario.name+'; one real HTTP 200/{ok:true} upstream acceptance, one native browser POST, exact single source user log; receipt/draft/feedback ownership and neutral input presence survive existing polls without retry');
    }
    assert.equal(posts.length,scenarios.length);assert.equal(upstreamPosts,scenarios.length);
    assert.deepEqual(posts,texts.map(text=>({path:'/api/agents/'+source.id+'/message',body:{text}})));
    const final=await api('/api/state'),finalSource=final.agents.find(agent=>agent.id===source.id);
    assert.deepEqual(finalSource.logs.filter(log=>log.kind==='user').map(log=>log.text),texts,
      'The real worker consumed exactly the six distinct original messages, in order');
    assert.equal(finalSource.result_revision,source.result_revision+scenarios.length);
    assert.equal(finalSource.turns,source.turns+scenarios.length);
    assert.deepEqual(providerRequests,providerBefore,'Receipt acceptance never invokes a provider endpoint');
    assert.deepEqual(report.externalRequests,externalBefore);assert.equal(pending.size,0);
    assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
  }catch(error){failed=true;throw error;}
  finally {
    const errors=[];
    for(const entry of pending)await entry.route.abort('aborted').catch(error=>errors.push(error));
    if(page){
      for(const {url,handler} of handlers)await page.unroute(url,handler).catch(error=>errors.push(error));
      page.off('request',observe);await page.close().catch(error=>errors.push(error));
    }
    // Runs are deliberately retained by this app. Stop only our uniquely named
    // synthetic run; do not delete or restart the enclosing history fixture.
    if(restoreNeeded){
      try {
        const state=await api('/api/state');
        for(const run of state.runs.filter(run=>run.task===runTask)){
          assert(!runId||run.id===runId);await api('/api/runs/'+run.id+'/stop','POST',{});
        }
        const stopped=await api('/api/state');
        for(const run of stopped.runs.filter(run=>run.task===runTask)){
          assert.equal(run.status,'stopped','Cleanup stops only this module\'s synthetic run');
          assert(stopped.agents.filter(agent=>agent.run_id===run.id).every(agent=>agent.status==='stopped'));
        }
        await configure(originalConfig);assert.deepEqual((await api('/api/config')).config,originalConfig);
      }catch(error){errors.push(error);}
    }
    if(errors.length){
      report.checks.push('message-receipt cleanup failed: '+errors.map(error=>error.message).join('; '));
      if(!failed)throw new AggregateError(errors,'Message-receipt cleanup failed');
    }
  }
}

module.exports={messageReceiptAcceptance};
