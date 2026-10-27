"""Deterministic public-data projection with no external requests or models."""
import asyncio
import hashlib
import json

import pytest

import workbench.webdata as data_module
from workbench.webtools import WebToolError, WebTools


def size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False))


def tools_with_body(monkeypatch, body, content_type='application/json; charset=utf-8'):
    tools = WebTools({'search': {'enabled': True}})
    calls = []
    payload = body.encode('utf-8') if isinstance(body, str) else body

    async def request(url, **kwargs):
        calls.append((url, kwargs))
        return payload, content_type, 'https://public.example/final'

    monkeypatch.setattr(tools, '_request', request)
    return tools, calls, payload


async def fetch(tools):
    return await tools.execute('web_fetch', {'url': 'https://public.example/source'})


async def read(tools, first, **args):
    return await tools.execute('web_read', {'snapshot_id': first['snapshot_id'], **args})


def test_sparse_forecast_shaped_json_keeps_dates_indices_null_and_missing_distinct(monkeypatch):
    source = {'timeSeries': [{'timeDefines': ['2026-10-27T00:00:00+09:00',
                                             '2026-10-28T00:00:00+09:00',
                                             '2026-10-29T00:00:00+09:00'],
                              'areas': [{'area': {'name': 'Synthetic A', 'code': '001'},
                                         'weather': ['clear', '', None], 'pops': ['', None, '20']},
                                        {'area': {'name': 'Synthetic B', 'code': '002'},
                                         'weather': [None, 'rain', ''], 'pops': [None, '40', '']}]}],
              'unrelated': [''] * 1000}
    tools, calls, raw = tools_with_body(monkeypatch, json.dumps(source))

    async def run():
        first = await fetch(tools)
        dates = await read(tools, first, pointer='/timeSeries/0/timeDefines', offset=1, limit=1)
        weather = await read(tools, first, pointer='/timeSeries/0/areas/0/weather', offset=1, limit=1)
        probability = await read(tools, first, pointer='/timeSeries/0/areas/0/pops', offset=1, limit=1)
        area = await read(tools, first, pointer='/timeSeries/0/areas/0', fields=['area', 'pops', 'missing'])
        assert dates['items'] == [{'index': 1, 'value': source['timeSeries'][0]['timeDefines'][1]}]
        assert weather['items'] == [{'index': 1, 'value': ''}]
        assert probability['items'] == [{'index': 1, 'value': None}]
        assert area['value'] == {'area': source['timeSeries'][0]['areas'][0]['area'], 'pops': ['', None, '20']}
        assert area['missing_fields'] == ['missing'] and area['projected'] is True
        assert dates['next_offset'] == 2 and dates['page_complete'] is True and dates['truncated'] is True
        assert first['structure']['type'] == 'object'
        for result in (first, dates, weather, probability, area):
            assert size(result) <= 12000 and result['untrusted'] is True
            assert result['sha256'] == hashlib.sha256(raw).hexdigest()
            assert result['fetched_at'] == first['fetched_at']
        assert dates['cached'] is True and first['cached'] is False
        assert len(calls) == 1

    asyncio.run(run())


def test_large_json_does_not_enter_fetch_result_and_exact_selected_fields_remain_readable(monkeypatch):
    source = {'irrelevant': 'x' * 150000, 'needed': {'date': 'tomorrow', 'value': 0, 'empty': []}}
    tools, calls, _ = tools_with_body(monkeypatch, json.dumps(source))

    async def run():
        first = await fetch(tools)
        assert size(first) <= 12000 and first['truncated'] is True
        assert first['source_truncated'] is False and first['json_status'] == 'valid'
        whole = await read(tools, first)
        assert whole['value_included'] is False and 'value' not in whole and whole['truncated']
        selected = await read(tools, first, fields=['needed'])
        assert selected['value'] == {'needed': source['needed']}
        assert selected['truncated'] is False and selected['value_included'] is True
        assert size(whole) <= 12000 and len(calls) == 1

    asyncio.run(run())


