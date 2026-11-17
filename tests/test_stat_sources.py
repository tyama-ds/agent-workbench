"""Official statistics from the IMF, Eurostat and the ILO through stat_lookup.

No network. The answers are fixtures in the layouts the three standards
describe (SDMX-JSON, SDMX-ML, JSON-stat); the address shapes are the ones that
answered from a real machine.
"""
import asyncio
import json
import os
import time

import pytest

from workbench import statdata, statsources
from workbench.webtools import WebToolError, WebTools, _HTTPStatusError


# --- fixtures -----------------------------------------------------------------------------------------

def imf_json(country='JPN', name='Japan', values=((2022, '0.954'), (2023, '1.475'), (2024, '0.104'), (2027, '0.6')), version=2):
    """SDMX-JSON: version 2 keeps the description under data.structures, version 1 under structure."""
    structure = {'dimensions': {
        'series': [{'id': 'COUNTRY', 'values': [{'id': country, 'name': name}]},
                   {'id': 'INDICATOR', 'values': [{'id': 'NGDP_RPCH', 'name': 'Gross domestic product, constant prices, percent change'}]},
                   {'id': 'FREQUENCY', 'values': [{'id': 'A', 'name': 'Annual'}]}],
        # As the IMF really answers: a time period is {"value": "1980"}, without an "id".
        'observation': [{'id': 'TIME_PERIOD', 'values': [{'value': str(year)} if version == 2 else {'id': str(year)}
                                                         for year, _ in values]}]}}
    data_set = {'series': {'0:0:0': {'observations': {str(index): [value] for index, (_, value) in enumerate(values)}}}}
    if version == 2:
        return {'meta': {'prepared': '2026-11-01T00:00:00Z'}, 'data': {'dataSets': [data_set], 'structures': [structure]}}
    return {'header': {}, 'dataSets': [data_set], 'structure': structure}


def ilo_xml(rows=(('JPN', ((2022, '2.6'), (2023, '2.6'))), ('DEU', ((2022, '3.1'), (2023, '3.0')))), generic=False, extra=''):
    if generic:
        body = ''.join(
            f'<generic:Series><generic:SeriesKey><generic:Value id="REF_AREA" value="{code}"/><generic:Value id="FREQ" value="A"/>'
            f'<generic:Value id="SEX" value="SEX_T"/></generic:SeriesKey>'
            + ''.join(f'<generic:Obs><generic:ObsDimension value="{year}"/><generic:ObsValue value="{value}"/></generic:Obs>'
                      for year, value in values) + '</generic:Series>' for code, values in rows)
        return (f'<?xml version="1.0"?>{extra}<message:GenericData xmlns:message="m" xmlns:generic="g"><message:Header/>'
                f'<message:DataSet>{body}</message:DataSet></message:GenericData>').encode()
    body = ''.join(f'<Series REF_AREA="{code}" FREQ="A" MEASURE="UNE_DEAP_RT" SEX="SEX_T" AGE="AGE_YTHADULT_YGE15">'
                   + ''.join(f'<Obs TIME_PERIOD="{year}" OBS_VALUE="{value}" OBS_STATUS="A"/>' for year, value in values) + '</Series>'
                   for code, values in rows)
    return (f'<?xml version="1.0" encoding="UTF-8"?>{extra}<message:StructureSpecificData xmlns:message="m" xmlns:ns1="d">'
            f'<message:Header><message:Prepared>2026-11-17T00:00:00</message:Prepared></message:Header>'
            f'<message:DataSet>{body}</message:DataSet></message:StructureSpecificData>').encode()


def eurostat_json(geos=('DE', 'FR'), years=(2022, 2023, 2024), units=('PC_ACT',), values=None, label='Total unemployment rate'):
    """JSON-stat 2.0 with dimensions freq, unit, geo, time; ``values`` by flat index (sparse, as Eurostat sends them)."""
    size = [1, len(units), len(geos), len(years)]
    if values is None:
        values = {str(index): round(3 + index * 0.1, 1) for index in range(len(units) * len(geos) * len(years))}
    return {'version': '2.0', 'class': 'dataset', 'label': label, 'source': 'ESTAT', 'updated': '2026-10-30T23:00:00+0100',
            'value': values, 'id': ['freq', 'unit', 'geo', 'time'], 'size': size,
            'dimension': {'freq': {'category': {'index': {'A': 0}, 'label': {'A': 'Annual'}}},
                          'unit': {'category': {'index': {unit: index for index, unit in enumerate(units)},
                                                'label': {'PC_ACT': 'Percentage of population in the labour force',
                                                          'THS_PER': 'Thousand persons'}}},
                          'geo': {'category': {'index': {geo: index for index, geo in enumerate(geos)},
                                               'label': {'DE': 'Germany', 'FR': 'France', 'EL': 'Greece', 'UK': 'United Kingdom'}}},
                          'time': {'category': {'index': {str(year): index for index, year in enumerate(years)}}}}}


