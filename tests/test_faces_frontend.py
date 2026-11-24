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


def test_the_style_sheet_can_be_read_with_the_default_encoding_of_windows():
    # Other tests read it with the platform's default encoding (cp1252 on Windows): one Japanese comment broke them.
    (Path(__file__).resolve().parents[1] / 'static/styles.css').read_bytes().decode('cp1252')
    assert not [char for char in CSS if '\u3040' <= char <= '\u9fff']
    assert '@media(max-width:640px){.conversation-face{display:none}}' in CSS   # a narrow heading keeps its room
    assert '@media(max-width:640px){.topbar .brand{display:none}}' in CSS       # and the narrow top bar its height

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


def test_there_are_more_than_twenty_faces_and_the_illustrations_are_drawn_in_the_page():
    check(WALK + r'''
assert.ok(FACES.length>=20);
assert.equal(new Set(FACES.map(face=>face.id)).size,FACES.length);assert.equal(new Set(FACES.map(face=>face.name)).size,FACES.length);
assert.ok(FACES.filter(face=>face.kind==='human').length>=12);assert.ok(FACES.filter(face=>face.kind==='robot').length>=6);
for(const name of ['黒スーツとサングラス','ふつうの会社員','気だるそうなお姉さん'])assert.ok(FACES.some(face=>face.name===name),name);
const drawings=new Set();
for(const face of FACES){
  const svg=faceSvg(face),nodes=everyNode(svg);
  assert.equal(svg.getAttribute('aria-hidden'),'true');assert.equal(svg.dataset.face,face.id);assert.equal(svg.dataset.faceStyle,'flat');assert.ok(nodes.length>8,face.id);
  for(const node of nodes){
    assert.ok(['SVG','RECT','PATH','CIRCLE','ELLIPSE'].includes(node.tagName.toUpperCase()),face.id+' '+node.tagName);
    // Nothing the page's content policy would refuse, and nothing fetched: no style attribute, no link, no image.
    for(const name of ['style','href','xlink:href','src'])assert.ok(node.getAttribute(name)==null,face.id+' '+name);
  }
  drawings.add(JSON.stringify(nodes.map(node=>[node.tagName,node.getAttribute('d'),node.getAttribute('fill'),node.getAttribute('cx'),node.getAttribute('x')])));
}
assert.equal(drawings.size,FACES.length);   // no two faces are the same drawing
''')
    assert 'Math.random' not in APP


def test_the_real_and_anime_manners_are_pictures_and_anime_is_used_only_when_ticked():
    check(WALK + r'''
assert.deepEqual(FACE_STYLES,['flat','real','anime']);assert.deepEqual(Object.values(FACE_STYLE_LABELS),['イラスト','リアル','アニメ']);
// A picture is one of the application's own files, by manner and number; it carries no script, style or outside address.
const sources=new Set();
for(const style of ['real','anime'])for(const [index,face] of FACES.entries()){
  const image=faceElement(face,style);
  assert.equal(image.tagName.toUpperCase(),'IMG');assert.equal(image.src,`/faces/${style}/${String(index+1).padStart(2,'0')}.webp`);
  assert.equal(image.dataset.face,face.id);assert.equal(image.dataset.faceStyle,style);assert.equal(image.alt,'');assert.equal(image.getAttribute('aria-hidden'),'true');
  assert.equal(image.draggable,false);assert.ok(image.getAttribute('style')==null);sources.add(image.src);
}
assert.equal(sources.size,FACES.length*2);
assert.equal(faceElement(FACES[0],'flat').tagName.toUpperCase(),'SVG');assert.equal(faceElement(FACES[0],'photograph').tagName.toUpperCase(),'SVG');
// Not ticked (how the page opens): no piece of work is shown in the anime manner, and it cannot be chosen.
seedSelection();
const runs=Array.from({length:40},(_,index)=>'r-'+String(index).padStart(16,'0'));
assert.ok(ui.faceAnime!==true);assert.deepEqual(faceStyles(),['flat','real']);
assert.deepEqual([...new Set(runs.map(run=>faceStyle(run)))].sort(),['flat','real']);
assert.deepEqual(runs.map(run=>faceStyle(run)),runs.map(run=>faceStyle(run)));           // a work keeps its manner
ui.faceStyle='anime';assert.ok(runs.every(run=>faceStyle(run)!=='anime'));ui.faceStyle='';
// Ticked: anime joins the manners that go with a piece of work, and can be chosen.
ui.faceAnime=true;assert.deepEqual(faceStyles(),['flat','real','anime']);
assert.deepEqual([...new Set(runs.map(run=>faceStyle(run)))].sort(),['anime','flat','real']);
// Chosen on the screen: every piece of work is shown that way, the faces themselves stay, and the lists are drawn again.
renderRun();const before=facesIn($('agentCards')).map(node=>node.dataset.face);
for(const style of FACE_STYLES){
  ui.faceStyle=style;renderRun();assert.ok(runs.every(run=>faceStyle(run)===style));
  for(const holder of ['agentCards','teamMap','conversationFace'])
    assert.ok(facesIn($(holder)).length>0&&facesIn($(holder)).every(node=>node.dataset.faceStyle===style&&(node.tagName.toUpperCase()==='IMG')===(style!=='flat')),holder+' '+style);
  assert.deepEqual(facesIn($('agentCards')).map(node=>node.dataset.face),before);
}
// Unticked again while anime is chosen: the choice no longer holds.
ui.faceAnime=false;renderRun();assert.ok(facesIn($('agentCards')).every(node=>node.dataset.faceStyle!=='anime'));
ui.faceStyle='';renderRun();assert.equal(facesIn($('agentCards'))[0].dataset.faceStyle,faceStyle(ui.selectedRun));
''')
    tree = Elements()
    assert tree.ids['faceAnimeAllow']['attrs'].get('type') == 'checkbox' and 'checked' not in tree.ids['faceAnimeAllow']['attrs']
    assert '<option value="anime" disabled>' in HTML
    assert [value for value in ('auto', 'flat', 'real', 'anime') if f'<option value="{value}"' in HTML] == ['auto', 'flat', 'real', 'anime']
    assert "$('faceAnimeAllow').addEventListener('change'" in APP
    faces = APP.split('// --- Faces:')[1].split('function retainedTeamEvents')[0]
    assert 'localStorage' not in faces and 'sessionStorage' not in faces and 'http' not in faces.replace('http://www.w3.org', '')