def test_array_oversized_first_item_is_not_skipped_and_can_be_narrowed(monkeypatch):
    tools, calls, _ = tools_with_body(monkeypatch, json.dumps([{'large': 'x' * 30000, 'id': 1}, {'id': 2}]))

    async def run():
        first = await fetch(tools)
        page = await read(tools, first, limit=2)
        assert page['items'] == [] and page['blocked_index'] == 0 and page['item_pointer'] == '/0'
        assert page['next_offset'] is None and page['page_complete'] is False
        assert page['truncated'] is True and size(page) <= 12000
        projected = await read(tools, first, limit=2, fields=['id'])
        assert projected['items'] == [{'index': 0, 'value': {'id': 1}, 'missing_fields': []},
                                      {'index': 1, 'value': {'id': 2}, 'missing_fields': []}]
        assert projected['page_complete'] is True and projected['next_offset'] is None
        assert len(calls) == 1

    asyncio.run(run())


def test_array_page_stops_before_large_later_item_without_reordering(monkeypatch):
    tools, _, _ = tools_with_body(monkeypatch, json.dumps([None, '', {'huge': 'q' * 50000}, False]))

    async def run():
        first = await fetch(tools)
        page = await read(tools, first, limit=4)
        assert page['items'] == [{'index': 0, 'value': None}, {'index': 1, 'value': ''}]
        assert page['next_offset'] == 2 and page['page_complete'] is False
        blocked = await read(tools, first, offset=2, limit=2)
        assert blocked['blocked_index'] == 2 and blocked['items'] == []
        assert blocked['next_offset'] is None

    asyncio.run(run())


@pytest.mark.parametrize(('pointer', 'value'), [('', {'a/b': {'~key': [None, '']}, '': 3}),
                                               ('/a~1b/~0key/0', None), ('/a~1b/~0key/1', ''), ('/', 3)])
def test_rfc6901_literal_keys_and_root(monkeypatch, pointer, value):
    tools, _, _ = tools_with_body(monkeypatch, '{"a/b":{"~key":[null,""]},"":3}')

    async def run():
        first = await fetch(tools)
        result = await read(tools, first, pointer=pointer)
        if isinstance(value, str):
            assert result['text'] == value
        else:
            assert result['value'] == value

    asyncio.run(run())


