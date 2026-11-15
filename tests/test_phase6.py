"""Phase 6: partial reads, multi-place and line-range edits, read-only
workers, stopping one worker, and restoring a file from a saved write."""
import asyncio
import hashlib
import json

import pytest

from workbench.checkpoints import CheckpointStore
from workbench.harness import HarnessError, PathHarness, ToolExecutor
from workbench.history import public_document
from test_engine import ScriptClient, configured, reply, settled, start


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def tools(tmp_path):
    return ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)])), tmp_path


async def patch(executor, path, **args):
    return await executor.execute('patch_text', {'path': str(path), 'expected_sha256': sha(path.read_bytes()), **args})


# --- read_text line ranges -------------------------------------------------

@pytest.mark.asyncio
async def test_read_text_returns_a_line_range_with_the_whole_file_hash(tools):
    executor, root = tools
    path = root / 'a.txt'
    path.write_bytes(b'\xef\xbb\xbfone\r\ntwo\r\nthree\r\nfour')
    part = await executor.execute('read_text', {'path': str(path), 'start_line': 2, 'line_count': 2})
    assert part['text'] == 'two\r\nthree\r\n'
    assert (part['start_line'], part['end_line'], part['total_lines']) == (2, 3, 4)
    assert part['sha256'] == sha(path.read_bytes())
    tail = await executor.execute('read_text', {'path': str(path), 'start_line': 4})
    assert tail['text'] == 'four' and tail['end_line'] == 4
    whole = await executor.execute('read_text', {'path': str(path)})
    assert whole['text'] == 'one\r\ntwo\r\nthree\r\nfour' and 'total_lines' not in whole
    with pytest.raises(HarnessError, match='start_line'):
        await executor.execute('read_text', {'path': str(path), 'start_line': 5})


# --- patch_text edits ------------------------------------------------------

@pytest.mark.asyncio
async def test_single_find_replace_still_works(tools):
    executor, root = tools
    path = root / 'a.txt'
    path.write_text('alpha beta', encoding='utf-8')
    result = await patch(executor, path, find='beta', replace='gamma')
    assert path.read_text(encoding='utf-8') == 'alpha gamma' and 'edits_applied' not in result


@pytest.mark.asyncio
async def test_edits_apply_together_against_the_same_version(tools):
    executor, root = tools
    path = root / 'a.txt'
    path.write_text('line 1\nsame\nline 3\nsame\nline 5\n', encoding='utf-8')
    result = await patch(executor, path, edits=[
        {'start_line': 4, 'end_line': 4, 'replace': 'fourth'},        # repeated text: use a line number
        {'find': 'line 1', 'replace': 'first\nextra'},                 # adds a line before line 4...
        {'start_line': 5, 'replace': ''},                              # ...without shifting later numbers
    ])
    assert result['edits_applied'] == 3
    assert path.read_text(encoding='utf-8') == 'first\nextra\nsame\nline 3\nfourth\n'


