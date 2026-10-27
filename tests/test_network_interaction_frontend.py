"""Real cockpit callbacks with synthetic DOM; no provider or browser requests."""
from test_cockpit_frontend import check


def test_drag_uses_camera_coordinates_preserves_selection_and_updates_edges():
    check(r'''
seedSelection();ui.state.events=[mail(1)];renderRun();
const original=JSON.stringify(ui.state),point={...ui.networkLayout.positions.get('agent-b')},beforeEdge=ui.networkParentLines[0].line.getAttribute('d');
networkViewState().camera={x:10,y:20,scale:.5};paintNetworkCamera();
const event=(x,y)=>({pointerId:7,clientX:x,clientY:y,isPrimary:true,button:0,preventDefault(){},stopPropagation(){}});
startNetworkGesture(event(100,100),'agent-b');updateNetworkGesture(event(102,102));
assert.deepEqual(ui.networkLayout.positions.get('agent-b'),point);
updateNetworkGesture(event(140,120));endNetworkGesture(event(140,120));
assert.deepEqual(ui.networkLayout.positions.get('agent-b'),{x:point.x+80,y:point.y+40});
assert.notEqual(ui.networkParentLines[0].line.getAttribute('d'),beforeEdge);
assert.equal(ui.networkMailLines[0].line.getAttribute('d'),networkMailPath(ui.networkLayout.positions.get('agent-a'),ui.networkLayout.positions.get('agent-b'),0));
networkNodeClick({detail:1,preventDefault(){}},'agent-b');assert.equal(ui.selectedAgent,'agent-a');
assert.equal(JSON.stringify(ui.state),original);assert.equal(ui.networkGesture,null);
''')


def test_pointer_cancel_restores_position_and_ignores_other_pointer():
    check(r'''
seedSelection();const point={...ui.networkLayout.positions.get('agent-b')};
const event={pointerId:1,clientX:100,clientY:100,button:0,stopPropagation(){}};
startNetworkGesture(event,'agent-b');updateNetworkGesture({...event,pointerId:2,clientX:180});
assert.deepEqual(ui.networkLayout.positions.get('agent-b'),point);
updateNetworkGesture({...event,clientX:180});endNetworkGesture({...event,clientX:180},true);
assert.deepEqual(ui.networkLayout.positions.get('agent-b'),point);assert.equal(ui.networkGesture,null);
''')


def test_membership_poll_during_drag_clears_grab_state_without_discarding_position():
    check(r'''
seedSelection();const event={pointerId:1,clientX:100,clientY:100,button:0,stopPropagation(){}};
startNetworkGesture(event,'agent-b');updateNetworkGesture({...event,clientX:180});
assert($('teamMap').classList.contains('is-dragging'));const point={...ui.networkLayout.positions.get('agent-b')};
ui.state.agents.push({...namedAgent('agent-b'),id:'new-worker'});renderRun();
assert.equal(ui.networkGesture,null);assert(!$('teamMap').classList.contains('is-dragging'));
assert.deepEqual(ui.networkLayout.positions.get('agent-b'),point);
''')


def test_pan_zoom_anchor_bounds_and_mobile_fit():
    check(r'''
seedSelection();$('teamMap').clientWidth=320;$('teamMap').clientHeight=150;fitNetwork();
let camera=networkViewState().camera;const bounds=networkBounds();
assert(bounds.x*camera.scale+camera.x>=-1);assert(bounds.y*camera.scale+camera.y>=-1);
assert((bounds.x+bounds.width)*camera.scale+camera.x<=321);assert((bounds.y+bounds.height)*camera.scale+camera.y<=151);
const point={x:90,y:70},world={x:(point.x-camera.x)/camera.scale,y:(point.y-camera.y)/camera.scale};
zoomNetwork(1.2,point);camera=networkViewState().camera;
assert(Math.abs(world.x*camera.scale+camera.x-point.x)<.001);assert(Math.abs(world.y*camera.scale+camera.y-point.y)<.001);
const before={...camera};panNetwork(30,-20);assert.equal(camera.x,before.x+30);assert.equal(camera.y,before.y-20);
zoomNetwork(Infinity);assert.deepEqual(networkViewState().camera,camera);
zoomNetwork(100000);assert.equal(networkViewState().camera.scale,2);assert($('networkZoomIn').disabled);
zoomNetwork(.000001);assert.equal(networkViewState().camera.scale,.01);assert($('networkZoomOut').disabled);
''')


