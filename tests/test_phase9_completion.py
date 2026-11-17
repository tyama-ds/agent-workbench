"""Phase 9: runs that end when the work is done, cited URLs the run has seen,
and fewer questions that wait for a person."""
import asyncio

import pytest

from workbench import sources
from test_engine import ScriptClient, configured, reply, settled, start


async def quiet(engine, steps=400):
    for _ in range(steps):
        await asyncio.sleep(.01)
        if not any(agent.task and not agent.task.done() for agent in engine.agents.values()):
            await asyncio.sleep(.02)
            if not any(agent.task and not agent.task.done() for agent in engine.agents.values()):
                return
    raise AssertionError('engine did not become quiet')


# --- P1: the run ends -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_plain_text_final_answer_ends_the_run_when_workers_only_wait(tmp_path):
    """Real-machine case: the PM saved the file, wrote 「完了しました」 without
    finish_work, and a worker stayed in wait_for_message for 20 minutes."""
    class Team:
        pm_calls = 0

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            if '"assigned_role": "調査"' in system:
                return reply(calls=[('finish_work', {'summary': '値を調べました。'})])
            if '"assigned_role": "品質確認"' in system:
                return reply(calls=[('wait_for_message', {})])  # waits for a request that never comes
            self.pm_calls += 1
            if self.pm_calls == 1:
                return reply(calls=[('spawn_worker', {'role': '調査', 'task': '値を調べる', 'profile_id': 'local'}),
                                    ('spawn_worker', {'role': '品質確認', 'task': '依頼が届いたら確認する', 'profile_id': 'local'})])
            return reply('統計を stats.xlsx に保存し、読み直して確認しました。完了しました。')  # prose, no finish_work

    engine, work = configured(tmp_path, Team())
    try:
        run, pm = await start(engine)
        await quiet(engine)
        workers = [engine.agents[i] for i in run['agent_ids'] if engine.agents[i].parent_id]
        assert run['status'] == 'done' and pm.status == 'done', (run['status'], pm.status, [w.status for w in workers])
        assert [worker.status for worker in workers] == ['done', 'done']
        assert not workers[1].waiting_for_message
        assert pm.results[-1]['source'] == 'assistant_response' and '完了しました' in pm.results[-1]['text']
        assert any(row['kind'] == 'team_settled' for row in engine.events)
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_worker_that_starts_waiting_after_the_final_answer_does_not_hold_the_run(tmp_path):
    release = asyncio.Event()

    class Team:
        pm_calls = 0

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            if '"assigned_role"' in system:
                await release.wait()
                return reply(calls=[('wait_for_message', {})])
            self.pm_calls += 1
            if self.pm_calls == 1:
                return reply(calls=[('spawn_worker', {'role': '確認', 'task': '確認する', 'profile_id': 'local'})])
            return reply('結果を保存しました。完了です。')

    engine, work = configured(tmp_path, Team())
    try:
        run, pm = await start(engine)
        for _ in range(100):
            if pm.status == 'idle' and pm.results:
                break
            await asyncio.sleep(.01)
        assert pm.status == 'idle' and run['status'] == 'running', 'the worker is still working'
        release.set()
        await quiet(engine)
        assert run['status'] == 'done' and pm.status == 'done'
    finally:
        await engine.close()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_pm_waiting_for_reports_is_told_when_every_worker_only_waits(tmp_path):
    class Team:
        pm_messages = []

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            if '"assigned_role"' in system:
                return reply(calls=[('wait_for_message', {})])
            self.pm_messages.append(messages[-1]['content'])
            if len(self.pm_messages) == 1:
                return reply(calls=[('spawn_worker', {'role': '確認', 'task': '依頼を待つ', 'profile_id': 'local'}),
                                    ('wait_for_workers', {})])
            return reply(calls=[('finish_work', {'summary': '作業者は使わず、自分でまとめました。'})])

    client = Team()
    engine, work = configured(tmp_path, client)
    try:
        run, pm = await start(engine)
        await quiet(engine)
        assert any('チームの全員が待機していて' in str(message) and '連絡待ち' in str(message) for message in client.pm_messages)
        assert run['status'] == 'done' and pm.status == 'done'
    finally:
        await engine.close()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_pm_and_worker_waiting_for_each_other_after_a_correction_are_woken(tmp_path):
    """Real-machine case (statistics task): the PM asked for a correction and
    waited; the worker read the request and waited too; the run stayed
    "waiting" for 15 minutes although the PM already had what it needed."""
    class Team:
        pm_turns, worker_calls, refused = [], 0, []

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            last = messages[-1]['content']
            if '"assigned_role"' in system:
                self.worker_calls += 1
                if self.worker_calls == 1:
                    return reply(calls=[('finish_work', {'summary': '人口: 日本 1.2億（年が不明）'})])
                if 'ok": false' in str(last) or '待機できません' in str(last):
                    self.refused.append(str(last))
                return reply(calls=[('wait_for_message', {})])  # does not act on the correction
            self.pm_turns.append(str(last))
            if len(self.pm_turns) == 1:
                return reply(calls=[('spawn_worker', {'role': '人口調査', 'task': '人口を調べる', 'profile_id': 'local'}),
                                    ('wait_for_workers', {})])
            if 'チームの全員が待機していて' in str(last):
                return reply(calls=[('finish_work', {'summary': '手元の値で表を仕上げました。'})])
            if 'worker_completed' in str(last):
                worker = next(a for a in engine.agents.values() if a.parent_id)
                return reply(calls=[('review_worker_report', {'worker_id': worker.id, 'result_revision': worker.result_revision,
                                                              'decision': 'revise', 'feedback': '年を明記してください'}),
                                    ('wait_for_message', {})])
            return reply(calls=[('wait_for_message', {})])

    client = Team()
    engine, work = configured(tmp_path, client)
    try:
        run, pm = await start(engine)
        await quiet(engine)
        assert client.refused, 'a worker that received a correction is told to act instead of waiting'
        assert any('チームの全員が待機していて' in turn and '人口調査' in turn for turn in client.pm_turns)
        assert run['status'] == 'done' and pm.status == 'done', (run['status'], pm.status, pm.last_error)
        assert any(row['kind'] == 'stall_notice' for row in engine.events)
    finally:
        await engine.close()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_team_that_keeps_waiting_is_stopped_with_a_reason_after_three_notices(tmp_path):
    class Team:
        notices = 0

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            if '"assigned_role"' in system:
                return reply(calls=[('wait_for_message', {})])
            if 'チームの全員が待機していて' in str(messages[-1]['content']):
                self.notices += 1
            if not any(row.get('role') == 'assistant' for row in messages):
                return reply(calls=[('spawn_worker', {'role': '確認', 'task': '待つ', 'profile_id': 'local'}),
                                    ('wait_for_message', {})])
            return reply(calls=[('wait_for_message', {})])

    client = Team()
    engine, work = configured(tmp_path, client)
    try:
        run, pm = await start(engine)
        await quiet(engine)
        assert client.notices == 3 and pm.status == 'error' and '行き詰まり' in pm.last_error
        assert 'これが最後の通知です' in pm.conversation[-3]['content'] or any(
            'これが最後の通知です' in str(row.get('content')) for row in pm.conversation)
        assert run['status'] == 'waiting'
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_finish_work_is_not_blocked_by_idle_or_failed_workers_but_waits_for_active_ones(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        waiting = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'a', 'task': 't', 'profile_id': 'local'}))['agent_id']]
        failed = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'b', 'task': 't', 'profile_id': 'local'}))['agent_id']]
        waiting.pending.clear(); waiting.turns = 1; waiting.status = 'idle'; waiting.waiting_for_message = True
        failed.pending.clear(); failed.status = 'error'; failed.last_error = 'boom'
        pm.pending.clear()
        # A worker that is still working keeps the report back.
        waiting.status = 'working'
        with pytest.raises(ValueError, match='未完了の作業者'):
            await engine.execute_tool(run, pm, 'finish_work', {'summary': 'early'})
        assert failed.status == 'error', 'nothing is closed while someone is active'
        waiting.status = 'idle'
        # A worker waiting for the human also keeps it back.
        waiting.question = '確認してください'
        with pytest.raises(ValueError, match='未完了の作業者'):
            await engine.execute_tool(run, pm, 'finish_work', {'summary': 'early'})
        waiting.question = ''
        result = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'まとめました。'})
        assert result['ok'] and (waiting.status, failed.status) == ('done', 'stopped')
        assert failed.last_error == 'boom', 'the failure stays visible on the stopped worker'
    finally:
        await engine.close()


