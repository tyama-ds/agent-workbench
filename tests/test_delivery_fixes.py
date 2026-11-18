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
        other = engine.pdf_library.put(make_pdf(['Another report.'], title='Other'), 'https://example.org/other.pdf')
        run['_web'].pdf_ids[other['pdf_id']] = other
        with pytest.raises(ValueError, match='already exists'):
            await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': other['pdf_id'], 'path': 'WorldEnergyOutlook.pdf'})
        assert (work / 'WorldEnergyOutlook.pdf').read_bytes() == REPORT
        # And the same file is not saved a second time, under this name or another.
        with pytest.raises(ValueError, match='already saved in this work'):
            await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': record['pdf_id'], 'path': 'copy.pdf'})
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


def test_which_named_files_a_request_asks_to_produce():
    from workbench.verification import output_names
    assert output_names('要約を weo2026_summary.docx、スライドを weo2026_slides.pptx として weo2026e フォルダーに保存してください') == {
        'weo2026_summary.docx', 'weo2026_slides.pptx'}
    assert output_names('data.xlsx と notes.docx を読んで report.docx を作って') == {'report.docx'}
    assert output_names('weo.pdf から要点を抜き出し、summary.md にまとめて') == {'summary.md'}
    assert output_names('Read data.xlsx and write the result to report.docx') == {'report.docx'}
    assert output_names('Save the summary as a.docx and the slides as b.pptx, based on source.pdf') == {'a.docx', 'b.pptx'}
    assert output_names('report.docx について教えて') == set() and output_names(None) == set()
    # Real-machine case: slides that were asked for were not made and the run was "done". A word of reading that
    # stands somewhere before the word of making ("要約から…作成", "図表を使ったスライド") does not make the file an input.
    both = {'weo2026_summary.docx', 'weo2026_slides.pptx'}
    for request in ('IMF の WEO 最新号の PDF を読み、要約を weo2026_summary.docx に、スライドを weo2026_slides.pptx に保存してください',
                    '要約レポート weo2026_summary.docx と、図表を使ったスライド weo2026_slides.pptx を作成してください',
                    'weo2026_summary.docx（要約、主要な数値は表にする）と weo2026_slides.pptx（要約から 8 枚程度）を作成',
                    'スライド weo2026_slides.pptx は、要約の内容をもとに 16:9 で作成してください。要約は weo2026_summary.docx に保存',
                    'weo2026_summary.docx を作り、それを見て weo2026_slides.pptx も作る'):
        assert output_names(request) == both, request
    assert output_names('figures.xlsx の数値で report.docx を作成') == {'report.docx'}
    assert output_names('前回の old.docx（先月分）を参考に new.docx を作成') == {'new.docx'}
    assert output_names('成果物: weo_energy_summary.docx, weo_energy_slides.pptx') == {'weo_energy_summary.docx', 'weo_energy_slides.pptx'}
    assert output_names('IEA の PDF を読み、要約を weo_energy_summary.docx、スライドを weo_energy_slides.pptx に保存し、'
                        'ダウンロードした PDF も WorldEnergyOutlook2025.pdf として同じフォルダーに保存してください') == {
        'weo_energy_summary.docx', 'weo_energy_slides.pptx', 'worldenergyoutlook2025.pdf'}


async def test_a_requested_file_is_a_deliverable_although_one_of_its_name_lies_directly_in_a_permitted_folder(tmp_path):
    """Real-machine case: the slides were asked for by name, were not made, and the run was "done". A file of that name
    from an earlier run counted as "what the request works on" wherever it lay directly in a permitted folder."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        (work / 'weo2026_slides.pptx').write_bytes(b'last week')     # directly in the folder, from an earlier run
        (work / 'figures.xlsx').write_bytes(b'input')
        run, pm = await start(engine, max_workers=0, task='figures.xlsx を読んで、要約を weo2026_summary.docx に保存し、'
                              'スライド weo2026_slides.pptx（要約から 8 枚程度）も作成してください')
        assert run['output_check'] == {'expected': ['weo2026_summary.docx', 'weo2026_slides.pptx'],
                                       'missing': ['weo2026_summary.docx', 'weo2026_slides.pptx']}
        pm.pending.clear()
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'weo2026_summary.docx'), 'expected_sha256': 'missing',
                                                           'paragraphs': ['要約']})
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'スライドは未検証です。'})
        assert first['code'] == 'outputs_missing' and 'weo2026_slides.pptx (save with pptx_write)' in first['error']
        await engine.execute_tool(run, pm, 'finish_work', {'summary': 'スライドは未検証です。'})
        pm.status = 'done'
        engine._run_status(run)
        assert run['status'] == 'incomplete' and run['output_check']['missing'] == ['weo2026_slides.pptx']
        # Written anew in this run (over the old file): the deliverable is there.
        sha = (await engine.execute_tool(run, pm, 'file_hash', {'path': str(work / 'weo2026_slides.pptx')}))['sha256']
        await engine.execute_tool(run, pm, 'pptx_write', {'path': str(work / 'weo2026_slides.pptx'), 'expected_sha256': sha,
                                                           'slides': [{'title': '要約', 'body': ['一行']}]})
        engine._run_status(run)
        assert run['status'] == 'done'
    finally:
        await engine.close()


async def test_an_older_file_of_the_same_name_elsewhere_does_not_stand_in_for_a_requested_file(tmp_path):
    """Real-machine case: "save the summary as weo2026_summary.docx" ended "done" with an empty folder. Files of
    those names stood in the folders of earlier runs beside it, and the application took them for the files asked for."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        for folder in ('weo2026c', 'weo2026d'):
            (work / folder).mkdir()
            (work / folder / 'weo2026_summary.docx').write_bytes(b'last week')
        (work / 'weo2026d' / 'weo2026_slides.pptx').write_bytes(b'last week')
        (work / 'data').mkdir()
        (work / 'data' / 'figures.xlsx').write_bytes(b'input')
        (work / 'notes.md').write_text('input', encoding='utf-8')
        run, pm = await start(engine, max_workers=0, task='figures.xlsx と notes.md を読んで、要約を weo2026_summary.docx、'
                              'スライドを weo2026_slides.pptx として weo2026e フォルダーに保存してください')
        # What the request reads is not asked for; what it asks to produce is, although files of those names exist.
        assert run['output_check'] == {'expected': ['weo2026_summary.docx', 'weo2026_slides.pptx'],
                                       'missing': ['weo2026_summary.docx', 'weo2026_slides.pptx']}
        pm.pending.clear()
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': '取得できず、成果物は未作成です。'})
        assert first['code'] == 'outputs_missing'
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '取得できず、成果物は未作成です。'})
        assert '成果物は作られていません' in done['summary']
        pm.status = 'done'
        engine._run_status(run)
        assert run['status'] == 'incomplete'          # the coordinator said so itself; the run says so too
        # Saved where it was asked for (through a tool, or by a script without a receipt): no longer missing.
        (work / 'weo2026e').mkdir()
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'weo2026e' / 'weo2026_summary.docx'),
                                                           'expected_sha256': 'missing', 'paragraphs': ['要約']})
        (work / 'weo2026e' / 'weo2026_slides.pptx').write_bytes(b'written by a script')
        engine._run_status(run)
        assert run['status'] == 'done' and run['output_check']['missing'] == []
    finally:
        await engine.close()


