/* Text-only task reuse: native controls, synthetic retained teams, no inference. */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

async function taskReuseAcceptance({page,fixture,compactFixture,providerRequests,artifacts,report,
  holdNextRequest,releaseResponse,assertLayout,assertDialogLayout}) {
  const original=structuredClone(fixture),viewport=page.viewportSize(),providerBefore=structuredClone(providerRequests);
  const before=await page.evaluate(()=>{
    const active=document.activeElement,input=document.querySelector('#messageInput'),log=document.querySelector('#conversationLog');
    return {run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey.slice(4),
      agent:document.querySelector('#agentTabs [aria-pressed="true"]')?.dataset.focusKey.slice(4),
      draft:input.value,start:input.selectionStart,end:input.selectionEnd,direction:input.selectionDirection,
      search:document.querySelector('#agentSearch').value,questions:document.querySelector('#needsYou').getAttribute('aria-pressed')==='true',
      expanded:[...log.querySelectorAll('details[open]')].map(node=>node.dataset.logId),scroll:log.scrollTop,
      resultsOpen:document.querySelector('#resultsPanel').open,x:scrollX,y:scrollY,focusId:active.id,
      focusKey:active.dataset.focusKey,focusLog:active.localName==='summary'?active.parentElement.dataset.logId:null,
      task:document.querySelector('#taskInput').value,pm:document.querySelector('#pmProfile').value,
      workers:[...document.querySelectorAll('#workerProfiles input:checked')].map(node=>node.value),
      count:document.querySelector('#maxWorkers').value,notice:{text:document.querySelector('#globalNotice').textContent,
        hidden:document.querySelector('#globalNotice').hidden,className:document.querySelector('#globalNotice').className}};
  });
  const baseRun=fixture.runs.find(run=>run.id===before.run),baseAgent=fixture.agents.find(agent=>agent.id===before.agent);
  assert(baseRun&&baseAgent,'Reuse acceptance starts with the smoke’s selected synthetic owner');
  const sourceText='  [SYNTHETIC] 表示中の依頼だけをそのまま再利用。\n'+
    '<img src=x onerror="window.taskReuseInjected=true"> & <script>window.taskReuseInjected=true</script>\n'+
    '[redacted] は復元しません。\t行末の空白も保持。  \n'+
    Array.from({length:24},(_,index)=>`確認項目 ${index+1}: 日本語の資料、対象の部署、期限、公開前の確認条件を整理してください。`).join('\n')+'\n  ';
  const source={...structuredClone(baseRun),id:'reuse-source-run-0027',task:sourceText,status:'stopped',status_reason:'stopped',
    created_at:baseRun.created_at+100,pm_profile:'historical-profile-do-not-copy',worker_profiles:['historical-worker-do-not-copy'],
    max_workers:15,agent_ids:['reuse-source-pm-0027']};
  const sourceAgent={...structuredClone(baseAgent),id:source.agent_ids[0],run_id:source.id,parent_id:null,role:'pm',
    name:'[SYNTHETIC] 再利用元の担当者',assignment:'[SYNTHETIC] ASSIGNMENT MUST NOT BECOME TASK',
    status:'stopped',status_reason:'stopped',question:'',logs:[{id:9701,kind:'assistant',text:'[SYNTHETIC] SOURCE LOG MUST NOT BECOME TASK',at:source.created_at}],
    results:[{id:9702,source:'assistant_response',text:'[SYNTHETIC] RESULT MUST NOT BECOME TASK',at:source.created_at,
      turn:baseAgent.turns,revision:baseAgent.result_revision,truncated:false}],output_receipts:[],
    message_eligibility:{allowed:false,reason:'stopped',message:'[SYNTHETIC] 停止済み'}};
  const other={...structuredClone(source),id:'reuse-other-run-0028',task:'[SYNTHETIC] 別のチームの依頼',
    created_at:source.created_at+1,status:'done',status_reason:'done',agent_ids:['reuse-other-pm-0028']};
  const otherAgent={...structuredClone(sourceAgent),id:other.agent_ids[0],run_id:other.id,status:'done',status_reason:'done'};
  const requests=[],unexpected=[],paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const runLink=id=>page.locator(`#runList [data-focus-key="run:${id}"]`);
  const focused=selector=>page.locator(selector).evaluate(node=>node===document.activeElement);
  const owner=()=>page.evaluate(()=>({run:document.querySelector('#runList .run-link.selected')?.dataset.focusKey.slice(4),
    agent:document.querySelector('#agentTabs [aria-pressed="true"]')?.dataset.focusKey.slice(4)}));
  const choices=()=>page.evaluate(()=>({pm:document.querySelector('#pmProfile').value,
    workers:[...document.querySelectorAll('#workerProfiles input:checked')].map(node=>node.value),count:document.querySelector('#maxWorkers').value}));
  const currentChoices={pm:'local',workers:['openai'],count:'1'};
  const editorText=text=>text.replace(/\r\n?/g,'\n');
  const preflights=()=>requests.filter(item=>item.path==='/api/run-preflight');
  const observer=request=>{
    const url=new URL(request.url());if(!url.pathname.startsWith('/api/')||['GET','HEAD','OPTIONS'].includes(request.method()))return;
    requests.push({path:url.pathname,method:request.method(),body:request.postDataJSON()});
  };
  // This guard is above the surrounding fixture handlers. An accidental write
  // cannot create a synthetic team or touch real saved settings/credentials.
  const mutationGuard=async route=>{
    const request=route.request(),url=new URL(request.url());
    if(['GET','HEAD','OPTIONS'].includes(request.method())||url.pathname==='/api/run-preflight')return route.fallback();
    unexpected.push({path:url.pathname,method:request.method()});await route.abort('blockedbyclient');
  };
  // Observe interval-driven state delivery; do not call application internals.
  const poll=async(change=()=>{})=>{
    const selected=await owner();
    const requested=page.waitForRequest(request=>{
      const url=new URL(request.url());return request.method()==='GET'&&url.pathname==='/api/state'&&
        url.searchParams.get('run_id')===selected.run&&url.searchParams.get('agent_id')===selected.agent;
    });
    change();const response=await (await requested).response();assert(response);assert.equal(response.status(),200);
    await response.finished();await paint();
  };
  const close=async()=>{
    if(await page.locator('#taskDialog').isVisible())await page.keyboard.press('Escape');
    await page.locator('#taskDialog').waitFor({state:'hidden'});await paint();
  };
  const setDraft=async text=>{
    await close();await page.locator('#newRun').click();await page.locator('#taskInput').fill(text);
    await page.locator('#preflightStatus[aria-busy="false"]').waitFor();await close();
  };
  const select=async id=>{
    await close();await runLink(id).click();await page.locator(`#runList .run-link.selected[data-focus-key="run:${id}"]`).waitFor();
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();await paint();
  };
  const reuse=async(key='Enter')=>{
    await page.locator('#reuseTask').focus();await page.keyboard.press(key);
    await page.locator('#taskDialog').waitFor({state:'visible'});await paint();
    assert.equal(await page.locator('#taskDialog').evaluate(dialog=>dialog.contains(document.activeElement)),true,
      'Native reuse activation moves focus into the existing task dialog');
    assert.deepEqual(await choices(),currentChoices,'Reuse never substitutes the historical team’s model, worker or count choices');
  };
  const candidate=async draft=>{
    await setDraft(draft);const count=preflights().length;await reuse();
    await page.locator('#taskReuseConfirm').waitFor({state:'visible'});
    assert.equal(await page.locator('#taskInput').inputValue(),draft,'Pending overwrite preserves every draft character');
    assert.equal(await page.locator('#taskReusePreview').textContent(),editorText(source.task),'The confirmation changes only native textarea line endings');
    assert((await page.locator('#taskReuseCandidateSource').textContent()).includes(source.id.slice(-8)),
      'Pending confirmation identifies the candidate’s exact source team');
    assert.match(await page.locator('#taskReuseCandidateSource').textContent(),/表示用/);
    assert.equal(await page.locator('#startRun').isDisabled(),true,'Unresolved Keep/Replace blocks Start');
    await poll();assert.equal(preflights().length,count,'Pending overwrite does not issue a preview request');
  };
  const assertNoCandidate=async(text,label)=>{
    assert.equal(await page.locator('#taskReuseConfirm').isVisible(),false,label+': confirmation is invalidated');
    assert.equal(await page.locator('#taskInput').inputValue(),text,label+': no stale replacement');
    assert.deepEqual(await choices(),currentChoices,label+': choices preserved');
  };
  const assertVisible=async(selector,label)=>{
    const area=await page.locator(selector).evaluate(node=>{
      const box=node.getBoundingClientRect();let left=0,top=0,right=innerWidth,bottom=innerHeight;
      for(let parent=node.parentElement;parent;parent=parent.parentElement){
        const style=getComputedStyle(parent),rect=parent.getBoundingClientRect();
        if(/auto|scroll|hidden|clip/.test(style.overflowX)){left=Math.max(left,rect.left+parent.clientLeft);right=Math.min(right,rect.left+parent.clientLeft+parent.clientWidth);}
        if(/auto|scroll|hidden|clip/.test(style.overflowY)){top=Math.max(top,rect.top+parent.clientTop);bottom=Math.min(bottom,rect.top+parent.clientTop+parent.clientHeight);}
      }
      const hit=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2);
      return {left:box.left,top:box.top,right:box.right,bottom:box.bottom,width:box.width,height:box.height,
        clipLeft:left,clipTop:top,clipRight:right,clipBottom:bottom,hit:hit===node||node.contains(hit),overflow:node.scrollWidth-node.clientWidth};
    });
    assert(area.width>0&&area.height>0&&area.left>=area.clipLeft-1&&area.right<=area.clipRight+1&&
      area.top>=area.clipTop-1&&area.bottom<=area.clipBottom+1,label+': control is inside all visible clipping regions');
    assert.equal(area.hit,true,label+': control is not obscured');
    assert(area.overflow<=1,label+': text does not overflow horizontally');
  };
  let heldState,heldStart,restored=false;
  page.on('request',observer);await page.route('**/api/**',mutationGuard);
  try {
    if(before.questions)await page.locator('#needsYou').click();await page.locator('#agentSearch').clear();
    await poll(()=>{fixture.runs.push(source,other);fixture.agents.push(sourceAgent,otherAgent);});
    await select(source.id);
    await page.locator('#newRun').click();await page.locator('#pmProfile').selectOption(currentChoices.pm);
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.setChecked(currentChoices.workers.includes(await checkbox.inputValue()));
    await page.locator('#maxWorkers').fill(currentChoices.count);await page.locator('#taskInput').clear();
    await page.locator('#preflightStatus[aria-busy="false"]').waitFor();await close();
    assert.equal(await page.locator('#reuseTask').getAttribute('type'),'button','Reuse is never a submit control');
    assert.equal(await page.locator('#reuseTask').isEnabled(),true,'Stopped retained teams can supply text without resuming');
    assert.equal(await page.locator('#activeRunTask').textContent(),sourceText);
    await reuse();await assertNoCandidate(sourceText,'Empty draft adopts immediately');
    await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    assert.deepEqual(preflights().at(-1).body,{task:sourceText,pm_profile:'local',worker_profiles:['openai'],max_workers:1},
      'The only adoption POST is the normal read-only preflight with current choices');
    assert.equal(await page.locator('#taskReuseStatus').getAttribute('aria-live'),'polite');
    assert((await page.locator('#taskReuseProvenance').textContent()).includes(source.id.slice(-8)),'Copied text identifies its source team');
    assert.match(await page.locator('#taskReuseProvenance').textContent(),/最後に取得した表示用の内容/,'Provenance identifies the last displayed snapshot');
    assert.match(await page.locator('#taskReuseHelp').textContent(),/この画面の選択と開始時の保存済み設定で新しいチーム/,'Help distinguishes preparation from starting a new team');
    assert.match(await page.locator('#taskReuseHelp').textContent(),/過去の会話・成果・設定は引き継ぎません/,'Help explains the text-only boundary');
    assert.equal(await page.locator('#taskDialog img, #taskDialog script, #activeRunTask img, #activeRunTask script').count(),0);
    assert.equal(await page.evaluate(()=>Boolean(window.taskReuseInjected)),false,'Source markup stays inert literal text');
    assert.equal(source.status,'stopped');

    // Identical text opens without an overwrite decision or synthetic input event.
    await close();await page.evaluate(()=>{
      window.taskReuseEvents=0;window.taskReuseEventObserver=()=>{window.taskReuseEvents++;};
      document.querySelector('#taskInput').addEventListener('input',window.taskReuseEventObserver);
      document.querySelector('#taskInput').addEventListener('change',window.taskReuseEventObserver);
    });
    await reuse('Space');await assertNoCandidate(sourceText,'Identical draft is a no-op');
    assert.equal(await page.evaluate(()=>window.taskReuseEvents),0,'Identical reuse does not manufacture a draft-edit event');
    await page.locator('#taskInput').focus();await page.keyboard.press('Control+End');
    const identicalSelection=await page.locator('#taskInput').evaluate(input=>[input.selectionStart,input.selectionEnd]);
    await poll();assert.equal(await focused('#taskInput'),true);
    assert.deepEqual(await page.locator('#taskInput').evaluate(input=>[input.selectionStart,input.selectionEnd]),identicalSelection,
      'Unchanged polling preserves the adopted draft’s cursor');

    const existing='  [SYNTHETIC] 自分で書いた未送信の下書き。\n保持してください。  ';
    await candidate(existing);
    // Native Enter from another input exercises implicit form submission while
    // the normal submit button is disabled. Pointer clicks also cannot submit.
    const postsBefore=requests.length;await page.locator('#maxWorkers').focus();await page.keyboard.press('Enter');
    await page.locator('#startRun').scrollIntoViewIfNeeded();const startBox=await page.locator('#startRun').boundingBox();assert(startBox);
    await page.mouse.click(startBox.x+startBox.width/2,startBox.y+startBox.height/2);await paint();
    assert.equal(requests.length,postsBefore,'Neither implicit submit nor a disabled Start pointer gesture issues a request');
    await page.locator('#keepTaskDraft').focus();await page.keyboard.press('Space');
    await assertNoCandidate(existing,'Keep is explicitly lossless');await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    assert.equal(preflights().at(-1).body.task,existing,'Keep previews only the existing draft');

    await candidate(existing);await page.locator('#replaceTaskDraft').focus();await page.keyboard.press('Enter');
    await assertNoCandidate(sourceText,'Replace copies only the task text');await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    assert.deepEqual(preflights().at(-1).body,{task:sourceText,pm_profile:'local',worker_profiles:['openai'],max_workers:1});
    assert.equal(await page.locator('#taskDialog').isVisible(),true,'Replacement never starts or closes the new task');
    assert.deepEqual(await owner(),{run:source.id,agent:sourceAgent.id},'Copying never changes the selected retained team');
    await candidate(' \n\t ');await page.locator('#keepTaskDraft').click();await assertNoCandidate(' \n\t ','Whitespace-only is a real draft');

    // Once edited, an old candidate never revives when the same text returns.
    await candidate(existing);await page.locator('#taskInput').focus();await page.keyboard.press('Control+End');await page.keyboard.insertText('改');
    await assertNoCandidate(existing+'改','Native editing cancels the candidate');await page.keyboard.press('Backspace');
    await poll();await assertNoCandidate(existing,'Draft A → B → A still invalidates the candidate');
    await candidate(existing);await page.locator('#pmProfile').selectOption('openai');await page.locator('#pmProfile').selectOption('local');
    await poll();await assertNoCandidate(existing,'Choice A → B → A cannot revive an old candidate');

    // The action uses what was displayed when invoked, even if an unseen newer
    // HTTP response is in flight. A later poll cannot replace the adopted draft.
    await setDraft('');heldState=await holdNextRequest(page,'**/api/state*',async()=>{});
    source.task='[SYNTHETIC] NEWER BUT NOT YET DISPLAYED TASK';
    assert.equal(await page.locator('#activeRunTask').textContent(),sourceText);
    await reuse();await assertNoCandidate(sourceText,'Undelivered newer state cannot become the source');
    await releaseResponse(page,heldState,compactFixture(heldState.request()));heldState=null;
    await page.locator('#activeRunTask').filter({hasText:source.task}).waitFor();await assertNoCandidate(sourceText,'Later state cannot revise adopted text');
    await poll(()=>{source.task=sourceText;});await close();

    await candidate(existing);await poll(()=>{source.task=sourceText+'[SYNTHETIC] CHANGED SOURCE';});
    await assertNoCandidate(existing,'Changed displayed source cancels the decision');
    await poll(()=>{source.task=sourceText;});await assertNoCandidate(existing,'Source A → B → A does not revive a decision');
    await candidate(existing);await close();await page.locator('#newRun').click();
    await assertNoCandidate(existing,'Escape and reopen cancels the decision');
    await candidate(existing);await page.locator('#preflightSettings').click();await page.locator('#settingsDialog').waitFor({state:'visible'});
    await page.keyboard.press('Escape');await page.locator('#newRun').click();await assertNoCandidate(existing,'Settings/workspace round trip cancels the decision');
    await candidate(existing);await close();await select(other.id);await select(source.id);await page.locator('#newRun').click();
    await assertNoCandidate(existing,'Native team A → B → A and reopen cannot revive a decision');
    await candidate(existing);const beforeMalformedRemoval=preflights().length;
    await poll(()=>{
      fixture.runs=fixture.runs.filter(run=>run.id!==source.id);fixture.agents=fixture.agents.filter(agent=>agent.run_id!==source.id);
    });
    // compactFixture still claims detail_loaded for the removed requested agent.
    // That malformed response is rejected before replacing the displayed state;
    // it must not manufacture source removal or cancel the displayed candidate.
    assert.deepEqual(await owner(),{run:source.id,agent:sourceAgent.id},'Malformed compact removal retains the displayed owner');
    assert.equal(await page.locator('#activeRunTask').textContent(),sourceText,'Malformed compact removal retains the last displayed source');
    assert.equal(await page.locator('#taskInput').inputValue(),existing,'Malformed compact removal preserves the current draft');
    assert.equal(await page.locator('#taskReuseConfirm').isVisible(),true,'Rejected state does not invalidate the last displayed candidate');
    assert.equal(await page.locator('#taskReusePreview').textContent(),sourceText);
    assert.equal(await page.locator('#startRun').isDisabled(),true);
    assert.equal(preflights().length,beforeMalformedRemoval,'Rejected state keeps candidate preflight suppressed');
    // Exercise accepted synthetic source removal through the explicitly supported
    // legacy full-state snapshot, without compact selection metadata. This is a
    // controller invalidation test, not a claim that Engine deletes retained runs.
    heldState=await holdNextRequest(page,'**/api/state*',async()=>{});
    const removedFullState=structuredClone(fixture);assert.equal(Object.hasOwn(removedFullState,'selection'),false);
    await releaseResponse(page,heldState,removedFullState);heldState=null;
    await assertNoCandidate(existing,'A valid legacy full-state removal cancels the decision');
    await poll(()=>{fixture.runs.push(source);fixture.agents.push(sourceAgent);});await close();await select(source.id);await page.locator('#newRun').click();
    await assertNoCandidate(existing,'Returning the same source ID does not revive the removed candidate');

    // Native textarea normalization changes only CRLF/CR to LF. Raw public
    // source freshness remains distinct even when the normalized text is equal.
    for(const ending of ['\n','\r\n','\r']){
      const raw='  [SYNTHETIC] 改行だけを正規化。'+ending+'[redacted] \t  ',normalized=editorText(raw);
      await close();await poll(()=>{source.task=raw;});await setDraft('');await reuse();
      await assertNoCandidate(normalized,'LF/CRLF/CR adoption preserves other characters');
      await page.locator('#preflightStatus[aria-busy="false"]').waitFor();assert.equal(preflights().at(-1).body.task,normalized);
      await close();await reuse();await assertNoCandidate(normalized,'Normalized identical draft needs no overwrite decision');
    }
    await close();await poll(()=>{source.task='[SYNTHETIC] One\r\nTwo';});await candidate(existing);
    await poll(()=>{source.task='[SYNTHETIC] One\nTwo';});await assertNoCandidate(existing,'Raw newline change invalidates an equal normalized candidate');
    await poll(()=>{source.task='[SYNTHETIC] One\r\nTwo';});await assertNoCandidate(existing,'Raw source newline ABA never revives a candidate');

    // Missing/invalid text and >16000 normalized UTF-16 code units fail closed
    // instead of truncating, including a surrogate-pair boundary.
    for(const [label,value] of [['missing',undefined],['null',null],['non-string',27],['empty',''],['whitespace',' \n\t '],
      ['NUL','a\0b'],['oversize','😀'.repeat(8001)]]){
      await setDraft(existing);await poll(()=>{if(value===undefined)delete source.task;else source.task=value;});
      const count=preflights().length;
      if(await page.locator('#reuseTask').isVisible()&&await page.locator('#reuseTask').isEnabled()){
        await page.locator('#reuseTask').focus();await page.keyboard.press('Enter');await paint();
      }
      await poll();assert.equal(await page.locator('#taskInput').inputValue(),existing,label+': unsupported source never changes the draft');
      assert.equal(await page.locator('#taskReuseConfirm').isVisible(),false,label+': invalid source offers no overwrite decision');
      assert.equal(preflights().length,count,label+': rejected reuse does not schedule preflight');
      await close();
    }
    for(const raw of ['😀'.repeat(8000),'😀'.repeat(7999)+'\r\nx']){
      await poll(()=>{source.task=raw;});await setDraft('');await reuse();
      await assertNoCandidate(editorText(raw),'Exactly 16000 normalized UTF-16 code units are preserved');
      assert.equal((await page.locator('#taskInput').inputValue()).length,16000);
      await page.locator('#preflightStatus[aria-busy="false"]').waitFor();assert.equal(preflights().at(-1).body.task,editorText(raw));
      await close();
    }
    await poll(()=>{source.task=sourceText;});

    // Focus, reading position, live announcements and control geometry across
    // all supported viewport classes, using real keyboard scrolling and polls.
    for(const [name,width,height] of [['desktop',1366,768],['tablet',820,768],['narrow',390,844]]){
      await page.setViewportSize({width,height});await candidate(existing);
      assert.equal(await page.locator('#taskReusePreview').getAttribute('tabindex'),'0','Long source preview is keyboard-scrollable');
      assert.equal(await page.locator('#taskReusePreview').evaluate(node=>node.scrollTop),0,
        name+': every explicit new candidate begins at the top of its preview');
      await page.locator('#taskReusePreview').focus();await page.keyboard.press('End');
      await page.waitForFunction(()=>{const node=document.querySelector('#taskReusePreview');return node.scrollTop>0&&node.scrollHeight-node.clientHeight-node.scrollTop<=1;});
      await paint();await assertVisible('#taskReusePreview',name+' first End preview');
      assert.equal(await page.locator('#taskReusePreview').evaluate(node=>getComputedStyle(node).outlineStyle),'solid',name+': focused preview has a visible outline');
      const reading=await page.locator('#taskReusePreview').evaluate(node=>node.scrollTop),
        dialogReading=await page.locator('#taskDialog').evaluate(node=>node.scrollTop);
      // A fresh-candidate reset alone must not hide keyboard scroll chaining:
      // End again at the boundary must remain inside this focused reading region.
      await page.keyboard.press('End');await paint();
      assert.equal(await focused('#taskReusePreview'),true,name+': repeated End keeps preview focus');
      assert.equal(await page.locator('#taskReusePreview').evaluate(node=>node.scrollTop),reading,name+': repeated End stays at the preview bottom');
      assert.equal(await page.locator('#taskDialog').evaluate(node=>node.scrollTop),dialogReading,name+': repeated End does not scroll the outer dialog');
      await assertVisible('#taskReusePreview',name+' repeated End preview');
      await page.keyboard.press('Home');
      await page.waitForFunction(()=>document.querySelector('#taskReusePreview').scrollTop===0);await paint();
      assert.equal(await focused('#taskReusePreview'),true,name+': Home keeps preview focus');
      assert.equal(await page.locator('#taskDialog').evaluate(node=>node.scrollTop),dialogReading,name+': Home scrolls only the preview');
      await assertVisible('#taskReusePreview',name+' Home preview');
      await page.keyboard.press('End');
      await page.waitForFunction(()=>{const node=document.querySelector('#taskReusePreview');return node.scrollTop>0&&node.scrollHeight-node.clientHeight-node.scrollTop<=1;});
      await paint();assert.equal(await page.locator('#taskReusePreview').evaluate(node=>node.scrollTop),reading,name+': Home then End reaches the same complete source');
      assert.equal(await page.locator('#taskDialog').evaluate(node=>node.scrollTop),dialogReading,name+': Home then End keeps the dialog reading position');
      await assertVisible('#taskReusePreview',name+' Home then End preview');
      await page.evaluate(()=>{
        window.taskReuseChanges=0;window.taskReuseMutationObserver?.disconnect();
        window.taskReuseMutationObserver=new MutationObserver(records=>{window.taskReuseChanges+=records.length;});
        for(const id of ['taskReuseStatus','taskReuseConfirm'])window.taskReuseMutationObserver.observe(document.getElementById(id),{subtree:true,childList:true,characterData:true});
      });
      await poll();assert.equal(await focused('#taskReusePreview'),true,name+': unchanged polls retain preview focus');
      assert.equal(await page.locator('#taskReusePreview').evaluate(node=>node.scrollTop),reading,name+': unchanged polls preserve source reading position');
      assert.equal(await page.locator('#taskDialog').evaluate(node=>node.scrollTop),dialogReading,name+': unchanged polls preserve the dialog reading position');
      assert.equal(await page.evaluate(()=>window.taskReuseChanges),0,name+': unchanged polls do not rewrite confirmation or polite status');
      await assertDialogLayout(page,'#taskDialog','task reuse '+name);await assertVisible('#taskReusePreview',name+' preview');
      await page.screenshot({path:path.join(artifacts,'workbench-task-reuse-'+name+'.png'),fullPage:true,animations:'disabled'});
      for(const id of ['keepTaskDraft','replaceTaskDraft']){
        await page.locator('#'+id).focus();await assertVisible('#'+id,name+' '+id);
        const style=await page.locator('#'+id).evaluate(node=>({outline:getComputedStyle(node).outlineStyle,shadow:getComputedStyle(node).boxShadow}));
        assert(style.outline!=='none'||style.shadow!=='none',name+': focused decision has a visible focus indicator');
      }
      await page.screenshot({path:path.join(artifacts,'workbench-task-reuse-'+name+'-controls.png'),fullPage:true,animations:'disabled'});
      await page.locator('#keepTaskDraft').focus();await page.keyboard.press('Enter');await close();
      await assertLayout(page,'task reuse underlying '+name);await page.locator('#reuseTask').focus();await assertVisible('#reuseTask',name+' reuse entry');
      await page.screenshot({path:path.join(artifacts,'workbench-task-reuse-'+name+'-entry.png'),fullPage:true,animations:'disabled'});
    }

    // Explicit Start after a real replacement sends only the reviewed normalized
    // text and current choices. Hold/reject it before the surrounding simulated
    // start handler, then prove reuse cannot steal the active operation.
    const admissionSource='  [SYNTHETIC] 置き換え後に確認した依頼。\r\n[redacted] はそのまま。\t  ';
    await page.setViewportSize(viewport);await poll(()=>{source.task=admissionSource;});await candidate(existing);
    await page.locator('#replaceTaskDraft').focus();await page.keyboard.press('Enter');
    await assertNoCandidate(editorText(admissionSource),'Explicit replacement prepares the reviewed admission text');
    await page.locator('#preflightStatus[aria-busy="false"]').waitFor();
    const reviewedTask=await page.locator('#taskInput').inputValue(),reviewedChoices=await choices();
    assert.equal(reviewedTask,editorText(admissionSource));assert.deepEqual(reviewedChoices,currentChoices);
    const expectedAdmission={task:reviewedTask,pm_profile:reviewedChoices.pm,
      worker_profiles:reviewedChoices.workers,max_workers:Number(reviewedChoices.count)};
    heldStart=await holdNextRequest(page,'**/api/runs',()=>page.locator('#startRun').click());
    assert.deepEqual(heldStart.request().postDataJSON(),expectedAdmission,
      'Explicit Start posts the entire visible normalized task and current PM/worker/count selection, with no historical authority');
    assert.equal(source.status,'stopped','Starting the new draft never resumes its retained source');
    await close();assert.equal(await page.locator('#reuseTask').isDisabled(),true,'In-flight start blocks reuse entry');
    await page.locator('#reuseTask').scrollIntoViewIfNeeded();const reuseBox=await page.locator('#reuseTask').boundingBox();assert(reuseBox);
    await page.mouse.click(reuseBox.x+reuseBox.width/2,reuseBox.y+reuseBox.height/2);await poll();
    assert.equal(await page.locator('#taskDialog').isVisible(),false,'Blocked reuse cannot open the task dialog');
    assert.equal(await page.locator('#taskInput').inputValue(),reviewedTask);
    await releaseResponse(page,heldStart,{ok:false,error:'[SYNTHETIC] Rejected held reuse-guard admission'});heldStart=null;
    await page.waitForFunction(()=>!document.querySelector('#reuseTask').disabled);
    assert.equal(requests.filter(item=>item.path==='/api/runs').length,1,'Only the explicit held/rejected Start sends a start request');
    assert.deepEqual(unexpected,[],'Reuse never attempts start/message/stop/config/key/provider mutations');
    assert(requests.every(item=>item.method==='POST'&&['/api/run-preflight','/api/runs'].includes(item.path)));
    assert.deepEqual(providerRequests,providerBefore,'Adoption and checks generate no provider traffic');
    assert.equal(await page.evaluate(()=>Boolean(window.taskReuseInjected)),false);

    // Restore the enclosing smoke’s form, selected owner and native reading UI.
    await page.locator('#newRun').click();await page.locator('#taskInput').fill(before.task);await page.locator('#pmProfile').selectOption(before.pm);
    for(const checkbox of await page.locator('#workerProfiles input').all())await checkbox.setChecked(before.workers.includes(await checkbox.inputValue()));
    await page.locator('#maxWorkers').fill(before.count);await page.locator('#preflightStatus[aria-busy="false"]').waitFor();await close();
    await select(before.run);
    if((await owner()).agent!==before.agent)await page.locator(`#agentTabs [data-focus-key="tab:${before.agent}"]`).click();
    await page.locator('#conversationLog[aria-busy="false"]').waitFor();await poll(()=>Object.assign(fixture,structuredClone(original)));
    if(before.questions)await page.locator('#needsYou').click();await page.locator('#agentSearch').fill(before.search);
    await page.setViewportSize(viewport);
    for(const detail of await page.locator('#conversationLog details').all()){
      if(await detail.evaluate(node=>node.open)!==before.expanded.includes(await detail.getAttribute('data-log-id'))){
        await detail.locator(':scope > summary').focus();await page.keyboard.press('Enter');
      }
    }
    if(await page.locator('#resultsPanel').evaluate(node=>node.open)!==before.resultsOpen){await page.locator('#resultsPanel > summary').focus();await page.keyboard.press('Enter');}
    await page.evaluate(saved=>{
      const input=document.querySelector('#messageInput'),log=document.querySelector('#conversationLog');input.setSelectionRange(saved.start,saved.end,saved.direction);
      const target=saved.focusLog?[...log.querySelectorAll('details > summary')].find(node=>node.parentElement.dataset.logId===saved.focusLog):
        saved.focusId?document.getElementById(saved.focusId):[...document.querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===saved.focusKey);
      // Restore only pre-test presentation after the intentionally rejected
      // admission; the behavioral checks above never call controller internals.
      const notice=document.querySelector('#globalNotice');notice.textContent=saved.notice.text;notice.hidden=saved.notice.hidden;notice.className=saved.notice.className;
      target?.focus({preventScroll:true});log.scrollTop=saved.scroll;window.scrollTo(saved.x,saved.y);
    },before);
    assert.deepEqual(fixture,original);assert.deepEqual(await owner(),{run:before.run,agent:before.agent});
    assert.equal(await page.locator('#messageInput').inputValue(),before.draft);assert.equal(await page.locator('#taskInput').inputValue(),before.task);
    assert.deepEqual(await choices(),{pm:before.pm,workers:before.workers,count:before.count});assert.deepEqual(page.viewportSize(),viewport);
    restored=true;
    report.checks.push('task reuse: native Enter/Space reuses only last-displayed run.task, preserving whitespace, [redacted], literal markup and current PM/worker/count choices; stopped source is never resumed; empty/identical/Keep/Replace and whitespace-only overwrite guards, implicit/pointer Start blocking and preflight suppression while deciding; draft/form/source ABA, late displayed-state delivery, Escape/reopen, settings/team round trips, malformed compact-state retention and valid legacy-full source removal; LF/CRLF/CR normalization with raw-source ABA checks; missing/invalid/oversize sources rejected without truncation, exactly 16000 normalized UTF-16 code units retained; fresh preview starts at top, repeated End and Home/End stay within the visible focused preview, poll-stable preview/dialog scroll and unchanged polite status; desktop/tablet/narrow preview, decision-control and reuse-entry geometry and screenshots; no mutation except normal preflight and one explicit held/rejected synthetic Start after normalized replacement, with exact visible-task/current-choice POST and pending-entry protection; no provider traffic; original fixture, choices and selected-owner context restored');
  } catch(error) {
    await page.screenshot({path:path.join(artifacts,'workbench-task-reuse-failure.png'),fullPage:true,animations:'disabled'}).catch(()=>{});throw error;
  } finally {
    Object.assign(fixture,structuredClone(original));page.off('request',observer);await page.unroute('**/api/**',mutationGuard);
    if(heldState)await heldState.abort().catch(()=>{});if(heldStart)await heldStart.abort().catch(()=>{});
    await page.evaluate(()=>{
      window.taskReuseMutationObserver?.disconnect();const input=document.querySelector('#taskInput');
      if(window.taskReuseEventObserver){input.removeEventListener('input',window.taskReuseEventObserver);input.removeEventListener('change',window.taskReuseEventObserver);}
      for(const key of ['taskReuseMutationObserver','taskReuseChanges','taskReuseEventObserver','taskReuseEvents'])delete window[key];
    }).catch(()=>{});
    if(!restored)await page.setViewportSize(viewport).catch(()=>{});
  }
}

module.exports={taskReuseAcceptance};
