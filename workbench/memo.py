"""A team memo the human writes once and every new run reads (phase 7).

The memo is human guidance, not a permission: it is added to each agent's
system prompt for runs started after it is saved, and it never changes the
paths, tools or budgets a run allows. A PM may propose additions; only a
human approval appends them. The text lives in its own file in the app state
folder (which agent tools never read), outside settings, so editing it never
marks running teams as having changed settings.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

MAX_MEMO_CHARS = 4000
MAX_PROPOSAL_CHARS = 1000


def clean(value, label, limit, *, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f'{label}は{limit}文字以内で入力してください')
    if any((ord(char) < 32 and char not in '\n\t') or ord(char) == 127 for char in value):
        raise ValueError(f'{label}に制御文字は使えません')
    return value.replace('\r\n', '\n')


class MemoStore:
    def __init__(self, directory):
        self.path = Path(directory).absolute() / 'memo.json'
        self._lock = threading.Lock()
        self.text, self.updated_at = '', None
        with contextlib.suppress(OSError, ValueError, TypeError):
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.text = clean(data['text'], 'メモ', MAX_MEMO_CHARS)
            self.updated_at = float(data.get('updated_at') or 0) or None

    def public(self):
        return {'text': self.text, 'updated_at': self.updated_at, 'max_chars': MAX_MEMO_CHARS}

    def save(self, value):
        value = clean(value, 'メモ', MAX_MEMO_CHARS)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix='.memo-', dir=self.path.parent)
            try:
                updated = time.time()
                with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                    json.dump({'text': value, 'updated_at': updated}, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary)
            self.text, self.updated_at = value, updated
        return self.public()

    def append(self, addition):
        addition = clean(addition, '追加するメモ', MAX_PROPOSAL_CHARS, empty=False).strip()
        combined = (self.text.rstrip() + '\n' if self.text.strip() else '') + '- ' + addition
        if len(combined) > MAX_MEMO_CHARS:
            raise ValueError(f'メモが{MAX_MEMO_CHARS}文字を超えます。先にメモを整理してください')
        return self.save(combined)
