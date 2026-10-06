/* Neutral composer-input discovery: native controls, synthetic state, no inference. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

async function inputPresenceAcceptance({page,fixture,compactFixture,providerRequests,artifacts,report,
  holdNextRequest,releaseResponse,assertLayout}) {
  const original=structuredClone(fixture),viewport=page.viewportSize(),providerBefore=structuredClone(providerRequests);
  const before=await page.evaluate(()=>{
    const active=document.activeElement,input=document.querySelector('#messageInput'),log=document.querySelector('#conversationLog');
    const storage=store=>Object.fromEntries(Array.from({length:store.length},(_,index)=>{const key=store.key(index);return [key,store.getItem(key)];}));
    return {run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey.slice(4),
      agent:document.querySelector('#agentTabs [aria-pressed="true"]')?.dataset.focusKey.slice(4),
      draft:input.value,start:input.selectionStart,end:input.selectionEnd,direction:input.selectionDirection,
      search:document.querySelector('#agentSearch').value,questions:document.querySelector('#needsYou').getAttribute('aria-pressed')==='true',
      task:document.querySelector('#taskInput').value,expanded:[...log.querySelectorAll('details[open]')].map(node=>node.dataset.logId),
      taskOpen:document.querySelector('#taskDialog').open,settingsOpen:document.querySelector('#settingsDialog').open,
      resultsOpen:document.querySelector('#resultsPanel').open,scroll:log.scrollTop,x:scrollX,y:scrollY,
      railScroll:Object.fromEntries(['agentCards','runList'].map(id=>{const node=document.getElementById(id);return [id,{top:node.scrollTop,left:node.scrollLeft}];})),
      focusId:active.id,focusKey:active.dataset.focusKey,focusLog:active.localName==='summary'?active.parentElement.dataset.logId:null,
      local:storage(localStorage),session:storage(sessionStorage)};
  });
  const baseRun=fixture.runs.find(run=>run.id===before.run),baseAgent=fixture.agents.find(agent=>agent.id===before.agent);
  assert(baseRun&&baseAgent&&baseAgent.run_id===baseRun.id,'Input discovery starts at the enclosing smoke’s synthetic owner');
  assert.equal(before.taskOpen,false,'The enclosing acceptance closes its task dialog');assert.equal(before.settingsOpen,false,'The enclosing acceptance closes settings');
  const makeRun=(id,offset)=>({...structuredClone(baseRun),id,created_at:baseRun.created_at+offset,status:'running',status_reason:'working',
    task:'[SYNTHETIC] 入力位置の確認用。長い日本語の依頼と対象部署、公開前の確認事項。'.repeat(4)+'\n本文検索語 '+id,agent_ids:[]});
  const other=makeRun('input-presence-run-other-0028',-200),stopped=makeRun('input-presence-run-stop-0028',200);
  const makeAgent=(id,run,parent=null)=>({...structuredClone(baseAgent),id,run_id:run.id,parent_id:parent,role:parent?'worker':'pm',
    name:'[SYNTHETIC] 長い担当者名・情報共有と日本語資料確認担当・'+id,
    assignment:'[SYNTHETIC] 担当範囲を確認する長い説明。'.repeat(8),status:'waiting',status_reason:'human_input',
    question:'[SYNTHETIC] 確認が必要な長い質問です。対象部署、共有資料、期限を確認してください。'.repeat(14),
    configured_profile:{id:baseAgent.profile_id,kind:baseAgent.configured_profile.kind,
      label:'[SYNTHETIC] 長い開始時設定名・社内日本語確認モデル',model:'[SYNTHETIC] configuration-identity-'.repeat(5)},
    message_eligibility:{allowed:true,reason:'',message:''},results:[],output_receipts:[],
    logs:[{id:9801,kind:'assistant',text:'[SYNTHETIC] 入力位置の所有者 '+id,at:run.created_at}]});
  const root=makeAgent('input-presence-other-root',other),worker=makeAgent('input-presence-other-worker',other,root.id),
    unknown=makeAgent('input-presence-other-unknown',other,root.id),stoppedAgent=makeAgent('input-presence-stopped-root',stopped);
  // Declared order deliberately differs from both the root-first navigation
  // default and the transport order, so the cyclic contract is observable.
  other.agent_ids=[worker.id,root.id,unknown.id];stopped.agent_ids=[stoppedAgent.id];
  const fillers=Array.from({length:17},(_,index)=>makeRun('input-presence-filler-'+String(index).padStart(4,'0'),400-index*7));
  const fillerAgents=fillers.map((run,index)=>{
    const agent=makeAgent('input-presence-filler-agent-'+index,run);run.agent_ids=[agent.id];
    agent.question='';agent.status=index%2?'done':'working';agent.status_reason=agent.status;return agent;
  });
  const texts=new Map([[baseAgent.id,'  [SYNTHETIC] EXACT-INPUT-BASE\n日本語の追記。\t  '],
    [root.id,'[SYNTHETIC] EXACT-INPUT-ROOT'],[worker.id,'[SYNTHETIC] EXACT-INPUT-WORKER'],
    [unknown.id,'[SYNTHETIC] EXACT-INPUT-UNKNOWN'],[stoppedAgent.id,' \n\t ']]);
  const entries=[baseAgent,worker,root,unknown,stoppedAgent],requests=[],unexpected=[],priorDrafts=new Map();
  const input=page.locator('#messageInput'),next=page.locator('#nextMessageInput');
  const runLink=id=>page.locator(`#runList [data-focus-key="run:${id}"]`);
  const card=id=>page.locator(`#agentCards .agent-card[data-agent-id="${id}"]`);
  const owner=()=>page.evaluate(()=>({run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey.slice(4),
    agent:document.querySelector('#agentTabs [aria-pressed="true"]')?.dataset.focusKey.slice(4)}));
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const focused=selector=>page.locator(selector).evaluate(node=>node===document.activeElement);
  const observer=request=>{
    const url=new URL(request.url());if(!url.pathname.startsWith('/api/'))return;
    requests.push({path:url.pathname,method:request.method(),view:url.searchParams.get('view'),run:url.searchParams.get('run_id'),agent:url.searchParams.get('agent_id')});
  };
  // Accidental sends or writes fail closed before reaching the surrounding
  // synthetic handlers. Explicit race sends get their own one-use held route.
  const mutationGuard=async route=>{
    const request=route.request(),url=new URL(request.url());
    if(['GET','HEAD','OPTIONS'].includes(request.method())||url.pathname==='/api/run-preflight')return route.fallback();
    unexpected.push({path:url.pathname,method:request.method()});await route.abort('blockedbyclient');
  };
  const poll=async(change=()=>{})=>{
    const selected=await owner(),requested=page.waitForRequest(request=>{
      const url=new URL(request.url());return request.method()==='GET'&&url.pathname==='/api/state'&&
        url.searchParams.get('run_id')===selected.run&&url.searchParams.get('agent_id')===selected.agent;
    });
    change();const response=await (await requested).response();assert(response);assert.equal(response.status(),200);
    await response.finished();await paint();
  };
  const mode=async questions=>{
    if((await page.locator('#needsYou').getAttribute('aria-pressed')==='true')!==questions){
      await page.locator('#needsYou').focus();await page.keyboard.press('Space');
    }
    assert.equal(await page.locator('#needsYou').getAttribute('aria-pressed'),String(questions));
  };
  const select=async agent=>{
    if((await owner()).run!==agent.run_id)await runLink(agent.run_id).click();
    if((await owner()).agent!==agent.id)await page.locator(`#agentTabs [data-focus-key="tab:${agent.id}"]`).click();
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();await paint();
    assert.deepEqual(await owner(),{run:agent.run_id,agent:agent.id});
  };
  const count=async total=>{
    assert.equal(await page.locator('#messageInputCount').textContent(),String(total),'Count is the number of known owners with exact nonempty input');
    assert.equal(await next.isDisabled(),total===0,'Zero input owners disables the single discovery action');
    assert.equal(await next.count(),1,'There is one existing-sidebar discovery button');
    assert.equal(await next.getAttribute('type'),'button','Discovery never submits a form');
    assert.match(await next.getAttribute('aria-label'),new RegExp(`${total}人`),'The action’s accessible name exposes the same owner count');
  };
  const assertMarker=async(agent,present=true)=>{
    assert.equal(await card(agent.id).getByText('入力あり',{exact:true}).count(),present?1:0,
      'Existing card exposes one neutral presence marker: '+agent.id);
  };
  const assertNeutral=async()=>{
    const text=await page.locator('.sidebar').textContent();
    for(const value of texts.values())if(value.trim())assert(!text.includes(value.trim()),'The sidebar never exposes input snippets');
    const copy=await page.locator('#nextMessageInput, .input-presence-badge').allTextContents();
    assert.doesNotMatch(copy.join('\n'),/未送信|保存済み|送信済み|送信失敗|下書き一覧|unsent|saved|failed|sent/i,
      'Per-owner markers and navigation never label input as a send or persistence state');
    assert.match(await page.locator('#messageInputHelp').textContent(),/入力の有無/,'Help explicitly limits the marker to presence');
  };
  const assertOnlySelectedLoads=(start,agent,previous={run:agent.run_id,agent:agent.id})=>{
    const target={run:agent.run_id,agent:agent.id};let targetRequested=false;
    for(const request of requests.slice(start)){
      assert.equal(request.method,'GET','Discovery issues no mutation');assert.equal(request.path,'/api/state','Discovery uses only the existing selected-state endpoint');
      assert.equal(request.view,'selected','Discovery retains the compact selected-state request contract');
      const requested={run:request.run,agent:request.agent};
      if(requested.run===target.run&&requested.agent===target.agent){targetRequested=true;continue;}
      assert.equal(targetRequested,false,'An old-owner poll cannot follow the first exact-target request without another navigation');
      assert.deepEqual(requested,previous,'Before activation finishes, only the known previous owner may poll; an intermediate root or third owner is forbidden');
    }
  };
  const activate=async(agent,key='Enter',wait=true)=>{
    const retained={questions:await page.locator('#needsYou').getAttribute('aria-pressed'),search:await page.locator('#agentSearch').inputValue()},previous=await owner(),start=requests.length;
    await next.focus();await page.keyboard.press(key);
    assert.deepEqual(await owner(),{run:agent.run_id,agent:agent.id},'Next input picks exactly the expected run and declared member');
    assert.equal(await input.inputValue(),texts.get(agent.id),'Navigation preserves every input character, including whitespace');
    const target=await input.isDisabled()?'#conversationHeading':'#messageInput';
    assert.equal(await focused(target),true,'Explicit activation focuses the available composer or existing conversation heading immediately');
    assert.equal(await page.locator('#needsYou').getAttribute('aria-pressed'),retained.questions,'Navigation preserves the current roster mode');
    assert.equal(await page.locator('#agentSearch').inputValue(),retained.search,'Navigation does not clear or replace the current search');
    if(wait){await page.locator('#conversationLog[aria-busy="false"]').waitFor();await paint();assert.equal(await focused(target),true,'Selected-detail completion does not perform a second focus move');}
    assertOnlySelectedLoads(start,agent,previous);
  };
  const assertVisible=async(locator,label)=>{
    const area=await locator.evaluate(node=>{
      const box=node.getBoundingClientRect();let left=0,top=0,right=innerWidth,bottom=innerHeight;
      for(let parent=node.parentElement;parent;parent=parent.parentElement){
        const style=getComputedStyle(parent),rect=parent.getBoundingClientRect();
        if(/auto|scroll|hidden|clip/.test(style.overflowX)){left=Math.max(left,rect.left+parent.clientLeft);right=Math.min(right,rect.left+parent.clientLeft+parent.clientWidth);}
        if(/auto|scroll|hidden|clip/.test(style.overflowY)){top=Math.max(top,rect.top+parent.clientTop);bottom=Math.min(bottom,rect.top+parent.clientTop+parent.clientHeight);}
      }
      const hit=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2);
      return {left:box.left,top:box.top,right:box.right,bottom:box.bottom,width:box.width,height:box.height,
        clipLeft:left,clipTop:top,clipRight:right,clipBottom:bottom,hit:hit===node||node.contains(hit),
        overflow:node.scrollWidth-node.clientWidth,verticalOverflow:node.scrollHeight-node.clientHeight};
    });
    const measured='; measured area='+JSON.stringify(area);
    assert(area.width>0&&area.height>0&&area.left>=area.clipLeft-1&&area.right<=area.clipRight+1&&
      area.top>=area.clipTop-1&&area.bottom<=area.clipBottom+1,label+': target is inside every clipping ancestor'+measured);
    assert.equal(area.hit,true,label+': target is unobscured'+measured);assert(area.overflow<=1,label+': text has no horizontal clipping'+measured);
  };
  const assertGeometry=async label=>{
    await assertLayout(page,label);
    const boxes=await page.evaluate(()=>{
      const box=node=>{const rect=node.getBoundingClientRect();return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,
        width:rect.width,height:rect.height,overflow:node.scrollWidth-node.clientWidth};};
      return {width:innerWidth,button:box(document.querySelector('#nextMessageInput')),help:box(document.querySelector('#messageInputHelp')),
        cards:[...document.querySelectorAll('#agentCards .agent-card')].map(node=>({box:box(node),verticalOverflow:node.scrollHeight-node.clientHeight,
          children:[...node.querySelectorAll('.agent-name,.agent-model,.agent-task,.agent-state-line,.question-run,.question-run-id,.question-preview,.question-availability,.question-open,.input-presence-badge')].map(box)})),
        runs:[...document.querySelectorAll('#runList .run-link')].map(node=>({box:box(node),meta:box(node.querySelector('.run-link-meta'))}))};
    });
    for(const [name,box] of [['button',boxes.button],['help',boxes.help]]){
      assert(box.width>0&&box.height>0&&box.left>=-1&&box.right<=boxes.width+1,label+': '+name+' fits the sidebar width');
      assert(box.overflow<=1,label+': '+name+' has no clipped text');
    }
    for(const {box,verticalOverflow,children} of boxes.cards){
      assert(box.overflow<=1,label+': card has no horizontal overflow');assert(verticalOverflow<=1,label+': card does not hide vertically overflowing content');
      for(const child of children)assert(child.width>0&&child.height>0&&child.left>=box.left-1&&child.right<=box.right+1&&
        child.top>=box.top-1&&child.bottom<=box.bottom+1,label+': presence, status, identity, question and open action remain inside each existing card');
    }
    for(const {box,meta} of boxes.runs)assert(meta.width>0&&meta.height>0&&meta.left>=box.left-1&&meta.right<=box.right+1&&
      meta.top>=box.top-1&&meta.bottom<=box.bottom+1&&meta.overflow<=1,label+': session metadata and input counts remain inside the session button');
  };
  let heldState,heldSend,restored=false;
  page.on('request',observer);await page.route('**/api/**',mutationGuard);
  try {
    before.searches={[before.questions?'questions':'crew']:before.search};
    await mode(!before.questions);before.searches[before.questions?'crew':'questions']=await page.locator('#agentSearch').inputValue();
    await mode(false);await page.locator('#agentSearch').clear();
    for(const agent of original.agents){
      await select(agent);priorDrafts.set(agent.id,await input.inputValue());
      assert.equal(await input.isEnabled(),true,'The enclosing smoke must provide an editable original composer before zero-count isolation; cannot clear retained input for '+agent.id);
      await input.clear();
    }
    await select(baseAgent);await count(0);
    assert.equal(await page.locator('#messageInputHelp').isVisible(),true);
    assert((await next.getAttribute('aria-describedby')||'').split(/\s+/).includes('messageInputHelp'),'The action describes its limited input-presence meaning');
    const taskStart=requests.length;
    await page.locator('#newRun').click();await page.locator('#taskInput').fill('[SYNTHETIC] TASK-EDITOR-IS-NOT-A-MESSAGE\n  ');
    await page.locator('#preflightStatus[aria-busy="false"]').waitFor();await count(0);await page.keyboard.press('Escape');
    assert(requests.slice(taskStart).every(item=>item.path==='/api/state'||item.path==='/api/run-preflight'),'Task exclusion uses only ordinary state and preflight requests');
    const navigationStart=requests.length;
    await poll(()=>{
      fixture.runs=[other,...fillers.slice(0,9),stopped,baseRun,...fillers.slice(9)];
      fixture.agents.push(unknown,root,stoppedAgent,worker,...fillerAgents);
    });
    assert.equal(await page.locator('#runList .run-link').count(),20);assert.equal(await page.locator('#runCount').textContent(),'20 / 20');
    for(const agent of entries){await select(agent);await input.fill(texts.get(agent.id));}
    await count(5);await mode(false);await select(root);
    for(const agent of [worker,root,unknown])await assertMarker(agent);
    assert.match(await runLink(other.id).textContent(),/入力\s*3人/);
    assert.match(await runLink(baseRun.id).textContent(),/入力\s*1人/);
    assert.match(await runLink(stopped.id).textContent(),/入力\s*1人/);
    for(const run of fillers)assert.doesNotMatch(await runLink(run.id).textContent(),/入力\s*[1-9]/);
    await assertNeutral();
    await poll(()=>{
      worker.message_eligibility={allowed:false,reason:'profile_missing',message:'[SYNTHETIC] 設定を修正するまで送信できません。'};
      delete unknown.message_eligibility;stopped.status='stopped';stopped.status_reason='stopped';
      stoppedAgent.status='stopped';stoppedAgent.status_reason='stopped';stoppedAgent.message_eligibility={allowed:false,reason:'stopped',message:'[SYNTHETIC] 停止済み'};
    });
    await count(5);
    const runOrder=await page.locator('#runList .run-link').evaluateAll(nodes=>nodes.map(node=>node.dataset.focusKey.slice(4)));
    assert.deepEqual(runOrder,[...fixture.runs].reverse().map(run=>run.id),'Fixture retains the existing session-list transport order');
    const ordered=runOrder.flatMap(id=>fixture.runs.find(run=>run.id===id).agent_ids.map(agentId=>entries.find(agent=>agent.id===agentId)).filter(Boolean));
    assert.equal(ordered.length,5);assert(ordered.indexOf(worker)<ordered.indexOf(root),'The cyclic test distinguishes declared member order from root-first order');
    const outside=fixture.agents.find(agent=>agent.run_id===baseRun.id&&agent.id!==baseAgent.id);assert(outside);
    await select(outside);await page.locator('#agentSearch').fill('[SYNTHETIC] no crew matches');
    // Reach the new control by real Tab traversal, without test-side click
    // dispatch or calling the application’s selection/poll/render functions.
    await page.locator('#navSettings').focus();let tabs=0;
    while(!await focused('#nextMessageInput')&&tabs++<20)await page.keyboard.press('Tab');
    assert.equal(await focused('#nextMessageInput'),true,'Native Tab reaches the one discovery action');
    const tabPrevious=await owner(),tabStart=requests.length;await page.keyboard.press('Enter');
    assert.deepEqual(await owner(),{run:ordered[0].run_id,agent:ordered[0].id});
    assert.equal(await input.inputValue(),texts.get(ordered[0].id));assertOnlySelectedLoads(tabStart,ordered[0],tabPrevious);
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();
    for(let index=1;index<=ordered.length*2;index++)await activate(ordered[index%ordered.length],index%2?'Space':'Enter');
    await mode(true);await page.locator('#agentSearch').fill('[SYNTHETIC] no question matches');
    assert.equal(await page.locator('#agentCards .agent-card').count(),0);
    for(let index=1;index<=ordered.length;index++)await activate(ordered[index%ordered.length],index%2?'Enter':'Space');
    await mode(false);assert.equal(await page.locator('#agentSearch').inputValue(),'[SYNTHETIC] no crew matches');
    await mode(true);assert.equal(await page.locator('#agentSearch').inputValue(),'[SYNTHETIC] no question matches');
    await page.locator('#agentSearch').clear();await select(root);await assertMarker(root);await assertMarker(worker);await assertMarker(unknown);
    assert.equal(await card(stoppedAgent.id).count(),0,'Stopped residue stays outside question mode even though its input remains discoverable');
    assert(requests.slice(navigationStart).every(item=>item.method==='GET'&&item.path==='/api/state'),'Typing, presence rendering, filtering and cyclic navigation only load selected state');

    // Presence changes are semantic announcements, while edits inside an
    // already-present input and unchanged interval polls stay quiet.
    await page.evaluate(()=>{
      window.inputPresenceChanges=0;window.inputPresenceObserver=new MutationObserver(records=>{window.inputPresenceChanges+=records.length;});
      const count=document.querySelector('#messageInputCount'),live=count.closest('[aria-live="polite"], [role="status"]')||document.querySelector('#messageInputNavigationStatus');
      if(live){window.inputPresenceLive=live;window.inputPresenceObserver.observe(live,{subtree:true,childList:true,characterData:true});}
      window.inputPresenceObserver.observe(count,{subtree:true,childList:true,characterData:true});
      window.inputPresenceObserver.observe(document.querySelector('#nextMessageInput'),{attributes:true,attributeFilter:['aria-label','disabled']});
      window.inputPresenceStable={button:document.querySelector('#nextMessageInput'),count,card:document.querySelector('#agentCards .agent-card'),run:document.querySelector('#runList .run-link')};
    });
    assert.equal(await page.evaluate(()=>Boolean(window.inputPresenceLive)),true,'Input owner count has a polite status announcement');
    await input.focus();await page.keyboard.press('Control+Home');await page.keyboard.press('ArrowRight');await page.keyboard.press('Shift+ArrowRight');
    const cursor=await input.evaluate(node=>({value:node.value,start:node.selectionStart,end:node.selectionEnd,direction:node.selectionDirection}));
    await poll();await poll();
    assert.equal(await focused('#messageInput'),true);assert.deepEqual(await input.evaluate(node=>({value:node.value,start:node.selectionStart,end:node.selectionEnd,direction:node.selectionDirection})),cursor);
    assert.equal(await page.evaluate(()=>window.inputPresenceChanges),0,'Unchanged polling does not rewrite the live region, visual count, accessible name or disabled state');
    assert.equal(await page.evaluate(()=>{const nodes=window.inputPresenceStable;return nodes.button===document.querySelector('#nextMessageInput')&&nodes.count===document.querySelector('#messageInputCount')&&nodes.card===document.querySelector('#agentCards .agent-card')&&nodes.run===document.querySelector('#runList .run-link');}),true,'Unchanged polls retain input navigation, count, card and session nodes');
    await input.fill(texts.get(root.id)+'\n編集');await count(5);
    assert.equal(await page.evaluate(()=>window.inputPresenceChanges),0,'Text edits with unchanged presence do not rewrite count text or accessibility semantics');
    await input.clear();texts.set(root.id,'');await count(4);await assertMarker(root,false);
    assert((await page.evaluate(()=>window.inputPresenceChanges))>0,'Removing one owner updates the semantic input count');
    assert.match(await page.evaluate(()=>window.inputPresenceLive.textContent),/4人/,'The polite announcement reports the new number of owners');
    texts.set(root.id,'[SYNTHETIC] EXACT-INPUT-ROOT');await input.fill(texts.get(root.id));await count(5);await assertMarker(root);

    // A response claiming loaded selected detail while omitting that owner is
    // malformed. It cannot manufacture a removal, erase text, or change count.
    heldState=await holdNextRequest(page,'**/api/state*',async()=>{});
    const malformed=compactFixture(heldState.request());malformed.agents=malformed.agents.filter(agent=>agent.id!==root.id);
    await releaseResponse(page,heldState,malformed);heldState=null;
    assert.deepEqual(await owner(),{run:other.id,agent:root.id});await count(5);assert.equal(await input.inputValue(),texts.get(root.id));await poll();
    // Accepted disappearance hides only no-longer-known owners. Existing map
    // data remains recoverable if the same known owner returns in a later state.
    await select(baseAgent);
    await poll(()=>{fixture.agents=fixture.agents.filter(agent=>agent.id!==unknown.id);other.agent_ids=other.agent_ids.filter(id=>id!==unknown.id);});
    await count(4);assert.match(await runLink(other.id).textContent(),/入力\s*2人/);
    await poll(()=>{fixture.agents.push(unknown);other.agent_ids.push(unknown.id);});await count(5);await select(unknown);assert.equal(await input.inputValue(),texts.get(unknown.id));
    await select(baseAgent);
    await poll(()=>{fixture.runs=fixture.runs.filter(run=>run.id!==stopped.id);fixture.agents=fixture.agents.filter(agent=>agent.run_id!==stopped.id);});await count(4);
    await poll(()=>{fixture.runs.splice(10,0,stopped);fixture.agents.push(stoppedAgent);});await count(5);await select(stoppedAgent);assert.equal(await input.inputValue(),' \n\t ');

    // Delay a detail load across Next-driven A -> B -> A. The response cannot
    // flash stale details or perform deferred focus after explicit navigation.
    await select(root);heldState=await holdNextRequest(page,'**/api/state*',async()=>{});
    const obsolete=compactFixture(heldState.request()),marker='[SYNTHETIC] OBSOLETE INPUT PRESENCE DETAIL';
    obsolete.agents.find(agent=>agent.id===root.id).logs=[{id:9890,kind:'assistant',text:marker,at:other.created_at}];
    await page.evaluate(marker=>{window.inputPresenceSawObsolete=false;window.inputPresenceStaleObserver=new MutationObserver(()=>{
      if(document.body.textContent.includes(marker))window.inputPresenceSawObsolete=true;
    });window.inputPresenceStaleObserver.observe(document.body,{subtree:true,childList:true,characterData:true});},marker);
    // Re-read display order after the intentional remove/reinsert fixture pass.
    const currentOrder=await page.locator('#runList .run-link').evaluateAll(nodes=>nodes.map(node=>node.dataset.focusKey.slice(4)));
    const cycle=currentOrder.flatMap(id=>fixture.runs.find(run=>run.id===id).agent_ids.map(agentId=>entries.find(agent=>agent.id===agentId)).filter(Boolean));
    const rootIndex=cycle.indexOf(root);
    for(let step=1;step<=cycle.length;step++)await activate(cycle[(rootIndex+step)%cycle.length],step%2?'Enter':'Space',false);
    await page.locator('#agentSearch').focus();await releaseResponse(page,heldState,obsolete);heldState=null;
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();await paint();
    assert.equal(await page.evaluate(()=>window.inputPresenceSawObsolete),false,'Old ABA detail never flashes');
    assert.equal(await focused('#agentSearch'),true,'A late selected response cannot steal focus back to the composer');await count(5);
    assert.equal(await input.inputValue(),texts.get(root.id));

    // Existing send-epoch semantics remain authoritative. Discovery cannot
    // rename pending/failed/succeeded requests or clear a newer identical input.
    const sendStart=requests.length;
    for(const outcome of [{ok:true},{ok:false,error:'[SYNTHETIC] OBSOLETE INPUT SEND FAILURE'}]){
      heldSend=await holdNextRequest(page,`**/api/agents/${root.id}/message`,()=>page.locator('#sendMessage').click());
      assert.deepEqual(heldSend.request().postDataJSON(),{text:texts.get(root.id)});await count(5);
      for(let step=1;step<=cycle.length;step++)await activate(cycle[(rootIndex+step)%cycle.length],step%2?'Space':'Enter');
      await input.fill(texts.get(root.id)+'編集');await input.fill(texts.get(root.id));await input.focus();
      await releaseResponse(page,heldSend,outcome);heldSend=null;await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);await paint();
      assert.equal(await input.inputValue(),texts.get(root.id));assert.equal(await page.locator('#messageStatus').textContent(),'');
      assert.equal(await focused('#messageInput'),true);await count(5);await assertNeutral();
    }
    const sends=requests.slice(sendStart).filter(item=>item.method!=='GET');
    assert.deepEqual(sends.map(({path,method})=>({path,method})),Array.from({length:2},()=>({path:`/api/agents/${root.id}/message`,method:'POST'})));
    // A current successful send keeps the established clear-on-success rule;
    // presence disappears rather than inventing a separate sent state.
    heldSend=await holdNextRequest(page,`**/api/agents/${root.id}/message`,()=>page.locator('#sendMessage').click());
    heldState=await holdNextRequest(page,'**/api/state*',async()=>{await releaseResponse(page,heldSend,{ok:true});heldSend=null;});
    texts.set(root.id,'');assert.equal(await input.inputValue(),'');await count(4);await assertMarker(root,false);
    assert.equal(await page.locator('#sendMessage').isDisabled(),true,'The following state refresh is still pending when accepted input clears');
    await releaseResponse(page,heldState,compactFixture(heldState.request()));heldState=null;
    await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);await paint();await count(4);
    texts.set(root.id,'[SYNTHETIC] EXACT-INPUT-ROOT');await input.fill(texts.get(root.id));await count(5);

    // Existing card types, long identities, question text and the session
    // metadata remain legible in all supported viewport classes.
    for(const [name,width,height] of [['desktop',1366,768],['tablet',820,768],['narrow',390,844]]){
      await page.setViewportSize({width,height});await mode(false);await page.locator('#agentSearch').clear();await select(root);
      await next.focus();await assertVisible(next,name+' discovery button');await assertGeometry('input presence crew '+name);
      const focusStyle=await next.evaluate(node=>({outline:getComputedStyle(node).outlineStyle,shadow:getComputedStyle(node).boxShadow}));
      assert(focusStyle.outline!=='none'||focusStyle.shadow!=='none',name+': discovery has a visible keyboard focus indicator');
      await poll();assert.equal(await focused('#nextMessageInput'),true,name+': unchanged polls retain discovery focus');
      await page.screenshot({path:path.join(artifacts,'workbench-input-presence-'+name+'-crew.png'),fullPage:true,animations:'disabled'});
      await card(root.id).focus();await assertVisible(card(root.id),name+' crew input owner');await assertMarker(root);
      await mode(true);await page.locator('#agentSearch').clear();
      for(const [agent,state] of [[root,'enabled'],[worker,'blocked'],[unknown,'unknown eligibility']]){
        await card(agent.id).focus();await assertVisible(card(agent.id),name+' '+state+' question input owner');
        assert.equal(await card(agent.id).evaluate(node=>node===document.activeElement),true,name+': native focus remains on the '+state+' question card');
        await assertVisible(card(agent.id).locator('.question-open'),name+' '+state+' lower question open action');
        await assertMarker(agent);
      }
      await card(root.id).focus();await assertVisible(card(root.id),name+' screenshot question input owner');await assertGeometry('input presence questions '+name);
      await page.screenshot({path:path.join(artifacts,'workbench-input-presence-'+name+'-questions.png'),fullPage:true,animations:'disabled'});
      await next.focus();const position=cycle.indexOf(root),destination=cycle[(position+1)%cycle.length];
      await activate(destination,'Space');await assertVisible(page.locator(await input.isDisabled()?'#conversationHeading':'#messageInput'),name+' explicit destination');
    }
    // One remaining owner is still a useful focus action. Repeated native
    // activations neither manufacture another selection nor send its input.
    await mode(false);await page.locator('#agentSearch').clear();
    await poll(()=>{
      stopped.status='running';stopped.status_reason='working';
      for(const agent of [worker,unknown,stoppedAgent]){agent.status='waiting';agent.status_reason='human_input';agent.message_eligibility={allowed:true,reason:'',message:''};}
    });
    for(const agent of [root,worker,unknown,stoppedAgent]){await select(agent);await input.clear();texts.set(agent.id,'');}
    await count(1);await select(baseAgent);
    for(const key of ['Enter','Space','Enter'])await activate(baseAgent,key);
    await input.clear();texts.set(baseAgent.id,'');await count(0);
    const zeroOwner=await owner(),zeroStart=requests.length;
    await page.locator('#newRun').focus();await page.keyboard.press('Tab');
    assert.equal(await focused('#agentSearch'),true,'Native Tab skips the disabled action between New task and search');
    await next.scrollIntoViewIfNeeded();const zeroBox=await next.boundingBox();assert(zeroBox);
    await page.mouse.click(zeroBox.x+zeroBox.width/2,zeroBox.y+zeroBox.height/2);await paint();
    assert.deepEqual(await owner(),zeroOwner,'A disabled zero-owner pointer gesture leaves selection unchanged');
    assertOnlySelectedLoads(zeroStart,baseAgent);assert.equal(await input.inputValue(),'');
    assert.deepEqual(unexpected,[],'Discovery never attempted a send, stop, start, config, credential, or provider mutation');
    assert.deepEqual(providerRequests,providerBefore,'Input discovery produces no provider traffic');
    const storage=await page.evaluate(()=>{
      const read=store=>Object.fromEntries(Array.from({length:store.length},(_,index)=>{const key=store.key(index);return [key,store.getItem(key)];}));
      return {local:read(localStorage),session:read(sessionStorage)};
    });
    assert.deepEqual(storage,{local:before.local,session:before.session},'Input discovery adds no browser storage persistence');

    // Restore the encompassing smoke through native controls. Temporary input
    // owners are no longer counted once their synthetic owners disappear.
    await mode(false);await page.locator('#agentSearch').clear();await select(baseAgent);
    await poll(()=>Object.assign(fixture,structuredClone(original)));
    for(const agent of original.agents){await select(agent);if(await input.isEnabled())await input.fill(priorDrafts.get(agent.id));else assert.equal(await input.inputValue(),priorDrafts.get(agent.id));}
    await select(baseAgent);
    await page.locator('#newRun').click();await page.locator('#taskInput').fill(before.task);await page.locator('#preflightStatus[aria-busy="false"]').waitFor();await page.keyboard.press('Escape');
    await mode(false);await page.locator('#agentSearch').fill(before.searches.crew);await mode(true);await page.locator('#agentSearch').fill(before.searches.questions);
    await mode(before.questions);await page.setViewportSize(viewport);
    for(const detail of await page.locator('#conversationLog details').all())if(await detail.evaluate(node=>node.open)!==before.expanded.includes(await detail.getAttribute('data-log-id'))){
      await detail.locator(':scope > summary').focus();await page.keyboard.press('Enter');
    }
    if(await page.locator('#resultsPanel').evaluate(node=>node.open)!==before.resultsOpen){await page.locator('#resultsPanel > summary').focus();await page.keyboard.press('Enter');}
    await page.evaluate(saved=>{
      const input=document.querySelector('#messageInput'),log=document.querySelector('#conversationLog');input.setSelectionRange(saved.start,saved.end,saved.direction);
      const target=saved.focusLog?[...log.querySelectorAll('details > summary')].find(node=>node.parentElement.dataset.logId===saved.focusLog):
        saved.focusId?document.getElementById(saved.focusId):[...document.querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===saved.focusKey);
      target?.focus({preventScroll:true});log.scrollTop=saved.scroll;
      for(const [id,position] of Object.entries(saved.railScroll)){const node=document.getElementById(id);node.scrollTop=position.top;node.scrollLeft=position.left;}
      window.scrollTo(saved.x,saved.y);
    },before);
    assert.deepEqual(fixture,original);assert.deepEqual(await owner(),{run:before.run,agent:before.agent});
    assert.equal(await input.inputValue(),before.draft);assert.equal(await page.locator('#taskInput').inputValue(),before.task);
    await count([...priorDrafts.values()].filter(text=>text.length>0).length);
    assert.equal(await page.locator('#taskDialog').evaluate(node=>node.open),before.taskOpen);assert.equal(await page.locator('#settingsDialog').evaluate(node=>node.open),before.settingsOpen);
    assert.equal(await page.locator('#needsYou').getAttribute('aria-pressed'),String(before.questions));assert.equal(await page.locator('#agentSearch').inputValue(),before.search);
    assert.deepEqual(page.viewportSize(),viewport);restored=true;
    report.checks.push('neutral message-input discovery: 20 sessions, exact per-owner whitespace and multiteam/multiagent input, card markers and per-session people counts without snippets or send-state claims; task editor excluded; blocked/unknown/stopped input retained; one native Tab/Enter/Space cyclic action follows current session-list then declared member order independent of both retained roster searches/modes, repeated single-owner activation and zero-owner disabled Tab/pointer behavior; exact run+agent selected without intermediate loads, immediate enabled-composer/disabled-heading focus, no deferred focus; known agent/run disappearance and return retain input, malformed compact state rejected, delayed detail ABA and same-text old send success/error ABA remain guarded, current send retains normal clear-on-success contract; poll-stable DOM/caret/focus and quiet unchanged counts with semantic changed-count announcements; no new requests except existing selected-state loads, normal task preflight and three deliberately intercepted sends; no provider traffic or browser storage writes; desktop 1366x768/tablet 820x768/narrow 390x844 crew/question/long-identity/session metadata geometry and screenshots; original fixture and selected UI restored');
  } catch(error) {
    await page.screenshot({path:path.join(artifacts,'workbench-input-presence-failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});throw error;
  } finally {
    Object.assign(fixture,structuredClone(original));page.off('request',observer);await page.unroute('**/api/**',mutationGuard);
    if(heldState)await heldState.abort().catch(()=>{});if(heldSend)await heldSend.abort().catch(()=>{});
    await page.evaluate(()=>{
      window.inputPresenceObserver?.disconnect();window.inputPresenceStaleObserver?.disconnect();
      for(const key of ['inputPresenceObserver','inputPresenceChanges','inputPresenceLive','inputPresenceStable','inputPresenceStaleObserver','inputPresenceSawObsolete'])delete window[key];
    }).catch(()=>{});
    if(!restored)await page.setViewportSize(viewport).catch(()=>{});
  }
}

module.exports={inputPresenceAcceptance};
