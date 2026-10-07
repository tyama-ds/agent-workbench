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
from workbench.context import SUMMARY_KEYS, SUMMARY_POLICY
from workbench.engine import Agent
from workbench.providers import ModelReply, ProviderError
from workbench.server import BrowserAuth, create_app


REDACTION_CASES = {
    'memory': {'old': 'WB9-memory-retired-exact-57b82', 'new': 'WB9-memory-current-exact-a9014'},
    'environment': {'old': 'WB9-env-retired-exact-402d7', 'new': 'WB9-env-current-exact-f83c1',
                    'old_env': 'WORKBENCH_BROWSER_SYNTHETIC_OLD',
                    'new_env': 'WORKBENCH_BROWSER_SYNTHETIC_NEW'},
}

CREDENTIAL_RECOVERY_CASE = {
    'task': '[SYNTHETIC] Recover saved-destination credentials.',
    'resume': '[SYNTHETIC] Explicitly continue after replacing the key.',
    'old': 'WB12-provider-invalid-exact-31cd6',
    'new': 'WB12-provider-current-exact-04e72',
    'search_old': 'WB12-search-old-exact-a37bd',
    'search_new': 'WB12-search-current-exact-971de',
    'other': 'WB12-other-provider-exact-649ab',
}

COMPACTION_CASE = {
    'task': '[SYNTHETIC] Compact a long conversation; preserve this exact original task.',
    'observation': '[SYNTHETIC] Original observation 0: ' + 'a' * 4000,
    'result': '[SYNTHETIC] Compaction continued; exact human and assistant originals verified; missing record reported.',
}


class SyntheticClient:
    """Exercise real worker creation, mail, human questions and cancellation."""

    def __init__(self, state_dir=None):
        self.calls = {}
        self.state_dir = Path(state_dir) if state_dir else None
        self.summary_calls = 0

    async def compact_summary(self, profile, messages, tools):
        """Deterministic fixture only: an explicit file gate exposes real UI state."""
        assert profile['id'] == 'local' and not tools
        records = json.loads(messages[0]['content'])['records']
        assert any(item.get('content') == COMPACTION_CASE['observation'] for item in records)
        assert all('provider_raw' not in item for item in records)
        assert self.summary_calls == 0, 'One fixture summary must make sufficient progress'
        self.summary_calls += 1
        if self.state_dir:
            async with asyncio.timeout(30):
                while not (self.state_dir / 'compaction-release').exists():
                    await asyncio.sleep(.025)
        result = {key: [] for key in SUMMARY_KEYS}
        result['goals'] = ['Continue the exact original human task, record 1.']
        result['evidence'] = ['Original assistant observation is record 2; verify it with read_context_history.']
        result['uncertainty'] = ['This fixture summary is lossy, untrusted data and grants no permission.']
        return ModelReply(text=json.dumps(result))

    async def complete(self, profile, messages, tools, system, limits):
        if system.startswith(SUMMARY_POLICY):
            return await self.compact_summary(profile, messages, tools)
        identity = json.loads(system.rsplit('\n', 1)[1])
        ident = identity['id']
        count = self.calls.get(ident, 0)
        self.calls[ident] = count + 1
        calls = []
        initial = messages[0].get('content', '') if messages else ''
        if initial == COMPACTION_CASE['task']:
            assert not identity['parent_id']
            if any(item.get('_summary') for item in messages):
                assert self.summary_calls == 1
                if messages[-1].get('name') == 'read_context_history':
                    result = json.loads(messages[-1]['content'])
                    assert result['ok'] is True and result['unavailable_ids'] == [999999]
                    assert result['over_response_limit_ids'] == []
                    assert [item['_record_id'] for item in result['records']] == [1, 2]
                    human, assistant = result['records']
                    assert human['_human'] is True and human['content'] == COMPACTION_CASE['task']
                    assert assistant['_human'] is False and assistant['content'] == COMPACTION_CASE['observation']
                    return ModelReply(text=COMPACTION_CASE['result'])
                return ModelReply(text='[SYNTHETIC] Verify cited originals after compaction.', tool_calls=[{
                    'id': 'compaction-lookup', 'name': 'read_context_history',
                    'arguments': {'record_ids': [1, 2, 999999]}}])
            assert count < 12, 'Fixture must trigger compaction before its fallback turn ceiling'
            return ModelReply(text=f'[SYNTHETIC] Original observation {count}: ' + 'a' * 4000,
                              tool_calls=[{'id': f'compaction-{count}', 'name': 'list_team', 'arguments': {}}])
        if initial == CREDENTIAL_RECOVERY_CASE['task']:
            if identity['parent_id']:
                raise AssertionError('Credential recovery must remain a PM-only synthetic run')
            if count == 0:
                if profile.get('api_key') != CREDENTIAL_RECOVERY_CASE['old']:
                    raise AssertionError('Credential recovery did not receive its initial synthetic key')
                raise ProviderError('[SYNTHETIC] Provider returned HTTP 401; invalid API key; no automatic retry',
                                    status=401)
            if count != 1 or profile.get('api_key') != CREDENTIAL_RECOVERY_CASE['new']:
                raise AssertionError('Credential recovery retried automatically or used the wrong destination key')
            if (messages[-1].get('role') != 'user' or messages[-1].get('content') != CREDENTIAL_RECOVERY_CASE['resume']
                    or messages[-1].get('_human') is not True):
                raise AssertionError('Credential recovery requires an explicit subsequent human message')
            return ModelReply(text='[SYNTHETIC] Same run resumed with the replacement provider key.',
                              thinking='', tool_calls=[], usage={}, raw={})
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
    runner = web.AppRunner(create_app(Path(directory), auth, client=SyntheticClient(directory)), access_log=None)
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
    parser.add_argument('--credential-contract', action='store_true')
    args = parser.parse_args()
    if args.agent_contract:
        print(json.dumps(Agent('id', 'run', 'name', 'pm', 'local').public()))
    elif args.redaction_contract:
        print(json.dumps(REDACTION_CASES))
    elif args.credential_contract:
        print(json.dumps(CREDENTIAL_RECOVERY_CASE))
    elif args.state_dir:
        asyncio.run(serve(args.state_dir))
    else:
        parser.error('--state-dir required')