# --- P5: cited URLs -------------------------------------------------------------------

def test_url_extraction_exemptions_and_placeholders():
    assert sources.extract('見てください: https://Example.JP/a/b/?q=1#frag。次') == {'https://example.jp/a/b?q=1'}
    assert sources.extract({'t': '（https://a.test/x）、https://b.test/y.'}) == {'https://a.test/x', 'https://b.test/y'}
    assert sources.placeholder('https://www.soumu.go.jp/main_content/000000000000000000.pdf')
    assert sources.placeholder('https://site.jp/xxxx') and not sources.placeholder('https://www.soumu.go.jp/main_content/000912345.pdf')
    assert sources.exempt('http://localhost:8000/x') and sources.exempt('http://127.0.0.1/x') and sources.exempt('https://example.com/')
    known = {'https://www.meti.go.jp/policy/ai.html'}
    assert sources.unknown({'https://www.meti.go.jp', 'https://www.meti.go.jp/policy/ai.html', 'https://www.cao.go.jp/x'}, known) == [
        'https://www.cao.go.jp/x'], 'a site root counts as seen when a page of that site was'


@pytest.mark.asyncio
async def test_a_document_citing_unseen_urls_is_refused_once_and_reported(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='生成AI規制の動向を https://www.kantei.go.jp/ai を参考にまとめて', max_workers=0)
        assert 'cite only URLs' in engine._policy(run, pm)
        target = str(work / 'report.md')
        fake = 'https://www.soumu.go.jp/main_content/000000000000000000.pdf'
        with pytest.raises(ValueError, match='実在しない形'):
            await engine.execute_tool(run, pm, 'write_text', {'path': target, 'text': f'出典: {fake}（未確認）', 'expected_sha256': 'missing'})
        with pytest.raises(ValueError, match='実在しない形'):
            await engine.execute_tool(run, pm, 'write_text', {'path': target, 'text': f'出典: {fake}', 'expected_sha256': 'missing'})
        guessed = '出典: https://www.meti.go.jp/policy/ai-guideline.html'
        with pytest.raises(ValueError, match='確認されていません'):
            await engine.execute_tool(run, pm, 'write_text', {'path': target, 'text': guessed, 'expected_sha256': 'missing'})
        assert not (work / 'report.md').exists()
        # URLs the human gave or a tool returned are fine.
        engine._urls_seen(run, {'results': [{'url': 'https://www.meti.go.jp/policy/ai-guideline.html'}]})
        saved = await engine.execute_tool(run, pm, 'write_text', {
            'path': target, 'text': guessed + '\n参考: https://www.kantei.go.jp/ai', 'expected_sha256': 'missing'})
        assert saved['operation'] == 'created' and not run['_unverified_urls']
        # A second attempt with a still-unseen URL is saved, and the human is told.
        other = str(work / 'notes.md')
        with pytest.raises(ValueError, match='確認されていません'):
            await engine.execute_tool(run, pm, 'write_text', {'path': other, 'text': 'https://unseen.jp/page', 'expected_sha256': 'missing'})
        await engine.execute_tool(run, pm, 'write_text', {'path': other, 'text': 'https://unseen.jp/page', 'expected_sha256': 'missing'})
        pm.pending.clear()
        # The cited sources are sent back once for a check (see the next test), then the result is accepted.
        review = await engine.execute_tool(run, pm, 'finish_work', {'summary': '報告書を保存しました。'})
        assert review['ok'] is False and review['code'] == 'sources_review'
        result = await engine.execute_tool(run, pm, 'finish_work', {'summary': '報告書を保存しました。'})
        assert '【アプリの確認】' in result['summary'] and 'https://unseen.jp/page' in result['summary'] and 'notes.md' in result['summary']
        # Source code is not a citation.
        await engine.execute_tool(run, pm, 'write_text', {
            'path': str(work / 'client.py'), 'text': 'URL = "https://api.unseen.jp/v1"', 'expected_sha256': 'missing'})
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_cited_sources_are_checked_once_against_what_was_retrieved(tmp_path):
    """Real-machine case: the only page that could be fetched was about another
    subject, and it was cited as the source of the report."""
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='生成AI規制の動向を https://www.kantei.go.jp/ai も参考にまとめて', max_workers=0)
        assert 'Cite a page only for what its retrieved text states' in engine._policy(run, pm)
        fetched = 'https://www.meti.go.jp/press/2024/04/20240419003/20240419003.html'
        engine._pages_note(run, 'web_fetch', {'url': fetched}, engine._urls_seen(run, {
            'url': fetched, 'text': '令和6年度 中小企業者に関する国等の契約の基本方針\n\n  官公需についての方針を閣議決定しました。' + 'あ' * 500}))
        listed = 'https://digital-strategy.ec.europa.eu/ai-act-overview'
        engine._pages_note(run, 'web_search', {'query': 'AI 規制'}, engine._urls_seen(run, {
            'results': [{'title': 'EU AI Act の概要', 'url': listed, 'snippet': '...'}, {'title': 'ignored', 'url': fetched}]}))
        assert run['_pages'][fetched][0] == 'fetched'  # a search hit does not replace the page's own text
        text = f'# 生成AI規制の動向\n出典: {fetched}\n参考: {listed}\n依頼の資料: https://www.kantei.go.jp/ai\n'
        await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'report.md'), 'text': text, 'expected_sha256': 'missing'})
        await engine.execute_tool(run, pm, 'write_text', {  # source code is not a document
            'path': str(work / 'client.py'), 'text': f'URL = "{fetched}"', 'expected_sha256': 'missing'})
        pm.pending.clear()
        review = await engine.execute_tool(run, pm, 'finish_work', {'summary': '報告書を保存しました。'})
        assert review['ok'] is False and review['code'] == 'sources_review'
        notice = review['error']
        assert 'report.md' in notice and 'client.py' not in notice and 'untrusted data' in notice
        assert f'{fetched} - fetched page begins: «令和6年度 中小企業者に関する国等の契約の基本方針 官公需についての方針' in notice
        assert f'{listed} - only seen as a search result titled «EU AI Act の概要»' in notice
        assert 'https://www.kantei.go.jp/ai - known from the request' in notice
        assert len(notice) < 2500  # page text is quoted briefly
        assert 'delete the citation from the file' in notice and 'Do not keep an unrelated page' in notice
        # The PM corrects the document; the list for the human follows the corrected file.
        saved = (work / 'report.md').read_bytes()
        import hashlib
        await engine.execute_tool(run, pm, 'write_text', {
            'path': str(work / 'report.md'), 'text': f'# 生成AI規制の動向\n参考: {listed}（本文は未確認）\n',
            'expected_sha256': hashlib.sha256(saved).hexdigest()})
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '出典を見直して保存しました。'})
        assert done['ok'] and '出典として書かれた URL' in done['summary'] and 'アプリでは確認していません' in done['summary']
        assert f'{listed} — 検索結果の題名「EU AI Act の概要」のみ（本文は未取得）' in done['summary']
        assert fetched not in done['summary'] and 'kantei' not in done['summary']
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_run_that_cites_nothing_is_not_sent_back(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='売上を集計して', max_workers=0)
        await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'memo.md'), 'text': '集計結果: 42', 'expected_sha256': 'missing'})
        pm.pending.clear()
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '集計しました。'})
        assert done['ok'] and '【アプリの確認】' not in done['summary']
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_without_web_tools_unseen_urls_are_saved_and_reported_only(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0)
        assert 'cite only URLs' not in engine._policy(run, pm)
        saved = await engine.execute_tool(run, pm, 'write_text', {
            'path': str(work / 'memo.md'), 'text': '参考: https://unseen.jp/a', 'expected_sha256': 'missing'})
        assert saved['operation'] == 'created' and list(run['_unverified_urls'].values())[0]['urls'] == ['https://unseen.jp/a']
    finally:
        await engine.close()


