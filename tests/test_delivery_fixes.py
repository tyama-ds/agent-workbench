"""Real-machine findings of a report-and-slides run that ended "done" without its files.

- the run's state when a requested file was never saved;
- docx_edit could only replace the paragraphs that were there;
- pptx_write refused a body given as one text, four times, without saying what it had received;
- a downloaded PDF could not be saved into the folder;
- a worker that depended on accepted reports did not get them.
"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest
from docx import Document
from pptx import Presentation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.harness import HarnessError, PathHarness, ToolExecutor
from pdf_fixture import make_pdf
from test_engine import configured, reply, settled, start

REPORT = make_pdf(['World Energy Outlook', 'Executive summary.\n' + 'Energy demand rises. ' * 150], title='WEO (test)')


def tools_in(tmp_path):
    return ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))


def call(tools, name, **args):
    return asyncio.run(tools.execute(name, args))


async def test_a_run_whose_requested_file_was_never_saved_is_incomplete_not_done(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='要約を report.docx に、スライドを slides.pptx に保存して', max_workers=0)
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'report.docx'), 'expected_sha256': 'missing',
                                                           'paragraphs': ['要約']})
        pm.pending.clear()
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert first['ok'] is False and first['code'] == 'outputs_missing' and 'slides.pptx' in first['error']
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert 'slides.pptx' in done['summary'] and '成果物は作られていません' in done['summary']
        pm.status = 'done'
        engine._run_status(run)
        # Everyone has finished, and the run is not "done".
        assert run['status'] == 'incomplete' and run['output_check']['missing'] == ['slides.pptx']
        events = [row['text'] for row in engine.events if row['kind'] == 'incomplete']
        assert events == ['未完了（成果物なし）: 依頼されたファイルが保存されていません: slides.pptx']
        engine._run_status(run)
        assert len([row for row in engine.events if row['kind'] == 'incomplete']) == 1   # said once
        # History keeps the state, and a saved run reads back as what it was.
        saved = engine.history.load(run['id'])['run'] if hasattr(engine.history, 'load') else None
        assert saved is None or saved['status'] == 'incomplete'
        # The file arrives after all (the human asked again): the run is done.
        await engine.execute_tool(run, pm, 'pptx_write', {'path': str(work / 'slides.pptx'), 'expected_sha256': 'missing',
                                                           'slides': [{'title': '要約', 'body': ['一行']}]})
        engine._run_status(run)
        assert run['status'] == 'done' and run['output_check']['missing'] == []
    finally:
        await engine.close()
    page = (Path(__file__).resolve().parents[1] / 'static' / 'app.js').read_text(encoding='utf-8')
    assert "incomplete:'未完了（成果物なし）'" in page


def test_docx_edit_adds_inserts_and_deletes_and_says_how_to_rewrite_the_document(tmp_path):
    tools = tools_in(tmp_path)
    path = str(tmp_path / 'report.docx')
    first = call(tools, 'docx_write', path=path, expected_sha256='missing', paragraphs=['見出し', '（本文を埋める予定）', '出典'])
    # What the model tried: replacing a paragraph that is not there.
    with pytest.raises(HarnessError) as caught:
        call(tools, 'docx_edit', path=path, expected_sha256=first['sha256'],
             operations=[{'type': 'replace_paragraph', 'index': 3, 'text': '第2章'}])
    text = str(caught.value)
    assert 'index must be 0..2 (the document has 3 paragraph(s)); got 3' in text
    assert 'append_paragraph' in text and 'insert_paragraph' in text
    assert 'docx_write with all paragraphs and tables and expected_sha256 set to' in text
    second = call(tools, 'docx_edit', path=path, expected_sha256=first['sha256'], operations=[
        {'type': 'replace_paragraph', 'index': 1, 'text': '第1章の本文'},
        {'type': 'insert_paragraph', 'index': 2, 'text': '第2章の本文'},      # before "出典"
        {'type': 'insert_paragraph', 'index': 4, 'text': '以上'},             # index = count: after the last
        {'type': 'insert_paragraph', 'index': 0, 'text': '表紙'},
        {'type': 'append_paragraph', 'text': '付録'}])
    assert [p.text for p in Document(path).paragraphs] == ['表紙', '見出し', '第1章の本文', '第2章の本文', '出典', '以上', '付録']
    third = call(tools, 'docx_edit', path=path, expected_sha256=second['sha256'], operations=[{'type': 'delete_paragraph', 'index': 5}])
    assert [p.text for p in Document(path).paragraphs] == ['表紙', '見出し', '第1章の本文', '第2章の本文', '出典', '付録']
    for bad in ({'type': 'insert_paragraph', 'index': 9, 'text': 'x'}, {'type': 'delete_paragraph', 'index': -1},
                {'type': 'insert_paragraph', 'index': '1', 'text': 'x'}):
        with pytest.raises(HarnessError, match='index must be 0..'):
            call(tools, 'docx_edit', path=path, expected_sha256=third['sha256'], operations=[bad])
    # The whole document rewritten: docx_write with the current hash.
    call(tools, 'docx_write', path=path, expected_sha256=third['sha256'], paragraphs=['全体を書き直した本文'])
    assert [p.text for p in Document(path).paragraphs] == ['全体を書き直した本文']
    # A text tool on a document says which tool to use and how to replace the file.
    with pytest.raises(HarnessError, match=r'use docx_write \(or docx_edit\) for \.docx files \(to replace an existing file, pass expected_sha256'):
        call(tools, 'write_text', path=path, expected_sha256='missing', text='x')


def test_a_slide_body_given_as_one_text_or_with_numbers_is_taken_and_a_wrong_one_says_what_it_was(tmp_path):
    tools = tools_in(tmp_path)
    path = str(tmp_path / 'deck.pptx')
    result = call(tools, 'pptx_write', path=path, expected_sha256='missing', slides=[
        {'title': '要点', 'body': '世界の需要は増加\n再エネの比率が上昇\n\n出典: p. 17'},      # one text with line breaks
        {'title': '数値', 'body': ['需要', 3.1, 42]},                                         # numbers among the lines
        {'layout': 'two_column', 'title': '比較', 'left': '現状\n課題', 'right': ['将来']}])
    assert result['slides_written'] == 3
    deck = Presentation(path)
    assert [p.text for p in deck.slides[0].placeholders[1].text_frame.paragraphs] == ['世界の需要は増加', '再エネの比率が上昇', '出典: p. 17']
    assert [p.text for p in deck.slides[1].placeholders[1].text_frame.paragraphs] == ['需要', '3.1', '42']
    # More lines than one slide holds continue on further slides instead of being refused.
    many = call(tools, 'pptx_write', path=str(tmp_path / 'long.pptx'), expected_sha256='missing',
                slides=[{'title': '一覧', 'body': [f'項目 {index}' for index in range(1, 151)]}])
    assert many['slides_written'] > 1 and 'continues on' in many['adjusted'][0]
    for body, problem in (({'a': 1}, r'such as \["first point", "second point"\]; got dict'),
                          ([['a', 'b']], r'one item is list\. A table goes into "table"'),
                          (['x'] * 400, 'got 400 items')):
        with pytest.raises(HarnessError, match=problem) as caught:
            call(tools, 'pptx_write', path=str(tmp_path / 'bad.pptx'), expected_sha256='missing', slides=[{'title': 'T', 'body': body}])
        assert 'slide 1 body' in str(caught.value)


async def test_a_downloaded_pdf_is_saved_as_a_new_file_in_a_write_folder(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    engine.settings.value['limits']['max_file_bytes'] = 2048   # a PDF has its own limit
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='IEA の PDF をダウンロードして WorldEnergyOutlook.pdf として保存して', max_workers=0)
        assert 'pdf_save' in [tool['name'] for tool in engine._model_tools(run, pm)]
        url = 'https://iea.blob.core.windows.net/assets/1438d3a5/WorldEnergyOutlook2025.pdf'
        record = engine.pdf_library.put(REPORT, url)
        with pytest.raises(ValueError, match='the id a web_fetch result of this work returned'):
            await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': record['pdf_id'], 'path': 'WorldEnergyOutlook.pdf'})
        run['_web'].pdf_ids[record['pdf_id']] = record
        saved = await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': record['pdf_id'], 'path': 'WorldEnergyOutlook.pdf'})
        assert (work / 'WorldEnergyOutlook.pdf').read_bytes() == REPORT and len(REPORT) > 2048
        assert saved['operation'] == 'created' and saved['sha256'] == hashlib.sha256(REPORT).hexdigest() and saved['source_url'] == url
        # A receipt like every saved file, and the requested file counts as saved.
        assert pm.output_receipts[-1]['tool'] == 'pdf_save' and pm.output_receipts[-1]['sha256'] == saved['sha256']
        assert run['output_check']['missing'] == []
        # New files only, .pdf only, write folders only.
        with pytest.raises(ValueError, match='already exists'):
            await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': record['pdf_id'], 'path': 'WorldEnergyOutlook.pdf'})
        with pytest.raises(ValueError, match='must end in .pdf'):
            await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': record['pdf_id'], 'path': 'report.docx'})
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': record['pdf_id'], 'path': str(tmp_path / 'outside.pdf')})
        assert not (tmp_path / 'outside.pdf').exists()
        # No approval card: it never changes an existing file.
        assert engine._approval_needed({**run, 'approval_mode': 'ask'}, 'pdf_save', {'pdf_id': 'x', 'path': 'a.pdf'}) is False
    finally:
        await engine.close()
    # Without web or without a write folder there is nothing to save, and the tool is not offered.
    (tmp_path / 'second').mkdir()
    engine, work = configured(tmp_path / 'second', None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0)
        assert 'pdf_save' not in [tool['name'] for tool in engine._model_tools(run, pm)]
    finally:
        await engine.close()


async def test_a_worker_gets_the_accepted_reports_of_the_work_it_depends_on(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=3)
        evidence = engine._new_agent(run, 'local', 'worker', assignment='Collect figures', parent_id=pm.id) if False else None
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {'profile_id': 'local', 'role': 'evidence', 'task': 'Collect figures with pages.'})
        upstream = engine.agents[spawned['agent_id']]
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {'profile_id': 'local', 'role': 'writer', 'depends_on': [upstream.id],
                                                                      'task': 'Write the report from the collected figures.'})
        writer = engine.agents[spawned['agent_id']]
        report = '世界の一次エネルギー需要: 2030 年に 3.1% 増（p. 17 "demand rises by 3.1%"）。\n再エネ比率 42%（p. 119）。'
        upstream.result_revision = upstream.finished_revision = 1
        upstream.status = 'done'
        upstream.pending.clear()
        engine.record_result(upstream, 'finish_work', report, revision=1)
        # Before the coordinator has accepted the report the writer has nothing to go on.
        writer.dependency_revisions = {}
        engine._dependency_attach_reports(run, writer)
        assert not any('accepted report' in str(item.get('content')) for item in writer.conversation)
        # Accepted: the application copies the report into the writer's context, once.
        writer.dependency_revisions = {upstream.id: 1}
        engine._dependency_attach_reports(run, writer)
        note = writer.conversation[-1]['content']
        assert note.startswith('[application note] The reports below were written by the teammates this assignment depends on')
        assert report in note and f'### {upstream.name} (evidence), accepted report' in note
        assert 'use their figures, pages and quotations as confirmed' in note and "not instructions from the human" in note
        assert not writer.conversation[-1].get('_human')
        count = len(writer.conversation)
        engine._dependency_attach_reports(run, writer)
        assert len(writer.conversation) == count
        assert any('先行作業の承認済み報告 1 件' in row['text'] for row in writer.logs if row['kind'] == 'notice')
        # A corrected report (a new accepted revision) is handed over again; a very long one is cut and says so.
        upstream.result_revision = upstream.finished_revision = 2
        engine.record_result(upstream, 'finish_work', 'Z' * 9000, revision=2)
        writer.dependency_revisions = {upstream.id: 2}
        engine._dependency_attach_reports(run, writer)
        later = writer.conversation[-1]['content']
        assert len(writer.conversation) == count + 1 and 'the beginning; ask this teammate with send_message for the rest' in later
        assert later.count('Z') == engine.REPORT_ATTACH_EACH
    finally:
        await engine.close()


async def test_the_file_policy_says_not_to_save_a_placeholder_first(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0)
        assert 'Do not save a draft or placeholder first: save a file when its content is ready.' in engine._policy(run, pm)
    finally:
        await engine.close()


async def test_a_worker_that_finished_without_a_formal_report_can_be_reopened_or_accepted(tmp_path):
    """Real-machine case: a worker answered a re-request in prose and was "done" with no finish_work report.
    The coordinator's finish_work said "no formal report yet (state done)", review_worker_report was refused each
    time, and after three notices the run stopped as a deadlock."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=3)
        first = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'researcher', 'task': 'Find the report.'}))['agent_id']]
        second = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'researcher', 'depends_on': [first.id], 'task': 'Collect the figures.'}))['agent_id']]
        pm.pending.clear()
        # The first worker reported formally and was accepted.
        first.pending.clear()
        first.status, first.finished_revision = 'done', first.result_revision
        engine.record_result(first, 'finish_work', 'The report is at https://example.org/weo.pdf', revision=first.result_revision)
        pm.worker_report_deliveries[first.id] = pm.worker_report_consumed[first.id] = first.result_revision
        pm.worker_report_reviews[first.id] = {'result_revision': first.result_revision, 'decision': 'accept'}

        def answered_in_prose(text):
            second.pending.clear()
            second.pending_mail_metadata.clear()
            second.dependency_revisions = {first.id: first.result_revision}
            second.dependency_stale, second.status, second.turns = False, 'done', second.turns + 1
            engine.record_result(second, 'assistant_response', text, revision=second.result_revision)

        answered_in_prose('世界成長率は 3.1%（p. 12）。報告は以上です。')
        assert engine._formal_report_expected(run, second) and not engine._formal_report_expected(run, pm)
        # The coordinator is told what this state is and the two ways on.
        refused = await engine.execute_tool(run, pm, 'finish_work', {'summary': '完了しました。'})
        assert refused['ok'] is False
        for words in ('finish_work の報告を出さずに終了しています', '待っても報告は届きません', f'worker_id {second.id}',
                      f'result_revision {second.result_revision}', 'decision "revise"', 'decision "accept"'):
            assert words in refused['error'], words
        # A wrong revision names the right one.
        with pytest.raises(ValueError, match=f'現在の result_revision は {second.result_revision} です'):
            await engine.execute_tool(run, pm, 'review_worker_report', {
                'worker_id': second.id, 'result_revision': 99, 'decision': 'accept', 'feedback': 'ok'})
        # "revise" reopens the worker: it gets the request and will run again.
        before = second.result_revision
        reopened = await engine.execute_tool(run, pm, 'review_worker_report', {
            'worker_id': second.id, 'result_revision': before, 'decision': 'revise', 'feedback': 'ページ番号も付けてください。'})
        assert reopened['ok'] and reopened['reopened'] and reopened['accepted'] is False and 'wait_for_workers' in reopened['note']
        assert second.result_revision == before + 1 and len(second.pending) == 1
        request = second.pending[0][0]
        assert 'not given with finish_work' in request and 'ページ番号も付けてください。' in request
        # It answers in prose once more. "accept" takes that answer as the report, on the coordinator's word.
        answered_in_prose('世界成長率は 3.1%（p. 12、"growth of 3.1 percent"）。')
        taken = await engine.execute_tool(run, pm, 'review_worker_report', {
            'worker_id': second.id, 'result_revision': second.result_revision, 'decision': 'accept', 'feedback': '数値を PDF で確認した。'})
        assert taken['accepted'] and taken['informal_report'] and 'did not pass the checks of a formal report' in taken['note']
        assert engine._dependency_current_report(run, second) and engine._dependency_pm_issue(run, pm) is None
        reviews = [json.loads(row['text']) for row in engine.events if row['kind'] == 'worker_report_review']
        assert [(row['decision'], row.get('informal_report')) for row in reviews] == [('revise', True), ('accept', True)]
        # A later worker that depends on it receives the accepted answer.
        third = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'writer', 'depends_on': [second.id], 'task': 'Write the report.'}))['agent_id']]
        third.dependency_revisions = {second.id: second.result_revision}
        engine._dependency_attach_reports(run, third)
        assert 'growth of 3.1 percent' in third.conversation[-1]['content']
        # A worker that is still at work is not such a case: the refusal says to wait.
        third.status = 'working'
        with pytest.raises(ValueError, match='wait_for_workers で待ってください'):
            await engine.execute_tool(run, pm, 'review_worker_report', {
                'worker_id': third.id, 'result_revision': third.result_revision, 'decision': 'accept', 'feedback': 'ok'})
        third.status = 'idle'
    finally:
        await engine.close()


