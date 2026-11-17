"""Fewer searches per piece of work: statistics read directly, a search guide, similar questions, and an
unanswered human check that does not hold the run for ever.

No network: the World Bank answer is a fixture and the browser is a function returning prepared HTML.
"""
import asyncio
import io
import json
import os
import time
import zipfile

import pytest

from workbench import sources, statdata
from workbench.browser_search import SearchCache, query_words
from workbench.config import DEFAULT, validate_settings
from workbench.webtools import WebToolError, WebTools
from test_browser_search import DDG_CHECK, WEB, WEB_CHECK, browser_run, fresh_engine_guards, pages  # noqa: F401  (autouse: no pacing)
from test_engine import configured, start


def world_bank(rows, *, name='GDP growth (annual %)', code='NY.GDP.MKTP.KD.ZG'):
    """The shape api.worldbank.org returns: [paging, rows]."""
    return [{'page': 1, 'pages': 1, 'per_page': 1000, 'total': len(rows), 'sourceid': '2', 'lastupdated': '2026-07-01'},
            [{'indicator': {'id': code, 'value': name}, 'country': {'id': iso2, 'value': country},
              'countryiso3code': iso3, 'date': str(year), 'value': value, 'unit': '', 'obs_status': '', 'decimal': 1}
             for iso3, iso2, country, year, value in rows]]


ROWS = [('JPN', 'JP', 'Japan', 2023, 1.48), ('JPN', 'JP', 'Japan', 2022, 0.95), ('JPN', 'JP', 'Japan', 2024, None),
        ('USA', 'US', 'United States', 2023, 2.89), ('USA', 'US', 'United States', 2022, 2.51),
        ('', '1W', 'World', 2023, 2.83)]


# --- names, the request and the answer ---------------------------------------------------------------

def test_indicators_and_countries_are_named_in_plain_words_or_by_code():
    assert statdata.indicator('gdp_growth') == ('NY.GDP.MKTP.KD.ZG', 'GDP growth (annual %)')
    for name in ('GDP成長率', 'ＧＤＰ成長率', 'real GDP growth', 'gdp growth', 'ny.gdp.mktp.kd.zg'):
        assert statdata.indicator(name)[0] == 'NY.GDP.MKTP.KD.ZG', name
    assert [statdata.indicator(name)[0] for name in ('人口', '失業率', 'インフレ率', '消費者物価指数', 'population')] == [
        'SP.POP.TOTL', 'SL.UEM.TOTL.ZS', 'FP.CPI.TOTL.ZG', 'FP.CPI.TOTL', 'SP.POP.TOTL']
    assert statdata.indicator('SH.XPD.CHEX.GD.ZS') == ('SH.XPD.CHEX.GD.ZS', '')  # any other World Bank series, by code
    for bad in ('', 'happiness', 'https://example.org/x', 'A.B/../C', None, 'x' * 200):
        with pytest.raises(ValueError, match='indicator'):
            statdata.indicator(bad)
    assert [statdata.country(name) for name in ('Japan', '日本', 'jp', 'JPN', '米国', 'United States', 'UK', '韓国', 'ドイツ', '世界', 'BWA')] == [
        'JPN', 'JPN', 'JPN', 'JPN', 'USA', 'USA', 'GBR', 'KOR', 'DEU', 'WLD', 'BWA']
    for bad in ('', 'Atlantis', 'JP;US', '../x', None):
        with pytest.raises(ValueError, match='country'):
            statdata.country(bad)


