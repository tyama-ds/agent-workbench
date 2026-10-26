"""Actual Engine board receipts consumed by production UI; no real provider."""
import json

import pytest

from test_engine import ScriptClient, configured, start
from test_frontend import APP, run_javascript
from test_run_action_frontend import ACTION_DOM


@pytest.mark.asyncio
async def test_pm_two_workers_and_human_share_actual_feed_in_production_ui(tmp_path, monkeypatch):
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'BRAVE_SEARCH_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    client = ScriptClient([])
    engine, _ = configured(tmp_path, client)
    engine.settings.value['work_board']['enabled'] = True
    engine.kick = lambda agent: None
    secret = 'SYNTHETIC-board-contract-secret'
    try:
        run, pm = await start(engine)
        workers = [engine._new_agent(run, 'local', 'researcher', pm.id,
                                    assignment='Research source ' + str(index))
                   for index in (1, 2)]
        for actor in (pm, *workers):
            actor.pending.clear()
            actor.status = 'working'
        engine.settings.secrets['local'] = secret
        texts = ['Discuss the two source findings',
                 '<script>literal note</script> ' + secret,
                 'Second worker: <img src=x onerror=alert(1)>']
        for index, (actor, body) in enumerate(zip((pm, *workers), texts)):
            args = {'body': body}
            if index:
                args['reply_to'] = 1
            accepted = await engine.execute_tool(run, actor, 'post_work_board', args)
            assert accepted['post']['author_id'] == actor.id
        engine.post_work_board(run['id'], 'Please distinguish targets from results',
                               reply_to=2, client_post_id='human-board-contract-0001')
        first_feed = engine.read_work_board(run['id'], limit=50)
        snapshot = engine.selected_snapshot(run_id=run['id'], agent_id=pm.id)
        assert snapshot['runs'][0]['work_board']['post_count'] == 4
        human_body = 'Keep both sources in the final comparison'
        receipt = engine.post_work_board(run['id'], human_body, reply_to=3,
                                         client_post_id='human-board-contract-0002')
        last_feed = engine.read_work_board(run['id'], after_seq=4, limit=50)
        for actor in (pm, *workers):
            actual_read = await engine.execute_tool(run, actor, 'read_work_board', {'after_seq': 4})
            assert actual_read['posts'] == last_feed['posts']
            assert not actor.pending and not actor.worker_report_consumed
        assert not client.calls and run['auto_collaborations'] == 3
        assert all(actor.status == 'working' for actor in (pm, *workers))
        public = json.dumps({'snapshot': snapshot, 'first': first_feed,
                             'last': last_feed, 'receipt': receipt}, ensure_ascii=False)
        assert secret not in public and '[redacted]' in public
        assert '_work_board_posts' not in public
        javascript = ACTION_DOM + APP + '\nconst payload=' + public + ';\n' + r'''
const crypto=require('node:crypto').webcrypto;
(async()=>{
  function textTree(node){return [node.textContent,...node.children.map(textTree)].join('\n');}
  const run=payload.snapshot.runs[0], requests=[];
  ui.state=payload.snapshot;ui.selectedRun=run.id;ui.selectedAgent=run.pm_agent_ids[0];
  ui.cockpitView='board';ui.boardRedactionRevision=payload.snapshot.redaction_revision;
  api=async(path,options={})=>{
    requests.push({path,options});
    const url=new URL(path,'http://fixture.test');
    assert.equal(url.pathname,`/api/runs/${run.id}/work-board`);
    if(options.method==='POST'){
      assert.equal(options.body.body,'Keep both sources in the final comparison');
      assert.equal(options.body.reply_to,3);
      assert.match(options.body.client_post_id,/^[A-Za-z0-9_-]{16,128}$/);
      return payload.receipt;
    }
    assert.equal(url.searchParams.get('limit'),'50');
    const cursor=Number(url.searchParams.get('after_seq'));
    assert([0,4,5].includes(cursor));
    return cursor===0?payload.first:cursor===4?payload.last:{...payload.last,posts:[],next_after_seq:5};
  };
  renderWorkBoard(run);await loadWorkBoard(run);
  const board=workBoardState(run.id), feed=$('workBoardFeed');
  assert.equal(board.posts.size,4);assert.equal(feed.children.length,4);
  assert.equal(feed.children.filter(row=>row.className.includes('human')).length,1);
  assert.equal(feed.children.filter(row=>row.className.includes('agent')).length,3);
  assert.equal(board.nodes.get(1).avatar.textContent,'PM');
  assert.equal(board.nodes.get(2).avatar.textContent,'W');
  assert.equal(board.nodes.get(3).avatar.textContent,'W');
  assert(textTree(feed).includes('<script>literal note</script> [redacted]'));
  assert(textTree(feed).includes('<img src=x onerror=alert(1)>'));
  assert(!feed.querySelectorAll('*').some(node=>['SCRIPT','IMG'].includes(node.tagName)));
  assert(board.nodes.get(4).quote.textContent.includes('[redacted]'));
  board.nodes.get(3).reply.listeners.click();
  assert.equal(board.draft.reply_to,3);
  assert($('workBoardReplyBody').textContent.includes('Second worker:'));
  $('workBoardInput').value='Keep both sources in the final comparison';saveWorkBoardDraft({type:'input'});
  await submitWorkBoardPost();await loadWorkBoard(run);
  assert.equal(requests.filter(request=>request.options.method==='POST').length,1);
  assert.equal(board.posts.size,5);assert.equal(feed.children.length,5);
  assert.equal(board.nodes.get(5).avatar.textContent,'YOU');
  assert.equal(board.draft.body,'');assert.equal(board.draft.reply_to,null);
  assert.equal($('workBoardInput').value,'');
  assert(textTree(feed).includes('Keep both sources in the final comparison'));
  assert($('workBoardStatus').textContent.includes('閲覧・理解は未確認'));
  assert(!requests.some(request=>/message|answer|finish|provider/.test(request.path)));
  console.log(JSON.stringify({ok:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        assert run_javascript(javascript) == {'ok': True}
    finally:
        await engine.close()
