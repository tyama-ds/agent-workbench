/* Global human-question navigation, using synthetic state and real native controls. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

async function allQuestionsAcceptance({page,fixture,compactFixture,artifacts,report,
  holdNextRequest,releaseResponse,assertLayout}) {
  const original=structuredClone(fixture),viewport=page.viewportSize();
  const before=await page.evaluate(()=>{
    const active=document.activeElement,input=document.querySelector('#messageInput'),log=document.querySelector('#conversationLog');
    return {run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey.slice(4),
      agent:document.querySelector('#agentTabs [aria-pressed="true"]')?.dataset.focusKey.slice(4),
      draft:input.value,start:input.selectionStart,end:input.selectionEnd,direction:input.selectionDirection,
      search:document.querySelector('#agentSearch').value,questions:document.querySelector('#needsYou').getAttribute('aria-pressed')==='true',
      resultsOpen:document.querySelector('#resultsPanel').open,
      expanded:[...log.querySelectorAll('details[open]')].map(detail=>detail.dataset.logId),scroll:log.scrollTop,
      x:scrollX,y:scrollY,focusId:active.id,focusKey:active.dataset.focusKey,
      focusLog:active.localName==='summary'?active.parentElement.dataset.logId:null,
      taskDraft:document.querySelector('#taskInput').value};
  });
  const run=fixture.runs.find(item=>item.id===before.run),pm=fixture.agents.find(item=>item.id===before.agent);
  assert(run&&pm&&pm.run_id===run.id,'Start from the surrounding smoke’s selected synthetic owner');
  const shortId=owner=>owner.id.slice(-8),blockedReason='[SYNTHETIC] モデルの設定を確認するまで回答を送信できません。';
  const makeRun=(id,task,created_at,status='running')=>({...structuredClone(run),id,task,created_at,status,
    status_reason:status==='waiting'?'teammates':status,agent_ids:[]});
  const older=makeRun('questions-run-old-0001','[SYNTHETIC] 古いチームの確認対象。部署ごとの確認資料と公開前の条件を、日本語で確かめる長い依頼。'.repeat(3)+'\n旧チーム検索用詳細',run.created_at-120);
  const other=makeRun('questions-run-new-0002','[SYNTHETIC] 別チーム見出し検索語\n本文専用検索語。別の担当者への依頼です。',run.created_at+120);
  const stopped=makeRun('questions-run-end-0003','[SYNTHETIC] 停止済みの残留質問',run.created_at+240,'stopped');
  const makeAgent=(id,owner,name,question,patch={})=>({...structuredClone(pm),id,run_id:owner.id,name:'[SYNTHETIC] '+name,
    role:'pm',parent_id:null,assignment:'[SYNTHETIC] 担当検索語 '+id,status:'waiting',status_reason:'human_input',question,
    message_eligibility:{allowed:true,reason:'',message:''},results:[],output_receipts:[],
    logs:[{id:9301,kind:'assistant',text:'[SYNTHETIC] 質問の履歴 '+id,at:owner.created_at}],...patch});
  const oldQuestion=makeAgent('questions-old-pm',older,'旧チーム責任者','[SYNTHETIC] 長い日本語の確認事項。対象の部署、共有する資料、外部公開の可否、希望する期限を確認してください。'.repeat(12));
  const otherRoot=makeAgent('questions-other-pm',other,'別チーム管理者','[SYNTHETIC] 仲間への確認であり人への質問ではありません。',{status_reason:'teammates'});
  const remote=makeAgent('questions-remote-worker',other,'遠隔質問担当検索語','[SYNTHETIC] 質問本文専用検索語。どの資料を共有できますか？',
    {parent_id:otherRoot.id,role:'worker'});
  const blocked=makeAgent('questions-blocked-worker',other,'回答不可担当','[SYNTHETIC] 設定の修正後に回答してください。',
    {parent_id:otherRoot.id,role:'worker',message_eligibility:{allowed:false,reason:'profile_missing',message:blockedReason}});
  const error=makeAgent('questions-error-worker',other,'エラー担当','[SYNTHETIC] エラー時の古い質問。',
    {parent_id:otherRoot.id,role:'worker',status:'error',status_reason:'error'});
  const empty=makeAgent('questions-empty-worker',other,'空欄質問担当',' \n\t ',{parent_id:otherRoot.id,role:'worker'});
  const stoppedAgent=makeAgent('questions-stopped-pm',stopped,'停止チーム担当','[SYNTHETIC] 停止チームに残った古い質問。');
  const stoppedMember=makeAgent('questions-stopped-worker',other,'停止担当','[SYNTHETIC] 停止した担当者の古い質問。',
    {parent_id:otherRoot.id,role:'worker',status:'stopped',status_reason:'stopped'});
  older.agent_ids=[oldQuestion.id];other.agent_ids=[otherRoot.id,remote.id,blocked.id,error.id,empty.id,stoppedMember.id];stopped.agent_ids=[stoppedAgent.id];
  const fillerStates=[['running','working'],['running','queued'],['waiting','waiting'],['waiting','error'],['done','done'],['stopped','stopped']];
  const fillerRuns=Array.from({length:16},(_,index)=>makeRun(`questions-run-extra-${String(index+4).padStart(4,'0')}`,
    '[SYNTHETIC] 実行一覧の上限確認 '+(index+4),run.created_at+300+index,
    fillerStates[index%fillerStates.length][0]));
  const fillerAgents=fillerRuns.map((team,index)=>{
    const status=fillerStates[index%fillerStates.length][1];
    const agent=makeAgent('questions-extra-pm-'+index,team,'一覧上限担当 '+index,'',
      {status,status_reason:status==='waiting'?'teammates':status});
    team.agent_ids=[agent.id];return agent;
  });
  const expected=[oldQuestion.id,pm.id,remote.id,blocked.id],requests=[],mutations=[];
  const currentResult='[SYNTHETIC] 表示中チームだけの報告',remoteResult='[SYNTHETIC] 別チーム質問担当だけの報告';
  const result=(text,id)=>({id,source:'assistant_response',text,at:run.created_at,turn:pm.turns,revision:pm.result_revision,truncated:false});
  const card=id=>page.locator(`#agentCards .agent-card[data-agent-id="${id}"]`);
  const runLink=id=>page.locator(`#runList [data-focus-key="run:${id}"]`);
  const focused=target=>target.evaluate(element=>element===document.activeElement);
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const owner=()=>page.evaluate(()=>({run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey.slice(4),
    agent:document.querySelector('#agentTabs [aria-pressed="true"]')?.dataset.focusKey.slice(4)}));
  const assertOwner=async(team,agent,label)=>{
    assert.deepEqual(await owner(),{run:team.id,agent:agent.id},label+': exact team and agent stay paired');
    assert.equal(await page.locator('#activeRunTask').textContent(),team.task,label+': full selected-team task');
    assert.equal(await page.locator('#activeRunTitle').textContent(),'表示中のチーム · '+shortId(team),label+': visible short team identity');
  };
  const ids=()=>page.locator('#agentCards .agent-card').evaluateAll(elements=>elements.map(element=>element.dataset.agentId));
  // Wait for a real interval-driven selected snapshot after changing the fixture;
  // never call application selection/render/poll internals from the test.
  const poll=async(change=()=>{})=>{
    const selected=await owner();
    const requested=page.waitForRequest(request=>{
      const url=new URL(request.url());return request.method()==='GET'&&url.pathname==='/api/state'&&
        url.searchParams.get('run_id')===selected.run&&url.searchParams.get('agent_id')===selected.agent;
    });
    change();const response=await (await requested).response();assert(response,'A real state poll receives a response');
    assert.equal(response.status(),200);await response.finished();await paint();
    assert.equal(await page.locator('#conversationLog').getAttribute('aria-busy'),'false');
  };
  const questionsMode=async(enabled)=>{
    if((await page.locator('#needsYou').getAttribute('aria-pressed')==='true')!==enabled){
      await page.locator('#needsYou').focus();await page.keyboard.press('Space');
    }
    assert.equal(await page.locator('#needsYou').getAttribute('aria-pressed'),String(enabled));
  };
  const count=async(total,filtered=total)=>{
    assert.equal(await page.locator('#questionCount').textContent(),String(total),'Header count includes all live questions independently of search/eligibility');
    assert.equal(await page.locator('#agentCount').textContent(),`${filtered} / ${total}`,'Roster reports its filtered and global question counts');
    assert.match(await page.locator('#questionQueueStatus').textContent(),new RegExp(`全チームの質問\\s*${total}件`));
  };
  const activate=async(agent,team,key='Enter',wait=true)=>{
    await card(agent.id).focus();await page.keyboard.press(key);
    await assertOwner(team,agent,'Question activation');
    assert.equal(await focused(page.locator('#humanQuestion')),true,'Native question activation immediately focuses the full question');
    assert((await page.locator('#humanQuestion').textContent()).includes(agent.question),'The complete selected question is already available');
    if(wait){await page.locator('#conversationLog[aria-busy="false"]').filter({hasText:'質問の履歴 '+agent.id}).waitFor();await paint();}
  };
  const observer=request=>{
    const url=new URL(request.url());if(!url.pathname.startsWith('/api/'))return;
    requests.push({path:url.pathname,method:request.method(),run:url.searchParams.get('run_id'),agent:url.searchParams.get('agent_id')});
    if(!['GET','HEAD','OPTIONS'].includes(request.method()))mutations.push({path:url.pathname,method:request.method()});
  };
  const assertVisible=async(target,label)=>{
    const area=await target.evaluate(element=>{
      const box=element.getBoundingClientRect();let left=0,top=0,right=innerWidth,bottom=innerHeight;
      for(let parent=element.parentElement;parent;parent=parent.parentElement){
        const style=getComputedStyle(parent),rect=parent.getBoundingClientRect();
        if(/auto|scroll|hidden|clip/.test(style.overflowX)){left=Math.max(left,rect.left+parent.clientLeft);right=Math.min(right,rect.left+parent.clientLeft+parent.clientWidth);}
        if(/auto|scroll|hidden|clip/.test(style.overflowY)){top=Math.max(top,rect.top+parent.clientTop);bottom=Math.min(bottom,rect.top+parent.clientTop+parent.clientHeight);}
      }
      const hit=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2);
      return {left:box.left,top:box.top,right:box.right,bottom:box.bottom,width:box.width,height:box.height,
        clipLeft:left,clipTop:top,clipRight:right,clipBottom:bottom,hit:hit===element||element.contains(hit)};
    });
    assert(area.width>0&&area.height>0&&area.left>=area.clipLeft-1&&area.right<=area.clipRight+1&&
      area.top>=area.clipTop-1&&area.bottom<=area.clipBottom+1,label+': focused target remains in its visible scroll regions');
    assert.equal(area.hit,true,label+': focused target is not obscured');
  };
  const assertShortIdVisible=async(agent,team,label)=>{
    const visible=await card(agent.id).evaluate((element,id)=>{
      const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);let node;
      while((node=walker.nextNode()))if(node.textContent.includes(id))break;
      if(!node)return false;
      const start=node.textContent.lastIndexOf(id),range=document.createRange();range.setStart(node,start);range.setEnd(node,start+id.length);
      const box=range.getBoundingClientRect();if(box.width<=0||box.height<=0)return false;
      // The roster itself may scroll; only clipping inside this card can hide
      // its ID. The viewport-focused screenshot separately proves reachability.
      for(let parent=node.parentElement;parent&&element.contains(parent);parent=parent.parentElement){
        const rect=parent.getBoundingClientRect(),style=getComputedStyle(parent);
        if((parent===element||/auto|scroll|hidden|clip/.test(style.overflowX))&&(box.left<rect.left-1||box.right>rect.right+1))return false;
        if((parent===element||/auto|scroll|hidden|clip/.test(style.overflowY))&&(box.top<rect.top-1||box.bottom>rect.bottom+1))return false;
      }
      return true;
    },shortId(team));
    assert.equal(visible,true,label+': full short team ID stays visible beside long clamped provenance');
  };
  const assertControlLayout=async(label)=>{
    await assertLayout(page,label);
    const controls=await page.evaluate(()=>{
      const box=id=>{const node=document.getElementById(id),rect=node.getBoundingClientRect();return {id,left:rect.left,right:rect.right,
        top:rect.top,bottom:rect.bottom,width:rect.width,height:rect.height,overflow:node.scrollWidth-node.clientWidth};};
      return {width:innerWidth,controls:['needsYou','navSettings','newRun','agentSearch'].map(box),
        cards:[...document.querySelectorAll('#agentCards .agent-card')].map(node=>{
          const rect=node.getBoundingClientRect();return {width:rect.width,overflow:node.scrollWidth-node.clientWidth,
            children:[...node.querySelectorAll('.question-run,.question-preview,.question-availability,.question-open,.agent-model,.agent-name')].map(child=>{
              const area=child.getBoundingClientRect();return {width:area.width,height:area.height,left:area.left-rect.left,right:area.right-rect.right,
                top:area.top-rect.top,bottom:area.bottom-rect.bottom};})};})};
    });
    for(const item of controls.controls){
      assert(item.width>0&&item.height>0,label+': '+item.id+' remains usable');
      assert(item.left>=-1&&item.right<=controls.width+1,label+': '+item.id+' stays inside viewport width');
      assert(item.overflow<=1,label+': '+item.id+' does not clip its control label');
    }
    for(const item of controls.cards){
      assert(item.overflow<=1,label+': question card has no horizontal overflow');
      for(const child of item.children)assert(child.width>0&&child.height>0&&child.left>=-1&&child.right<=1&&child.top>=-1&&child.bottom<=1,
        label+': provenance, question preview, answer eligibility, open action, model and agent name remain inside each card');
    }
  };
  let heldState,heldSend,restored=false;
  page.on('request',observer);
  try {
    await questionsMode(false);await page.locator('#agentSearch').clear();
    await poll(()=>{
      pm.status='waiting';pm.status_reason='human_input';pm.question='[SYNTHETIC] 表示中チームへの確認事項。';
      pm.results=[result(currentResult,9401)];
      remote.results=[result(remoteResult,9402)];
      // Deliberately non-chronological team and agent transport order: display
      // order comes from creation time, then the team’s declared agent order.
      fixture.runs=[other,...fillerRuns.slice(0,8),run,stopped,...fillerRuns.slice(8),older];
      fixture.agents.push(blocked,oldQuestion,otherRoot,error,remote,empty,stoppedAgent,stoppedMember,...fillerAgents);
      fixture.events.push({id:9403,run_id:other.id,kind:'mail',from:'別チーム',to:'質問担当',text:'[SYNTHETIC] 別チーム限定の進捗',at:other.created_at});
    });
    assert.equal(await page.locator('#runList .run-link').count(),20,'All 20 retained sessions participate in the global view');
    assert.equal(await page.locator('#runCount').textContent(),'20 / 20');
    const centerBefore=await page.locator('#activityFeed').textContent();
    assert.equal(await page.locator('#questionCount').textContent(),'4','Running teams can contain waiting questions; blocked replies still count');
    assert.equal(await page.locator('#needsYou').evaluate(node=>node.childNodes[0].textContent.trim()),'全チームの質問','Toggle label remains stable beside its separate count');
    await questionsMode(true);
    assert.equal(await page.locator('#rosterHeading').textContent(),'質問');
    assert.match(await page.locator('#rosterScope').textContent(),/全チーム/);
    assert.equal(await page.locator('#questionQueueStatus').getAttribute('aria-live'),'polite');
    assert.equal(await page.locator('#humanQuestion').getAttribute('tabindex'),'0');
    await count(4);assert.deepEqual(await ids(),expected,'Oldest team first, then declared agent order');
    await assertOwner(run,pm,'Global mode is a sidebar view');
    assert.equal(await page.locator('#activityFeed').textContent(),centerBefore,'Global mode leaves selected-team activity in the center');
    assert.equal(await page.locator('#resultText').textContent(),currentResult,'Global mode leaves selected-agent result provenance intact');
    for(const agent of [otherRoot,error,empty,stoppedAgent,stoppedMember])assert.equal(await card(agent.id).count(),0,'Non-human/empty/stopped residue is excluded: '+agent.id);
    assert.match(await card(remote.id).locator('.question-run').textContent(),/別チーム見出し検索語/);
    assert((await card(remote.id).locator('.question-run').textContent()).includes(shortId(other)));
    assert.equal(await card(remote.id).getAttribute('data-focus-key'),'question:'+remote.id);
    assert((await card(remote.id).locator('.question-preview').textContent()).includes('質問本文専用検索語'));
    assert.match(await card(remote.id).locator('.question-availability').textContent(),/回答可能/);
    assert.match(await card(blocked.id).locator('.question-availability').textContent(),/回答不可/);
    assert((await card(blocked.id).locator('.question-availability').textContent()).includes(blockedReason));
    for(const [team,total] of [[older,1],[run,1],[other,2]])assert.match(await runLink(team.id).textContent(),new RegExp(`質問\\s*${total}件`));
    assert.doesNotMatch(await runLink(stopped.id).textContent(),/質問\s*[1-9]/);

    for(const [query,matches] of [['本文専用検索語',[remote.id,blocked.id]],['質問本文専用検索語',[remote.id]],
      ['遠隔質問担当検索語',[remote.id]],[remote.id,[remote.id]],['担当検索語 '+remote.id,[remote.id]],
      [other.id,[remote.id,blocked.id]],['存在しない質問検索語',[]]]){
      await page.locator('#agentSearch').fill(query);assert.deepEqual(await ids(),matches,'Global search finds run/task/question/agent identity: '+query);
      await count(4,matches.length);await assertOwner(run,pm,'Searching questions');
    }
    assert.equal(await page.locator('#rosterEmpty').isVisible(),true);
    await page.locator('#agentSearch').clear();await count(4);
    await page.locator('#agentSearch').focus();await page.keyboard.press('Tab');
    assert.equal(await focused(card(oldQuestion.id)),true,'Native Tab enters the first question');
    await page.evaluate(()=>{
      window.questionsStatusChanges=0;window.questionsStatusObserver=new MutationObserver(records=>{window.questionsStatusChanges+=records.length;});
      window.questionsStatusObserver.observe(document.querySelector('#questionQueueStatus'),{childList:true,subtree:true,characterData:true});
    });
    await poll();assert.equal(await focused(card(oldQuestion.id)),true,'Unchanged polling retains keyboard ownership');
    assert.equal(await page.evaluate(()=>window.questionsStatusChanges),0,'Unchanged counts do not rewrite the polite status region');
    await page.keyboard.press('Tab');assert.equal(await focused(card(pm.id)),true);
    await page.keyboard.press('Tab');assert.equal(await focused(card(remote.id)),true);
    const draftA='[SYNTHETIC] 表示中チームの未送信回答',draftB='[SYNTHETIC] 別チーム担当の未送信回答';
    await page.locator('#messageInput').fill(draftA);
    const navigationStart=requests.length;
    await activate(remote,other,'Enter');
    assert.equal(await page.locator('#resultText').textContent(),remoteResult);
    assert.match(await page.locator('#activityFeed').textContent(),/別チーム限定の進捗/);
    assert.equal(await page.locator('#messageInput').inputValue(),'');
    for(const request of requests.slice(navigationStart).filter(item=>item.path==='/api/state'&&item.run===other.id))
      assert.equal(request.agent,remote.id,'Cross-team question navigation never requests an intermediate root agent');
    await page.locator('#messageInput').fill(draftB);
    await activate(blocked,other,'Space');
    assert.equal(await page.locator('#messageInput').isDisabled(),true);assert.equal(await page.locator('#sendMessage').isDisabled(),true);
    assert.equal(await page.locator('#messageEligibility').textContent(),blockedReason);
    await card(pm.id).click();await assertOwner(run,pm,'Pointer activation');
    assert.equal(await focused(page.locator('#humanQuestion')),true,'Pointer activation also focuses the question immediately');
    assert.equal(await page.locator('#messageInput').inputValue(),draftA);
    await activate(remote,other);assert.equal(await page.locator('#messageInput').inputValue(),draftB);
    await card(pm.id).click();await page.locator('#conversationLog[aria-busy="false"]').waitFor();
    assert.equal(await page.locator('#messageInput').inputValue(),draftA);

    // A held selected-detail response must not become current after A → B → A.
    heldState=await holdNextRequest(page,'**/api/state*',async()=>{});
    assert.equal(new URL(heldState.request().url()).searchParams.get('agent_id'),pm.id);
    const obsolete=compactFixture(heldState.request()),marker='[SYNTHETIC] OBSOLETE GLOBAL QUESTION RESPONSE';
    obsolete.agents.find(agent=>agent.id===pm.id).logs=[{id:9450,kind:'assistant',text:marker,at:run.created_at}];
    obsolete.agents.find(agent=>agent.id===pm.id).question=marker;
    await page.evaluate(marker=>{
      window.questionsSawObsolete=false;window.questionsObserver=new MutationObserver(()=>{
        if(document.body.textContent.includes(marker))window.questionsSawObsolete=true;
      });window.questionsObserver.observe(document.body,{childList:true,subtree:true,characterData:true});
    },marker);
    await activate(remote,other,'Enter',false);
    assert.equal(await page.locator('#resultText').textContent(),'','Loading cannot display the previous owner’s result');
    assert.doesNotMatch(await page.locator('#conversationLog').textContent(),/作業を2つに分けました/);
    await activate(pm,run,'Space',false);
    const newerDraft='[SYNTHETIC] 選択往復後の新しい下書き';
    await page.locator('#messageInput').fill(newerDraft);await page.locator('#messageInput').focus();
    await releaseResponse(page,heldState,obsolete);heldState=null;
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();await paint();
    assert.equal(await page.evaluate(()=>window.questionsSawObsolete),false,'Obsolete selected snapshots never flash in question/roster/history after ABA');
    assert.equal(await focused(page.locator('#messageInput')),true);assert.equal(await page.locator('#messageInput').inputValue(),newerDraft);
    await page.evaluate(()=>window.questionsObserver.disconnect());
    await assertOwner(run,pm,'Delayed response');await count(4);
    assert.deepEqual(mutations,[],'Opening/searching/activating global questions sends no POST or other mutation');

    // Count arrivals preserve exact input selection and never select another team.
    const arrival=makeAgent('questions-arriving-worker',older,'後から届いた担当','[SYNTHETIC] 新しく届いた確認です。',
      {parent_id:oldQuestion.id,role:'worker',message_eligibility:undefined});
    await page.locator('#messageInput').evaluate(input=>input.setSelectionRange(3,15,'backward'));
    await poll(()=>{fixture.agents.push(arrival);older.agent_ids.push(arrival.id);});
    await count(5);await assertOwner(run,pm,'Question arrival');
    assert((await page.evaluate(()=>window.questionsStatusChanges))>0,'A changed global count updates the polite announcement');
    assert.equal(await focused(page.locator('#messageInput')),true,'Arrival cannot steal composer focus');
    assert.deepEqual(await page.locator('#messageInput').evaluate(input=>({text:input.value,start:input.selectionStart,end:input.selectionEnd,direction:input.selectionDirection})),
      {text:newerDraft,start:3,end:15,direction:'backward'});
    assert.match(await card(arrival.id).locator('.question-availability').textContent(),/送信可否未確認/);
    await activate(arrival,older);
    assert.equal(await page.locator('#messageInput').isDisabled(),true,'Unknown reply eligibility never implies permission to send');
    assert.equal(await page.locator('#sendMessage').isDisabled(),true);
    await card(pm.id).click();await page.locator('#conversationLog[aria-busy="false"]').waitFor();
    assert.equal(await page.locator('#messageInput').inputValue(),newerDraft);
    assert.deepEqual(mutations,[],'Unknown eligibility remains navigable without sending a message');
    await page.locator('#agentSearch').fill('質問本文専用検索語');await page.locator('#agentSearch').focus();
    await poll(()=>{arrival.question='';arrival.status_reason='working';arrival.status='working';});
    await count(4,1);assert.equal(await focused(page.locator('#agentSearch')),true,'Changed counts cannot steal search focus');
    await page.locator('#agentSearch').clear();

    for(const [open,close,modal,control] of [['navSettings','closeSettings','settingsDialog','closeSettings'],['newRun',null,'taskDialog','taskInput']]){
      await page.locator('#'+open).click();await page.locator('#'+control).focus();
      await poll(()=>{arrival.question='[SYNTHETIC] モーダルの後ろで届いた質問';arrival.status_reason='human_input';arrival.status='waiting';});
      await count(5);assert.equal(await focused(page.locator('#'+control)),true,'Count changes cannot steal '+modal+' focus');
      assert.equal(await page.locator('#'+modal).evaluate(dialog=>dialog.open&&dialog.contains(document.activeElement)),true);
      if(close)await page.locator('#'+close).click();else await page.keyboard.press('Escape');
      await poll(()=>{arrival.question='';arrival.status_reason='working';arrival.status='working';});await count(4);
    }
    assert.equal(await page.locator('#taskInput').inputValue(),before.taskDraft,'Testing the task modal does not edit its draft');
    assert(mutations.every(item=>item.path==='/api/run-preflight'&&item.method==='POST'),'Only the task dialog’s existing read-only preview may POST');

    // Own one-time routes avoid the surrounding smoke’s sentMessages fixture.
    // A successful old send must not erase newer identical text, including its
    // saved draft, after both an edit/restore and a cross-team A → B → A.
    const sendStart=mutations.length,sameText='[SYNTHETIC] 同じ文字列でも新しく編集した回答';
    await page.locator('#messageInput').fill(sameText);
    heldSend=await holdNextRequest(page,`**/api/agents/${pm.id}/message`,()=>page.locator('#sendMessage').click());
    assert.deepEqual(heldSend.request().postDataJSON(),{text:sameText});
    await activate(remote,other);await card(pm.id).click();
    await page.locator('#messageInput').fill(sameText+'を編集');await page.locator('#messageInput').fill(sameText);
    await page.locator('#messageInput').focus();
    await releaseResponse(page,heldSend,{ok:true});heldSend=null;
    await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);await paint();
    assert.equal(await page.locator('#messageInput').inputValue(),sameText,'Old success cannot erase a newer identical draft');
    assert.equal(await page.locator('#messageStatus').textContent(),'','Old success cannot report feedback in the newer same-ID selection');
    assert.equal(await focused(page.locator('#messageInput')),true);
    await activate(remote,other);await card(pm.id).click();
    assert.equal(await page.locator('#messageInput').inputValue(),sameText,'The newer same-text draft survives another navigation round trip');
    heldSend=await holdNextRequest(page,`**/api/agents/${pm.id}/message`,()=>page.locator('#sendMessage').click());
    await activate(remote,other);await card(pm.id).click();await page.locator('#messageInput').focus();
    await releaseResponse(page,heldSend,{ok:false,error:'[SYNTHETIC] OBSOLETE QUESTION SEND ERROR'});heldSend=null;
    await page.waitForFunction(()=>!document.querySelector('#sendMessage').disabled);await paint();
    assert.equal(await page.locator('#messageStatus').textContent(),'','Old rejection cannot overwrite newer selection feedback after ABA');
    assert.equal(await page.locator('#messageInput').inputValue(),sameText);
    assert.deepEqual(mutations.slice(sendStart),[{path:`/api/agents/${pm.id}/message`,method:'POST'},{path:`/api/agents/${pm.id}/message`,method:'POST'}],
      'Only the two deliberate, intercepted sends may mutate during send-race tests');

    // The full question is keyboard-scrollable; provenance and controls are
    // captured in all three supported viewport classes with long Japanese text.
    await activate(oldQuestion,older);
    for(const [name,width,height] of [['desktop',1366,768],['tablet',820,768],['narrow',390,844]]){
      await page.setViewportSize({width,height});await card(oldQuestion.id).click();await paint();
      assert.equal(await focused(page.locator('#humanQuestion')),true);
      await page.keyboard.press('End');
      await page.waitForFunction(()=>{const question=document.querySelector('#humanQuestion');return question.scrollTop>0&&question.scrollHeight-question.clientHeight-question.scrollTop<=1;});
      const questionScroll=await page.locator('#humanQuestion').evaluate(question=>question.scrollTop);
      await poll();assert.equal(await focused(page.locator('#humanQuestion')),true,'Polling retains full-question keyboard focus at '+name);
      assert.equal(await page.locator('#humanQuestion').evaluate(question=>question.scrollTop),questionScroll,'Unchanged question polling preserves its reading position');
      await assertVisible(page.locator('#humanQuestion'),'Full question '+name);
      await assertControlLayout('all questions '+name);
      await assertShortIdVisible(oldQuestion,older,name);
      await page.screenshot({path:path.join(artifacts,'workbench-questions-'+name+'.png'),fullPage:true,animations:'disabled'});
    }
    // Removal is a focus fallback, never a selection jump. Repeat in vertical
    // desktop and horizontal narrow rosters, without test-side scroll repairs.
    const savedQuestions=[pm,remote,blocked,oldQuestion].map(agent=>({agent,question:agent.question}));
    for(const [name,width,height] of [['desktop',1366,768],['narrow',390,844]]){
      await page.setViewportSize({width,height});
      await poll(()=>{for(const {agent,question} of savedQuestions)Object.assign(agent,{question,status_reason:'human_input',status:'waiting'});});
      await card(pm.id).click();await page.locator('#conversationLog[aria-busy="false"]').waitFor();
      await card(pm.id).focus();
      await poll(()=>{pm.question='';pm.status_reason='working';pm.status='working';});
      assert.equal(await focused(card(remote.id)),true,'Removing a focused middle question chooses its next surviving neighbor');
      await assertVisible(card(remote.id),name+' next fallback');
      await assertOwner(run,pm,'Question removal');await count(3);
      await card(blocked.id).focus();
      await poll(()=>{blocked.question='';blocked.status_reason='working';blocked.status='working';});
      assert.equal(await focused(card(remote.id)),true,'Removing the last question chooses its previous surviving neighbor');await count(2);
      await assertVisible(card(remote.id),name+' previous fallback');
      await page.screenshot({path:path.join(artifacts,'workbench-questions-'+name+'-removal.png'),fullPage:false,animations:'disabled'});
      await poll(()=>{remote.question='';remote.status_reason='working';remote.status='working';oldQuestion.question='';oldQuestion.status_reason='working';oldQuestion.status='working';});
      await count(0);assert.equal((await ids()).length,0);assert.equal(await page.locator('#rosterEmpty').isVisible(),true);
      assert.equal(await focused(page.locator('#needsYou')),true,'Removing all questions falls back to the existing global toggle');
      await assertVisible(page.locator('#needsYou'),name+' empty fallback');
      await assertOwner(run,pm,'Final question removal');
      await poll(()=>{oldQuestion.question='[SYNTHETIC] 次の確認事項';oldQuestion.status_reason='human_input';oldQuestion.status='waiting';});
      await count(1);assert.equal(await focused(page.locator('#needsYou')),true,'A later question cannot steal fallback focus');
      await assertOwner(run,pm,'Arrival after empty queue');
    }

    // Restore the original selected owner through native controls before removing
    // temporary teams. Only the original selected agent’s draft was edited.
    await poll(()=>Object.assign(fixture,structuredClone(original)));
    await questionsMode(false);await page.locator('#agentSearch').clear();
    if((await owner()).run!==before.run)await runLink(before.run).click();
    if((await owner()).agent!==before.agent)await page.locator(`#agentTabs [data-focus-key="tab:${before.agent}"]`).click();
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();await poll();
    await page.locator('#messageInput').fill(before.draft);await page.setViewportSize(viewport);
    for(const detail of await page.locator('#conversationLog details').all()){
      const id=await detail.getAttribute('data-log-id');
      if(await detail.evaluate(node=>node.open)!==before.expanded.includes(id)){
        await detail.locator(':scope > summary').focus();await page.keyboard.press('Enter');
      }
    }
    if(await page.locator('#resultsPanel').evaluate(node=>node.open)!==before.resultsOpen){
      await page.locator('#resultsPanel > summary').focus();await page.keyboard.press('Enter');
    }
    // Clear the temporary question-mode search separately from the crew query.
    await questionsMode(true);await page.locator('#agentSearch').clear();await questionsMode(before.questions);
    await page.locator('#agentSearch').fill(before.search);
    await page.evaluate(saved=>{
      const input=document.querySelector('#messageInput'),log=document.querySelector('#conversationLog');
      input.setSelectionRange(saved.start,saved.end,saved.direction);
      const target=saved.focusLog?[...log.querySelectorAll('details > summary')].find(node=>node.parentElement.dataset.logId===saved.focusLog):
        saved.focusId?document.getElementById(saved.focusId):[...document.querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===saved.focusKey);
      target?.focus({preventScroll:true});log.scrollTop=saved.scroll;window.scrollTo(saved.x,saved.y);
    },before);
    assert.deepEqual(fixture,original);assert.deepEqual(await owner(),{run:before.run,agent:before.agent});
    assert.equal(await page.locator('#messageInput').inputValue(),before.draft);
    assert.equal(await page.locator('#agentSearch').inputValue(),before.search);
    assert.equal(await page.locator('#needsYou').getAttribute('aria-pressed'),String(before.questions));
    assert.deepEqual(await page.locator('#conversationLog details[open]').evaluateAll(elements=>elements.map(node=>node.dataset.logId)),before.expanded);
    assert.equal(await page.locator('#resultsPanel').evaluate(node=>node.open),before.resultsOpen);assert.deepEqual(page.viewportSize(),viewport);
    restored=true;
    report.checks.push('all-team questions: 20 retained mixed-state sessions, global count/search and stable oldest-team/member ordering; running-team pauses and blocked and unknown-eligibility replies included but disabled, empty/error/teammate/stopped residue excluded; selected center provenance unchanged until native Enter/Space/pointer activation chooses exact team+agent and focuses full question; per-agent drafts, compact delayed selection ABA, same-text edit/restore and delayed send success/error ABA, composer selection/search/modal focus, unchanged polite status is not rewritten, changed-count announcements, visible desktop/narrow next/previous/toggle removal fallback and no auto-selection on arrivals; navigation sends no mutations; only two intercepted synthetic message sends; desktop 1366x768, tablet 820x768 and narrow 390x844 long-Japanese question/provenance/control screenshots; original fixture and UI context restored');
  } catch(error) {
    await page.screenshot({path:path.join(artifacts,'workbench-questions-failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});
    throw error;
  } finally {
    Object.assign(fixture,structuredClone(original));page.off('request',observer);
    if(heldState)await heldState.abort().catch(()=>{});if(heldSend)await heldSend.abort().catch(()=>{});
    await page.evaluate(()=>{window.questionsObserver?.disconnect();window.questionsStatusObserver?.disconnect();delete window.questionsObserver;delete window.questionsSawObsolete;delete window.questionsStatusObserver;delete window.questionsStatusChanges;}).catch(()=>{});
    // A failed acceptance stops the enclosing smoke; do not mask its first error
    // with cleanup navigation or accidentally submit anything while unwinding.
    if(!restored)await page.setViewportSize(viewport).catch(()=>{});
  }
}

module.exports={allQuestionsAcceptance};