async def test_a_worker_that_answers_in_prose_is_reminded_and_the_coordinator_gets_it_to_report(tmp_path):
    """The whole way with scripted models: the second worker answers in prose twice; the coordinator's finish_work
    is refused with the way on, "revise" reopens the worker, its finish_work report arrives and the run ends."""
    from workbench.engine import CONTINUATION_NUDGE

    class Client:
        def __init__(self):
            self.engine, self.steps, self.seen, self.ids, self.refusal = None, {}, [], {}, ''

        @staticmethod
        def last_tool(messages, name):
            return json.loads(next(item for item in reversed(messages)
                                   if item.get('role') == 'tool' and item.get('name') == name)['content'])

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            agent = self.engine.agents[conversation_id.rsplit('/', 1)[1]]
            step = self.steps.get(agent.id, 0)
            self.steps[agent.id] = step + 1
            self.seen.append((agent.role, step, messages[-1].get('content') if messages else ''))
            assert len(self.seen) <= 14, 'the run does not end'
            if agent.parent_id is None:
                if step == 0:
                    return reply(calls=[('spawn_worker', {'profile_id': 'local', 'role': 'finder', 'task': 'Find the report.'})])
                if step == 1:
                    self.ids['finder'] = self.last_tool(messages, 'spawn_worker')['agent_id']
                    return reply(calls=[('spawn_worker', {'profile_id': 'local', 'role': 'reader', 'depends_on': [self.ids['finder']],
                                                          'task': 'Collect the figures with pages.'})])
                if step == 2:
                    self.ids['reader'] = self.last_tool(messages, 'spawn_worker')['agent_id']
                    return reply(calls=[('wait_for_workers', {})])
                if step == 3:
                    finder = self.engine.agents[self.ids['finder']]
                    return reply(calls=[('review_worker_report', {'worker_id': finder.id, 'result_revision': finder.result_revision,
                                                                  'decision': 'accept', 'feedback': 'Checked.'}),
                                        ('wait_for_workers', {})])
                if step == 4:
                    return reply(calls=[('finish_work', {'summary': 'Both workers are done.'})])
                if step == 5:
                    self.refusal = self.last_tool(messages, 'finish_work')['error']
                    reader = self.engine.agents[self.ids['reader']]
                    return reply(calls=[('review_worker_report', {'worker_id': reader.id, 'result_revision': reader.result_revision,
                                                                  'decision': 'revise', 'feedback': 'Report with finish_work.'}),
                                        ('wait_for_workers', {})])
                reader = self.engine.agents[self.ids['reader']]
                return reply(calls=[('review_worker_report', {'worker_id': reader.id, 'result_revision': reader.result_revision,
                                                              'decision': 'accept', 'feedback': 'Checked.'}),
                                    ('finish_work', {'summary': 'Integrated both accepted reports.'})])
            if agent.role == 'finder':
                return reply(calls=[('finish_work', {'summary': 'The report is weo.pdf.'})])
            if step < 2:
                return reply(text='Growth is 3.1 percent (p. 12). That is my report.')   # prose, no tool, twice
            return reply(calls=[('finish_work', {'summary': 'Growth is 3.1 percent (p. 12).'})])

    client = Client()
    engine, work = configured(tmp_path, client)
    client.engine = engine
    try:
        run, pm = await asyncio.wait_for(start(engine, max_workers=2, delegation_level=1), 20)
        await asyncio.wait_for(settled(engine), 20)
        reader = engine.agents[client.ids['reader']]
        # Reminded once after its first answer in prose; the second answer in prose ended its turn without a report.
        reader_turns = [content for role, _, content in client.seen if role == 'reader']
        assert len(reader_turns) == 3 and reader_turns[1] == CONTINUATION_NUDGE
        assert 'not given with finish_work' in reader_turns[2] and 'Report with finish_work.' in reader_turns[2]
        # The coordinator's refusal named the state and the way on; "revise" then brought the formal report.
        assert 'finish_work の報告を出さずに終了しています' in client.refusal and 'decision "revise"' in client.refusal
        assert run['status'] == 'done' and pm.status == 'done' and reader.status == 'done'
        assert reader.finished_revision == reader.result_revision and reader.results[-1]['source'] == 'finish_work'
        assert pm.worker_report_reviews[reader.id] == {'result_revision': reader.result_revision, 'decision': 'accept'}
        assert not any(row['kind'] == 'stall_notice' for row in engine.events)
    finally:
        await asyncio.wait_for(engine.close(), 20)