def test_a_refused_file_tool_call_says_which_argument_and_one_table_is_taken_as_one_table(tmp_path):
    """Real-machine case: docx_write answered "Unsupported or missing tool arguments" seven times in a row. tables held
    the rows of one table, and the history did not show which argument was wrong."""
    tools = tools_in(tmp_path)
    path = str(tmp_path / 'report.docx')
    rows = [['指標', 'CPS', 'STEPS', 'NZE'], ['2035年の総エネルギー需要増加', 838, 744.5, '654'], ['出典ページ', 'p. 12', None, 'p. 14']]
    # The rows of one table are one table; a number typed without quotes is its text.
    result = call(tools, 'docx_write', path=path, expected_sha256='missing', paragraphs=['要約'], tables=rows)
    document = Document(path)
    assert [[cell.text for cell in row.cells] for row in document.tables[0].rows] == [
        ['指標', 'CPS', 'STEPS', 'NZE'], ['2035年の総エネルギー需要増加', '838', '744.5', '654'], ['出典ページ', 'p. 12', '', 'p. 14']]
    assert len(document.tables) == 1 and result['operation'] == 'created'
    # A list of tables stays a list of tables.
    (tmp_path / 'b').mkdir()
    call(tools, 'docx_write', path=str(tmp_path / 'b' / 'two.docx'), expected_sha256='missing', tables=[rows, [['a', 'b']]])
    assert len(Document(str(tmp_path / 'b' / 'two.docx')).tables) == 2
    # An argument the tool does not have, and one that is missing: named, with what the tool takes and an example.
    with pytest.raises(HarnessError) as caught:
        call(tools, 'docx_write', path=path, title='要約', sections=[], paragraphs=['x'])
    text = str(caught.value)
    for words in ('docx_write was not run', 'no argument named sections, title', 'required argument expected_sha256 is missing',
                  'takes only: path, expected_sha256, paragraphs, tables', 'Example: {"path": "report.docx"',
                  'docx_edit with append_paragraph and append_table'):
        assert words in text, words
    # Rows of different widths, and something that is not rows: said as what they are.
    with pytest.raises(HarnessError, match=r'the rows here have \[2, 3\] cells'):
        call(tools, 'docx_write', path=path, expected_sha256=result['sha256'], tables=[[['a', 'b'], ['c', 'd', 'e']]])
    with pytest.raises(HarnessError, match='A table is a list of 1 to 200 rows, each row a list of cells'):
        call(tools, 'docx_write', path=path, expected_sha256=result['sha256'], tables=[{'rows': []}])
    from workbench.providers import _native_call
    broken = _native_call('c1', 'docx_write', '{"path": "report.docx", "paragraphs": ["a" "b"]}', set())
    assert 'the reply may have been cut off' in broken['error'] and 'docx_edit to append the rest' in broken['error']


