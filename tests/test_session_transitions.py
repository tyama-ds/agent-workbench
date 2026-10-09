"""Bounded reachable-session traces, with an external model and explicit barriers.

Only the provider is synthetic. HTTP auth/revisions, Engine, ResourceGate and file
reservations are real. Watchdog timeouts diagnose hangs; elapsed time never chooses
a transition. These tests are not exhaustive model checking or provider-wire tests.
"""
import asyncio
import copy
import json
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest

from test_config_server import bootstrap, serving
from workbench.config import DEFAULT
from workbench.providers import ModelReply
from workbench.server import APP_KEY


@pytest.fixture(autouse=True)
def synthetic_credentials_only(monkeypatch):
    for profile in [*DEFAULT['providers'], DEFAULT['search']]:
        if profile['api_key_env']:
            monkeypatch.delenv(profile['api_key_env'], raising=False)


async def observed(awaitable):
    """A hang guard, not a sleep-based ordering or quiescence assumption."""
    return await asyncio.wait_for(awaitable, 10)


def response(*calls, text=''):
    return ModelReply(text=text, tool_calls=[
        {'id': f'call-{index}', 'name': name, 'arguments': arguments}
        for index, (name, arguments) in enumerate(calls)])


@dataclass
class Request:
    agent_id: str
    profile: dict
    messages: list
    future: asyncio.Future
    admitted: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_release: asyncio.Event | None = None


class ScheduledProvider:
    def __init__(self, engine):
        self.engine = engine
        self.requested = asyncio.Queue()
        self.history = []

    async def complete(self, profile, messages, tools, policy, limits):
        identity = json.loads(policy.split('Verified runtime identity and user-selected scope:\n', 1)[1])
        call = Request(identity['id'], copy.deepcopy(profile), copy.deepcopy(messages),
                       asyncio.get_running_loop().create_future())
        self.history.append(call)
        self.requested.put_nowait(call)
        async with self.engine.gate.slot(limits['local']):
            call.admitted.set()
            try:
                return await call.future
            except asyncio.CancelledError:
                call.cancelled.set()
                if call.cancel_release is not None:
                    await call.cancel_release.wait()
                raise


class Session:
    def __init__(self, auth, app, client):
        self.auth, self.client, self.engine = auth, client, app[APP_KEY]
        self.provider = ScheduledProvider(self.engine)
        self.engine.client = self.provider
        self.trace, self.aliases = [], {}

    async def api(self, method, path, payload=None, *, status=200):
        label = path
        for ident, alias in self.aliases.items():
            label = label.replace(ident, alias)
        self.trace.append(f'{method.upper()} {label} -> expected {status}')
        kwargs = {'headers': {'Origin': self.auth.origin}}
        if payload is not None:
            kwargs['json'] = payload
        async with asyncio.timeout(10):
            async with getattr(self.client, method)(self.auth.origin + path, **kwargs) as result:
                value = await result.json()
                assert result.status == status, (result.status, value)
                return value

    async def take(self, agent, *, admitted=True):
        call = await observed(self.provider.requested.get())
        assert call.agent_id == agent.id
        if admitted:
            await observed(call.admitted.wait())
        self.trace.append(f'provider request {self.aliases.get(agent.id, agent.name)}')
        return call

    async def start(self, *, workers=0):
        value = await self.api('post', '/api/runs', {
            'task': 'Synthetic transition task', 'pm_profile': 'local',
            'worker_profiles': ['local'] if workers else [], 'max_workers': workers})
        run = self.engine.runs[value['run']['id']]
        agent = self.engine.agents[run['agent_ids'][0]]
        self.aliases[run['id']] = f'run-{len(self.engine.runs)}'
        self.aliases[agent.id] = self.aliases[run['id']] + '-pm'
        return run, agent, await self.take(agent)

    async def finish(self, agent, call, reply=None, *, error=None):
        self.trace.append(f'resolve {self.aliases.get(agent.id, agent.name)}: ' + (
            'provider error' if error else ','.join(item['name'] for item in reply.tool_calls) or 'text'))
        if error:
            call.future.set_exception(error)
        else:
            call.future.set_result(reply)
        await observed(asyncio.shield(agent.task))

    async def stop(self, run):
        await self.api('post', f'/api/runs/{run["id"]}/stop', {})

    def clean(self):
        assert not self.engine.reservations and not self.engine.lock.locked()
        assert self.engine.gate.snapshot()['active'] == self.engine.gate.snapshot()['waiting'] == 0
        assert all(not agent.pending and (agent.task is None or agent.task.done())
                   for agent in self.engine.agents.values())


