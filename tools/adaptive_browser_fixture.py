"""Fresh, owned adaptive-team browser fixture; synthetic inference, real app.

Only the smoke driver starts this module. Its two application lifetimes share a
new evidence directory to check persisted display history. Nothing is deleted.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
import traceback

from aiohttp import web

from tools.browser_fixture import synthetic_native
from workbench.config import DEFAULT, validate_settings
from workbench.providers import ModelReply
from workbench.runtime_paths import RESOURCE_ROOT
from workbench.server import APP_KEY, BrowserAuth, create_app


MANUAL = '[SYNTHETIC-ADAPTIVE-UI] Manual compatibility.'
ADAPTIVE = '[SYNTHETIC-ADAPTIVE-UI] Save result.txt containing value 42 and independently review it.'
FINAL = 'The requested local output was saved and independently reviewed against its current bytes.'
CONTENT = 'source=synthetic-fixture\nvalue=42\n'
LIMITS = {'max_workers': 2, 'max_model_calls': 24, 'max_tool_calls': 60,
          'max_auto_collaborations': 24, 'max_turns_per_agent': 20,
          'max_run_seconds': 3600, 'max_output_tokens': 2048}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def emit(kind, **values):
    print(json.dumps({'kind': kind, **values}, ensure_ascii=False), flush=True)


def external_directory(path):
    path = Path(path).absolute()
    require(path.is_absolute() and not path.is_symlink(), 'Explicit non-symlink output required')
    for parent in (path, *path.parents):
        if parent.exists():
            require(not getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400,
                    'Reparse paths are not fixture workspaces')
    resource = Path(RESOURCE_ROOT).resolve()
    require(path != resource and resource not in path.parents, 'Output must be outside application resources')
    return path


def check_file_result(name, value, workspace, reviewer_candidate=None):
    require(type(value) is dict, 'Tool result must be an object')
    data = CONTENT.encode('utf-8')
    if name == 'write_text':
        require(set(value) == {'path', 'bytes', 'sha256', 'operation'}, 'Unexpected write receipt')
        require(type(value['bytes']) is int and value['bytes'] == len(data) and value['operation'] == 'created',
                'Write receipt length/operation mismatch')
    elif name == 'read_text':
        keys = {'path', 'text', 'truncated', 'sha256'}
        if reviewer_candidate is not None:
            keys.add('independent_review_read')
            marker = value.get('independent_review_read')
            require(type(marker) is dict and set(marker) == {'candidate_id', 'observation_id', 'coverage'} and
                    marker['candidate_id'] == reviewer_candidate and
                    type(marker['observation_id']) is str and re.fullmatch(r'o-[0-9a-f]{24}', marker['observation_id']) is not None and
                    marker['coverage'] == 'content exposure, not exhaustive verification', 'Independent read marker mismatch')
        require(set(value) == keys, 'Unexpected read receipt')
        require(value['text'] == CONTENT and value['truncated'] is False, 'Read content differs or is truncated')
    else:
        require(value.get('ok') is True, 'Actual tool failed: ' + name)
        return
    require(value['path'] == str(workspace / 'result.txt') and
            value['sha256'] == hashlib.sha256(data).hexdigest(), 'Actual file path/SHA mismatch')


class ScriptedClient:
    def __init__(self, workspace, archive_only=False):
        self.engine = None
        self.workspace = workspace
        self.archive_only = archive_only
        self.calls = []
        self.active = 0
        self.review_release = asyncio.Event()
        self.finish_release = asyncio.Event()

    async def complete(self, profile, messages, tools, system, limits, *, conversation_id=None):
        self.active += 1
        try:
            require(not self.archive_only, 'Archive browsing must never invoke a model')
            require(conversation_id and '/' in conversation_id, 'Exact conversation identity required')
            run_id, agent_id = conversation_id.split('/')
            engine = self.engine
            run, agent = engine.runs[run_id], engine.agents[agent_id]
            names = {tool['name'] for tool in tools}
            self.calls.append({'agent_id': agent_id, 'run_id': run_id, 'kind': agent.kind,
                               'tools': sorted(names), 'messages': copy.deepcopy(messages)})
            require(len(self.calls) <= 13, 'Finite synthetic script exceeded 13 requests')
            for message in messages:
                if message.get('role') == 'tool':
                    value = json.loads(message['content'])
                    candidate_id = (run['formation']['candidate']['id'] if agent.kind == 'independent_reviewer' else None)
                    check_file_result(message['name'], value, self.workspace, candidate_id)

            def reply(calls):
                require(all(name in names for name, _ in calls), 'Script tried a tool absent from this request')
                native = [{'id': f'fixture-{len(self.calls)}-{index}', 'name': name, 'arguments': args}
                          for index, (name, args) in enumerate(calls)]
                text = '[SYNTHETIC] Finite fixture response; no model inference.'
                return ModelReply(text=text, tool_calls=native, raw=synthetic_native(profile, text, native))

            if run['task'] == MANUAL:
                require(not run.get('adaptive_team') and agent.kind != 'independent_reviewer', 'Manual mode changed')
                return reply([('finish_work', {'summary': 'Manual compatibility confirmed by a synthetic response.'})])
            require(run['task'] == ADAPTIVE and run['adaptive_team'] is True, 'Unexpected fixture task')
            formation = run['formation']
            if agent_id in run['pm_agent_ids']:
                if formation['phase'] == 'unplanned':
                    return reply([('plan_team', {'difficulty': 'low', 'reason': 'One bounded local text artifact',
                        'reviewer_profile_id': 'local', 'assignments': [{'key': 'write', 'role': 'writer',
                            'task': 'Save result.txt with the fixture value 42 and report its native receipt.', 'profile_id': 'local'}]})])
                if formation['phase'] == 'accepted':
                    await asyncio.wait_for(self.finish_release.wait(), 60)
                    return reply([('finish_work', {'summary': FINAL})])
                workers = [engine.agents[key] for key in formation['worker_ids']]
                if any(child.status != 'done' or agent.worker_report_consumed.get(child.id) != child.result_revision for child in workers):
                    return reply([('wait_for_workers', {})])
                pending = [child for child in workers if agent.worker_report_reviews.get(child.id) !=
                           {'result_revision': child.result_revision, 'decision': 'accept'}]
                if pending:
                    return reply([('review_worker_report', {'worker_id': child.id, 'result_revision': child.result_revision,
                        'decision': 'accept', 'feedback': 'Current native save receipt matches the assigned fixture value.'}) for child in pending])
                require(formation['phase'] == 'working', 'PM attempted a review from an unexpected phase')
                return reply([('request_independent_review', {'summary': FINAL, 'artifact_paths': []})])
            if agent.kind == 'independent_reviewer':
                require(not names & {'write_text', 'ask_user', 'send_message', 'spawn_worker', 'finish_work'},
                        'Reviewer received an author or human-question capability')
                candidate = formation['candidate']
                require(candidate['artifact_count'] == 1, 'Recorded output must be included despite empty explicit paths')
                reads = [json.loads(message['content']) for message in messages
                         if message.get('role') == 'tool' and message.get('name') == 'read_text']
                if not reads:
                    await asyncio.wait_for(self.review_release.wait(), 60)
                    return reply([('read_text', {'path': 'result.txt'})])
                require(candidate['read_count'] == candidate['consumed_read_count'] == 1,
                        'Accept must follow native read exposure in a subsequent request')
                return reply([('submit_independent_review', {'candidate_id': candidate['id'], 'decision': 'accept',
                    'feedback': 'Compared the exposed current text with the requested fixture value 42.'})])
            wrote = any(message.get('role') == 'tool' and message.get('name') == 'write_text' for message in messages)
            return reply([('finish_work', {'summary': 'Saved result.txt; current native bytes and SHA were checked.'})]
                         if wrote else [('write_text', {'path': 'result.txt', 'text': CONTENT, 'expected_sha256': 'missing'})])
        finally:
            self.active -= 1


async def verify_live(engine, client, workspace):
    require(len(engine.runs) == 2, 'Exactly manual and adaptive runs are expected')
    manual = next(run for run in engine.runs.values() if run['task'] == MANUAL)
    run = next(run for run in engine.runs.values() if run['task'] == ADAPTIVE)
    require(manual['status'] == run['status'] == 'done' and run['formation']['phase'] == 'complete', 'Runs not completed')
    require('adaptive_team' not in manual and 'formation' not in manual, 'Manual public shape changed')
    require(len(run['agent_ids']) == 3 and len(run['pm_agent_ids']) == 1, 'Unexpected team size')
    formation = run['formation']
    candidate = formation['candidate']
    require(candidate['artifact_count'] == candidate['read_count'] == candidate['consumed_read_count'] == 1 and
            candidate['decision'] == 'accept' and candidate['summary_sha256'] == hashlib.sha256(FINAL.encode()).hexdigest(),
            'Review candidate evidence mismatch')
    reviewer = engine.agents[formation['reviewer_id']]
    require(reviewer.parent_id is None and reviewer.id not in run['pm_agent_ids'] and
            not engine.message_eligibility(reviewer)['allowed'], 'Reviewer is not independent/read-only')
    pm = engine.agents[run['pm_agent_ids'][0]]
    worker = engine.agents[formation['worker_ids'][0]]
    require(pm.worker_report_consumed.get(worker.id) == worker.result_revision and
            pm.worker_report_reviews.get(worker.id) == {'result_revision': worker.result_revision, 'decision': 'accept'},
            'Current direct-parent report was not consumed and accepted')
    require(pm.finished_revision == pm.result_revision and
            any(row['source'] == 'finish_work' and row['text'] == FINAL for row in pm.results), 'Exact PM finish missing')
    require((workspace / 'result.txt').read_text(encoding='utf-8') == CONTENT, 'Actual output bytes differ')
    require(sum(item['model_calls'] for item in engine.runs.values()) == len(client.calls) <= 13, 'Model-call accounting differs')
    require(sum(item['tool_calls'] for item in engine.runs.values()) <= 60 and
            sum(item['auto_collaborations'] for item in engine.runs.values()) <= 24, 'Shared fixture cap exceeded')
    require(all(run['_config']['limits'][key] == val for run in engine.runs.values() for key, val in LIMITS.items()),
            'Execution limits changed')
    return {'run_id': run['id'], 'manual_id': manual['id'], 'pm_id': pm.id, 'reviewer_id': reviewer.id,
            'formation': copy.deepcopy(formation), 'model_calls': len(client.calls), 'current_parent_accept': True}


async def serve(output, nonce):
    fixture = output / 'fixture'
    fixture.mkdir()
    state, workspace = output / 'state', output / 'work'
    state.mkdir()
    workspace.mkdir()
    config = copy.deepcopy(DEFAULT)
    config['providers'] = [{**config['providers'][0], 'model': 'adaptive-synthetic', 'api_key_env': '', 'base_url': 'http://127.0.0.1:1/v1'}]
    config['paths'] = {'read_roots': [str(workspace)], 'write_roots': [str(workspace)], 'deny_roots': []}
    config['limits'].update(LIMITS)
    config['local'].update(max_concurrent_requests=1, max_retries=0, queue_timeout_seconds=3600, request_timeout_seconds=600)
    save(state / 'settings.json', validate_settings(config))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    current = {}
    record = {'kind': 'synthetic_adaptive_browser_fixture', 'errors': [], 'lifecycles': [], 'controls': [],
              'real_model_inference': 0, 'deleted_files': 0, 'forced_termination': False, 'stdin_valid': False}

    def command_reader():
        try:
            for _ in range(4):
                raw = sys.stdin.buffer.readline(4097)
                require(raw and len(raw) <= 4096 and raw.endswith(b'\n'), 'Missing or oversized stdin command')
                value = json.loads(raw)
                require(type(value) is dict and set(value) == {'command', 'nonce'} and
                        type(value['command']) is str and value['command'] in ('review', 'finish', 'archive', 'shutdown') and
                        type(value['nonce']) is str and secrets.compare_digest(value['nonce'], nonce), 'Invalid stdin command')
                expected = (json.dumps(value, separators=(',', ':')) + '\n').encode()
                require(raw == expected, 'Noncanonical stdin frame')
                if value['command'] == 'shutdown':
                    require(sys.stdin.buffer.read(1) == b'', 'Surplus input after shutdown')
                    record['stdin_valid'] = True
                loop.call_soon_threadsafe(queue.put_nowait, value['command'])
                if value['command'] == 'shutdown': return
            raise AssertionError('Stdin command cap exceeded')
        except BaseException as exc:
            record['errors'].append('stdin: ' + str(exc))
            loop.call_soon_threadsafe(stop.set)

    async def commands():
        try:
            while True:
                command = await queue.get()
                if command == 'shutdown':
                    emit('ack', command=command, ok=True, nonce=nonce)
                    stop.set()
                    return
                require(command == ('review', 'finish', 'archive')[len(record['controls'])], 'Unexpected command order')
                require(current.get('phase') == 'live', 'Only the live fixture accepts release commands')
                engine, client = current['engine'], current['client']
                adaptive = next((run for run in engine.runs.values() if run.get('adaptive_team')), None)
                expected = {'review': 'reviewing', 'finish': 'accepted', 'archive': 'complete'}[command]
                require(adaptive is not None and adaptive['formation']['phase'] == expected, 'Command reached wrong phase')
                record['controls'].append({'action': command, 'at': time.time(), 'phase': expected})
                if command == 'review': client.review_release.set()
                elif command == 'finish': client.finish_release.set()
                else: current['restart'].set()
                emit('ack', command=command, ok=True, nonce=nonce)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            record['errors'].append('control: ' + str(exc))
            emit('ack', command=command, ok=False, nonce=nonce, error=str(exc))
            stop.set()

    threading.Thread(target=command_reader, name='fixture-commands', daemon=True).start()
    controller = asyncio.create_task(commands())
    proof = None
    try:
        async with asyncio.timeout(240):
            for phase in ('live', 'archive'):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    if os.name == 'nt': listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    listener.bind(('127.0.0.1', 0))
                    listener.listen()
                    listener.setblocking(False)
                    auth = BrowserAuth(listener.getsockname()[1])
                    client = ScriptedClient(workspace, archive_only=phase == 'archive')
                    app = create_app(state, auth, client=client)
                except BaseException:
                    listener.close()
                    raise
                engine = client.engine = app[APP_KEY]
                lease = engine.history._lease
                restart = asyncio.Event()
                current.update(phase=phase, engine=engine, client=client, restart=restart)
                runner = web.AppRunner(app, access_log=None)
                try:
                    require(engine.history._available and lease is not None and not lease.closed, 'History lease not available')
                    await runner.setup()
                    await web.SockSite(runner, listener).start()
                    emit('ready', phase=phase, url=auth.launch_url, pid=os.getpid(), parent_pid=os.getppid(), nonce=nonce,
                         tasks={'manual': MANUAL, 'adaptive': ADAPTIVE}, limits=LIMITS)
                    waits = [asyncio.create_task(stop.wait())]
                    if phase == 'live': waits.append(asyncio.create_task(restart.wait()))
                    try:
                        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in waits:
                            if not task.done(): task.cancel()
                        await asyncio.gather(*waits, return_exceptions=True)
                    if phase == 'live' and restart.is_set() and not stop.is_set():
                        proof = await verify_live(engine, client, workspace)
                        save(fixture / 'live-proof.json', proof)
                    elif phase == 'live':
                        raise AssertionError('Stopped before the live workflow and archive transition completed')
                    else:
                        require(not client.calls and not engine.runs and not engine.agents, 'Archive browsing created execution state')
                        archived = engine.snapshot()
                        saved = next(row for row in archived['runs'] if row['id'] == proof['run_id'])
                        require(saved['formation'] == proof['formation'] and saved['archived'] and saved['read_only'], 'Archived formation differs')
                        require(all(row['read_only'] and not row['message_eligibility']['allowed'] for row in archived['agents']),
                                'Archive exposed executable controls')
                finally:
                    # Evidence failures never prevent releasing the resources they describe.
                    # Retain the in-flight failure; record secondary failures separately.
                    primary = sys.exc_info()[1]
                    secondary = []
                    tracked = [agent.task for agent in engine.agents.values() if agent.task] + list(engine._question_tasks)
                    tracked.extend(task for task in (engine._copilot_sync_task, engine._copilot_operation) if task)
                    try:
                        save(fixture / f'{phase}-snapshot.json', engine.snapshot())
                        save(fixture / f'{phase}-calls.json', client.calls)
                        save(fixture / f'{phase}-conversations.json', {key: agent.conversation for key, agent in engine.agents.items()})
                    except BaseException as exc:
                        secondary.append('Evidence: ' + type(exc).__name__ + ': ' + str(exc))
                    finally:
                        try:
                            await runner.cleanup()
                        except BaseException as exc:
                            secondary.append('App cleanup: ' + type(exc).__name__ + ': ' + str(exc))
                        finally:
                            try:
                                if not engine.closed:
                                    await engine.close()
                                    engine.settings.secrets.clear()
                            except BaseException as exc:
                                secondary.append('Engine cleanup: ' + type(exc).__name__ + ': ' + str(exc))
                            finally:
                                listener.close()
                    lifecycle = {'phase': phase, 'engine_closed': engine.closed, 'lease_closed': bool(lease and lease.closed),
                        'history_lease_none': engine.history._lease is None, 'credentials_closed': engine.credentials._closed,
                        'secrets_empty': not engine.settings.secrets, 'provider_active': client.active,
                        'tasks_unfinished': sum(bool(a.task and not a.task.done()) for a in engine.agents.values()),
                        'tracked_tasks_unfinished': sum(not task.done() for task in tracked),
                        'provider_phases': {key: getattr(agent, '_provider_observation', {}).get('phase') for key, agent in engine.agents.items()},
                        'listener_closed': listener.fileno() == -1,
                        'question_tasks': len(engine._question_tasks), 'resources': engine.gate.snapshot(),
                        'history_error': engine.history.error}
                    record['lifecycles'].append(lifecycle)
                    valid = (lifecycle['engine_closed'] and lifecycle['lease_closed'] and lifecycle['history_lease_none'] and
                            lifecycle['credentials_closed'] and lifecycle['secrets_empty'] and not lifecycle['provider_active'] and
                            not lifecycle['tasks_unfinished'] and not lifecycle['question_tasks'] and not lifecycle['history_error'] and
                            not lifecycle['tracked_tasks_unfinished'] and lifecycle['listener_closed'] and
                            all(value in ('completed', 'error', 'cancelled') for value in lifecycle['provider_phases'].values()) and
                            lifecycle['resources']['active'] == lifecycle['resources']['waiting'] == 0)
                    if not valid: secondary.append('Incomplete normal lifecycle')
                    record['errors'].extend(secondary)
                    if primary is None and secondary:
                        raise AssertionError('Phase finalization failed; see secondary error records')
                if stop.is_set(): break
        require(record['stdin_valid'] and len(record['lifecycles']) == 2 and proof is not None, 'Incomplete fixture session')
    except BaseException as exc:
        record['errors'].append(type(exc).__name__ + ': ' + str(exc))
        record['traceback'] = traceback.format_exc()
    finally:
        controller.cancel()
        await asyncio.gather(controller, return_exceptions=True)
    record['ok'] = not record['errors'] and len(record['lifecycles']) == 2
    save(fixture / 'closure-ack.json', record)
    emit('closed', ok=record['ok'], nonce=nonce, pid=os.getpid())
    return 0 if record['ok'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--nonce', required=True)
    args = parser.parse_args()
    require(len(args.nonce) == 64 and all(char in '0123456789abcdef' for char in args.nonce), 'Invalid session nonce')
    output = external_directory(args.output)
    require(output.is_dir() and (output / 'launch-claim.json').is_file(), 'The smoke driver must own a fresh output')
    require(not (output / 'fixture').exists() and not (output / 'state').exists() and not (output / 'work').exists(),
            'Never reuse fixture state or an earlier invocation')
    return asyncio.run(serve(output, args.nonce))


if __name__ == '__main__':
    raise SystemExit(main())
