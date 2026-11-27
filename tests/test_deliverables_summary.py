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
                                       'review': 'none', 'resaved': [], 'unaddressed': False}
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


async def reviewed(engine, run, pm, work, report):
    """The coordinator saved a file and tried to finish; the reviewer then reported ``report``."""
    pm.pending.clear()
    await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing', 'paragraphs': ['要約']})
    held = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
    assert held['ok'] is False and held['code'] == 'review_pending'
    reviewer = next(agent for agent in engine.agents.values() if agent.role == 'reviewer')
    reviewer.results.append({'text': report, 'revision': 1})
    reviewer.status = 'done'
    reviewer.pending.clear()
    pm.pending.clear()
    return reviewer


@pytest.mark.review
async def test_a_work_whose_review_findings_were_left_as_they_were_is_not_done(tmp_path):
    """Real-machine case: the reviewer's verdict was "fix", "no file was saved again after the findings" stood at the
    end of the result, and the run was "done"."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='要約を summary.docx に保存して')
        await reviewed(engine, run, pm, work, 'VERDICT: fix\n1. summary.docx: 表がありません。')
        # Sent back once, with the findings and with what happens if nothing is saved again.
        back = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert back['ok'] is False and back['code'] == 'review_pending'
        assert '表がありません' in back['error'] and 'review findings not addressed' in back['error']
        # Finished again without saving anything: said at the head of the result, and the findings are at its end.
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '指摘は当たらないと判断しました。'})
        assert done.get('ok') is not False
        assert done['summary'].startswith('【アプリの確認】レビューの指摘が未対応です。')
        assert '指摘は当たらないと判断しました。' in done['summary'] and '表がありません' in done['summary']
        assert run['deliverables']['review'] == 'fix' and run['deliverables']['unaddressed'] is True
        # Everyone has finished, and the run is not "done".
        pm.status = 'done'
        engine._run_status(run)
        assert run['status'] == 'incomplete' and engine.run_status_reason(run) == 'review_unaddressed'
        events = [row['text'] for row in engine.events if row['kind'] == 'incomplete']
        assert events == ['未完了（レビューの指摘が未対応）: 提出前レビューの判定は「要修正」で、指摘のあとに保存し直されたファイルがありません']
        engine._run_status(run)
        assert len([row for row in engine.events if row['kind'] == 'incomplete']) == 1      # said once
        assert engine.snapshot()['runs'][-1]['status_reason'] == 'review_unaddressed'
    finally:
        await engine.close()


@pytest.mark.review
@pytest.mark.parametrize('report,resave,status,head', [
    ('VERDICT: fix\n1. summary.docx: 表がありません。', True, 'done', False),      # corrected and saved again
    ('VERDICT: pass\n問題ありません。', False, 'done', False),
    ('確認しました。表がありません。', False, 'done', False),                        # no verdict line: said in the footer, as before
])
async def test_a_corrected_or_passed_review_ends_as_done(tmp_path, report, resave, status, head):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='要約を summary.docx に保存して')
        await reviewed(engine, run, pm, work, report)
        if resave:
            read = await engine.execute_tool(run, pm, 'docx_read', {'path': str(work / 'summary.docx')})
            await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': read['sha256'],
                                                               'paragraphs': ['要約'], 'tables': [[['項目', '値'], ['成長率', '3.1']]]})
            pm.pending.clear()
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        if done.get('ok') is False:                       # the one send-back (no verdict line, nothing saved since)
            done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert done.get('ok') is not False and done['summary'].startswith('【アプリの確認】レビューの指摘が未対応') is head
        assert run['deliverables']['unaddressed'] is False
        pm.status = 'done'
        engine._run_status(run)
        assert run['status'] == status and engine.run_status_reason(run) == status
        assert not [row for row in engine.events if row['kind'] == 'incomplete']
    finally:
        await engine.close()


def test_the_screen_names_a_work_that_ended_with_the_findings_left_open():
    from test_cockpit_frontend import check
    check(r'''
assert.equal(REASON_LABELS.review_unaddressed,'未完了（レビューの指摘が未対応）');
const live={id:'r-1',status:'incomplete',status_reason:'review_unaddressed',deliverables:{files:[],review:'fix',resaved:[],unaddressed:true}};
assert.equal(stateLabel(live),'未完了（レビューの指摘が未対応）');
assert.equal(stateLabel({...live,status_reason:'incomplete',deliverables:{files:[],review:'fix',resaved:[],unaddressed:false}}),'未完了（成果物なし）');
// A saved work: the same words, unless a requested file is missing as well.
const saved={...live,archived:true,read_only:true,status_reason:'保存された履歴（閲覧専用）'};
assert.equal(stateLabel(saved),'保存履歴 · 未完了（レビューの指摘が未対応）');
assert.equal(stateLabel({...saved,output_check:{expected:['a.docx'],missing:['a.docx']}}),'保存履歴 · 未完了（成果物なし）');
// The summary of what was handed in says that the findings were left open.
function everyNode(root){const all=[];(function walk(node){all.push(node);(node.children||[]).forEach(walk);})(root);return all;}
const lines=()=>everyNode($('deliverablesContent')).map(node=>node.children&&node.children.length?'':String(node.textContent||'')).filter(Boolean);
ui.deliverablesSignature='';renderDeliverables({...live,deliverables:{files:[{name:'summary.docx',path:'C:\\out\\summary.docx',by:'PM'}],review:'fix',resaved:[],unaddressed:true}});
assert.ok(lines().includes('要修正（指摘が未対応のまま終了しました）'));
ui.deliverablesSignature='';renderDeliverables({...live,deliverables:{files:[{name:'summary.docx',path:'C:\\out\\summary.docx',by:'PM'}],review:'fix',resaved:['summary.docx'],unaddressed:false}});
assert.ok(lines().includes('要修正（指摘あり） · 指摘のあとに保存し直されたファイル: summary.docx'));
''')
