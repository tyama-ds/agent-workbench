"""Admission tests use synthetic responses only; no bridge or model is started."""
import asyncio
import copy
from contextlib import asynccontextmanager

import pytest

from workbench.providers import ProviderClient, ProviderError
from workbench.resources import ResourceError, ResourceGate


def copilot_profile(**overrides):
    return {"id": "copilot-agent", "kind": "local", "model": "same-copilot-model",
            "base_url": "http://127.0.0.1:8765/v1", "_copilot_agent": True, **overrides}


def local_profile(**overrides):
    return {"id": "local", "kind": "local", "model": "same-local-model",
            "base_url": "http://127.0.0.1:1234/v1", **overrides}


def response(text="fixture"):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}]}


async def until(predicate):
    # Yield to the pending tasks without relying on short wall-clock sleeps.
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


async def cancel_and_join(tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def test_default_gates_and_snapshots_are_independent():
    local = ResourceGate()
    client = ProviderClient(local)
    assert client.resource_gate is local
    assert client.copilot_resource_gate is not local
    snapshot = client.copilot_resource_snapshot()
    assert snapshot["active"] == snapshot["queued"] == 0
    snapshot["last_admission"]["fixture"] = True
    assert "fixture" not in client.copilot_resource_snapshot()["last_admission"]


async def test_three_copilot_sessions_and_one_local_request_have_separate_queues():
    client = ProviderClient()
    release, requests, tasks = asyncio.Event(), {}, []

    async def post(endpoint, body, headers, timeout, proxy):
        session = headers["X-Conversation-Id"]
        requests[session] = copy.deepcopy(body)
        await release.wait()
        return response(session)

    client._post = post
    limits = {"local": {"max_concurrent_requests": 1, "queue_timeout_seconds": 10}}
    try:
        for session in ("local/one", "local/two", "copilot/one", "copilot/two", "copilot/three", "copilot/four"):
            profile = (local_profile() if session.startswith("local/") else
                       copilot_profile(_copilot_max_concurrent_requests=3))
            tasks.append(asyncio.create_task(client.complete(
                profile, [{"role": "user", "content": session}], [], "policy", limits,
                conversation_id=session)))
        await until(lambda: client.resource_gate.snapshot()["queued"] == 1
                    and client.copilot_resource_snapshot()["queued"] == 1 and len(requests) == 4)
        assert set(requests) == {"local/one", "copilot/one", "copilot/two", "copilot/three"}
        assert client.resource_gate.snapshot()["active"] == 1
        assert client.copilot_resource_snapshot()["active"] == 3
        assert all(body["messages"][-1]["content"] == session for session, body in requests.items())
        tasks[1].cancel()
        tasks[-1].cancel()
        for task in (tasks[1], tasks[-1]):
            with pytest.raises(asyncio.CancelledError):
                await task
        assert client.resource_gate.snapshot()["queued"] == 0
        assert client.copilot_resource_snapshot()["queued"] == 0
        release.set()
        replies = await asyncio.gather(tasks[0], *tasks[2:5])
        assert {reply.text for reply in replies} == set(requests)
        assert client.resource_gate.snapshot()["active"] == 0
        assert client.copilot_resource_snapshot()["active"] == 0
    finally:
        release.set()
        await cancel_and_join(tasks)


async def test_copilot_default_one_does_not_inherit_local_parallel_four():
    client = ProviderClient()
    release, requests, tasks = asyncio.Event(), [], []

    async def post(endpoint, body, headers, timeout, proxy):
        requests.append(headers["X-Conversation-Id"])
        await release.wait()
        return response()

    client._post = post
    try:
        for session in ("run/worker-one", "run/worker-two"):
            tasks.append(asyncio.create_task(client.complete(
                copilot_profile(), [{"role": "user", "content": session}], [], "policy",
                {"local": {"max_concurrent_requests": 4}}, conversation_id=session)))
        await until(lambda: client.copilot_resource_snapshot()["queued"] == 1)
        assert requests == ["run/worker-one"]
        assert client.copilot_resource_snapshot()["active"] == 1
        assert client.resource_gate.snapshot()["active"] == 0
        release.set()
        await asyncio.gather(*tasks)
        assert requests == ["run/worker-one", "run/worker-two"]
    finally:
        release.set()
        await cancel_and_join(tasks)


async def test_copilot_conversation_header_is_stable_per_agent_and_histories_are_separate():
    client = ProviderClient()
    requests = []

    async def post(endpoint, body, headers, timeout, proxy):
        requests.append((headers["X-Conversation-Id"], copy.deepcopy(body["messages"])))
        return response("answer-" + headers["X-Conversation-Id"])

    client._post = post
    first_history = [{"role": "user", "content": "first worker's task"}]
    second_history = [{"role": "user", "content": "second worker's task"}]
    profile = copilot_profile(_copilot_max_concurrent_requests=3)
    first = await client.complete(profile, first_history, [], "policy", conversation_id="run/worker-one")
    await client.complete(profile, second_history, [], "policy", conversation_id="run/worker-two")
    followup = first_history + [{"role": "assistant", "provider_raw": first.raw},
                                {"role": "user", "content": "continue first task"}]
    await client.complete(profile, followup, [], "policy", conversation_id="run/worker-one")
    assert [session for session, _ in requests] == ["run/worker-one", "run/worker-two", "run/worker-one"]
    assert requests[1][1] == [{"role": "system", "content": "policy"}, *second_history]
    assert requests[2][1] == [{"role": "system", "content": "policy"}, *first_history,
                              {"role": "assistant", "content": "answer-run/worker-one"},
                              {"role": "user", "content": "continue first task"}]


class RecordingGate:
    def __init__(self):
        self.admissions = []

    @asynccontextmanager
    async def slot(self, config):
        self.admissions.append(copy.deepcopy(config))
        yield {}


@pytest.mark.parametrize("maximum", [1, 3, 16])
async def test_managed_limit_keeps_timeouts_intervals_and_never_retries(maximum):
    local_gate, copilot_gate = RecordingGate(), RecordingGate()
    client = ProviderClient(local_gate, copilot_gate=copilot_gate)
    requests = []
    local = {"gpu_guard_enabled": True, "max_retries": 3, "max_concurrent_requests": 1,
             "queue_timeout_seconds": 44, "request_timeout_seconds": 55,
             "min_interval_seconds": 2, "gpu_wait_timeout_seconds": 11}
    profile = copilot_profile(_copilot_max_concurrent_requests=maximum,
                              request_timeout_seconds=50, proxy_url="http://invalid.example:8080")
    before = copy.deepcopy((local, profile))

    async def post(endpoint, body, headers, timeout, proxy):
        requests.append((endpoint, body, headers, timeout, proxy))
        raise ProviderError("fixture busy", status=503, retryable=True)

    client._post = post
    with pytest.raises(ProviderError, match="fixture busy"):
        await client.complete(profile, [{"role": "user", "content": "fixture"}], [], "policy",
                              {"local": local}, conversation_id="run/worker")
    assert not local_gate.admissions
    assert len(copilot_gate.admissions) == len(requests) == 1
    assert copilot_gate.admissions[0] == {
        **local, "gpu_guard_enabled": False, "max_retries": 0,
        "max_concurrent_requests": maximum, "_remote_endpoint": False}
    assert requests[0][2]["X-Conversation-Id"] == "run/worker"
    assert requests[0][3:] == (50, None)
    assert (local, profile) == before


@pytest.mark.parametrize("value", [None, True, False, 0, 17, -1, 3.0, 1.5, "3", [], {}])
async def test_invalid_managed_limit_fails_before_admission_or_request(value):
    local_gate, copilot_gate = RecordingGate(), RecordingGate()
    client = ProviderClient(local_gate, copilot_gate=copilot_gate)

    async def post(*args):
        pytest.fail("invalid managed concurrency reached the provider")

    client._post = post
    with pytest.raises(ProviderError, match="concurrency must be an integer between 1 and 16"):
        await client.complete(copilot_profile(_copilot_max_concurrent_requests=value), [], [], "policy")
    assert not local_gate.admissions and not copilot_gate.admissions


@pytest.mark.parametrize("overrides", [{"id": "ordinary"}, {"_copilot_agent": False}, {"_copilot_agent": 1}])
async def test_private_limit_has_no_effect_without_managed_identity(overrides):
    local_gate, copilot_gate = RecordingGate(), RecordingGate()
    client = ProviderClient(local_gate, copilot_gate=copilot_gate)

    async def post(*args):
        return response()

    client._post = post
    await client.complete(copilot_profile(_copilot_max_concurrent_requests=16, **overrides), [], [], "policy",
                          {"local": {"max_concurrent_requests": 1, "gpu_guard_enabled": True}})
    assert not copilot_gate.admissions
    assert local_gate.admissions[0]["max_concurrent_requests"] == 1
    assert local_gate.admissions[0]["gpu_guard_enabled"] is True


async def test_unavailable_local_gpu_does_not_block_managed_bridge():
    calls = []

    async def unavailable_gpu():
        raise ResourceError("fixture GPU unavailable")

    client = ProviderClient(ResourceGate(unavailable_gpu), copilot_gate=ResourceGate(unavailable_gpu))

    async def post(endpoint, *args):
        calls.append(endpoint)
        return response()

    client._post = post
    limits = {"local": {"gpu_guard_enabled": True, "gpu_guard_fail_closed": True}}
    await client.complete(copilot_profile(), [], [], "policy", limits)
    with pytest.raises(ResourceError, match="fixture GPU unavailable"):
        await client.complete(local_profile(), [], [], "policy", limits)
    assert calls == ["http://127.0.0.1:8765/v1/chat/completions"]
    assert client.resource_gate.snapshot()["active"] == client.copilot_resource_snapshot()["active"] == 0


async def test_managed_bridge_still_requires_loopback_and_releases_failed_request():
    client = ProviderClient()
    calls = []

    async def post(*args):
        calls.append(True)
        raise ProviderError("fixture failure")

    client._post = post
    with pytest.raises(ProviderError, match="requires the local bridge"):
        await client.complete(copilot_profile(base_url="http://192.168.1.7:8765/v1"), [], [], "policy")
    assert not calls
    with pytest.raises(ProviderError, match="fixture failure"):
        await client.complete(copilot_profile(), [], [], "policy")
    assert len(calls) == 1
    assert client.copilot_resource_snapshot()["active"] == client.copilot_resource_snapshot()["queued"] == 0


async def test_same_openai_model_parallel_requests_keep_separate_histories():
    client = ProviderClient()
    release, requests, tasks = asyncio.Event(), [], []
    profile = {"id": "gpt", "kind": "openai", "model": "same-gpt-model", "api_key": "synthetic-key"}

    async def post(endpoint, body, headers, timeout, proxy):
        requests.append(copy.deepcopy(body))
        await release.wait()
        return {"status": "completed", "output": []}

    client._post = post
    try:
        for label in ("worker-one", "worker-two", "worker-three"):
            tasks.append(asyncio.create_task(client.complete(
                profile, [{"role": "user", "content": label}], [], "policy",
                {"local": {"max_concurrent_requests": 1}}, conversation_id="run/" + label)))
        await until(lambda: len(requests) == 3)
        assert {request["input"][0]["content"] for request in requests} == {
            "worker-one", "worker-two", "worker-three"}
        assert all(request["store"] is False and "previous_response_id" not in request for request in requests)
        assert client.resource_gate.snapshot()["active"] == client.copilot_resource_snapshot()["active"] == 0
        release.set()
        await asyncio.gather(*tasks)
    finally:
        release.set()
        await cancel_and_join(tasks)
