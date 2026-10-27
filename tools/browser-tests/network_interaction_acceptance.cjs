/* Synthetic recorded team, production pointer/keyboard controls, no inference. */
'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');

async function networkInteractionAcceptance({page,fixture,artifacts,report}) {
  const previousViewport=page.viewportSize(),previousEvents=fixture.events;
  const node=page.locator('#teamMap [data-agent-id="fixture-worker-1"]');
  const geometry=()=>page.evaluate(()=>({
    left:parseFloat(document.querySelector('#teamMap [data-agent-id="fixture-worker-1"]').style.left),
    top:parseFloat(document.querySelector('#teamMap [data-agent-id="fixture-worker-1"]').style.top),
    camera:document.querySelector('.network-canvas').style.transform,
    parent:[...document.querySelectorAll('.network-parent-line')].map(line=>line.getAttribute('d')),
    selected:document.querySelector('#teamMap .network-node[aria-pressed="true"]')?.dataset.agentId,
  }));
  try {
    await page.setViewportSize({width:1366,height:900});await page.locator('#networkView').click();await page.locator('#networkFit').click();
    const original=await geometry(),box=await node.boundingBox();assert(box&&box.width>0);
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
    await page.mouse.move(box.x+box.width/2+35,box.y+box.height/2+18,{steps:8});await page.mouse.up();
    const dragged=await geometry();assert(dragged.left>original.left&&dragged.top>original.top);
    assert.equal(dragged.selected,original.selected,'Dragging does not activate the card');assert.notDeepEqual(dragged.parent,original.parent);
    const response=await page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state');await response.finished();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.deepEqual(await geometry(),dragged,'Polling retains geometry, camera, selection and matching parent edges');
    await node.focus();await page.keyboard.press('Alt+ArrowRight');assert.equal((await geometry()).left,dragged.left+10);
    const beforeZoom=await geometry();await page.locator('#networkZoomIn').click();assert.notEqual((await geometry()).camera,beforeZoom.camera);
    const beforePan=await geometry();await page.locator('#teamMap').focus();await page.keyboard.press('ArrowRight');assert.notEqual((await geometry()).camera,beforePan.camera);
    const map=await page.locator('#teamMap').boundingBox();assert(map);
    const beforePointerPan=await geometry();await page.mouse.move(map.x+8,map.y+8);await page.mouse.down();await page.mouse.move(map.x+35,map.y+27,{steps:6});await page.mouse.up();
    assert.notEqual((await geometry()).camera,beforePointerPan.camera);assert.equal((await geometry()).left,beforePointerPan.left);
    await page.locator('#networkFit').click();await node.click();assert.equal(await node.getAttribute('aria-pressed'),'true');
    await page.locator('#networkView').click();
    fixture.events=[...previousEvents,{id:99001,run_id:'fixture-run',kind:'mail',mail_id:'synthetic-network-mail',
      from_agent_id:'fixture-worker-1',to_agent_id:'fixture-pm',from:'[SYNTHETIC] 資料・検索担当',to:'[SYNTHETIC] PM',
      subject:'[SYNTHETIC] Interactive edge',text:'[SYNTHETIC] Recorded mail only',delivery_state:'queued',message_type:'peer_message',at:1791169201}];
    const line=page.locator('.network-mail-line');await line.waitFor();await page.locator('#networkFit').click();
    const hit=await line.evaluate(line=>{
      const matrix=line.getScreenCTM();
      for(const part of [.5,.35,.65,.2,.8]){const point=line.getPointAtLength(line.getTotalLength()*part).matrixTransform(matrix);
        if(document.elementFromPoint(point.x,point.y)===line)return {x:point.x,y:point.y};}
      return null;
    });
    assert(hit,'Mail edge exposes a real visible pointer target');await page.mouse.click(hit.x,hit.y);
    await page.locator('#activityFeed').filter({hasText:'[SYNTHETIC] Recorded mail only'}).waitFor();
    assert.equal(await page.locator('#activityFeed .activity-item').count(),1,'Mail edge filters the recorded pair');
    await line.focus();await page.keyboard.press('Enter');await page.locator('#activityTitle:focus').waitFor();
    await page.screenshot({path:path.join(artifacts,'interactive-network-desktop.png'),fullPage:true});
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
    await page.screenshot({path:path.join(artifacts,'interactive-network-mobile.png'),fullPage:true});
    report.checks.push('interactive network: real drag without click, live parent edges, poll persistence, Alt+arrow node move, keyboard and pointer pan, zoom, recorded-mail pointer/keyboard selection, narrow fit and usable controls');
  } finally {
    fixture.events=previousEvents;await page.setViewportSize(previousViewport);await page.locator('#networkView').click();await page.locator('#networkReset').click();
    const refreshed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state');
    await page.locator('#agentCards [data-agent-id="fixture-pm"]').click();await page.locator('#activityAll').click();
    await (await refreshed).finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  }
}
module.exports={networkInteractionAcceptance};