def test_the_request_goes_to_the_fixed_address_with_only_codes_and_years():
    url, page, code, label, codes, start, end = statdata.request(['日本', 'USA', 'Japan', '世界'], 'GDP成長率', None, None, 2026)
    assert url == 'https://api.worldbank.org/v2/country/JPN;USA;WLD/indicator/NY.GDP.MKTP.KD.ZG?format=json&date=2017:2026&per_page=1000'
    assert page == 'https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=JP-US-1W'
    assert (code, codes, start, end) == ('NY.GDP.MKTP.KD.ZG', ['JPN', 'USA', 'WLD'], 2017, 2026)
    assert statdata.request('Japan', 'population', 2000, 2005, 2026)[0].endswith('/country/JPN/indicator/SP.POP.TOTL?format=json&date=2000:2005&per_page=1000')
    for countries, first, last in (([], None, None), (['Japan'] * 13 + [str(i) for i in range(0)], 1800, None), (['Japan'], 2020, 2010),
                                   (['Japan'], 1960, 2025), (['Japan'], '2020', None), (['Japan'], None, 2090), ({'a': 1}, None, None)):
        with pytest.raises(ValueError):
            statdata.request(countries, 'population', first, last, 2026)
    with pytest.raises(ValueError, match='1 to 12'):
        statdata.request([f'C{i:02d}'.replace('C0', 'AA').replace('C1', 'AB')[:3] for i in range(13)], 'population', None, None, 2026)


def test_the_answer_becomes_values_per_country_and_missing_values_are_said():
    found = statdata.read(world_bank(ROWS), 'NY.GDP.MKTP.KD.ZG', '', ['JPN', 'USA', 'WLD', 'DEU'])
    assert found['indicator'] == {'id': 'NY.GDP.MKTP.KD.ZG', 'name': 'GDP growth (annual %)'} and found['last_updated'] == '2026-07-01'
    japan, usa, world = found['series']
    assert japan == {'country': 'Japan', 'code': 'JPN', 'values': [{'year': 2022, 'value': 0.95}, {'year': 2023, 'value': 1.48}],
                     'latest': {'year': 2023, 'value': 1.48}}  # the empty 2024 is not a value
    assert usa['latest'] == {'year': 2023, 'value': 2.89} and world['code'] == 'WLD' and world['latest']['value'] == 2.83
    assert found['no_values'] == ['DEU']
    error = [{'message': [{'id': '120', 'key': 'Invalid value', 'value': 'The provided parameter value is not valid'}]}]
    with pytest.raises(ValueError, match='did not accept the request.*not valid'):
        statdata.read(error, 'X.Y', '', ['JPN'])
    for odd in ({}, [], [{'page': 1}], 'text', [{'page': 1}, None, 3]):
        with pytest.raises(ValueError, match='expected form'):
            statdata.read(odd, 'X.Y', '', ['JPN'])
    assert statdata.read([{'page': 0}, None], 'X.Y', 'L', ['JPN'])['no_values'] == ['JPN']  # an empty answer


# --- the bulk file: one indicator, every country and year ---------------------------------------------

def bulk_csv(rows, code='NY.GDP.MKTP.KD.ZG', name='GDP growth (annual %)', years=range(2019, 2026)):
    """The data table as the World Bank's download has it: four lead lines, then one row per country."""
    table = {}
    for iso3, _iso2, country, year, value in rows:
        table.setdefault((country, iso3 or 'WLD'), {})[year] = value
    lines = ['\ufeff"Data Source","World Development Indicators",', '', '"Last Updated Date","2026-07-01",', '',
             '"Country Name","Country Code","Indicator Name","Indicator Code",' + ','.join(f'"{year}"' for year in years) + ',']
    for (country, iso3), values in table.items():
        cells = ','.join('"' + ('' if values.get(year) is None else str(values[year])) + '"' for year in years)
        lines.append(f'"{country}","{iso3}","{name}","{code}",{cells},')
    return '\r\n'.join(lines) + '\r\n'


