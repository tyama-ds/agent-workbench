"""Test-only loopback server: real HTTP/engine, deterministic synthetic model.

Not installed as a runtime entrypoint. No model network client is constructed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
from pathlib import Path

from aiohttp import web
from workbench.engine import Agent
from workbench.providers import ModelReply
from workbench.server import BrowserAuth, create_app


REDACTION_CASES = {
    'memory': {'old': 'WB9-memory-retired-exact-57b82', 'new': 'WB9-memory-current-exact-a9014'},
    'environment': {'old': 'WB9-env-retired-exact-402d7', 'new': 'WB9-env-current-exact-f83c1',
                    'old_env': 'WORKBENCH_BROWSER_SYNTHETIC_OLD',
                    'new_env': 'WORKBENCH_BROWSER_SYNTHETIC_NEW'},
}


class SyntheticClient:
    """Exercise real worker creation, mail, human questions and cancellation."""

    def __init__(self):
        self.calls = {}

    async def complete(self, profile, messages, tools, system, limits):
        identity = json.loads(system.rsplit('\n', 1)[1])
        ident = identity['id']
        count = self.calls.get(ident, 0)
        self.calls[ident] = count + 1
        calls = []
        initial = messages[0].get('content', '') if messages else ''
        retained_case = next((name for name in REDACTION_CASES if initial.startswith(tuple(
            f'[SYNTHETIC] Retained {kind} {name} ' for kind in ('credential', 'worker', 'replay')))), None)
        if retained_case:
            case = REDACTION_CASES[retained_case]
            replay = initial.startswith('[SYNTHETIC] Retained replay ')
            current = replay or (retained_case == 'memory' and not identity['parent_id'] and count > 0)
            if profile.get('api_key') != case['new' if current else 'old']:
                raise AssertionError('Synthetic redaction fixture received an obsolete authentication key')
            marker = case['old']
            if not identity['parent_id'] and not replay and count == 0:
                calls = [
                    ('spawn_worker', {'task': f'[SYNTHETIC] Retained worker {retained_case} {marker}',
                                      'role': 'retained-' + marker, 'profile_id': 'local'}),
                    ('ask_user', {'question': '[SYNTHETIC] Historical question ' + marker}),
                ]
            elif (identity['parent_id'] or replay) and count == 0:
                calls = [('write_text', {'path': str(Path(identity['write_roots'][0]) /
                                                    f'browser-retained-{retained_case}-{"replay-" if replay else ""}{marker}.txt'),
                                        'text': '[SYNTHETIC] Safe saved bytes.',
                                        'expected_sha256': 'missing'})]
            else:
                return ModelReply(text='[SYNTHETIC] Historical report ' + marker +
                                  ('; current authentication verified.' if current else '.'),
                                  thinking='[SYNTHETIC] Private historical reasoning ' + marker,
                                  tool_calls=[], usage={}, raw={'private': marker})
            return ModelReply(text='[SYNTHETIC] Historical log ' + marker,
                              thinking='[SYNTHETIC] Private historical reasoning ' + marker,
                              tool_calls=[{'id': f'retained-{count}-{i}', 'name': name, 'arguments': args}
                                          for i, (name, args) in enumerate(calls)], usage={}, raw={'private': marker})
        if messages and messages[0].get('content') == '[SYNTHETIC] Save result.':
            if count == 0:
                calls = [('write_text', {'path': str(Path(identity['write_roots'][0]) / 'browser-result.txt'),
                                        'text': '[SYNTHETIC] Saved text 日本語.', 'expected_sha256': 'missing'})]
            else:
                return ModelReply(text='[SYNTHETIC] Terminal answer 日本語.', thinking='PRIVATE-REASONING-FIXTURE',
                                  tool_calls=[], usage={}, raw={'protocol': 'PRIVATE-PROTOCOL-FIXTURE'})
        elif messages and messages[0].get('content') == '[SYNTHETIC] Complete immediately.':
            calls = []
        elif identity['parent_id']:
            calls = [('finish_work', {'summary': '[SYNTHETIC] Worker review complete.'})]
        elif count == 0:
            calls = [
                ('spawn_worker', {'task': '[SYNTHETIC] Review fixture only.', 'role': 'fixture-review', 'profile_id': 'local'}),
                ('ask_user', {'question': '[SYNTHETIC] Continue this test run?'}),
            ]
        else:
            # Deliberately remain active until the real stop endpoint cancels us.
            await asyncio.Event().wait()
        return ModelReply(text='[SYNTHETIC] Browser integration fixture.', thinking='',
                          tool_calls=[{'id': f'fixture-{count}-{i}', 'name': name, 'arguments': args}
                                      for i, (name, args) in enumerate(calls)], usage={}, raw={})


async def serve(directory):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.setblocking(False)
    auth = BrowserAuth(listener.getsockname()[1])
    runner = web.AppRunner(create_app(Path(directory), auth, client=SyntheticClient()), access_log=None)
    await runner.setup()
    await web.SockSite(runner, listener).start()
    print(auth.launch_url, flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        listener.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir')
    parser.add_argument('--agent-contract', action='store_true')
    parser.add_argument('--redaction-contract', action='store_true')
    args = parser.parse_args()
    if args.agent_contract:
        print(json.dumps(Agent('id', 'run', 'name', 'pm', 'local').public()))
    elif args.redaction_contract:
        print(json.dumps(REDACTION_CASES))
    elif args.state_dir:
        asyncio.run(serve(args.state_dir))
    else:
        parser.error('--state-dir required')
