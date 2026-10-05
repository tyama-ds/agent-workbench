"""Real loopback providers, controlled engine time and explicit lock handshakes."""
import asyncio
import copy
import json
import threading
from types import SimpleNamespace

import pytest

import workbench.engine as engine_module
from workbench.engine import Engine
from workbench.harness import ToolExecutor
from test_engine import ScriptClient, configured, settled, start
from test_engine_integration import (
    api_server, configured_settings, local_reply, openai_reply, anthropic_reply, eventually,
)


WIRE_REPLY = {'local': local_reply, 'openai': openai_reply, 'anthropic': anthropic_reply}


class ObservedLock(asyncio.Lock):
    """Report a real contested acquisition before suspending on the mutex."""

    def __init__(self):
        super().__init__()
        self.queued = asyncio.Event()

    async def acquire(self):
        if self.locked():
            self.queued.set()
        return await super().acquire()


@pytest.mark.parametrize('kind', WIRE_REPLY)
@pytest.mark.parametrize('boundary', ['before', 'exact', 'after', 'stop'])
@pytest.mark.parametrize('single', [False, True])
async def test_queued_file_dispatch_rechecks_time_before_path_resolution(tmp_path, monkeypatch, kind, boundary, single):
    now = [100.0]
    # Replace only the engine's clock reference, not Python's shared time module
    # or asyncio's monotonic timers used by HTTP and test watchdogs.
    monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda: now[0]))
    requests = []

    async def handler(request):
        requests.append(await request.json())
        if len(requests) == 1:
            return WIRE_REPLY[kind]([('earlier', 'write_text', {
                'path': 'earlier.txt', 'text': 'Retained output', 'expected_sha256': 'missing'})])
        if len(requests) == 2:
            return WIRE_REPLY[kind](text='Earlier report')
        if len(requests) == 4:
            assert single and boundary == 'before'
            return WIRE_REPLY[kind](text='New report')
        assert len(requests) == 3
        calls = [
            ('queued', 'write_text', {'path': 'queued.txt', 'text': 'Queued output', 'expected_sha256': 'missing'}),
            ('later', 'write_text', {'path': 'later.txt', 'text': 'Later output', 'expected_sha256': 'missing'}),
            ('finish', 'finish_work', {'summary': 'New report'}),
        ]
        return WIRE_REPLY[kind](calls[:1] if single else calls)

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        settings.value['limits']['max_run_seconds'] = 10
        engine = Engine(settings)
        engine.lock = ObservedLock()
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await settled(engine)
            receipts = copy.deepcopy(list(agent.output_receipts))
            reports = copy.deepcopy(list(agent.results))
            assert len(receipts) == len(reports) == 1
            resolved = []
            original = run['_harness'].resolve

            def resolve(*args, **kwargs):
                resolved.append(args[0])
                return original(*args, **kwargs)

            monkeypatch.setattr(run['_harness'], 'resolve', resolve)
            await engine.lock.acquire()
            await engine.human_message(agent.id, 'Continue with another file')
            await asyncio.wait_for(engine.lock.queued.wait(), 3)
            # The existing attempted-call accounting is already charged. No
            # path resolution or filesystem operation has started while queued.
            assert run['model_calls'] == 3 and run['tool_calls'] == 2 and agent.turns == 2
            assert not resolved and not (work / 'queued.txt').exists()
            now[0] += {'before': 9.999, 'exact': 10, 'after': 10.001, 'stop': 10}[boundary]
            if boundary == 'stop':
                await engine.stop_run(run['id'])
                assert agent.status == run['status'] == 'stopped'
            engine.lock.release()
            await settled(engine)
            assert len(requests) == run['model_calls'] == (4 if single and boundary == 'before' else 3)
            assert agent.turns == 2
            assert run['auto_collaborations'] == 0
            assert (work / 'earlier.txt').read_text() == 'Retained output'
            if boundary == 'before':
                assert (work / 'queued.txt').read_text() == 'Queued output'
                assert (work / 'later.txt').exists() is not single
                assert agent.status == run['status'] == 'done'
                assert run['tool_calls'] == (2 if single else 4)
                assert len(agent.output_receipts) == (2 if single else 3)
                assert len(agent.results) == 2 and resolved
            else:
                assert not resolved
                assert not (work / 'queued.txt').exists() and not (work / 'later.txt').exists()
                assert list(agent.output_receipts) == receipts and list(agent.results) == reports
                assert run['tool_calls'] == 2  # No refund and no charge for skipped calls.
                reason = 'stopped' if boundary == 'stop' else 'time_limit'
                assert engine.message_eligibility(agent)['reason'] == reason
                if boundary != 'stop':
                    assert agent.status == 'error' and run['status'] == 'waiting'
                    assert '実行時間' in agent.last_error
                    results = [item for item in agent.conversation if item['role'] == 'tool'][-(1 if single else 3):]
                    assert [item['tool_call_id'] for item in results] == (['queued'] if single else ['queued', 'later', 'finish'])
                    assert all(json.loads(item['content'])['ok'] is False for item in results)
                    assert all('実行時間' in json.loads(item['content'])['error'] for item in results)
                before = (run['model_calls'], run['tool_calls'], agent.turns, agent.result_revision)
                with pytest.raises(ValueError):
                    await engine.human_message(agent.id, 'Continue again')
                assert (run['model_calls'], run['tool_calls'], agent.turns, agent.result_revision) == before
        finally:
            if engine.lock.locked():
                engine.lock.release()
            await engine.close()