def bulk_zip(rows=None, code='NY.GDP.MKTP.KD.ZG', *, files=None, **csv_options):
    files = files if files is not None else {
        f'API_{code}_DS2_en_csv_v2_123456.csv': bulk_csv(ROWS if rows is None else rows, code, **csv_options),
        f'Metadata_Country_API_{code}_DS2_en_csv_v2_123456.csv': '"Country Code","Region",\r\n"JPN","East Asia & Pacific",\r\n',
        f'Metadata_Indicator_API_{code}_DS2_en_csv_v2_123456.csv': '"INDICATOR_CODE","INDICATOR_NAME",\r\n'}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def test_the_bulk_file_is_read_in_memory_and_only_in_the_expected_form(monkeypatch):
    table = statdata.read_bulk(bulk_zip(), 'NY.GDP.MKTP.KD.ZG')
    assert table['label'] == 'GDP growth (annual %)' and table['last_updated'] == '2026-07-01'
    assert table['rows']['JPN'] == ('Japan', {2022: 0.95, 2023: 1.48}) and table['rows']['WLD'][1] == {2023: 2.83}
    found = statdata.select(table, 'NY.GDP.MKTP.KD.ZG', '', ['JPN', 'USA', 'WLD', 'DEU'], 2023, 2025)
    assert [row['code'] for row in found['series']] == ['JPN', 'USA', 'WLD'] and found['no_values'] == ['DEU']
    assert found['series'][0] == {'country': 'Japan', 'code': 'JPN', 'values': [{'year': 2023, 'value': 1.48}], 'latest': {'year': 2023, 'value': 1.48}}
    whole = statdata.read_bulk(bulk_zip([('JPN', 'JP', 'Japan', 2023, 124516650)], 'SP.POP.TOTL', name='Population, total'), 'SP.POP.TOTL')
    assert whole['rows']['JPN'][1] == {2023: 124516650}  # a whole number stays one

    data = bulk_csv(ROWS)
    for files, problem in (
            ({'../API_NY.GDP.MKTP.KD.ZG_DS2.csv': data}, 'does not accept'),
            ({'data/API_NY.GDP.MKTP.KD.ZG_DS2.csv': data}, 'does not accept'),
            ({'C:\\Windows\\API_NY.GDP.MKTP.KD.ZG_DS2.csv': data}, 'does not accept'),
            ({'/etc/API_NY.GDP.MKTP.KD.ZG_DS2.csv': data}, 'does not accept'),
            ({'API_NY.GDP.MKTP.KD.ZG_DS2.csv': data, '.hidden': 'x'}, 'does not accept'),
            ({f'API_NY.GDP.MKTP.KD.ZG_{index}.txt': 'x' for index in range(17)}, 'expected contents'),
            ({'Metadata_Country_API_NY.GDP.MKTP.KD.ZG_DS2.csv': 'x'}, 'does not contain the data table'),
            ({'API_NY.GDP.MKTP.KD.ZG_a.csv': data, 'API_NY.GDP.MKTP.KD.ZG_b.csv': data}, 'does not contain the data table'),
            ({'API_SP.POP.TOTL_DS2.csv': data}, 'does not contain the data table'),
            ({'API_NY.GDP.MKTP.KD.ZG_DS2.csv': bulk_csv(ROWS, code='SP.POP.TOTL')}, 'expected columns'),
            ({'API_NY.GDP.MKTP.KD.ZG_DS2.csv': 'no table here'}, 'expected columns'),
            ({'API_NY.GDP.MKTP.KD.ZG_DS2.csv': b'\xff\xfe\x00bad'.decode('latin-1').encode('latin-1')}, 'not UTF-8')):
        with pytest.raises(ValueError, match=problem):
            statdata.read_bulk(bulk_zip(files=files), 'NY.GDP.MKTP.KD.ZG')
    for junk in (b'', b'<html>busy</html>', b'PK\x03\x04broken', None, 'text'):
        with pytest.raises(ValueError, match='not a zip archive|larger than'):
            statdata.read_bulk(junk, 'NY.GDP.MKTP.KD.ZG')
    # Sizes: the download, what an entry declares, and what is really unpacked.
    monkeypatch.setattr(statdata, 'MAX_CSV_BYTES', 2000)
    with pytest.raises(ValueError, match='does not accept'):
        statdata.read_bulk(bulk_zip(files={'API_NY.GDP.MKTP.KD.ZG_DS2.csv': 'x' * 5000}), 'NY.GDP.MKTP.KD.ZG')
    forged = bytearray(bulk_zip(files={'API_NY.GDP.MKTP.KD.ZG_DS2.csv': 'x' * 5000}))
    for at in (index for index in range(len(forged) - 4) if forged[index:index + 4] in (b'PK\x01\x02', b'PK\x03\x04')):
        offset = at + (24 if forged[at:at + 4] == b'PK\x01\x02' else 22)
        forged[offset:offset + 4] = (100).to_bytes(4, 'little')  # the archive claims 100 bytes
    with pytest.raises(ValueError, match='larger than the application reads|could not be unpacked'):
        statdata.read_bulk(bytes(forged), 'NY.GDP.MKTP.KD.ZG')
    monkeypatch.setattr(statdata, 'MAX_ZIP_BYTES', 100)
    with pytest.raises(ValueError, match='larger than'):
        statdata.read_bulk(bulk_zip(), 'NY.GDP.MKTP.KD.ZG')


