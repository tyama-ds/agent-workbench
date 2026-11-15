"""Application-refereed turn-taking work (phase 8).

One game: a fixed order of participants, a number of rounds, and a rule that
validates each move. The application grants every turn and records every
accepted move, pass and rejected attempt; no model writes another
participant's move or the history. This module is pure state: the engine owns
agents, delivery and files.

``shiritori``: one word per move, written in hiragana or katakana. The word
must start with the last kana of the previous accepted word, must not end in
ん and must not repeat. A long mark (ー) is skipped and a small kana counts as
its large form when finding the last kana.
``free``: one free-text contribution per move (round-robin discussion).
"""
from __future__ import annotations

import csv
import io
import time
import unicodedata

RULES = ('shiritori', 'free')
RULE_LABELS = {'shiritori': 'しりとり', 'free': '順番に1つずつ発言'}
MAX_PARTICIPANTS = 16
MAX_TOTAL_TURNS = 200
MAX_STRIKES = 4  # three ordinary attempts and one last, explicitly prompted attempt
RESTART_AFTER_PASSES = 2
MAX_WORD = 24
MAX_FREE = 2000
MAX_NOTE = 200
_SMALL = dict(zip('ぁぃぅぇぉゃゅょっゎゕゖ', 'あいうえおやゆよつわかけ'))
_QUOTES = '「」『』"\'“”‘’（）()[]【】。、.,!！?？ 　\t\r\n'


def to_reading(raw: str) -> str:
    """Trim quotes and spaces, fold width, and turn katakana into hiragana."""
    text = unicodedata.normalize('NFKC', raw).strip(_QUOTES)
    return ''.join(chr(ord(char) - 0x60) if 'ァ' <= char <= 'ヶ' else char for char in text)


def tail_kana(reading: str) -> str:
    core = reading.rstrip('ー')
    return _SMALL.get(core[-1], core[-1]) if core else ''


def head_kana(reading: str) -> str:
    return _SMALL.get(reading[0], reading[0]) if reading else ''