@asynccontextmanager
async def session(tmp_path, *, concurrency=2, limits=None):
    async with serving(tmp_path) as (auth, app, client):
        case = Session(auth, app, client)
        await bootstrap(auth, client)
        files = tmp_path / 'files'
        files.mkdir()
        config = copy.deepcopy(case.engine.settings.value)
        config['providers'] = [dict(config['providers'][0], model='synthetic-fixture', api_key_env='')]
        config['search']['api_key_env'] = ''
        config['paths'] = {'read_roots': [str(files)], 'write_roots': [str(files)], 'deny_roots': []}
        config['local'].update(max_concurrent_requests=concurrency, max_retries=0)
        config['limits'].update(limits or {})
        await case.api('put', '/api/config', {'config_revision': 0, 'config': config})
        case.initial_config = copy.deepcopy(config)
        try:
            yield case
        except (AssertionError, TimeoutError) as exc:
            raise AssertionError(f'{exc}\nReachable transition trace:\n' + '\n'.join(case.trace)) from exc
        finally:
            # Release any deliberately held provider cancellation before shutdown.
            for call in case.provider.history:
                if call.cancel_release is not None:
                    call.cancel_release.set()
            await observed(case.engine.close())
            case.clean()


async def test_paused_peer_queue_preserves_human_slot_priority_fifo_and_stop_cleanup(tmp_path):
    async with session(tmp_path, limits={'max_auto_collaborations': 100}) as case:
        run, pm, call = await case.start(workers=1)
        await case.finish(pm, call, response(
            ('spawn_worker', {'task': 'Synthetic worker task', 'role': 'review', 'profile_id': 'local'}),
            ('ask_user', {'question': 'Human decision?'})))
        worker = case.engine.agents[run['agent_ids'][1]]
        case.aliases[worker.id] = 'run-1-worker'
        call = await case.take(worker)
        await case.finish(worker, call, response(*[
            ('send_message', {'to_agent_id': pm.id, 'body': f'Peer message {index}'})
            for index in range(30)], ('finish_work', {'summary': 'Worker verified its turn'})))
        assert worker.status == 'done' and pm.question == 'Human decision?'
        assert len(pm.pending) == 31 and run['auto_collaborations'] == 32
        envelopes = [json.loads(body.split('\n', 1)[1]) for body, human in pm.pending if not human]
        assert [item['body'] for item in envelopes] == [f'Peer message {index}' for index in range(30)] + ['Worker verified its turn']
        assert all(item['untrusted'] is True for item in envelopes)
        assert run['model_calls'] == 2 and run['tool_calls'] == 33
        assert run['status'] == 'waiting' and case.provider.requested.empty()

        # A real worker turn attempts the reserved human slot; no queue injection.
        await case.api('post', f'/api/agents/{worker.id}/message', {'text': 'Check peer overflow'})
        overflow = await case.take(worker)
        before_peer = list(pm.pending)
        await case.finish(worker, overflow, response(
            ('send_message', {'to_agent_id': pm.id, 'body': 'Peer overflow'}),
            ('ask_user', {'question': 'Worker waits independently'})))
        overflow_result = json.loads([item for item in worker.conversation if item['role'] == 'tool'][-2]['content'])
        assert overflow_result['ok'] is False and 'キュー' in overflow_result['error']
        assert list(pm.pending) == before_peer and run['auto_collaborations'] == 32
        assert pm.question == 'Human decision?' and worker.question == 'Worker waits independently'

        await case.api('post', f'/api/agents/{pm.id}/message', {'text': 'First human answer'})
        held = await case.take(pm)
        assert held.messages[-1]['content'] == 'First human answer'
        await case.api('post', f'/api/agents/{pm.id}/message', {'text': 'Second human answer'})
        assert len(pm.pending) == 32 and pm.pending[0] == ('Second human answer', True)
        before = (list(pm.pending), pm.result_revision, pm.question, pm.status)
        await case.api('post', f'/api/agents/{pm.id}/message', {'text': 'Overflow'}, status=400)
        assert before == (list(pm.pending), pm.result_revision, pm.question, pm.status)
        await case.stop(run)
        assert held.cancelled.is_set() and run['status'] == pm.status == 'stopped'
        assert run['model_calls'] == 4 and run['tool_calls'] == 35 and run['auto_collaborations'] == 32
        case.clean()

        # A second reachable run leaves room to queue two human messages together.
        fifo_run, fifo_pm, initial = await case.start()
        for body in ['Queued human first', 'Queued human second']:
            await case.api('post', f'/api/agents/{fifo_pm.id}/message', {'text': body})
        assert list(fifo_pm.pending) == [('Queued human first', True), ('Queued human second', True)]
        initial.future.set_result(response(text='Initial turn'))
        first = await case.take(fifo_pm)
        assert first.messages[-1]['content'] == 'Queued human first'
        first.future.set_result(response(text='First queued turn'))
        second = await case.take(fifo_pm)
        assert second.messages[-1]['content'] == 'Queued human second'
        await case.finish(fifo_pm, second, response(text='Second queued turn'))
        assert fifo_run['model_calls'] == fifo_pm.turns == 3
        await case.stop(fifo_run)
        case.clean()