@pytest.mark.parametrize('name', [tool['name'] for tool in ToolExecutor(None).schemas()])
async def test_every_filesystem_tool_rejects_expired_queue_before_any_path_access(tmp_path, monkeypatch, name):
    now = [100.0]
    monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda: now[0]))
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    engine.lock = ObservedLock()
    queued = None

    def forbidden(*args, **kwargs):
        pytest.fail('Expired file tool reached path resolution or executor dispatch')

    try:
        run, agent = await start(engine)
        monkeypatch.setattr(run['_harness'], 'resolve', forbidden)
        monkeypatch.setattr(run['_executor'], 'execute', forbidden)
        await engine.lock.acquire()
        queued = asyncio.create_task(engine.execute_tool(run, agent, name, {'path': 'PRIVATE-INVALID-PATH\x00'}))
        await asyncio.wait_for(engine.lock.queued.wait(), 3)
        now[0] += run['_config']['limits']['max_run_seconds']
        engine.lock.release()
        with pytest.raises(ValueError, match='実行時間') as error:
            await queued
        assert 'PRIVATE' not in str(error.value)
    finally:
        if engine.lock.locked():
            engine.lock.release()
        if queued:
            await asyncio.gather(queued, return_exceptions=True)
        await engine.close()


@pytest.mark.parametrize('kind', WIRE_REPLY)
@pytest.mark.parametrize('stop', [False, True])
async def test_started_save_still_drains_after_deadline_without_starting_later_calls(tmp_path, monkeypatch, kind, stop):
    now = [100.0]
    monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda: now[0]))
    entered, release = threading.Event(), threading.Event()
    dispatched, requests = [], []
    original = ToolExecutor._execute

    def held(self, name, args):
        dispatched.append((name, args.get('path')))
        entered.set()
        assert release.wait(5), 'Test did not release the started file operation'
        return original(self, name, args)

    monkeypatch.setattr(ToolExecutor, '_execute', held)

    async def handler(request):
        requests.append(await request.json())
        return WIRE_REPLY[kind]([
            ('started', 'write_text', {'path': 'started.txt', 'text': 'Drained output', 'expected_sha256': 'missing'}),
            ('later', 'write_text', {'path': 'later.txt', 'text': 'Must not start', 'expected_sha256': 'missing'}),
            ('finish', 'finish_work', {'summary': 'Must not report completion'}),
        ])

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        settings.value['limits']['max_run_seconds'] = 10
        engine = Engine(settings)
        stopping = None
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            assert await asyncio.to_thread(entered.wait, 3)
            now[0] += 10
            assert engine.lock.locked() and not agent.output_receipts
            if stop:
                stopping = asyncio.create_task(engine.stop_run(run['id']))
                await eventually(lambda: run['status'] == 'stopping', engine)
                assert not stopping.done() and engine.lock.locked()
            release.set()
            if stopping:
                await stopping
            await settled(engine)
            assert dispatched == [('write_text', 'started.txt')]
            assert (work / 'started.txt').read_text() == 'Drained output'
            assert not (work / 'later.txt').exists()
            assert len(agent.output_receipts) == 1 and not agent.results
            assert len(requests) == run['model_calls'] == run['tool_calls'] == agent.turns == 1
            assert not engine.lock.locked() and engine.reservations == {}
            if stop:
                assert agent.status == run['status'] == 'stopped'
            else:
                assert agent.status == 'error' and run['status'] == 'waiting'
                results = [item for item in agent.conversation if item['role'] == 'tool']
                assert [item['tool_call_id'] for item in results] == ['started', 'later', 'finish']
                assert json.loads(results[0]['content']).get('ok') is not False
                assert all(json.loads(item['content'])['ok'] is False for item in results[1:])
        finally:
            release.set()
            if stopping:
                await asyncio.gather(stopping, return_exceptions=True)
            await engine.close()