def test_two_agents_keeping_the_same_pdf_at_once_do_not_fail(tmp_path, monkeypatch):
    """Real-machine case: "[WinError 5] Access is denied: ...pdf.21068.27188.tmp -> ...pdf": the coordinator and a
    worker fetched the same report at the same time, and replacing the file the other had open was refused."""
    import os
    from workbench import pdfdocs
    library = pdfdocs.PdfLibrary(tmp_path / 'pdf-cache')
    first = library.put(REPORT, 'https://example.org/weo.pdf')
    replaced, really_replace = [], os.replace

    def refusing(source, target):
        replaced.append(Path(target).name)
        if str(target).endswith('.pdf'):
            raise PermissionError(5, 'Access is denied')   # the other agent has it open
        return really_replace(source, target)

    monkeypatch.setattr(pdfdocs.os, 'replace', refusing)
    second = library.put(REPORT, 'https://example.org/weo.pdf')
    # The file that is there is this file: it is not replaced at all, and nothing fails.
    assert second['pdf_id'] == first['pdf_id'] and replaced == [first['pdf_id'] + '.json']
    assert library.get(first['pdf_id'])[0] == REPORT and not list((tmp_path / 'pdf-cache').glob('*.tmp'))
    # A record that cannot be replaced for a moment is tried again, and an existing one is kept.
    monkeypatch.setattr(pdfdocs.time, 'sleep', lambda seconds: None)
    def always_refusing(source, target):
        raise PermissionError(5, 'Access is denied')

    monkeypatch.setattr(pdfdocs.os, 'replace', always_refusing)
    third = library.put(REPORT, 'https://example.org/weo.pdf')
    assert third['pdf_id'] == first['pdf_id'] and library.get(first['pdf_id'])[0] == REPORT
    assert not list((tmp_path / 'pdf-cache').glob('*.tmp'))


