"""Current-session reports and actual save receipts, never model-claimed artifacts."""
import asyncio
import json
import threading

import pytest

from workbench.engine import RESULT_LIMIT, RECEIPT_LIMIT, RESULT_TEXT_LIMIT
from workbench.harness import ToolExecutor
from test_engine import ScriptClient, configured, reply, settled, start


async def test_terminal_reply_only_and_resumed_history(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([
        reply('Intermediate claim: file saved', [('list_team', {})]), reply('Actual terminal answer'),
        reply(calls=[('finish_work', {'summary': 'Explicit report'})])]))
    try:
        run, pm = await start(engine)
        await settled(engine)
        assert [(r['source'], r['text']) for r in pm.results] == [('assistant_response', 'Actual terminal answer')]
        assert not pm.output_receipts
        original = dict(pm.results[-1])
        await engine.human_message(pm.id, 'Continue')
        assert pm.result_revision != original['revision']
        await settled(engine)
        assert pm.results[0] == original
        assert pm.results[-1]['source'] == 'finish_work' and pm.results[-1]['turn'] == 2
        assert len(pm.results) == 2
    finally:
        await engine.close()


@pytest.mark.parametrize('mode', ['question', 'error', 'collaboration'])
async def test_intermediate_text_is_not_a_completed_report(tmp_path, mode):
    calls = {'question': [('ask_user', {'question': 'Which?'})],
             'error': [('list_team', {})],
             'collaboration': [('spawn_worker', {'role': 'worker', 'task': 'Help', 'profile_id': 'local'})]}[mode]
    engine, _ = configured(tmp_path, ScriptClient([reply('Unfinished answer', calls)]))
    if mode == 'collaboration':
        engine.settings.value['limits']['max_auto_collaborations'] = 0
    try:
        run, pm = await start(engine)
        await settled(engine)
        assert not pm.results and not pm.output_receipts
    finally:
        await engine.close()


async def test_real_write_variants_have_receipts_and_failures_do_not(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        cases = [
            ('write_text', 'a.txt', {'text': 'first'}),
            ('docx_write', 'a.docx', {'paragraphs': ['first']}),
            ('xlsx_write', 'a.xlsx', {'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': 'first'}]}),
            ('pptx_write', 'a.pptx', {'slides': [{'title': 'first', 'body': ['body']}]}),
        ]
        hashes = {}
        for tool, filename, fields in cases:
            result = await engine.execute_tool(run, pm, tool, {'path': str(work / filename), 'expected_sha256': 'missing', **fields})
            hashes[filename] = result['sha256']
            assert pm.output_receipts[-1]['tool'] == tool
            assert pm.output_receipts[-1]['operation'] == 'created'
            assert pm.output_receipts[-1]['sha256'] == result['sha256']
        edits = [
            ('patch_text', 'a.txt', {'find': 'first', 'replace': 'next'}),
            ('docx_edit', 'a.docx', {'operations': [{'type': 'replace_paragraph', 'index': 0, 'text': 'next'}]}),
            ('xlsx_write', 'a.xlsx', {'cells': [{'sheet': 'Sheet', 'cell': 'A1', 'value': 'next'}]}),
            ('pptx_edit', 'a.pptx', {'operations': [{'slide': 0, 'shape': 0, 'paragraph': 0, 'text': 'next'}]}),
        ]
        for tool, filename, fields in edits:
            await engine.execute_tool(run, pm, tool, {'path': str(work / filename), 'expected_sha256': hashes[filename], **fields})
            assert pm.output_receipts[-1]['operation'] == 'updated'
        count = len(pm.output_receipts)
        for filename, fields in [('a.txt', {'text': 'bad', 'expected_sha256': 'missing'}),
                                 ('a.pdf', {'text': 'bad', 'expected_sha256': 'missing'}),
                                 ('../escape.txt', {'text': 'bad', 'expected_sha256': 'missing'})]:
            with pytest.raises(ValueError):
                await engine.execute_tool(run, pm, 'write_text', {'path': str(work / filename), **fields})
        await engine.execute_tool(run, pm, 'read_text', {'path': str(work / 'a.txt')})
        assert len(pm.output_receipts) == count
        # Historical save metadata cannot assert that a file still exists.
        (work / 'a.txt').unlink()
        assert engine.snapshot()['agents'][0]['output_receipts'][0]['operation'] == 'created'
    finally:
        await engine.close()


