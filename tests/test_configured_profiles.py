"""Historical configured identity, not a claim about the model a server executed."""
import json
import copy

import pytest

from test_engine import ScriptClient, configured, start
from test_compact_frontend import DOM
from test_frontend import APP, run_javascript


def projected(engine, run, agent):
    full = next(a for a in engine.snapshot()['agents'] if a['id'] == agent.id)
    compact = next(a for a in engine.selected_snapshot(run_id=run['id'], agent_id=agent.id)['agents'] if a['id'] == agent.id)
    summary = next(a for a in engine.selected_snapshot()['agents'] if a['id'] == agent.id)
    assert full['configured_profile'] == compact['configured_profile'] == summary['configured_profile']
    assert 'logs' not in summary
    return full['configured_profile']


async def test_run_identity_survives_reused_renamed_disabled_and_removed_profile(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        profile = engine.settings.value['providers'][0]
        profile.update(label='Original provider', model='original-model')
        original = {key: profile[key] for key in ('id', 'label', 'kind', 'model')}
        run, pm = await start(engine)
        pm.pending.clear(); pm.status = 'done'; run['status'] = 'done'
        profile.update(label='Renamed provider', model='new-model')
        run2, pm2 = await start(engine)
        assert projected(engine, run, pm) == original
        assert projected(engine, run2, pm2)['model'] == 'new-model'
        profile['enabled'] = False
        assert projected(engine, run, pm) == original
        engine.settings.value['providers'] = engine.settings.value['providers'][1:]
        assert projected(engine, run, pm) == original
        assert projected(engine, run2, pm2)['model'] == 'new-model'
        assert engine.message_eligibility(pm)['reason'] == 'settings_changed'
        with pytest.raises(ValueError, match='設定が変更'):
            await engine.human_message(pm.id, 'Must not resume with current settings')
        value = projected(engine, run, pm)
        value['model'] = 'Modified public copy'
        assert projected(engine, run, pm) == original
    finally:
        await engine.close()


async def test_mixed_team_descriptors_are_per_profile_and_only_allowlisted(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        for profile in engine.settings.value['providers']:
            profile['model'] = profile['id'] + '-configured-model'
            engine.settings.secrets[profile['id']] = 'secret-' + profile['id']
        run, pm = await start(engine, worker_profiles=['openai', 'anthropic'])
        workers = []
        for ident in ('openai', 'anthropic'):
            response = await engine.execute_tool(run, pm, 'spawn_worker', {'role': 'review', 'task': 'Review', 'profile_id': ident})
            workers.append(engine.agents[response['agent_id']])
        for agent in [pm, *workers]:
            descriptor = projected(engine, run, agent)
            assert set(descriptor) == {'id', 'label', 'kind', 'model'}
            assert descriptor['id'] == agent.profile_id
            assert descriptor['model'] == agent.profile_id + '-configured-model'
            assert descriptor['kind'] == agent.profile_id
        state = engine.snapshot()
        assert all(not key.startswith('_') for run in state['runs'] for key in run)
        assert all('base_url' not in a['configured_profile'] and 'api_key_env' not in a['configured_profile'] for a in state['agents'])
    finally:
        await engine.close()


async def test_capture_redaction_survives_deleted_env_reference_and_late_worker(tmp_path, monkeypatch):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    monkeypatch.setenv('CYCLE7_TEST_KEY', 'synthetic-old-env-secret')
    try:
        profile = engine.settings.value['providers'][0]
        profile.update(api_key_env='CYCLE7_TEST_KEY', label='Original synthetic-old-env-secret', model='model-synthetic-old-env-secret')
        run, pm = await start(engine)
        expected = {'id': 'local', 'label': 'Original [redacted]', 'kind': 'local', 'model': 'model-[redacted]'}
        assert projected(engine, run, pm) == expected
        # The private request configuration is not changed by public redaction.
        assert run['_config']['providers'][0]['model'] == 'model-synthetic-old-env-secret'
        profile.update(api_key_env='', label='Current', model='Current')
        monkeypatch.delenv('CYCLE7_TEST_KEY')
        engine.settings.value['providers'] = engine.settings.value['providers'][1:]
        assert projected(engine, run, pm) == expected
        worker = engine._new_agent(run, 'local', 'late worker', pm.id)
        assert projected(engine, run, worker) == expected
        for state in (engine.snapshot(), engine.selected_snapshot(run_id=run['id'], agent_id=worker.id)):
            encoded = json.dumps(state)
            assert 'synthetic-old-env-secret' not in encoded
            assert 'CYCLE7_TEST_KEY' not in encoded
            assert '_configured_profiles' not in encoded
    finally:
        await engine.close()


async def test_missing_historical_descriptor_never_uses_current_config(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine)
        del run['_configured_profiles']
        assert projected(engine, run, pm) is None
        run['_configured_profiles'] = {'different-profile': {'model': 'wrong'}}
        assert projected(engine, run, pm) is None
    finally:
        await engine.close()


async def test_optional_saved_label_and_missing_model_keep_preflight_start_contract(tmp_path):
    engine, _ = configured(tmp_path, ScriptClient([]))
    engine.kick = lambda agent: None
    try:
        value = copy.deepcopy(engine.settings.value)
        del value['providers'][0]['label']
        engine.settings.save(value)
        assert engine.settings.value['providers'][0]['label'] == ''
        payload = {'task': 'Valid optional label', 'pm_profile': 'local', 'worker_profiles': [], 'max_workers': 0}
        assert engine.preflight(payload)['can_start']
        run, pm = await start(engine, **payload)
        assert projected(engine, run, pm) == {'id': 'local', 'label': '', 'kind': 'local', 'model': 'fixture'}
        del value['providers'][0]['model']
        engine.settings.save(value)
        preview = engine.preflight(payload)
        assert not preview['can_start'] and preview['blockers'][0]['code'] == 'model_missing'
        with pytest.raises(ValueError, match='モデル名'):
            await engine.start_run(payload)
    finally:
        await engine.close()


def test_frontend_identity_and_exports_never_follow_current_settings():
    value = run_javascript(DOM + APP + r"""
ui.config={providers:[{id:'local',label:'Current settings label',model:'current-model'}]};
const original={id:'local',label:'Original <img src=x>\nlabel',kind:'local',model:'old-model\nwith delimiter · test'};
const agent={id:'agent-old',run_id:'run-old',name:'PM\nname',profile_id:'local',configured_profile:original,
  status:'done',turns:1,result_revision:1,logs:[],results:[],output_receipts:[]};
ui.state={runs:[{id:'run-old',task:'Old work',status:'done'}],agents:[agent],events:[],resources:{}};
ui.selectedRun='run-old';ui.selectedAgent='agent-old';renderState();
const card=$('agentCards').children[0],header=$('conversationProfile').textContent;
ui.config.providers[0]={id:'local',label:'Renamed settings',model:'new-model'};renderState();
assert.equal($('agentCards').children[0],card,'Settings edits do not rebuild the old roster');
ui.config.providers=[];renderState();assert.equal($('agentCards').children[0],card);
assert.equal($('conversationProfile').textContent,header);assert.ok(header.includes('old-model'));
assert.ok(header.includes('応答モデル未確認'));
const result={kind:'result',record:{at:1,turn:1,revision:1,source:'assistant_response',text:'Public answer'}};
const receipt={kind:'receipt',record:{at:1,turn:1,path:'saved.txt',bytes:3,sha256:'abc',tool:'write_text',operation:'created'}};
const exports=[exportOutputText(agent,result),exportOutputText(agent,receipt)];
for(const text of exports){
  assert.ok(text.includes('作業 ID: run-old'));assert.ok(text.includes('エージェント ID: agent-old'));
  assert.ok(text.includes('プロファイル ID: local'));
  assert.ok(text.includes('開始時の表示名: '+JSON.stringify(original.label)));
  assert.ok(text.includes('開始時のモデル設定: '+JSON.stringify(original.model)));
  assert.ok(text.includes('接続先が実際に使ったモデルの確認ではありません'));
  assert.ok(!text.includes('new-model'));assert.ok(!text.includes('Current settings'));
}
assert.ok(exports[1].includes('ファイル本体は含みません'));
const other={...agent,id:'agent-new',run_id:'run-new',configured_profile:{...original,label:'New run',model:'new-model'}};
assert.ok(exportOutputText(other,result).includes('作業 ID: run-new'));
assert.ok(exportOutputText(other,result).includes('開始時のモデル設定: "new-model"'));
for(const descriptor of [undefined,null,{},[],{...original,id:'wrong'},{...original,kind:'unknown'},{...original,model:[]}]){
  const unknown={...agent,configured_profile:descriptor};
  assert.equal(configuredProfileLabel(unknown),'開始時の設定情報なし');
  assert.ok(exportOutputText(unknown,result).includes('開始時の設定情報なし'));
}
console.log(JSON.stringify({ok:true}));
""")
    assert value == {'ok': True}
