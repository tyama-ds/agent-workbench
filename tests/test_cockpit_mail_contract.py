"""Real Engine public mail snapshots consumed by the production JavaScript.

Providers and the DOM are synthetic. This is a cross-layer data contract, not
native layout, external-provider, or browser CSP acceptance.
"""
import json

import pytest

from workbench.engine import Engine
from test_engine import ScriptClient, configured, reply, settled
from test_frontend import APP, run_javascript
from test_run_action_frontend import ACTION_DOM


@pytest.fixture(autouse=True)
def no_operator_credentials(monkeypatch):
    for name in ('BRAVE_SEARCH_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_engine_selected_mail_snapshot_renders_directions_receipts_and_redaction(tmp_path):
    client = ScriptClient([reply('Reviewed the queued evidence')])
    engine, _ = configured(tmp_path, client)
    engine.kick = lambda agent: None
    secret = 'SYNTHETIC-cockpit-contract-secret'
    try:
        result = await engine.start_run({'task': 'Coordinate public evidence',
            'pm_profiles': ['local', 'local'], 'worker_profiles': ['local'],
            'max_workers': 1, 'delegation_level': 0})
        run = engine.runs[result['run']['id']]
        first, second = [engine.agents[ident] for ident in run['pm_agent_ids']]
        worker = engine._new_agent(run, 'local', 'reader', first.id, assignment='Read queued evidence')
        for agent in (first, second, worker):
            agent.pending.clear()
            agent.status = 'idle'
        engine.settings.secrets['local'] = secret
        plural = await engine.execute_tool(run, first, 'send_message', {
            'to_agent_ids': [worker.id, second.id],
            'subject': '<script>literal subject</script> ' + secret,
            'body': 'Source <img src=x onerror=alert(1)> ' + secret})
        reverse = await engine.execute_tool(run, worker, 'send_message', {
            'to_agent_id': first.id, 'body': 'Question for the PM'})
        assert plural['queued_count'] == 2 and reverse['queued'] is True
        queued = engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)
        delivered_id = plural['deliveries'][0]['mail_id']
        queued_event = next(row for row in queued['events'] if row.get('mail_id') == delivered_id)
        assert queued_event['delivery_state'] == 'queued'
        assert queued_event['message_type'] == 'peer_message'
        assert queued_event['from_agent_id'] == first.id and queued_event['to_agent_id'] == worker.id
        assert not any(row['kind'] == 'mail_consumed' for row in queued['events'])

        # Only this worker's actual agent loop runs. It inserts the queued mail
        # into provider context; automatic notifications do not start another PM.
        real_kick = Engine.kick.__get__(engine)
        engine.kick = lambda agent: real_kick(agent) if agent.id == worker.id else None
        engine.kick(worker)
        await settled(engine)
        assert len(client.calls) == 1
        assert any('Source <img src=x onerror=alert(1)>' in row.get('content', '')
                   for row in client.calls[0])
        consumed = engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)
        receipt = next(row for row in consumed['events']
                       if row.get('mail_id') == delivered_id and row['kind'] == 'mail_consumed')
        assert receipt['delivery_state'] == 'context_consumed' and receipt['text'] == ''
        assert receipt['from_agent_id'] == first.id and receipt['to_agent_id'] == worker.id
        assert receipt['message_type'] == 'peer_message'
        assert not worker.worker_report_consumed
        public = json.dumps({'queued': queued, 'consumed': consumed}, ensure_ascii=False)
        assert secret not in public and '[redacted]' in public
        assert 'pending_mail_metadata' not in public

        # These are the untouched selected_snapshot payloads, not reconstructed
        # graph/event fixtures. Node is resolved by the shared bundled-PATH helper.
        identifiers = json.dumps({'run': run['id'], 'first': first.id,
                                  'second': second.id, 'worker': worker.id,
                                  'delivered': delivered_id})
        dom = ACTION_DOM.replace('this.children=[];this.dataset={};',
                                 'this.children=[];this.style={};this.dataset={};', 1)
        javascript = dom + APP + '\nconst payload=' + public + ';\nconst ids=' + identifiers + r''';
function textTree(node){return [node.textContent,...node.children.map(textTree)].join('\n');}
function useSnapshot(snapshot){
  ui.state=snapshot;ui.selectedRun=ids.run;ui.selectedAgent=ids.worker;
  ui.compactState=true;ui.loadedEventsRun=ids.run;
  ui.activityFilter='pair';ui.activityPair={from:ids.first,to:ids.worker};
  ui.activitySignature=null;
}
useSnapshot(payload.queued);
const agents=ui.state.agents.filter(agent=>agent.run_id===ids.run);
const links=currentMailLinks(agents,retainedTeamEvents(getRun()));
assert.deepEqual(links,[{from:ids.first,to:ids.worker},{from:ids.first,to:ids.second},
                        {from:ids.worker,to:ids.first}]);
renderTeamMap(agents);
assert.equal(ui.networkSvg.children.length,3);
assert(ui.networkSvg.children.every(line=>line.getAttribute('marker-end')==='url(#mailArrow)'));
assert(ui.networkSvg.children.some(line=>line.dataset.focusKey===`mail-line:${JSON.stringify([ids.first,ids.worker])}`));
renderActivity(getRun());
const before=textTree($('activityFeed'));
assert(before.includes('送信キューに受理（記録時点）'));
assert(!before.includes('会話へ取り込み済み'));
assert(before.includes('Question for the PM'));
assert(before.includes('[redacted]'));
assert(before.includes('<script>literal subject</script>'));
assert(!$('activityFeed').querySelectorAll('*').some(node=>['SCRIPT','IMG'].includes(node.tagName)));
assert.equal($('activityFeed').children.length,2);
useSnapshot(payload.consumed);
renderActivity(getRun());
const after=textTree($('activityFeed'));
assert(after.includes('会話へ取り込み済み'));
assert(after.includes('送信キューに受理（記録時点）'));
assert(after.includes('理解・完了の確認ではありません'));
const expected=payload.consumed.events.filter(event=>['mail','mail_consumed'].includes(event.kind)&&
  ((event.from_agent_id===ids.first&&event.to_agent_id===ids.worker)||
   (event.from_agent_id===ids.worker&&event.to_agent_id===ids.first)));
assert.equal($('activityFeed').children.length,expected.length);
assert(payload.consumed.events.some(event=>event.to_agent_id===ids.second));
assert(expected.every(event=>event.to_agent_id!==ids.second&&event.from_agent_id!==ids.second));
const sameReceipt=expected.filter(event=>event.mail_id===ids.delivered);
assert.equal(sameReceipt.length,2);
assert.deepEqual(sameReceipt.map(event=>event.delivery_state),['queued','context_consumed']);
console.log(JSON.stringify({ok:true}));
'''
        assert run_javascript(javascript) == {'ok': True}
    finally:
        await engine.close()