# --- P6: questions that wait for a person ---------------------------------------------

@pytest.mark.question_limits
@pytest.mark.asyncio
async def test_only_the_pm_may_block_on_a_human_and_only_twice(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        description = next(tool for tool in engine._model_tools(run, pm) if tool['name'] == 'ask_user')['description']
        assert 'A failed tool is not a permission matter' in description
        worker = engine.agents[(await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'w', 'task': 't', 'profile_id': 'local'}))['agent_id']]
        # A worker cannot stop the team for a human; with a recommendation it becomes a consultation.
        with pytest.raises(ValueError, match='PM に相談'):
            await engine.execute_tool(run, worker, 'ask_user', {'question': '検索が失敗します。許可をください', 'kind': 'permission'})
        downgraded = await engine.execute_tool(run, worker, 'ask_user', {
            'question': '検索が失敗します。どうしますか', 'kind': 'permission', 'recommendation': '既知の情報で進める'})
        assert downgraded['question_state']['kind'] == 'consultation' and downgraded['question_state']['deadline_at']
        assert '相談として扱います' in downgraded['note']
        # The PM may wait for a person twice in one run.
        for n in range(2):
            asked = await engine.execute_tool(run, pm, 'ask_user', {'question': f'方針{n}を決めてください'})
            assert asked['question_state']['deadline_at'] is None
        with pytest.raises(ValueError, match='2回まで'):
            await engine.execute_tool(run, pm, 'ask_user', {'question': '3回目です'})
        third = await engine.execute_tool(run, pm, 'ask_user', {'question': '3回目です', 'recommendation': 'Aで進める'})
        assert third['question_state']['kind'] == 'consultation'
    finally:
        await engine.close()


