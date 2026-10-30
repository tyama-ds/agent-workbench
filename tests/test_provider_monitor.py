import asyncio
from types import SimpleNamespace

import pytest

from workbench.engine import Agent
from workbench.provider_monitor import complete_observed, provider_display
from workbench.provider_observation import observation_phase, observed_provider_call


@pytest.mark.asyncio
async def test_provider_display_observes_live_phase_without_changing_messages_or_signature():
    ready, release = asyncio.Event(), asyncio.Event()
    payload = {'original': ['unchanged']}

    class Client:
        @observed_provider_call
        async def complete(self, sent, *, conversation_id):
            assert sent is payload and conversation_id == 'r/a'
            observation_phase('response_wait')
            ready.set()
            await release.wait()
            return SimpleNamespace(usage={'input_tokens': 9})

    agent = Agent('a', 'r', 'A', 'worker', 'p', None)
    task = asyncio.create_task(complete_observed(agent, Client(), payload, conversation_id='r/a'))
    await ready.wait()
    first = provider_display(agent)
    await asyncio.sleep(0)
    second = agent.public()['provider_observation']
    assert second['phase'] == 'response_wait' and second['phase_elapsed_seconds'] >= first['phase_elapsed_seconds']
    second['phase'] = 'forged'
    assert provider_display(agent)['phase'] == 'response_wait'
    release.set()
    await task
    final = provider_display(agent)
    assert final['phase'] == 'completed' and final['usage'] == {'input_tokens': 9}
    await asyncio.sleep(0)
    assert provider_display(agent) == final
    assert payload == {'original': ['unchanged']}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['error', 'cancel', 'normal'])
async def test_uninstrumented_client_has_no_invented_http_phase_and_no_error_text(kind):
    agent = SimpleNamespace()

    class Client:
        async def complete(self):
            assert provider_display(agent)['phase'] == 'started'
            if kind == 'error':
                raise ValueError('SECRET prompt or URL')
            if kind == 'cancel':
                raise asyncio.CancelledError()
            return 'unchanged reply'

    try:
        result = await complete_observed(agent, Client(), purpose='compaction')
        assert result == 'unchanged reply'
    except (ValueError, asyncio.CancelledError):
        assert kind != 'normal'
    observation = provider_display(agent)
    assert observation['phase'] == {'error':'error','cancel':'cancelled','normal':'completed'}[kind]
    assert observation['purpose'] == 'compaction'
    assert observation['phase_elapsed_seconds'] == 0 and observation['terminal'] is True
    assert observation['phase_started_at'] == observation['observed_at']
    assert observation['previous_phase'] == 'started'
    assert 'SECRET' not in str(observation) and 'response_wait' not in str(observation)


def test_no_observation_is_absent_not_idle():
    agent = Agent('a', 'r', 'A', 'worker', 'p', None)
    assert provider_display(agent) is None
    assert 'provider_observation' not in agent.public()
