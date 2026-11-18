"""The main screen: one thing at a time in the centre, and a face for every agent.

- the centre opens on 進み具合 (who is doing what, and the messages); the team diagram and the board are their own tabs;
- every agent is drawn with a face; the faces are original drawings built in the page, and each piece of work has its own cast.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cockpit_frontend import check
from test_frontend import APP, HTML
from test_task_guidance import Elements

CSS = (Path(__file__).resolve().parents[1] / 'static/styles.css').read_text(encoding='utf-8')

WALK = r'''
function everyNode(root){const all=[];(function walk(node){all.push(node);(node.children||[]).forEach(walk);})(root);return all;}
function facesIn(root){return everyNode(root).filter(node=>node.dataset&&node.dataset.face);}
'''


def test_the_centre_opens_on_progress_and_the_diagram_and_the_board_are_tabs():
    tree = Elements()
    assert 'data-cockpit-view="progress"' in HTML
    order = [ident for ident in ('progressView', 'networkView', 'boardView', 'inspectorView')]
    assert [HTML.index(f'id="{ident}"') for ident in order] == sorted(HTML.index(f'id="{ident}"') for ident in order)
    assert tree.ids['progressView']['attrs']['aria-pressed'] == 'true' and tree.ids['networkView']['attrs']['aria-pressed'] == 'false'
    assert tree.ids['progressView']['attrs']['aria-controls'] == 'main'
    # The numbers of a run are one line away, not always on the screen.
    assert any(node['attrs'].get('id') == 'runFacts' for node in tree.ids['runMetrics']['ancestors'])
    # Each tab shows its own thing: progress has no diagram, the diagram has neither the cards nor the messages.
    scope = ':root:not([data-layout=network-popout]) .app-shell'
    assert scope + '[data-cockpit-view=progress] .network-panel{display:none}' in CSS
    assert (scope + '[data-cockpit-view=network] .coordination-monitor,' + scope
            + '[data-cockpit-view=network] .activity-panel{display:none}') in CSS
    check(r'''
assert.equal(ui.cockpitView,'network');   // this file's set-up opens the diagram, as the diagram tests do
seedSelection();const composer=$('messageInput');composer.value='下書き';
for(const view of ['progress','network','board','inspector','progress']){
  setCockpitView(view);assert.equal(ui.cockpitView,view);
  for(const [id,mode] of [['progressView','progress'],['networkView','network'],['boardView','board'],['inspectorView','inspector']])
    assert.equal($(id).getAttribute('aria-pressed'),String(view===mode));
}
setCockpitView('somewhere');assert.equal(ui.cockpitView,'progress');
assert.equal(composer.value,'下書き');assert.equal(requests.length,0);
// Following a message from the diagram leads to the tab that holds the messages.
setCockpitView('network');selectMailPair('agent-a','agent-b');
assert.equal(ui.cockpitView,'progress');assert.deepEqual(ui.activityPair,{from:'agent-a',to:'agent-b'});assert.equal(document.activeElement,$('activityTitle'));
''')
    assert "Object.assign(ui,{cockpitView:'progress'," in APP
    assert "$('inspectAgentMail').addEventListener('click',()=>{ui.activityFilter='selected';setCockpitView('progress');" in APP


def test_there_are_more_than_twenty_faces_drawn_in_the_page_itself():
    check(WALK + r'''
assert.ok(FACES.length>=20);
assert.equal(new Set(FACES.map(face=>face.id)).size,FACES.length);assert.equal(new Set(FACES.map(face=>face.name)).size,FACES.length);
assert.ok(FACES.filter(face=>face.kind==='human').length>=12);assert.ok(FACES.filter(face=>face.kind==='robot').length>=6);
for(const name of ['黒スーツとサングラス','ふつうの会社員','気だるそうなお姉さん'])assert.ok(FACES.some(face=>face.name===name),name);
const drawings=new Set();
for(const face of FACES){
  const svg=faceSvg(face),nodes=everyNode(svg);
  assert.equal(svg.getAttribute('aria-hidden'),'true');assert.equal(svg.dataset.face,face.id);assert.ok(nodes.length>8,face.id);
  for(const node of nodes){
    assert.ok(['SVG','RECT','PATH','CIRCLE','ELLIPSE'].includes(node.tagName.toUpperCase()),face.id+' '+node.tagName);
    // Nothing the page's content policy would refuse, and nothing fetched: no style attribute, no link, no image.
    for(const name of ['style','href','xlink:href','src'])assert.ok(node.getAttribute(name)==null,face.id+' '+name);
  }
  drawings.add(JSON.stringify(nodes.map(node=>[node.tagName,node.getAttribute('d'),node.getAttribute('fill'),node.getAttribute('cx'),node.getAttribute('x')])));
}
assert.equal(drawings.size,FACES.length);   // no two faces are the same drawing
''')
    assert 'Math.random' not in APP and '<img' not in APP


def test_every_face_is_drawn_in_three_manners_and_a_piece_of_work_has_one_of_them():
    check(WALK + r'''
assert.deepEqual(FACE_STYLES,['flat','real','anime']);assert.deepEqual(Object.values(FACE_STYLE_LABELS),['イラスト','リアル','アニメ']);
const allowed=['SVG','RECT','PATH','CIRCLE','ELLIPSE','DEFS','LINEARGRADIENT','RADIALGRADIENT','STOP'],names=new Set();
for(const face of FACES){
  const drawn=FACE_STYLES.map(style=>{
    const svg=faceSvg(face,style),nodes=everyNode(svg);
    assert.equal(svg.dataset.face,face.id);assert.equal(svg.dataset.faceStyle,style);
    for(const node of nodes){
      assert.ok(allowed.includes(node.tagName.toUpperCase()),face.id+' '+style+' '+node.tagName);
      for(const name of ['style','href','xlink:href','src'])assert.ok(node.getAttribute(name)==null,face.id+' '+name);
      // A shading is named inside its own drawing, and a drawing uses only its own shadings.
      const id=node.getAttribute('id');if(id!=null){assert.ok(!names.has(id),id);names.add(id);}
      const fill=String(node.getAttribute('fill')||'');
      if(fill.startsWith('url('))assert.ok(nodes.some(other=>other.getAttribute('id')===fill.slice(5,-1)),face.id+' '+fill);
    }
    return JSON.stringify(nodes.map(node=>[node.tagName,node.getAttribute('d'),node.getAttribute('cx'),node.getAttribute('rx'),String(node.getAttribute('fill')||'').replace(/face-\d+-/,'')]));
  });
  assert.equal(new Set(drawn).size,3,face.id);                                  // the three manners are three drawings
}
assert.ok(names.size>FACES.length);                                             // the shaded manner uses shadings
assert.equal(faceSvg(FACES[0],'photograph').dataset.faceStyle,'flat');
// A piece of work is drawn in one manner, the same every time; other pieces of work have other manners.
seedSelection();
const runs=Array.from({length:30},(_,index)=>'r-'+String(index).padStart(16,'0')),manners=runs.map(run=>faceStyle(run));
assert.deepEqual(runs.map(run=>faceStyle(run)),manners);assert.deepEqual([...new Set(manners)].sort(),['anime','flat','real']);
const agent=ui.state.agents.find(item=>item.run_id===ui.selectedRun);
assert.equal(agentFaceSvg(agent).dataset.faceStyle,faceStyle(agent.run_id));assert.equal(agentFaceSvg(agent).dataset.face,agentFace(agent).id);
// Chosen on the screen: every piece of work is drawn that way, the faces themselves stay, and the lists are drawn again.
renderRun();const before=facesIn($('agentCards')).map(node=>node.dataset.face);
for(const style of FACE_STYLES){
  ui.faceStyle=style;renderRun();
  assert.ok(runs.every(run=>faceStyle(run)===style));
  for(const holder of ['agentCards','teamMap','conversationFace'])
    assert.ok(facesIn($(holder)).length>0&&facesIn($(holder)).every(node=>node.dataset.faceStyle===style),holder+' '+style);
  assert.deepEqual(facesIn($('agentCards')).map(node=>node.dataset.face),before);
}
ui.faceStyle='';renderRun();assert.equal(facesIn($('agentCards'))[0].dataset.faceStyle,faceStyle(ui.selectedRun));
''')
    tree = Elements()
    assert tree.ids['faceStyleSelect']['attrs'].get('id') == 'faceStyleSelect'
    assert [value for value in ('auto', 'flat', 'real', 'anime') if f'<option value="{value}"' in HTML] == ['auto', 'flat', 'real', 'anime']
    assert "ui.faceStyle=FACE_STYLES.includes(event.target.value)?event.target.value:'';renderRun();" in APP
    assert 'localStorage' not in APP.split('// --- Faces:')[1].split('function retainedTeamEvents')[0]


def test_each_piece_of_work_has_its_own_cast_and_keeps_it():
    check(r'''
seedSelection();
const agents=ui.state.agents.filter(agent=>agent.run_id===ui.selectedRun),cast=agents.map(agent=>agentFace(agent).id);
assert.ok(agents.length>=2);assert.equal(new Set(cast).size,cast.length);            // no face twice in one piece of work
assert.deepEqual(agents.map(agent=>agentFace(agent).id),cast);                         // and the same faces every time
const runs=['run-a','run-b','run-c','r-3e21983ed0285f4d','r-96249bac2abddce2','r-0000000000000001'];
for(const run of runs)assert.deepEqual([...faceOrder(run)].sort((a,b)=>a-b),FACES.map((_,index)=>index));   // every face, once
assert.ok(new Set(runs.map(run=>faceOrder(run).join(','))).size>=runs.length-1);       // another work, another order
assert.ok(new Set(runs.map(run=>faceOrder(run)[0])).size>=3);                           // and another lead
// The same agent in another piece of work looks different more often than not.
const moved=runs.filter(run=>agentFace({...agents[0],run_id:run}).id!==cast[0]).length;assert.ok(moved>=runs.length-2);
// More agents than faces: the cast starts again rather than running out.
ui.state.agents=Array.from({length:FACES.length+3},(_,index)=>({...agents[0],id:'agent-'+index}));
assert.equal(agentFace(ui.state.agents[FACES.length]).id,agentFace(ui.state.agents[0]).id);
''')


def test_the_list_the_cards_the_diagram_and_the_detail_show_the_same_face():
    check(WALK + r'''
seedSelection();renderRun();
const agent=ui.state.agents.find(item=>item.id===ui.selectedAgent),face=agentFace(agent).id;
const listed=facesIn($('agentCards')).map(node=>node.dataset.face),mapped=facesIn($('teamMap')).map(node=>node.dataset.face);
const total=ui.state.agents.filter(item=>item.run_id===ui.selectedRun).length;
assert.equal(listed.length,total);assert.equal(mapped.length,total);assert.deepEqual([...listed].sort(),[...mapped].sort());
assert.ok(listed.includes(face));
assert.deepEqual(facesIn($('conversationFace')).map(node=>node.dataset.face),[face]);
assert.equal($('conversationFace').hidden,false);assert.equal($('conversationFace').title,agentFace(agent).name);
// A refresh that changes nothing keeps the drawing in the detail; the diagram keeps its nodes.
const kept=facesIn($('conversationFace'))[0],node=ui.networkNodes.get(agent.id).button;
renderRun();assert.equal(facesIn($('conversationFace'))[0],kept);assert.equal(ui.networkNodes.get(agent.id).button,node);
''')
    for rule in ('.face{display:block;width:100%;height:100%;border-radius:50%}', '.agent-avatar.has-face .agent-avatar-mark{display:none}',
                 '.network-node .network-face~.network-monogram,.network-node .network-face~.network-role{display:none}'):
        assert rule in CSS