@pytest.mark.parametrize('pointer', ['#/a', 'a', '/a~2b', '/missing', '/a/01', '/a/-', '/a/-1', '/a/3', '/a/*', '/\ud800', True, None])
def test_invalid_pointer_or_missing_path_never_fetches_again(monkeypatch, pointer):
    tools, calls, _ = tools_with_body(monkeypatch, '{"a":[1,2,3]}')

    async def run():
        first = await fetch(tools)
        with pytest.raises(WebToolError):
            await read(tools, first, pointer=pointer)
        assert len(calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize('args', [{'offset': True}, {'offset': -1}, {'limit': False}, {'limit': 101},
                                  {'max_chars': True}, {'max_chars': 24001}, {'max_chars': 0},
                                  {'fields': []}, {'fields': ['a', 'a']}, {'fields': [[]]},
                                  {'fields': None}, {'fields': ['\ud800']}, {'url': 'https://other.example'}])
def test_invalid_projection_arguments_are_rejected(monkeypatch, args):
    tools, calls, _ = tools_with_body(monkeypatch, '[{"a":1}]')

    async def run():
        first = await fetch(tools)
        with pytest.raises(WebToolError):
            await read(tools, first, **args)
        assert len(calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(('source', 'reason'), [('{"x":1,"x":2}', 'json_duplicate_keys'),
    ('{"outer":{"x":1,"x":2}}', 'json_duplicate_keys'), ('[NaN]', 'json_nonfinite_number'),
    ('[1e999]', 'json_nonfinite_number'), ('[0.123456789012345678901]', 'json_number_precision'),
    ('[1.0000000000000001]', 'json_number_precision'), ('[1e-999]', 'json_number_precision'),
    ('[1e-' + '9' * 60 + ']', 'json_number_precision'),
    ('[' + '1' * 129 + ']', 'json_number_limit'), ('["\\ud800"]', 'invalid_json'),
    ('{"x":"bad\x01control"}', 'invalid_json'), ('{"x":', 'invalid_json'),
    ('[' * 33 + '0' + ']' * 33, 'json_depth_limit'),
    ('[' + ','.join(['null'] * 20001) + ']', 'json_node_limit')], ids=[
    'duplicate-root', 'duplicate-nested', 'nan', 'infinite-exponent', 'precise-fraction',
    'rounded-one', 'underflow', 'huge-negative-exponent', 'large-number-token',
    'lone-surrogate', 'literal-control', 'incomplete-json', 'deep-json', 'many-null-nodes'])
def test_ambiguous_or_unsupported_json_is_honest_raw_only(monkeypatch, source, reason):
    tools, calls, raw = tools_with_body(monkeypatch, source)

    async def run():
        first = await fetch(tools)
        assert first['format'] == 'text' and first['json_status'] == 'raw_only'
        assert first['json_reason'] == reason and 'structure' not in first
        assert first['sha256'] == hashlib.sha256(raw).hexdigest()
        page = await read(tools, first, limit=10000)
        assert page['text'] == source[:page['returned_chars']]
        with pytest.raises(WebToolError, match='raw text'):
            await read(tools, first, pointer='/0')
        assert size(first) <= 12000 and size(page) <= 12000 and len(calls) == 1

    asyncio.run(run())


def test_normal_numbers_and_exact_large_integer_are_preserved(monkeypatch):
    tools, _, _ = tools_with_body(monkeypatch, '[0.1,1e3,-0.0,123456789012345678901234567890]')

    async def run():
        first = await fetch(tools)
        result = await read(tools, first)
        assert first['json_status'] == 'valid'
        assert [entry['value'] for entry in result['items']] == [0.1, 1000.0, -0.0, 123456789012345678901234567890]

    asyncio.run(run())


def test_plain_text_cleaning_does_not_repair_a_json_candidate(monkeypatch):
    tools, _, _ = tools_with_body(monkeypatch, '\x01{"a":1}', 'text/plain; charset=utf-8')

    async def run():
        first = await fetch(tools)
        assert first['text'] == '{"a":1}' and first['format'] == 'text'
        assert first['json_status'] == 'not_json'
        with pytest.raises(WebToolError, match='raw text'):
            await read(tools, first, pointer='/a')

    asyncio.run(run())


def test_json_beyond_retention_limit_is_not_parsed_as_a_complete_prefix(monkeypatch):
    source = '{}' + ' ' * 200000 + '{"ignored":1}'
    tools, _, _ = tools_with_body(monkeypatch, source)

    async def run():
        first = await fetch(tools)
        assert first['source_truncated'] and first['json_reason'] == 'retained_text_limit'
        assert first['retained_chars'] == 200000 and first['format'] == 'text'
        last = await read(tools, first, offset=199999, limit=1)
        assert last['text'] == ' ' and last['source_truncated'] and last['next_offset'] is None
        assert last['truncated'] is True

    asyncio.run(run())


def test_string_and_raw_text_pages_measure_actual_json_escaping(monkeypatch):
    text = '\n"\\\t' * 3000
    tools, calls, _ = tools_with_body(monkeypatch, json.dumps({'long': text}))

    async def run():
        first = await fetch(tools)
        collected, offset = [], 0
        while True:
            page = await read(tools, first, pointer='/long', offset=offset, limit=10000, max_chars=1400)
            assert size(page) <= 1400
            assert page['returned_chars'] > 0
            collected.append(page['text'])
            if page['next_offset'] is None:
                break
            assert page['next_offset'] > offset
            offset = page['next_offset']
        assert ''.join(collected) == text and len(calls) == 1

    asyncio.run(run())


def test_snapshot_isolation_immutability_and_count_eviction(monkeypatch):
    tools, calls, _ = tools_with_body(monkeypatch, '{"a":1}')
    other = WebTools({'search': {'enabled': True}})

    async def run():
        first = await fetch(tools)
        same = await fetch(tools)
        assert first['snapshot_id'] != same['snapshot_id'] and first['sha256'] == same['sha256']
        projection = await read(tools, first)
        projection['value']['a'] = 999
        first['url'] = 'https://changed.invalid'
        assert (await read(tools, first))['value'] == {'a': 1}
        assert (await read(tools, first))['url'] == 'https://public.example/final'
        with pytest.raises(WebToolError, match='unknown or evicted'):
            await read(other, first)
        for _ in range(7):
            await fetch(tools)
        assert len(tools._snapshots._entries) == 8
        with pytest.raises(WebToolError, match='unknown or evicted'):
            await read(tools, first)
        assert len(calls) == 9

    asyncio.run(run())


def test_snapshot_utf8_payload_byte_quota_evicts_without_disk_or_refetch(monkeypatch):
    tools, calls, _ = tools_with_body(monkeypatch, '😀' * 200000, 'text/plain; charset=utf-8')

    async def run():
        first = await fetch(tools)
        await fetch(tools)
        newest = await fetch(tools)
        cache = tools._snapshots
        assert len(cache._entries) == 2 and cache.byte_count <= data_module.MAX_SNAPSHOT_BYTES
        assert cache.byte_count == sum(item.charge for item in cache._entries.values())
        with pytest.raises(WebToolError, match='unknown or evicted'):
            await read(tools, first)
        assert (await read(tools, newest, limit=1))['text'] == '😀'
        assert len(calls) == 3

    asyncio.run(run())


def test_disabled_tools_refuse_snapshot_reads_and_keep_permissions(monkeypatch):
    tools, calls, _ = tools_with_body(monkeypatch, '{}')

    async def run():
        first = await fetch(tools)
        tools.enabled = False
        assert tools.schemas() == []
        with pytest.raises(WebToolError, match='disabled'):
            await read(tools, first)
        assert len(calls) == 1

    asyncio.run(run())


def test_object_projection_and_array_null_rows_never_become_missing_or_zero(monkeypatch):
    tools, _, _ = tools_with_body(monkeypatch, '[{"a":null,"b":"","c":[]},null,{"b":false,"c":0}]')

    async def run():
        first = await fetch(tools)
        result = await read(tools, first, fields=['a', 'b', 'c'])
        assert result['items'] == [
            {'index': 0, 'value': {'a': None, 'b': '', 'c': []}, 'missing_fields': []},
            {'index': 1, 'value': None},
            {'index': 2, 'value': {'b': False, 'c': 0}, 'missing_fields': ['a']}]
        assert result['returned_items'] == 3 and result['page_complete'] is True

    asyncio.run(run())


def test_long_metadata_and_fields_cannot_bypass_response_limit(monkeypatch):
    source = {('key' + str(i) + '"\\' * 35): {'long': 'x' * 5000} for i in range(20)}
    tools, _, raw = tools_with_body(monkeypatch, json.dumps(source))

    async def request(url):
        return raw, 'application/json; charset=utf-8', 'https://public.example/' + 'u' * 3900

    monkeypatch.setattr(tools, '_request', request)

    async def run():
        first = await fetch(tools)
        assert size(first) <= 12000
        result = await read(tools, first, fields=list(source), max_chars=24000)
        assert result['value_included'] is False and size(result) <= 24000
        with pytest.raises(WebToolError, match='max_chars'):
            await read(tools, first, max_chars=1024)

    asyncio.run(run())
