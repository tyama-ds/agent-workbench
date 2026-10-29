"""Display-only observations of one engine inference, never scheduling input."""
import asyncio
import copy
import secrets
import time

from .provider_observation import observe_provider

TERMINAL = frozenset({'completed', 'error', 'cancelled'})


def provider_display(agent):
    value = getattr(agent, '_provider_observation', None)
    if not value:
        return None
    result = copy.deepcopy(value)
    if result['phase'] not in TERMINAL:
        delta = max(0, time.monotonic() - agent._provider_observed_mono)
        result['elapsed_seconds'] += delta
        result['phase_elapsed_seconds'] += delta
        result['observed_at'] = time.time()
    return result


async def complete_observed(agent, client, *args, purpose='work', **kwargs):
    started = time.monotonic()

    def observe(value):
        agent._provider_observation = {**copy.deepcopy(value), 'purpose': purpose}
        agent._provider_observed_mono = time.monotonic()

    observe({'schema_version': 1, 'call_id': secrets.token_hex(8), 'phase': 'started',
             'observed_at': time.time(), 'elapsed_seconds': 0.0, 'phase_elapsed_seconds': 0.0,
             'attempt': 1, 'history_only': False})

    def finish(phase):
        if agent._provider_observation['phase'] in TERMINAL:
            return  # Preserve the actual adapter's terminal boundary.
        result = provider_display(agent)
        at = time.time()
        result.update(previous_phase=result['phase'],
                      previous_phase_elapsed_seconds=result['phase_elapsed_seconds'],
                      phase=phase, phase_elapsed_seconds=0.0, phase_started_at=at,
                      terminal=True, observed_at=at, elapsed_seconds=max(0, time.monotonic()-started))
        observe(result)
    try:
        with observe_provider(observe):
            reply = await client.complete(*args, **kwargs)
    except BaseException as exc:
        # Covers synthetic clients and run deadline cancellation as well. Do not
        # publish exception text: it may contain provider credentials or input.
        finish('cancelled' if isinstance(exc, asyncio.CancelledError) else 'error')
        raise
    else:
        finish('completed')
        return reply
