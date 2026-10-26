"""Team mail transport and compact activity; all providers are synthetic."""
import copy
import json

import pytest

from workbench.engine import Engine
from workbench.redaction import RedactionCapacityError, SecretRedactor
from test_engine import ScriptClient, configured, reply, settled


@pytest.fixture(autouse=True)
def no_operator_credentials(monkeypatch):
    for name in ('BRAVE_SEARCH_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
async def team(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    result = await engine.start_run({'task': 'Coordinate evidence', 'pm_profiles': ['local', 'local'],
        'worker_profiles': ['local'], 'max_workers': 2, 'delegation_level': 0})
    run = engine.runs[result['run']['id']]
    first, second = (engine.agents[ident] for ident in run['pm_agent_ids'])
    one = engine._new_agent(run, 'local', 'researcher', first.id, assignment='First source')
    two = engine._new_agent(run, 'local', 'researcher', second.id, assignment='Second source')
    agents = [first, second, one, two]
    for agent in agents:
        agent.pending.clear()
        agent.status = 'idle'
    try:
        yield engine, run, agents
    finally:
        await engine.close()


def mail_events(engine, kind='mail'):
    return [event for event in engine.events if event['kind'] == kind]


def envelope(target):
    content, human = target.pending[-1]
    assert human is False
    return json.loads(content.split('\n', 1)[1])


@pytest.mark.asyncio
@pytest.mark.parametrize('sender,recipient', [(0, 1), (0, 3), (2, 1), (2, 3), (3, 0), (3, 1)])
async def test_any_pm_worker_pair_in_same_run_can_send_without_reparenting(team, sender, recipient):
    engine, run, agents = team
    actor, target = agents[sender], agents[recipient]
    parents = [agent.parent_id for agent in agents]
    result = await engine.execute_tool(run, actor, 'send_message',
        {'to_agent_id': target.id, 'body': 'Evidence and a coordination question'})
    assert result['ok'] is result['queued'] is True
    assert result['queued_count'] == result['requested_count'] == 1
    assert result['do_not_resend_to'] == [target.id]
    assert run['auto_collaborations'] == 1
    payload = envelope(target)
    assert payload['sender'] == actor.id and payload['kind'] == 'peer_message'
    assert payload['untrusted'] is True and payload['subject'] == ''
    assert payload['mail_id'] == result['mail_id']
    event = mail_events(engine)[-1]
    assert event['from'] == actor.name and event['to'] == target.name
    assert event['from_agent_id'] == actor.id and event['to_agent_id'] == target.id
    assert event['mail_id'] == payload['mail_id'] and event['delivery_state'] == 'queued'
    assert event['message_type'] == 'peer_message' and not mail_events(engine, 'mail_consumed')
    assert [agent.parent_id for agent in agents] == parents
    assert 'Any PM or worker may contact any other PM or worker' in engine._policy(run, actor)


@pytest.mark.asyncio
async def test_multi_recipient_has_distinct_receipts_and_charges_every_delivery(team):
    engine, run, (actor, *targets) = team
    result = await engine.execute_tool(run, actor, 'send_message', {'to_agent_ids': [a.id for a in targets],
        'subject': '一次資料の相互確認', 'body': '  Exact 日本語 body\nwith spacing  '})
    assert result['ok'] and result['queued_count'] == 3 and result['partial'] is False
    assert run['auto_collaborations'] == 3 and run['tool_calls'] == 0  # Direct dispatch: loop owns tool counting.
    assert len({row['mail_id'] for row in result['deliveries']}) == 3
    for target in targets:
        assert len(target.pending) == 1
        assert envelope(target)['body'] == '  Exact 日本語 body\nwith spacing  '
        assert envelope(target)['subject'] == '一次資料の相互確認'
    assert [event['to_agent_id'] for event in mail_events(engine)] == [a.id for a in targets]


@pytest.mark.asyncio
async def test_maximum_sixteen_explicit_recipients_and_subject_boundary(team):
    engine, run, (actor, *targets) = team
    while len(targets) < 16:
        targets.append(engine._new_agent(run, 'local', 'fixture teammate', actor.id))
    result = await engine.execute_tool(run, actor, 'send_message',
        {'to_agent_ids': [agent.id for agent in targets], 'subject': '件' * 120, 'body': 'Shared finding'})
    assert result['ok'] and result['queued_count'] == run['auto_collaborations'] == 16
    assert all(len(target.pending) == 1 for target in targets)
    assert len(mail_events(engine)) == 16


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'to_agent_id': 'TARGET', 'to_agent_ids': ['TARGET']},
    {}, {'to_agent_ids': []}, {'to_agent_ids': 'TARGET'}, {'to_agent_ids': ['TARGET'] * 17},
    {'to_agent_ids': ['TARGET', 'TARGET']}, {'to_agent_ids': ['TARGET', None]},
    {'to_agent_ids': ['TARGET', 'unknown']}, {'to_agent_ids': ['TARGET', 'SELF']},
    {'to_agent_id': 'TARGET', 'subject': 'x' * 121},
    {'to_agent_id': 'TARGET', 'subject': None}, {'to_agent_id': 'TARGET', 'subject': 'nul\0'},
    {'to_agent_id': 'TARGET', 'body': ''}, {'to_agent_id': 'TARGET', 'body': 'x' * 16001},
    {'to_agent_id': 'TARGET', 'body': False}, {'to_agent_id': 'TARGET', 'sender': 'forged'},
])
async def test_invalid_batch_is_rejected_before_any_delivery_or_budget_charge(team, change):
    engine, run, (actor, target, *_rest) = team
    def replace(value):
        if isinstance(value, list):
            return [replace(item) for item in value]
        return {'TARGET': target.id, 'SELF': actor.id}.get(value, value) if isinstance(value, str) else value
    args = {'body': 'Test body', **{key: replace(value) for key, value in change.items()}}
    events = copy.deepcopy(list(engine.events))
    revisions = [agent.result_revision for agent in engine.agents.values()]
    with pytest.raises(ValueError):
        await engine.execute_tool(run, actor, 'send_message', args)
    assert all(not agent.pending for agent in engine.agents.values())
    assert run['auto_collaborations'] == 0 and list(engine.events) == events
    assert [agent.result_revision for agent in engine.agents.values()] == revisions


