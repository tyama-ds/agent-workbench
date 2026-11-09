"""Agents keep going: correctable errors return to the model, workers are nudged
once instead of stopping on narration, oversized tool output stays bounded, and
network paths are rejected before any filesystem access."""
import json
from pathlib import Path, PureWindowsPath

import pytest

from workbench.config import preview_settings_import, DEFAULT
from workbench.dependencies import DependencyBlocked
from workbench.engine import CONTINUATION_NUDGE, bounded_tool_output
from workbench.harness import HarnessError, _literal_path
from test_engine import configured, reply, settled, start


@pytest.mark.parametrize('value', ['\\/attacker/share/x', '/\\attacker/share/x', '//attacker/share/x',
                                   '\\\\attacker\\share\\x', '\\\\?\\C:\\x', '\\\\.\\pipe\\x'])
def test_every_unc_and_device_spelling_is_rejected_before_filesystem_access(value, monkeypatch):
    assert PureWindowsPath(value).drive.startswith(('\\', '/')) or value.replace('/', '\\').startswith('\\\\')
    monkeypatch.setattr(Path, 'lstat', lambda self: pytest.fail('filesystem touched'))
    monkeypatch.setattr(Path, 'exists', lambda self: pytest.fail('filesystem touched'))
    with pytest.raises(HarnessError, match='UNC'):
        _literal_path(value)


def test_settings_preview_rejects_unc_roots_without_touching_the_path(monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: pytest.fail('preview touched a backup path'))
    monkeypatch.setattr(Path, 'is_dir', lambda self: pytest.fail('preview touched a backup path'))
    for root in ('\\\\attacker\\share\\x', '\\/attacker/share/x'):
        backup = json.loads(json.dumps(DEFAULT))
        backup['paths']['read_roots'] = [root]
        with pytest.raises(ValueError):
            preview_settings_import(backup)


def test_bounded_tool_output_keeps_head_and_tail_and_small_results_unchanged():
    small = json.dumps({'ok': True, 'text': 'short'})
    assert bounded_tool_output(small, {'max_context_chars': 100000}) == small
    large = json.dumps({'ok': True, 'text': 'HEAD' + 'x' * 100000 + 'TAIL'})
    bounded = json.loads(bounded_tool_output(large, {'max_context_chars': 100000}, record_id=7))
    assert bounded['truncated_for_context'] is True and bounded['record_id'] == 7
    assert bounded['original_chars'] == len(large)
    assert 'HEAD' in bounded['head'] and 'TAIL' in bounded['tail']
    assert len(json.dumps(bounded)) < 30000


class RoleClient:
    """PM delegates; the worker narrates a next step once before finishing."""

    def __init__(self):
        self.calls = []

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        self.calls.append(messages)
        mine = sum(1 for m in messages if m['role'] == 'assistant')
        if messages[0]['content'] == 'Perform assigned work':
            if mine == 0:
                return reply(calls=[('spawn_worker', {'role': 'writer', 'task': 'Write the report', 'profile_id': 'local'})])
            return reply('PM summary after worker report.')
        if mine == 0:
            return reply(calls=[('list_team', {})])
        if mine == 1:
            return reply('次にレポートを書きます。')
        assert messages[-1]['content'] == CONTINUATION_NUDGE
        return reply(calls=[('finish_work', {'summary': 'Report written and verified.'})])


@pytest.mark.asyncio
async def test_worker_prose_after_tools_is_nudged_once_into_a_formal_report(tmp_path):
    client = RoleClient()
    engine, _ = configured(tmp_path, client)
    try:
        run, pm = await start(engine)
        await settled(engine)
        worker = next(engine.agents[a] for a in run['agent_ids'] if engine.agents[a].parent_id == pm.id)
        assert worker.status == 'done' and pm.status == 'done', (worker.last_error, pm.last_error)
        assert any(m['role'] == 'user' and m['content'] == CONTINUATION_NUDGE for m in worker.conversation)
        assert any(row.get('source') == 'finish_work' for row in worker.results)
        # The PM's own plain-text final answer is never nudged.
        assert not any(m.get('content') == CONTINUATION_NUDGE for m in pm.conversation)
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_reviewing_a_blocked_child_is_a_tool_error_not_a_pause_of_the_reviewer(tmp_path):
    engine, _ = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        result = await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'writer', 'task': 'Write', 'profile_id': 'local'})
        worker = engine.agents[result['agent_id']]
        original = engine._dependency_require

        def require(agent):
            if agent is worker:
                raise DependencyBlocked(stale=True)
            return original(agent)
        engine._dependency_require = require
        with pytest.raises(ValueError) as caught:
            await engine.execute_tool(run, pm, 'review_worker_report', {
                'worker_id': worker.id, 'result_revision': 1, 'decision': 'accept', 'feedback': 'ok'})
        assert not isinstance(caught.value, DependencyBlocked)
        assert 'send_message' in str(caught.value) and 'dependency_stale' in str(caught.value)
    finally:
        await engine.close()