@pytest.mark.parametrize('reply_first', [False, True])
async def test_ordered_stop_and_completion_preserve_only_committed_results(tmp_path, reply_first):
    async with session(tmp_path) as case:
        run, pm, call = await case.start()
        if reply_first:
            await case.finish(pm, call, response(('finish_work', {'summary': 'Completed before Stop'})))
            await case.stop(run)
        else:
            call.cancel_release = asyncio.Event()
            stopping = asyncio.create_task(case.stop(run))
            try:
                await observed(call.cancelled.wait())
                assert run['status'] == 'stopping' and not stopping.done()
                await case.api('post', f'/api/agents/{pm.id}/message', {'text': 'Too late'}, status=400)
                await case.api('put', '/api/config', {'config_revision': case.engine.settings.revision,
                                                    'config': copy.deepcopy(case.engine.settings.value)}, status=409)
                call.cancel_release.set()
                await observed(stopping)
            finally:
                call.cancel_release.set()
                await observed(stopping)
        assert run['status'] == pm.status == 'stopped'
        assert len(pm.results) == int(reply_first)
        assert run['model_calls'] == 1 and run['tool_calls'] == int(reply_first)
        before = copy.deepcopy(case.engine.snapshot())
        await case.stop(run)
        assert case.engine.snapshot() == before
        case.clean()


async def test_key_rotation_distinguishes_dispatched_gate_waiter_from_mailbox_work(tmp_path):
    async with session(tmp_path, concurrency=1) as case:
        revision = case.engine.settings.revision
        old, new = 'SYNTHETIC-transition-old-key', 'SYNTHETIC-transition-new-key'
        await case.api('post', '/api/secrets', {'config_revision': revision, 'id': 'local', 'key': old})
        first, first_pm, first_call = await case.start()
        # Start through HTTP, but observe entry before local gate admission.
        value = await case.api('post', '/api/runs', {'task': 'Queued inference', 'pm_profile': 'local',
                                                    'worker_profiles': [], 'max_workers': 0})
        second = case.engine.runs[value['run']['id']]
        second_pm = case.engine.agents[second['agent_ids'][0]]
        case.aliases[second['id']], case.aliases[second_pm.id] = 'run-2', 'run-2-pm'
        queued = await case.take(second_pm, admitted=False)
        assert not queued.admitted.is_set() and case.engine.gate.snapshot()['waiting'] == 1
        await case.api('post', f'/api/agents/{second_pm.id}/message', {'text': 'Not dispatched yet'})
        before = (second['model_calls'], second['tool_calls'], second_pm.turns, second_pm.result_revision)
        await case.api('post', '/api/secrets', {'config_revision': revision, 'id': 'local', 'key': new})
        assert before == (second['model_calls'], second['tool_calls'], second_pm.turns, second_pm.result_revision)
        assert case.engine.settings.revision == revision
        assert first_call.profile['api_key'] == queued.profile['api_key'] == old
        await case.finish(first_pm, first_call, response(text=old))
        await observed(queued.admitted.wait())
        queued.future.set_result(response(text=old))
        later = await case.take(second_pm)
        assert later.profile['api_key'] == new and later.messages[-1]['content'] == 'Not dispatched yet'
        await case.api('post', f'/api/agents/{second_pm.id}/message', {'text': 'Still queued after failure'})
        await case.finish(second_pm, later, error=RuntimeError('Synthetic authentication failure ' + new))
        assert second_pm.status == 'error' and list(second_pm.pending) == [('Still queued after failure', True)]
        recovered = 'SYNTHETIC-transition-recovered-key'
        before = (second['model_calls'], second['tool_calls'], second_pm.turns, second_pm.result_revision,
                  list(second_pm.pending), len(case.provider.history))
        await case.api('post', '/api/secrets', {'config_revision': revision, 'id': 'local', 'key': recovered})
        assert before == (second['model_calls'], second['tool_calls'], second_pm.turns, second_pm.result_revision,
                          list(second_pm.pending), len(case.provider.history))
        assert second_pm.status == 'error' and second_pm.task.done() and case.provider.requested.empty()
        await case.api('post', f'/api/agents/{second_pm.id}/message', {'text': 'Explicit recovery direction'})
        repair = await case.take(second_pm)
        assert repair.profile['api_key'] == recovered and repair.messages[-1]['content'] == 'Still queued after failure'
        # Accepted human messages preserve FIFO even across an errored turn.
        repair.future.set_result(response(text='Recovered queued work'))
        instruction = await case.take(second_pm)
        assert instruction.messages[-1]['content'] == 'Explicit recovery direction'
        await case.finish(second_pm, instruction, response(text=recovered))
        assert (second['model_calls'], second_pm.turns, second_pm.result_revision) == (4, 4, 4)
        assert len(second_pm.results) == 3 and first['status'] == second['status'] == 'done'
        public = json.dumps(await case.api('get', '/api/state'))
        assert old not in public and new not in public and recovered not in public
        await case.stop(first)
        await case.stop(second)
        case.clean()


