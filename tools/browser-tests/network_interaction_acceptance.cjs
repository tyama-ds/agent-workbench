/* Synthetic recorded team, production pointer/keyboard controls, no inference. */
'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');

async function networkInteractionAcceptance({page,fixture,artifacts,report}) {
  const previousViewport=page.viewportSize(),previousEvents=fixture.events,previousDraft=await page.locator('#messageInput').inputValue();
  const node=page.locator('#teamMap [data-agent-id="fixture-worker-1"]');
  const geometry=()=>page.evaluate(()=>({
    left:parseFloat(document.querySelector('#teamMap [data-agent-id="fixture-worker-1"]').style.left),
    top:parseFloat(document.querySelector('#teamMap [data-agent-id="fixture-worker-1"]').style.top),
    camera:document.querySelector('.network-canvas').style.transform,
    parent:[...document.querySelectorAll('.network-parent-line')].map(line=>line.getAttribute('d')),
    selected:document.querySelector('#teamMap .network-node.selected')?.dataset.agentId,
  }));
  const nextPaint=async()=>{const response=await page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state');await response.finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));};
  const motionSnapshot=()=>page.evaluate(()=>{
    const view=ui.networkViews.get(ui.selectedRun),run=ui.state.runs.find(run=>run.id===ui.selectedRun),diagnostic=window.__awbNetworkAcceptanceDiagnostic;
    return {at:performance.now(),selectedRun:ui.selectedRun,selectedAgent:ui.selectedAgent,runStatus:run?.status,
      archived:run?.archived===true,compact:ui.compactState,loadedEventsRun:ui.loadedEventsRun,connected:ui.networkConnected,
      previewReady:ui.networkPreviewReady,motionEnabled:ui.networkMotionEnabled,reduced:ui.networkReducedMotion,
      mediaReduced:matchMedia('(prefers-reduced-motion: reduce)').matches,hidden:document.hidden,cockpitView:ui.cockpitView,
      settingsOpen:document.querySelector('#settingsDialog').open,taskOpen:document.querySelector('#taskDialog').open,
      allowed:networkMotionAllowed(),mailReady:view?.mailReady,mailCursor:view?.mailCursor,mailSeenCount:view?.mailSeen.size,
      eventIds:ui.state.events.map(event=>event.id),pulses:[...ui.networkPulses.values()].map(pulse=>({eventId:pulse.node.dataset.eventId,stage:pulse.stage})),
      observed:diagnostic?.records||[],observations:diagnostic?.total||0};
  });
  report.networkMotionDiagnostics={fixture:'SYNTHETIC IDs and gate metadata only'};
  try {
    await page.setViewportSize({width:1366,height:900});await page.locator('#networkView').click();await page.locator('#networkFit').click();
    const circle=await node.evaluate(node=>{const style=getComputedStyle(node);return {width:style.width,height:style.height,radius:style.borderRadius};});
    assert.deepEqual(circle,{width:'112px',height:'112px',radius:'50%'});
    await page.locator('#messageInput').fill('[SYNTHETIC] Unsent PM draft retained during preview');
    const original=await geometry(),box=await node.boundingBox();assert(box&&box.width>0);
    await node.hover();await page.locator('#networkPreview').waitFor({state:'visible'});
    assert.match(await page.locator('#networkPreviewAssignment').textContent(),/Unique assignment search phrase/);
    assert.equal((await geometry()).selected,original.selected,'Hover is view-only, not a recipient change');
    await page.locator('#networkPreviewOpen').hover();await nextPaint();await page.locator('#networkPreview').waitFor({state:'visible'});
    assert.equal((await geometry()).selected,original.selected,'Moving to the hover card does not select or pin');
    assert.equal(await node.getAttribute('aria-pressed'),'false');
    await page.locator('#networkFit').hover();await node.focus();await page.locator('#networkPreview').waitFor({state:'visible'});
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
    await page.mouse.move(box.x+box.width/2+35,box.y+box.height/2+18,{steps:8});await page.mouse.up();
    const dragged=await geometry();assert(dragged.left>original.left&&dragged.top>original.top);
    assert.equal(dragged.selected,original.selected,'Dragging does not activate the card');assert.notDeepEqual(dragged.parent,original.parent);
    const response=await page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state');await response.finished();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.deepEqual(await geometry(),dragged,'Polling retains geometry, camera, selection and matching parent edges');
    // CSSOM rounds its serialized px value. Assert the exact movement on the
    // view coordinate, then independently check its browser-normalized display.
    const keyBefore=await page.evaluate(()=>({...networkViewState().positions.get('fixture-worker-1')}));
    await node.focus();await page.keyboard.press('Alt+ArrowRight');
    const keyAfter=await page.evaluate(()=>{const point=networkViewState().positions.get('fixture-worker-1'),probe=document.createElement('div');probe.style.left=`${point.x}px`;return {...point,expectedCss:probe.style.left,actualCss:document.querySelector('#teamMap [data-agent-id="fixture-worker-1"]').style.left};});
    assert.equal(keyAfter.x,keyBefore.x+10);assert.equal(keyAfter.y,keyBefore.y);assert.equal(keyAfter.actualCss,keyAfter.expectedCss);
    const beforeZoom=await geometry();await page.locator('#networkZoomIn').click();assert.notEqual((await geometry()).camera,beforeZoom.camera);
    const beforePan=await geometry();await page.locator('#teamMap').focus();await page.keyboard.press('ArrowRight');assert.notEqual((await geometry()).camera,beforePan.camera);
    const map=await page.locator('#teamMap').boundingBox();assert(map);
    const beforePointerPan=await geometry();await page.mouse.move(map.x+8,map.y+8);await page.mouse.down();await page.mouse.move(map.x+35,map.y+27,{steps:6});await page.mouse.up();
    assert.notEqual((await geometry()).camera,beforePointerPan.camera);assert.equal((await geometry()).left,beforePointerPan.left);
    await page.locator('#networkFit').click();await node.click();assert.equal(await node.getAttribute('aria-pressed'),'true');
    assert.equal((await geometry()).selected,original.selected,'Pin does not select the inspector or change the human recipient');
    await page.locator('#networkFit').hover();await nextPaint();assert.equal(await node.getAttribute('aria-pressed'),'true');
    assert.match(await page.locator('#networkPreviewMode').textContent(),/固定中/);
    assert.equal(await page.locator('#messageInput').inputValue(),'[SYNTHETIC] Unsent PM draft retained during preview');
    await page.locator('#networkPreviewClose').click();await page.locator('#networkPreview').waitFor({state:'hidden'});
    assert.equal(await node.evaluate(node=>node===document.activeElement),true);
    await page.keyboard.press('Enter');await page.locator('#networkPreview').waitFor({state:'visible'});
    assert.equal(await node.getAttribute('aria-pressed'),'true');await page.keyboard.press('Escape');await page.locator('#networkPreview').waitFor({state:'hidden'});
    await node.click();await page.locator('#networkPreviewOpen').click();assert.equal((await geometry()).selected,'fixture-worker-1');
    await page.locator('#networkView').click();
    // The harness defaults to reduced motion. The initial recorded history is
    // never animated; only the newly observed synthetic event below may move.
    assert.equal(await page.locator('.network-mail-pulse').count(),0);
    await page.emulateMedia({reducedMotion:'no-preference'});
    // A response/render alone may precede the media change handler. Observe the
    // accepted production baseline without setting any UI flags or event cursor.
    await page.waitForFunction(()=>!matchMedia('(prefers-reduced-motion: reduce)').matches
      &&ui.networkReducedMotion===false&&networkMotionAllowed()&&ui.selectedRun==='fixture-run'
      &&ui.selectedAgent==='fixture-worker-1'&&ui.loadedEventsRun===ui.selectedRun
      &&ui.networkViews.get(ui.selectedRun)?.mailReady===true);
    report.networkMotionDiagnostics.beforeAppend=await motionSnapshot();
    await page.evaluate(()=>{
      const records=[],diagnostic={records,total:0,observer:null},record=(action,node)=>{
        diagnostic.total++;if(records.length<32)records.push({action,at:performance.now(),eventId:node.dataset.eventId,stage:node.dataset.stage});
      };
      diagnostic.observer=new MutationObserver(changes=>{
        for(const change of changes)for(const [action,nodes] of [['added',change.addedNodes],['removed',change.removedNodes]])
          for(const node of nodes)if(node.nodeType===Node.ELEMENT_NODE&&node.matches('.network-mail-pulse')){
            record(action,node);
            if(action==='added')for(const animation of node.querySelectorAll('animateMotion,animate'))
              for(const event of ['beginEvent','endEvent'])animation.addEventListener(event,()=>record(event,node),{once:true});
          }
      });
      diagnostic.observer.observe(document.querySelector('.network-mail-pulses'),{childList:true});
      window.__awbNetworkAcceptanceDiagnostic=diagnostic;
    });
    fixture.events=[...previousEvents,{id:99001,run_id:'fixture-run',kind:'mail',mail_id:'synthetic-network-mail',
      from_agent_id:'fixture-worker-1',to_agent_id:'fixture-pm',from:'[SYNTHETIC] 資料・検索担当',to:'[SYNTHETIC] PM',
      subject:'[SYNTHETIC] Interactive edge',text:'[SYNTHETIC] Recorded mail only',delivery_state:'queued',message_type:'peer_message',at:Date.now()/1000}];
    const packet=page.locator('.network-mail-pulse.queued[data-event-id="99001"]');await packet.waitFor({state:'visible'});
    const movement=await packet.evaluate(async node=>{
      const animation=node.querySelector('animateMotion'),first=node.getBoundingClientRect();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      const second=node.getBoundingClientRect();return {duration:animation.getAttribute('dur'),repeat:animation.getAttribute('repeatCount'),distance:Math.hypot(second.x-first.x,second.y-first.y)};
    });
    assert.equal(movement.duration,'1200ms');assert.equal(movement.repeat,'1');assert(movement.distance>0,'An actual observed queued record moves once along its SVG path');
    await packet.waitFor({state:'detached'});await nextPaint();assert.equal(await page.locator('.network-mail-pulse').count(),0,'Repeated polling cannot replay old records');
    fixture.events=[...fixture.events,{...fixture.events.at(-1),id:99002,kind:'mail_consumed',delivery_state:'context_consumed',at:Date.now()/1000}];
    const consumed=page.locator('.network-mail-pulse.consumed[data-event-id="99002"]');await consumed.waitFor({state:'visible'});
    assert.equal(await consumed.locator('animate').getAttribute('repeatCount'),'1');
    await page.emulateMedia({reducedMotion:'reduce'});await consumed.waitFor({state:'detached'});
    fixture.events=[...fixture.events,{...fixture.events.at(-1),id:99003,kind:'mail',delivery_state:'queued',mail_id:'synthetic-reduced-mail',at:Date.now()/1000}];
    await nextPaint();assert.equal(await page.locator('.network-mail-pulse').count(),0,'Reduced-motion preference suppresses new activity animation');
    const line=page.locator('.network-mail-line');await line.waitFor();await page.locator('#networkFit').click();
    const hitSnapshot=()=>line.evaluate(line=>{
      const matrix=line.getScreenCTM(),preview=document.querySelector('#networkPreview');
      return {line:line.getBoundingClientRect().toJSON(),map:document.querySelector('#teamMap').getBoundingClientRect().toJSON(),
        preview:{hidden:preview.hidden,box:preview.getBoundingClientRect().toJSON()},
        samples:[.5,.35,.65,.2,.8].map(part=>{
          const point=line.getPointAtLength(line.getTotalLength()*part).matrixTransform(matrix),element=document.elementFromPoint(point.x,point.y);
          return {part,x:point.x,y:point.y,hit:element===line,element:element?{tag:element.tagName,id:element.id,class:element.getAttribute('class')}:null};
        })};
    });
    report.networkHitDiagnostics={beforeClose:await hitSnapshot(),previewClosed:false};
    if(await page.locator('#networkPreview').isVisible()){
      await page.locator('#networkPreviewClose').click();await page.locator('#networkPreview').waitFor({state:'hidden'});
      report.networkHitDiagnostics.previewClosed=true;
    }
    report.networkHitDiagnostics.afterClose=await hitSnapshot();
    const hit=report.networkHitDiagnostics.afterClose.samples.find(sample=>sample.hit)||null;
    assert(hit,'Mail edge exposes a real visible pointer target');await page.mouse.click(hit.x,hit.y);
    await page.locator('#activityFeed').filter({hasText:'[SYNTHETIC] Recorded mail only'}).waitFor();
    await page.locator('#activityFeed .activity-item').nth(2).waitFor();
    assert.equal(await page.locator('#activityFeed .activity-item').count(),3,'Mail edge filters only the recorded pair and keeps separate queue/consumption records');
    await line.focus();await page.keyboard.press('Enter');await page.locator('#activityTitle:focus').waitFor();
    assert.match(await page.locator('#activityFeed').textContent(),/会話へ取り込み済み/);
    assert.match(await page.locator('#activityFeed').textContent(),/理解・完了の確認ではありません/);
    await node.click();if(await node.getAttribute('aria-pressed')!=='true')await node.click();
    await page.screenshot({path:path.join(artifacts,'interactive-network-desktop.png'),fullPage:true});
    await page.setViewportSize({width:1920,height:1080});await page.locator('#networkFit').click();
    await page.screenshot({path:path.join(artifacts,'interactive-network-wide.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.locator('#networkView').click();await page.locator('#networkFit').click();
    const mobile=await page.evaluate(()=>{
      const map=document.querySelector('#teamMap').getBoundingClientRect();
      return {overflow:document.documentElement.scrollWidth>innerWidth,
        controls:[...document.querySelectorAll('.network-tools button')].map(button=>({box:button.getBoundingClientRect().toJSON(),visible:button.checkVisibility()})),
        map:map.toJSON(),nodes:[...document.querySelectorAll('.network-node')].map(node=>node.getBoundingClientRect().toJSON())};
    });
    assert(!mobile.overflow);assert(mobile.map.height>=140);
    for(const item of mobile.controls)assert(item.visible&&item.box.width>=20&&item.box.height>=32&&item.box.left>=0&&item.box.right<=391);
    for(const box of mobile.nodes)assert(box.left>=mobile.map.left-1&&box.right<=mobile.map.right+1&&box.top>=mobile.map.top-1&&box.bottom<=mobile.map.bottom+1,'Fit contains each actual card on narrow viewport');
    await page.locator('#networkZoomIn').click();await page.locator('#networkZoomOut').click();
    if(await node.getAttribute('aria-pressed')!=='true')await node.click();
    await page.locator('#networkPreview').waitFor({state:'visible'});
    const preview=await page.locator('#networkPreview').boundingBox(),open=await page.locator('#networkPreviewOpen').boundingBox(),close=await page.locator('#networkPreviewClose').boundingBox();
    assert(preview&&open&&close&&preview.x>=0&&preview.x+preview.width<=391&&preview.height>80);
    for(const button of [open,close])assert(button.width>=32&&button.height>=32&&button.x>=0&&button.x+button.width<=391,'Narrow preview has usable explicit controls');
    await page.screenshot({path:path.join(artifacts,'interactive-network-mobile.png'),fullPage:true});
    await page.locator('#networkPreviewOpen').click();assert.equal(await page.locator('#inspectorView').getAttribute('aria-pressed'),'true');
    report.checks.push('interactive network: circular nodes, hover/focus view-only preview, pin/poll/draft retention and explicit inspector opening, Escape/close keyboard behavior, real drag without pin, live edges, pan/zoom/fit, one-shot actual queued/consumed record motion without history replay, reduced-motion suppression, keyboard mail selection and 390/1366/1920 layouts');
  } catch(error) {
    // Preserve the failing interactive state before finally restores the fixture.
    const screenshot=path.join(artifacts,'interactive-network-failure-before-cleanup.png');
    try { await page.screenshot({path:screenshot,fullPage:true});report.networkFailureScreenshot=screenshot; }
    catch(captureError) { report.networkFailureScreenshotError=String(captureError); }
    throw error;
  } finally {
    // Capture failure state before fixture restoration; no task text or mail body.
    try { report.networkMotionDiagnostics.final=await motionSnapshot(); }
    catch(error) { report.networkMotionDiagnostics.captureError=String(error); }
    await page.evaluate(()=>{window.__awbNetworkAcceptanceDiagnostic?.observer.disconnect();delete window.__awbNetworkAcceptanceDiagnostic;});
    fixture.events=previousEvents;await page.emulateMedia({reducedMotion:'reduce'});await page.setViewportSize(previousViewport);await page.locator('#networkView').click();await page.locator('#networkReset').click();
    if(await page.locator('#networkPreview').isVisible())await page.locator('#networkPreviewClose').click();
    const refreshed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state');
    await page.locator('#agentCards [data-agent-id="fixture-pm"]').click();await page.locator('#activityAll').click();
    await (await refreshed).finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.locator('#messageInput').fill(previousDraft);
  }
}
module.exports={networkInteractionAcceptance};