async def test_a_file_whose_save_failed_is_not_listed_as_a_cited_source(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        source = 'https://www.iea.org/reports/world-energy-outlook-2025'
        run, pm = await start(engine, max_workers=0, task=f'{source} の要約を summary.docx に保存して')
        args = {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing', 'paragraphs': [f'出典: {source}']}
        # The citations of a write are noted before it runs; this write never produced a file.
        engine._source_check(run, pm, 'docx_write', args)
        assert run['_cited'] and engine._citation_rows(run, 10) == [] and engine._citations_footer(run) == ''
        await engine.execute_tool(run, pm, 'docx_write', args)
        assert [row[:2] for row in engine._citation_rows(run, 10)] == [(args['path'], source)]
    finally:
        await engine.close()


def test_page_and_quotation_pairs_are_read_from_what_a_document_states():
    from workbench.verification import page_quotes
    args = {'path': 'report.docx', 'expected_sha256': 'missing',
            'paragraphs': ['天然ガス需要は増える（p.119 「5,600 bcm by 2050」）。', 'Coal use: "Coal use starts to decline globally before 2030" (p. 123).',
                           '電力需要は 2035 年に 37,800 TWh（p.31）。', '「引用だけでページのない文」', 'Figure 1.2 shows "a quotation far from any page"'],
            'tables': [[['指標', '値', '出典ページ', '原文の短い引用'], ['蓄電池', '77 GW', 'p.65', 'battery storage additions of 77 GW'],
                        ['石油需要', '105 mb/d', '123', 'oil demand reaches 105 mb/d']]]}
    assert page_quotes(args) == [(119, '5,600 bcm by 2050'), (123, 'Coal use starts to decline globally before 2030'),
                                 (65, 'battery storage additions of 77 GW'), (123, 'oil demand reaches 105 mb/d')]
    assert page_quotes({'slides': [{'title': 'x', 'body': ['p. 12 “growth of 3.1 percent”', 'app.12 "not a page"']}]}) == [
        (12, 'growth of 3.1 percent')]
    assert page_quotes({'text': 'no page here'}) == [] and page_quotes(None) == []


async def test_quotations_are_looked_up_in_the_pdf_and_a_wrong_page_is_corrected_or_sent_back(tmp_path):
    """Real-machine cases: "5,600 bcm by 2050 (p.119)" stood on pages 151 and 161 and one figure was not in the PDF;
    later "…105 mb/d in 2035 (p.153)" stood on p. 123 alone, the coordinator was shown it and did not change it."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        pdf = make_pdf(['Overview. Electricity demand reaches 37 800 TWh by 2035.', 'Natural gas. Demand rises to\n5,600 bcm by 2050 in this scenario.',
                        'Coal. Coal use starts to decline globally before 2030. Oil demand plateaus in the 2030s.',
                        'Annex. Oil demand plateaus in the 2030s.'], title='Outlook (test)')
        (work / 'outlook.pdf').write_bytes(pdf)
        run, pm = await start(engine, max_workers=0, task='outlook.pdf を読んで要約を summary.docx に保存して')
        pm.pending.clear()
        await engine.execute_tool(run, pm, 'pdf_read', {'path': str(work / 'outlook.pdf'), 'first_page': 1, 'last_page': 1})
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing', 'paragraphs': [
            '電力需要: 「Electricity demand reaches 37 800 TWh by 2035」（p.1）',
            '天然ガス: 「5,600 bcm by 2050」（p.3）',                       # stands on page 2 alone, across a line break
            '石油: 「Oil demand plateaus in the 2030s」（p.1）',             # stands on pages 3 and 4
            'STEPS: 約 55 EJ 増（p.2 「demand rises by about 55 EJ」）']})   # not in the PDF
        refused = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        # The page the PDF leaves no doubt about was written by the application, before anything was sent back.
        paragraphs = [paragraph.text for paragraph in Document(str(work / 'summary.docx')).paragraphs]
        assert paragraphs[1] == '天然ガス: 「5,600 bcm by 2050」（p.2）' and paragraphs[0].endswith('（p.1）')
        assert pm.output_receipts[-1]['tool'] == 'page_reference_fix'
        assert run['_quotes_corrected'] == [{'path': str(work / 'summary.docx'), 'from': 3, 'to': 2, 'quote': '5,600 bcm by 2050'}]
        # Sent back once: only what the application could not decide.
        assert refused['ok'] is False and refused['code'] == 'quotations_review' and '5,600 bcm' not in refused['error']
        assert '- p. 1 「Oil demand plateaus in the 2030s」 → PDF では p. 3, 4。ページを p. 3 に直すか、引用を外してください' in refused['error']
        assert ('- p. 2 「demand rises by about 55 EJ」 → PDF の本文に見つかりません。引用符とページを外すか、「ページ未確認」と書いてください'
                in refused['error'])
        # Left as it was: the file says so itself, and the result says what the application did.
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert 'ページ番号つきの引用 4 件' in done['summary'] and '一致 2 件、不一致 2 件' in done['summary']
        assert '- p.3→p.2 に訂正: 「5,600 bcm by 2050」（summary.docx）' in done['summary']
        assert '「（ページ未確認）」または「（PDF に原文なし・数値未確認）」を付けました' in done['summary']
        assert [paragraph.text for paragraph in Document(str(work / 'summary.docx')).paragraphs] == [
            '電力需要: 「Electricity demand reaches 37 800 TWh by 2035」（p.1）', '天然ガス: 「5,600 bcm by 2050」（p.2）',
            '石油: 「Oil demand plateaus in the 2030s」（p.1（ページ未確認））',
            'STEPS: 約 55 EJ 増（p.2（PDF に原文なし・数値未確認） 「demand rises by about 55 EJ」）']
        assert pm.output_receipts[-1]['tool'] == 'page_unconfirmed_mark'
        # Corrected and saved again by the coordinator: nothing is left to say.
        sha = (await engine.execute_tool(run, pm, 'file_hash', {'path': str(work / 'summary.docx')}))['sha256']
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': sha, 'paragraphs': [
            '電力需要: 「Electricity demand reaches 37 800 TWh by 2035」（p.1）', '天然ガス: 「5,600 bcm by 2050」（p.2）',
            '石油: 「Oil demand plateaus in the 2030s」（p.3）', 'STEPS の増加幅はページ未確認。']})
        await engine._quotes_verify(run)
        assert [row['status'] for row in run['_quote_results']] == ['ok', 'ok', 'ok'] and '不一致 0 件' in engine._quotes_footer(run)
    finally:
        await engine.close()


async def test_the_saved_pdf_is_the_one_that_was_read_and_it_is_saved_once(tmp_path):
    """Real-machine case: the report quoted one copy of a document; an older copy was saved, twice, under two names;
    and the saved file, read by its path, was reported as "not downloaded in this work"."""
    from workbench.pdfdocs import PdfLibrary
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='報告書の PDF を読んで要約し、PDF も保存して')
        pm.pending.clear()
        newer = make_pdf(['Outlook 2025, edition of March.', 'Demand rises.'], title='Outlook (newer)')
        older = make_pdf(['Outlook 2025, edition of November.', 'Demand rises.'], title='Outlook (older)')
        records = {}
        for name, data in (('newer', newer), ('older', older)):
            records[name] = engine.pdf_library.put(data, f'https://files.iea.org/{name}/WorldEnergyOutlook2025.pdf')
        class Web:
            pdf_ids = {record['pdf_id']: record for record in records.values()}
        run['_web'] = Web()
        read = await engine._pdf_read(run, pm, {'pdf_id': records['newer']['pdf_id'], 'first_page': 1})
        assert read['pages'] == 2
        # The other copy: refused once, with the id of the one that was read.
        with pytest.raises(ValueError) as caught:
            await engine._pdf_save(run, pm, {'pdf_id': records['older']['pdf_id'], 'path': str(work / 'WorldEnergyOutlook2025.pdf')})
        assert 'This is not the PDF this work read' in str(caught.value) and records['newer']['pdf_id'] in str(caught.value)
        saved = await engine._pdf_save(run, pm, {'pdf_id': records['newer']['pdf_id'], 'path': str(work / 'WorldEnergyOutlook2025.pdf')})
        assert (work / 'WorldEnergyOutlook2025.pdf').read_bytes() == newer and saved['operation'] == 'created'
        # The same file under a second name: not saved again.
        with pytest.raises(ValueError, match='already saved in this work as .*WorldEnergyOutlook2025.pdf'):
            await engine._pdf_save(run, pm, {'pdf_id': records['newer']['pdf_id'], 'path': str(work / 'WorldEnergyOutlook2025_latest.pdf')})
        assert not (work / 'WorldEnergyOutlook2025_latest.pdf').exists()
        # Asked for a second time, the other copy is saved: the choice is the coordinator's.
        await engine._pdf_save(run, pm, {'pdf_id': records['older']['pdf_id'], 'path': str(work / 'older.pdf')})
        # Read by its path, the saved file is what it is: the PDF downloaded in this work.
        by_path = await engine._pdf_from_file(run, {'path': str(work / 'WorldEnergyOutlook2025.pdf'), 'first_page': 2})
        assert 'the PDF this work downloaded from https://files.iea.org/newer/WorldEnergyOutlook2025.pdf' in by_path['origin']
        assert 'was not downloaded' not in by_path['origin']
        assert run['_pdf_sources'] == {'https://files.iea.org/newer/WorldEnergyOutlook2025.pdf': 'downloaded'}
        # A file the work did not download stays what it was.
        (work / 'own.pdf').write_bytes(make_pdf(['A file of the human.'], title='Own'))
        own = await engine._pdf_from_file(run, {'path': str(work / 'own.pdf'), 'first_page': 1})
        assert 'it was not downloaded in this work' in own['origin']
    finally:
        await engine.close()


def test_a_request_to_keep_the_pdf_is_recognised_without_a_file_name():
    from workbench.verification import asks_to_keep_pdf
    for text in ('要約を report.docx に保存し、ダウンロードした PDF も同じフォルダーに保存してください', 'PDF も保存して',
                 '取得した PDF を weo フォルダーに保存', 'PDF を保存してください', 'PDFファイル自体も残しておいて',
                 'Summarise it and save the PDF in the same folder', 'Please keep a copy of the downloaded PDF'):
        assert asks_to_keep_pdf(text), text
    for text in ('PDF を読んで要約を report.docx に保存して', 'WEO の PDF をダウンロードして読み、要約を summary.md に書いて',
                 'PDF を参照して表を作り、xlsx に保存', 'Save the summary of the PDF as report.docx', 'https://example.org/PDFを保存', None):
        assert not asks_to_keep_pdf(text), text


async def test_keeping_the_downloaded_pdf_is_a_deliverable_even_without_a_name(tmp_path):
    """Real-machine case: "…and save the downloaded PDF in the same folder". No PDF was saved, the document said
    "obtained and saved in this work", and the run was done."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0,
                              task='IEA の報告書の PDF を読んで要約を summary.docx に保存し、ダウンロードした PDF も同じフォルダーに保存してください')
        assert run['output_check']['expected'] == ['summary.docx', 'ダウンロードした PDF（保存する名前は任意）']
        pm.pending.clear()
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing',
                                                           'paragraphs': ['要約。PDF は本作業で取得・保存した。']})
        record = engine.pdf_library.put(REPORT, 'https://files.iea.org/WorldEnergyOutlook2025.pdf')
        class Web:
            pdf_ids = {record['pdf_id']: record}
        run['_web'] = Web()
        await engine._pdf_read(run, pm, {'pdf_id': record['pdf_id'], 'first_page': 1})
        # The coordinator is sent back with the tool and the id; a second completion goes through as what it is.
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert first['code'] == 'outputs_missing' and 'ダウンロードした PDF（保存する名前は任意） (save with pdf_save)' in first['error']
        assert record['pdf_id'] in first['error']
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert 'ダウンロードした PDF は、フォルダーには保存されていません（pdf_save の記録がありません）' in done['summary']
        pm.status = 'done'
        engine._run_status(run)
        assert run['status'] == 'incomplete' and run['output_check']['missing'] == ['ダウンロードした PDF（保存する名前は任意）']
        # Saved under any name: the deliverable is there, and the result names the file.
        await engine.execute_tool(run, pm, 'pdf_save', {'pdf_id': record['pdf_id'], 'path': str(work / 'WEO2025.pdf')})
        engine._run_status(run)
        assert run['status'] == 'done' and run['output_check']['missing'] == []
        assert 'フォルダーに保存した PDF: ' in engine._pdf_footer(run) and 'WEO2025.pdf' in engine._pdf_footer(run)
    finally:
        await engine.close()