@pytest.mark.asyncio
async def test_a_bad_edit_rejects_the_whole_patch(tools):
    executor, root = tools
    path = root / 'a.txt'
    path.write_text('a\nb\nc\n', encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(HarnessError, match='Edit 2 find text must occur exactly once'):
        await patch(executor, path, edits=[{'find': 'a', 'replace': 'A'}, {'find': 'zzz', 'replace': 'Z'}])
    with pytest.raises(HarnessError, match='overlap'):
        await patch(executor, path, edits=[{'start_line': 1, 'end_line': 2, 'replace': 'x'}, {'find': 'b', 'replace': 'B'}])
    with pytest.raises(HarnessError, match='either find and replace, or edits'):
        await patch(executor, path, find='a', replace='A', edits=[{'find': 'b', 'replace': 'B'}])
    with pytest.raises(HarnessError, match='end_line'):
        await patch(executor, path, edits=[{'start_line': 2, 'end_line': 1, 'replace': 'x'}])
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_line_edits_keep_crlf_and_the_bom(tools):
    executor, root = tools
    path = root / 'a.txt'
    path.write_bytes(b'\xef\xbb\xbfone\r\ntwo\r\nthree\r\n')
    await patch(executor, path, edits=[{'start_line': 1, 'replace': 'ONE\nUNO'}, {'start_line': 3, 'replace': 'THREE'}])
    assert path.read_bytes() == b'\xef\xbb\xbfONE\r\nUNO\r\ntwo\r\nTHREE\r\n'


def test_patch_schema_needs_only_path_and_hash(tools):
    executor, _ = tools
    schema = next(item for item in executor.schemas() if item['name'] == 'patch_text')['parameters']
    assert schema['required'] == ['path', 'expected_sha256']
    assert schema['properties']['edits']['items']['required'] == ['replace']


# --- worker tools are not offered without workers --------------------------

@pytest.mark.asyncio
async def test_solo_runs_are_not_offered_worker_tools(tmp_path):
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        solo_run, solo = await start(engine, max_workers=0)
        team_run, team = await start(engine, max_workers=1)
        solo_names = {tool['name'] for tool in engine._model_tools(solo_run, solo)}
        team_names = {tool['name'] for tool in engine._model_tools(team_run, team)}
        assert not {'spawn_worker', 'wait_for_workers', 'review_worker_report', 'start_ordered_work'} & solo_names
        assert {'spawn_worker', 'wait_for_workers', 'review_worker_report'} <= team_names
    finally:
        await engine.close()


# --- read-only workers -----------------------------------------------------

@pytest.mark.asyncio
async def test_read_only_worker_can_read_but_not_change_files(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    (work / 'notes.txt').write_text('data', encoding='utf-8')
    try:
        run, pm = await start(engine)
        assert 'read_only' in next(t for t in engine._model_tools(run, pm) if t['name'] == 'spawn_worker')['parameters']['properties']
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {
            'role': 'researcher', 'task': 'Read notes', 'profile_id': 'local', 'read_only': True})
        assert spawned['read_only'] is True
        worker = engine.agents[spawned['agent_id']]
        names = {tool['name'] for tool in engine._model_tools(run, worker)}
        assert 'read_text' in names
        assert not {'write_text', 'patch_text', 'create_directory', 'reserve_paths', 'spawn_worker', 'docx_write'} & names
        assert '"read_only":true' in engine._policy(run, worker)
        assert (await engine.execute_tool(run, worker, 'read_text', {'path': str(work / 'notes.txt')}))['text'] == 'data'
        with pytest.raises(ValueError, match='読み取り専用'):
            await engine.execute_tool(run, worker, 'write_text', {
                'path': str(work / 'new.txt'), 'text': 'x', 'expected_sha256': 'missing'})
        assert not (work / 'new.txt').exists()
        with pytest.raises(ValueError, match='read_only'):
            await engine.execute_tool(run, pm, 'spawn_worker', {
                'role': 'r', 'task': 't', 'profile_id': 'local', 'read_only': 'yes'})
        public = worker.public()
        assert public['read_only'] is True and 'read_only' not in pm.public()
        saved = public_document(run, [worker.public(), pm.public()], [], [])
        assert saved['agents'][0]['read_only'] is True
    finally:
        await engine.close()


# --- stopping one worker ---------------------------------------------------

@pytest.mark.asyncio
async def test_a_human_stops_one_worker_and_the_pm_is_told(tmp_path):
    release = asyncio.Event()

    async def slow(profile, messages):
        await release.wait()
        return reply('never used')
    engine, _ = configured(tmp_path, ScriptClient([reply(calls=[('spawn_worker', {
        'role': 'writer', 'task': 'Long task', 'profile_id': 'local'})]), reply(calls=[('wait_for_workers', {})]),
        slow, reply('PM handles the stop.')]))
    try:
        run, pm = await start(engine)
        for _ in range(200):
            worker = next((engine.agents[i] for i in run['agent_ids'] if engine.agents[i].parent_id), None)
            if worker and worker.status == 'working':
                break
            await asyncio.sleep(.01)
        with pytest.raises(ValueError, match='PM は個別に停止できません'):
            await engine.stop_agent(pm.id)
        result = await engine.stop_agent(worker.id)
        assert result == {'ok': True, 'stopped': [worker.id]}
        assert (worker.status, worker.stop_reason) == ('stopped', 'human_stop')
        assert worker.task.done() and not worker.pending
        assert (await engine.stop_agent(worker.id))['stopped'] == []
        await settled(engine)
        notices = [row['content'] for row in pm.conversation if row['role'] == 'user' and 'Worker stopped by the human' in row.get('content', '')]
        assert notices, 'the PM must be told that its worker was stopped'
        assert pm.status == 'done' and run['status'] == 'done'
        eligibility = engine.message_eligibility(worker)
        assert eligibility['reason'] == 'agent_stopped' and not eligibility['allowed']
        assert any(row['kind'] == 'stopped' and row['agent_id'] == worker.id for row in engine.events)
    finally:
        release.set()
        await engine.close()


@pytest.mark.asyncio
async def test_adaptive_and_finished_runs_refuse_a_single_stop(tmp_path):
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'w', 'task': 't', 'profile_id': 'local'})
        run['adaptive_team'] = True
        with pytest.raises(ValueError, match='自動編成'):
            await engine.stop_agent(spawned['agent_id'])
        run.pop('adaptive_team')
        await engine.stop_run(run['id'])
        with pytest.raises(ValueError, match='チームは停止しています'):
            await engine.stop_agent(spawned['agent_id'])
    finally:
        await engine.close()


