"""Fewer searches per piece of work: statistics read directly, a search guide, similar questions, and an
unanswered human check that does not hold the run for ever.

No network: the World Bank answer is a fixture and the browser is a function returning prepared HTML.
"""
import asyncio
import json

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


# --- the tool ------------------------------------------------------------------------------------------

def lookup_tools(payload, **search):
    tools, sent = WebTools({'search': {'enabled': True, **search}}), []

    async def request(url, **kwargs):
        sent.append((url, kwargs))
        return json.dumps(payload).encode(), 'application/json;charset=utf-8', url
    tools._request = request
    return tools, sent


def test_stat_lookup_reads_the_figures_without_a_search():
    async def run():
        tools, sent = lookup_tools(world_bank(ROWS))
        assert 'stat_lookup' in {item['name'] for item in tools.schemas()}
        result = await tools.execute('stat_lookup', {'countries': ['日本', '米国', 'ドイツ'], 'indicator': 'GDP成長率', 'start_year': 2022, 'end_year': 2024})
        assert sent == [('https://api.worldbank.org/v2/country/JPN;USA;DEU/indicator/NY.GDP.MKTP.KD.ZG?format=json&date=2022:2024&per_page=1000', {})]
        assert result['source'] == 'World Bank Open Data' and result['untrusted'] is True and result['years'] == [2022, 2024]
        assert result['url'] == sent[0][0] and result['page_url'] == 'https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=JP-US-DE'
        assert [row['code'] for row in result['series']] == ['JPN', 'USA'] and result['no_values'] == ['DEU'] and 'DEU' in result['note']
        # The same figures again cost no request; nothing is counted against the searches.
        again = await tools.execute('stat_lookup', {'countries': ['JPN', 'USA', 'DEU'], 'indicator': 'gdp_growth', 'start_year': 2022, 'end_year': 2024})
        assert again is result and len(sent) == 1
        assert tools.use == {'sent': 0, 'reused': 0, 'similar': 0, 'lookups': 1}
        for bad in ({'countries': ['Japan']}, {'indicator': 'population'}, {'countries': ['Japan'], 'indicator': 'population', 'host': 'x'},
                    {'countries': ['Atlantis'], 'indicator': 'population'}, {'countries': ['Japan'], 'indicator': 'vibes'}):
            with pytest.raises(WebToolError):
                await tools.execute('stat_lookup', bad)
        assert len(sent) == 1
        tools, _ = lookup_tools('<html>not json</html>')
        tools._request = lambda url, **kwargs: asyncio.sleep(0, (b'<html>', 'text/html', url))
        with pytest.raises(WebToolError, match='could not be read as JSON'):
            await tools.execute('stat_lookup', {'countries': ['Japan'], 'indicator': 'population'})
        off = WebTools({'search': {'enabled': False}})
        assert off.schemas() == []
        with pytest.raises(WebToolError, match='disabled'):
            await off.execute('stat_lookup', {'countries': ['Japan'], 'indicator': 'population'})
    asyncio.run(run())


@pytest.mark.asyncio
async def test_figures_read_directly_can_be_cited_and_the_model_is_told_to_use_them_first(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    engine.settings.value['search'].update(enabled=True)
    try:
        run, pm = await start(engine, task='日米のGDP成長率を比べて', max_workers=0)

        async def request(url, **kwargs):
            return json.dumps(world_bank(ROWS)).encode(), 'application/json', url
        run['_web']._request = request
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
            return json.dumps(world_bank(ROWS)).encode(), 'application/json', url
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