def test_poll_membership_and_run_switch_preserve_local_geometry_and_selection():
    check(r'''
seedSelection();changeSelection('run-a','agent-b');renderRun();moveNetworkNode('agent-b',600,400);panNetwork(15,20);
const camera={...networkViewState().camera},button=ui.networkNodes.get('agent-b').button;
namedAgent('agent-b').status='working';renderRun();assert.equal(ui.networkNodes.get('agent-b').button,button);
assert.deepEqual(networkViewState().camera,camera);assert.deepEqual(ui.networkLayout.positions.get('agent-b'),{x:600,y:400});
selectRun('run-b');selectRun('run-a');assert.equal(ui.selectedAgent,'agent-b');
assert.deepEqual(ui.networkLayout.positions.get('agent-b'),{x:600,y:400});assert.deepEqual(networkViewState().camera,camera);
ui.state.agents.push({...namedAgent('agent-b'),id:'new-worker'});renderRun();assert.deepEqual(ui.networkLayout.positions.get('agent-b'),{x:600,y:400});
assert(ui.networkNodes.has('new-worker'));ui.state.agents=ui.state.agents.filter(a=>a.id!=='new-worker');renderRun();assert(!networkViewState().positions.has('new-worker'));
''')


def test_recent_geometry_cache_is_bounded_and_has_no_public_text():
    check(r'''
seedSelection();for(let i=0;i<100;i++)networkViewState('old-'+i);assert.equal(ui.networkViews.size,64);
assert(!ui.networkViews.has('old-0'));assert.deepEqual(Object.keys(networkViewState('old-99')).sort(),['camera','positions','selectedAgent']);
renderTeamMap(ui.state.agents.filter(a=>a.run_id==='run-a').slice(0,1));
assert([...ui.networkViews.keys()].every(id=>runs.some(run=>run.id===id)));
''')


def test_keyboard_node_move_camera_controls_and_reset_do_not_change_work():
    check(r'''
seedSelection();const original=JSON.stringify(ui.state),point={...ui.networkLayout.positions.get('agent-b')};let prevented=0;
networkNodeKey({key:'ArrowRight',altKey:false,preventDefault(){throw Error('regular arrows remain native');}},'agent-b');
networkNodeKey({key:'ArrowRight',altKey:true,preventDefault(){prevented++},stopPropagation(){}},'agent-b');
assert.equal(ui.networkLayout.positions.get('agent-b').x,point.x+10);assert.equal(prevented,1);
const before={...networkViewState().camera};networkKey({target:$('teamMap'),key:'ArrowRight',preventDefault(){}});assert.equal(networkViewState().camera.x,before.x-40);
networkKey({target:ui.networkNodes.get('agent-b').button,key:'ArrowRight',preventDefault(){throw Error('node arrows cannot pan');}});
resetNetworkLayout();assert.deepEqual(ui.networkLayout.positions.get('agent-b'),point);assert.equal(JSON.stringify(ui.state),original);
''')


def test_key_activation_still_selects_after_drag_and_mail_remains_accessible():
    check(r'''
seedSelection();ui.state.events=[mail(1)];renderRun();ui.networkSuppressClick='agent-b';
networkNodeClick({detail:0},'agent-b');assert.equal(ui.selectedAgent,'agent-b');
const line=ui.networkMailLines[0].line;line.listeners.keydown({key:'Enter',preventDefault(){}});
assert.deepEqual(ui.activityPair,{from:'agent-a',to:'agent-b'});assert.equal(ui.activityFilter,'pair');
assert.equal(line.getAttribute('role'),'button');assert.equal(line.getAttribute('tabindex'),'0');
''')


def test_restart_clears_geometry_and_excerpt_counts_do_not_claim_model_summary():
    check(r'''
seedSelection();ui.instanceId='first';ui.networkGesture={pointerId:9};
assert(acceptServerInstance({instance_id:'second'}));assert.equal(ui.networkViews.size,0);assert.equal(ui.networkGesture,null);
seedSelection();const agent=namedAgent('agent-a');agent.context_memory={compactions:2,fallback_compactions:1,history_records:10,history_omitted:0};renderConversation(agent);
assert.match($('contextMemoryStatus').textContent,/文脈圧縮 2 回/);assert.match($('contextMemoryStatus').textContent,/自動抜粋 1 回・AIによる要約ではありません/);
agent.context_memory.fallback_compactions=0;renderConversation(agent);assert(!/自動抜粋/.test($('contextMemoryStatus').textContent));
''')