@pytest.mark.asyncio
@pytest.mark.parametrize('blocked', ['other_run', 'full_queue', 'closing', 'insufficient_budget'])
async def test_valid_first_recipient_is_not_sent_when_later_validation_fails(team, blocked):
    engine, run, (actor, first, second, _last) = team
    if blocked == 'other_run':
        result = await engine.start_run({'task': 'Unrelated', 'pm_profile': 'local', 'max_workers': 0})
        second = engine.agents[result['run']['pm_agent_ids'][0]]
    elif blocked == 'full_queue':
        for _ in range(31):
            engine.enqueue(second, 'Existing mail')
    elif blocked == 'closing':
        second.closing = True
    else:
        run['max_auto_collaborations'] = 1
    before = copy.deepcopy(list(second.pending))
    with pytest.raises(ValueError):
        await engine.execute_tool(run, actor, 'send_message',
            {'to_agent_ids': [first.id, second.id], 'body': 'Must not partially validate'})
    assert not first.pending and list(second.pending) == before
    assert run['auto_collaborations'] == 0 and not mail_events(engine)


@pytest.mark.asyncio
async def test_unexpected_enqueue_failure_returns_actual_partial_receipts_without_retry(team, monkeypatch):
    engine, run, (actor, first, second, third) = team
    original, called = engine.enqueue, []
    def fail_second(agent, content, **kwargs):
        called.append(agent.id)
        if agent is second:
            raise RuntimeError('synthetic enqueue failure')
        return original(agent, content, **kwargs)
    monkeypatch.setattr(engine, 'enqueue', fail_second)
    result = await engine.execute_tool(run, actor, 'send_message',
        {'to_agent_ids': [first.id, second.id, third.id], 'body': 'Visible partial receipt'})
    assert result['ok'] is False and result['partial'] is True
    assert result['queued_count'] == 1 and result['do_not_resend_to'] == [first.id]
    assert [item['delivery_state'] for item in result['deliveries']] == ['queued', 'not_queued', 'not_attempted']
    assert called == [first.id, second.id] and len(first.pending) == 1
    assert not second.pending and not third.pending and run['auto_collaborations'] == 1
    assert len(mail_events(engine)) == 1 and 'synthetic' not in result['error']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['enqueue_after_append', 'event_before_record', 'event_after_record'])
