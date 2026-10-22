"""Multiple independent PMs share one bounded team, including real HTTP replay."""
import asyncio
import json

import pytest

from workbench.engine import CollaborationLimitError, Engine
from test_engine import ScriptClient, configured, reply, settled, start
from test_engine_integration import (api_server, configured_settings, eventually,
                                     local_reply, openai_reply, anthropic_reply)


async def multi_start(engine, profiles=None, **extra):
    result = await engine.start_run({'task': 'Coordinate the shared task',
        'pm_profiles': profiles or ['local', 'local'], 'worker_profiles': ['local'],
        'max_workers': 2, **extra})
    run = engine.runs[result['run']['id']]
    return run, [engine.agents[ident] for ident in run['pm_agent_ids']]


@pytest.mark.asyncio
async def test_legacy_one_pm_and_repeated_profile_pm_identities_are_snapshots(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        legacy, original = await start(engine)
        assert legacy['pm_profiles'] == ['local'] and legacy['pm_agent_ids'] == [original.id]
        assert original.name == 'PM' and original.parent_id is None
        selection = ['local', 'local']
        run, leads = await multi_start(engine, selection)
        selection.append('openai')
        assert run['pm_profile'] == 'local' and run['pm_profiles'] == ['local', 'local']
        assert [a.name for a in leads] == ['PM 1', 'PM 2']
        assert len({a.id for a in leads}) == 2
        assert all(a.parent_id is None and a.profile_id == 'local' for a in leads)
        assert all(list(a.pending) == [('Coordinate the shared task', True)] for a in leads)
        for index, lead in enumerate(leads, 1):
            identity = json.loads(engine._policy(run, lead).split('Verified runtime identity and user-selected scope:\n')[1])
            assert identity['pm_index'] == index and identity['pm_agent_ids'] == run['pm_agent_ids']
            assert 'spawn_worker' in {tool['name'] for tool in engine._model_tools(run, lead)}
        # Configured metadata is captured at start, including when profiles are removed later.
        engine.settings.value['providers'][0]['model'] = 'changed-after-start'
        engine.settings.value['providers'].clear()
        projected = {a['id']: a for a in engine.snapshot()['agents']}
        assert all(projected[lead.id]['configured_profile']['model'] == 'fixture' for lead in leads)
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('selection,legacy', [([], None), ('local', None), (None, None),
    (['local'] * 17, None), (['unknown'], None), (['local', 1], None),
    (['local', []], None), (['local'], 'openai')])
async def test_invalid_pm_selection_preflight_and_start_reject_without_agents(tmp_path, selection, legacy):
    engine, _ = configured(tmp_path, ScriptClient([]))
    request = {'task': 'No side effects', 'pm_profiles': selection, 'max_workers': 0}
    if legacy is not None:
        request['pm_profile'] = legacy
    try:
        preview = engine.preflight(request)
        assert not preview['can_start'] and preview['blockers'][0]['code'] == 'invalid_selection'
        with pytest.raises(ValueError):
            await engine.start_run(request)
        assert not engine.runs and not engine.agents and not engine.events
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('problem,code', [('disabled', 'invalid_selection'),
    ('missing_model', 'model_missing'), ('missing_key', 'key_missing')])
async def test_all_pm_profiles_checked_before_admission(tmp_path, monkeypatch, problem, code):
    engine, _ = configured(tmp_path, ScriptClient([]))
    cloud = engine.settings.value['providers'][1]
    cloud.update(model='fixture', api_key_env='MULTI_PM_TEST_KEY')
    monkeypatch.delenv('MULTI_PM_TEST_KEY', raising=False)
    if problem == 'disabled': cloud['enabled'] = False
    if problem == 'missing_model': cloud['model'] = ''
    request = {'task': 'Validate every PM', 'pm_profiles': ['local', 'openai'], 'max_workers': 0}
    try:
        preview = engine.preflight(request)
        assert not preview['can_start'] and preview['blockers'][0]['code'] == code
        with pytest.raises(ValueError):
            await engine.start_run(request)
        assert not engine.runs and not engine.agents
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_preflight_deduplicates_destinations_but_preserves_pm_counts(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    engine.settings.value['providers'][1]['model'] = 'cloud-fixture'
    engine.settings.secrets['openai'] = 'test-key'
    request = {'task': 'One task', 'pm_profile': 'local', 'pm_profiles': ['local', 'local', 'openai'],
               'worker_profiles': ['local', 'openai'], 'max_workers': 1}
    try:
        preview = engine.preflight(request)
        assert preview['can_start'] and not preview['inference_tested']
        assert not engine.runs and not engine.agents
        assert [(p['profile_id'], p['pm_count'], p['worker_available'], p['role'])
                for p in preview['destinations']] == [('local', 2, True, 'PM'), ('openai', 1, True, 'PM')]
        result = await engine.start_run(request)
        assert [engine.agents[a].profile_id for a in result['run']['pm_agent_ids']] == ['local', 'local', 'openai']
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_pm_worker_limit_parentage_privileges_and_peer_mail_are_shared(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, (pm1, pm2) = await multi_start(engine)
        children = []
        for lead in (pm1, pm2):
            created = await engine.execute_tool(run, lead, 'spawn_worker',
                {'profile_id': 'local', 'role': 'pm', 'task': 'Worker label must not grant PM powers'})
            child = engine.agents[created['agent_id']]
            assert child.parent_id == lead.id
            children.append(child)
            assert 'spawn_worker' not in {tool['name'] for tool in engine._model_tools(run, child)}
            with pytest.raises(ValueError, match='増員'):
                await engine.execute_tool(run, child, 'spawn_worker',
                    {'profile_id': 'local', 'role': 'helper', 'task': 'Not authorized'})
        assert [a.name for a in children] == ['Worker 1 · pm', 'Worker 2 · pm']
        for lead in (pm1, pm2):
            with pytest.raises(ValueError, match='最大 worker'):
                await engine.execute_tool(run, lead, 'spawn_worker',
                    {'profile_id': 'local', 'role': 'helper', 'task': 'Over shared cap'})
        await engine.execute_tool(run, pm1, 'send_message', {'to_agent_id': pm2.id, 'body': 'Take the review role'})
        await engine.execute_tool(run, children[0], 'send_message', {'to_agent_id': pm2.id, 'body': 'Evidence for another PM'})
        assert run['auto_collaborations'] == 4  # Two spawns + two peer deliveries.
        assert all(not human for _, human in list(pm2.pending)[1:])
        assert all(json.loads(body.split('\n', 1)[1])['untrusted'] for body, _ in list(pm2.pending)[1:])
        other, (other_pm, _) = await multi_start(engine)
        with pytest.raises(ValueError, match='別チーム'):
            await engine.execute_tool(run, children[0], 'send_message', {'to_agent_id': other_pm.id, 'body': 'Cross-team'})
        assert other['auto_collaborations'] == 0
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_pm_finish_waits_for_own_worker_without_deadlocking_other_pm(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, (pm1, pm2) = await multi_start(engine)
        for lead in (pm1, pm2):
            lead.pending.clear()
            lead.status = 'working'
        created = await engine.execute_tool(run, pm1, 'spawn_worker',
            {'profile_id': 'local', 'role': 'writer', 'task': 'Write'})
        worker = engine.agents[created['agent_id']]
        with pytest.raises(ValueError, match='未完了'):
            await engine.execute_tool(run, pm1, 'finish_work', {'summary': 'Too early'})
        assert (await engine.execute_tool(run, pm2, 'finish_work', {'summary': 'My review is complete'}))['ok']
        worker.status = 'done'
        # A completed worker with a new queued assignment is still unfinished.
        with pytest.raises(ValueError, match='未完了'):
            await engine.execute_tool(run, pm1, 'finish_work', {'summary': 'Still too early'})
        worker.pending.clear()
        assert (await engine.execute_tool(run, pm1, 'finish_work', {'summary': 'My file is complete'}))['ok']
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_run_stays_running_until_all_independent_pm_calls_complete(tmp_path):
    blocked, release = asyncio.Event(), asyncio.Event()

    async def second(profile, messages):
        blocked.set()
        await release.wait()
        return reply(calls=[('finish_work', {'summary': 'Second PM finished'})])

    engine, _ = configured(tmp_path, ScriptClient([reply(calls=[('finish_work', {'summary': 'First PM finished'})]), second]))
    try:
        run, (pm1, pm2) = await multi_start(engine, max_workers=0)
        await asyncio.wait_for(blocked.wait(), 2)
        assert pm1.status == 'done' and pm2.status == 'working' and run['status'] == 'running'
        release.set()
        await settled(engine)
        assert pm2.status == 'done' and run['status'] == 'done'
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_sixteen_pms_share_model_budget_without_overshoot(tmp_path):
    client = ScriptClient([reply(calls=[('finish_work', {'summary': 'One allowed call'})])])
    engine, _ = configured(tmp_path, client)
    engine.settings.value['limits']['max_model_calls'] = 1
    try:
        run, leads = await multi_start(engine, ['local'] * 16, max_workers=0)
        await settled(engine)
        assert len(leads) == 16 and run['model_calls'] == len(client.calls) == 1
        assert leads[0].status == 'done' and all(a.status == 'error' for a in leads[1:])
        assert run['status'] == 'waiting'
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_concurrent_pm_spawns_share_collaboration_budget(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    engine.settings.value['limits']['max_auto_collaborations'] = 1
    try:
        run, leads = await multi_start(engine)
        results = await asyncio.gather(*(engine.execute_tool(run, lead, 'spawn_worker',
            {'profile_id': 'local', 'role': 'helper', 'task': 'Shared budget'}) for lead in leads), return_exceptions=True)
        assert sum(isinstance(item, CollaborationLimitError) for item in results) == 1
        assert len(run['agent_ids']) == 3 and run['auto_collaborations'] == 1
        assert run['collaboration_limit_reached']
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_stop_cancels_every_pm_and_worker_and_releases_all_reservations(tmp_path):
    entered = []

    async def blocked(profile, messages):
        entered.append(True)
        await asyncio.Event().wait()

    engine, _ = configured(tmp_path, ScriptClient([blocked] * 4))
    try:
        run, leads = await multi_start(engine)
        for index, lead in enumerate(leads):
            await engine.execute_tool(run, lead, 'spawn_worker',
                {'profile_id': 'local', 'role': 'helper', 'task': 'Wait'})
            await engine.execute_tool(run, lead, 'reserve_paths', {'paths': [f'pm-{index}.txt']})
        await eventually(lambda: len(entered) == 4, engine)
        await engine.stop_run(run['id'])
        assert run['status'] == 'stopped' and not engine.reservations
        assert all(a.status == 'stopped' and a.task.done() and not a.pending for a in engine.agents.values())
        assert run['auto_collaborations'] == 2
    finally:
        await engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('second_profile', ['local', 'openai', 'anthropic'])
async def test_real_api_two_pm_team_delegates_writes_and_returns_to_each_parent(tmp_path, second_profile):
    requests, errors = {}, []

    async def handler(request):
        try:
            body = await request.json()
            if request.path == '/v1/responses':
                assert request.headers['Authorization'] == 'Bearer test-openai-secret'
                system, respond = body['instructions'], openai_reply
                messages = [item if 'role' in item else {'role': 'tool', 'tool_call_id': item['call_id'],
                            'content': item['output']} for item in body['input']
                            if 'role' in item or item.get('type') == 'function_call_output']
                available = {tool['name'] for tool in body['tools']}
            elif request.path == '/v1/messages':
                assert request.headers['x-api-key'] == 'test-anthropic-secret'
                system, respond = body['system'], anthropic_reply
                messages = []
                for item in body['messages']:
                    for block in item['content']:
                        if block['type'] == 'tool_result':
                            messages.append({'role': 'tool', 'tool_call_id': block['tool_use_id'], 'content': block['content']})
                        elif block['type'] == 'text':
                            messages.append({'role': item['role'], 'content': block['text']})
                available = {tool['name'] for tool in body['tools']}
            else:
                assert request.path == '/v1/chat/completions'
                system, respond = body['messages'][0]['content'], local_reply
                messages = body['messages']
                available = {tool['function']['name'] for tool in body['tools']}
            identity = json.loads(system.split('Verified runtime identity and user-selected scope:\n')[1])
            ident = identity['id']
            headers = requests.setdefault(ident, [])
            headers.append(request.headers.get('X-Conversation-Id'))
            if identity['parent_id'] is None:
                assert 'spawn_worker' in available
                index = identity['pm_index']
                if not any(item.get('tool_call_id') == f'spawn-{index}' for item in messages):
                    calls = [(f'spawn-{index}', 'spawn_worker', {'profile_id': 'local', 'role': 'writer',
                        'task': f'Create and verify part-{index}.txt'})]
                    if index == 1:
                        calls.append(('delegate-peer', 'send_message', {'to_agent_id': identity['pm_agent_ids'][1],
                            'body': 'I own part-1.txt; coordinate part-2.txt and report your own verified result.'}))
                    return respond(calls)
                notices = [json.loads(item['content'].split('\n', 1)[1]) for item in messages
                    if item['role'] == 'user' and item['content'].startswith('Peer data;')]
                completed = [notice for notice in notices if notice['kind'] == 'worker_completed']
                if completed:
                    assert all(note['untrusted'] and f'part-{index}.txt' in note['body'] for note in completed)
                    return respond([(f'pm-done-{index}', 'finish_work', {'summary': f'Verified part-{index}.txt via my worker.'})])
                return respond(text='My assigned worker is still working; wait for its completion notice.')
            assert 'spawn_worker' not in available
            assignment = next(item['content'] for item in messages if item['role'] == 'user')
            filename = 'part-1.txt' if 'part-1.txt' in assignment else 'part-2.txt'
            if len(headers) == 1:
                return local_reply([('write', 'write_text', {'path': filename, 'text': 'Verified subagent output', 'expected_sha256': 'missing'})])
            if len(headers) == 2:
                return local_reply([('read', 'read_text', {'path': filename})])
            result = json.loads(next(item['content'] for item in messages if item.get('tool_call_id') == 'read'))
            assert 'Verified subagent output' in json.dumps(result)
            return local_reply([('worker-done', 'finish_work', {'summary': 'Created and read back ' + filename})])
        except Exception as exc:
            errors.append(repr(exc))
            raise

    async with api_server(handler) as endpoint:
        settings, workspace = configured_settings(tmp_path, endpoint)
        engine = Engine(settings)
        try:
            run, leads = await multi_start(engine, ['local', second_profile])
            await eventually(lambda: run['status'] in {'done', 'waiting'}, engine)
            assert not errors and run['status'] == 'done', engine.snapshot()
            workers = [engine.agents[i] for i in run['agent_ids'] if i not in run['pm_agent_ids']]
            assert len(workers) == 2 and {a.parent_id for a in workers} == {a.id for a in leads}
            assert all(a.status == 'done' for a in [*leads, *workers])
            assert run['auto_collaborations'] == 5  # Two delegations, one PM message, two completion notices.
            assert run['model_calls'] == sum(map(len, requests.values()))
            assert set(requests) == set(run['agent_ids'])
            assert all(set(values) == ({f'{run["id"]}/{ident}'} if engine.agents[ident].profile_id == 'local' else {None})
                       for ident, values in requests.items())
            for index in (1, 2):
                assert (workspace / f'part-{index}.txt').read_text() == 'Verified subagent output'
            for lead in leads:
                mail = [json.loads(item['content'].split('\n', 1)[1]) for item in lead.conversation
                    if item['role'] == 'user' and item['content'].startswith('Peer data;')]
                for notice in mail:
                    if notice['kind'] == 'worker_completed':
                        assert engine.agents[notice['sender']].parent_id == lead.id
        finally:
            await engine.close()