def test_which_words_are_looked_up_and_a_range_of_pages():
    from workbench.verification import page_quotes, quotable
    # Real-machine case: 26 of 40 "quotations" did not match; many were terms of one to three words.
    for words in ('Renewables', 'already in place', 'Total final consumption', '再生可能エネルギー'):
        assert not quotable(words), words
    for words in ('around 37 800 TWh', '5,600 bcm by 2050', 'Coal use starts to decline globally', '37,800 TWh', '世界の電力需要は 2035 年までに増える'):
        assert quotable(words), words
    assert page_quotes({'paragraphs': ['「Renewables」（p.12）', '「already in place」 p. 40', '"around 37 800 TWh" (p. 423)',
                                       '“solar and wind lead the growth in supply” (pp. 17–19)', '「demand rises steadily to 2050」（p.5-7）']}) == [
        (423, 'around 37 800 TWh'), ((17, 19), 'solar and wind lead the growth in supply'), ((5, 7), 'demand rises steadily to 2050')]


async def test_pages_are_corrected_in_tables_slides_and_text_files_and_a_range_matches_any_page_in_it(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        pdf = make_pdf(['Overview of the outlook.', 'Supply. Solar and wind lead the growth in supply to 2035.',
                        'Demand. Electricity demand reaches 37 800 TWh by 2035.', 'Annex.'], title='Outlook (test)')
        (work / 'outlook.pdf').write_bytes(pdf)
        run, pm = await start(engine, max_workers=0, task='outlook.pdf を読んで要約を summary.docx と slides.pptx と notes.md に保存して')
        pm.pending.clear()
        await engine.execute_tool(run, pm, 'pdf_read', {'path': str(work / 'outlook.pdf'), 'first_page': 1, 'last_page': 1})
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing', 'paragraphs': [
            '供給: 「solar and wind lead the growth in supply」（pp. 1-3）'],                                   # page 2: inside the range
            'tables': [[['指標', '値', '出典ページ', '原文の引用'], ['電力需要', '37,800 TWh', 'p.4', 'Electricity demand reaches 37 800 TWh by 2035']]]})
        await engine.execute_tool(run, pm, 'pptx_write', {'path': str(work / 'slides.pptx'), 'expected_sha256': 'missing', 'slides': [
            {'title': '需要', 'body': ['電力需要は 37,800 TWh（p. 1 「Electricity demand reaches 37 800 TWh by 2035」）', '供給は別紙']}]})
        await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'notes.md'), 'expected_sha256': 'missing',
                                                           'text': '# メモ\n- 電力: "Electricity demand reaches 37 800 TWh" (p. 2)\n- 供給は p. 2 を参照\n'})
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        # Every wrong page stood for a passage on one page: all are written by the application, nothing is sent back.
        assert done.get('ok') is not False and '引用 4 件' in done['summary'] and '一致 4 件、不一致 0 件' in done['summary']
        for line in ('- p.4→p.3 に訂正: 「Electricity demand reaches 37 800 TWh by 2035」（summary.docx）',
                     '- p.1→p.3 に訂正: 「Electricity demand reaches 37 800 TWh by 2035」（slides.pptx）',
                     '- p.2→p.3 に訂正: 「Electricity demand reaches 37 800 TWh」（notes.md）'):
            assert line in done['summary'], line
        document = Document(str(work / 'summary.docx'))
        assert [cell.text for cell in document.tables[0].rows[1].cells] == ['電力需要', '37,800 TWh', 'p.3', 'Electricity demand reaches 37 800 TWh by 2035']
        assert document.paragraphs[0].text == '供給: 「solar and wind lead the growth in supply」（pp. 1-3）'   # the range was right
        texts = [paragraph.text for shape in Presentation(str(work / 'slides.pptx')).slides[0].shapes if shape.has_text_frame
                 for paragraph in shape.text_frame.paragraphs]
        assert '電力需要は 37,800 TWh（p. 3 「Electricity demand reaches 37 800 TWh by 2035」）' in texts and '供給は別紙' in texts
        assert (work / 'notes.md').read_text(encoding='utf-8') == (
            '# メモ\n- 電力: "Electricity demand reaches 37 800 TWh" (p. 3)\n- 供給は p. 2 を参照\n')
        assert [receipt['tool'] for receipt in list(pm.output_receipts)[-3:]] == ['page_reference_fix'] * 3
    finally:
        await engine.close()


