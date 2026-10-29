"""Run-scoped shared reference notes; no real model, browser or external API."""
import copy
import json

import pytest

from workbench.config import DEFAULT, Settings, preview_settings_import, validate_settings
from workbench.engine import CollaborationLimitError, DelegationBlocked, WorkBoardError
from workbench.redaction import RedactionCapacityError
from workbench.server import APP_KEY
from test_config_server import bootstrap, serving
from test_engine import ScriptClient, configured, reply, settled, start
from test_pm_delegation import consume, deliver, spawn


@pytest.fixture(autouse=True)
def no_operator_secrets(monkeypatch):
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'BRAVE_SEARCH_API_KEY'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
async def board(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.settings.value['work_board']['enabled'] = True
    engine.kick = lambda agent: None
    run, pm = await start(engine)
    pm.pending.clear()
    pm.status = 'working'
    worker = engine._new_agent(run, 'local', 'researcher', pm.id, assignment='Research one source')
    worker.status = 'working'
    try:
        yield engine, run, pm, worker, work
    finally:
        await engine.close()


def human(engine, run, text='Human reference note', *, key='synthetic-post-id-0001', reply_to=None):
    return engine.post_work_board(run['id'], text, client_post_id=key, reply_to=reply_to)


@pytest.mark.parametrize('bad', [None, 0, 1, 'true', [], {'enabled': True, 'secret': 'value'}])
def test_setting_is_exact_boolean_and_rejects_extra_fields(bad):
    raw = {'work_board': bad if isinstance(bad, dict) else {'enabled': bad}}
    with pytest.raises(ValueError):
        validate_settings(raw)


def test_legacy_and_export_import_roundtrip_never_rewrite_until_save(tmp_path):
    raw = copy.deepcopy(DEFAULT)
    raw.pop('work_board')
    initial = json.dumps(raw).encode()
    (tmp_path / 'settings.json').write_bytes(initial)
    settings = Settings(tmp_path)
    assert settings.value['work_board'] == {'enabled': False}
    assert settings.path.read_bytes() == initial
    draft, warnings = preview_settings_import(settings.export())
    assert warnings == [] and draft['work_board'] == {'enabled': False}
    draft['work_board']['enabled'] = True
    assert settings.path.read_bytes() == initial and not settings.value['work_board']['enabled']
    settings.save(draft)
    assert Settings(tmp_path).value['work_board'] == {'enabled': True}
    assert settings.export()['config']['work_board'] == {'enabled': True}


def test_board_setting_survives_missing_path_recovery_without_enabling_execution(tmp_path):
    raw = copy.deepcopy(DEFAULT)
    raw['work_board']['enabled'] = True
    raw['paths']['read_roots'] = [str(tmp_path / 'removed-version')]
    saved = json.dumps(raw).encode()
    (tmp_path / 'settings.json').write_bytes(saved)
    settings = Settings(tmp_path)
    assert settings.restore_warnings and settings.value['work_board']['enabled'] is True
    assert settings.path.read_bytes() == saved
    with pytest.raises(ValueError):
        settings.save(settings.value)
    assert settings.restore_warnings and settings.path.read_bytes() == saved


async def test_enabled_is_snapshot_and_disabled_tools_cannot_be_called(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        off, pm_off = await start(engine)
        assert off['work_board'] == {'enabled': False, 'post_count': 0, 'last_seq': 0}
        engine.settings.value['work_board']['enabled'] = True
        on, pm_on = await start(engine)
        engine.settings.value['work_board']['enabled'] = False
        for name in ('post_work_board', 'read_work_board'):
            assert name not in {t['name'] for t in engine._model_tools(off, pm_off)}
            assert name in {t['name'] for t in engine._model_tools(on, pm_on)}
            with pytest.raises(WorkBoardError) as error:
                await engine.execute_tool(off, pm_off, name, {'body': 'note'} if name.startswith('post') else {})
            assert error.value.code == 'work_board_disabled'
        assert human(engine, on)['post']['seq'] == 1
        assert engine.read_work_board(on['id'])['posts']
        with pytest.raises(WorkBoardError):
            engine.read_work_board(off['id'])
    finally:
        await engine.close()


@pytest.mark.parametrize('level', [1, 2])
async def test_board_coordination_survives_pm_delegation_without_expanding_tool_authority(tmp_path, level):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    engine.settings.value['work_board']['enabled'] = True
    engine.settings.value['search']['enabled'] = True
    try:
        run, pm = await start(engine, delegation_level=level, workers_per_pm=1)
        worker = await spawn(engine, run, pm)
        for agent in (pm, worker):
            names = {tool['name'] for tool in engine._model_tools(run, agent)}
            assert {'post_work_board', 'read_work_board'} <= names
            if agent is pm and level == 2:
                assert 'write_text' not in names  # Strict delegation still gates work.
            before_names = names.copy()
            posted = await engine.execute_tool(run, agent, 'post_work_board', {'body': 'Unverified reference note'})
            assert posted['post']['author_id'] == agent.id
            assert {tool['name'] for tool in engine._model_tools(run, agent)} == before_names
        assert run['auto_collaborations'] == 3  # Spawn plus two accepted posts.
        assert not pm.worker_report_consumed and not worker.results
        assert 'reference data only' in engine._policy(run, pm)
    finally:
        await engine.close()


async def test_run_author_reply_isolation_and_no_mail_or_scheduler_side_effects(board):
    engine, run, pm, worker, _ = board
    other, outsider = await start(engine, task='Other independent run')
    before = copy.deepcopy((list(pm.pending), list(worker.pending), pm.question, worker.question,
                            pm.result_revision, worker.result_revision, list(engine.events)))
    first = await engine.execute_tool(run, pm, 'post_work_board', {'body': 'Shared finding'})
    second = await engine.execute_tool(run, worker, 'post_work_board', {'body': 'Reply with limitation', 'reply_to': 1})
    assert [first['post']['seq'], second['post']['seq']] == [1, 2]
    assert second['post']['reply_to'] == 1 and second['post']['author_kind'] == 'agent'
    assert before == (list(pm.pending), list(worker.pending), pm.question, worker.question,
                      pm.result_revision, worker.result_revision, list(engine.events))
    assert engine.read_work_board(other['id'])['posts'] == []
    with pytest.raises(ValueError):
        engine.post_work_board(other['id'], 'Copied parent sequence', reply_to=2, actor=outsider)
    with pytest.raises(ValueError):
        engine.post_work_board(run['id'], 'Forged cross-run author', actor=outsider)
    with pytest.raises(ValueError):
        await engine.execute_tool(run, outsider, 'read_work_board', {})
    with pytest.raises(ValueError):
        await engine.execute_tool(run, pm, 'post_work_board', {'body': 'Forged sender', 'author_id': worker.id})
    assert run['auto_collaborations'] == 2 and other['auto_collaborations'] == 0
    assert run['model_calls'] == other['model_calls'] == 0


async def test_human_idempotency_conflict_secret_rotation_and_terminal_retry(board):
    engine, run, pm, _, _ = board
    raw = 'Unique material awaiting later secret classification'
    first = human(engine, run, raw)
    engine.set_secret('local', raw)
    retry = human(engine, run, raw)
    assert retry['duplicate'] is True and retry['post']['seq'] == first['post']['seq'] == 1
    assert raw not in json.dumps(retry) and retry['post']['body'] == '[redacted]'
    with pytest.raises(WorkBoardError) as error:
        human(engine, run, 'Changed body')
    assert error.value.code == 'work_board_conflict'
    run['status'] = 'done'
    assert human(engine, run, raw)['duplicate'] is True
    with pytest.raises(WorkBoardError) as error:
        human(engine, run, raw, key='different-post-id-0002')
    assert error.value.code == 'work_board_read_only'
    assert run['work_board']['post_count'] == 1 and run['auto_collaborations'] == 0
    assert not pm.worker_report_consumed and not engine.read_work_board(run['id'])['can_post']


@pytest.mark.parametrize('status', ['done', 'error', 'stopping', 'stopped'])
async def test_terminal_or_failed_agent_cannot_post_but_existing_board_remains_readable(board, status):
    engine, run, pm, *_ = board
    human(engine, run)
    pm.status = status
    with pytest.raises(WorkBoardError) as error:
        engine.post_work_board(run['id'], 'Agent must not resume', actor=pm)
    assert error.value.code == 'work_board_read_only'
    assert len(engine.read_work_board(run['id'])['posts']) == 1 and run['auto_collaborations'] == 0


@pytest.mark.parametrize('status', ['done', 'error', 'stopping', 'stopped'])
async def test_terminal_run_allows_history_and_same_operation_retry_only(board, status):
    engine, run, *_ = board
    human(engine, run)
    run['status'] = status
    assert human(engine, run)['duplicate'] is True
    with pytest.raises(WorkBoardError) as error:
        human(engine, run, key='new-post-after-terminal')
    assert error.value.code == 'work_board_read_only'
    assert engine.read_work_board(run['id'])['can_post'] is False
    assert run['work_board']['post_count'] == 1


@pytest.mark.parametrize('field,value', [('body', ''), ('body', ' '), ('body', 'x' * 2001),
    ('body', 'bad\0text'), ('body', 12), ('reply_to', True), ('reply_to', 0), ('reply_to', 2),
    ('client_post_id', ''), ('client_post_id', 'x' * 129), ('client_post_id', 'spaces are invalid!')])
async def test_rejected_post_never_uses_sequence_or_idempotency_key(board, field, value):
    engine, run, _, _, _ = board
    args = {'body': 'Valid note', 'client_post_id': 'synthetic-post-id-0001'}
    args[field] = value
    with pytest.raises(ValueError):
        engine.post_work_board(run['id'], **args)
    assert not run['_work_board_posts'] and not run['_work_board_submissions']
    assert run['work_board']['last_seq'] == run['auto_collaborations'] == 0
    assert human(engine, run)['post']['seq'] == 1


@pytest.mark.parametrize('field,value', [('after_seq', True), ('after_seq', -1), ('after_seq', 1),
    ('after_seq', '0'), ('limit', False), ('limit', 0), ('limit', 51), ('limit', 1.5)])
async def test_read_cursor_and_limit_require_exact_current_integer(board, field, value):
    engine, run, *_ = board
    with pytest.raises(ValueError):
        engine.read_work_board(run['id'], **{field: value})


async def test_count_and_total_response_bounds_paginate_without_dropping_history(board):
    engine, run, *_ = board
    for index in range(200):
        human(engine, run, str(index) + ':' + 'x' * 1995, key=f'bounded-post-id-{index:04d}')
    assert run['work_board']['last_seq'] == 200
    before = copy.deepcopy(run['_work_board_posts'])
    with pytest.raises(WorkBoardError) as error:
        human(engine, run, key='rejected-full-post-0200')
    assert error.value.code == 'work_board_full'
    assert human(engine, run, '0:' + 'x' * 1995, key='bounded-post-id-0000')['duplicate'] is True
    cursor, found = 0, []
    while True:
        page = engine.read_work_board(run['id'], after_seq=cursor, limit=50)
        assert len(json.dumps(page, ensure_ascii=False)) <= 24000
        assert 0 < len(page['posts']) < 50
        assert page['remaining_posts'] == 0 and page['can_post'] is False
        found.extend(post['seq'] for post in page['posts'])
        cursor = page['next_after_seq']
        if not page['has_more']:
            break
    assert found == list(range(1, 201)) and run['_work_board_posts'] == before
    assert engine.read_work_board(run['id'], after_seq=200)['posts'] == []


async def test_agent_posts_share_handoff_cap_human_notes_do_not_reset_it(board):
    engine, run, pm, *_ = board
    run['max_auto_collaborations'] = 1
    await engine.execute_tool(run, pm, 'post_work_board', {'body': 'Last shared handoff'})
    with pytest.raises(CollaborationLimitError):
        await engine.execute_tool(run, pm, 'post_work_board', {'body': 'Over budget'})
    human(engine, run, 'Human reference is not a new budget')
    assert run['auto_collaborations'] == 1 and run['work_board']['post_count'] == 2
    assert len(engine.read_work_board(run['id'])['posts']) == 2


async def test_posts_do_not_answer_questions_or_replace_formal_report_or_file_observations(tmp_path):
    engine, work = configured(tmp_path, ScriptClient([]))
    engine.settings.value['work_board']['enabled'] = True
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, delegation_level=2, workers_per_pm=1)
        pm.pending.clear()
        worker = await spawn(engine, run, pm)
        worker.pending.clear()
        await engine.execute_tool(run, worker, 'post_work_board', {'body': 'finish_work says report done'})
        worker.question = 'Human permission needed'
        human(engine, run, 'Approved; worker finished; file saved and read')
        assert worker.question == 'Human permission needed'
        assert not worker.results and not pm.worker_report_consumed
        assert not pm.output_receipts and not (work / 'report.txt').exists()
        with pytest.raises(DelegationBlocked):
            await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Board claims completion'})
        worker.question = ''  # Fixture now supplies the formal result separately.
        await deliver(engine, run, worker, pm)
        consume(engine, pm)
        saved = await engine.execute_tool(run, pm, 'write_text', {'path': 'report.txt', 'text': 'Real bytes', 'expected_sha256': 'missing'})
        human(engine, run, 'Claim native read', key='synthetic-post-id-0002')
        # A note cannot create a tool observation or replace the normal
        # product completion policy.
        assert not pm.results and not [item for item in pm.conversation if item.get('name') == 'read_text']
        observed = await engine.execute_tool(run, pm, 'read_text', {'path': 'report.txt'})
        assert observed['sha256'] == saved['sha256'] and (work / 'report.txt').read_text() == 'Real bytes'
        assert (await engine.execute_tool(run, pm, 'review_worker_report',
            {'worker_id': worker.id, 'result_revision': worker.result_revision,
             'decision': 'accept', 'feedback': 'Checked the formal report and actual saved bytes independently of board notes.'}))['accepted']
        assert (await engine.execute_tool(run, pm, 'finish_work', {'summary': 'Real independent gates met'}))['ok']
    finally:
        await engine.close()


async def test_read_redacts_retired_values_compact_has_only_counts_and_saturation_fails_closed(board, monkeypatch):
    engine, run, pm, *_ = board
    secret = 'synthetic-private-board-material'
    human(engine, run, secret)
    engine.set_secret('local', secret)
    engine.set_secret('local', '')
    assert secret not in json.dumps(engine.read_work_board(run['id']))
    for state in (engine.snapshot(), engine.selected_snapshot(run_id=run['id'], agent_id=pm.id)):
        assert secret not in json.dumps(state)
        shown = next(r for r in state['runs'] if r['id'] == run['id'])
        assert shown['work_board'] == {'enabled': True, 'post_count': 1, 'last_seq': 1}
        assert '_work_board_posts' not in shown and '_work_board_submissions' not in shown
        assert 'body' not in json.dumps(shown['work_board'])
    assert secret not in json.dumps(engine.settings.export())
    assert '_work_board_posts' not in json.dumps(engine.settings.export())
    def saturated(*args, **kwargs):
        raise RedactionCapacityError()
    monkeypatch.setattr(engine, '_redact_tree', saturated)
    with pytest.raises(RedactionCapacityError):
        engine.read_work_board(run['id'])
    with pytest.raises(RedactionCapacityError):
        human(engine, run, 'Must not commit', key='synthetic-post-id-0002')
    assert run['work_board']['post_count'] == 1 and len(run['_work_board_submissions']) == 1


async def test_mask_expansion_is_measured_once_and_preserves_paginated_cursor(board):
    engine, run, *_ = board
    engine.set_secret('local', 'a')
    for index in range(2):
        human(engine, run, 'a' * 2000, key=f'expanded-mask-key-{index:04d}')
    first = engine.read_work_board(run['id'], limit=50)
    assert len(first['posts']) == 1 and first['has_more'] is True
    assert first['posts'][0]['body'] == '[redacted]' * 2000
    assert len(json.dumps(first, ensure_ascii=False)) <= 24000
    assert engine.read_work_board(run['id'], limit=50) == first
    second = engine.read_work_board(run['id'], after_seq=first['next_after_seq'])
    assert second['posts'][0]['seq'] == 2 and second['has_more'] is False
    assert second['posts'][0]['body'] == first['posts'][0]['body']


async def test_mask_revision_tracks_new_and_retired_secrets_after_projection_at_same_post_count(board, monkeypatch):
    engine, run, pm, *_ = board
    name = 'SYNTHETIC_BOARD_ENV'
    engine.settings.value['providers'][0]['api_key_env'] = name
    monkeypatch.setenv(name, 'first-board-private-value')
    human(engine, run, 'first-board-private-value second-board-private-value')
    first = engine.read_work_board(run['id'])
    assert first['redaction_revision'] == engine.snapshot()['redaction_revision']
    monkeypatch.setenv(name, 'second-board-private-value')
    # The snapshot synchronizes new environment values before publishing its
    # revision; no post and no config revision change is needed to invalidate UI.
    state = engine.selected_snapshot(run_id=run['id'], agent_id=pm.id)
    assert state['redaction_revision'] == first['redaction_revision'] + 1
    current = engine.read_work_board(run['id'])
    assert current['redaction_revision'] == state['redaction_revision'] == engine.snapshot()['redaction_revision']
    assert current['last_seq'] == first['last_seq'] == 1
    assert 'first-board-private-value' not in json.dumps(current)
    assert 'second-board-private-value' not in json.dumps(current)
    monkeypatch.delenv(name)
    assert engine.snapshot()['redaction_revision'] == current['redaction_revision']  # Retirement retains masks.
    assert engine.read_work_board(run['id'])['posts'] == current['posts']


async def test_only_explicit_tool_read_enters_context_and_uses_normal_tool_budget(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([reply(calls=[('read_work_board', {})]), reply('Done')]))
    engine.settings.value['work_board']['enabled'] = True
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        human(engine, run, 'Read this unique shared fact')
        assert not engine.client.calls and not pm.conversation and run['tool_calls'] == run['model_calls'] == 0
        await engine._agent_loop(pm)
        assert run['tool_calls'] == 1 and run['model_calls'] == 2
        assert 'Read this unique shared fact' not in json.dumps(engine.client.calls[0])
        assert 'Read this unique shared fact' in json.dumps(engine.client.calls[1])
        assert not any(human for _, human in pm.pending)
    finally:
        await engine.close()


async def test_http_auth_origin_exact_payload_idempotency_and_readonly(tmp_path, monkeypatch):
    async with serving(tmp_path) as (auth, app, client):
        endpoint = auth.origin + '/api/runs/unknown/work-board'
        assert (await client.get(endpoint)).status == 401
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        engine.settings.value['providers'][0]['model'] = 'fixture'
        engine.settings.value['work_board']['enabled'] = True
        engine.kick = lambda agent: None
        run, pm = await start(engine)
        endpoint = auth.origin + f'/api/runs/{run["id"]}/work-board'
        payload = {'body': 'Human reference', 'client_post_id': 'http-post-id-00001'}
        assert (await client.post(endpoint, json=payload)).status == 403
        headers = {'Origin': auth.origin}
        assert (await client.post(endpoint, json={**payload, 'author_id': pm.id}, headers=headers)).status == 400
        assert not run['_work_board_posts']
        accepted = await client.post(endpoint, json=payload, headers=headers)
        first = await accepted.json()
        assert accepted.status == 200 and first['post']['author_kind'] == 'human' and first['post']['author_id'] is None
        assert (await (await client.post(endpoint, json=payload, headers=headers)).json())['duplicate'] is True
        collision = await client.post(endpoint, json={**payload, 'body': 'Changed'}, headers=headers)
        assert collision.status == 409 and (await collision.json())['code'] == 'work_board_conflict'
        # A response failure after acceptance must not duplicate the post when
        # the human explicitly retries the same operation ID.
        from workbench import server
        original_response = server.web.json_response
        fail_once = True
        def fail_after_commit(data, *args, **kwargs):
            nonlocal fail_once
            if fail_once and isinstance(data, dict) and data.get('post') and data.get('duplicate') is False:
                fail_once = False
                raise OSError('Synthetic response failure')
            return original_response(data, *args, **kwargs)
        monkeypatch.setattr(server.web, 'json_response', fail_after_commit)
        uncertain = {**payload, 'client_post_id': 'http-post-id-uncertain'}
        failed_response = await client.post(endpoint, json=uncertain, headers=headers)
        assert failed_response.status == 503 and run['work_board']['post_count'] == 2
        recovered = await (await client.post(endpoint, json=uncertain, headers=headers)).json()
        assert recovered['duplicate'] and recovered['post']['seq'] == 2
        assert run['work_board']['post_count'] == 2 and run['auto_collaborations'] == 0
        for query in ('?limit=true', '?limit=0', '?limit=51', '?after_seq=-1', '?after_seq=1&after_seq=1', '?author_id=x'):
            assert (await client.get(endpoint + query)).status == 400
        run['status'] = 'done'
        assert (await client.get(endpoint)).status == 200
        assert (await client.post(endpoint, json=payload, headers=headers)).status == 200
        new = await client.post(endpoint, json={**payload, 'client_post_id': 'http-post-id-00002'}, headers=headers)
        assert new.status == 409 and (await new.json())['code'] == 'work_board_read_only'
        engine.settings.value['work_board']['enabled'] = False
        off, _ = await start(engine)
        disabled = auth.origin + f'/api/runs/{off["id"]}/work-board'
        for response in (await client.get(disabled), await client.post(disabled, json=payload, headers=headers)):
            assert response.status == 409 and (await response.json())['code'] == 'work_board_disabled'
        assert run['model_calls'] == off['model_calls'] == 0