def tools_with(answers, **search):
    """WebTools whose requests are answered from ``answers``: {substring of the address: bytes | payload | exception | callable}."""
    tools, sent = WebTools({'search': {'enabled': True, **search}}), []
    tools.STAT_API_PAUSE, tools.STAT_PAUSE = 0, dict.fromkeys(statsources.PROVIDERS, 0)

    async def request(url, **options):
        sent.append((url, options))
        answer = next((value for part, value in answers.items() if part in url), None)
        answer = answer(url) if callable(answer) else answer
        if isinstance(answer, Exception) or answer is None:
            raise answer or WebToolError('Web request failed: timeout waiting for the response (30 s limit)')
        return (answer if isinstance(answer, bytes) else json.dumps(answer).encode()), 'application/json', url
    tools._request = request
    return tools, sent


# --- choosing a provider and an indicator ---------------------------------------------------------------

def test_a_provider_and_its_indicators_are_named_in_plain_words():
    assert [statsources.source(name) for name in (None, 'worldbank', 'World Bank', '世界銀行', 'IMF', 'weo', 'Eurostat', 'ILO', 'ilostat')] == [
        'worldbank', 'worldbank', 'worldbank', 'worldbank', 'imf', 'imf', 'eurostat', 'ilo', 'ilo']
    for bad in ('un', '', 'https://example.org', 5):
        with pytest.raises(ValueError, match='source must be one of: worldbank, imf, eurostat, ilo, oecd'):
            statsources.source(bad)
    assert statsources.indicator('imf', 'GDP成長率')[1][0] == 'NGDP_RPCH' and statsources.indicator('imf', 'unemployment rate')[0] == 'unemployment'
    assert statsources.indicator('imf', 'ngdp_rpch')[0] == 'gdp_growth'             # a WEO code that has a plain name
    assert statsources.indicator('imf', 'BCA_NGDPD') == ('BCA_NGDPD', ('BCA_NGDPD', '', ''))  # any other WEO series, by code
    assert statsources.indicator('eurostat', '失業率')[1][0] == 'tps00203' and statsources.indicator('ilo', '若年失業率')[0] == 'youth_unemployment'
    with pytest.raises(ValueError, match='Eurostat has no built-in indicator .*Available from this source: population, gdp_growth'):
        statsources.indicator('eurostat', 'fertility')
    with pytest.raises(ValueError, match='has no built-in indicator'):
        statsources.indicator('ilo', '../x')
    # The same plain name means the same thing at every provider that has it.
    for key in ('population', 'gdp_growth', 'inflation', 'unemployment', 'government_debt'):
        assert key in statdata.INDICATORS and key in statsources.IMF and (key in statsources.EUROSTAT)


def test_requests_go_to_fixed_addresses_built_from_codes_only():
    imf = statsources.plan('imf', 'gdp_growth', ['日本', 'USA', 'ドイツ'], None, None, 2026)
    assert [url for url, _ in imf['requests']] == [
        f'https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/{code}.NGDP_RPCH.A' for code in ('JPN', 'USA', 'DEU')]
    assert imf['page'] == 'https://www.imf.org/external/datamapper/NGDP_RPCH@WEO' and (imf['start'], imf['end']) == (2017, 2026)
    assert imf['unit'] == 'percent change' and statsources.plan('imf', 'population', ['JPN'], 2020, 2024, 2026)['unit'] == 'millions of persons'
    euro = statsources.plan('eurostat', 'unemployment', ['Germany', 'Greece', 'UK', 'Japan', 'EU'], 2020, 2024, 2026)
    assert euro['requests'] == [('https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tps00203'
                                 '?format=JSON&lang=EN&geo=DE&geo=EL&geo=UK&geo=JP&geo=EU27_2020', ['DEU', 'GRC', 'GBR', 'JPN', 'EUU'])]
    assert euro['page'] == 'https://ec.europa.eu/eurostat/databrowser/view/tps00203/default/table?lang=en'
    # The ILO: one country per request and only the latest years, the shape that answered in two seconds.
    ilo = statsources.plan('ilo', 'unemployment', ['JPN', 'DEU'], 2020, 2024, 2026)
    assert ilo['requests'] == [(f'https://sdmx.ilo.org/rest/data/ILO,DF_UNE_DEAP_SEX_AGE_RT/{code}.A..SEX_T.AGE_YTHADULT_YGE15'
                                '?lastNObservations=7', [code]) for code in ('JPN', 'DEU')]
    # The OECD: the three keys that answered from a real machine, with the countries in their place.
    base = 'https://sdmx.oecd.org/public/rest/data/'
    assert statsources.plan('oecd', '失業率', ['JPN', 'USA', 'DEU'], 2024, 2025, 2026)['requests'] == [(
        base + 'OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0/JPN+USA+DEU..._Z.Y._T.Y_GE15..A?startPeriod=2024&format=csvfilewithlabels',
        ['JPN', 'USA', 'DEU'])]
    assert statsources.plan('oecd', 'gdp_growth', ['JPN', 'USA', 'DEU'], 2024, 2025, 2026)['requests'][0][0] == (
        base + 'OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD,/A..JPN+USA+DEU.S1..B1GQ......GY.?startPeriod=2024&format=csvfilewithlabels')
    assert statsources.plan('oecd', '失業率', ['JPN', 'USA'], 2024, 2025, 2026)['page'] == (
        'https://data-explorer.oecd.org/vis?df%5Bds%5D=dsDisseminateFinalDMZ&df%5Bid%5D=DSD_LFS%40DF_IALFS_UNE_M&df%5Bag%5D=OECD.SDD.TPS'
        '&dq=JPN%2BUSA..._Z.Y._T.Y_GE15..A')                # the table and selection themselves, not the site's front page
    assert statsources.plan('oecd', 'inflation', ['USA', 'DEU'], 2024, 2025, 2026)['requests'][0][0] == (
        base + 'OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/USA+DEU.A.N.CPI.PA._T.N.GY?startPeriod=2024&format=csvfilewithlabels')
    with pytest.raises(ValueError, match='OECD Data Explorer has no built-in indicator .*Available from this source: unemployment, gdp_growth, inflation'):
        statsources.plan('oecd', 'population', ['JPN'], None, None, 2026)
    for countries, first, last in (([], None, None), (['Atlantis'], None, None), (['JPN'], 2025, 2020), (['JPN'], 1900, None)):
        with pytest.raises(ValueError):
            statsources.plan('imf', 'population', countries, first, last, 2026)


