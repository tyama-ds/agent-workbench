"""The files a piece of work saved, and how its review stands, in one place for the human."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cockpit_frontend import check
from test_engine import ScriptClient, configured, reply, settled, start
from test_frontend import HTML


async def test_the_run_says_which_files_were_saved_where_and_by_whom(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='要約を report.docx に、表を table.xlsx に保存して')
        assert 'deliverables' not in run                                  # nothing saved yet: nothing to list
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'report.docx'), 'expected_sha256': 'missing', 'paragraphs': ['要約']})
        assert run['deliverables'] == {'files': [{'name': 'report.docx', 'path': str(work / 'report.docx'), 'by': pm.name}],
                                       'review': 'none', 'resaved': []}
        await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'notes.txt'), 'expected_sha256': 'missing', 'text': 'メモ'})
        assert [row['name'] for row in run['deliverables']['files']] == ['report.docx', 'notes.txt']
        assert run['output_check']['missing'] == ['table.xlsx']            # what was asked for is still told separately
        # It travels with the run to the screen and into the history.
        assert engine.snapshot()['runs'][0]['deliverables']['files'][0]['name'] == 'report.docx'
    finally:
        await engine.close()


@pytest.mark.review
async def test_the_run_says_how_the_review_stands(tmp_path):
    def step(answer):
        async def respond(profile, messages):
            return answer
        return respond
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='要約を summary.docx に保存して')
        pm.pending.clear()
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing', 'paragraphs': ['要約']})
        assert run['deliverables']['review'] == 'pending'                 # a reviewer will read before the end
        held = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert held['ok'] is False and held['code'] == 'review_pending' and run['deliverables']['review'] == 'waiting'
        reviewer = next(agent for agent in engine.agents.values() if agent.role == 'reviewer')
        reviewer.results.append({'text': 'VERDICT: pass\n問題ありません。', 'revision': 1})
        reviewer.status = 'done'
        reviewer.pending.clear()
        pm.pending.clear()
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert done.get('ok') is not False and run['deliverables']['review'] == 'pass'
    finally:
        await engine.close()


def test_the_progress_tab_shows_the_summary():
    assert HTML.index('id="deliverablesPanel"') < HTML.index('id="coordinationMonitor"')
    check(r'''
function everyNode(root){const all=[];(function walk(node){all.push(node);(node.children||[]).forEach(walk);})(root);return all;}
const text=()=>everyNode($('deliverablesContent')).map(node=>node.children&&node.children.length?'':String(node.textContent||'')).filter(Boolean);
seedSelection();renderRun();assert.equal($('deliverablesPanel').hidden,true);             // nothing to tell yet
const run=getRun();
run.output_check={expected:['report.docx','slides.pptx'],missing:['slides.pptx']};
run.deliverables={files:[{name:'report.docx',path:'C:\\work\\out\\report.docx',by:'Worker 1'},{name:'<img src=x onerror=alert(1)>',path:'C:\\work\\x',by:''}],review:'fix',resaved:['report.docx']};
renderRun();assert.equal($('deliverablesPanel').hidden,false);
const lines=text();
assert.ok(lines.includes('保存済み: report.docx'));assert.ok(lines.includes('未保存: slides.pptx'));
assert.ok(lines.includes('report.docx'));assert.ok(lines.includes('（Worker 1）'));assert.ok(lines.includes('C:\\work\\out\\report.docx'));
assert.ok(lines.includes('要修正（指摘あり） · 指摘のあとに保存し直されたファイル: report.docx'));
// A file name is text, whatever it holds.
assert.ok(lines.includes('<img src=x onerror=alert(1)>'));assert.equal(everyNode($('deliverablesContent')).filter(node=>node.tagName==='IMG').length,0);
// Drawn again only when something changed.
const first=$('deliverablesContent').children[0];renderRun();assert.equal($('deliverablesContent').children[0],first);
run.deliverables.review='pass';renderRun();assert.notEqual($('deliverablesContent').children[0],first);assert.ok(text().some(line=>line.startsWith('合格')));
// An unknown state or a malformed value shows nothing rather than something wrong.
run.deliverables={files:'x',review:'approved-by-magic'};run.output_check=null;renderRun();assert.equal($('deliverablesPanel').hidden,true);
''')
