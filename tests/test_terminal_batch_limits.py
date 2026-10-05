"""Terminal batch closure is distinct from admitting another tool at a limit."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import workbench.engine as engine_module
from workbench.config import DEFAULT
from workbench.engine import Engine
from test_engine import start
from test_engine_integration import api_server, configured_settings, local_reply, openai_reply, anthropic_reply


WIRE_REPLY = {'local': local_reply, 'openai': openai_reply, 'anthropic': anthropic_reply}
TERMINALS = {'finish_work': {'summary': 'Verified terminal report'}, 'ask_user': {'question': 'Human decision?'}}


@pytest.fixture(autouse=True)
def synthetic_credentials_only(monkeypatch):
    for profile in [*DEFAULT['providers'], DEFAULT['search']]:
        if profile['api_key_env']:
            monkeypatch.delenv(profile['api_key_env'], raising=False)


def batch(terminal, arguments):
    return [('terminal', terminal, arguments),
            ('write', 'write_text', {'path': 'must-not-exist.txt', 'text': 'Not executed', 'expected_sha256': 'missing'}),
            ('later-question', 'ask_user', {'question': 'Must not replace the first question'})]


async def complete_turn(agent):
    # The provider and Engine determine completion; the timeout only detects hangs.
    await asyncio.wait_for(asyncio.shield(agent.task), 10)


@pytest.mark.parametrize('kind', WIRE_REPLY)
@pytest.mark.parametrize('terminal', TERMINALS)
@pytest.mark.parametrize('boundary', ['tool_limit', 'deadline_exact', 'deadline_after'])
async def test_successful_terminal_keeps_its_state_when_remaining_calls_are_skipped(
        tmp_path, monkeypatch, kind, terminal, boundary):
    now, requests = [100.0], []
    monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda: now[0]))

    async def handler(request):
        requests.append(await request.json())
        if len(requests) == 1:
            return WIRE_REPLY[kind](batch(terminal, TERMINALS[terminal]))
        assert boundary == 'tool_limit' and len(requests) == 2
        return WIRE_REPLY[kind](text='Explicit human continuation, without more tools')

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        settings.value['limits']['max_run_seconds'] = 10
        if boundary == 'tool_limit':
            settings.value['limits']['max_tool_calls'] = 1
        engine = Engine(settings)
        original = engine.execute_tool

        async def execute(run, agent, name, arguments):
            result = await original(run, agent, name, arguments)
            if name == terminal and result.get('ok') is not False and boundary != 'tool_limit':
                # Cross the deadline only after this terminal tool succeeds.
                now[0] = 110.0 if boundary == 'deadline_exact' else 110.001
            return result

        monkeypatch.setattr(engine, 'execute_tool', execute)
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await complete_turn(agent)
            expected = 'done' if terminal == 'finish_work' else 'waiting'
            assert run['status'] == agent.status == expected and not agent.last_error
            assert agent.question == (TERMINALS[terminal]['question'] if terminal == 'ask_user' else '')
            assert len(agent.results) == int(terminal == 'finish_work')
            assert (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.turns) == (1, 1, 0, 1)
            results = [item for item in agent.conversation if item['role'] == 'tool']
            assert [item['tool_call_id'] for item in results] == ['terminal', 'write', 'later-question']
            assert json.loads(results[0]['content'])['ok'] is True
            assert all(json.loads(item['content']) == {'ok': False, 'error': 'Not executed: this turn is paused or finished.'}
                       for item in results[1:])
            assert not (work / 'must-not-exist.txt').exists() and not agent.output_receipts
            assert not engine.reservations and not engine.lock.locked()

            if boundary == 'tool_limit':
                # Spent tools stay spent, but existing text-only continuation remains legal.
                await engine.human_message(agent.id, 'Explicit human continuation')
                await complete_turn(agent)
                assert (run['model_calls'], run['tool_calls'], agent.turns) == (2, 1, 2)
                assert agent.status == run['status'] == 'done' and not agent.question
                assert len(agent.results) == int(terminal == 'finish_work') + 1
            else:
                before = (run['model_calls'], run['tool_calls'], agent.turns, agent.result_revision)
                with pytest.raises(ValueError, match='実行時間'):
                    await engine.human_message(agent.id, 'Cannot restart an expired run')
                assert (run['model_calls'], run['tool_calls'], agent.turns, agent.result_revision) == before
                assert len(requests) == 1
        finally:
            await engine.close()


@pytest.mark.parametrize('kind', WIRE_REPLY)
@pytest.mark.parametrize('terminal', TERMINALS)
async def test_rejected_terminal_does_not_suppress_real_tool_budget_exhaustion(tmp_path, kind, terminal):
    invalid = {next(iter(TERMINALS[terminal])): ' '}

    async def handler(request):
        await request.json()
        return WIRE_REPLY[kind](batch(terminal, invalid))

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        settings.value['limits']['max_tool_calls'] = 1
        engine = Engine(settings)
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await complete_turn(agent)
            assert run['status'] == 'waiting' and agent.status == 'error'
            assert 'ツール実行回数' in agent.last_error and not agent.question and not agent.results
            assert (run['model_calls'], run['tool_calls']) == (1, 1)
            results = [json.loads(item['content']) for item in agent.conversation if item['role'] == 'tool']
            assert len(results) == 3 and all(item['ok'] is False for item in results)
            assert all('ツール実行回数' in item['error'] for item in results[1:])
            assert not (work / 'must-not-exist.txt').exists() and not agent.output_receipts
        finally:
            await engine.close()


@pytest.mark.parametrize('kind', WIRE_REPLY)
@pytest.mark.parametrize('terminal', TERMINALS)
async def test_expiry_before_terminal_dispatch_still_executes_no_tools(tmp_path, monkeypatch, kind, terminal):
    now = [100.0]
    monkeypatch.setattr(engine_module, 'time', SimpleNamespace(time=lambda: now[0]))

    async def handler(request):
        await request.json()
        now[0] = 110.0
        return WIRE_REPLY[kind](batch(terminal, TERMINALS[terminal]))

    async with api_server(handler) as endpoint:
        settings, work = configured_settings(tmp_path, endpoint)
        settings.value['limits']['max_run_seconds'] = 10
        engine = Engine(settings)
        try:
            run, agent = await start(engine, pm_profile=kind, max_workers=0)
            await complete_turn(agent)
            assert run['status'] == 'waiting' and agent.status == 'error'
            assert run['model_calls'] == 1 and run['tool_calls'] == 0
            assert not agent.question and not agent.results and not agent.output_receipts
            results = [json.loads(item['content']) for item in agent.conversation if item['role'] == 'tool']
            assert len(results) == 3 and all(item['ok'] is False and '実行時間' in item['error'] for item in results)
            assert not (work / 'must-not-exist.txt').exists()
        finally:
            await engine.close()