# --- reading the three layouts ---------------------------------------------------------------------------

@pytest.mark.parametrize('version', [1, 2])
def test_sdmx_json_series_are_read_in_both_layouts(version):
    rows = statsources.sdmx_json(imf_json(version=version))
    assert len(rows) == 1 and rows[0]['dims']['COUNTRY'] == ('JPN', 'Japan') and rows[0]['dims']['INDICATOR'][0] == 'NGDP_RPCH'
    assert rows[0]['obs'] == {'2022': 0.954, '2023': 1.475, '2024': 0.104, '2027': 0.6}
    plan = statsources.plan('imf', 'gdp_growth', ['JPN'], 2022, 2025, 2026)
    found, label, updated, remarks = statsources.read('imf', json.dumps(imf_json(version=version)).encode(), plan, ['JPN'])
    assert found == {'JPN': ('Japan', [{'year': 2022, 'value': 0.954}, {'year': 2023, 'value': 1.475}, {'year': 2024, 'value': 0.104}])}
    assert label == 'Gross domestic product, constant prices, percent change' and updated == '' and remarks == []  # 2027 is outside the asked years


def test_sdmx_json_with_all_dimensions_at_the_observation_and_odd_answers():
    flat = {'data': {'dataSets': [{'observations': {'0:0:0:0': [1.5, 0], '0:0:0:1': [None], '0:0:0:2': ['NaN'], '0:0:0:3': ['2.5']}}],
                     'structures': [{'dimensions': {'observation': [
                         {'id': 'REF_AREA', 'values': [{'id': 'DEU', 'name': 'Germany'}]}, {'id': 'MEASURE', 'values': [{'id': 'X'}]},
                         {'id': 'FREQ', 'values': [{'id': 'A'}]},
                         {'id': 'TIME_PERIOD', 'values': [{'id': '2021'}, {'id': '2022'}, {'id': '2023'}, {'id': '2024-Q1'}]}]}}]}}
    rows = statsources.sdmx_json(flat)
    assert len(rows) == 1 and rows[0]['obs'] == {'2021': 1.5, '2024-Q1': 2.5}
    assert statsources._annual(rows[0]['obs'], 2000, 2030) == [{'year': 2021, 'value': 1.5}]  # a quarter is not a year
    for odd, problem in (({}, 'not an SDMX data message \\(received an object with no keys\\)'), ([1, 2], 'received a list of 2'),
                         ({'errors': [{'code': 404}]}, 'received an object with errors'),
                         ({'dataSets': [], 'structure': {}}, 'no description of its dimensions')):
        with pytest.raises(ValueError, match=problem):
            statsources.sdmx_json(odd)
    with pytest.raises(ValueError, match='neither JSON nor XML'):
        statsources.sdmx(b'Service unavailable')