# --- the tool ------------------------------------------------------------------------------------------

def lookup_tools(*, bulk=None, api=None, **search):
    """WebTools whose requests are answered here. ``bulk``/``api``: bytes or payload, or an exception to raise."""
    tools, sent = WebTools({'search': {'enabled': True, **search}}), []
    tools.STAT_API_PAUSE = 0

    async def request(url, **kwargs):
        sent.append((url, kwargs))
        answer = bulk if 'downloadformat=csv' in url else api
        answer = answer(url) if callable(answer) else answer
        if isinstance(answer, Exception) or answer is None:
            raise answer or WebToolError('Web request failed: timeout waiting for the response (20 s limit)')
        return (answer if isinstance(answer, bytes) else json.dumps(answer).encode()), 'application/octet-stream', url
    tools._request = request
    return tools, sent


BULK = 'https://api.worldbank.org/v2/en/indicator/NY.GDP.MKTP.KD.ZG?downloadformat=csv'


def test_stat_lookup_reads_one_small_file_per_indicator_without_a_search():
    async def run():
        tools, sent = lookup_tools(bulk=bulk_zip())
        assert 'stat_lookup' in {item['name'] for item in tools.schemas()}
        result = await tools.execute('stat_lookup', {'countries': ['日本', '米国', 'ドイツ'], 'indicator': 'GDP成長率', 'start_year': 2022, 'end_year': 2024})
        assert sent == [(BULK, {'wait': 20, 'size': statdata.MAX_ZIP_BYTES})]
        assert result['source'] == 'worldbank' and result['source_name'] == 'World Bank Open Data' and result['unit'] == 'annual %'
        assert result['as_of'] == '2026-07-01' and result['as_of_basis'] == 'provider_updated'
        assert result['untrusted'] is True and result['years'] == [2022, 2024]
        assert result['read_from'] == BULK and result['last_updated'] == '2026-07-01'
        assert result['url'] == 'https://api.worldbank.org/v2/country/JPN;USA;DEU/indicator/NY.GDP.MKTP.KD.ZG?format=json&date=2022:2024&per_page=1000'
        assert result['page_url'] == 'https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=JP-US-DE'
        assert result['indicator'] == {'id': 'NY.GDP.MKTP.KD.ZG', 'name': 'GDP growth (annual %)'}
        assert [(row['code'], row['latest']) for row in result['series']] == [
            ('JPN', {'year': 2023, 'value': 1.48}), ('USA', {'year': 2023, 'value': 2.89})]
        assert result['no_values'] == ['DEU'] and 'DEU' in result['note']
        # The same figures again, and other countries or years of the same indicator, cost no request.
        again = await tools.execute('stat_lookup', {'countries': ['JPN', 'USA', 'DEU'], 'indicator': 'gdp_growth', 'start_year': 2022, 'end_year': 2024})
        world = await tools.execute('stat_lookup', {'countries': ['世界'], 'indicator': 'gdp_growth'})
        assert again is result and world['series'][0]['code'] == 'WLD' and len(sent) == 1
        assert tools.use == {'sent': 0, 'reused': 0, 'similar': 0, 'lookups': 2}
        for bad in ({'countries': ['Japan']}, {'indicator': 'population'}, {'countries': ['Japan'], 'indicator': 'population', 'host': 'x'},
                    {'countries': ['Atlantis'], 'indicator': 'population'}, {'countries': ['Japan'], 'indicator': 'vibes'}):
            with pytest.raises(WebToolError):
                await tools.execute('stat_lookup', bad)
        assert len(sent) == 1
        off = WebTools({'search': {'enabled': False}})
        assert off.schemas() == []
        with pytest.raises(WebToolError, match='disabled'):
            await off.execute('stat_lookup', {'countries': ['Japan'], 'indicator': 'population'})
    asyncio.run(run())