def test_the_pictures_are_the_application_s_own_small_files():
    import struct
    root = Path(__file__).resolve().parents[1] / 'static' / 'faces'
    assert sorted(path.name for path in root.iterdir()) == ['NOTICE.txt', 'anime', 'real']
    for style in ('real', 'anime'):
        names = sorted(path.name for path in (root / style).iterdir())
        assert names == [f'{number:02d}.webp' for number in range(1, 27)]
        for name in names:
            data = (root / style / name).read_bytes()
            assert data[:4] == b'RIFF' and data[8:12] == b'WEBP' and struct.unpack('<I', data[4:8])[0] + 8 == len(data)
            assert 1000 < len(data) < 40000, name                      # 256 pixels square: a few kilobytes each
    assert 'fictional' in (root / 'NOTICE.txt').read_text(encoding='utf-8')


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


async def test_the_server_gives_only_the_fixed_pictures_to_the_page_that_signed_in(tmp_path):
    from test_config_server import bootstrap, serving
    root = Path(__file__).resolve().parents[1] / 'static' / 'faces'
    async with serving(tmp_path / 'http') as (auth, app, client):
        # Not signed in: nothing.
        response = await client.get(auth.origin + '/faces/real/01.webp')
        assert response.status == 401 and response.headers['Cache-Control'] == 'no-store'
        await bootstrap(auth, client)
        for style, name in (('real', '01.webp'), ('real', '26.webp'), ('anime', '13.webp')):
            response = await client.get(f'{auth.origin}/faces/{style}/{name}')
            assert response.status == 200 and response.headers['Content-Type'] == 'image/webp'
            assert await response.read() == (root / style / name).read_bytes()
            # A fixed file of the application: the page may keep it, and the other protections stay.
            assert response.headers['Cache-Control'] == 'private, max-age=86400'
            assert response.headers['X-Content-Type-Options'] == 'nosniff' and "img-src 'self' data:" in response.headers['Content-Security-Policy']
        # Nothing else under the folder, no other folder, no other name.
        for path in ('/faces/real/00.webp', '/faces/real/27.webp', '/faces/real/1.webp', '/faces/real/01.png', '/faces/real/01.webp.bak',
                     '/faces/flat/01.webp', '/faces/NOTICE.txt', '/faces/real/NOTICE.txt', '/faces/real/..%2Fanime%2F01.webp',
                     '/faces/real/', '/faces/', '/faces/real/01.webp/x'):
            response = await client.get(auth.origin + path)
            assert response.status in {404, 405}, path
            assert response.headers['Cache-Control'] == 'no-store', path
        for headers in ({'Origin': 'https://attacker.invalid'}, {'Sec-Fetch-Site': 'cross-site'}):
            response = await client.get(auth.origin + '/faces/real/01.webp', headers=headers)
            assert response.status == 403 and response.headers['Cache-Control'] == 'no-store'
        # Everything else is still not kept.
        response = await client.get(auth.origin + '/styles.css')
        assert response.status == 200 and response.headers['Cache-Control'] == 'no-store'