@pytest.mark.parametrize('generic', [False, True])
def test_sdmx_xml_series_are_read_in_both_layouts_and_entities_are_refused(generic):
    rows = statsources.sdmx_xml(ilo_xml(generic=generic))
    assert [(row['dims']['REF_AREA'][0], row['obs']) for row in rows] == [
        ('JPN', {'2022': 2.6, '2023': 2.6}), ('DEU', {'2022': 3.1, '2023': 3.0})]
    plan = statsources.plan('ilo', 'unemployment', ['JPN', 'DEU', 'USA'], 2023, 2024, 2026)
    found, label, updated, remarks = statsources.read('ilo', ilo_xml(generic=generic), plan, ['JPN', 'DEU', 'USA'])
    assert found == {'JPN': ('', [{'year': 2023, 'value': 2.6}]), 'DEU': ('', [{'year': 2023, 'value': 3.0}])} and updated == '' and remarks == []
    bomb = ilo_xml(generic=generic, extra='<!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>')
    with pytest.raises(ValueError, match='declares entities'):
        statsources.sdmx_xml(bomb)
    with pytest.raises(ValueError, match='not readable XML'):
        statsources.sdmx_xml(b'<a><b></a>')
    with pytest.raises(ValueError, match='not an SDMX data message \\(its root is html\\)'):
        statsources.sdmx_xml(b'<html><body>busy</body></html>')
    assert statsources.sdmx_xml(b'<message:StructureSpecificData xmlns:message="m"><message:DataSet/></message:StructureSpecificData>') == []


def test_two_series_for_one_country_are_an_error_not_a_choice():
    twice = ilo_xml(rows=(('JPN', ((2023, '2.6'),)),)).replace(
        b'</message:DataSet>', b'<Series REF_AREA="JPN" FREQ="A" MEASURE="OTHER" SEX="SEX_T" AGE="AGE_YTHADULT_YGE15">'
                               b'<Obs TIME_PERIOD="2023" OBS_VALUE="9.9"/></Series></message:DataSet>')
    plan = statsources.plan('ilo', 'unemployment', ['JPN'], 2023, 2023, 2026)
    with pytest.raises(ValueError, match='2 different series for JPN \\(MEASURE: OTHER / UNE_DEAP_RT\\).*does not choose'):
        statsources.read('ilo', twice, plan, ['JPN'])


def test_several_records_of_one_series_are_one_statistic_and_the_latest_is_used_with_a_remark():
    """Real-machine case: the ILO answered with two series for Japan that did not differ in any dimension."""
    survey = ('<Series REF_AREA="JPN" FREQ="A" MEASURE="UNE_DEAP_RT" SEX="SEX_T" AGE="AGE_YTHADULT_YGE15">'
              '<Obs TIME_PERIOD="2022" OBS_VALUE="2.6" SOURCE="BA:2244 - Labour Force Survey"/>'
              '<Obs TIME_PERIOD="2023" OBS_VALUE="2.6" SOURCE="BA:2244 - Labour Force Survey"/>'
              '<Obs TIME_PERIOD="2024" OBS_VALUE="2.5" SOURCE="BA:2244 - Labour Force Survey"/></Series>')
    census = ('<Series REF_AREA="JPN" FREQ="A" MEASURE="UNE_DEAP_RT" SEX="SEX_T" AGE="AGE_YTHADULT_YGE15">'
              '<Obs TIME_PERIOD="2020" OBS_VALUE="3.8" SOURCE="AA:999 - Population Census"/></Series>')
    answer = ('<message:StructureSpecificData xmlns:message="m"><message:DataSet>' + census + survey
              + '</message:DataSet></message:StructureSpecificData>').encode()
    plan = statsources.plan('ilo', 'unemployment', ['JPN'], 2020, 2024, 2026)
    found, _label, _updated, remarks = statsources.read('ilo', answer, plan, ['JPN'])
    assert found['JPN'][1] == [{'year': 2022, 'value': 2.6}, {'year': 2023, 'value': 2.6}, {'year': 2024, 'value': 2.5}]
    assert remarks == ['JPN: the provider keeps 2 records of this series (SOURCE: AA:999 - Population Census | BA:2244 - Labour Force Survey)'
                       '; the one with the most recent year (2024) was used']
    # The same in the generic layout, where attributes are elements; and without any attribute to tell them apart.
    generic = ('<m:GenericData xmlns:m="m" xmlns:g="g"><m:DataSet>'
               + ''.join('<g:Series><g:SeriesKey><g:Value id="REF_AREA" value="JPN"/></g:SeriesKey>'
                         f'<g:Attributes><g:Value id="SOURCE" value="{source}"/></g:Attributes>'
                         f'<g:Obs><g:ObsDimension value="{year}"/><g:ObsValue value="{value}"/></g:Obs></g:Series>'
                         for source, year, value in (('Survey', 2024, '2.5'), ('Census', 2020, '3.8')))
               + '</m:DataSet></m:GenericData>').encode()
    found, _label, _updated, remarks = statsources.read('ilo', generic, plan, ['JPN'])
    assert found['JPN'][1] == [{'year': 2024, 'value': 2.5}] and 'SOURCE: Survey | Census' in remarks[0]
    bare = generic.replace(b'<g:Attributes><g:Value id="SOURCE" value="Survey"/></g:Attributes>', b'').replace(
        b'<g:Attributes><g:Value id="SOURCE" value="Census"/></g:Attributes>', b'')
    assert statsources.read('ilo', bare, plan, ['JPN'])[3] == [
        'JPN: the provider keeps 2 records of this series; the one with the most recent year (2024) was used']


