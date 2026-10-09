"""Model-list checks use mocked HTTP only; no provider or inference calls."""
import asyncio
import json
import ssl
from datetime import datetime, timezone

import aiohttp
import pytest

from workbench import diagnostics


PROFILE = {'kind': 'openai', 'base_url': 'https://provider.invalid/v1',
           'model': 'chosen-model', 'proxy_url': ''}
SECRET = 'fake-private-api-key'


class Content:
    def __init__(self, raw, failure=None):
        self.raw = raw
        self.failure = failure
        self.bytes_read = 0

    async def iter_chunked(self, size):
        if self.failure:
            raise self.failure
        for offset in range(0, len(self.raw), size):
            chunk = self.raw[offset:offset + size]
            self.bytes_read += len(chunk)
            yield chunk


class Response:
    def __init__(self, raw, status=200, failure=None, headers=None):
        self.status = status
        self.headers = headers or {}
        self.content = Content(raw, failure)
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.exited = True


@pytest.fixture
def http(monkeypatch):
    """Only this fake session may be instantiated by the diagnostic."""
    state = {'calls': [], 'sessions': [], 'exited': False}

    class Session:
        def __init__(self, **kwargs):
            state['sessions'].append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            state['exited'] = True

        def get(self, endpoint, **kwargs):
            state['calls'].append((endpoint, kwargs))
            if state.get('failure'):
                raise state['failure']
            return state['response']

    monkeypatch.setattr(diagnostics.aiohttp, 'ClientSession', Session)

    def prepare(payload=None, *, raw=None, status=200, failure=None, stream_failure=None, headers=None):
        if raw is None:
            raw = json.dumps(payload).encode()
        state['response'] = Response(raw, status, stream_failure, headers)
        state['failure'] = failure
        return state

    return prepare


def assert_envelope(result):
    assert isinstance(result['ok'], bool)
    assert isinstance(result['code'], str)
    assert result['inference_tested'] is False
    assert result['tools_tested'] is False
    assert result['selected_model'] in {'observed', 'not_observed', 'unknown'}
    assert isinstance(result['list_incomplete'], bool)
    assert len(result['models']) <= 200
    assert all(isinstance(model, str) and len(model) <= 200 for model in result['models'])
    checked = datetime.fromisoformat(result['checked_at'])
    assert checked.tzinfo is not None and checked.utcoffset().total_seconds() == 0
    assert abs((datetime.now(timezone.utc) - checked).total_seconds()) < 10
    assert SECRET not in json.dumps(result)
    assert not {'body', 'headers', 'api_key', 'url', 'endpoint'} & result.keys()
    if not result['ok']:
        assert result['error']
        assert result['models'] == []
        assert result['selected_model'] == 'unknown'


@pytest.mark.parametrize('kind,field', [('openai', 'data'), ('anthropic', 'data'), ('local', 'models')])
async def test_success_is_exact_model_observation_and_only_one_read_only_request(http, monkeypatch, kind, field):
    state = http({field: [{'id': 'other'}, {'name': 'chosen-model'}]})
    profile = dict(PROFILE, kind=kind, proxy_url='http://proxy.invalid:8080')
    if kind == 'local':
        profile['base_url'] = 'http://127.0.0.1:8000/v1/'
    monkeypatch.setenv('HTTPS_PROXY', 'http://unexpected.invalid:8888')
    monkeypatch.setenv('HTTP_PROXY', 'http://unexpected.invalid:8888')
    monkeypatch.setenv('ALL_PROXY', 'http://unexpected.invalid:8888')
    result = await diagnostics.diagnose_provider(profile, SECRET)
    assert_envelope(result)
    assert result['ok'] and result['code'] == 'models_listed'
    assert result['models'] == ['other', 'chosen-model']
    assert result['selected_model'] == 'observed'
    assert not result['list_incomplete']
    assert len(state['calls']) == len(state['sessions']) == 1
    endpoint, request = state['calls'][0]
    assert endpoint == profile['base_url'].rstrip('/') + '/models'
    assert request['allow_redirects'] is False
    assert request['proxy'] == (None if kind == 'local' else profile['proxy_url'])
    assert request['headers'] == ({'x-api-key': SECRET, 'anthropic-version': '2023-06-01'}
                                  if kind == 'anthropic' else {'Authorization': 'Bearer ' + SECRET})
    assert state['sessions'][0]['trust_env'] is False
    assert state['sessions'][0]['timeout'].total == 15
    assert state['exited'] and state['response'].exited


@pytest.mark.parametrize('model,entries,expected', [
    ('chosen-model', [], 'not_observed'),
    ('chosen-model', [{'id': 'Chosen-Model'}], 'not_observed'),
    ('', [{'id': 'chosen-model'}], 'unknown'),
    ('chosen-model', [{'id': 'different', 'name': 'chosen-model'}], 'not_observed'),
])
async def test_empty_absent_and_unconfigured_models_are_not_capability_assertions(http, model, entries, expected):
    http({'data': entries})
    result = await diagnostics.diagnose_provider(dict(PROFILE, model=model), '')
    assert_envelope(result)
    assert result['ok'] and result['selected_model'] == expected
    assert result['list_incomplete'] is False


