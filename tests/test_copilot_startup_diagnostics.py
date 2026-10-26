"""Startup control-flow tests; no account, browser or real subprocess."""
import asyncio
import pytest
from workbench import copilot_bridge as cb
from test_copilot_bridge import CONFIG, OBSERVED, setup, no_real_processes


async def test_initial_probe_failure_identifies_prelaunch_and_does_not_spawn(setup, tmp_path):
    setup['responses'] = [cb.BridgeFailure('connection_failed', '確認がタイムアウトしました。')]
    result = await cb.CopilotBridgeManager(tmp_path).sync(CONFIG)
    assert result['stage'] == 'existing_bridge_probe'
    assert '起動前' in result['message']
    assert setup['spawned'] == []


async def test_owned_startup_transient_probe_recovers_without_second_child(setup, tmp_path):
    setup['responses'] = [None, cb.BridgeFailure('connection_failed', 'timeout'), OBSERVED]
    manager = cb.CopilotBridgeManager(tmp_path)
    result = await manager.sync(CONFIG)
    assert result['ready'] and result['owned']
    assert len(setup['spawned']) == 1 and setup['spawned'][0].stops == 0
    await manager.close()
    assert setup['spawned'][0].stops == 1


async def test_owned_probe_failures_remain_within_total_deadline(setup, tmp_path, monkeypatch):
    setup['responses'] = [None, cb.BridgeFailure('connection_failed', 'timeout')]
    real_wait = asyncio.wait_for
    async def short_wait(awaitable, timeout):
        assert timeout == 600
        return await real_wait(awaitable, .02)
    monkeypatch.setattr(cb.asyncio, 'wait_for', short_wait)
    result = await cb.CopilotBridgeManager(tmp_path).sync(CONFIG)
    assert result['code'] == 'startup_timeout'
    assert result['stage'] == 'owned_bridge_probe'
    assert '起動後' in result['message']
    assert len(setup['spawned']) == 1 and setup['spawned'][0].stops == 1


@pytest.mark.parametrize('code', ['invalid_response', 'unexpected_service', 'bridge_error'])
async def test_owned_contract_errors_are_terminal_without_retry(setup, tmp_path, code):
    setup['responses'] = [None, cb.BridgeFailure(code, 'contract rejected'), OBSERVED]
    result = await cb.CopilotBridgeManager(tmp_path).sync(CONFIG)
    assert result['code'] == code and not result['ready']
    assert setup['probes'] == 2
    assert len(setup['spawned']) == 1 and setup['spawned'][0].stops == 1


def test_standard_for_eigyo_checkout_is_discovered(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, 'ROOT', tmp_path / 'agent-workbench')
    directory = tmp_path / 'for_eigyo' / 'copilot-bridge'
    (directory / 'bridge').mkdir(parents=True)
    for relative in ('server.py', 'bridge/config.py', 'bridge/edge.py'):
        (directory / relative).touch()
    assert cb._bridge_directory('') == directory.resolve()


async def test_existing_bridge_is_borrowed_without_startup_path_changes(setup, tmp_path):
    setup['responses'] = [OBSERVED]
    manager = cb.CopilotBridgeManager(tmp_path)
    result = await manager.sync(CONFIG)
    assert result['ready'] and result['borrowed'] and not result['owned']
    assert setup['spawned'] == []
    await manager.close()


async def test_unknown_startup_error_does_not_expose_exception_payload(setup, tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError('SECRET=credentials')
    monkeypatch.setattr(cb, '_spawn_owned', fail)
    result = await cb.CopilotBridgeManager(tmp_path).sync(CONFIG)
    assert result['stage'] == 'starting_bridge'
    assert 'SECRET' not in str(result)
    assert not result['ready']