OECD_HEADER = ('STRUCTURE,STRUCTURE_ID,STRUCTURE_NAME,ACTION,REF_AREA,Reference area,MEASURE,Measure,UNIT_MEASURE,Unit of measure,'
               'TRANSFORMATION,Transformation,ADJUSTMENT,Adjustment,SEX,Sex,AGE,Age,ACTIVITY,Economic activity,FREQ,Frequency of observation,'
               'TIME_PERIOD,Time period,OBS_VALUE,Observation value,OBS_STATUS,Observation status,UNIT_MULT,Unit multiplier,DECIMALS,Decimals')


def oecd_csv(rows):
    """SDMX-CSV with labels, as the OECD sends it: (country, name, measure, unit, year, value)."""
    lines = [OECD_HEADER]
    for code, name, measure, unit, year, value in rows:
        lines.append(f'DATAFLOW,OECD.SDD.TPS:DSD_LFS@DF_IALFS_UNE_M(1.0),"Unemployment rates, monthly",I,{code},{name},{measure},'
                     f'"Monthly unemployment rate",{unit},"Percentage of labour force in the same subgroup",_Z,Not applicable,Y,'
                     f'"Calendar and seasonally adjusted",_T,Total,Y_GE15,15 years or over,_Z,Not applicable,A,Annual,'
                     f'{year},,{value},,A,Normal value,0,Units,1,One')
    return ('\ufeff' + '\r\n'.join(lines) + '\r\n').encode()


def test_the_oecd_table_is_read_by_its_code_columns_and_an_open_dimension_takes_the_value_that_is_meant():
    plan = statsources.plan('oecd', 'unemployment', ['JPN', 'USA', 'DEU', 'FRA'], 2024, 2025, 2026)
    codes = ['JPN', 'USA', 'DEU', 'FRA']
    rows = [('JPN', 'Japan', 'UNE_LF_M', 'PT_LF_SUB', 2024, 2.542), ('JPN', 'Japan', 'UNE_LF_M', 'PT_LF_SUB', 2025, 2.508),
            ('USA', 'United States', 'UNE_LF_M', 'PT_LF_SUB', 2024, 4.017), ('DEU', 'Germany', 'UNE_LF_M', 'PT_LF_SUB', 2025, 3.767),
            ('DEU', 'Germany', 'UNE_LF_M', 'PT_LF_SUB', 2023, 3.0), ('USA', 'United States', 'UNE_LF_M', 'PT_LF_SUB', '2025-Q1', 4.1)]
    found, label, updated, remarks = statsources.read('oecd', oecd_csv(rows), plan, codes)
    assert found == {'JPN': ('Japan', [{'year': 2024, 'value': 2.542}, {'year': 2025, 'value': 2.508}]),
                     'USA': ('United States', [{'year': 2024, 'value': 4.017}]),
                     'DEU': ('Germany', [{'year': 2025, 'value': 3.767}])}        # 2023 is outside the years; France is not in the table
    assert label.startswith('Monthly unemployment rate — Percentage of labour force in the same subgroup') and updated == '' and remarks == []
    # The key leaves the measure and its unit open: the rate is taken where a level in thousands also comes back.
    both = rows + [('JPN', 'Japan', 'UNE_LF_M', 'PS', 2025, 1730), ('JPN', 'Japan', 'UNE', 'PS', 2025, 1730)]
    assert statsources.read('oecd', oecd_csv(both), plan, codes)[0]['JPN'][1][-1] == {'year': 2025, 'value': 2.508}
    # Values this indicator does not mean are never chosen between.
    odd = [('JPN', 'Japan', 'X1', 'PS', 2025, 1.0), ('JPN', 'Japan', 'X2', 'PS', 2025, 2.0)]
    with pytest.raises(ValueError, match='2 different series for JPN \\(MEASURE: X1 / X2\\).*does not choose'):
        statsources.read('oecd', oecd_csv(odd), plan, codes)
    for junk, problem in ((b'<html>busy</html>', 'not an SDMX-CSV table .*it begins: <html>busy'), (b'', 'not an SDMX-CSV table'),
                          (b'\xff\xfe', 'not UTF-8'), (b'NoResultsFound', 'it begins: NoResultsFound')):
        with pytest.raises(ValueError, match=problem):
            statsources.read('oecd', junk, plan, codes)
    assert statsources.read('oecd', (OECD_HEADER + '\r\n').encode(), plan, codes)[0] == {}   # a table without rows: no values