# --- smaller real-machine findings ----------------------------------------------------

@pytest.mark.asyncio
async def test_text_tools_name_the_right_tool_for_office_files(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, max_workers=0)
        with pytest.raises(ValueError, match=r'use xlsx_write for \.xlsx files'):
            await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'stats.xlsx'), 'text': 'a,b', 'expected_sha256': 'missing'})
        with pytest.raises(ValueError, match=r'docx_write'):
            await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'report.docx'), 'text': 'x', 'expected_sha256': 'missing'})
    finally:
        await engine.close()


def test_the_start_check_says_when_the_search_service_is_blocking_this_pc(tmp_path):
    from workbench.webtools import SEARCH_GUARD
    engine, work = configured(tmp_path, None)
    engine.settings.value['search']['enabled'] = True
    payload = {'task': '調べて', 'pm_profile': 'local', 'worker_profiles': ['local'], 'max_workers': 0}
    try:
        assert 'search_blocked_minutes' not in engine.preflight(payload)['web']
        SEARCH_GUARD.refused()
        assert engine.preflight(payload)['web']['search_blocked_minutes'] == 10
    finally:
        asyncio.run(engine.close())


# --- files the request names ----------------------------------------------------------

def test_file_names_in_a_request():
    from workbench.verification import named_files
    assert named_files('日本とドイツの人口を調べて stats.xlsx にまとめて') == ['stats.xlsx']
    assert named_files('結果をstats.xlsxに保存し、Report.MD も作って。stats.xlsx は1シートで') == ['stats.xlsx', 'Report.MD']
    assert named_files('「売上集計.xlsx」と C:\\work\\out\\result.docx を作成') == ['売上集計.xlsx', 'result.docx']
    assert named_files('https://example.com/data/file.csv を参考に、Node.js と v1.2.3 を調べて data.csv.bak は無視') == []