async def test_save_ownership_survives_completion_rotation_and_stale_writes(tmp_path):
    async with session(tmp_path) as case:
        stale = await case.api('get', '/api/config')
        run, pm, call = await case.start()
        candidate = copy.deepcopy(stale['config'])
        candidate['providers'][0]['label'] = 'New saved label'
        await case.api('put', '/api/config', {'config_revision': stale['config_revision'],
                                            'config': candidate}, status=409)
        await case.finish(pm, call, response(text='Completed original task'))
        saved = await case.api('put', '/api/config', {'config_revision': stale['config_revision'], 'config': candidate})
        assert saved['config_revision'] == stale['config_revision'] + 1
        assert saved['config'] == candidate and json.loads(case.engine.settings.path.read_bytes()) == candidate
        await case.api('post', '/api/secrets', {'config_revision': saved['config_revision'],
                                              'id': 'local', 'key': 'SYNTHETIC-current-key'})
        before = (case.engine.settings.path.read_bytes(), copy.deepcopy(case.engine.settings.value),
                  dict(case.engine.settings.secrets), case.engine.settings.revision, copy.deepcopy(case.engine.snapshot()))
        await case.api('put', '/api/config', {'config_revision': stale['config_revision'],
                                            'config': stale['config']}, status=409)
        await case.api('post', '/api/secrets', {'config_revision': stale['config_revision'],
                                              'id': 'local', 'key': ''}, status=409)
        await case.api('post', f'/api/agents/{pm.id}/message', {'text': 'Old configuration'}, status=400)
        assert before == (case.engine.settings.path.read_bytes(), case.engine.settings.value,
                          case.engine.settings.secrets, case.engine.settings.revision, case.engine.snapshot())
        assert len(case.provider.history) == 1
        await case.stop(run)


@dataclass
class RunModel:
    run: dict
    agent: object
    call: Request
    generation: int
    phase: str = 'working'
    models: int = 1
    tools: int = 0
    turns: int = 1
    revision: int = 1
    reports: int = 0