@pytest.mark.parametrize('pagination', [
    {'has_more': True}, {'hasMore': True}, {'next_cursor': 'opaque-private-cursor'},
    {'next': 'https://do-not-follow.invalid'}, {'next_page': 2}, {'next_page_token': 'token'},
    {'nextPageToken': 'token'}, {'pagination': {'has_more': True}},
    {'links': {'next': 'https://do-not-follow.invalid'}},
])
@pytest.mark.parametrize('observed', [True, False])
async def test_pagination_is_disclosed_but_never_followed(http, pagination, observed):
    state = http({'data': [{'id': 'chosen-model' if observed else 'other'}], **pagination})
    result = await diagnostics.diagnose_provider(PROFILE, '')
    assert_envelope(result)
    assert result['ok'] and result['list_incomplete']
    assert result['selected_model'] == ('observed' if observed else 'unknown')
    assert len(state['calls']) == 1
    assert 'opaque-private-cursor' not in json.dumps(result)
    assert 'do-not-follow' not in json.dumps(result)


@pytest.mark.parametrize('link,incomplete', [
    ('<https://do-not-follow.invalid>; rel="next"', True),
    ('<https://do-not-follow.invalid>; rel=next', True),
    ('<https://do-not-follow.invalid>; rel="alternate next"', True),
    ('<https://do-not-follow.invalid>; rel="prev", <https://do-not-follow.invalid/2>; rel="next"', True),
    ('<https://do-not-follow.invalid>; rel="prev"', False),
])
async def test_link_pagination_is_neither_followed_nor_exposed(http, link, incomplete):
    state = http({'data': []}, headers={'Link': link, 'X-Secret': SECRET})
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['ok'] and result['list_incomplete'] is incomplete
    assert result['selected_model'] == ('unknown' if incomplete else 'not_observed')
    assert 'do-not-follow' not in json.dumps(result)
    assert len(state['calls']) == 1


async def test_truncation_preserves_exact_match_and_does_not_invent_match(http):
    http({'data': [{'id': 'chosen-model' + 'x' * 240}]})
    result = await diagnostics.diagnose_provider(PROFILE, '')
    assert_envelope(result)
    assert len(result['models'][0]) == 200
    assert result['selected_model'] == 'unknown' and result['list_incomplete']


async def test_entry_cap_does_not_skip_validation_or_raw_exact_match(http):
    entries = [{'id': f'model-{index}'} for index in range(200)]
    http({'data': entries + [{'id': 'chosen-model'}]})
    result = await diagnostics.diagnose_provider(PROFILE, '')
    assert_envelope(result)
    assert len(result['models']) == 200 and result['list_incomplete']
    assert result['selected_model'] == 'observed'
    http({'data': entries + [{'id': {'invalid': True}}]})
    result = await diagnostics.diagnose_provider(PROFILE, '')
    assert_envelope(result)
    assert result['code'] == 'invalid_schema'


@pytest.mark.parametrize('payload', [
    None, [], 'text', 5, True, {}, {'error': 'private upstream detail'},
    {'data': None}, {'data': {}}, {'data': 'abc'}, {'data': False},
    {'models': {}}, {'data': [], 'models': []},
    {'data': [None]}, {'data': [1]}, {'data': ['chosen-model']}, {'data': [[]]},
    {'data': [{}]}, {'data': [{'id': None}]}, {'data': [{'id': 3}]},
    {'data': [{'id': True}]}, {'data': [{'id': []}]}, {'data': [{'id': {'name': 'bad'}}]},
    {'data': [{'name': 3}]}, {'data': [{'id': ''}]}, {'data': [{'name': '   '}]},
    {'data': [{'id': '\ud800'}]},
    {'data': [{'id': 'line\nbreak'}]}, {'data': [{'id': None, 'name': 'otherwise valid'}]},
    {'data': [], 'has_more': 'false'}, {'data': [], 'has_more': 0},
    {'data': [], 'next_cursor': []}, {'data': [], 'next': {'href': 'unsafe'}},
    {'data': [], 'pagination': []}, {'data': [], 'links': True},
    {'data': [], 'pagination': {'pagination': {}}},
])
async def test_malformed_shapes_are_rejected_without_coercion_or_raw_output(http, payload):
    http(payload)
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['code'] == 'invalid_schema'
    assert 'private upstream detail' not in json.dumps(result)


@pytest.mark.parametrize('raw', [
    b'', b'not-json-private-detail', b'<html>private detail</html>', b'\xff',
    b'{"data":[],"data":[]}', b'{"data":[],"other":NaN}',
])
async def test_invalid_json_is_safe_and_typed(http, raw):
    http(raw=raw)
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['code'] == 'invalid_json'
    assert 'private' not in result['error']