class TurnRejected(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def check_word(reading: str) -> None:
    if not 2 <= len(reading) <= MAX_WORD:
        raise TurnRejected('length', f'2〜{MAX_WORD}文字の1語にしてください')
    if reading[0] == 'ー' or any(not ('ぁ' <= char <= 'ゖ' or char == 'ー') for char in reading):
        raise TurnRejected('characters', 'ひらがな（またはカタカナ）の1語だけにしてください。漢字・空白・記号・説明文は使えません')
    if not tail_kana(reading):
        raise TurnRejected('characters', 'ひらがな（またはカタカナ）の1語だけにしてください')
    if tail_kana(reading) == 'ん':
        raise TurnRejected('n_ending', '「ん」で終わる語は使えません。別の語にしてください')


class TurnGame:
    def __init__(self, *, rule, participants, rounds, topic='', first_word='', pm_id=''):
        if rule not in RULES:
            raise ValueError('rule は shiritori か free です')
        if not 2 <= len(participants) <= MAX_PARTICIPANTS:
            raise ValueError(f'参加者は2〜{MAX_PARTICIPANTS}人です')
        if type(rounds) is not int or rounds < 1 or len(participants) * rounds > MAX_TOTAL_TURNS:
            raise ValueError(f'手番の合計（参加者×周）は1〜{MAX_TOTAL_TURNS}です')
        self.rule, self.rounds, self.topic, self.pm_id = rule, rounds, topic, pm_id
        self.participants = [dict(row) for row in participants]  # key, agent_id, name
        self.total = len(participants) * rounds
        self.history = []   # accepted moves and passes, in turn order
        self.rejected = []  # attempts the application sent back
        self.strikes = 0
        self.failures = {}  # agent_id -> times this participant failed outright
        self.banned = set()  # readings refused for ending in ん: never valid, shown to every participant
        self.seed = None
        self.started_at, self.finished_at = time.time(), None
        self.ended_early = False
        self.saved_path = ''
        if first_word:
            reading = to_reading(first_word)
            if rule == 'shiritori':
                check_word(reading)
            self.seed = {'word': first_word.strip(), 'reading': reading}

    # --- state -------------------------------------------------------------
    @property
    def finished(self):
        return self.finished_at is not None

    def current(self):
        if self.finished or len(self.history) >= self.total:
            return None
        index = len(self.history)
        return {'turn': index + 1, 'round': index // len(self.participants) + 1,
                **self.participants[index % len(self.participants)]}

    def accepted(self):
        return [row for row in self.history if row['status'] == 'ok']

    def previous(self):
        rows = self.accepted()
        return rows[-1] if rows else self.seed

    def used(self):
        return {row['reading'] for row in self.accepted()} | ({self.seed['reading']} if self.seed else set())

    def restarting(self):
        """Two participants in a row could not continue: the next one starts a new chain."""
        return len(self.history) >= RESTART_AFTER_PASSES and all(
            row['status'] == 'pass' for row in self.history[-RESTART_AFTER_PASSES:])

    def expected_head(self):
        previous = self.previous()
        if not previous or self.rule != 'shiritori' or self.restarting():
            return ''
        return tail_kana(previous['reading'])

    def tried_this_turn(self):
        current = self.current()
        return [row['word'] for row in self.rejected if current and row['turn'] == current['turn']]

    def unusable(self):
        """Words a participant must not offer now, most relevant first."""
        head = self.expected_head()
        used, banned = sorted(self.used()), sorted(self.banned)
        return {'head': head,
                'used_with_head': [word for word in used if head and head_kana(word) == head],
                'banned_with_head': [word for word in banned if head and head_kana(word) == head],
                'used_other': [word for word in used if not head or head_kana(word) != head],
                'banned_other': [word for word in banned if not head or head_kana(word) != head]}

    # --- moves -------------------------------------------------------------
    def _record(self, status, **fields):
        current = self.current()
        self.history.append({'turn': current['turn'], 'round': current['round'], 'key': current['key'],
                             'agent_id': current['agent_id'], 'name': current['name'], 'status': status,
                             'word': '', 'reading': '', 'note': '', 'at': time.time(), **fields})
        self.strikes = 0
        count = len(self.participants)
        if len(self.history) >= count and all(row['status'] == 'pass' for row in self.history[-count:]):
            self.ended_early = True  # A whole round of passes: nobody can continue.
        if len(self.history) >= self.total or self.ended_early:
            self.finished_at = time.time()
        return self.history[-1]

    def pass_current(self, reason):
        if self.current() is None:
            return None
        return self._record('pass', note=str(reason)[:MAX_NOTE])

    def submit(self, agent_id, raw, note=''):
        """Returns {'outcome': accepted|rejected|passed|not_your_turn|finished, ...}."""
        current = self.current()
        if current is None:
            return {'outcome': 'finished'}
        if agent_id != current['agent_id']:
            return {'outcome': 'not_your_turn', 'current': current['name']}
        raw = raw if isinstance(raw, str) else ''
        try:
            if self.rule == 'shiritori':
                reading = to_reading(raw)
                check_word(reading)
                head = self.expected_head()
                if head and head_kana(reading) != head:
                    raise TurnRejected('chain', f'「{head}」で始まる語にしてください（前の語は「{self.previous()["reading"]}」）')
                if reading in self.used():
                    raise TurnRejected('duplicate', f'「{reading}」は既に使われています。別の語にしてください')
                word = unicodedata.normalize('NFKC', raw).strip(_QUOTES)
            else:
                word = reading = raw.strip()
                if not 1 <= len(word) <= MAX_FREE:
                    raise TurnRejected('length', f'1〜{MAX_FREE}文字で発言してください')
        except TurnRejected as exc:
            self.strikes += 1
            if exc.code == 'n_ending':
                self.banned.add(to_reading(raw))
            self.rejected.append({'turn': current['turn'], 'key': current['key'], 'name': current['name'],
                                  'word': raw.strip()[:80], 'code': exc.code, 'message': str(exc), 'at': time.time()})
            if self.strikes >= MAX_STRIKES:
                entry = self._record('pass', note=f'{MAX_STRIKES}回続けて無効（最後の理由: {exc}）'[:MAX_NOTE])
                return {'outcome': 'passed', 'code': exc.code, 'message': str(exc), 'entry': entry}
            return {'outcome': 'rejected', 'code': exc.code, 'message': str(exc), 'attempts_left': MAX_STRIKES - self.strikes}
        restart = self.rule == 'shiritori' and self.restarting()
        entry = self._record('ok', word=word, reading=reading, restart=restart,
                             note=('（直前の2人がパスしたため、新しい語から再開）' if restart else '') + str(note or '').strip()[:MAX_NOTE])
        return {'outcome': 'accepted', 'entry': entry}

    # --- projections -------------------------------------------------------
    def public(self):
        current = self.current()
        return {'rule': self.rule, 'rounds': self.rounds, 'topic': self.topic[:200],
                'participants': [row['name'] for row in self.participants], 'total': self.total,
                'done': len(self.history), 'accepted': len(self.accepted()),
                'passes': sum(row['status'] == 'pass' for row in self.history), 'rejected': len(self.rejected),
                'status': 'complete' if self.finished else 'running', 'ended_early': self.ended_early,
                'current': current['name'] if current else '', 'saved_path': self.saved_path,
                'first_word': self.seed['word'] if self.seed else '',
                'history': [{'turn': row['turn'], 'name': row['name'], 'status': row['status'],
                             'word': row['word'][:MAX_WORD if self.rule == 'shiritori' else 200]} for row in self.history]}

    def summary_lines(self):
        lines = []
        if self.seed:
            lines.append(f'0. （最初の語）: {self.seed["word"]}')
        for row in self.history:
            lines.append(f'{row["turn"]}. {row["name"]}: ' + (row['word'] if row['status'] == 'ok' else f'パス（{row["note"]}）'))
        return lines

    def counts_text(self):
        passes = sum(row['status'] == 'pass' for row in self.history)
        return (f'受理 {len(self.accepted())} 手、パス {passes} 手、差し戻し {len(self.rejected)} 回'
                + ('（全員がパスしたため途中で終了）' if self.ended_early else ''))

    def rows(self):
        header = ['手番', '周', '参加者', '語', 'よみ', '判定', '補足']
        body = [[0, 0, '（最初の語）', self.seed['word'], self.seed['reading'], '開始', '']] if self.seed else []
        body += [[row['turn'], row['round'], row['name'], row['word'], row['reading'],
                  ('受理（再開）' if row.get('restart') else '受理') if row['status'] == 'ok' else 'パス', row['note']]
                 for row in self.history]
        return header, body

    def rejected_rows(self):
        return ['手番', '参加者', '出した語', '理由'], [[row['turn'], row['name'], row['word'], row['message']] for row in self.rejected]

    def export_bytes(self, extension):
        header, body = self.rows()
        if extension == '.xlsx':
            import openpyxl
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = '手番の履歴'
            for line in [header, *body]:
                sheet.append(line)
            rejected_header, rejected_body = self.rejected_rows()
            if rejected_body:
                other = workbook.create_sheet('差し戻し')
                for line in [rejected_header, *rejected_body]:
                    other.append(line)
            output = io.BytesIO()
            workbook.save(output)
            return output.getvalue()
        if extension == '.csv':
            output = io.StringIO(newline='')
            csv.writer(output).writerows([header, *body])
            return ('﻿' + output.getvalue()).encode('utf-8')
        if extension == '.md':
            lines = ['| ' + ' | '.join(header) + ' |', '|' + ' --- |' * len(header)]
            lines += ['| ' + ' | '.join(str(cell).replace('|', '／').replace('\n', ' ') for cell in line) + ' |' for line in body]
            return ('\n'.join(lines) + '\n').encode('utf-8')
        return ('\n'.join(self.summary_lines()) + '\n').encode('utf-8')