async def test_bounded_redacted_retention_independent_of_logs(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        engine.settings.secrets['local'] = 'synthetic-secret'
        for _ in range(RESULT_LIMIT + 3):
            engine.record_result(pm, 'assistant_response', 'synthetic-secret' + 'x' * RESULT_TEXT_LIMIT)
        for _ in range(RECEIPT_LIMIT + 4):
            engine.record_receipt(pm, 'write_text', {'path': '/synthetic-secret/test', 'bytes': 1, 'sha256': 'a' * 64, 'operation': 'created'})
        for _ in range(205):
            engine.log(pm, 'assistant', 'irrelevant')
        state = engine.snapshot()['agents'][0]
        assert len(state['results']) == RESULT_LIMIT and state['results_omitted'] == 3
        assert all(r['truncated'] and len(r['text']) == RESULT_TEXT_LIMIT for r in state['results'])
        assert len(state['output_receipts']) == RECEIPT_LIMIT and state['receipts_omitted'] == 4
        assert 'synthetic-secret' not in json.dumps(state)
        assert 'conversation' not in state
    finally:
        await engine.close()


async def test_write_only_receipt_does_not_grant_read(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    engine.settings.value['paths']['read_roots'] = []
    try:
        run, pm = await start(engine)
        await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'saved.txt'), 'text': 'saved', 'expected_sha256': 'missing'})
        assert len(pm.output_receipts) == 1
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'read_text', {'path': str(work / 'saved.txt')})
    finally:
        await engine.close()


@pytest.mark.parametrize('fail', [False, True])
async def test_cancelled_operation_observer_once_on_loop_and_only_success(tmp_path, monkeypatch, fail):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    entered, release = threading.Event(), threading.Event()
    original = ToolExecutor._execute
    def delayed(self, name, args):
        entered.set()
        assert release.wait(3)
        if fail:
            raise ValueError('Synthetic failed save')
        return original(self, name, args)
    monkeypatch.setattr(ToolExecutor, '_execute', delayed)
    try:
        run, pm = await start(engine)
        observed = []
        record = engine.record_receipt
        def observer(*args):
            observed.append(threading.get_ident())
            record(*args)
        engine.record_receipt = observer
        operation = asyncio.create_task(engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'stopped.txt'), 'text': 'saved', 'expected_sha256': 'missing'}))
        assert await asyncio.to_thread(entered.wait, 2)
        operation.cancel()
        await asyncio.sleep(.01)
        assert not operation.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert len(pm.output_receipts) == (0 if fail else 1)
        assert observed == ([] if fail else [threading.get_ident()])
    finally:
        release.set()
        await engine.close()


async def test_observer_failure_never_changes_successful_save(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        def broken(*args):
            raise RuntimeError('Observer only')
        engine.record_receipt = broken
        result = await engine.execute_tool(run, pm, 'write_text', {'path': str(work / 'saved.txt'), 'text': 'saved', 'expected_sha256': 'missing'})
        assert result['operation'] == 'created' and (work / 'saved.txt').read_text() == 'saved'
    finally:
        await engine.close()


async def test_queued_turns_and_active_resume_do_not_relabel_earlier_result(tmp_path):
    release = asyncio.Event()
    async def delayed(profile, messages):
        await release.wait()
        return reply('Second answer')
    engine, _ = configured(tmp_path, ScriptClient([reply('First answer'), delayed]))
    try:
        run, pm = await start(engine)
        await settled(engine)
        first = dict(pm.results[0])
        await engine.human_message(pm.id, 'Second task')
        await asyncio.sleep(.01)
        assert pm.status == 'working' and pm.turns != first['turn']
        assert pm.result_revision != first['revision'] and pm.results[0] == first
        release.set()
        await settled(engine)
        assert pm.results[-1]['text'] == 'Second answer' and pm.results[-1]['turn'] == 2
    finally:
        release.set()
        await engine.close()


async def test_idle_pm_response_is_a_turn_response_not_team_completion(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([reply('Waiting for my worker')]))
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        child = engine._new_agent(run, 'local', 'worker', pm.id)
        child.status = 'working'
        await engine._agent_loop(pm)
        assert pm.status == 'idle' and run['status'] != 'done'
        assert pm.results[-1]['source'] == 'assistant_response'
    finally:
        await engine.close()