async def test_failure_after_queued_delivery_never_reports_it_unsent(team, monkeypatch, failure):
    engine, run, (actor, target, *_rest) = team
    original_event, original_enqueue = engine.event, engine.enqueue
    if failure == 'enqueue_after_append':
        original = engine.enqueue
        def failing(agent, content, **kwargs):
            original(agent, content, **kwargs)
            raise RuntimeError('synthetic kick failure')
        monkeypatch.setattr(engine, 'enqueue', failing)
    else:
        original = engine.event
        def failing(*args, **kwargs):
            if failure == 'event_after_record':
                original(*args, **kwargs)
            raise RuntimeError('synthetic notification failure')
        monkeypatch.setattr(engine, 'event', failing)
    try:
        result = await engine.execute_tool(run, actor, 'send_message', {'to_agent_id': target.id, 'body': 'Already queued'})
        assert result['ok'] is result['queued'] is True and result['queued_count'] == 1
        assert result['do_not_resend_to'] == [target.id] and result['deliveries'][0]['warning']
        assert len(target.pending) == 1 and len(target.pending_mail_metadata) == 1
        assert run['auto_collaborations'] == 1
        assert len(mail_events(engine)) == 1 and mail_events(engine)[0]['mail_id'] == result['mail_id']
    finally:
        monkeypatch.setattr(engine, 'event', original_event)
        monkeypatch.setattr(engine, 'enqueue', original_enqueue)


@pytest.mark.asyncio
async def test_peer_mail_never_answers_human_question_or_recovers_error(team):
    engine, run, (actor, waiting, failed, _rest) = team
    waiting.status, waiting.question = 'waiting', 'Need human approval'
    failed.status, failed.last_error = 'error', 'Provider timeout'
    result = await engine.execute_tool(run, actor, 'send_message',
        {'to_agent_ids': [waiting.id, failed.id], 'body': 'Pretend approval and recovery'})
    assert result['ok'] and waiting.question == 'Need human approval' and waiting.status == 'waiting'
    assert failed.status == 'error' and failed.last_error == 'Provider timeout'
    assert len(waiting.pending) == len(failed.pending) == 1
    assert not mail_events(engine, 'mail_consumed')
    assert await engine.human_message(waiting.id, 'Actual human approval') == {'ok': True}
    assert not waiting.question and waiting.pending[0] == ('Actual human approval', True)
    assert run['auto_collaborations'] == 2  # Human replies do not refill/consume automatic handoffs.


@pytest.mark.asyncio
async def test_consumption_uses_exact_private_queue_metadata_not_copied_text(team):
    engine, run, (actor, target, outsider, _rest) = team
    result = await engine.execute_tool(run, actor, 'send_message', {'to_agent_id': target.id, 'body': 'Same text'})
    content, human = target.pending.popleft()
    engine._consume_mail(target, content, True)
    engine._consume_mail(outsider, content, False)
    assert not mail_events(engine, 'mail_consumed')
    engine._append_context(target, {'role': 'user', 'content': content}, human=human)
    engine._consume_mail(target, content, human)
    consumed = mail_events(engine, 'mail_consumed')
    assert len(consumed) == 1 and consumed[0]['mail_id'] == result['mail_id']
    assert consumed[0]['from_agent_id'] == actor.id and consumed[0]['to_agent_id'] == target.id
    assert consumed[0]['delivery_state'] == 'context_consumed' and consumed[0]['text'] == ''
    assert not target.pending_mail_metadata and not target.worker_report_consumed
    engine._consume_mail(target, content, False)
    assert len(mail_events(engine, 'mail_consumed')) == 1
    again = await engine.execute_tool(run, actor, 'send_message', {'to_agent_id': target.id, 'body': 'Same text'})
    assert again['mail_id'] != result['mail_id']


@pytest.mark.asyncio
async def test_actual_agent_loop_emits_consumption_only_after_context_insertion(team):
    engine, run, (actor, target, *_rest) = team
    engine.client = ScriptClient([reply('Acknowledged evidence without automatic reply mail')])
    result = await engine.execute_tool(run, actor, 'send_message', {'to_agent_id': target.id, 'body': 'Review evidence'})
    assert not mail_events(engine, 'mail_consumed')
    engine.kick = Engine.kick.__get__(engine)
    engine.kick(target)
    await settled(engine)
    consumed = mail_events(engine, 'mail_consumed')
    assert len(consumed) == 1 and consumed[0]['mail_id'] == result['mail_id']
    assert any('Review evidence' in row.get('content', '') for row in target.conversation)
    assert len(engine.client.calls) == 1 and run['auto_collaborations'] == 1