@pytest.mark.asyncio
async def test_finishing_without_a_file_the_request_names_is_sent_back_once_then_reported(tmp_path):
    """Real-machine case: the PM rejected a worker's report and finished without
    creating stats.xlsx; the run was done and the output folder was empty."""
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    (work / 'input.csv').write_text('国,人口\n', encoding='utf-8')
    try:
        run, pm = await start(engine, task='input.csv を読み、日本とドイツの人口を stats.xlsx と summary.md にまとめて', max_workers=0)
        # A named file that already exists is an input, not a deliverable.
        assert run['output_check'] == {'expected': ['stats.xlsx', 'summary.md'], 'missing': ['stats.xlsx', 'summary.md']}
        await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'summary.md'), 'text': '要約', 'expected_sha256': 'missing'})
        assert run['output_check']['missing'] == ['stats.xlsx']
        pm.pending.clear()
        refused = await engine.execute_tool(run, pm, 'finish_work', {'summary': '統計をまとめました。'})
        assert refused['ok'] is False and refused['code'] == 'outputs_missing'
        assert 'stats.xlsx' in refused['error'] and 'summary.md' not in refused['error'] and '未確認' in refused['error']
        assert 'stats.xlsx (save with xlsx_write)' in refused['error'] and 'python_execute' in refused['error']
        done = await engine.execute_tool(run, pm, 'finish_work', {'summary': '統計をまとめました。'})
        assert done['ok'] and '依頼された成果物は作られていません' in done['summary'] and 'stats.xlsx' in done['summary']
        assert run['output_check']['missing'] == ['stats.xlsx']
        # Asked again by the human, the check applies again; saving the file settles it.
        await engine.human_message(pm.id, 'stats.xlsx を作ってください')
        pm.pending.clear()
        again = await engine.execute_tool(run, pm, 'finish_work', {'summary': '作りました。'})
        assert again['ok'] is False and again['code'] == 'outputs_missing'
        await engine.execute_tool(run, pm, 'xlsx_write', {'path': str(work / 'stats.xlsx'), 'expected_sha256': 'missing',
                                                           'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': '83,491,249'}]})
        pm.pending.clear()
        final = await engine.execute_tool(run, pm, 'finish_work', {'summary': 'stats.xlsx を保存しました。'})
        assert final['ok'] and '【アプリの確認】' not in final['summary'] and run['output_check']['missing'] == []
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_plain_text_completion_without_the_named_file_is_sent_back_and_a_worker_save_counts(tmp_path):
    class Team:
        pm_calls = 0

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            if '"assigned_role": "集計"' in system:
                if not any(message.get('role') == 'tool' for message in messages):
                    return reply(calls=[('xlsx_write', {'path': 'stats.xlsx', 'expected_sha256': 'missing',
                                                        'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': 1}]})])
                return reply(calls=[('finish_work', {'summary': 'stats.xlsx を保存しました。'})])
            self.pm_calls += 1
            if self.pm_calls == 1:
                return reply('統計をまとめました。完了です。')  # nothing was saved
            if self.pm_calls == 2:
                assert any('no record that they were saved' in str(message.get('content')) for message in messages)
                return reply(calls=[('spawn_worker', {'role': '集計', 'task': 'stats.xlsx を作る', 'profile_id': 'local'})])
            return reply('集計担当が stats.xlsx を保存しました。')

    engine, work = configured(tmp_path, Team())
    try:
        run, pm = await start(engine, task='人口統計を stats.xlsx にまとめて')
        await quiet(engine)
        assert run['status'] == 'done', (run['status'], pm.status, pm.last_error)
        assert (work / 'stats.xlsx').exists() and run['output_check'] == {'expected': ['stats.xlsx'], 'missing': []}
        assert '【アプリの確認】' not in pm.results[-1]['text']
    finally:
        await engine.close()


# --- a coordinator nobody can wake ------------------------------------------------------

