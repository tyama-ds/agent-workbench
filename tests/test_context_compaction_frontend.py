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
