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
        if identity['parent_id']:
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
    args = parser.parse_args()
    if args.agent_contract:
        print(json.dumps(Agent('id', 'run', 'name', 'pm', 'local').public()))
    elif args.state_dir:
        asyncio.run(serve(args.state_dir))
    else:
        parser.error('--state-dir required')
