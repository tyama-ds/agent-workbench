import asyncio
import time

import pytest

from workbench.resources import ResourceError, ResourceGate, retry_settings


@pytest.mark.asyncio
async def test_global_concurrency_and_cancelled_queue_release():
    gate = ResourceGate()
    entered, release = asyncio.Event(), asyncio.Event()
    async def hold():
        async with gate.slot({"max_concurrent_requests": 1}):
            entered.set()
            await release.wait()
    first = asyncio.create_task(hold())
    await entered.wait()
    queued = asyncio.create_task(hold())
    await asyncio.sleep(.02)
    assert gate.snapshot()["active"] == 1 and gate.snapshot()["queued"] == 1
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    release.set()
    await first
    assert gate.snapshot()["active"] == gate.snapshot()["queued"] == 0
    async with gate.slot():
        assert gate.snapshot()["active"] == 1


@pytest.mark.asyncio
async def test_parallel_requests_cannot_exceed_global_limit():
    gate = ResourceGate()
    active = maximum = 0
    async def work():
        nonlocal active, maximum
        async with gate.slot({"max_concurrent_requests": 2}):
            active += 1
            maximum = max(active, maximum)
            await asyncio.sleep(.01)
            active -= 1
    await asyncio.gather(*(work() for _ in range(8)))
    assert maximum == 2


@pytest.mark.asyncio
async def test_interval_and_queue_timeout_do_not_leak_slot():
    gate = ResourceGate()
    starts = []
    for _ in range(3):
        async with gate.slot({"min_interval_seconds": .04}):
            starts.append(time.monotonic())
    assert all(b - a >= .035 for a, b in zip(starts, starts[1:]))
    with pytest.raises(ResourceError, match="timed out"):
        async with gate.slot({"min_interval_seconds": 2, "queue_timeout_seconds": .02}):
            pytest.fail("Timed-out admission entered")
    assert gate.snapshot()["active"] == gate.snapshot()["queued"] == 0


@pytest.mark.asyncio
async def test_actual_gpu_readings_gate_both_memory_and_utilization():
    samples = [dict(index=0, used_mb=10000, total_mb=12000, utilization_percent=10),
               dict(index=0, used_mb=5000, total_mb=12000, utilization_percent=95),
               dict(index=0, used_mb=5000, total_mb=12000, utilization_percent=30)]
    calls = 0
    async def read():
        nonlocal calls
        row = samples[min(calls, 2)]
        calls += 1
        return [row]
    gate = ResourceGate(read)
    async with gate.slot({"gpu_guard_enabled": True, "max_vram_mb": 6000,
                          "max_gpu_utilization_percent": 80, "gpu_poll_interval_seconds": .01}) as meta:
        assert calls == 3 and meta["gpu"]["used_mb"] == 5000
        assert meta["gpu_memory_enforcement"] == "admission_check_only"
    assert gate.snapshot()["gpu_readings"][0]["utilization_percent"] == 30


@pytest.mark.asyncio
async def test_gpu_failure_closed_and_explicit_failure_open():
    async def read():
        raise ResourceError("GPU unavailable")
    gate = ResourceGate(read)
    with pytest.raises(ResourceError, match="GPU unavailable"):
        async with gate.slot({"gpu_guard_enabled": True}):
            pytest.fail("Unavailable GPU entered")
    async with gate.slot({"gpu_guard_enabled": True, "gpu_guard_fail_closed": False}) as meta:
        assert meta["gpu_guard"] == "unavailable_allowed_by_configuration"
    assert gate.snapshot()["active"] == 0


@pytest.mark.asyncio
async def test_gpu_timeout_and_zero_thresholds():
    async def read():
        return [dict(index=0, used_mb=8000, total_mb=12000, utilization_percent=90)]
    gate = ResourceGate(read)
    with pytest.raises(ResourceError, match="timed out"):
        async with gate.slot({"gpu_guard_enabled": True, "max_vram_mb": 1,
                              "gpu_wait_timeout_seconds": .02, "gpu_poll_interval_seconds": .01}):
            pytest.fail("Busy GPU entered")
    async with gate.slot({"gpu_guard_enabled": True, "max_vram_mb": 0, "max_gpu_utilization_percent": 0}):
        pass
    assert gate.snapshot()["active"] == 0


@pytest.mark.parametrize("config", [{"max_retries": 4}, {"max_retries": True}, {"retry_backoff_seconds": float('nan')}])
def test_retry_settings_are_bounded(config):
    with pytest.raises(ResourceError):
        retry_settings(config)


@pytest.mark.asyncio
async def test_nvidia_smi_query_reads_actual_values_without_shell(monkeypatch):
    import workbench.resources as resources
    calls = []
    class Process:
        returncode = 0
        async def communicate(self):
            return b'0, 4096, 16384, 35\n1, 100, 24576, 2\n', None
    async def start(*argv, **kwargs):
        calls.append((argv, kwargs))
        return Process()
    monkeypatch.setattr(resources, 'find_nvidia_smi', lambda: '/test/nvidia-smi')
    monkeypatch.setattr(resources.asyncio, 'create_subprocess_exec', start)
    rows = await resources.read_nvidia_gpus()
    assert rows[0] == dict(index=0, used_mb=4096, total_mb=16384, utilization_percent=35)
    assert calls[0][0] == ('/test/nvidia-smi', '--query-gpu=index,memory.used,memory.total,utilization.gpu', '--format=csv,noheader,nounits')
    assert 'shell' not in calls[0][1]


def test_nvidia_discovery_never_searches_current_or_project_directory(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import workbench.resources as resources
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('SystemRoot', str(tmp_path / 'absent-windows'))
    monkeypatch.setenv('ProgramFiles', str(tmp_path / 'absent-programs'))
    executable = 'nvidia-smi.exe' if os.name == 'nt' else 'nvidia-smi'
    (tmp_path / executable).write_text('not executable')
    project = Path(resources.__file__).resolve().parents[1]
    monkeypatch.setenv('PATH', os.pathsep.join([str(tmp_path), '.', '', str(project)]))
    # No current-directory implicit lookup, even if a fake executable is present.
    if os.name == 'nt':
        assert resources.find_nvidia_smi() is None
        trusted = tmp_path / 'trusted'
        trusted.mkdir()
        (trusted / executable).write_text('fixture')
        monkeypatch.setenv('PATH', os.pathsep.join([str(tmp_path), str(trusted)]))
        assert resources.find_nvidia_smi() == str(trusted / executable)


def test_resource_bounds_match_settings_interface():
    assert retry_settings({'retry_backoff_seconds': 60}) == (0, 60)