def test_json_stat_cells_are_found_by_position_and_the_category_meant_is_chosen_or_refused():
    plan = statsources.plan('eurostat', 'unemployment', ['Germany', 'France', 'Japan'], 2023, 2024, 2026)
    codes = ['DEU', 'FRA', 'JPN']
    found, label, updated, _ = statsources.read('eurostat', json.dumps(eurostat_json()).encode(), plan, codes)
    assert found == {'DEU': ('Germany', [{'year': 2023, 'value': 3.1}, {'year': 2024, 'value': 3.2}]),
                     'FRA': ('France', [{'year': 2023, 'value': 3.4}, {'year': 2024, 'value': 3.5}])}
    assert label == 'Total unemployment rate (Annual; Percentage of population in the labour force)' and updated == '2026-10-30T23:00:00+0100'
    # Two units in the table: the rate is taken, not the thousands, wherever it stands; empty cells are not values.
    both = eurostat_json(units=('THS_PER', 'PC_ACT'), values={'0': 1400, '6': 3.0, '8': 3.2, '9': 7.3})
    found, label, _, _ = statsources.read('eurostat', json.dumps(both).encode(), plan, codes)
    assert found == {'DEU': ('Germany', [{'year': 2024, 'value': 3.2}])} and 'Percentage of population' in label
    as_list = eurostat_json(values=[3.0, 3.1, None, 7.2, 7.3, 7.4])
    assert statsources.read('eurostat', json.dumps(as_list).encode(), plan, codes)[0]['DEU'][1] == [{'year': 2023, 'value': 3.1}]
    # A category this indicator does not mean is never picked silently.
    other = eurostat_json(units=('THS_PER', 'PC_POP'))
    with pytest.raises(ValueError, match='several categories for unit \\(THS_PER, PC_POP\\).*does not choose'):
        statsources.read('eurostat', json.dumps(other).encode(), plan, codes)
    for odd, problem in (({'error': [{'status': 400, 'label': 'Invalid value for geo'}]}, 'not a JSON-stat dataset: Invalid value for geo'),
                         ({'id': ['geo'], 'size': [2], 'dimension': {'geo': {'category': {'index': {'DE': 0}}}}, 'value': []}, 'does not list its 2'),
                         ({'id': ['freq'], 'size': [1], 'dimension': {'freq': {'category': {'index': {'A': 0}}}}, 'value': []}, 'no geo or time')):
        with pytest.raises(ValueError, match=problem):
            statsources.read('eurostat', json.dumps(odd).encode(), plan, codes)
    with pytest.raises(ValueError, match='not JSON'):
        statsources.read('eurostat', b'<html>', plan, codes)
    greece = statsources.plan('eurostat', 'unemployment', ['Greece', 'UK'], 2022, 2024, 2026)
    found, _, _, _ = statsources.read('eurostat', json.dumps(eurostat_json(geos=('EL', 'UK'))).encode(), greece, ['GRC', 'GBR'])
    assert set(found) == {'GRC', 'GBR'} and found['GRC'][0] == 'Greece'


# --- the tool --------------------------------------------------------------------------------------------

def test_stat_lookup_reads_the_imf_one_country_at_a_time_and_says_what_the_figures_are(tmp_path):
    async def run():
        answers = {'/JPN.': imf_json(), '/USA.': imf_json('USA', 'United States', ((2023, '2.9'), (2024, '2.8'))),
                   '/DEU.': _HTTPStatusError(404)}
        tools, sent = tools_with(answers)
        tools.use_stat_store(statdata.IndicatorStore(tmp_path / 'stat-cache'))
        result = await tools.execute('stat_lookup', {'source': 'imf', 'countries': ['日本', '米国', 'ドイツ'], 'indicator': 'GDP成長率',
                                                     'start_year': 2022, 'end_year': 2024})
        base = 'https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/'
        assert [url for url, _ in sent] == [base + 'JPN.NGDP_RPCH.A', base + 'USA.NGDP_RPCH.A', base + 'DEU.NGDP_RPCH.A']  # a 404 is not retried
        assert all(options == {'wait': 45, 'size': statsources.MAX_BYTES, 'accept': '*/*'} for _, options in sent)
        assert result['source'] == 'imf' and result['source_name'] == 'IMF World Economic Outlook' and result['unit'] == 'percent change'
        assert result['indicator'] == {'id': 'NGDP_RPCH', 'name': 'Gross domestic product, constant prices, percent change', 'key': 'gdp_growth'}
        assert [(row['country'], row['code'], row['latest']) for row in result['series']] == [
            ('Japan', 'JPN', {'year': 2024, 'value': 0.104}), ('United States', 'USA', {'year': 2024, 'value': 2.8})]
        assert result['as_of_basis'] == 'retrieved' and result['as_of'] == time.strftime('%Y-%m-%d', time.gmtime())
        assert result['url'] == base + 'JPN.NGDP_RPCH.A' and len(result['urls']) == 3 and result['untrusted'] is True
        assert result['page_url'] == 'https://www.imf.org/external/datamapper/NGDP_RPCH@WEO' and result['no_values'] == []
        assert 'estimates or projections' in result['note'] and 'Not read (Web service returned HTTP 404' in result['note'] and 'DEU' in result['note']
        # The same question again costs nothing, and a second run the same day reads the kept answers.
        assert await tools.execute('stat_lookup', {'source': 'IMF', 'countries': ['JPN', 'USA', 'DEU'], 'indicator': 'gdp_growth',
                                                   'start_year': 2022, 'end_year': 2024}) is result and len(sent) == 3
        later, sent = tools_with({'/DEU.': _HTTPStatusError(404)})
        later.use_stat_store(statdata.IndicatorStore(tmp_path / 'stat-cache'))
        again = await later.execute('stat_lookup', {'source': 'imf', 'countries': ['JPN', 'USA'], 'indicator': 'gdp_growth',
                                                    'start_year': 2022, 'end_year': 2024})
        assert sent == [] and [row['code'] for row in again['series']] == ['JPN', 'USA'] and tools.use['lookups'] == 1
        assert sorted(item.name[:4] for item in (tmp_path / 'stat-cache').iterdir()) == ['imf_', 'imf_']
    asyncio.run(run())


