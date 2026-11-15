"""Copies of files as they were before the app overwrote them.

Every overwrite through PathHarness.write_bytes (text, Office, Python and
browser outputs) first stores the replaced bytes here, keyed by their SHA-256.
A human can then put a file back from its saved-file receipt. The store lives
in the app's own state folder, which agent tools may never read, and only for
the current app session: each process uses its own folder and removes it on
close; folders left by a crashed process are removed after a week.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path

MAX_RUN_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
STALE_SECONDS = 7 * 24 * 3600
_RUN = re.compile(r"r-[0-9a-f]{16}")
_SHA = re.compile(r"[0-9a-f]{64}")


class CheckpointStore:
    def __init__(self, directory):
        self.base = Path(directory).absolute() / "checkpoints"
        self.root = self.base / ("p-" + secrets.token_hex(8))
        self._lock = threading.Lock()
        self._sizes: dict[str, int] = {}
        self._total = 0
        self._sweep()

    def _sweep(self):
        """Remove folders that crashed processes left behind."""
        with contextlib.suppress(OSError):
            for child in self.base.iterdir():
                with contextlib.suppress(OSError):
                    if child.is_dir() and not child.is_symlink() and time.time() - child.stat().st_mtime > STALE_SECONDS:
                        shutil.rmtree(child, ignore_errors=True)

    def _path(self, run_id: str, digest: str) -> Path:
        if not isinstance(run_id, str) or not _RUN.fullmatch(run_id) or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError("Invalid checkpoint key")
        return self.root / run_id / digest

    def save(self, run_id: str, data: bytes) -> str | None:
        """Store bytes for this run; returns their SHA-256, or None when over the limits."""
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(run_id, digest)
        with self._lock:
            if path.is_file():
                return digest
            used = self._sizes.get(run_id, 0)
            if used + len(data) > MAX_RUN_BYTES or self._total + len(data) > MAX_TOTAL_BYTES:
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary)
            self._sizes[run_id] = used + len(data)
            self._total += len(data)
            return digest

    def has(self, run_id: str, digest: str) -> bool:
        try:
            return self._path(run_id, digest).is_file()
        except ValueError:
            return False

    def load(self, run_id: str, digest: str) -> bytes:
        data = self._path(run_id, digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Checkpoint content does not match its hash")
        return data

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)