async def test_a_pdf_id_written_longer_or_as_the_hash_is_that_pdf_and_a_wrong_one_lists_the_ids(tmp_path):
    """Real-machine case: web_fetch returned "pdf-23d1302fbff692820d3a6a4e" and the file's sha256 beside it; "pdf-" plus
    the whole hash was passed six times and refused each time, and a page snapshot id was passed as well."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='報告書の PDF を読んで')
        record = engine.pdf_library.put(REPORT, 'https://www.imf.org/-/media/files/weo/2026/october/english/text.pdf')
        other = engine.pdf_library.put(make_pdf(['Supplement.'], title='S002'), 'https://www.elibrary.imf.org/S002.pdf')
        class Web:
            pdf_ids = {record['pdf_id']: {**record, 'pages': 2}, other['pdf_id']: {**other, 'pages': 1}}
        run['_web'] = Web()
        for given in (record['pdf_id'], 'pdf-' + record['sha256'], record['sha256'], record['pdf_id'][:14], ' ' + record['pdf_id'] + ' '):
            result = await engine._pdf_read(run, pm, {'pdf_id': given, 'first_page': 1})
            assert result['pdf_id'] == record['pdf_id'] and result['pages'] == 2, given
        # The hash is returned under a name that cannot be taken for an id.
        assert result['content_sha256'] == record['sha256'] and 'sha256' not in result
        for given in ('web-0123456789abcdef', 'pdf-ffffffffffffffffffffffff', 'pdf-', 42):
            with pytest.raises(ValueError) as caught:
                await engine._pdf_read(run, pm, {'pdf_id': given, 'first_page': 1})
            text = str(caught.value)
            assert 'The PDFs of this work: ' in text and f"{record['pdf_id']} (https://www.imf.org/-/media/files/weo/2026/october/english/text.pdf, 2 pages)" in text
            assert other['pdf_id'] in text and 'exactly as written' in text
        with pytest.raises(ValueError, match='page snapshot'):
            await engine._pdf_read(run, pm, {'pdf_id': 'web-0123456789abcdef', 'first_page': 1})
        saved = await engine._pdf_save(run, pm, {'pdf_id': 'pdf-' + record['sha256'], 'path': str(work / 'weo.pdf')})
        assert (work / 'weo.pdf').read_bytes() == REPORT and saved['operation'] == 'created'
        run['_web'] = type('Web', (), {'pdf_ids': {}})()
        with pytest.raises(ValueError, match='This work has downloaded no PDF yet'):
            await engine._pdf_read(run, pm, {'pdf_id': record['pdf_id'], 'first_page': 1})
    finally:
        await engine.close()


def test_a_request_for_a_table_is_recognised_and_an_address_loses_its_session_values():
    from workbench.verification import asks_for_table
    from workbench.webtools import citable_url
    for text in ('主要な数値は表にする', '結果を表にまとめて report.docx に保存', '国別の比較表を付けてください', '数値は表形式で',
                 'Put the main figures in a table', 'Summarise it with a comparison table'):
        assert asks_for_table(text), text
    for text in ('表紙を付けて発表用にまとめて', '代表で示す値を書いて', '年表示は西暦で', 'report.docx に保存して', None):
        assert not asks_for_table(text), text
    state = 'H4sI' + 'A' * 300
    assert citable_url(f'https://www.elibrary.imf.org/downloadpdf/book/9798400/CH001.pdf?t:state:client={state}&page=2') == (
        'https://www.elibrary.imf.org/downloadpdf/book/9798400/CH001.pdf?page=2')
    assert citable_url('https://example.org/doc;jsessionid=ABC123?id=7&PHPSESSID=xyz') == 'https://example.org/doc?id=7'
    for same in ('https://www.imf.org/en/publications/weo', 'https://api.worldbank.org/v2/country/JPN?format=json&date=2020:2024',
                 'https://example.org/search?q=world+energy+outlook'):
        assert citable_url(same) == same


async def test_a_document_without_the_table_the_request_asks_for_is_sent_back_once(tmp_path):
    """Real-machine case: "the main figures in a table" was asked for; the document had no table, and the run was done."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='要約を summary.docx に保存して。主要な数値は表にする。')
        pm.pending.clear()
        saved = await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing',
                                                                  'paragraphs': ['需要は 654 EJ、供給は 744 EJ。']})
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert first['ok'] is False and first['code'] == 'table_missing'
        assert 'summary.docx' in first['error'] and 'docx_edit with append_table' in first['error']
        # Said once; a document that still has no table is named in the result.
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert '依頼文は数値を表にするよう求めていますが、次の文書に表はありません' in done['summary']
        # With a table, nothing is said.
        await engine.execute_tool(run, pm, 'docx_edit', {'path': str(work / 'summary.docx'), 'expected_sha256': saved['sha256'],
                                                          'operations': [{'type': 'append_table', 'rows': [['指標', '値'], ['需要', '654 EJ']]}]})
        await engine._tables_check(run)
        assert run['_tables_missing'] == [] and engine._tables_footer(run) == ''
    finally:
        await engine.close()


