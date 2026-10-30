"""Real engine dispatch and permission boundaries, using only synthetic providers."""
import copy
import json
import asyncio
import threading

import pytest

from workbench.history import public_document
from test_engine import ScriptClient, configured, reply, settled, start
from test_config_server import APP_KEY, bootstrap, serving


def skill(work, body='Check the evidence, then ask_user if a human decision is missing.'):
    path = work / 'skills' / 'review' / 'SKILL.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('---\nname: review\ndescription: Review a worker report.\n---\n' + body, encoding='utf-8')
    return path


async def team(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    return engine, work


async def test_pm_and_worker_share_catalog_but_load_only_when_requested(tmp_path):
    engine, work = await team(tmp_path)
    skill(work, 'UNIQUE_PROCEDURE_BODY')
    try:
        run, pm = await start(engine, delegation_level=2, workers_per_pm=1)
        descriptor = run['skills']['skills'][0]
        assert 'content' not in descriptor
        assert 'UNIQUE_PROCEDURE_BODY' not in engine._policy(run, pm)
        assert 'Review a worker report.' in engine._policy(run, pm)
        assert 'read_skill' in {t['name'] for t in engine._model_tools(run, pm)}
        before = copy.deepcopy(run['_config'])
        loaded = await engine.execute_tool(run, pm, 'read_skill', {'skill_id': descriptor['id']})
        assert 'UNIQUE_PROCEDURE_BODY' in loaded['content']
        assert loaded['sha256'] == descriptor['sha256']
        # Reading the instructions never satisfies required delegation.
        assert engine._delegation_issue(run, pm)
        child = engine._new_agent(run, 'local', 'worker', pm.id, assignment='Review evidence')
        assert 'read_skill' in {t['name'] for t in engine._model_tools(run, child)}
        assert await engine.execute_tool(run, child, 'read_skill', {'skill_id': descriptor['id']}) == loaded
        assert run['_config'] == before
        assert 'skills' in public_document(run, [a.public() for a in engine.agents.values()], list(engine.events), [])['run']
    finally:
        await engine.close()


async def test_run_snapshot_survives_disk_edits_and_refresh_applies_to_next_run(tmp_path):
    engine, work = await team(tmp_path)
    path = skill(work, 'FIRST_BODY')
    try:
        first, pm = await start(engine)
        original = first['skills']['skills'][0]
        path.write_text('---\nname: review\ndescription: Updated procedure\n---\nSECOND_BODY', encoding='utf-8')
        refreshed = engine.skill_catalog()['skills'][0]
        assert refreshed['sha256'] != original['sha256']
        assert 'FIRST_BODY' in (await engine.execute_tool(first, pm, 'read_skill', {'skill_id': original['id']}))['content']
        second, new_pm = await start(engine)
        assert 'SECOND_BODY' in (await engine.execute_tool(second, new_pm, 'read_skill', {'skill_id': refreshed['id']}))['content']
    finally:
        await engine.close()


async def test_absent_skills_keep_previous_tool_surface_and_reject_path_arguments(tmp_path):
    engine, _ = await team(tmp_path)
    try:
        run, pm = await start(engine)
        assert run['skills'] == {'skills': [], 'errors': []}
        assert 'read_skill' not in {t['name'] for t in engine._model_tools(run, pm)}
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'read_skill', {'skill_id': '../../outside'})
        with pytest.raises(ValueError):
            await engine.execute_tool(run, pm, 'read_skill', {'path': 'outside/SKILL.md'})
    finally:
        await engine.close()