def test_the_file_is_kept_for_a_day_and_an_older_copy_serves_when_nothing_newer_can_be_had(tmp_path):
    async def run():
        store = statdata.IndicatorStore(tmp_path / 'stat-cache')
        ask = {'countries': ['Japan'], 'indicator': 'gdp_growth', 'start_year': 2023, 'end_year': 2023}
        tools, sent = lookup_tools(bulk=bulk_zip())
        tools.use_stat_store(store)
        assert (await tools.execute('stat_lookup', ask))['series'][0]['latest']['value'] == 1.48 and len(sent) == 1
        kept = tmp_path / 'stat-cache' / 'wb_NY.GDP.MKTP.KD.ZG.zip'
        assert kept.read_bytes() == bulk_zip() and [item.name for item in kept.parent.iterdir()] == [kept.name]
        # Another run of the application the same day: nothing is requested.
        later, sent = lookup_tools(bulk=WebToolError('must not be asked'))
        later.use_stat_store(store)
        assert (await later.execute('stat_lookup', ask))['series'][0]['latest']['value'] == 1.48 and sent == []
        # Two days later the file is fetched again and replaced.
        os.utime(kept, (time.time() - 2 * 86400,) * 2)
        fresh = bulk_zip([('JPN', 'JP', 'Japan', 2023, 1.5)])
        newer, sent = lookup_tools(bulk=fresh)
        newer.use_stat_store(store)
        assert (await newer.execute('stat_lookup', ask))['series'][0]['latest']['value'] == 1.5 and len(sent) == 1
        assert kept.read_bytes() == fresh
        # The World Bank cannot be reached and the copy is old: the old copy still answers.
        os.utime(kept, (time.time() - 5 * 86400,) * 2)
        down, sent = lookup_tools()
        down.use_stat_store(store)
        answer = await down.execute('stat_lookup', ask)
        assert answer['series'][0]['latest']['value'] == 1.5 and [url for url, _ in sent] == [BULK]
        # A damaged copy is not trusted: it is fetched again.
        kept.write_bytes(b'PK\x03\x04damaged')
        repaired, sent = lookup_tools(bulk=bulk_zip())
        repaired.use_stat_store(store)
        assert (await repaired.execute('stat_lookup', ask))['series'][0]['latest']['value'] == 1.48 and len(sent) == 1
        assert kept.read_bytes() == bulk_zip()
        # Names that are not indicator codes never become file names.
        for odd in ('../x', 'CON', 'a/b', ''):
            assert store.get(odd) is None
            store.put(odd, b'x')
        assert [item.name for item in kept.parent.iterdir()] == [kept.name]
    asyncio.run(run())