async def test_a_worker_that_reports_without_its_assigned_file_or_any_tool_is_sent_back_once(tmp_path):
    """Real-machine case: the worker that was to make the slides ended without one tool call and was "done"; the run
    had no slides."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=3, task='要約を summary.docx に保存し、スライドを slides.pptx に保存して')
        designer = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'designer', 'task': '要約をもとに slides.pptx を 16:9 で作成する。'}))['agent_id']]
        helper = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'checker', 'task': '数値を確認する。'}))['agent_id']]
        writer = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {
            'profile_id': 'local', 'role': 'writer', 'task': '要約を summary.docx に保存する。'}))['agent_id']]
        for agent in (pm, designer, helper, writer):
            agent.pending.clear()
        # The file its assignment names was not saved: said once, with the tool that makes it.
        first = await engine.execute_tool(run, designer, 'finish_work', {'summary': 'スライドの構成を考えました。'})
        assert first['ok'] is False and first['code'] == 'assignment_not_done'
        assert 'Your assignment asks you to produce: slides.pptx (save with pptx_write)' in first['error']
        assert (await engine.execute_tool(run, designer, 'finish_work', {'summary': '作れませんでした。'})).get('ok') is not False
        # No file in its assignment, but no tool used at all while requested files are missing: said once as well.
        assert 'without having used any tool in this assignment' in engine._assignment_undone(run, helper)
        assert engine._assignment_undone(run, helper) is None
        # A worker that did its part reports without being asked again.
        await engine.execute_tool(run, writer, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing',
                                                               'paragraphs': ['要約']})
        assert engine._assignment_undone(run, writer) is None and engine._assignment_undone(run, pm) is None
    finally:
        await engine.close()


async def test_a_completion_that_never_read_the_largest_pdf_of_the_work_is_sent_back_once(tmp_path):
    """Real-machine case: the full report (124 pages) arrived at second 281 of 312; the document had been written
    before from a two-page summary, and the report was never opened."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0, task='報告書の PDF を読んで要約を summary.docx に保存して')
        pm.pending.clear()
        summary = engine.pdf_library.put(make_pdf(['Executive summary.', 'Foreword.'], title='S001'), 'https://www.elibrary.imf.org/S001.pdf')
        full = engine.pdf_library.put(make_pdf([f'Chapter text, page {number}.' for number in range(1, 13)], title='Full report'),
                                      'https://www.imf.org/-/media/files/publications/weo/2026/october/english/text.pdf')
        class Web:
            pdf_ids = {summary['pdf_id']: {**summary, 'pages': 2}, full['pdf_id']: {**full, 'pages': 12}}
        run['_web'] = Web()
        await engine._pdf_read(run, pm, {'pdf_id': summary['pdf_id'], 'first_page': 1})
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'summary.docx'), 'expected_sha256': 'missing',
                                                           'paragraphs': ['要約（Executive Summary による）']})
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert first['ok'] is False and first['code'] == 'main_pdf_unread'
        for words in ('october/english/text.pdf (12 pages', f"pdf_id {full['pdf_id']}", 'the largest PDF of the work, and no page of it was read',
                      'pdf_search for the main figures'):
            assert words in first['error'], words
        # Said once; left unread, the result says so.
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '保存しました。'})
        assert '（12 ページ）は、1 ページも読まれていません' in done['summary']
        # Read: nothing is said. A copy nearly as long that was read counts as well.
        await engine._pdf_read(run, pm, {'pdf_id': full['pdf_id'], 'first_page': 3})
        assert engine._main_pdf_unread(run) is None and engine._main_pdf_footer(run) == ''
        other = engine.pdf_library.put(make_pdf([f'Other copy, page {number}.' for number in range(1, 14)], title='Copy'), 'https://files.example/copy.pdf')
        run['_web'].pdf_ids[other['pdf_id']] = {**other, 'pages': 13}
        assert engine._main_pdf_unread(run) is None
    finally:
        await engine.close()


