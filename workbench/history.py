"""Versioned local archives of public display data, never executable engine state."""
from __future__ import annotations

import copy
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time

from .coordination_view import validate_coordination, restore_coordination_metadata

SCHEMA_VERSION = 1
APPLICATION_ID = 0x41574248
MAX_RUNS = 500
MAX_RUN_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ITEMS = 50000
RUN_FIELDS = frozenset(('id', 'task', 'pm_profile', 'pm_profiles', 'pm_agent_ids', 'worker_profiles',
    'delegation_level', 'workers_per_pm', 'max_workers', 'status', 'created_at', 'model_calls', 'tool_calls',
    'auto_collaborations', 'work_board', 'max_auto_collaborations', 'collaboration_limit_reached', 'agent_ids',
    'budget', 'stop_reason', 'stop_reasons', 'ordered_reference', 'coordination', 'skills'))
AGENT_FIELDS = frozenset(('id', 'run_id', 'name', 'role', 'profile_id', 'parent_id', 'status', 'question',
    'last_error', 'turns', 'assignment', 'configured_profile', 'logs', 'results', 'output_receipts',
    'results_omitted', 'receipts_omitted', 'result_revision', 'stop_reason', 'coordination', 'worker_dependencies', 'question_state'))
LOG_FIELDS = frozenset(('id', 'kind', 'text', 'thinking', 'at'))
RESULT_FIELDS = frozenset(('id', 'source', 'text', 'truncated', 'at', 'turn', 'revision'))
RECEIPT_FIELDS = frozenset(('id', 'tool', 'at', 'turn', 'path', 'bytes', 'sha256', 'operation'))
EVENT_FIELDS = frozenset(('id', 'run_id', 'agent_id', 'kind', 'text', 'at', 'mail_id', 'from_agent_id',
    'to_agent_id', 'from', 'to', 'subject', 'message_type', 'delivery_state'))
POST_FIELDS = frozenset(('seq', 'run_id', 'author_kind', 'author_id', 'author_name', 'body', 'reply_to', 'created_at'))
TERMINAL = frozenset(('done', 'stopped', 'error', 'interrupted'))
STOP_REASONS = frozenset(('time_limit', 'model_limit', 'tool_limit', 'turn_limit', 'provider_timeout'))


class HistoryError(ValueError):
    code = 'history_storage_error'


class ArchivedReadOnly(ValueError):
    code = 'archive_read_only'

    def __init__(self):
        super().__init__('保存された履歴は閲覧専用です。続ける場合は依頼文から新しい作業を開始してください。')


def pick(value, fields):
    return {key: copy.deepcopy(value[key]) for key in fields if key in value}


def redact_tree(value, redact):
    if isinstance(value, str):
        # Previously inserted masks are inert; short rotated keys must not expand them.
        masked = redact(value)
        expanded_marker = redact('[redacted]')
        return masked.replace(expanded_marker, '[redacted]') if expanded_marker != '[redacted]' else masked
    if isinstance(value, list):
        return [redact_tree(item, redact) for item in value]
    if isinstance(value, dict):
        return {key: redact_tree(item, redact) for key, item in value.items()}
    return value


