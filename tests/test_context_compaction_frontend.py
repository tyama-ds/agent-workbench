from test_frontend import APP, HTML, run_javascript


def test_context_controls_and_truthful_status_are_wired():
    prefix = APP[:APP.index('const ACTIVE_STATUSES')]
    result = run_javascript(prefix + "console.log(JSON.stringify({limits:FIELD_GROUPS.limits,profiles:PROFILE_FIELDS,bounds:NUMBER_BOUNDS.limits}));")
    fields = {item[0]: item for item in result['limits']}
    assert fields['auto_compact'][2] == 'checkbox'
    assert fields['context_recent_groups'][2] == 'number'
    assert result['bounds']['context_trigger_percent'] == [50, 90]
    assert result['bounds']['max_history_chars'] == [4000, 4000000]
    profile = next(item for item in result['profiles'] if item[0] == 'context_window_tokens')
    assert profile[3] == 0 and 'UTF-8' in profile[5] and '保証ではありません' in profile[5]
    assert 'id="contextMemoryStatus"' in HTML
    assert "$('contextMemoryStatus').hidden=!memory" in APP
    assert 'memory.history_omitted' in APP and 'memory.compacting' in APP
    assert '要約には情報が抜けることがあります' in APP
    assert 'context_window_tokens:0},index,true,false' in APP


def test_context_status_refreshes_when_logs_are_unchanged_and_on_selection_change():
    from test_compact_frontend import check_behavior
    check_behavior(r"""
seedSelection();
const agent=getAgent();
agent.context_memory={compactions:1,compacting:true,history_records:42,history_omitted:3};
renderConversation(agent);
assert.equal($('contextMemoryStatus').hidden,false);
assert.match($('contextMemoryStatus').textContent,/会話を要約中/);
assert.match($('contextMemoryStatus').textContent,/文脈圧縮 1 回/);
assert.match($('contextMemoryStatus').textContent,/除外 3 件/);
agent.context_memory={compactions:2,compacting:false,history_records:39,history_omitted:7};
renderConversation(agent);
assert.doesNotMatch($('contextMemoryStatus').textContent,/会話を要約中/);
assert.match($('contextMemoryStatus').textContent,/文脈圧縮 2 回/);
assert.match($('contextMemoryStatus').textContent,/除外 7 件/);
renderConversation(null);
assert.equal($('contextMemoryStatus').hidden,true);
assert.equal($('contextMemoryStatus').textContent,'');
""")
