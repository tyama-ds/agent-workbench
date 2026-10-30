"""Check observed native receipt contracts before starting an owned browser.

No server, model client, browser, or file mutation is created by these checks.
"""
import copy
import hashlib
from types import SimpleNamespace

import pytest

from tools.adaptive_browser_fixture import CONTENT, MANUAL, ScriptedClient, check_file_result
from workbench.config import DEFAULT


CANDIDATE = 'c-' + '1' * 24


def receipt(workspace, kind):
    base = {'path': str(workspace / 'result.txt'),
            'sha256': hashlib.sha256(CONTENT.encode()).hexdigest()}
    if kind == 'write':
        return {**base, 'bytes': len(CONTENT.encode()), 'operation': 'created'}
    value = {**base, 'text': CONTENT, 'truncated': False}
    if kind == 'reviewer':
        value['independent_review_read'] = {
            'candidate_id': CANDIDATE, 'observation_id': 'o-' + '2' * 24,
            'coverage': 'content exposure, not exhaustive verification'}
    return value


@pytest.mark.parametrize('kind', ['write', 'read', 'reviewer'])
def test_native_receipts_do_not_require_generic_ok(tmp_path, kind):
    value = receipt(tmp_path, kind)
    assert 'ok' not in value
    check_file_result('write_text' if kind == 'write' else 'read_text', value, tmp_path,
                      CANDIDATE if kind == 'reviewer' else None)


@pytest.mark.parametrize('kind,change', [
    ('write', 'boolean_bytes'), ('write', 'wrong_operation'),
    ('read', 'truncated'), ('read', 'wrong_path'), ('read', 'wrong_sha'),
    ('read', 'unexpected_marker'), ('read', 'generic_ok'),
    ('reviewer', 'missing_marker'), ('reviewer', 'old_candidate'),
    ('reviewer', 'invalid_observation'), ('reviewer', 'overclaimed_coverage'),
    ('reviewer', 'extra_marker_key'), ('reviewer', 'wrong_content'),
])
def test_fixture_rejects_mismatched_native_evidence(tmp_path, kind, change):
    value = receipt(tmp_path, kind)
    if change == 'boolean_bytes': value['bytes'] = True
    elif change == 'wrong_operation': value['operation'] = 'updated'
    elif change == 'truncated': value['truncated'] = True
    elif change == 'wrong_path': value['path'] = str(tmp_path / 'other.txt')
    elif change == 'wrong_sha': value['sha256'] = '0' * 64
    elif change == 'unexpected_marker': value['independent_review_read'] = receipt(tmp_path, 'reviewer')['independent_review_read']
    elif change == 'generic_ok': value['ok'] = True
    elif change == 'missing_marker': value.pop('independent_review_read')
    elif change == 'old_candidate': value['independent_review_read']['candidate_id'] = 'c-' + '3' * 24
    elif change == 'invalid_observation': value['independent_review_read']['observation_id'] = 'fabricated'
    elif change == 'overclaimed_coverage': value['independent_review_read']['coverage'] = 'all facts verified'
    elif change == 'extra_marker_key': value['independent_review_read']['ok'] = True
    elif change == 'wrong_content': value['text'] = 'value=43\n'
    with pytest.raises(AssertionError):
        check_file_result('write_text' if kind == 'write' else 'read_text', value, tmp_path,
                          CANDIDATE if kind == 'reviewer' else None)


async def test_fixture_uses_current_model_reply_and_native_envelope(tmp_path):
    client = ScriptedClient(tmp_path)
    client.engine = SimpleNamespace(runs={'r': {'task': MANUAL}},
                                    agents={'a': SimpleNamespace(kind='author')})
    profile = copy.deepcopy(DEFAULT['providers'][0])
    result = await client.complete(profile, [], [{'name': 'finish_work'}], '', {}, conversation_id='r/a')
    assert result.tool_calls[0]['name'] == 'finish_work'
    assert result.raw['message']['tool_calls'][0]['function']['name'] == 'finish_work'
    assert client.active == 0 and len(client.calls) == 1