def sequence_team(after_refusal):
    """PM: two workers in sequence, never approves the first, and finishes early.
    The second worker therefore never starts. `after_refusal(team, last)` scripts the rest."""
    class Team:
        refusals, wait_refusals, notices = [], [], []

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            last = str(messages[-1]['content'])
            if '"assigned_role"' in system:
                return reply(calls=[('finish_work', {'summary': 'ドイツ: 人口 83,491,249（2025年、世界銀行）'})])
            workers = [agent for agent in self.engine.agents.values() if agent.parent_id]
            if not workers:
                return reply(calls=[('spawn_worker', {'role': 'ドイツ担当', 'task': 'ドイツの人口を調べる', 'profile_id': 'local'})])
            if len(workers) == 1:
                return reply(calls=[('spawn_worker', {'role': '集計担当', 'task': '表にまとめる', 'profile_id': 'local',
                                                      'depends_on': [workers[0].id]}), ('wait_for_workers', {})])
            if 'worker_dependency_pending' in last:
                self.refusals.append(last)
            if '待機できません' in last:
                self.wait_refusals.append(last)
            if 'チームの全員が待機していて' in last:
                self.notices.append(last)
            if 'worker_completed' in last:
                return reply(calls=[('finish_work', {'summary': '自分で表を仕上げました。'})])  # nothing was approved
            return after_refusal(self, last, workers)
    return Team()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_pm_whose_finish_is_refused_is_told_what_to_approve_and_may_not_just_wait(tmp_path):
    """Real-machine case: finish_work was refused (reports not approved), the PM
    called wait_for_message although every worker had ended, and the run stayed
    "waiting" until it was cut off after 15 minutes."""
    def script(team, last, workers):
        if 'worker_dependency_pending' in last:
            return reply(calls=[('wait_for_message', {})])
        if '待機できません' in last:
            first = workers[0]
            return reply(calls=[('review_worker_report', {'worker_id': first.id, 'result_revision': first.result_revision,
                                                          'decision': 'accept', 'feedback': '世界銀行の値と一致'})])
        return reply(calls=[('finish_work', {'summary': '報告を承認し、表を仕上げました。'})])

    client = sequence_team(script)
    engine, work = configured(tmp_path, client)
    client.engine = engine
    try:
        run, pm = await start(engine)
        await quiet(engine)
        first, second = [agent for agent in engine.agents.values() if agent.parent_id]
        assert run['status'] == 'done' and pm.status == 'done', (run['status'], pm.status, pm.last_error)
        # The worker that never started was closed with the PM's completion and no longer blocks it.
        assert second.status == 'stopped' and second.turns == 0
        # (c) the refusal names the report to approve, with the values review_worker_report needs.
        refusal = client.refusals[0]
        assert first.id in refusal and 'result_revision 1' in refusal and 'review_worker_report' in refusal
        assert second.id not in refusal
        # (a) waiting when nobody is left to send anything is refused, with the same next step.
        assert len(client.wait_refusals) == 1
        assert '連絡を送れる担当がいません' in client.wait_refusals[0] and first.id in client.wait_refusals[0]
        assert not client.notices and not any(row['kind'] == 'stall_notice' for row in engine.events)
        # The activity log keeps what each tool was called with, not only its result.
        import json
        tool_logs = {name: json.loads(body) for name, _, body in
                     (log['text'].partition('\n') for log in pm.logs if log['kind'] == 'tool')}  # still "name, newline, JSON"
        assert tool_logs['review_worker_report']['called_with']['worker_id'] == first.id
        assert tool_logs['review_worker_report']['ok'] is True
        assert tool_logs['spawn_worker']['called_with']['role'] in {'ドイツ担当', '集計担当'}
        # The model's own tool result does not carry the summary.
        assert not any('called_with' in str(row.get('content')) for row in pm.conversation if row.get('role') == 'tool')
    finally:
        await engine.close()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_pm_that_keeps_waiting_after_every_worker_ended_gets_three_notices_and_a_clear_stop(tmp_path):
    """(b) The notices used to stop after the first when no worker was left alive."""
    client = sequence_team(lambda team, last, workers: reply(calls=[('wait_for_message', {})]))
    engine, work = configured(tmp_path, client)
    client.engine = engine
    try:
        run, pm = await start(engine)
        for _ in range(400):  # each notice starts a new turn a moment after the previous one ended
            await asyncio.sleep(.01)
            if pm.status == 'error':
                break
        await quiet(engine)
        notices = [row['text'] for row in engine.events if row['kind'] == 'stall_notice']
        assert [text[-4:-1] for text in notices] == ['1/3', '2/3', '3/3'], notices
        assert client.notices and '全員が終了しています' in client.notices[0]
        assert '完了の前に必要な操作が残っています' in client.notices[0] and 'review_worker_report' in client.notices[0]
        delivered = [str(row.get('content')) for row in pm.conversation if 'チームの全員が待機していて' in str(row.get('content'))]
        assert len(delivered) == 3 and 'これが最後の通知です' in delivered[2] and 'これが最後の通知です' not in delivered[1]
        assert pm.status == 'error' and '行き詰まり' in pm.last_error
        assert any(row['kind'] == 'error' and '行き詰まり' in row['text'] for row in engine.events)
        assert len(client.wait_refusals) >= 1  # said once per turn, never an endless loop
        assert run['model_calls'] < 30
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_a_stopped_worker_that_was_still_waiting_on_a_dependency_does_not_hold_the_run(tmp_path):
    """Real-machine regression: the third worker depended on two others; the PM
    approved one report and finished. The application closed the worker that
    only waited and the one that never started, but the latter still counted
    as "waiting for a dependency", so the run stayed waiting for 15 minutes."""
    class Team:
        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            last = str(messages[-1]['content'])
            if '"assigned_role": "実装"' in system:
                return reply(calls=[('wait_for_message', {})])  # never gives a formal report
            if '"assigned_role": "テスト"' in system:
                return reply(calls=[('finish_work', {'summary': 'run_tests: 6 passed'})])
            workers = [agent for agent in engine.agents.values() if agent.parent_id]
            if len(workers) < 2:
                role = ('実装', 'テスト')[len(workers)]
                return reply(calls=[('spawn_worker', {'role': role, 'task': f'{role}を担当する', 'profile_id': 'local'})])
            if len(workers) == 2:
                return reply(calls=[('spawn_worker', {'role': '実行', 'task': '最終確認', 'profile_id': 'local',
                                                      'depends_on': [workers[0].id, workers[1].id]}), ('wait_for_workers', {})])
            if 'worker_completed' in last:
                tester = workers[1]
                return reply(calls=[('review_worker_report', {'worker_id': tester.id, 'result_revision': tester.result_revision,
                                                              'decision': 'accept', 'feedback': 'テスト結果を確認'})])
            return reply(calls=[('finish_work', {'summary': '実装とテストを確認しました。'})])

    engine, work = configured(tmp_path, Team())
    try:
        result = await engine.start_run({'task': 'Perform assigned work', 'pm_profile': 'local',
                                         'worker_profiles': ['local'], 'max_workers': 3})
        run = engine.runs[result['run']['id']]
        pm = engine.agents[run['agent_ids'][0]]
        await quiet(engine)
        coder, tester, runner = [agent for agent in engine.agents.values() if agent.parent_id]
        assert pm.status == 'done', (pm.status, pm.last_error)
        assert (coder.status, tester.status, runner.status) == ('done', 'done', 'stopped') and runner.turns == 0
        # The stopped worker's unmet dependency is still on record, but it no longer holds the run.
        assert engine._dependency_blockers(runner)
        assert run['status'] == 'done' and engine.run_status_reason(run) == 'done'
        assert engine.agent_status_reason(runner) == 'stopped'
    finally:
        await engine.close()


