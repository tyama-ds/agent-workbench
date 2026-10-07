"""Real HTTP receipt acknowledges acceptance before synthetic work completes."""
from test_session_transitions import session


async def test_http_message_receipt_accepts_exact_text_once_before_provider_completion(tmp_path):
    async with session(tmp_path) as case:
        run, agent, initial = await case.start()
        text = '  Exact 日本語 😀\n\t  '
        revision = agent.result_revision
        receipt = await case.api('post', f'/api/agents/{agent.id}/message', {'text': text})
        assert receipt == {'ok': True}
        assert list(agent.pending) == [(text, True)]
        assert agent.result_revision == revision + 1
        assert not initial.future.done()
        for _ in range(2):
            await case.api('get', f'/api/state?view=selected&run_id={run["id"]}&agent_id={agent.id}')
        assert list(agent.pending) == [(text, True)]
        assert agent.result_revision == revision + 1
        assert len(case.provider.history) == 1
        await case.stop(run)
