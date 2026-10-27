"""Durable display history; no live provider, browser, or operator state."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from workbench.config import Settings
from workbench.engine import Engine
from workbench.history import (HistoryStore, HistoryError, ArchivedReadOnly, public_document,
                               validate, redact_tree, archived_view)
from workbench.redaction import SecretRedactor
from test_engine import configured, ScriptClient, start
from test_config_server import bootstrap, serving
from workbench.server import APP_KEY

RUN = 'r-' + '1' * 16
AGENT = 'a-' + '2' * 16


def document(ident=RUN, text='public text'):
    agent_id = AGENT if ident == RUN else 'a-' + ident[2:]
    run = {'id': ident, 'task': 'Original task', 'status': 'running', 'created_at': 10.0,
           'agent_ids': [agent_id], 'pm_agent_ids': [agent_id],
           'work_board': {'enabled': True, 'post_count': 0, 'last_seq': 0}}
    agent = {'id': agent_id, 'run_id': ident, 'name': 'PM', 'role': 'pm', 'profile_id': 'local',
             'parent_id': None, 'status': 'working', 'question': '', 'last_error': '', 'turns': 0,
             'assignment': 'Original task', 'configured_profile': {'id': 'local', 'label': 'Old label', 'kind': 'openai', 'model': 'old-model'},
             'logs': [{'id': 1, 'kind': 'assistant', 'text': text, 'thinking': 'displayed model thinking', 'at': 11.0}],
             'results': [], 'output_receipts': []}
    return {'run': run, 'agents': [agent], 'events': [], 'board': []}


@pytest.fixture
def store(tmp_path):
    value = HistoryStore(tmp_path / 'state')
    try:
        assert not value.error
        yield value
    finally:
        value.close()


def test_transactional_store_and_readonly_restoration_are_separate_from_engine(store):
    value = document()
    at = store.save(value, lambda s: s)
    restored, saved = store.read(RUN)
    assert restored == value and saved == at
    view = archived_view(restored, saved)
    assert view['run']['status'] == 'interrupted' and view['run']['original_status'] == 'running'
    assert view['run']['read_only'] and view['run']['history_saved_at'] == at
    assert view['agents'][0]['status'] == 'interrupted'
    assert not view['agents'][0]['message_eligibility']['allowed']
    assert restored == value


def test_rolling_display_windows_do_not_evict_earlier_durable_records(store):
    first = document()
    store.save(first, lambda s: s)
    current = document()
    current['agents'][0]['logs'] = [{'id': 2, 'kind': 'assistant', 'text': 'later', 'at': 12.0}]
    store.save(current, lambda s: s)
    restored, _ = store.read(RUN)
    assert [row['id'] for row in restored['agents'][0]['logs']] == [1, 2]
    assert restored['agents'][0]['logs'][0]['thinking'] == 'displayed model thinking'


def test_public_allowlist_excludes_private_authority_and_context():
    value = document()
    value['run'].update(_config={'api_key': 'private'}, _executor=object(), _stop_task=object())
    agent = value['agents'][0]
    agent.update(conversation=[{'system': 'private-context'}], pending=['unsent'], pending_worker_reports={'token': 2},
                 worker_report_deliveries={'token': 3}, original_history=['private-original'])
    projected = public_document(value['run'], [agent], [], [])
    encoded = json.dumps(projected)
    for word in ('private-context', 'unsent', 'pending_worker_reports', 'private-original', 'api_key', '_executor'):
        assert word not in encoded
    assert projected['agents'][0]['logs'][0]['thinking'] == 'displayed model thinking'


@pytest.mark.parametrize('mutation', ['agent_status', 'log_text', 'log_at', 'parent', 'agent_roster', 'pm', 'mail_peer', 'board_author', 'extra_private'])
def test_corrupt_display_relationships_fail_before_rendering(mutation):
    value = document()
    if mutation == 'agent_status': value['agents'][0].pop('status')
    elif mutation == 'log_text': value['agents'][0]['logs'][0].pop('text')
    elif mutation == 'log_at': value['agents'][0]['logs'][0]['at'] = 'now'
    elif mutation == 'parent': value['agents'][0]['parent_id'] = 'a-' + '3' * 16
    elif mutation == 'agent_roster': value['run']['agent_ids'] = []
    elif mutation == 'pm': value['run']['pm_agent_ids'] = ['a-' + '3' * 16]
    elif mutation == 'mail_peer': value['events'] = [{'id': 2, 'kind': 'mail', 'text': 'hi', 'at': 12, 'run_id': RUN, 'agent_id': AGENT, 'from_agent_id': AGENT, 'to_agent_id': 'other'}]
    elif mutation == 'board_author':
        value['run']['work_board'].update(post_count=1, last_seq=1)
        value['board'] = [{'seq': 1, 'run_id': RUN, 'author_kind': 'agent', 'author_id': 'other', 'author_name': 'Other', 'body': 'hi', 'reply_to': None, 'created_at': 12}]
    else: value['agents'][0]['pending'] = ['must-not-restore']
    with pytest.raises(HistoryError): validate(value)


def test_literal_mask_spanning_secret_is_redacted_and_short_masks_stay_stable():
    mask = SecretRedactor()
    mask.remember(['x[redacted]y'])
    assert redact_tree('prefix x[redacted]y suffix', mask.redact) == 'prefix [redacted] suffix'
    short = SecretRedactor(); short.remember(['a'])
    once = redact_tree('a [redacted]', short.redact)
    assert once == '[redacted] [redacted]'
    assert redact_tree(once, short.redact) == once


def test_rotation_scrubs_known_values_from_existing_disk_and_reloads(store):
    old = 'synthetic-old-key-0123456789'
    later = 'synthetic-new-key-9876543210'
    mask = SecretRedactor(); mask.remember([old])
    store.save(document(text=f'{old} and {later}'), mask.redact)
    assert old.encode() not in store.path.read_bytes() and later.encode() in store.path.read_bytes()
    mask.remember([later]); store.scrub(mask.redact)
    raw = store.path.read_bytes()
    assert old.encode() not in raw and later.encode() not in raw
    assert store.read(RUN)[0]['agents'][0]['logs'][0]['text'] == '[redacted] and [redacted]'
    assert not Path(str(store.path) + '-journal').exists()


def test_failed_write_keeps_last_committed_public_record(store, monkeypatch):
    import workbench.history as history
    store.save(document(), lambda s: s)
    def failed(_): raise HistoryError('synthetic write failure')
    monkeypatch.setattr(history, 'encode', failed)
    with pytest.raises(HistoryError): store.save(document(text='newer unsaved'), lambda s: s)
    assert store.error and store.read(RUN)[0]['agents'][0]['logs'][0]['text'] == 'public text'


def test_quota_failure_preserves_prior_runs_without_eviction(store, monkeypatch):
    import workbench.history as history
    monkeypatch.setattr(history, 'MAX_RUNS', 1)
    store.save(document(), lambda s: s)
    with pytest.raises(HistoryError): store.save(document('r-' + '3' * 16), lambda s: s)
    assert list(store.summaries()) == [RUN]


def test_writer_lease_is_independent_of_port_and_never_overwrites_other_instance(store):
    store.save(document(), lambda s: s)
    second = HistoryStore(store.directory.parent)
    try:
        assert second.error and not second._available
        with pytest.raises(HistoryError): second.summaries()
        with pytest.raises(HistoryError): second.save(document(text='overwrite'), lambda s: s)
        assert store.read(RUN)[0]['agents'][0]['logs'][0]['text'] == 'public text'
    finally:
        second.close()
    store.close()
    third = HistoryStore(store.directory.parent)
    try:
        assert not third.error and RUN in third.summaries()
        third.save(document('r-' + '4' * 16), lambda s: s)
        assert len(third.summaries()) == 2
    finally:
        third.close()


@pytest.mark.parametrize('kind', ['corrupt_header', 'future_version', 'unknown_table', 'invalid_json'])
def test_unknown_or_corrupt_store_is_preserved_without_overwrite(tmp_path, kind):
    first = HistoryStore(tmp_path)
    first.save(document(), lambda s: s)
    path = first.path; first.close()
    if kind == 'corrupt_header': path.write_bytes(b'original unsupported content')
    else:
        with sqlite3.connect(path) as connection:
            if kind == 'future_version': connection.execute('PRAGMA user_version=999')
            elif kind == 'unknown_table': connection.execute('CREATE TABLE future(value TEXT)')
            else: connection.execute("UPDATE archives SET payload='{}'")
    before = path.read_bytes()
    next_store = HistoryStore(tmp_path)
    try:
        if kind == 'invalid_json':
            with pytest.raises(HistoryError): next_store.scrub(lambda s: s)
        else:
            assert next_store.error
            with pytest.raises(HistoryError): next_store.save(document(), lambda s: s)
        assert path.read_bytes() == before
    finally:
        next_store.close()


def test_linked_history_file_is_rejected_without_target_change(tmp_path):
    state = tmp_path / 'state'; (state / 'history').mkdir(parents=True)
    original = tmp_path / 'original.sqlite3'; original.write_bytes(b'preserve original')
    os.link(original, state / 'history/work-history.sqlite3')
    value = HistoryStore(state)
    try:
        assert value.error and not value._available
        assert original.read_bytes() == b'preserve original'
    finally:
        value.close()


async def test_restart_restores_accepted_human_logs_reports_receipts_mail_board_without_execution(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda _: None
    engine.settings.value['work_board']['enabled'] = True
    engine.save_settings(engine.settings.value)
    run, pm = await start(engine)
    worker = engine._new_agent(run, 'local', 'researcher', pm.id, assignment='Specific assignment')
    engine.record_result(worker, 'finish_work', 'Worker report')
    engine.record_receipt(pm, 'write_text', {'path': 'public-result.txt', 'bytes': 4, 'sha256': 'f' * 64, 'operation': 'create'})
    engine.log(pm, 'assistant', 'Visible response', thinking='Displayed thinking')
    engine._mail(worker, pm, 'Visible team mail')
    engine.post_work_board(run['id'], 'Shared note', client_post_id='test-history-post-0001')
    await engine.human_message(pm.id, 'Accepted before processing')
    assert not engine.client.calls
    assert any(row['text'] == 'Accepted before processing' for row in pm.logs)
    # Simulate process loss with no model task: close only the OS writer lease.
    engine.history.close()
    fresh = Engine(Settings(tmp_path / 'state'), ScriptClient([]))
    fresh.kick = lambda _: pytest.fail('Archive must not schedule work')
    try:
        assert fresh.instance_id != engine.instance_id
        assert not fresh.runs and not fresh.agents and not fresh.reservations
        view = fresh.selected_snapshot(run_id=run['id'], agent_id=pm.id)
        assert view['runs'][0]['archived'] and view['runs'][0]['status'] == 'interrupted'
        assert view['runs'][0]['original_status'] == 'running'
        archive_pm = next(row for row in view['agents'] if row['id'] == pm.id)
        assert any(row['text'] == 'Accepted before processing' for row in archive_pm['logs'])
        assert any(row.get('thinking') == 'Displayed thinking' for row in archive_pm['logs'])
        assert archive_pm['output_receipts'][0]['path'] == 'public-result.txt'
        assert any(row['kind'] == 'mail' and row['text'] == 'Visible team mail' for row in view['events'])
        fresh.settings.value['work_board']['enabled'] = False
        board = fresh.read_work_board(run['id'])
        assert board['posts'][0]['body'] == 'Shared note' and not board['can_post']
        assert board['archived'] and board['instance_id'] == fresh.instance_id
        with pytest.raises(ArchivedReadOnly): await fresh.human_message(pm.id, 'No')
        with pytest.raises(ArchivedReadOnly): await fresh.stop_run(run['id'])
        with pytest.raises(ArchivedReadOnly): fresh.post_work_board(run['id'], 'No', client_post_id='test-history-post-0002')
        assert not fresh.client.calls
        assert fresh.preflight({'task': 'A new task', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})['can_start']
    finally:
        await fresh.close()
        engine.closed = True


async def test_normal_shutdown_preserves_completed_status_and_profile_identity(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([])); engine.kick = lambda _: None
    engine.save_settings(engine.settings.value)
    run, pm = await start(engine)
    run['status'] = pm.status = 'done'; pm.pending.clear()
    engine.record_result(pm, 'assistant_response', 'Completed')
    await engine.close()
    fresh = Engine(Settings(tmp_path / 'state'), ScriptClient([]))
    try:
        fresh.settings.value['providers'][0]['model'] = 'new-model'
        view = fresh.selected_snapshot(run_id=run['id'], agent_id=pm.id)
        assert view['runs'][0]['status'] == 'done'
        assert view['agents'][0]['configured_profile']['model'] == 'fixture'
        assert not fresh.runs and not fresh.agents
    finally:
        await fresh.close()


async def test_secret_change_failure_is_visible_and_does_not_apply_credentials(tmp_path, monkeypatch):
    engine, _ = configured(tmp_path, ScriptClient([])); engine.kick = lambda _: None
    try:
        await start(engine)
        old = dict(engine.settings.secrets)
        def failed(_): raise HistoryError('synthetic archive scrub failure')
        monkeypatch.setattr(engine.history, 'scrub', failed)
        with pytest.raises(HistoryError): engine.set_secret('local', 'new-secret')
        assert engine.settings.secrets == old
    finally:
        await engine.close()


async def test_second_engine_blocks_new_work_without_touching_first(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([])); engine.kick = lambda _: None
    engine.save_settings(engine.settings.value); run, pm = await start(engine)
    other = Engine(Settings(tmp_path / 'state'), ScriptClient([]))
    try:
        assert other.public_config()['history_storage']['status'] == 'error'
        assert not other.preflight({'task': 'No duplicate owner', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0})['can_start']
        with pytest.raises(HistoryError): other.set_secret('local', 'not-applied')
        assert run['status'] == 'running' and not engine.closed
    finally:
        await other.close(); await engine.close()


async def test_archive_mutations_are_rejected_over_existing_http_endpoints(tmp_path):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]; engine.kick = lambda _: None
        engine.settings.value['providers'][0]['model'] = 'fixture'
        engine.settings.value['work_board']['enabled'] = True
        engine.save_settings(engine.settings.value)
        run, pm = await start(engine, max_workers=0)
        engine.post_work_board(run['id'], 'kept', client_post_id='test-history-post-0001')
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        state = await (await client.get(auth.origin + '/api/state', params={'run_id': run['id'], 'agent_id': pm.id})).json()
        assert any(row['id'] == run['id'] and row['read_only'] for row in state['runs'])
        headers = {'Origin': auth.origin}
        for url, body in [(f'/api/agents/{pm.id}/message', {'text': 'No'}),
                          (f'/api/runs/{run["id"]}/stop', {}),
                          (f'/api/runs/{run["id"]}/work-board', {'body': 'No', 'client_post_id': 'test-history-post-0002'})]:
            response = await client.post(auth.origin + url, json=body, headers=headers)
            assert response.status == 409
            assert (await response.json())['code'] == 'archive_read_only'


@pytest.mark.parametrize('header', ['', 'stale-instance-from-previous-process'])
async def test_missing_or_stale_instance_blocks_mutations_before_handlers(tmp_path, header):
    async with serving(tmp_path) as (auth, app, client):
        await bootstrap(auth, client)
        engine = app[APP_KEY]
        before = copy.deepcopy(engine.settings.value)
        revision = engine.settings.revision
        for path, payload, method in [('/api/config', {'config_revision': revision, 'config': before}, 'PUT'),
                                      ('/api/runs', {'task': 'must not start'}, 'POST'),
                                      ('/api/secrets', {'profile_id': 'local', 'key': 'must-not-apply'}, 'POST')]:
            response = await client.request(method, auth.origin + path, json=payload,
                headers={'Origin': auth.origin, 'X-Workbench-Instance': header})
            assert response.status == 409
            value = await response.json()
            assert value['code'] == 'instance_changed' and value['instance_id'] == engine.instance_id
        assert not engine.runs and not engine.settings.secrets
        assert engine.settings.value == before and engine.settings.revision == revision


def test_duplicate_agent_identity_in_another_run_cannot_be_written(store):
    store.save(document(), lambda s: s)
    duplicate = document('r-' + '3' * 16)
    duplicate['run']['agent_ids'] = duplicate['run']['pm_agent_ids'] = [AGENT]
    duplicate['agents'][0]['id'] = AGENT
    with pytest.raises(HistoryError): store.save(duplicate, lambda s: s)
    assert list(store.summaries()) == [RUN]


async def test_shutdown_always_closes_bridge_and_writer_lease_after_persistence_failure(tmp_path, monkeypatch):
    from workbench.redaction import RedactionCapacityError
    engine, _ = configured(tmp_path, ScriptClient([])); engine.kick = lambda _: None
    run, pm = await start(engine)
    run['status'] = pm.status = 'done'
    closed = []
    async def bridge_close(): closed.append(True)
    def failure(_): raise RedactionCapacityError()
    monkeypatch.setattr(engine.copilot_bridge, 'close', bridge_close)
    monkeypatch.setattr(engine, '_persist_run', failure)
    with pytest.raises(RedactionCapacityError): await engine.close()
    assert closed == [True] and engine.history._lease is None
    reopened = HistoryStore(tmp_path / 'state')
    try:
        assert not reopened.error
    finally:
        reopened.close()


@pytest.mark.parametrize('secret', ['a', 'human', 'working', 'assistant', 'role-secret'])
def test_short_secret_masks_display_fields_without_corrupting_app_linkage(store, secret):
    value = document(text=secret)
    value['run']['task'] = secret
    agent = value['agents'][0]
    agent.update(name=secret, role=secret, assignment=secret)
    agent['logs'][0]['thinking'] = secret
    value['board'] = [{'seq': 1, 'run_id': RUN, 'author_kind': 'human', 'author_id': None,
        'author_name': secret, 'body': secret, 'reply_to': None, 'created_at': 12.0}]
    value['run']['work_board'].update(post_count=1, last_seq=1)
    store.save(value, lambda text: text)
    mask = SecretRedactor(); mask.remember([secret])
    store.scrub(mask.redact)
    restored, _ = store.read(RUN, mask.redact)
    validate(restored)
    assert restored['run']['id'] == RUN and restored['run']['agent_ids'] == [AGENT]
    assert restored['agents'][0]['id'] == AGENT and restored['agents'][0]['status'] == 'working'
    assert restored['board'][0]['author_kind'] == 'human'
    assert restored['run']['task'] == '[redacted]'
    for field in ('name', 'role', 'assignment'):
        assert restored['agents'][0][field] == '[redacted]'
    assert restored['agents'][0]['logs'][0]['text'] == '[redacted]'
    assert restored['agents'][0]['logs'][0]['thinking'] == '[redacted]'
    assert restored['board'][0]['body'] == '[redacted]'
    assert restored['board'][0]['author_name'] == '[redacted]'
    # Internal generated IDs/enums are metadata; all response strings retain
    # the usual masking contract, without recursively expanding mask markers.
    shown = redact_tree(archived_view(restored, 1.0), mask.redact)
    assert shown['agents'][0]['logs'][0]['text'] == '[redacted]'


@pytest.mark.parametrize('field,value', [('message_type', []), ('delivery_state', {}), ('mail_id', []),
    ('mail_id', 'credential-as-mail-id'), ('from_agent_id', 'credential-as-peer'),
    ('to_agent_id', 'credential-as-peer'), ('from_agent_id', [])])
def test_corrupt_optional_event_metadata_rejected_before_mask_preservation(store, field, value):
    doc = document()
    doc['events'] = [{'id': 2, 'run_id': RUN, 'agent_id': AGENT, 'kind': 'created',
                      'text': 'public text', 'at': 12.0, field: value}]
    with pytest.raises(HistoryError):
        store.save(doc, lambda text: text.replace('credential', '[redacted]'))
    assert not store.summaries()


def test_scrub_aggregate_expansion_rolls_back_without_eviction(store, monkeypatch):
    import workbench.history as history
    original = document(text='z' * 10000)
    store.save(original, lambda text: text)
    original_bytes = len(history.encode(original).encode('utf-8'))
    # A small synthetic quota above both current payload and physical DB size;
    # this isolates post-mask aggregate expansion from path/file-size guards.
    limit = max(original_bytes + 1, store.path.stat().st_size)
    monkeypatch.setattr(history, 'MAX_TOTAL_BYTES', limit)
    masks = SecretRedactor(); masks.remember(['z'])
    assert len(history.encode(history.redact_document(original, masks.redact)).encode('utf-8')) > limit
    with pytest.raises(HistoryError, match='マスク後'):
        store.scrub(masks.redact)
    assert store.read(RUN)[0] == original
    assert store.error and store.status()['status'] == 'error'
    assert not Path(str(store.path) + '-journal').exists()
