"""Question identity survives HTTP, redaction and read-only display archives."""
import copy

import pytest

from test_history_persistence import document
from test_session_transitions import session, response
from workbench.history import HistoryError, HistoryStore, archived_view, redact_document, validate
from workbench.redaction import SecretRedactor


async def test_timed_question_requires_its_id_and_stale_answer_never_reaches_next_question(tmp_path):
    async with session(tmp_path) as case:
        run, agent, initial = await case.start()
        await case.finish(agent, initial, response(('ask_user', {
            'question': 'Choose a format', 'recommendation': 'Use CSV', 'kind': 'consultation'})))
        first = agent.question_state['question_id']
        snapshot = await case.api('get', f'/api/state?view=selected&run_id={run["id"]}&agent_id={agent.id}')
        public = next(row for row in snapshot['agents'] if row['id'] == agent.id)['question_state']
        assert public['question_id'] == first
        assert public['deadline_at'] - public['asked_at'] == 90
        assert public['recommendation'] == 'Use CSV' and public['resolution'] == 'pending'
        rejected = await case.api('post', f'/api/agents/{agent.id}/message', {'text': 'Use JSON'}, status=409)
        assert rejected['code'] == 'question_conflict'
        assert agent.question_state['resolution'] == 'pending' and not agent.pending
        assert await case.api('post', f'/api/agents/{agent.id}/message',
                              {'text': 'Use JSON', 'question_id': first}) == {'ok': True}
        resumed = await case.take(agent)
        assert resumed.messages[-1]['content'] == 'Use JSON'
        await case.finish(agent, resumed, response(('ask_user', {
            'question': 'Choose a delimiter', 'recommendation': 'Use a comma'})))
        second = agent.question_state['question_id']
        counters = (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.result_revision)
        assert second != first
        late = await case.api('post', f'/api/agents/{agent.id}/message',
                              {'text': 'Late format answer', 'question_id': first}, status=409)
        assert late['code'] == 'question_conflict'
        assert agent.question == 'Choose a delimiter' and not agent.pending
        assert counters == (run['model_calls'], run['tool_calls'], run['auto_collaborations'], agent.result_revision)
        assert case.provider.requested.empty()


async def test_permission_has_no_deadline_and_question_metadata_is_saved_as_display_only(tmp_path):
    async with session(tmp_path) as case:
        run, agent, initial = await case.start()
        await case.finish(agent, initial, response(('ask_user', {
            'question': 'Authorize an otherwise unauthorized operation?',
            'kind': 'permission', 'recommendation': 'Keep the current files'})))
        assert agent.question_state['deadline_at'] is None
        assert agent.question_state['resolution'] == 'pending'
        saved, at = case.engine.history.read(run['id'])
        receipt = saved['agents'][0]['question_state']
        assert receipt == agent.question_state
        view = archived_view(saved, at)
        assert view['agents'][0]['question_state'] == receipt
        assert view['agents'][0]['read_only']
        assert not view['agents'][0]['message_eligibility']['allowed']
        assert len(case.provider.history) == 1


def question_document():
    value = document()
    value['agents'][0]['question_state'] = {
        'question_id': 'q-' + 'a' * 32, 'kind': 'consultation', 'recommendation': 'Prefer a table',
        'asked_at': 12, 'deadline_at': 102, 'resolution': 'fallback', 'resolved_at': 102, 'reason': 'timeout'}
    return value


def test_question_receipt_redacts_prose_without_corrupting_identifier_or_enums(tmp_path):
    value = question_document()
    redactor = SecretRedactor()
    redactor.remember(['a'])
    scrubbed = redact_document(value, redactor.redact)
    assert scrubbed['agents'][0]['question_state']['question_id'] == 'q-' + 'a' * 32
    assert scrubbed['agents'][0]['question_state']['kind'] == 'consultation'
    assert scrubbed['agents'][0]['question_state']['resolution'] == 'fallback'
    assert '[redacted]' in scrubbed['agents'][0]['question_state']['recommendation']
    validate(scrubbed)
    store = HistoryStore(tmp_path / 'history-state')
    try:
        store.save(value, redactor.redact)
        restored, at = store.read(value['run']['id'])
        assert restored['agents'][0]['question_state'] == scrubbed['agents'][0]['question_state']
        assert archived_view(restored, at)['agents'][0]['read_only']
    finally:
        store.close()


@pytest.mark.parametrize('field,invalid', [
    ('question_id', '../other'), ('kind', 'approval_inferred'), ('resolution', 'human_approved'),
    ('deadline_at', float('nan')), ('resolved_at', True), ('asked_at', -1),
    ('recommendation', []), ('reason', {}), ('kind', 'permission'),
])
def test_malformed_question_receipts_are_rejected(field, invalid):
    value = copy.deepcopy(question_document())
    value['agents'][0]['question_state'][field] = invalid
    with pytest.raises(HistoryError):
        validate(value)
