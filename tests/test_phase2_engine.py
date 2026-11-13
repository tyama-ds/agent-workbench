"""Concurrent read-only file tools, actionable edit errors and tool exposure."""
import asyncio
import hashlib

import pytest

from workbench.harness import HarnessError, PathHarness, ToolExecutor
from test_engine import configured, start


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def executor(tmp_path):
    return ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)], []))


@pytest.mark.asyncio
async def test_stale_hash_errors_say_how_to_recover_without_disclosing_the_hash(tmp_path):
    tools = executor(tmp_path)
    target = tmp_path / 'a.txt'
    with pytest.raises(HarnessError, match="does not exist; use expected_sha256='missing'"):
        await tools.execute('write_text', {'path': str(target), 'text': 'x', 'expected_sha256': '0' * 64})
    await tools.execute('write_text', {'path': str(target), 'text': 'x', 'expected_sha256': 'missing'})
    with pytest.raises(HarnessError, match='already exists') as exists:
        await tools.execute('write_text', {'path': str(target), 'text': 'y', 'expected_sha256': 'missing'})
    with pytest.raises(HarnessError, match='modified after you read it') as stale:
        await tools.execute('patch_text', {'path': str(target), 'find': 'x', 'replace': 'y', 'expected_sha256': '0' * 64})
    for caught in (exists, stale):
        assert sha(b'x') not in str(caught.value)
    assert target.read_bytes() == b'x'


@pytest.mark.asyncio
async def test_patch_reports_missing_or_ambiguous_matches_and_tolerates_crlf(tmp_path):
    tools = executor(tmp_path)
    target = tmp_path / 'b.txt'
    target.write_bytes(b'one\r\ntwo\r\ntwo\r\n')
    current = sha(target.read_bytes())
    with pytest.raises(HarnessError, match='not found'):
        await tools.execute('patch_text', {'path': str(target), 'find': 'three', 'replace': 'x', 'expected_sha256': current})
    with pytest.raises(HarnessError, match='occurs 2 times'):
        await tools.execute('patch_text', {'path': str(target), 'find': 'two', 'replace': 'x', 'expected_sha256': current})
    # The model quoted LF line breaks for a CRLF file: matched and replaced in CRLF.
    await tools.execute('patch_text', {'path': str(target), 'find': 'one\ntwo', 'replace': 'ONE\nTWO',
                                       'expected_sha256': current})
    assert target.read_bytes() == b'ONE\r\nTWO\r\ntwo\r\n'


@pytest.mark.asyncio
async def test_read_only_file_tools_run_concurrently_and_writes_wait_for_them(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, agent = await start(engine)
        (work / 'r.txt').write_text('data', encoding='utf-8')
        real = run['_executor'].execute
        release, active, peak, order = asyncio.Event(), [0], [0], []

        async def slow(name, args, **kwargs):
            if name == 'read_text':
                active[0] += 1
                peak[0] = max(peak[0], active[0])
                await release.wait()
                active[0] -= 1
            order.append(name)
            return await real(name, args, **kwargs)
        run['_executor'].execute = slow
        reads = [asyncio.create_task(engine.execute_tool(run, agent, 'read_text', {'path': str(work / 'r.txt')}))
                 for _ in range(2)]
        await asyncio.sleep(0.05)
        assert peak[0] == 2, 'two reads run at the same time'
        write = asyncio.create_task(engine.execute_tool(run, agent, 'write_text', {
            'path': str(work / 'w.txt'), 'text': 'new', 'expected_sha256': 'missing'}))
        await asyncio.sleep(0.05)
        assert not write.done() and 'write_text' not in order, 'a write waits for admitted reads'
        third = asyncio.create_task(engine.execute_tool(run, agent, 'read_text', {'path': str(work / 'r.txt')}))
        await asyncio.sleep(0.05)
        assert peak[0] == 2, 'a read queued behind a waiting write does not start'
        release.set()
        results = await asyncio.gather(*reads, write, third)
        assert [row.get('text') for row in results[:2]] == ['data', 'data'] and results[3]['text'] == 'data'
        assert order.index('write_text') < order.index('read_text', 2)
        assert engine._file_readers == 0 and engine._file_readers_idle.is_set()
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_file_tools_are_not_offered_without_any_folder(tmp_path):
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    engine.settings.value['paths'] = {'read_roots': [], 'write_roots': [], 'deny_roots': []}
    try:
        run, agent = await start(engine)
        names = {tool['name'] for tool in engine._model_tools(run, agent)}
        assert 'read_text' not in names and 'write_text' not in names
        assert {'spawn_worker', 'finish_work'} <= names
    finally:
        await engine.close()