def redact_document(document, redact):
    """Mask display content while preserving validated app-owned linkage.

    Opaque random IDs and fixed protocol enums are metadata, like JSON field
    names, not credential-bearing user/model prose. They must remain stable for
    schema/relationship checks, including when a configured key is one letter.
    Names, roles, labels, models, tasks, paths, bodies and thinking are always
    masked. Public projection applies its normal masking again before response.
    """
    validate(document)
    result = redact_tree(document, redact)
    def restore(before, after, keys):
        for key in keys:
            if key in before:
                after[key] = copy.deepcopy(before[key])
    def enum(before, after, key, allowed):
        if isinstance(before.get(key), str) and before[key] in allowed:
            after[key] = before[key]
    statuses = {'idle', 'queued', 'working', 'running', 'waiting', 'stopping', 'stopped', 'done', 'error', 'interrupted'}
    restore(document['run'], result['run'], ('id', 'agent_ids', 'pm_agent_ids'))
    enum(document['run'], result['run'], 'status', statuses)
    # Validated diagnostics are fixed application metadata, never credential text.
    restore(document['run'], result['run'], ('budget', 'stop_reason', 'stop_reasons'))
    restore_coordination_metadata(document['run'].get('coordination'), result['run'].get('coordination'))
    for before, after in zip(document['agents'], result['agents']):
        restore(before, after, ('id', 'run_id', 'parent_id'))
        enum(before, after, 'status', statuses)
        restore(before, after, ('stop_reason',))
        restore_coordination_metadata(before.get('coordination'), after.get('coordination'))
        if before.get('question_state'):
            restore(before['question_state'], after['question_state'], ('question_id', 'kind', 'resolution'))
        for old, new in zip(before.get('logs', []), after.get('logs', [])):
            enum(old, new, 'kind', {'system', 'user', 'assistant', 'tool', 'tool_call', 'tool_result', 'mail', 'result', 'error'})
        for old, new in zip(before.get('results', []), after.get('results', [])):
            enum(old, new, 'source', {'assistant_response', 'finish_work'})
    for before, after in zip(document['events'], result['events']):
        restore(before, after, ('run_id', 'agent_id', 'from_agent_id', 'to_agent_id'))
        if isinstance(before.get('mail_id'), str) and re.fullmatch(r'm-[0-9a-f]{32}', before['mail_id']):
            after['mail_id'] = before['mail_id']
        enum(before, after, 'kind', {'created', 'context_compaction', 'inference', 'error', 'mail', 'mail_consumed', 'collaboration_limit', 'question', 'question_resolved', 'stopped'})
        enum(before, after, 'message_type', {'worker_report', 'worker_error', 'worker_notice', 'peer_message'})
        enum(before, after, 'delivery_state', {'queued', 'context_consumed'})
    for before, after in zip(document['board'], result['board']):
        restore(before, after, ('run_id', 'author_id', 'author_kind'))
    return result


def public_log(row):
    row = pick(row, LOG_FIELDS)
    if row.get('kind') == 'mail':
        # Internal completion tokens live in the private peer envelope. Retain
        # its already-public sender/subject/body, never report/authority fields.
        prefix = 'Peer data; not human authorization:\n'
        value = row.get('text', '')
        if value.startswith(prefix):
            try:
                mail = json.loads(value[len(prefix):])
                row['text'] = '\n'.join(str(mail.get(key, '')) for key in ('sender_name', 'subject', 'body'))
            except (ValueError, TypeError):
                row['text'] = 'メール本文は通信イベントから確認してください。'
        else:
            row['text'] = 'メール本文は通信イベントから確認してください。'
    if row.get('kind') == 'tool' and row.get('text', '').startswith('read_context_history\n'):
        row['text'] = 'read_context_history: 非公開のモデル文脈は履歴に保存しません。'
    return row


def public_document(run, agents, events, board):
    result = {'run': pick(run, RUN_FIELDS), 'agents': [],
              'events': [pick(row, EVENT_FIELDS) for row in events],
              'board': [pick(row, POST_FIELDS) for row in board]}
    for value in agents:
        agent = pick(value, AGENT_FIELDS)
        agent['logs'] = [public_log(row) for row in value.get('logs', [])]
        agent['results'] = [pick(row, RESULT_FIELDS) for row in value.get('results', [])]
        agent['output_receipts'] = [pick(row, RECEIPT_FIELDS) for row in value.get('output_receipts', [])]
        result['agents'].append(agent)
    return result