def test_stat_lookup_reads_eurostat_and_the_ilo_and_says_when_a_country_is_not_covered():
    async def run():
        tools, sent = tools_with({'eurostat': eurostat_json(), '/JPN.A': ilo_xml(rows=(('JPN', ((2022, '2.6'), (2023, '2.6'))),)),
                                  '/DEU.A': ilo_xml(rows=(('DEU', ((2022, '3.1'), (2023, '3.0'))),)),
                                  'sdmx.oecd.org': oecd_csv([('JPN', 'Japan', 'UNE_LF_M', 'PT_LF_SUB', 2023, 2.6)])})
        euro = await tools.execute('stat_lookup', {'source': 'eurostat', 'countries': ['Germany', 'France', 'Japan'],
                                                   'indicator': 'unemployment', 'start_year': 2022, 'end_year': 2024})
        assert euro['source'] == 'eurostat' and euro['unit'] == 'percent of the labour force' and euro['indicator']['id'] == 'tps00203'
        assert euro['as_of'] == '2026-10-30T23:00:00+0100' and euro['as_of_basis'] == 'provider_updated'
        assert [row['code'] for row in euro['series']] == ['DEU', 'FRA'] and euro['no_values'] == ['JPN']
        assert 'Eurostat covers European countries' in euro['note'] and 'urls' not in euro
        assert euro['page_url'] == 'https://ec.europa.eu/eurostat/databrowser/view/tps00203/default/table?lang=en'
        ilo = await tools.execute('stat_lookup', {'source': 'ilo', 'countries': ['JPN', 'DEU'], 'indicator': '失業率',
                                                  'start_year': 2022, 'end_year': 2023})
        assert ilo['source_name'].startswith('ILOSTAT') and ilo['unit'] == 'percent (age 15 and over)'
        assert [(row['country'], row['latest']) for row in ilo['series']] == [
            ('Japan', {'year': 2023, 'value': 2.6}), ('Germany', {'year': 2023, 'value': 3.0})]
        assert len(sent) == 3 and tools.use['lookups'] == 2 and len(ilo['urls']) == 2
        oecd = await tools.execute('stat_lookup', {'source': 'OECD', 'countries': ['日本', 'ドイツ'], 'indicator': '失業率',
                                                   'start_year': 2022, 'end_year': 2024})
        assert oecd['source'] == 'oecd' and oecd['source_name'] == 'OECD Data Explorer' and oecd['indicator']['key'] == 'unemployment'
        assert oecd['unit'].startswith('percent of the labour force') and oecd['as_of_basis'] == 'retrieved'
        assert oecd['series'] == [{'country': 'Japan', 'code': 'JPN', 'values': [{'year': 2023, 'value': 2.6}], 'latest': {'year': 2023, 'value': 2.6}}]
        assert oecd['no_values'] == ['DEU'] and 'format=csvfilewithlabels' in oecd['url'] and len(sent) == 4
        for bad, problem in (({'source': 'un', 'countries': ['JPN'], 'indicator': 'population'}, 'source must be one of'),
                             ({'source': 'eurostat', 'countries': ['DEU'], 'indicator': 'fertility'}, 'no built-in indicator'),
                             ({'source': 'ilo', 'countries': ['JPN'], 'indicator': 'unemployment', 'host': 'x'}, 'accepts source')):
            with pytest.raises(WebToolError, match=problem):
                await tools.execute('stat_lookup', bad)
        assert len(sent) == 4
    asyncio.run(run())


