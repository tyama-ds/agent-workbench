"""Process-wide admission control for requests to a local inference server.

GPU readings are an admission check, not a GPU allocator. The model server must
enforce its own memory limits; another process can allocate memory after a poll.
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable

from .runtime_paths import FROZEN, PROTECTED_ROOTS


class ResourceError(RuntimeError):
    """A safe, user-facing admission failure."""


def number(config: dict, key: str, default: float, minimum: float, maximum: float) -> float:
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ResourceError(f"{key} must be a finite number")
    if not minimum <= value <= maximum:
        raise ResourceError(f"{key} must be between {minimum:g} and {maximum:g}")
    return float(value)


def integer(config: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    value = number(config, key, default, minimum, maximum)
    if value != int(value):
        raise ResourceError(f"{key} must be an integer")
    return int(value)


def retry_settings(config: dict) -> tuple[int, float]:
    return (integer(config, "max_retries", 0, 0, 3),
            number(config, "retry_backoff_seconds", 1, 0, 60))


def find_nvidia_smi() -> str | None:
    """Resolve explicit directories without Windows' implicit CWD executable search."""
    executable = "nvidia-smi.exe" if os.name == "nt" else "nvidia-smi"
    current, project = Path.cwd().resolve(), Path(__file__).resolve().parents[1]
    directories = []
    if os.name == "nt":
        if os.environ.get("SystemRoot"):
            directories.append(Path(os.environ["SystemRoot"]) / "System32")
        if os.environ.get("ProgramFiles"):
            directories.append(Path(os.environ["ProgramFiles"]) / "NVIDIA Corporation" / "NVSMI")
    else:
        directories += [Path("/usr/bin"), Path("/usr/local/bin")]
    directories += [Path(entry.strip('"')) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    for directory in directories:
        if not directory.is_absolute():
            continue
        try:
            resolved = directory.resolve()
            if resolved == current or any(resolved.is_relative_to(root) for root in PROTECTED_ROOTS):
                continue
            candidate = (resolved / executable).resolve()
            if candidate.parent == current or any(candidate.is_relative_to(root) for root in PROTECTED_ROOTS):
                continue
            if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return str(candidate)
        except (OSError, RuntimeError):
            continue
    return None


async def read_nvidia_gpus() -> list[dict]:
    """Read current NVIDIA usage without a shell or model-server side effects."""
    executable = find_nvidia_smi()
    if not executable:
        raise ResourceError("GPU guard enabled, but nvidia-smi is unavailable")
    process = None
    try:
        if FROZEN and os.name == "nt":
            from .windows_runtime import capture_helper
            output = await capture_helper("gpu", executable, timeout=8)
        else:
            process = await asyncio.create_subprocess_exec(
                executable, "--query-gpu=index,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=0x08000000 if os.name == "nt" else 0)
            output, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode or len(output) > 65536:
                raise ResourceError("nvidia-smi could not provide bounded GPU readings")
        readings = []
        for line in output.decode("utf-8", "strict").splitlines():
            fields = [int(value.strip()) for value in line.split(",")]
            if len(fields) != 4 or any(value < 0 for value in fields):
                raise ValueError
            index, used, total, utilization = fields
            if used > total or utilization > 100:
                raise ValueError
            readings.append({"index": index, "used_mb": used, "total_mb": total,
                             "utilization_percent": utilization})
        if not readings:
            raise ValueError
        return readings
    except (OSError, ValueError, UnicodeError, RuntimeError, asyncio.TimeoutError) as exc:
        raise ResourceError("GPU readings are unavailable; request was not started") from None
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


class ResourceGate:
    """Share one instance across all local profiles to enforce a global limit."""

    def __init__(self, gpu_reader: Callable[[], Awaitable[list[dict]]] | None = None):
        self._condition = asyncio.Condition()
        self._start_lock = asyncio.Lock()
        self._active = 0
        self._waiting = 0
        self._last_start: float | None = None
        self._gpu_reader = gpu_reader or read_nvidia_gpus
        self.last_gpu_readings: list[dict] = []
        self.last_admission: dict = {}

    def snapshot(self) -> dict:
        return {"active": self._active, "waiting": self._waiting, "queued": self._waiting,
                "gpu_readings": [dict(row) for row in self.last_gpu_readings],
                "last_admission": dict(self.last_admission),
                "gpu_memory_enforcement": "admission_check_only"}

    async def _gpu_ready(self, config: dict) -> dict:
        enabled = config.get("gpu_guard_enabled", False)
        if not isinstance(enabled, bool):
            raise ResourceError("gpu_guard_enabled must be true or false")
        if not enabled:
            return {"gpu_guard": "remote_not_monitored" if config.get("_remote_endpoint") else "disabled",
                    "gpu_memory_enforcement": "admission_check_only"}
        index = integer(config, "gpu_index", 0, 0, 1024)
        # A zero threshold means this particular metric is not constrained.
        vram = number(config, "max_vram_mb", 0, 0, 1048576)
        utilization = number(config, "max_gpu_utilization_percent", 0, 0, 100)
        minimum_free = number(config, "min_free_vram_mb", 0, 0, 1048576)
        poll = number(config, "gpu_poll_interval_seconds", 1, 0.01, 60)
        while True:
            try:
                readings = await self._gpu_reader()
            except ResourceError:
                fail_closed = config.get("gpu_guard_fail_closed", True)
                if not isinstance(fail_closed, bool):
                    raise ResourceError("gpu_guard_fail_closed must be true or false")
                if fail_closed:
                    raise
                return {"gpu_guard": "unavailable_allowed_by_configuration",
                        "gpu_memory_enforcement": "admission_check_only"}
            self.last_gpu_readings = [dict(row) for row in readings]
            selected = next((row for row in readings if row.get("index") == index), None)
            if selected is None:
                raise ResourceError("Configured GPU index was not found")
            if ((not vram or selected["used_mb"] <= vram) and (not utilization or selected["utilization_percent"] <= utilization)
                    and selected["total_mb"] - selected["used_mb"] >= minimum_free):
                return {"gpu_guard": "passed", "gpu": dict(selected),
                        "gpu_memory_enforcement": "admission_check_only"}
            await asyncio.sleep(poll)

    @asynccontextmanager
    async def slot(self, local_config: dict | None = None):
        config = dict(local_config or {})
        maximum = integer(config, "max_concurrent_requests", 1, 1, 64)
        timeout = number(config, "queue_timeout_seconds", 120, 0.01, 3600)
        interval = number(config, "min_interval_seconds", 0, 0, 3600)
        acquired = False
        self._waiting += 1
        try:
            try:
                async with asyncio.timeout(timeout):
                    async with self._condition:
                        await self._condition.wait_for(lambda: self._active < maximum)
                        self._active += 1
                        acquired = True
                    # Serialize admission timestamps, including the first request
                    # after a GPU wait, so a queue cannot burst through together.
                    async with self._start_lock:
                        # Event-loop timers can wake early on Windows. Recheck
                        # the monotonic deadline rather than admitting early.
                        if self._last_start is not None and interval > 0:
                            deadline = self._last_start + interval
                            while (delay := deadline - time.monotonic()) > 0:
                                await asyncio.sleep(delay)
                        gpu_timeout = number(config, "gpu_wait_timeout_seconds", timeout, 0.01, 3600)
                        async with asyncio.timeout(gpu_timeout):
                            metadata = await self._gpu_ready(config)
                        self.last_admission = dict(metadata)
                        self._last_start = time.monotonic()
            except TimeoutError:
                raise ResourceError("Local request queue or GPU admission timed out") from None
            self._waiting -= 1
            try:
                yield metadata
            finally:
                self._waiting += 1
        finally:
            self._waiting -= 1
            if acquired:
                async with self._condition:
                    self._active -= 1
                    self._condition.notify_all()