def test_tool_arguments_are_summarised_for_the_activity_log():
    from workbench.engine import _args_summary
    assert _args_summary({}) is None and _args_summary(None) is None
    brief = _args_summary({'path': 'C:\\out\\report.docx', 'expected_sha256': 'missing', 'text': 'あ' * 5000})
    assert brief['path'] == 'C:\\out\\report.docx' and brief['expected_sha256'] == 'missing'
    assert brief['text'].startswith('あ' * 80 + '…') and brief['text'].endswith('（全5000文字）')
    nested = _args_summary({'code': 'print(1)', 'outputs': [{'path': 'out/a.docx', 'name': 'a.docx', 'expected_sha256': 'missing'}] * 12})
    assert nested['outputs'][-1] == '…ほか4件' and nested['outputs'][0]['name'] == 'a.docx' and len(nested['outputs']) == 9
    long = _args_summary({f'field{index}': 'x' * 150 for index in range(10)})
    assert isinstance(long, str) and long.startswith('{"field0": "xxx') and len(long) <= 701  # clipped when even the summary is long


# --- nobody could ever send anything: a coordinator that works alone, and a worker whose coordinator waits ---

@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_pm_without_workers_may_not_wait_for_a_message_and_is_told_to_finish(tmp_path):
    """Real-machine case (research task): search was used up and most pages could
    not be fetched; the PM, working alone, called wait_for_message and the run
    stayed "waiting" for 15 minutes with no notice and nothing saved."""
    class Alone:
        refusals = []

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            last = str(messages[-1]['content'])
            if '待機できません' in last:
                self.refusals.append(last)
                return reply(calls=[('finish_work', {'summary': '検索できなかった点は未確認として報告します。'})])
            return reply(calls=[('wait_for_message', {})])
    client = Alone()
    engine, work = configured(tmp_path, client)
    try:
        run, pm = await start(engine, task='生成AI規制を調べて要約する', max_workers=0)
        await asyncio.wait_for(settled(engine), 20)
        assert run['agent_ids'] == [pm.id]
        assert len(client.refusals) == 1 and '連絡を送ってくる担当がいません' in client.refusals[0]
        for phrase in ('待っても何も届きません', 'finish_work', '未確認', 'ask_user'):
            assert phrase in client.refusals[0], phrase
        assert pm.status == 'done' and run['status'] == 'done' and not pm.waiting_for_message
        assert not any(row['kind'] == 'stall_notice' for row in engine.events)
    finally:
        await engine.close()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_pm_without_workers_that_keeps_waiting_gets_three_notices_and_a_clear_stop(tmp_path):
    class Alone:
        refusals, notices = [], []

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            last = str(messages[-1]['content'])
            if '待機できません' in last:
                self.refusals.append(last)
            if 'アプリからの通知' in last:
                self.notices.append(last)
            return reply(calls=[('wait_for_message', {})])  # waits whatever it is told
    client = Alone()
    engine, work = configured(tmp_path, client)
    try:
        run, pm = await start(engine, task='調べて要約する', max_workers=0)
        for _ in range(400):
            await asyncio.sleep(.01)
            if pm.status == 'error':
                break
        await quiet(engine)
        notices = [row['text'] for row in engine.events if row['kind'] == 'stall_notice']
        assert [text[-4:-1] for text in notices] == ['1/3', '2/3', '3/3'], notices
        assert all('連絡を送る担当がいないまま待機していた' in text for text in notices)
        assert len(client.notices) == 3 and '送ってくる担当がいません' in client.notices[0] and '作業者はいません' in client.notices[0]
        assert 'finish_work' in client.notices[0] and 'これが最後の通知です' in client.notices[2]
        assert pm.status == 'error' and '連絡を送ってくる担当がいないまま待機を続けたため' in pm.last_error
        # The run shows an error with its reason (a message to the PM resumes it); it is no longer "waiting for a peer".
        assert engine.run_status_reason(run) == 'error' and len(client.refusals) >= 1 and run['model_calls'] < 30
    finally:
        await engine.close()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_worker_may_not_wait_while_its_coordinator_only_waits_for_its_report(tmp_path):
    class Team:
        refusals = []

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            last = str(messages[-1]['content'])
            if '"assigned_role"' in system:
                if '待機できません' in last:
                    self.refusals.append(last)
                    return reply(calls=[('finish_work', {'summary': '値は確認できませんでした（未確認）。'})])
                # A worker starts as soon as it is created, while its coordinator's turn may still be
                # running. This case is about a coordinator that has gone to wait, so wait for that.
                pm = next(agent for agent in engine.agents.values() if agent.parent_id is None)
                for _ in range(1000):
                    if pm.waiting_for_workers and pm.status == 'idle' and (pm.task is None or pm.task.done()):
                        break
                    await asyncio.sleep(.01)
                return reply(calls=[('wait_for_message', {})])  # nothing was asked of anyone
            workers = [agent for agent in engine.agents.values() if agent.parent_id]
            if not workers:
                return reply(calls=[('spawn_worker', {'role': '調査', 'task': '値を調べる', 'profile_id': 'local'}), ('wait_for_workers', {})])
            if 'worker_completed' in last:
                return reply(calls=[('review_worker_report', {'worker_id': workers[0].id, 'result_revision': workers[0].result_revision,
                                                              'decision': 'accept'}), ('finish_work', {'summary': '未確認として報告します。'})])
            return reply(calls=[('wait_for_workers', {})])
    client = Team()
    engine, work = configured(tmp_path, client)
    try:
        run, pm = await start(engine, task='値を調べる')
        await asyncio.wait_for(settled(engine), 20)
        assert len(client.refusals) == 1
        for phrase in ('あなたの報告を待っている担当だけです', 'finish_work', 'send_message'):
            assert phrase in client.refusals[0], phrase
        assert run['status'] == 'done' and not any(row['kind'] == 'stall_notice' for row in engine.events)
    finally:
        await engine.close()