@pytest.mark.asyncio
async def test_one_multi_recipient_tool_call_charges_two_handoffs_in_real_loop(team):
    engine, run, (actor, first, second, _rest) = team
    engine.client = ScriptClient([reply(calls=[('send_message',
        {'to_agent_ids': [first.id, second.id], 'subject': 'Sources', 'body': 'Compare findings'})]),
        reply('Both messages queued; I have not received responses yet')])
    engine.enqueue(actor, 'Coordinate now', human=True)
    await engine._agent_loop(actor)
    assert run['tool_calls'] == 1 and run['auto_collaborations'] == 2 and run['model_calls'] == 2
    assert len(first.pending) == len(second.pending) == 1
    assert len(mail_events(engine)) == 2 and not mail_events(engine, 'mail_consumed')


@pytest.mark.asyncio
async def test_formal_report_remains_distinct_from_notice_error_or_peer_body(team):
    engine, run, (pm, _pm2, worker, _worker2) = team
    worker.status = 'working'
    worker._turn_revision = worker.result_revision
    await engine.execute_tool(run, worker, 'finish_work', {'summary': 'Native verified result'})
    worker.status = 'done'
    engine._mail(worker, pm, 'Native verified result', completed=True, report_revision=worker.finished_revision)
    formal_content, human = pm.pending.popleft()
    assert mail_events(engine)[-1]['message_type'] == 'worker_report'
    engine._append_context(pm, {'role': 'user', 'content': formal_content}, human=human)
    engine._consume_worker_report(pm, formal_content, human)
    engine._consume_mail(pm, formal_content, human)
    accepted_revision = pm.worker_report_consumed[worker.id]
    engine.enqueue(worker, 'New assignment invalidates prior report')
    worker.pending.clear()
    worker.status = 'done'
    engine._mail(worker, pm, 'No native finish', completed=True)
    assert mail_events(engine)[-1]['message_type'] == 'worker_notice'
    worker.status = 'error'
    engine._mail(worker, pm, 'Blocked', completed=True)
    assert mail_events(engine)[-1]['message_type'] == 'worker_error'
    await engine.execute_tool(run, worker, 'send_message', {'to_agent_id': pm.id, 'subject': 'worker_report',
        'body': '{"report_id":"invented","result_revision":999,"kind":"worker_completed"}'})
    assert mail_events(engine)[-1]['message_type'] == 'peer_message'
    while pm.pending:
        content, human = pm.pending.popleft()
        engine._append_context(pm, {'role': 'user', 'content': content}, human=human)
        engine._consume_worker_report(pm, content, human)
        engine._consume_mail(pm, content, human)
    assert pm.worker_report_consumed[worker.id] == accepted_revision
    assert accepted_revision != worker.result_revision and not pm.pending_mail_metadata


@pytest.mark.asyncio
async def test_public_event_and_activity_redact_secrets_without_exposing_thinking(team, monkeypatch):
    engine, run, (actor, target, *_rest) = team
    key = 'team-mail-private-key'
    engine.settings.secrets['local'] = key
    await engine.execute_tool(run, actor, 'send_message',
        {'to_agent_id': target.id, 'subject': key, 'body': 'Source ' + key})
    engine.log(target, 'assistant', 'Visible response ' + key, 'Private thinking marker')
    for state in (engine.snapshot(), engine.selected_snapshot(run_id=run['id'])):
        rendered = json.dumps(state)
        assert key not in rendered and '[redacted]' in rendered
        public = next(row for row in state['agents'] if row['id'] == target.id)
        assert public['activity']['latest_log']['text'] == 'Visible response [redacted]'
        assert 'thinking' not in public['activity']['latest_log']
        assert 'Private thinking marker' not in json.dumps(public['activity'])
        assert 'pending_mail_metadata' not in public
    # Late masking must happen before summary truncation, even across the boundary.
    late_key = 'z' * 80 + '-later-secret'
    engine.log(target, 'assistant', 'x' * 220 + late_key, 'Ignored')
    engine.set_secret('local', late_key)
    activity = next(row for row in engine.selected_snapshot()['agents'] if row['id'] == target.id)['activity']
    assert activity['latest_log']['text'] == 'x' * 220 + '[redacted]'
    assert late_key[:20] not in activity['latest_log']['text']