async def test_parser_recursion_limit_is_a_safe_json_failure(http, monkeypatch):
    http({'data': []})

    def too_deep(raw):
        raise RecursionError(SECRET)

    monkeypatch.setattr(diagnostics, 'strict_json', too_deep)
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['code'] == 'invalid_json'


async def test_deeply_nested_response_is_rejected(http):
    http(raw=b'[' * 1100 + b']' * 1100)
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['code'] in {'invalid_json', 'invalid_schema'}


@pytest.mark.parametrize('status,code', [
    (401, 'unauthorized'), (403, 'forbidden'), (404, 'endpoint_unsupported'),
    (405, 'endpoint_unsupported'), (429, 'rate_limited'), (500, 'server_error'),
    (503, 'server_error'), (599, 'server_error'), (301, 'redirect_blocked'),
    (302, 'redirect_blocked'), (307, 'redirect_blocked'), (308, 'redirect_blocked'),
    (400, 'http_error'), (418, 'http_error'), (204, 'http_error'),
])
async def test_http_failures_do_not_read_or_return_body_headers_or_keys(http, status, code):
    state = http(raw=(SECRET + ' private upstream detail').encode(), status=status)
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['code'] == code and result['http_status'] == status
    assert state['response'].content.bytes_read == 0
    assert state['response'].exited and state['exited']
    assert len(state['calls']) == 1
    assert 'private upstream detail' not in json.dumps(result)


@pytest.mark.parametrize('failure,code', [
    (asyncio.TimeoutError(SECRET), 'timeout'),
    (aiohttp.ServerTimeoutError(SECRET), 'timeout'),
    (ssl.SSLError(SECRET), 'tls_error'),
    (aiohttp.ClientConnectorSSLError(None, ssl.SSLError(SECRET)), 'tls_error'),
    (aiohttp.ClientConnectorCertificateError(None, ssl.CertificateError(SECRET)), 'tls_error'),
    (aiohttp.ServerFingerprintMismatch(b'expected', b'received', SECRET, 443), 'tls_error'),
    (aiohttp.ClientConnectionError(SECRET), 'connection_error'),
    (aiohttp.ClientPayloadError(SECRET), 'connection_error'),
    (aiohttp.ClientError(SECRET), 'connection_error'),
    (OSError(SECRET), 'connection_error'),
    (aiohttp.InvalidURL('https://private.invalid/' + SECRET), 'invalid_configuration'),
])
@pytest.mark.parametrize('stream', [False, True])
async def test_transport_failures_are_typed_without_leaking_exception_text(http, failure, code, stream):
    state = http({'data': []}, **({'stream_failure': failure} if stream else {'failure': failure}))
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['code'] == code
    assert len(state['calls']) == 1 and state['exited']


async def test_cancellation_is_not_swallowed(http):
    http(failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await diagnostics.diagnose_provider(PROFILE, SECRET)


async def test_byte_limit_is_inclusive_and_oversized_body_stops_promptly(http):
    valid = b'{"data":[]}'
    http(raw=valid + b' ' * (diagnostics.MAX_RESPONSE_BYTES - len(valid)))
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['ok']
    state = http(raw=valid + b' ' * (diagnostics.MAX_RESPONSE_BYTES * 2))
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['code'] == 'response_too_large' and result['list_incomplete']
    assert state['response'].content.bytes_read <= diagnostics.MAX_RESPONSE_BYTES + 65536
    assert state['response'].exited and state['exited']


async def test_credentials_echoed_as_model_names_are_not_returned(http):
    http({'models': [{'id': SECRET}, {'id': 'prefix-' + SECRET + '-suffix'}, {'name': 'safe-model'}]})
    result = await diagnostics.diagnose_provider(PROFILE, SECRET)
    assert_envelope(result)
    assert result['ok'] and result['models'] == ['safe-model']
    assert result['list_incomplete'] and result['selected_model'] == 'unknown'


@pytest.mark.parametrize('changes,key', [
    ({'kind': 'unsupported'}, ''), ({'base_url': None}, ''),
    ({'base_url': 'https://user:private@provider.invalid'}, ''),
    ({'base_url': 'http://external.invalid'}, ''), ({'base_url': 'https://provider.invalid/?key=private'}, ''),
    ({'proxy_url': 'http://user:private@proxy.invalid'}, ''),
    ({'model': []}, ''), ({}, None), ({}, 'key\nprivate'),
])
async def test_invalid_configuration_never_starts_network(http, changes, key):
    state = http({'data': []})
    result = await diagnostics.diagnose_provider(dict(PROFILE, **changes), key)
    assert_envelope(result)
    assert result['code'] == 'invalid_configuration'
    assert state['calls'] == state['sessions'] == []


async def test_complete_pagination_and_no_key(http):
    state = http({'models': [], 'has_more': False, 'next_cursor': None, 'next': '',
                  'pagination': {'next_page': 0}, 'links': {'next': None}})
    result = await diagnostics.diagnose_provider(PROFILE, '')
    assert_envelope(result)
    assert result['ok'] and not result['list_incomplete']
    assert state['calls'][0][1]['headers'] == {}
    assert state['calls'][0][1]['proxy'] is None
