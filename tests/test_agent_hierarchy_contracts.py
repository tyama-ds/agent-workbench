"""Depth settings, HTTP admission and non-executable hierarchy archives."""
import copy
import json

import pytest

from test_history_persistence import document
from test_session_transitions import session
from workbench.config import DEFAULT, Settings, validate_settings
from workbench.history import HistoryError, HistoryStore, archived_view, redact_document, validate
from workbench.redaction import SecretRedactor


@pytest.mark.parametrize('value', [True, False, None, 0, 4, 1.5, '3'])
def test_depth_setting_is_a_bounded_integer(value):
    with pytest.raises(ValueError):
        validate_settings({'orchestration': {'max_delegation_depth': value}})


@pytest.mark.parametrize('old', [None, {'delegation_level': 0, 'workers_per_pm': 1}])
def test_old_saved_settings_gain_depth_in_memory_without_rewriting_file(tmp_path, monkeypatch, old):
    for key in ('BRAVE_SEARCH_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    raw = copy.deepcopy(DEFAULT)
    if old is None:
        raw.pop('orchestration')
    else:
        raw['orchestration'] = old
    directory = tmp_path / 'settings'
    directory.mkdir()
    path = directory / 'settings.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    before = path.read_bytes()
    settings = Settings(directory)
    assert settings.value['orchestration']['max_delegation_depth'] == 3
    assert path.read_bytes() == before
    if old:
        assert all(settings.value['orchestration'][key] == value for key, value in old.items())


async def test_http_preflight_caps_run_depth_without_changing_saved_settings(tmp_path):
    async with session(tmp_path) as case:
        config = copy.deepcopy(case.engine.settings.value)
        config['orchestration']['max_delegation_depth'] = 2
        revision = case.engine.settings.revision
        await case.api('put', '/api/config', {'config_revision': revision, 'config': config})
        original = copy.deepcopy(case.engine.settings.value)
        payload = {'task': 'Small bounded team', 'pm_profile': 'local', 'worker_profiles': ['local'],
                   'max_workers': 3, 'max_delegation_depth': 1}
        preview = await case.api('post', '/api/run-preflight', payload)
        assert preview['can_start'] and preview['orchestration']['max_delegation_depth'] == 1
        payload['max_delegation_depth'] = 3
        denied = await case.api('post', '/api/run-preflight', payload)
        assert not denied['can_start']
        assert case.engine.settings.value == original
        assert not case.engine.runs and not case.engine.agents and not case.provider.history


def hierarchy_document():
    value = document()
    root = value['agents'][0]
    ids = [root['id'], 'a-' + '3' * 16, 'a-' + '4' * 16, 'a-' + '5' * 16]
    value['run'].update(agent_ids=ids, max_delegation_depth=3)
    for index in range(1, 4):
        child = copy.deepcopy(root)
        child.update(id=ids[index], parent_id=ids[index - 1], name='Author a', role='pm')
        value['agents'].append(child)
    for index, agent in enumerate(value['agents']):
        agent['hierarchy'] = {'depth': index, 'root_pm_id': ids[0],
                              'unit_id': ids[max(0, index - 1)],
                              'direct_children': ids[index + 1:index + 2], 'can_delegate': index < 3}
    return value


def test_hierarchy_archive_keeps_linkage_but_never_resumes_delegation(tmp_path):
    value = hierarchy_document()
    redactor = SecretRedactor()
    redactor.remember(['a'])
    scrubbed = redact_document(value, redactor.redact)
    assert [a['hierarchy'] for a in scrubbed['agents']] == [a['hierarchy'] for a in value['agents']]
    assert scrubbed['agents'][1]['name'] != value['agents'][1]['name']
    store = HistoryStore(tmp_path / 'history')
    try:
        store.save(value, redactor.redact)
        saved, at = store.read(value['run']['id'], redactor.redact)
        view = archived_view(saved, at)
        assert len(view['agents']) == 4
        assert all(a['read_only'] and not a['hierarchy']['can_delegate'] for a in view['agents'])
        assert all(not a['message_eligibility']['allowed'] for a in view['agents'])
        assert saved['agents'][0]['hierarchy']['can_delegate']
    finally:
        store.close()


@pytest.mark.parametrize('bad', ['cycle', 'missing_parent', 'wrong_depth', 'wrong_root', 'wrong_unit',
                               'wrong_children', 'depth_bool', 'cap_bool', 'cap_too_small', 'leaf_delegate'])
def test_archive_rejects_forged_or_inconsistent_hierarchy(bad):
    value = hierarchy_document()
    rows = value['agents']
    if bad == 'cycle':
        rows[1]['parent_id'] = rows[2]['id']
    elif bad == 'missing_parent':
        rows[2]['parent_id'] = 'a-' + 'f' * 16
    elif bad == 'wrong_depth':
        rows[2]['hierarchy']['depth'] = 1
    elif bad == 'wrong_root':
        rows[2]['hierarchy']['root_pm_id'] = rows[1]['id']
    elif bad == 'wrong_unit':
        rows[2]['hierarchy']['unit_id'] = rows[0]['id']
    elif bad == 'wrong_children':
        rows[1]['hierarchy']['direct_children'].append(rows[3]['id'])
    elif bad == 'depth_bool':
        rows[0]['hierarchy']['depth'] = False
    elif bad == 'cap_bool':
        value['run']['max_delegation_depth'] = True
    elif bad == 'cap_too_small':
        value['run']['max_delegation_depth'] = 2
    else:
        rows[3]['hierarchy']['can_delegate'] = True
    with pytest.raises(HistoryError):
        validate(value)


def test_legacy_archive_remains_display_only_without_invented_hierarchy():
    value = document()
    validate(value)
    restored = archived_view(value, 12)
    assert 'hierarchy' not in restored['agents'][0]
    assert restored['agents'][0]['read_only']


def test_legacy_interrupted_root_registration_remains_read_only():
    # Older versions could persist the root before registering pm_agent_ids.
    value = document()
    value['run']['pm_agent_ids'] = []
    validate(value)
    restored = archived_view(value, 12)
    assert restored['agents'][0]['read_only']
    assert not restored['agents'][0]['message_eligibility']['allowed']
    assert 'hierarchy' not in restored['agents'][0]


def test_new_hierarchy_archive_requires_registered_root():
    value = hierarchy_document()
    value['run']['pm_agent_ids'] = []
    with pytest.raises(HistoryError):
        validate(value)