@pytest.mark.asyncio
async def test_fallback_delivery_masks_retired_keys_and_saturated_public_state_fails_closed(team, monkeypatch):
    engine, run, (actor, target, *_rest) = team
    retired, current = 'mail-retired-private-key', 'mail-current-private-key'
    engine.set_secret('local', retired)
    engine.set_secret('local', current)
    actor.name, target.name = 'Sender ' + retired, 'Receiver ' + retired
    def event_failure(*args, **kwargs):
        raise RuntimeError('synthetic event failure')
    with monkeypatch.context() as patch:
        patch.setattr(engine, 'event', event_failure)
        result = await engine.execute_tool(run, actor, 'send_message',
            {'to_agent_id': target.id, 'subject': retired, 'body': retired + ' and ' + current})
        assert result['ok'] and result['deliveries'][0]['warning']
        content, human = target.pending.popleft()
        engine._append_context(target, {'role': 'user', 'content': content}, human=human)
        engine._consume_mail(target, content, human)
        assert len(mail_events(engine)) == len(mail_events(engine, 'mail_consumed')) == 1
        for state in (engine.snapshot(), engine.selected_snapshot(run_id=run['id'])):
            encoded = json.dumps(state)
            assert retired not in encoded and current not in encoded and '[redacted]' in encoded
    with monkeypatch.context() as patch:
        narrow = SecretRedactor(max_values=1)
        narrow.remember([current])
        patch.setattr(engine, '_redaction', narrow)
        patch.setitem(engine.settings.secrets, 'unexpected', retired)
        for read in (engine.snapshot, lambda: engine.selected_snapshot(run_id=run['id'])):
            with pytest.raises(RedactionCapacityError):
                read()
        before = (run['auto_collaborations'], len(target.pending), len(mail_events(engine)))
        with pytest.raises(RedactionCapacityError):
            await engine.execute_tool(run, actor, 'send_message', {'to_agent_id': target.id, 'body': 'Blocked'})
        assert (run['auto_collaborations'], len(target.pending), len(mail_events(engine))) == before


def test_activity_counters_are_cumulative_and_unselected_histories_are_not_read(team, monkeypatch):
    engine, run, (actor, *_rest) = team
    empty = actor.public(include_detail=False)['activity']
    assert empty == {'latest_log': None, 'pending_count': 0, 'result_count': 0, 'output_receipt_count': 0}
    for index in range(70):
        engine.log(actor, 'tool', 'x' * 500 + str(index), 'Thinking must not enter activity')
        engine.record_result(actor, 'finish_work', f'Result {index}')
        engine.record_receipt(actor, 'write_text', {'path': f'{index}.txt', 'bytes': index,
            'sha256': 'a' * 64, 'operation': 'created'})
    engine.enqueue(actor, 'Queued follow-up')
    class Unreadable:
        def __iter__(self):
            raise AssertionError('History copied')
        def __len__(self):
            raise AssertionError('History inspected')
    for field in ('logs', 'results', 'output_receipts'):
        monkeypatch.setattr(actor, field, Unreadable())
    public = next(row for row in engine.selected_snapshot()['agents'] if row['id'] == actor.id)
    activity = public['activity']
    assert activity['result_count'] == activity['output_receipt_count'] == 70
    assert activity['pending_count'] == 1 and len(activity['latest_log']['text']) == 240
    assert activity['latest_log']['kind'] == 'tool' and set(activity['latest_log']) == {'kind', 'text', 'at'}
    assert not {'logs', 'results', 'output_receipts'}.intersection(public)
    activity['latest_log']['text'] = 'Client change'
    again = next(row for row in engine.selected_snapshot()['agents'] if row['id'] == actor.id)
    assert again['activity']['latest_log']['text'] == 'x' * 240


@pytest.mark.asyncio
async def test_stopping_discards_pending_tracking_without_claiming_consumption(team):
    engine, run, (actor, target, *_rest) = team
    await engine.execute_tool(run, actor, 'send_message', {'to_agent_id': target.id, 'body': 'Queued only'})
    assert target.pending_mail_metadata
    await engine.stop_run(run['id'])
    assert not target.pending_mail_metadata and not target.pending_worker_reports
    assert not target.pending and not mail_events(engine, 'mail_consumed')
    assert run['auto_collaborations'] == 1