def test_a_refusal_is_said_to_be_temporary_and_the_provider_is_left_alone_for_a_while():
    """Real-machine case: after a few requests in quick succession sdmx.ilo.org answered 403 with a Forbidden page."""
    async def run():
        tools, sent = tools_with({'sdmx.ilo.org': _HTTPStatusError(403)})
        ask = {'source': 'ilo', 'countries': ['JPN', 'USA', 'DEU'], 'indicator': 'unemployment'}
        with pytest.raises(WebToolError, match='ILOSTAT .* could not be read: ILOSTAT .* temporarily refused the request \\(HTTP 403\\); '
                                               'this usually passes after some minutes.*try another source'):
            await tools.execute('stat_lookup', ask)
        assert len(sent) == 1, 'neither a retry nor the other countries are sent after a refusal'
        with pytest.raises(WebToolError, match='refused this machine.s requests a moment ago and is not asked again for now'):
            await tools.execute('stat_lookup', {**ask, 'indicator': 'youth_unemployment'})
        assert len(sent) == 1
        # Another provider is not affected, and a missing page (404) is not called a refusal.
        tools._request, held = None, tools
        other, sent = tools_with({'api.imf.org': _HTTPStatusError(404)})
        with pytest.raises(WebToolError, match='could not be read: Web service returned HTTP 404'):
            await other.execute('stat_lookup', {'source': 'imf', 'countries': ['JPN'], 'indicator': 'population'})
        assert 'imf' not in other._stat_refused and 'ilo' in held._stat_refused
    asyncio.run(run())


def test_requests_to_one_provider_are_spaced_and_the_ilo_most_of_all(monkeypatch):
    assert statsources.PAUSE == {'ilo': 3.0} and WebTools.STAT_PAUSE is statsources.PAUSE

    async def run():
        tools, sent = tools_with({'/JPN.A': ilo_xml(rows=(('JPN', ((2023, '2.6'),)),)), '/DEU.A': ilo_xml(rows=(('DEU', ((2023, '3.0'),)),))})
        tools.STAT_PAUSE = {'ilo': 0.3}
        started = time.monotonic()
        await tools.execute('stat_lookup', {'source': 'ilo', 'countries': ['JPN', 'DEU'], 'indicator': 'unemployment',
                                            'start_year': 2023, 'end_year': 2023})
        assert len(sent) == 2 and time.monotonic() - started >= 0.28
    asyncio.run(run())


def test_a_failed_request_is_tried_once_more_then_an_old_copy_serves_and_a_bad_answer_is_never_kept(tmp_path):
    async def run():
        store = statdata.IndicatorStore(tmp_path / 'stat-cache')
        ask = {'source': 'ilo', 'countries': ['JPN'], 'indicator': 'unemployment', 'start_year': 2022, 'end_year': 2023}
        attempts = []

        def flaky(url):
            attempts.append(url)
            return None if len(attempts) == 1 else ilo_xml()
        tools, sent = tools_with({'sdmx.ilo.org': flaky})
        tools.use_stat_store(store)
        assert (await tools.execute('stat_lookup', ask))['series'][0]['latest'] == {'year': 2023, 'value': 2.6} and len(sent) == 2
        kept = next((tmp_path / 'stat-cache').iterdir())
        assert kept.name.startswith('ilo_') and kept.suffix == '.bin' and kept.read_bytes() == ilo_xml()
        # Two days later the provider is down: the old copy still answers, and its date is the day it was kept.
        os.utime(kept, (time.time() - 2 * 86400,) * 2)
        down, sent = tools_with({})
        down.use_stat_store(store)
        old = await down.execute('stat_lookup', ask)
        assert old['series'][0]['latest']['value'] == 2.6 and len(sent) == 2
        assert old['as_of'] == time.strftime('%Y-%m-%d', time.gmtime(time.time() - 2 * 86400)) and old['as_of_basis'] == 'retrieved'
        # An answer that cannot be read is an error naming the provider, and it is not kept.
        kept.unlink()
        broken, sent = tools_with({'sdmx.ilo.org': b'<html><body>maintenance</body></html>'})
        broken.use_stat_store(store)
        with pytest.raises(WebToolError, match='ILOSTAT .* could not be read: the XML answer was not an SDMX data message.*try another source'):
            await broken.execute('stat_lookup', ask)
        # The provider did answer, so it is not asked again; and what could not be read is not kept.
        assert len(sent) == 1 and list((tmp_path / 'stat-cache').iterdir()) == []
        for odd in ('../x', 'imf_short', 'IMF_' + '0' * 32, 'imf_' + 'g' * 32):
            assert store.get_answer(odd) is None
            store.put_answer(odd, b'x')
        assert list((tmp_path / 'stat-cache').iterdir()) == []
    asyncio.run(run())
