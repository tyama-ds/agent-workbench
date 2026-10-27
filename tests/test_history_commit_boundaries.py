"""Synchronous mail persistence boundaries; real temporary SQLite, no provider."""
import asyncio
from contextlib import closing
import json
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from workbench.config import DEFAULT
from workbench.history import HistoryError, HistoryStore, MAX_TOTAL_BYTES
from test_engine import configured, ScriptClient, start


@pytest.fixture(autouse=True)
def no_operator_credentials(monkeypatch):
    for profile in [*DEFAULT['providers'], DEFAULT['search']]:
        if profile['api_key_env']:
            monkeypatch.delenv(profile['api_key_env'], raising=False)


@pytest.fixture
async def team(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    engine.settings.value['limits']['max_auto_collaborations'] = 100
    run, pm = await start(engine)
    worker = engine._new_agent(run, 'local', 'researcher', pm.id, assignment='Synthetic evidence')
    pm.pending.clear()
    try:
        yield engine, run, worker, pm
    finally:
        await engine.close()


def saved(engine, run):
    with closing(sqlite3.connect(engine.history.path)) as connection:
        row = connection.execute('SELECT payload,saved_at FROM archives WHERE run_id=?', (run['id'],)).fetchone()
    return json.loads(row[0]), row[1]


async def test_each_synchronous_mail_has_one_commit_and_is_durable_before_return(team, monkeypatch):
    engine, run, worker, pm = team
    original, calls = engine.history.save, []
    def save(document, redact):
        calls.append(document)
        return original(document, redact)
    monkeypatch.setattr(engine.history, 'save', save)
    for index in range(30):
        result = engine._mail(worker, pm, f'Peer message {index}')
        document, _ = saved(engine, run)
        mail = [row for row in document['events'] if row['kind'] == 'mail']
        assert len(calls) == len(mail) == index + 1
        assert mail[-1]['mail_id'] == result['mail_id']
        assert mail[-1]['text'] == f'Peer message {index}'
        assert document['run']['auto_collaborations'] == index + 1
        assert not engine._history_scopes and not engine._history_dirty
    assert len(pm.pending) == 30 and not engine.client.calls


@pytest.mark.parametrize('exception', [RuntimeError, asyncio.CancelledError])
async def test_mail_flushes_recorded_delivery_before_exception_or_cancellation_escapes(team, monkeypatch, exception):
    engine, run, worker, pm = team
    original = engine._mail_event
    def record_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise exception('synthetic after-record failure')
    with monkeypatch.context() as patch:
        patch.setattr(engine, '_mail_event', record_then_fail)
        with pytest.raises(exception):
            engine._mail(worker, pm, 'Accepted before failure')
    document, _ = saved(engine, run)
    assert [row['text'] for row in document['events'] if row['kind'] == 'mail'] == ['Accepted before failure']
    assert document['run']['auto_collaborations'] == 1 and len(pm.pending) == 1
    assert not engine._history_scopes and not engine._history_dirty
    engine.log(pm, 'notice', 'Direct hook still durable')
    assert any(row['text'] == 'Direct hook still durable' for agent in saved(engine, run)[0]['agents'] for row in agent['logs'])


@pytest.mark.parametrize('exception', [HistoryError, RuntimeError])
async def test_mail_save_failure_keeps_actual_acceptance_and_visible_error_without_replaying(team, monkeypatch, exception):
    engine, run, worker, pm = team
    before, before_at = saved(engine, run)
    def fail():
        raise exception('synthetic persistence failure')
    with monkeypatch.context() as patch:
        patch.setattr(engine.history, '_write_connection', fail)
        receipt = engine._mail(worker, pm, 'Accepted once')
    assert receipt['ok'] and receipt['queued'] and receipt['warning']
    assert engine.history.error and saved(engine, run) == (before, before_at)
    assert len(pm.pending) == 1 and run['auto_collaborations'] == 1
    assert not engine._history_scopes and not engine._history_dirty
    engine.log(pm, 'notice', 'Recovery persists accepted state')
    document, after_at = saved(engine, run)
    assert not engine.history.error and after_at >= before_at
    assert [row['text'] for row in document['events'] if row['kind'] == 'mail'] == ['Accepted once']
    assert len(pm.pending) == 1


async def test_mail_final_flush_uses_new_masks_after_synchronous_rotation(team, monkeypatch):
    engine, run, worker, pm = team
    secret = 'synthetic-new-known-secret-commit-boundary'
    original = engine._mail_event
    def record_and_rotate(*args, **kwargs):
        result = original(*args, **kwargs)
        engine.set_secret('local', secret)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(engine, '_mail_event', record_and_rotate)
        engine._mail(worker, pm, 'Visible ' + secret)
    document, _ = saved(engine, run)
    encoded = json.dumps(document)
    assert secret not in encoded and '[redacted]' in encoded
    assert secret.encode() not in engine.history.path.read_bytes()
    assert not engine._history_scopes and not engine._history_dirty


async def test_direct_enqueue_log_result_receipt_and_event_remain_durable_on_return(team):
    engine, run, worker, pm = team
    engine.enqueue(pm, 'Human accepted', human=True)
    assert any(row['text'] == 'Human accepted' for a in saved(engine, run)[0]['agents'] for row in a['logs'])
    engine.log(worker, 'assistant', 'Direct displayed text', thinking='Public displayed thinking')
    assert any(row['thinking'] == 'Public displayed thinking' for a in saved(engine, run)[0]['agents'] for row in a['logs'] if row['text'] == 'Direct displayed text')
    engine.record_result(worker, 'finish_work', 'Direct report')
    assert any(row['text'] == 'Direct report' for a in saved(engine, run)[0]['agents'] for row in a['results'])
    engine.record_receipt(worker, 'write_text', {'path': 'result.txt', 'bytes': 4, 'sha256': 'f' * 64, 'operation': 'create'})
    assert any(row['path'] == 'result.txt' for a in saved(engine, run)[0]['agents'] for row in a['output_receipts'])
    engine.event(run['id'], worker.id, 'notice', 'Direct event')
    assert any(row['text'] == 'Direct event' for row in saved(engine, run)[0]['events'])


@pytest.mark.parametrize('kind', ['file', 'missing', 'symlink', 'reparse', 'directory', 'hardlink', 'oversize', 'denied'])
def test_path_guard_uses_one_nofollow_observation_and_preserves_rejections(kind):
    calls = []
    class PathProbe:
        def lstat(self):
            calls.append('lstat')
            if kind == 'missing': raise FileNotFoundError()
            if kind == 'denied': raise PermissionError()
            return SimpleNamespace(st_mode=stat.S_IFLNK if kind == 'symlink' else stat.S_IFDIR if kind == 'directory' else stat.S_IFREG,
                st_nlink=2 if kind == 'hardlink' else 1, st_size=MAX_TOTAL_BYTES * 2 + 1 if kind == 'oversize' else 10,
                st_file_attributes=0x400 if kind == 'reparse' else 0)
    if kind in {'file', 'missing'}:
        HistoryStore._safe(PathProbe(), file=True)
    else:
        with pytest.raises(PermissionError if kind == 'denied' else HistoryError):
            HistoryStore._safe(PathProbe(), file=True)
    assert calls == ['lstat']