@pytest.mark.stall
@pytest.mark.asyncio
async def test_a_worker_that_asked_its_coordinator_something_may_wait_for_the_answer(tmp_path):
    class Team:
        refusals, asked = [], False

        async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
            last = str(messages[-1]['content'])
            if '"assigned_role"' in system:
                if '待機できません' in last:
                    self.refusals.append(last)
                if '2023年です' in last:
                    return reply(calls=[('finish_work', {'summary': '2023年の値を調べました。'})])
                pm = next(agent for agent in engine.agents.values() if agent.parent_id is None)
                return reply(calls=[('send_message', {'to_agent_id': pm.id, 'body': 'どの年の値が必要ですか'}), ('wait_for_message', {})])
            workers = [agent for agent in engine.agents.values() if agent.parent_id]
            if not workers:
                return reply(calls=[('spawn_worker', {'role': '調査', 'task': '値を調べる', 'profile_id': 'local'}), ('wait_for_workers', {})])
            if 'どの年の値' in last and not self.asked:
                self.asked = True
                return reply(calls=[('send_message', {'to_agent_id': workers[0].id, 'body': '2023年です'}), ('wait_for_workers', {})])
            if 'worker_completed' in last:
                return reply(calls=[('review_worker_report', {'worker_id': workers[0].id, 'result_revision': workers[0].result_revision,
                                                              'decision': 'accept'}), ('finish_work', {'summary': 'まとめました。'})])
            return reply(calls=[('wait_for_workers', {})])
    client = Team()
    engine, work = configured(tmp_path, client)
    try:
        run, pm = await start(engine, task='値を調べる')
        await asyncio.wait_for(settled(engine), 20)
        assert client.refusals == [] and client.asked and run['status'] == 'done'
    finally:
        await engine.close()