# The request of a real run, as it was typed (the user's folder name is replaced). The slides it asks for were
# not made, and the run was "done": no word of making stands in the lines that name the two files.
NUMBERED_REQUEST = '''IMF の World Economic Outlook（WEO）について、今年（2026年）の最新号の報告書 PDF を、公式の配布元からダウンロードして読み込んでください。PDF に書かれている内容をもとに、次の2つを作成して提出してください。

1. 要約レポート（weo2026_summary.docx）
   - 全体の要旨、世界経済の見通し（成長率・インフレ）、主要国・地域の見通し、リスク、政策提言を日本語でまとめる。
   - 主要な数値や主張には、PDF のページ番号と原文の短い引用を付ける。
   - 世界・主要国の成長率見通しは表にする。
   - PDF から読めなかった部分は推測で補わず、「未確認」と明記する。

2. 説明スライド（weo2026_slides.pptx）
   - 要約レポートの内容を説明する 8〜10 枚程度のスライドにする。
   - ファッショナブルでモダンなデザインにする（16:9、統一した配色、余白を活かしたレイアウト、大きな見出し、要点は簡潔に）。
   - 成長率見通しはグラフで見せる。

保存先は C:\\Users\\user\\Documents\\AgentWorkbenchOutputs\\weo2026l フォルダー。完了する前に、数値が PDF と一致しているかを pdf_search で確認してください。
'''


def test_files_named_in_a_numbered_list_after_a_sentence_of_making_are_outputs():
    from workbench.verification import file_roles, named_files, output_names
    assert named_files(NUMBERED_REQUEST) == ['weo2026_summary.docx', 'weo2026_slides.pptx']
    assert output_names(NUMBERED_REQUEST) == {'weo2026_summary.docx', 'weo2026_slides.pptx'}
    # Other lists of things to produce, with other markers.
    assert output_names('成果物:\n- a.docx\n- b.pptx') == {'a.docx', 'b.pptx'}
    assert output_names('Please produce the following:\n1. report.docx\n2. slides.pptx') == {'report.docx', 'slides.pptx'}
    assert output_names('次の2つを作ってください。\n(1) a.docx\n(2) b.pptx\n\n参考: old.docx を読んでおくこと') == {'a.docx', 'b.pptx'}
    # A list of things to read stays one, and prose after a list ends it.
    assert output_names('次のファイルを読んで、要約を作成してください:\n- a.xlsx\n- b.docx') == set()
    assert output_names('参考資料:\n- a.pdf\n- b.xlsx') == set()
    assert output_names('以下を参照して summary.md を作成:\n- data.csv') == {'summary.md'}
    assert file_roles('次の2つを作成:\n1. a.docx\n2. b.pptx\n\nなお c.xlsx を読んで数値を確かめること') == {
        'a.docx': 'out', 'b.pptx': 'out', 'c.xlsx': 'in'}


async def test_the_numbered_request_is_checked_although_older_files_of_those_names_exist(tmp_path):
    """Real-machine case (three runs): the request above, with the output of earlier runs under the same names in the
    folders beside it. Nothing was expected, so nothing was missed: no send-back, no note, "done"."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        for folder in ('weo2026j', 'weo2026k'):
            (work / folder).mkdir()
            for name in ('weo2026_summary.docx', 'weo2026_slides.pptx'):
                (work / folder / name).write_bytes(b'an earlier run')
        run, pm = await start(engine, max_workers=0, task=NUMBERED_REQUEST)
        assert list(run['_expected_outputs'].values()) == ['weo2026_summary.docx', 'weo2026_slides.pptx']
        assert run['output_check']['missing'] == ['weo2026_summary.docx', 'weo2026_slides.pptx']
        pm.pending.clear()
        (work / 'weo2026l').mkdir()
        await engine.execute_tool(run, pm, 'docx_write', {'path': str(work / 'weo2026l' / 'weo2026_summary.docx'),
                                                           'expected_sha256': 'missing', 'paragraphs': ['要約'],
                                                           'tables': [[['対象', '2026'], ['世界', '3.1']]]})
        first = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'スライド作成は未完了のため、次工程で作成が必要です。'})
        assert first['code'] == 'outputs_missing' and 'weo2026_slides.pptx (save with pptx_write)' in first['error']
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'スライド作成は未完了のため、次工程で作成が必要です。'})
        assert '依頼された成果物は作られていません' in done['summary'] and 'weo2026_slides.pptx' in done['summary']
        pm.status = 'done'
        engine._run_status(run)
        assert run['status'] == 'incomplete' and run['output_check']['missing'] == ['weo2026_slides.pptx']
    finally:
        await engine.close()


async def test_a_stated_destination_folder_decides_whether_a_named_file_already_exists(tmp_path):
    """Where the request says where the files go, a file of the same name in another folder is not that file."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        (work / 'old').mkdir()
        (work / 'new').mkdir()
        for name in ('report.docx', 'slides.pptx', 'figures.xlsx'):
            (work / 'old' / name).write_bytes(b'an earlier run')
        (work / 'new' / 'slides.pptx').write_bytes(b'already there')
        # No word of making near the names: the stated folder decides.
        run, pm = await start(engine, max_workers=0,
                              task=f'レポート: report.docx\nスライド: slides.pptx\nfigures.xlsx を読んで数値を確かめる。\n保存先は {work / "new"} フォルダー。')
        assert engine._stated_folders(run, run['task']) == [work / 'new']
        # report.docx is not in the stated folder: it is asked for. slides.pptx is there, figures.xlsx is read.
        assert list(run['_expected_outputs'].values()) == ['report.docx']
        # A folder named by its name alone, a file's full path, and a folder outside the permitted ones.
        assert engine._stated_folders(run, 'new フォルダーに保存して') == [work / 'new']
        assert engine._stated_folders(run, f'{work / "out" / "report.docx"} に保存') == [work / 'out']
        assert engine._stated_folders(run, '保存先は C:\\Users\\user\\Documents\\out フォルダー、または /etc/out') == []
    finally:
        await engine.close()