async def test_skill_tool_uses_normal_dispatch_budget_and_redaction(tmp_path):
    async def finish(profile, messages):
        result = json.loads(next(m['content'] for m in messages if m['role'] == 'tool'))
        assert result['ok'] is True and 'LOCAL_SKILL_TEST_SECRET' not in result['content']
        return reply(calls=[('finish_work', {'summary': 'Procedure checked.'})])

    client = ScriptClient([])
    engine, work = configured(tmp_path, client)
    engine.settings.secrets['local'] = 'LOCAL_SKILL_TEST_SECRET'
    skill(work, 'A procedure with LOCAL_SKILL_TEST_SECRET masked.')
    ident = engine.skill_catalog()['skills'][0]['id']
    client.responses = [reply(calls=[('read_skill', {'skill_id': ident})]), finish]
    try:
        run, pm = await start(engine, delegation_level=0)
        await settled(engine)
        assert pm.status == 'done'
        assert run['tool_calls'] == 2  # read_skill and finish_work
        assert run['model_calls'] == 2 and run['auto_collaborations'] == 0
        assert any(e['kind'] == 'skill' for e in engine.events)
        assert 'LOCAL_SKILL_TEST_SECRET' not in json.dumps(engine.snapshot())
    finally:
        await engine.close()


async def test_settings_and_application_roots_remain_denied(tmp_path, monkeypatch):
    import workbench.engine as module
    engine, work = await team(tmp_path)
    protected = tmp_path / 'installation'
    protected.mkdir()
    skill(protected, 'DO_NOT_READ_INSTALLATION')
    skill(engine.settings.directory, 'DO_NOT_READ_STATE')
    monkeypatch.setattr(module, 'PROTECTED_ROOTS', (protected,))
    engine.settings.value['paths']['read_roots'] = [str(tmp_path)]
    # A configured root inside a denied tree must also stay inaccessible.
    engine.settings.value['paths']['read_roots'] += [str(protected), str(engine.settings.directory)]
    try:
        value = engine.skill_catalog()
        assert not value['skills']
        assert 'DO_NOT_READ' not in json.dumps(value)
        assert value['errors']
    finally:
        await engine.close()


async def test_skills_api_requires_auth_uses_saved_roots_and_omits_body(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        assert (await client.get(auth.origin + '/api/skills')).status == 401
        await bootstrap(auth, client)
        work = tmp_path / 'work'
        work.mkdir()
        skill(work, 'PRIVATE_SKILL_BODY')
        engine = app[APP_KEY]
        engine.settings.value['paths']['read_roots'] = [str(work)]
        response = await client.get(auth.origin + '/api/skills')
        assert response.status == 200
        value = await response.json()
        assert value['config_revision'] == engine.settings.revision
        assert value['instance_id'] == engine.instance_id
        assert len(value['skills']) == 1 and 'PRIVATE_SKILL_BODY' not in json.dumps(value)
        assert (await client.get(auth.origin + '/api/skills?path=outside')).status == 400
        assert (await client.get(auth.origin + '/api/skills', headers={'Origin': 'https://untrusted.invalid'})).status == 403


@pytest.mark.parametrize('change', ['settings', 'shutdown'])
async def test_discovery_await_cannot_publish_using_stale_admission(tmp_path, monkeypatch, change):
    import workbench.engine as module
    engine, _ = await team(tmp_path)
    original = module.SkillCatalog
    entered, release = threading.Event(), threading.Event()

    def delayed(harness):
        entered.set()
        assert release.wait(5), 'test did not release the catalog'
        return original(harness)

    monkeypatch.setattr(module, 'SkillCatalog', delayed)
    pending = asyncio.create_task(start(engine))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == 'settings':
            engine.settings.revision += 1
        else:
            await engine.close()
        release.set()
        with pytest.raises(ValueError):
            await pending
        assert not engine.runs and not engine.agents
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await engine.close()


async def test_skill_load_does_not_bypass_tool_budget(tmp_path):
    client = ScriptClient([])
    engine, work = configured(tmp_path, client)
    skill(work)
    ident = engine.skill_catalog()['skills'][0]['id']
    engine.settings.value['limits']['max_tool_calls'] = 1
    client.responses = [reply(calls=[('read_skill', {'skill_id': ident}),
                                    ('read_skill', {'skill_id': ident})])]
    try:
        run, pm = await start(engine, delegation_level=0)
        await settled(engine)
        assert run['tool_calls'] == 1
        assert len([e for e in engine.events if e['kind'] == 'skill']) == 1
        assert pm.stop_reason == 'tool_limit'
    finally:
        await engine.close()