@pytest.mark.parametrize('seed', [7, 29, 101, 313])
async def test_seeded_reachable_session_model(tmp_path, seed):
    """The model predicts acceptance and counters; it never calls engine eligibility."""
    rng = random.Random(seed)
    async with session(tmp_path, limits={'max_model_calls': 6, 'max_tool_calls': 5,
                                        'max_turns_per_agent': 6}) as case:
        models, generation, revision, keys = [], 0, 1, []
        expected_config = copy.deepcopy(case.initial_config)
        for step in range(40):
            choices = ['key', 'save']
            if len(models) < 2:
                choices += ['start'] * 3
            if any(model.phase == 'working' for model in models):
                choices += ['reply'] * 6
            if any(model.phase != 'working' for model in models):
                choices += ['human'] * 4
            if step >= 28 and models:
                choices += ['stop']
            action = rng.choice(choices) if models else 'start'
            case.trace.append(f'seed={seed} step={step} action={action}')
            if action == 'start':
                run, agent, call = await case.start()
                models.append(RunModel(run, agent, call, generation))
            elif action == 'reply':
                model = rng.choice([item for item in models if item.phase == 'working'])
                kind = rng.choice(['text', 'question', 'finish', 'list', 'reserve_finish', 'failure'])
                case.trace.append('reply kind=' + kind)
                calls = {'question': [('ask_user', {'question': 'Human choice?'})],
                         'finish': [('finish_work', {'summary': 'Synthetic report'})],
                         'list': [('list_team', {})],
                         'reserve_finish': [('reserve_paths', {'paths': ['reserved.txt']}),
                                            ('finish_work', {'summary': 'Reserved and finished'})]}.get(kind, [])
                available = 5 - model.tools
                model.tools += min(available, len(calls))
                next_request = kind == 'list' and available >= 1 and model.models < 6
                if next_request:
                    model.models += 1
                    model.call.future.set_result(response(*calls))
                    model.call = await case.take(model.agent)
                else:
                    await case.finish(model.agent, model.call, response(*calls, text=keys[-1] if keys else 'Synthetic text'),
                                      error=RuntimeError('Synthetic provider failure') if kind == 'failure' else None)
                    if kind == 'failure' or available < len(calls) or kind == 'list':
                        model.phase = 'error'
                    elif kind == 'question':
                        model.phase = 'waiting'
                    else:
                        model.phase = 'done'
                        model.reports += 1
            elif action == 'human':
                model = rng.choice([item for item in models if item.phase != 'working'])
                allowed = (model.phase != 'stopped' and model.generation == generation
                           and model.turns < 6 and model.models < 6)
                await case.api('post', f'/api/agents/{model.agent.id}/message', {'text': 'Explicit human continuation'},
                               status=200 if allowed else 400)
                if allowed:
                    model.phase, model.turns, model.models, model.revision = 'working', model.turns + 1, model.models + 1, model.revision + 1
                    model.call = await case.take(model.agent)
            elif action == 'key':
                keys.append(f'SYNTHETIC-seed-{seed}-step-{step}-key')
                await case.api('post', '/api/secrets', {'config_revision': revision, 'id': 'local', 'key': keys[-1]})
            elif action == 'save':
                candidate = copy.deepcopy(expected_config)
                candidate['providers'][0]['label'] = f'Synthetic generation {step}'
                submitted = revision if rng.randrange(3) else revision - 1
                allowed = submitted == revision and all(item.phase in {'done', 'stopped'} for item in models)
                await case.api('put', '/api/config', {'config_revision': submitted, 'config': candidate},
                               status=200 if allowed else 409)
                if allowed:
                    generation, revision = generation + 1, revision + 1
                    expected_config = candidate
            else:
                model = rng.choice(models)
                await case.stop(model.run)
                model.phase = 'stopped'

            snapshot = await case.api('get', '/api/state')
            assert case.engine.settings.revision == revision
            assert case.engine.settings.value == expected_config
            assert json.loads(case.engine.settings.path.read_bytes()) == expected_config
            assert case.engine.settings.secrets == ({'local': keys[-1]} if keys else {})
            assert not case.engine.reservations and not case.engine.lock.locked()
            assert snapshot['resources']['active'] == sum(item.phase == 'working' for item in models)
            assert snapshot['resources']['waiting'] == 0
            assert not any(key in json.dumps(snapshot) for key in keys)
            for model in models:
                public_run = next(item for item in snapshot['runs'] if item['id'] == model.run['id'])
                public_agent = next(item for item in snapshot['agents'] if item['id'] == model.agent.id)
                assert (public_run['model_calls'], public_run['tool_calls'], public_run['auto_collaborations']) == (model.models, model.tools, 0)
                assert public_agent['status'] == model.phase
                assert (public_agent['turns'], public_agent['result_revision'], len(public_agent['results'])) == (model.turns, model.revision, model.reports)
                assert public_run['status'] == {'working': 'running', 'waiting': 'waiting', 'error': 'waiting',
                                                'done': 'done', 'stopped': 'stopped'}[model.phase]
                assert len(public_run['agent_ids']) == 1 and not model.agent.pending
        for model in models:
            await case.stop(model.run)
        case.clean()