def test_the_json_api_is_the_fallback_one_country_at_a_time_with_a_long_wait_and_one_retry():
    async def run():
        attempts = {}

        def api(url):
            country = url.split('/country/')[1].split('/')[0]
            attempts[country] = attempts.get(country, 0) + 1
            if country == 'DEU' or (country == 'USA' and attempts[country] == 1):
                return None  # times out (USA only the first time)
            return world_bank([row for row in ROWS if row[0] == country])
        tools, sent = lookup_tools(api=api)
        result = await tools.execute('stat_lookup', {'countries': ['JPN', 'USA', 'DEU'], 'indicator': 'gdp_growth', 'start_year': 2022, 'end_year': 2023})
        assert [url for url, _ in sent] == [BULK] + [
            f'https://api.worldbank.org/v2/country/{country}/indicator/NY.GDP.MKTP.KD.ZG?format=json&date=2022:2023&per_page=1000'
            for country in ('JPN', 'USA', 'USA', 'DEU', 'DEU')]
        assert all(options == {'wait': 75} for _url, options in sent[1:])
        assert [row['code'] for row in result['series']] == ['JPN', 'USA'] and result['series'][1]['latest'] == {'year': 2023, 'value': 2.89}
        assert 'Not read' in result['note'] and 'DEU' in result['note'] and result['read_from'] == result['url']
        # Nothing answers at all: one plain error, and the model is told not to repeat it.
        tools, sent = lookup_tools()
        with pytest.raises(WebToolError, match='could not be read: Web request failed: timeout.*Do not repeat'):
            await tools.execute('stat_lookup', {'countries': ['JPN'], 'indicator': 'population'})
        assert len(sent) == 3
        # The whole fallback is bounded: past its time no further country is tried.
        tools, sent = lookup_tools(api=lambda url: world_bank(ROWS))
        tools.STAT_API_SECONDS = -1
        with pytest.raises(WebToolError, match='could not be read'):
            await tools.execute('stat_lookup', {'countries': ['JPN', 'USA'], 'indicator': 'gdp_growth'})
        assert [url for url, _ in sent] == [BULK]
    asyncio.run(run())