async def test_a_missing_pdf_is_sent_back_once_more_with_the_tool_that_saves_it(tmp_path):
    """Real-machine case: report, slides and the downloaded PDF were asked for. Document and slides were saved, the
    PDF was not, pdf_save was never called, and the run ended incomplete without the coordinator being told."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='要約を report.docx に保存し、ダウンロードした PDF も WEO2025.pdf として同じフォルダーに保存して',
                              max_workers=0)
        pm.pending.clear()
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': '完了しました。'})
        assert first['code'] == 'outputs_missing' and 'report.docx (save with docx_write)' in first['error']
        assert 'WEO2025.pdf (save with pdf_save)' in first['error'] and 'pdf_id from the web_fetch result' in first['error']
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'report.docx'), 'expected_sha256': 'missing',
                                                           'paragraphs': ['要約']})
        # What is still missing is said once more, for that file alone.
        second = await engine.execute_tool(run, pm, 'finish_work', {'summary': '完了しました。'})
        assert second['code'] == 'outputs_missing' and 'report.docx' not in second['error']
        assert 'WEO2025.pdf (save with pdf_save)' in second['error'] and 'docx_write' not in second['error']
        # Said for this set; a third completion is let through and reported as what it is.
        third = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'PDF は保存できませんでした。'})
        assert 'WEO2025.pdf' in third['summary'] and '成果物は作られていません' in third['summary']
        pm.status = 'done'
        engine._run_status(run)
        assert run['status'] == 'incomplete' and run['output_check']['missing'] == ['WEO2025.pdf']
    finally:
        await engine.close()