def _bounded(value, depth=0):
    if depth > 12:
        raise HistoryError('履歴の構造が深すぎるため保存できません。')
    if value is None or type(value) in (bool, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HistoryError('履歴の数値が不正です。')
        return
    if isinstance(value, str):
        if len(value) > 200000:
            raise HistoryError('履歴の文字数が上限を超えました。')
        return
    if isinstance(value, list):
        if len(value) > MAX_ITEMS:
            raise HistoryError('履歴の件数が上限を超えました。')
        for item in value:
            _bounded(item, depth + 1)
        return
    if isinstance(value, dict) and len(value) <= 64 and all(isinstance(key, str) for key in value):
        for item in value.values():
            _bounded(item, depth + 1)
        return
    raise HistoryError('履歴のデータ形式が不正です。')


def _rows(rows, fields, identity='id'):
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        raise HistoryError('履歴の一覧が不正です。')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not set(row) <= fields or identity not in row:
            raise HistoryError('履歴に未対応の項目があります。')
        ident = row[identity]
        if type(ident) not in (int, str) or ident in seen:
            raise HistoryError('履歴の識別子が重複または不正です。')
        seen.add(ident)


def _text_fields(row, names):
    if any(not isinstance(row.get(key), str) for key in names):
        raise HistoryError('履歴の文字項目が不正です。')


def _time(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _number(value):
    return type(value) is int and value >= 0


def _question_state(value):
    """Display-only question receipt; never restores a timer or authorization."""
    fields = {'question_id', 'kind', 'recommendation', 'asked_at', 'deadline_at',
              'resolution', 'resolved_at', 'reason'}
    if (not isinstance(value, dict) or set(value) != fields or
            not isinstance(value['question_id'], str) or
            re.fullmatch(r'q-[0-9a-f]{32}', value['question_id']) is None or
            value['kind'] not in ('consultation', 'permission') or
            value['resolution'] not in ('pending', 'answered', 'fallback', 'blocked', 'cancelled') or
            not isinstance(value['recommendation'], str) or not isinstance(value['reason'], str) or
            not _time(value['asked_at']) or
            any(value[key] is not None and not _time(value[key]) for key in ('deadline_at', 'resolved_at')) or
            (value['kind'] == 'permission' and value['deadline_at'] is not None) or
            (value['resolution'] == 'fallback' and
             (value['kind'] != 'consultation' or not value['recommendation'] or value['deadline_at'] is None))):
        raise HistoryError('履歴の質問通知・回答状態が不正です。')


def _budget(value):
    if (not isinstance(value, dict) or set(value) != {'observed_at', 'started_at', 'shared', 'model_calls', 'tool_calls', 'time'}
            or value['shared'] is not True or not all(_time(value[key]) and value[key] <= 253402300799
                for key in ('observed_at', 'started_at')) or value['observed_at'] < value['started_at']):
        raise HistoryError('履歴の共有予算の観測情報が不正です。')
    for key, maximum in (('model_calls', 1000), ('tool_calls', 5000)):
        row = value[key]
        if (not isinstance(row, dict) or set(row) != {'used', 'limit', 'remaining'} or
                not all(_number(n) and n <= 2147483647 for n in row.values()) or
                not 1 <= row['limit'] <= maximum or row['remaining'] != max(0, row['limit'] - row['used'])):
            raise HistoryError('履歴の共有予算の回数が不正です。')
    row = value['time']
    if (not isinstance(row, dict) or set(row) != {'used_seconds', 'limit_seconds', 'remaining_seconds'} or
            not all(_time(n) and n <= 253402300799 for n in row.values()) or
            not 10 <= row['limit_seconds'] <= 86400 or
            not math.isclose(row['used_seconds'], value['observed_at'] - value['started_at'], abs_tol=1e-6) or
            not math.isclose(row['remaining_seconds'], max(0, row['limit_seconds'] - row['used_seconds']), abs_tol=1e-6)):
        raise HistoryError('履歴の共有予算の時間が不正です。')


def validate(document):
    if not isinstance(document, dict) or set(document) != {'run', 'agents', 'events', 'board'}:
        raise HistoryError('履歴の構造が不正です。')
    _bounded(document)
    run = document['run']
    if not isinstance(run, dict) or not set(run) <= RUN_FIELDS:
        raise HistoryError('履歴の作業情報が不正です。')
    _text_fields(run, ('id', 'task', 'status'))
    if re.fullmatch(r'r-[0-9a-f]{16}', run['id']) is None or not _time(run.get('created_at')):
        raise HistoryError('履歴の作業識別子・時刻が不正です。')
    if 'budget' in run:
        _budget(run['budget'])
        if (run['budget']['started_at'] != run['created_at'] or
                any(not _number(run.get(key)) or run['budget'][key]['used'] != run[key]
                    for key in ('model_calls', 'tool_calls'))):
            raise HistoryError('履歴の共有予算の開始時刻・回数が作業と一致しません。')
    if 'stop_reasons' in run:
        reasons = run['stop_reasons']
        if (not isinstance(reasons, list) or any(not isinstance(reason, str) or reason not in STOP_REASONS for reason in reasons)
                or len(set(reasons)) != len(reasons) or
                run.get('stop_reason') != (reasons[0] if len(reasons) == 1 else 'multiple' if reasons else '')):
            raise HistoryError('履歴の停止理由が不正です。')
    elif 'stop_reason' in run:
        raise HistoryError('履歴の停止理由一覧がありません。')
    board_meta = run.get('work_board')
    if (not isinstance(board_meta, dict) or set(board_meta) != {'enabled', 'post_count', 'last_seq'} or
            type(board_meta['enabled']) is not bool or not _number(board_meta['post_count']) or not _number(board_meta['last_seq'])):
        raise HistoryError('履歴の掲示板情報が不正です。')
    _rows(document['agents'], AGENT_FIELDS)
    if len(document['agents']) > 64:
        raise HistoryError('履歴の担当者数が上限を超えました。')
    ids = {agent['id'] for agent in document['agents']}
    if (not isinstance(run.get('agent_ids'), list) or len(run['agent_ids']) != len(ids) or set(run['agent_ids']) != ids or
            not isinstance(run.get('pm_agent_ids'), list) or len(set(run['pm_agent_ids'])) != len(run['pm_agent_ids']) or
            not set(run['pm_agent_ids']) <= ids):
        raise HistoryError('履歴の担当者一覧が作業と一致しません。')
    try:
        coordination = run.get('coordination')
        validate_coordination(coordination)
        if coordination is not None:
            peer_ids = {row['agent_id'] for row in coordination['reports']}
            if not peer_ids <= ids or coordination['current_actor_id'] not in peer_ids | {None}:
                raise ValueError('Coordination references another run')
        for member in document['agents']:
            item = member.get('coordination')
            validate_coordination(item, agent=True)
            if item is not None and (coordination is None or item['workflow_id'] != coordination['workflow_id']
                    or item['dependency']['actor_id'] not in ids | {None}
                    or (item['report'] is not None and item['report']['agent_id'] != member['id'])):
                raise ValueError('Coordination agent identity mismatch')
    except ValueError as exc:
        raise HistoryError('履歴の連携観測情報が不正です。') from exc
    for agent in document['agents']:
        if 'question_state' in agent:
            _question_state(agent['question_state'])
        if 'stop_reason' in agent and (not isinstance(agent['stop_reason'], str) or agent['stop_reason'] not in STOP_REASONS | {''}):
            raise HistoryError('履歴の担当者の停止理由が不正です。')
        _text_fields(agent, ('id', 'run_id', 'name', 'role', 'profile_id', 'status', 'question', 'last_error', 'assignment'))
        if (agent['run_id'] != run['id'] or re.fullmatch(r'a-[0-9a-f]{16}', agent['id']) is None or
                agent.get('parent_id') not in ids | {None} or agent.get('parent_id') == agent['id'] or
                not _number(agent.get('turns'))):
            raise HistoryError('履歴の担当者が作業と一致しません。')
        if agent['id'] in run['pm_agent_ids'] and agent.get('parent_id') is not None:
            raise HistoryError('履歴のPM情報が不正です。')
        profile = agent.get('configured_profile')
        if profile is not None and (not isinstance(profile, dict) or not set(profile) <= {'id', 'label', 'kind', 'model'} or
                                    not all(isinstance(v, str) for v in profile.values())):
            raise HistoryError('履歴のモデル表示情報が不正です。')
        for key, fields in [('logs', LOG_FIELDS), ('results', RESULT_FIELDS), ('output_receipts', RECEIPT_FIELDS)]:
            _rows(agent.get(key, []), fields)
            for row in agent.get(key, []):
                if type(row['id']) is not int or row['id'] <= 0 or not _time(row.get('at')):
                    raise HistoryError('履歴の表示記録が不正です。')
                _text_fields(row, ('kind', 'text') if key == 'logs' else ('source', 'text') if key == 'results' else ('tool', 'path', 'sha256', 'operation'))
                if key == 'logs' and 'thinking' in row and not isinstance(row['thinking'], str):
                    raise HistoryError('履歴の表示内容が不正です。')
    _rows(document['events'], EVENT_FIELDS)
    for row in document['events']:
        _text_fields(row, ('kind', 'text', 'run_id', 'agent_id'))
        _text_fields(row, [key for key in ('mail_id', 'from_agent_id', 'to_agent_id', 'from', 'to', 'subject',
                                         'message_type', 'delivery_state') if key in row])
        if any(row[key] not in ids for key in ('from_agent_id', 'to_agent_id') if key in row):
            raise HistoryError('履歴の通信相手が作業と一致しません。')
        if 'mail_id' in row and re.fullmatch(r'm-[0-9a-f]{32}', row['mail_id']) is None:
            raise HistoryError('履歴のメール識別子が不正です。')
        if (row['run_id'] != run['id'] or row['agent_id'] not in ids | {''} or not _time(row.get('at')) or
                type(row['id']) is not int or row['id'] <= 0):
            raise HistoryError('履歴の通信が作業と一致しません。')
        if row['kind'] in {'mail', 'mail_consumed'} and any(row.get(key) not in ids for key in ('from_agent_id', 'to_agent_id')):
            raise HistoryError('履歴のメール宛先が作業と一致しません。')
    _rows(document['board'], POST_FIELDS, 'seq')
    if (len(document['board']) > 200 or [row['seq'] for row in document['board']] != list(range(1, len(document['board']) + 1)) or
            board_meta['last_seq'] != len(document['board']) or board_meta['post_count'] != len(document['board'])):
        raise HistoryError('履歴の掲示板投稿順が不正です。')
    for row in document['board']:
        _text_fields(row, ('run_id', 'author_kind', 'author_name', 'body'))
        reply = row.get('reply_to')
        if (row['run_id'] != run['id'] or row['author_kind'] not in {'human', 'agent'} or not _time(row.get('created_at')) or
                (row['author_kind'] == 'human' and row.get('author_id') is not None) or
                (row['author_kind'] == 'agent' and row.get('author_id') not in ids) or
                (reply is not None and (type(reply) is not int or not 1 <= reply < row['seq']))):
            raise HistoryError('履歴の掲示板投稿者・返信先が不正です。')
    return document


def encode(document):
    validate(document)
    value = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(value.encode('utf-8')) > MAX_RUN_BYTES:
        raise HistoryError('この作業の履歴が16 MiBに達しました。保存済み履歴は保持されています。')
    return value


def decode(value):
    if not isinstance(value, str) or len(value.encode('utf-8')) > MAX_RUN_BYTES:
        raise HistoryError('保存された履歴のサイズが不正です。')
    try:
        return validate(json.loads(value))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise HistoryError('保存された履歴を読み取れません。元ファイルは変更していません。') from exc


def _merge_rows(old, new, identity='id'):
    rows = {row[identity]: row for row in old}
    rows.update({row[identity]: row for row in new})
    return list(rows.values())


def merge(old, new):
    result = copy.deepcopy(new)
    result['events'] = _merge_rows(old['events'], new['events'])
    result['board'] = _merge_rows(old['board'], new['board'], 'seq')
    old_agents = {row['id']: row for row in old['agents']}
    for agent in result['agents']:
        prior = old_agents.pop(agent['id'], None)
        if prior:
            for key in ('logs', 'results', 'output_receipts'):
                agent[key] = _merge_rows(prior[key], agent[key])
    result['agents'].extend(old_agents.values())
    return result


def summary(document):
    result = copy.deepcopy(document)
    result['events'] = []
    result['board'] = []
    for agent in result['agents']:
        logs = agent.get('logs', [])
        agent['activity'] = {'latest_log': ({key: logs[-1][key] for key in ('kind', 'text', 'at')} if logs else None),
                             'pending_count': 0, 'result_count': len(agent.get('results', [])),
                             'output_receipt_count': len(agent.get('output_receipts', []))}
        for key in ('logs', 'results', 'output_receipts'):
            agent.pop(key, None)
    return result


class HistoryStore:
    """SQLite transactions isolate app instances; archives never create work."""

    def __init__(self, directory):
        self.directory = Path(directory).absolute() / 'history'
        self.path = self.directory / 'work-history.sqlite3'
        self.owner = secrets.token_hex(16)
        self.error = ''
        self.last_saved_at = None
        self._available = False
        self._readable = False
        self._lease = None
        self._agent_owners = {}
        try:
            self._acquire_lease()
            self._initialize()
            self._available = self._readable = True
        except (OSError, sqlite3.Error, HistoryError) as exc:
            self.error = str(exc) if isinstance(exc, HistoryError) else '履歴を開けません。保存先の権限・空き容量・形式を確認してください。既存ファイルは保持しています。'

    def _acquire_lease(self):
        self._paths_safe()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = self.directory / '.writer.lock'
        self._safe(lock, file=True)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        handle = os.fdopen(fd, 'r+b', buffering=0)
        try:
            self._safe(lock, file=True)
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'\0')
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lease = handle
        except (OSError, HistoryError):
            handle.close()
            raise HistoryError('同じ保存先を別のAgent Workbenchが使用中です。この画面からは履歴を読み書きできません。別のアプリを終了してから起動し直してください。')

    def close(self):
        if self._lease is not None:
            self._lease.close()
            self._lease = None
        self._available = False

    def require_writable(self):
        if not self._available or self._lease is None:
            raise HistoryError(self.error or '履歴の保存先を使用できません。')

    @staticmethod
    def _safe(path, *, file=False):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise HistoryError('履歴保存先のリンクは使用できません。')
        if file and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_TOTAL_BYTES * 2):
            raise HistoryError('履歴ファイルの種類が不正です。')

    def _paths_safe(self):
        for parent in (self.directory, *self.directory.parents):
            self._safe(parent)
        self._safe(self.path, file=True)
        for suffix in ('-journal', '-wal', '-shm'):
            self._safe(Path(str(self.path) + suffix), file=True)

    def _connect(self, *, readonly=False):
        self._paths_safe()
        mode = 'ro' if readonly else 'rw'
        connection = sqlite3.connect(self.path.as_uri() + '?mode=' + mode, uri=True, timeout=2, isolation_level=None)
        connection.execute('PRAGMA trusted_schema=OFF')
        return connection

    def _schema(self, connection):
        if (connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION or
                connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID):
            raise HistoryError('未対応の履歴バージョンです。対応するアプリで開いてください。')
        objects = connection.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if objects != [('table', 'archives')]:
            raise HistoryError('履歴ファイルの構造が不正です。')
        columns = connection.execute('PRAGMA table_info(archives)').fetchall()
        if [row[1:3] for row in columns] != [('run_id', 'TEXT'), ('owner', 'TEXT'), ('saved_at', 'REAL'), ('payload', 'TEXT')]:
            raise HistoryError('履歴ファイルの項目が不正です。')

    def _validate_existing_payloads(self, connection):
        count, total = connection.execute('SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM archives').fetchone()
        if count > MAX_RUNS or total > MAX_TOTAL_BYTES:
            raise HistoryError('履歴ファイルの保存上限を超えています。')
        seen_runs = set()
        seen_agents = {}
        for ident, owner, saved_at, payload in connection.execute('SELECT run_id,owner,saved_at,payload FROM archives'):
            document = decode(payload)
            if (document['run']['id'] != ident or not isinstance(owner, str) or
                    re.fullmatch(r'[0-9a-f]{32}', owner) is None or not _time(saved_at)):
                raise HistoryError('履歴ファイルの識別情報が不正です。')
            if ident in seen_runs or any(row['id'] in seen_agents for row in document['agents']):
                raise HistoryError('履歴の作業・担当者の識別子が重複しています。')
            seen_runs.add(ident)
            seen_agents.update({row['id']: ident for row in document['agents']})
        self._agent_owners = seen_agents

    def _initialize(self):
        self._paths_safe()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._paths_safe()
        created = False
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            created = True
        except FileExistsError:
            pass
        if not created:
            with self.path.open('rb') as source:
                if source.read(16) != b'SQLite format 3\x00':
                    raise HistoryError('既存の履歴ファイルはSQLite形式ではありません。')
            # Inspect before any write PRAGMA. Future/corrupt data remains intact.
            with closing(self._connect(readonly=True)) as connection:
                self._schema(connection)
                self._validate_existing_payloads(connection)
            return
        with closing(self._connect()) as connection:
            connection.execute('BEGIN EXCLUSIVE')
            connection.execute('CREATE TABLE archives (run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, saved_at REAL NOT NULL, payload TEXT NOT NULL)')
            connection.execute('PRAGMA application_id=' + str(APPLICATION_ID))
            connection.execute('PRAGMA user_version=' + str(SCHEMA_VERSION))
            connection.commit()

    def _write_connection(self):
        self.require_writable()
        connection = self._connect()
        try:
            self._schema(connection)
            connection.execute('PRAGMA journal_mode=DELETE')
            connection.execute('PRAGMA secure_delete=ON')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            return connection
        except BaseException:
            connection.close()
            raise

    def _failed(self, exc):
        self.error = str(exc) if isinstance(exc, HistoryError) else '履歴を保存・読取できません。保存先の権限・空き容量を確認してください。'
        raise HistoryError(self.error) from exc

    def summaries(self, redact=lambda value: value):
        if not self._readable:
            raise HistoryError(self.error)
        try:
            with closing(self._connect(readonly=True)) as connection:
                self._schema(connection)
                count, total = connection.execute('SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM archives').fetchone()
                if count > MAX_RUNS or total > MAX_TOTAL_BYTES:
                    raise HistoryError('履歴ファイルの保存上限を超えています。')
                result = {}
                for ident, saved_at, value in connection.execute('SELECT run_id,saved_at,payload FROM archives ORDER BY saved_at DESC'):
                    document = redact_document(decode(value), redact)
                    if document['run']['id'] != ident:
                        raise HistoryError('履歴の作業IDが一致しません。')
                    result[ident] = (summary(document), saved_at)
                return result
        except (OSError, sqlite3.Error, HistoryError) as exc:
            self._failed(exc)

    def read(self, ident, redact=lambda value: value):
        if not self._readable:
            raise HistoryError(self.error)
        try:
            with closing(self._connect(readonly=True)) as connection:
                self._schema(connection)
                row = connection.execute('SELECT saved_at,payload FROM archives WHERE run_id=?', (ident,)).fetchone()
                if row is None:
                    raise HistoryError('保存された履歴が見つかりません。')
                document = redact_document(decode(row[1]), redact)
                if document['run']['id'] != ident:
                    raise HistoryError('履歴の作業IDが一致しません。')
                return document, row[0]
        except (OSError, sqlite3.Error, HistoryError) as exc:
            self._failed(exc)

    def save(self, document, redact):
        connection = None
        try:
            document = redact_document(document, redact)
            validate(document)
            ident = document['run']['id']
            if any(self._agent_owners.get(row['id'], ident) != ident for row in document['agents']):
                raise HistoryError('履歴の担当者IDが別の作業と重複しています。')
            connection = self._write_connection()
            existing = connection.execute('SELECT owner,payload FROM archives WHERE run_id=?', (ident,)).fetchone()
            if existing:
                if existing[0] != self.owner:
                    raise HistoryError('同じ作業IDを別のアプリが保存しています。既存履歴は変更していません。')
                document = merge(redact_document(decode(existing[1]), redact), document)
            value = encode(document)
            count, total = connection.execute('SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM archives WHERE run_id<>?', (ident,)).fetchone()
            if count >= MAX_RUNS or total + len(value.encode('utf-8')) > MAX_TOTAL_BYTES:
                raise HistoryError('履歴保存の上限（500作業・256 MiB）に達しました。既存履歴は削除していません。')
            at = time.time()
            connection.execute('INSERT INTO archives VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET saved_at=excluded.saved_at,payload=excluded.payload', (ident, self.owner, at, value))
            connection.commit()
            self.last_saved_at = at
            self._agent_owners.update({row['id']: ident for row in document['agents']})
            self.error = ''
            return at
        except (OSError, sqlite3.Error, HistoryError) as exc:
            if connection:
                connection.rollback()
            self._failed(exc)
        finally:
            if connection:
                connection.close()

    def scrub(self, redact):
        """Rewrite all retained public fields under one writer transaction."""
        connection = None
        try:
            connection = self._write_connection()
            count, total = connection.execute('SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM archives').fetchone()
            if count > MAX_RUNS or total > MAX_TOTAL_BYTES:
                raise HistoryError('履歴ファイルの保存上限を超えています。')
            for ident, value in connection.execute('SELECT run_id,payload FROM archives').fetchall():
                changed = encode(redact_document(decode(value), redact))
                if changed != value:
                    connection.execute('UPDATE archives SET payload=? WHERE run_id=?', (changed, ident))
            rewritten_total = connection.execute('SELECT coalesce(sum(length(CAST(payload AS BLOB))),0) FROM archives').fetchone()[0]
            if rewritten_total > MAX_TOTAL_BYTES:
                raise HistoryError('秘密情報マスク後の履歴が保存上限を超えます。元の履歴は保持されています。')
            connection.commit()
            self.error = ''
        except (OSError, sqlite3.Error, HistoryError) as exc:
            if connection:
                connection.rollback()
            self._failed(exc)
        finally:
            if connection:
                connection.close()

    def status(self, archived_runs=0):
        return {'enabled': True, 'path': str(self.path), 'status': 'error' if self.error else 'ready',
                'error': self.error, 'archived_runs': archived_runs, 'last_saved_at': self.last_saved_at,
                'max_runs': MAX_RUNS, 'max_run_bytes': MAX_RUN_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES}