# --- restoring a file from a saved write ------------------------------------

@pytest.mark.asyncio
async def test_a_human_restores_the_content_before_a_saved_write(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    target = work / 'report.txt'
    target.write_text('original', encoding='utf-8')
    try:
        run, pm = await start(engine)
        created = await engine.execute_tool(run, pm, 'write_text', {
            'path': str(work / 'new.txt'), 'text': 'new', 'expected_sha256': 'missing'})
        updated = await engine.execute_tool(run, pm, 'write_text', {
            'path': str(target), 'text': 'changed', 'expected_sha256': sha(b'original')})
        assert 'previous_sha256' not in updated, 'the restore record is not model data'
        new_receipt, update_receipt = list(pm.output_receipts)
        assert not new_receipt.get('restorable')
        assert update_receipt['restorable'] is True and update_receipt['previous_sha256'] == sha(b'original')

        with pytest.raises(ValueError, match='実行中は戻せません'):
            await engine.restore_output(run['id'], {'receipt_id': update_receipt['id']})
        run['status'] = 'done'
        with pytest.raises(ValueError, match='元に戻せません'):
            await engine.restore_output(run['id'], {'receipt_id': new_receipt['id']})
        result = await engine.restore_output(run['id'], {'receipt_id': update_receipt['id']})
        assert result['ok'] and target.read_text(encoding='utf-8') == 'original'
        assert update_receipt['restorable'] is False
        restore_receipt = pm.output_receipts[-1]
        assert restore_receipt['tool'] == 'human_restore' and restore_receipt['restorable'] is True
        assert any(row['kind'] == 'restored' for row in engine.events)
        with pytest.raises(ValueError, match='元に戻せません'):
            await engine.restore_output(run['id'], {'receipt_id': update_receipt['id']})

        # The restore can be undone, but never over a later change.
        target.write_text('edited by hand', encoding='utf-8')
        with pytest.raises(ValueError, match='変更されているため'):
            await engine.restore_output(run['id'], {'receipt_id': restore_receipt['id']})
        assert target.read_text(encoding='utf-8') == 'edited by hand'
        with pytest.raises(ValueError, match='receipt|保存記録'):
            await engine.restore_output(run['id'], {'receipt_id': 'x'})
        saved = public_document(run, [pm.public()], [], [])
        assert all('restorable' not in row and 'previous_sha256' not in row
                   for row in saved['agents'][0]['output_receipts']), 'archives never offer a restore'
    finally:
        await engine.close()
    assert not engine.checkpoints.root.exists(), 'checkpoints live only for this app session'


def test_checkpoint_store_limits_and_keys(tmp_path, monkeypatch):
    import workbench.checkpoints as module
    store = CheckpointStore(tmp_path)
    run = 'r-' + '0' * 16
    digest = store.save(run, b'abc')
    assert digest == sha(b'abc') and store.has(run, digest) and store.load(run, digest) == b'abc'
    assert store.save(run, b'abc') == digest
    monkeypatch.setattr(module, 'MAX_RUN_BYTES', 5)
    assert store.save(run, b'too long') is None
    assert not store.has('../escape', digest)
    with pytest.raises(ValueError):
        store.load(run, '../../x')
    store.close()
    assert not store.root.exists()
