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
        result = await engine.execute_tool(run, pm, 'finish_work', {'summary': '報告書を保存しました。'})
        assert '【アプリの確認】' in result['summary'] and 'https://unseen.jp/page' in result['summary'] and 'notes.md' in result['summary']
        # Source code is not a citation.
        await engine.execute_tool(run, pm, 'write_text', {
            'path': str(work / 'client.py'), 'text': 'URL = "https://api.unseen.jp/v1"', 'expected_sha256': 'missing'})
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