@pytest.mark.asyncio
async def test_figures_read_directly_can_be_cited_and_the_model_is_told_to_use_them_first(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    engine.settings.value['search'].update(enabled=True)
    try:
        run, pm = await start(engine, task='日米のGDP成長率を比べて', max_workers=0)

        async def request(url, **kwargs):
            assert 'downloadformat=csv' in url
            return bulk_zip(), 'application/zip', url
        run['_web']._request = request
        assert run['_web']._stat_store is engine.stat_store and engine.stat_store.directory == engine.settings.directory / 'stat-cache'
        policy = engine._policy(run, pm)
        assert 'stat_lookup first' in policy and 'about 20 searches' in policy
        assert 'stat_lookup' in {tool['name'] for tool in engine.tool_schemas(run, pm)} if hasattr(engine, 'tool_schemas') else True
        result = await engine.execute_tool(run, pm, 'stat_lookup', {'countries': ['Japan', 'United States'], 'indicator': 'gdp_growth'})
        assert result['series'][0]['latest'] == {'year': 2023, 'value': 1.48}
        for url in (result['url'], result['page_url']):
            assert sources.normalize(url) in {sources.normalize(known) for known in run['_known_urls']}, url
            kind, start_text = run['_pages'][sources.normalize(url)]
            assert kind == 'fetched' and 'GDP growth (annual %)' in start_text and 'Japan 2023: 1.48' in start_text
        assert run['search_use'] == {'sent': 0, 'reused': 0, 'similar': 0, 'lookups': 1}
        engine.settings.value['search']['enabled'] = False
        run['_config']['search']['enabled'] = False
        with pytest.raises(ValueError, match='無効'):
            await engine.execute_tool(run, pm, 'stat_lookup', {'countries': ['Japan'], 'indicator': 'population'})
    finally:
        await engine.close()


# --- a guide for one piece of work ---------------------------------------------------------------------

def test_the_model_is_reminded_from_half_of_the_guide_and_told_to_stop_past_it(tmp_path):
    async def run():
        page, calls = pages({'web': [WEB], 'bing': [WEB], 'html': [WEB]})
        tools = WebTools({'search': {'enabled': True, 'provider': 'browser', 'run_guide': 4}})
        tools.use_browser(page)
        tools.use_search_cache(SearchCache(tmp_path / 'search-cache.json'))
        answers = [await tools.execute('web_search', {'query': f'topic number {index} alpha{index} beta{index} gamma{index}'}) for index in range(5)]
        assert len(calls) == 5
        assert 'guide' not in answers[0]['search_budget'] and 'notice' not in answers[0]['search_budget']
        assert answers[1]['search_budget']['used'] == 2 and answers[1]['search_budget']['guide'] == 4
        assert 'Half of this work' in answers[1]['search_budget']['notice'] and 'web_fetch' in answers[1]['search_budget']['notice']
        assert 'Stop searching' in answers[3]['search_budget']['notice'] and 'stat_lookup' in answers[3]['search_budget']['notice']
        assert answers[4]['search_budget']['used'] == 5  # a guide, not a limit: the fifth search was still sent
        # No guide when the human sets 0; and without an allowance there is then nothing to say.
        quiet = WebTools({'search': {'enabled': True, 'provider': 'browser', 'run_guide': 0}})
        quiet.use_browser(page)
        assert 'search_budget' not in await quiet.execute('web_search', {'query': 'another matter entirely'})
    asyncio.run(run())
    raw = json.loads(json.dumps(DEFAULT))
    assert raw['search']['run_guide'] == 20 and validate_settings(raw)['search']['run_guide'] == 20
    for bad in (-1, 1001, 2.5, '20', True):
        raw['search']['run_guide'] = bad
        with pytest.raises(ValueError, match='目安'):
            validate_settings(raw)
    with pytest.raises(WebToolError, match='run_guide'):
        WebTools({'search': {'enabled': True, 'run_guide': 'many'}})


# --- practically the same question -----------------------------------------------------------------------

def test_a_very_similar_question_is_answered_from_this_runs_earlier_search_once(tmp_path):
    assert query_words('site:worldbank.org "United States" GDP growth (annual %) 2023') == frozenset(
        {'worldbank', 'united', 'states', 'gdp', 'growth', 'annual', '2023'})

    async def run():
        page, calls = pages({'web': [WEB], 'bing': [WEB], 'html': [WEB]})
        tools = WebTools({'search': {'enabled': True, 'provider': 'browser', 'run_guide': 0}})
        tools.use_browser(page)
        tools.use_search_cache(SearchCache(tmp_path / 'search-cache.json'))
        first = await tools.execute('web_search', {'query': 'World Bank Japan GDP growth annual percent', 'limit': 5})
        assert len(calls) == 1 and 'similar_to' not in first
        # Another worker asks the same in slightly different words: no search, the earlier results, and it says so.
        second = await tools.execute('web_search', {'query': 'site:worldbank.org Japan "GDP growth (annual %)" World Bank data', 'limit': 1})
        assert len(calls) == 1 and second['similar_to'] == 'World Bank Japan GDP growth annual percent'
        assert second['cached'] is True and second['results'] == first['results'][:1] and 'exactly the same query once more' in second['note']
        assert second['query'] == 'site:worldbank.org Japan "GDP growth (annual %)" World Bank data'
        # Insisting on exactly that query sends it.
        third = await tools.execute('web_search', {'query': 'site:worldbank.org Japan "GDP growth (annual %)" World Bank data', 'limit': 1})
        assert len(calls) == 2 and 'similar_to' not in third
        # Another country or another year is another question, however alike the rest.
        await tools.execute('web_search', {'query': 'World Bank Germany GDP growth annual percent'})
        await tools.execute('web_search', {'query': 'World Bank Japan GDP growth annual percent 2023'})
        await tools.execute('web_search', {'query': 'World Bank 日本 ドイツ GDP growth annual percent'})
        assert len(calls) == 5
        # So is a question that shares only a few words.
        await tools.execute('web_search', {'query': 'Japan unemployment rate youth labour survey'})
        assert len(calls) == 6
        assert tools.use == {'sent': 6, 'reused': 0, 'similar': 1, 'lookups': 0}
        # The exact question again (any wording the cache treats as equal) is still free.
        await tools.execute('web_search', {'query': 'percent annual growth GDP Japan Bank World'})
        assert len(calls) == 6 and tools.use['reused'] == 1
    asyncio.run(run())


# --- nobody answers the request to pass a bot check --------------------------------------------------------

@pytest.mark.asyncio
async def test_an_unanswered_human_check_ends_and_the_run_goes_on_without_search(tmp_path, monkeypatch):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    monkeypatch.setattr(type(engine), 'SEARCH_CHECK_ANSWER_SECONDS', 0.3)
    attach = browser_run(engine, {'web': [WEB_CHECK], 'bing': [WEB_CHECK], 'html': [DDG_CHECK]})
    try:
        run, pm = await start(engine, task='各国のGDP成長率を調べて', max_workers=0)
        calls = attach(run)
        assert 'not available in this work' not in engine._policy(run, pm)
        search = asyncio.ensure_future(engine.execute_tool(run, pm, 'web_search', {'query': 'United States GDP growth'}))
        for _ in range(100):
            await asyncio.sleep(.01)
            if pm.approval:
                break
        shown = pm.public()['approval']
        assert shown['tool'] == 'search_human_check' and shown['expires_at'] == pytest.approx(shown['requested_at'] + 0.3)
        assert '応答がない場合も、却下と同じ扱い' in shown['summary']
        with pytest.raises(ValueError, match='この作業では Web 検索は使えません.*stat_lookup'):
            await asyncio.wait_for(search, 3)
        assert pm.approval is None and pm.status != 'waiting' and not any(call[2] for call in calls), 'no window without a person'
        assert any(event['kind'] == 'approval_resolved' and '期限が切れました' in event['text'] for event in engine.events)
        # Decided for this run: nothing more is sent or asked, and every agent is told at its next turn.
        sent = len(calls)
        with pytest.raises(ValueError, match='この作業では Web 検索は使えません'):
            await engine.execute_tool(run, pm, 'web_search', {'query': 'another question'})
        assert len(calls) == sent and pm.approval is None
        assert 'Web search is not available in this work' in engine._policy(run, pm)
        # An answer after the deadline finds nothing to answer.
        with pytest.raises(ValueError, match='すでに終わっています'):
            engine.resolve_approval(pm.id, {'approval_id': shown['id'], 'decision': 'approve'})

        # Reading statistics directly still works.
        async def request(url, **kwargs):
            return bulk_zip(), 'application/zip', url
        run['_web']._request = request
        assert (await engine.execute_tool(run, pm, 'stat_lookup', {'countries': ['USA'], 'indicator': 'gdp_growth'}))['series'][0]['code'] == 'USA'
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_other_approvals_still_wait_for_the_human(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='x', max_workers=0)
        waiting = asyncio.ensure_future(engine._await_approval(run, pm, 'python_execute', {'code': 'print(1)'}))
        await asyncio.sleep(.2)
        assert not waiting.done() and 'expires_at' not in pm.public()['approval']
        engine.resolve_approval(pm.id, {'approval_id': pm.approval['id'], 'decision': 'approve'})
        await waiting
    finally:
        await engine.close()


def test_an_http_202_is_named_as_a_likely_browser_check_and_not_to_be_retried():
    from workbench.webtools import _HTTPStatusError
    text = str(_HTTPStatusError(202))
    assert text.startswith('Web service returned HTTP 202 (') and 'browser check' in text and 'Do not retry this URL' in text
    assert str(_HTTPStatusError(404)) == 'Web service returned HTTP 404 (not found)'
