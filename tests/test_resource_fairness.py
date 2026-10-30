"""Deterministic admission ordering with synthetic tasks, no model or GPU process."""
import asyncio

import pytest

from workbench.resources import ResourceError, ResourceGate


async def pending(gate, count):
    for _ in range(100):
        if gate.snapshot()['queued'] == count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f'Expected {count} queued admissions, got {gate.snapshot()}')


async def cleanup(tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def empty(gate):
    assert gate.snapshot()['active'] == gate.snapshot()['queued'] == gate.snapshot()['waiting'] == 0
    assert not gate._tickets
    assert not gate._start_lock.locked()


@pytest.mark.asyncio
async def test_queued_peers_precede_same_task_immediate_reacquisition():
    gate = ResourceGate()
    order, tasks = [], []

    async def peer(name):
        async with gate.slot({'max_concurrent_requests': 1}):
            order.append(name)

    try:
        async with gate.slot({'max_concurrent_requests': 1}):
            order.append('A0')
            tasks = [asyncio.create_task(peer('B')), asyncio.create_task(peer('C'))]
            await pending(gate, 2)
        # Deliberately no sleep/yield between release and the next request.
        # This represents one agent continuing through fast synchronous tools.
        for name in ('A1', 'A2', 'A3'):
            async with gate.slot({'max_concurrent_requests': 1}):
                order.append(name)
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert order == ['A0', 'B', 'C', 'A1', 'A2', 'A3']
        empty(gate)
    finally:
        await cleanup(tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancelled', [0, 1], ids=['head', 'middle'])
async def test_cancelled_waiter_is_removed_without_skipping_other_peers(cancelled):
    gate = ResourceGate()
    order, tasks = [], []

    async def peer(name):
        async with gate.slot():
            order.append(name)

    try:
        async with gate.slot():
            tasks = [asyncio.create_task(peer(name)) for name in ('B', 'C', 'D')]
            await pending(gate, 3)
            tasks[cancelled].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[cancelled]
            await pending(gate, 2)
            tasks.append(asyncio.create_task(peer('E')))
            await pending(gate, 3)
        await asyncio.wait_for(asyncio.gather(*(task for task in tasks if not task.cancelled())), 5)
        assert order == (['C', 'D', 'E'] if cancelled == 0 else ['B', 'D', 'E'])
        empty(gate)
    finally:
        await cleanup(tasks)


@pytest.mark.asyncio
async def test_timed_out_head_wakes_next_eligible_waiter_while_another_slot_is_active():
    gate = ResourceGate()
    entered, release = asyncio.Event(), asyncio.Event()
    tasks = []

    async def blocked_head():
        async with gate.slot({'max_concurrent_requests': 1, 'queue_timeout_seconds': .05}):
            pytest.fail('Head should time out while the first slot remains held')

    async def second():
        async with gate.slot({'max_concurrent_requests': 2, 'queue_timeout_seconds': 2}):
            entered.set()
            await release.wait()

    try:
        async with gate.slot({'max_concurrent_requests': 2}):
            tasks.append(asyncio.create_task(blocked_head()))
            await pending(gate, 1)
            tasks.append(asyncio.create_task(second()))
            await pending(gate, 2)
            assert not entered.is_set()  # Later requests cannot jump the head's limit.
            with pytest.raises(ResourceError, match='timed out'):
                await tasks[0]
            await asyncio.wait_for(entered.wait(), 5)
            assert gate.snapshot()['active'] == 2 and gate.snapshot()['queued'] == 0
            release.set()
            await tasks[1]
        empty(gate)
    finally:
        release.set()
        await cleanup(tasks)


@pytest.mark.asyncio
async def test_fifo_admission_still_uses_parallel_capacity_without_exceeding_it():
    gate = ResourceGate()
    entered = {name: asyncio.Event() for name in ('A0', 'A1', 'B', 'C', 'D')}
    release = {name: asyncio.Event() for name in entered}
    order, tasks = [], []
    active = maximum = 0

    async def work(name):
        nonlocal active, maximum
        async with gate.slot({'max_concurrent_requests': 2}):
            active += 1
            maximum = max(maximum, active)
            order.append(name)
            entered[name].set()
            await release[name].wait()
            active -= 1

    try:
        for name in ('A0', 'A1'):
            tasks.append(asyncio.create_task(work(name)))
            await asyncio.wait_for(entered[name].wait(), 5)
        tasks.extend(asyncio.create_task(work(name)) for name in ('B', 'C', 'D'))
        await pending(gate, 3)
        release['A0'].set()
        await asyncio.wait_for(entered['B'].wait(), 5)
        assert not entered['C'].is_set() and not entered['D'].is_set()
        release['B'].set()
        await asyncio.wait_for(entered['C'].wait(), 5)
        assert not entered['D'].is_set()
        release['A1'].set()
        await asyncio.wait_for(entered['D'].wait(), 5)
        assert gate.snapshot()['active'] == 2 and maximum == 2
        assert order == ['A0', 'A1', 'B', 'C', 'D']
        release['C'].set()
        release['D'].set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        empty(gate)
    finally:
        for event in release.values():
            event.set()
        await cleanup(tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['failure', 'cancel'], ids=['gpu-error', 'gpu-cancel'])
async def test_failed_or_cancelled_admitted_gpu_wait_releases_next_ticket(outcome):
    reading, finish = asyncio.Event(), asyncio.Event()
    order, tasks = [], []

    async def gpu():
        reading.set()
        await finish.wait()
        raise ResourceError('Synthetic GPU observation failure')

    gate = ResourceGate(gpu)

    async def first():
        async with gate.slot({'gpu_guard_enabled': True}):
            pytest.fail('Failed GPU admission must never execute a request')

    async def peer(name):
        async with gate.slot({'gpu_guard_enabled': False}):
            order.append(name)

    try:
        tasks.append(asyncio.create_task(first()))
        await asyncio.wait_for(reading.wait(), 5)
        tasks.extend([asyncio.create_task(peer('B')), asyncio.create_task(peer('C'))])
        await pending(gate, 3)  # An acquired slot in GPU admission is also waiting.
        if outcome == 'cancel':
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
        else:
            finish.set()
            with pytest.raises(ResourceError, match='Synthetic GPU observation failure'):
                await tasks[0]
        async with gate.slot():
            order.append('new-D')
        await asyncio.wait_for(asyncio.gather(*tasks[1:]), 5)
        assert order == ['B', 'C', 'new-D']
        empty(gate)
    finally:
        finish.set()
        await cleanup(tasks)


@pytest.mark.asyncio
async def test_request_body_failure_releases_slot_without_later_reacquisition_barging():
    gate = ResourceGate()
    order, tasks = [], []

    async def peer(name):
        async with gate.slot():
            order.append(name)

    try:
        with pytest.raises(ValueError, match='Synthetic request failure'):
            async with gate.slot():
                tasks = [asyncio.create_task(peer('B')), asyncio.create_task(peer('C'))]
                await pending(gate, 2)
                raise ValueError('Synthetic request failure')
        async with gate.slot():
            order.append('A-next')
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert order == ['B', 'C', 'A-next']
        empty(gate)
    finally:
        await cleanup(tasks)