def archived_view(document, saved_at):
    """Display dictionaries only; no Engine/Agent reconstruction or callbacks."""
    value = copy.deepcopy(document)
    run = value['run']
    if run.get('coordination') is not None:
        run['coordination'].update(history_only=True, read_only=True)
    run.update(archived=True, read_only=True, original_status=run['status'], history_saved_at=saved_at,
               status_reason='保存された履歴（閲覧専用）')
    if run['status'] not in TERMINAL:
        run['status'] = 'interrupted'
    for agent in value['agents']:
        if agent.get('coordination') is not None:
            agent['coordination'].update(history_only=True, read_only=True)
        agent.update(archived=True, read_only=True, original_status=agent['status'],
                     status_reason='保存された履歴（閲覧専用）',
                     message_eligibility={'allowed': False, 'reason': 'archived_read_only',
                         'message': '保存された履歴は閲覧専用です。'})
        if agent['status'] not in TERMINAL:
            agent['status'] = 'interrupted'
        logs = agent.get('logs', [])
        agent['activity'] = agent.get('activity') or {'latest_log': ({key: logs[-1][key] for key in ('kind', 'text', 'at')} if logs else None),
                             'pending_count': 0, 'result_count': len(agent.get('results', [])),
                             'output_receipt_count': len(agent.get('output_receipts', []))}
    return value
