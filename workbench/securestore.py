"""Explicit opt-in Windows CurrentUser DPAPI credentials, never public settings.

The Engine owns the state-directory writer lease. Ciphertext is the only payload
ever written; restored credentials remain bound to their exact provider identity.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

PROTECTION = 'windows-dpapi-current-user'
MAX_BYTES = 1024 * 1024
MAX_PLAIN_BYTES = 256 * 1024
IDENTITY = ('id', 'kind', 'base_url', 'api_key_env')
ID = re.compile(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}\Z')
ERROR = '保存済み API キーを使用できません。元のファイルを保持しています。保存先・Windows ユーザー・設定を確認してください。'
MISMATCH = '保存済み API キーと接続先設定が一致しません。該当キーを明示的に解除してから設定してください。'


class CredentialStorageError(ValueError):
    code = 'credential_storage_error'


class SavedCredentialIdentityChange(CredentialStorageError):
    code = 'saved_credential_identity_change'

    def __init__(self, affected_ids):
        super().__init__('保存済み API キーを解除してから、接続先・環境変数名・IDの変更またはプロファイル削除を行ってください。')
        self.affected_ids = sorted(affected_ids)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CredentialStorageError(ERROR)
        result[key] = value
    return result


def _decode(data):
    return json.loads(data.decode('utf-8'), object_pairs_hook=_object)


def _supported():
    return os.name == 'nt'


def _dpapi(data, *, decrypt=False):
    """Use CurrentUser, UI forbidden, with application-specific public entropy."""
    if os.name != 'nt':
        raise CredentialStorageError('キーの暗号化保存は Windows のみ対応しています。')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    protect = crypt.CryptProtectData
    protect.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p,
                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    protect.restype = wintypes.BOOL
    unprotect = crypt.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    unprotect.restype = wintypes.BOOL
    raw = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    entropy_bytes = b'AgentWorkbench credential vault v1'
    entropy_raw = (ctypes.c_ubyte * len(entropy_bytes)).from_buffer_copy(entropy_bytes)
    source = Blob(len(data), raw)
    entropy = Blob(len(entropy_bytes), entropy_raw)
    result = Blob()
    try:
        if decrypt:
            ok = unprotect(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(result))
        else:
            ok = protect(ctypes.byref(source), 'Agent Workbench', ctypes.byref(entropy), None, None, 1, ctypes.byref(result))
        if not ok or not result.pbData or result.cbData > MAX_BYTES:
            raise CredentialStorageError(ERROR)
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.memset(raw, 0, len(data))
        if result.pbData:
            ctypes.memset(result.pbData, 0, result.cbData)
            kernel.LocalFree(result.pbData)


def _validate(value):
    if not isinstance(value, dict) or set(value) != {'version', 'entries'} or type(value['version']) is not int or value['version'] != 1:
        raise CredentialStorageError(ERROR)
    rows = value['entries']
    if not isinstance(rows, list) or len(rows) > 16:
        raise CredentialStorageError(ERROR)
    found = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {*IDENTITY, 'key'}:
            raise CredentialStorageError(ERROR)
        if any(not isinstance(row[field], str) for field in row):
            raise CredentialStorageError(ERROR)
        if not ID.fullmatch(row['id']) or row['id'] in found or row['id'] in {'search', 'copilot-agent'}:
            raise CredentialStorageError(ERROR)
        if row['kind'] not in {'local', 'openai', 'anthropic'} or not 1 <= len(row['key']) <= 4096:
            raise CredentialStorageError(ERROR)
        if len(row['base_url']) > 2048 or len(row['api_key_env']) > 128 or any(ord(c) < 32 or ord(c) == 127 for field in row for c in row[field]):
            raise CredentialStorageError(ERROR)
        found[row['id']] = dict(row)
    return found


class CredentialStore:
    def __init__(self, directory, profiles, *, lease):
        self.path = Path(directory).absolute() / 'credentials.dpapi'
        self.supported = _supported()
        self._lease = lease
        self._entries = {}
        self._digest = None
        self._loaded = False
        self._closed = False
        self.error = ''
        self.affected_ids = []
        self._profiles = profiles
        try:
            self._require_lease()
            data = self._read_bytes()
            if data is not None:
                self._digest = hashlib.sha256(data).hexdigest()
                if not self.supported:
                    raise CredentialStorageError(ERROR)
                envelope = _decode(data)
                if (not isinstance(envelope, dict) or set(envelope) != {'version', 'protection', 'ciphertext'}
                    or type(envelope['version']) is not int or envelope['version'] != 1
                    or envelope['protection'] != PROTECTION or not isinstance(envelope['ciphertext'], str)):
                    raise CredentialStorageError(ERROR)
                encrypted = base64.b64decode(envelope['ciphertext'], validate=True)
                plain = _dpapi(encrypted, decrypt=True)
                if len(plain) > MAX_PLAIN_BYTES:
                    raise CredentialStorageError(ERROR)
                self._entries = _validate(_decode(plain))
            self._loaded = True
            self.check_bindings(profiles)
        except (OSError, ValueError, TypeError, RecursionError, UnicodeError):
            self.error = ERROR

    def _require_lease(self):
        if self._closed or self._lease is None or self._lease.closed:
            raise CredentialStorageError(ERROR)

    def _paths_safe(self):
        for path in (self.path, *self.path.parents):
            if path.is_symlink():
                raise CredentialStorageError(ERROR)
            if path.exists():
                info = path.lstat()
                if getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise CredentialStorageError(ERROR)
                if path == self.path:
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                        raise CredentialStorageError(ERROR)
                elif not stat.S_ISDIR(info.st_mode):
                    raise CredentialStorageError(ERROR)

    def _read_bytes(self):
        self._paths_safe()
        if not self.path.exists():
            return None
        with self.path.open('rb') as stream:
            before = self.path.lstat()
            opened = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or opened.st_nlink != 1:
                raise CredentialStorageError(ERROR)
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise CredentialStorageError(ERROR)
        self._paths_safe()
        return data

    def check_bindings(self, profiles):
        self._profiles = profiles
        actual = {p['id']: p for p in profiles}
        self.affected_ids = sorted(ident for ident, row in self._entries.items()
                                   if ident not in actual or any(row[k] != actual[ident].get(k, '') for k in IDENTITY)) if self._loaded else []
        return self.affected_ids

    def require_usable(self):
        self._require_lease()
        self.check_bindings(self._profiles)
        if not self._loaded or self.error or self.affected_ids:
            raise CredentialStorageError(MISMATCH if self.affected_ids else self.error or ERROR)

    def require_identity(self, profiles):
        if not self._loaded or self.error:
            raise CredentialStorageError(self.error or ERROR)
        actual = {p['id']: p for p in profiles}
        affected = [ident for ident, row in self._entries.items()
                    if ident not in actual or any(row[k] != actual[ident].get(k, '') for k in IDENTITY)]
        if affected:
            raise SavedCredentialIdentityChange(affected)

    def values(self):
        return [row['key'] for row in self._entries.values()]

    def contains(self, ident):
        return self._loaded and ident in self._entries

    def key(self, profile):
        self.require_usable()
        row = self._entries.get(profile['id'])
        if row and any(row[k] != profile.get(k, '') for k in IDENTITY):
            raise CredentialStorageError(MISMATCH)
        return row['key'] if row else ''

    def public(self):
        self.check_bindings(self._profiles)
        available = self._loaded and not self.error and not self.affected_ids and not self._closed
        status = 'identity_mismatch' if self.affected_ids else ('unavailable' if not available else ('ready' if self.supported else 'unsupported'))
        return {'supported': self.supported, 'available': available and self.supported, 'status': status,
                'error': MISMATCH if self.affected_ids else self.error, 'path': str(self.path),
                'protection': PROTECTION, 'affected_ids': list(self.affected_ids)}

    def replace(self, ident, key, profile=None):
        """A clear may recover a readable identity mismatch, never corrupt bytes."""
        self._require_lease()
        if not self._loaded or self.error:
            raise CredentialStorageError(self.error or ERROR)
        if key:
            self.require_usable()
        if not key and ident not in self._entries:
            if self.affected_ids:
                raise CredentialStorageError(MISMATCH)
            return
        if not self.supported:
            raise CredentialStorageError('キーの暗号化保存は Windows のみ対応しています。')
        entries = {name: dict(row) for name, row in self._entries.items()}
        if key:
            entries[ident] = {field: profile[field] for field in IDENTITY} | {'key': key}
        else:
            entries.pop(ident, None)
        payload = {'version': 1, 'entries': list(entries.values())}
        _validate(payload)
        plain = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(plain) > MAX_PLAIN_BYTES:
            raise CredentialStorageError(ERROR)
        try:
            encrypted = _dpapi(plain)
            encoded = json.dumps({'version': 1, 'protection': PROTECTION,
                                  'ciphertext': base64.b64encode(encrypted).decode('ascii')}, separators=(',', ':')).encode('ascii')
            if len(encoded) > MAX_BYTES:
                raise CredentialStorageError(ERROR)
            current = self._read_bytes()
            if (hashlib.sha256(current).hexdigest() if current is not None else None) != self._digest:
                raise CredentialStorageError(ERROR)
            descriptor, name = tempfile.mkstemp(prefix='.credentials-', suffix='.tmp', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                current = self._read_bytes()
                if (hashlib.sha256(current).hexdigest() if current is not None else None) != self._digest:
                    raise CredentialStorageError(ERROR)
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            raise CredentialStorageError('API キーの暗号化保存・解除に失敗しました。現在のキーは変更していません。') from None
        self._entries = entries
        self._digest = hashlib.sha256(encoded).hexdigest()
        self.check_bindings(self._profiles)

    def close(self):
        self._entries.clear()
        self._closed = True
