"""Directory-to-file workflows through the real engine and native API adapters."""
import asyncio
import json
import time

import pytest
from aiohttp import web

from workbench.engine import Engine, FILE_OPERATION_POLICY
from test_engine import ScriptClient, configured, reply, settled, start
from test_engine_integration import api_server, configured_settings
from test_tool_result_integrity import WIRE_REPLY, tool_results


@pytest.mark.parametrize('kind', WIRE_REPLY)
async def test_native_directory_and_file_creation_with_readback(tmp_path, kind):
    requests, errors = [], []

    async def handler(request):
        try:
            body = await request.json()
            requests.append(body)
            if len(requests) == 1:
                assert 'create_directory' in json.dumps(body['tools'])
                assert 'File operations:' in json.dumps(body)
                return WIRE_REPLY[kind]([
                    ('reserve', 'reserve_paths', {'paths': ['project']}),
                    ('directory', 'create_directory', {'path': 'project/reports'}),
                    ('write', 'write_text', {'path': 'project/reports/result.txt',
                        'text': '実際に保存した本文', 'expected_sha256': 'missing'}),
                    ('read', 'read_text', {'path': 'project/reports/result.txt'}),
                    ('release', 'release_paths', {'paths': ['project']}),
                ])
            assert len(requests) == 2
            results = tool_results(kind, body, ['reserve', 'directory', 'write', 'read', 'release'])
            assert all(result.get('ok') is not False for result in results)
            assert results[1]['kind'] == 'directory' and results[1]['operation'] == 'created'
            assert results[2]['operation'] == 'created'
            assert results[3]['text'] == '実際に保存した本文'
            assert results[2]['sha256'] == results[3]['sha256']
            return WIRE_REPLY[kind](text='Created the folder and saved and read back result.txt.')
        except Exception as exc:
            errors.append(repr(exc))
            return web.json_response({'error': 'Synthetic fixture failure'}, status=500)

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        engine = Engine(settings)
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await settled(engine)
            assert not errors and len(requests) == 2
            assert agent.status == 'done' and not agent.last_error
            assert (work / 'project/reports/result.txt').read_text(encoding='utf-8') == '実際に保存した本文'
            assert run['tool_calls'] == 5 and not engine.reservations
            assert [receipt['tool'] for receipt in agent.output_receipts] == ['write_text']
            assert any(log['kind'] == 'tool' and log['text'].startswith('create_directory\n') for log in agent.logs)
        finally:
            await engine.close()


async def test_directory_checks_missing_parent_reservations_without_blocking_existing_siblings(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, owner = await start(engine)
        run2, other = await start(engine)
        await engine.execute_tool(run, owner, 'reserve_paths', {'paths': ['project/reserved']})
        with pytest.raises(ValueError, match='予約中'):
            await engine.execute_tool(run2, other, 'create_directory', {'path': 'project/other'})
        assert not (work / 'project').exists()
        # Once project exists, creating a sibling does not mutate the reserved path.
        await engine.execute_tool(run, owner, 'create_directory', {'path': 'project'})
        result = await engine.execute_tool(run2, other, 'create_directory', {'path': 'project/other'})
        assert result['operation'] == 'created'
        for path in ('project/reserved', 'project/reserved/child', 'project'):
            with pytest.raises(ValueError, match='予約中'):
                await engine.execute_tool(run2, other, 'create_directory', {'path': path})
        assert not owner.output_receipts and not other.output_receipts
    finally:
        await engine.close()


async def test_directory_write_only_scope_does_not_grant_reads(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.settings.value['paths']['read_roots'] = []
    engine.kick = lambda agent: None
    try:
        run, agent = await start(engine)
        await engine.execute_tool(run, agent, 'create_directory', {'path': 'out/nested'})
        await engine.execute_tool(run, agent, 'write_text', {
            'path': 'out/nested/a.txt', 'text': 'saved', 'expected_sha256': 'missing'})
        with pytest.raises(ValueError):
            await engine.execute_tool(run, agent, 'read_text', {'path': str(work / 'out/nested/a.txt')})
        assert (work / 'out/nested/a.txt').read_text() == 'saved'
        assert len(agent.output_receipts) == 1
    finally:
        await engine.close()


async def test_queued_directory_does_not_start_after_deadline(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, agent = await start(engine)
        async with engine.lock:
            operation = asyncio.create_task(engine.execute_tool(run, agent, 'create_directory', {'path': 'expired'}))
            await asyncio.sleep(0)
            run['created_at'] = time.time() - run['_config']['limits']['max_run_seconds'] - 1
        with pytest.raises(ValueError, match='上限'):
            await operation
        assert not (work / 'expired').exists()
    finally:
        await engine.close()


async def test_saved_custom_policy_gets_workflow_without_mutating_settings_or_executing_text(tmp_path):
    draft = 'create_directory({"path":"draft"}); write_text({"path":"draft/a.txt","text":"proposal"})'
    engine, work = configured(tmp_path, ScriptClient([reply(draft)]))
    custom = 'Write the requested draft in Japanese.'
    engine.settings.value['system_policy'] = custom
    try:
        run, agent = await start(engine, task='Show a proposed file layout only. Do not save files.')
        await settled(engine)
        policy = engine._policy(run, agent)
        assert policy.startswith(custom) and FILE_OPERATION_POLICY in policy
        assert engine.settings.value['system_policy'] == run['_config']['system_policy'] == custom
        assert not list(work.iterdir()) and run['tool_calls'] == 0
        assert not agent.output_receipts and agent.results[-1]['text'] == draft
        assert run['model_calls'] == 1  # No forced repeat for a legitimate text-only answer.
    finally:
        await engine.close()
