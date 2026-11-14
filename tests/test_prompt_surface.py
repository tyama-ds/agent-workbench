"""Snapshot of what the model receives on every call (after hermes-agent's
prompt-surface check). Tool schemas and system prompts are sent with every
request, and several fixtures are tuned to their size, so any change must be
a reviewable diff. Regenerate after an intended change with:

    AWB_UPDATE_PROMPT_SURFACE=1 python -m pytest -q tests/test_prompt_surface.py
"""
import json
import os
import re
from pathlib import Path

import pytest

from test_engine import configured, start

SNAPSHOT = Path(__file__).parent / 'fixtures' / 'prompt_surface.json'
IDENTITY = '\n\nVerified runtime identity and user-selected scope:\n'


def stable_system(text):
    """Mask run-specific values: the identity JSON line (ids, paths, live budget)."""
    if IDENTITY in text:
        head, tail = text.split(IDENTITY, 1)
        rest = tail.split('\n', 1)[1] if '\n' in tail else ''
        text = head + IDENTITY + '<identity>' + ('\n' + rest if rest else '')
    return re.sub(r'\b[ar]-[0-9a-f]{16}\b', '<id>', text)


async def surface(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='Snapshot task: summarize the files.')
        spawned = await engine.execute_tool(run, pm, 'spawn_worker', {
            'role': 'writer', 'task': 'Snapshot assignment.', 'profile_id': 'local'})
        worker = engine.agents[spawned['agent_id']]
        result = {}
        for name, agent in (('pm', pm), ('worker', worker)):
            tools = engine._model_tools(run, agent)
            system = stable_system(engine._policy(run, agent))
            result[name] = {'tool_chars': len(json.dumps(tools, ensure_ascii=False, sort_keys=True)),
                            'system_chars': len(system), 'tools': tools, 'system': system}
        return result
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_prompt_surface_matches_the_reviewed_snapshot(tmp_path):
    current = await surface(tmp_path)
    if os.environ.get('AWB_UPDATE_PROMPT_SURFACE') == '1':
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    expected = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    for name in expected:
        assert current[name]['tool_chars'] == expected[name]['tool_chars'], (
            f'{name} tool schemas changed size; review and regenerate the snapshot')
        assert current[name]['system_chars'] == expected[name]['system_chars'], (
            f'{name} system prompt changed size; review and regenerate the snapshot')
        assert current[name] == expected[name]
