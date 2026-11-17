"""United States government statistics through stat_lookup: BEA, BLS, EIA and the Treasury.

No network. The fixtures follow what answered from a real machine (the BEA
file's first lines, the BLS and Treasury JSON) and the EIA bulk format.
"""
import asyncio
import io
import json
import zipfile

import pytest

from workbench import statdata, statsources, usstats
from workbench.webtools import WebToolError, WebTools, _HTTPStatusError
from test_stat_sources import tools_with

BEA_FILE = ('%SeriesCode,Period,Value\r\n'
            'A001RC,1929,"105,322"\r\n'
            'A191RC,2022,"26,006,893"\r\nA191RC,2023,"27,720,709"\r\nA191RC,2024,"29,184,890"\r\n'
            'A191RL,2022,2.5\r\nA191RL,2023,2.9\r\nA191RL,2024,2.8\r\nA191RL,1930,-8.5\r\n'
            'A191RL1,2024,9.9\r\n'
            'B191RL,2024,"n/a"\r\n').encode()


def bls_json(series='LNS14000000', rows=None, status='REQUEST_SUCCEEDED', message=()):
    if rows is None:
        rows = [(2025, month, 4.0 + month / 10) for month in range(9, 0, -1)] + [(2024, month, 4.0) for month in range(12, 0, -1)] + [
            (2023, month, 3.5 + (month % 2) / 10) for month in range(12, 0, -1)]
    return {'status': status, 'responseTime': 120, 'message': list(message),
            'Results': {'series': [{'seriesID': series, 'data': [
                {'year': str(year), 'period': f'M{month:02d}', 'periodName': 'x', 'value': str(value), 'footnotes': [{}]}
                for year, month, value in rows]}]}}


def eia_zip(lines=None, name='TOTAL.txt', extra=None):
    if lines is None:
        lines = [{'category_id': '711224', 'name': 'Total Energy', 'childseries': ['TOTAL.TETCBUS.A']},
                 {'series_id': 'TOTAL.TETCBUS.M', 'name': 'Total Primary Energy Consumption, Monthly', 'units': 'Trillion Btu',
                  'f': 'M', 'data': [['202412', 8500.1]]},
                 {'series_id': 'TOTAL.TETCBUS.A', 'name': 'Total Primary Energy Consumption, Annual', 'units': 'Trillion Btu', 'f': 'A',
                  'last_updated': '2026-10-28T12:00:00-04:00', 'data': [['2024', 94213.4], ['2023', 93587.1], ['2022', None], ['1949', 31981.5]]}]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, '\n'.join(json.dumps(line, separators=(',', ':')) for line in lines) + '\n')
        for other, text in (extra or {}).items():
            archive.writestr(other, text)
    return buffer.getvalue()


STEO = [{'series_id': 'STEO.WTIPUUS.A', 'name': 'West Texas Intermediate Crude Oil Price, Annual', 'units': 'dollars per barrel',
         'lastHistoricalPeriod': '2025', 'last_updated': '2026-11-10T12:00:00-05:00',
         'data': [['2027', 61.0], ['2026', 65.2], ['2025', 66.9], ['2024', 76.6]]}]

TREASURY = {'data': [{'record_date': '2026-11-13', 'tot_pub_debt_out_amt': '38112345678901.23'},
                     {'record_date': '2026-11-12', 'tot_pub_debt_out_amt': '38100000000000.00'},
                     {'record_date': '2025-12-31', 'tot_pub_debt_out_amt': '36900000000000.50'},
                     {'record_date': '2025-12-30', 'tot_pub_debt_out_amt': '36800000000000.00'},
                     {'record_date': '2024-12-31', 'tot_pub_debt_out_amt': 'null'}],
            'meta': {'count': 5}, 'links': {}}


# --- names and addresses ----------------------------------------------------------------------------------

def test_the_four_agencies_are_sources_for_the_united_states_only():
    assert [statsources.source(name) for name in ('BEA', 'bls', 'EIA', 'Treasury', '労働統計局', 'エネルギー省', '財務省')] == [
        'bea', 'bls', 'eia', 'treasury', 'bls', 'eia', 'treasury']
    bea = statsources.plan('bea', '経済成長率', ['USA'], 2022, 2024, 2026)
    assert bea['requests'] == [('https://apps.bea.gov/national/Release/TXT/NipaDataA.txt', ['USA'])] and bea['spec'][0] == 'A191RL'
    assert bea['unit'] == 'percent' and bea['size'] == usstats.MAX_FILE_BYTES and bea['codes'] == ['USA']
    assert statsources.plan('bls', '失業率', ['米国'], 2010, 2025, 2026)['requests'][0][0] == (
        'https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000?startyear=2016&endyear=2025')   # at most ten years without a key
    assert statsources.plan('bls', 'cpi', ['United States'], None, None, 2026)['spec'][0] == 'CUUR0000SA0'
    assert statsources.plan('eia', '原油価格', ['US'], None, None, 2026)['requests'][0][0] == 'https://api.eia.gov/bulk/STEO.zip'
    assert statsources.plan('eia', 'energy_consumption', ['USA'], None, None, 2026)['requests'][0][0] == 'https://api.eia.gov/bulk/TOTAL.zip'
    debt = statsources.plan('treasury', '政府債務', ['アメリカ'], 2024, 2026, 2026)
    assert debt['requests'][0][0] == ('https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny'
                                      '?fields=record_date,tot_pub_debt_out_amt&filter=record_date:gte:2024-01-01&sort=-record_date&page%5Bsize%5D=10000')
    for countries in (['Japan'], ['USA', 'Germany'], [], 'Germany', [5]):
        with pytest.raises(ValueError, match='covers the United States only'):
            statsources.plan('bea', 'gdp', countries, None, None, 2026)
    with pytest.raises(ValueError, match='has no built-in indicator .*Available from this source: gdp, real_gdp, gdp_growth'):
        statsources.plan('bea', 'unemployment', ['USA'], None, None, 2026)
    # An agency's own series code is accepted; anything else is not turned into an address.
    assert statsources.plan('bea', 'a191rx', ['USA'], None, None, 2026)['key'] == 'real_gdp'
    assert statsources.plan('bea', 'W006RC', ['USA'], None, None, 2026)['spec'] == ('W006RC', '', '')
    assert statsources.plan('bls', 'CES0500000003', ['USA'], None, None, 2026)['spec'][0] == 'CES0500000003'
    for word in ('unemployment', 'INFLATION', 'w006rc', 'population'):       # an ordinary word is never taken for a series code
        with pytest.raises(ValueError, match='no built-in indicator'):
            statsources.plan('bea', word, ['USA'], None, None, 2026)
    with pytest.raises(ValueError, match='no built-in indicator'):
        statsources.plan('bls', 'POPULATION', ['USA'], None, None, 2026)
    assert statsources.plan('eia', 'TOTAL.CLTCBUS.A', ['USA'], None, None, 2026)['requests'][0][0] == 'https://api.eia.gov/bulk/TOTAL.zip'
    for bad in ('PET.RWTC.A', '../TOTAL.X.A', 'TOTAL.X.M', 'https://x'):
        with pytest.raises(ValueError, match='no built-in indicator'):
            statsources.plan('eia', bad, ['USA'], None, None, 2026)


# --- reading -------------------------------------------------------------------------------------------------

def test_one_bea_series_is_read_out_of_the_whole_file_by_its_exact_code():
    values, label, updated, remarks = usstats.read('bea', BEA_FILE, 'A191RL', 2022, 2024)
    assert values == [{'year': 2022, 'value': 2.5}, {'year': 2023, 'value': 2.9}, {'year': 2024, 'value': 2.8}]   # not A191RL1's 9.9
    assert (label, updated, remarks) == ('', '', [])
    assert usstats.read('bea', BEA_FILE, 'A191RC', 2023, 2030)[0] == [{'year': 2023, 'value': 27720709}, {'year': 2024, 'value': 29184890}]
    assert usstats.read('bea', BEA_FILE, 'A001RC', 1900, 1950)[0] == [{'year': 1929, 'value': 105322}]
    assert usstats.read('bea', BEA_FILE, 'B191RL', 2020, 2030)[0] == []          # a series without a number has no values
    with pytest.raises(ValueError, match='holds no series A999XX'):
        usstats.read('bea', BEA_FILE, 'A999XX', 2020, 2030)
    with pytest.raises(ValueError, match='does not begin with its column names \\(it begins: <html>'):
        usstats.read('bea', b'<html>maintenance</html>', 'A191RL', 2020, 2030)


def test_a_monthly_bls_series_gives_complete_years_and_the_latest_month():
    values, _label, _updated, remarks = usstats.read('bls', json.dumps(bls_json()).encode(), 'LNS14000000', 2020, 2026)
    assert values == [{'year': 2023, 'value': 3.55, 'months': 12}, {'year': 2024, 'value': 4.0, 'months': 12}]   # 2025 has nine months
    assert remarks == ['Latest month: 2025-09 = 4.9. A year is given only when all twelve months are published; '
                       'its figure is the mean of the monthly values, computed by the application.']
    # The agency's own annual figure is used where the series has one.
    with_annual = bls_json(rows=[(2024, month, 300 + month) for month in range(1, 13)])
    with_annual['Results']['series'][0]['data'].append({'year': '2024', 'period': 'M13', 'value': '313.689'})
    assert usstats.read('bls', json.dumps(with_annual).encode(), 'LNS14000000', 2024, 2024)[0] == [{'year': 2024, 'value': 313.689}]
    refused = bls_json(status='REQUEST_NOT_PROCESSED', message=['daily threshold for total number of requests allocated to the user'])
    with pytest.raises(ValueError, match='BLS did not answer the request \\(daily threshold.*only a few requests a day'):
        usstats.read('bls', json.dumps(refused).encode(), 'LNS14000000', 2020, 2026)
    with pytest.raises(ValueError, match='no data for series LNS14000000'):
        usstats.read('bls', json.dumps(bls_json(series='OTHER')).encode(), 'LNS14000000', 2020, 2026)
    for junk, problem in ((b'<html>', 'not JSON'), (b'[1]', 'not in the expected form')):
        with pytest.raises(ValueError, match=problem):
            usstats.read('bls', junk, 'LNS14000000', 2020, 2026)


def test_one_eia_series_is_read_out_of_the_bulk_zip_and_forecasts_are_marked(monkeypatch):
    values, label, updated, remarks = usstats.read('eia', eia_zip(), 'TOTAL.TETCBUS.A', 2020, 2026)
    assert values == [{'year': 2023, 'value': 93587.1}, {'year': 2024, 'value': 94213.4}]     # the annual series, not the monthly one
    assert label == 'Total Primary Energy Consumption, Annual (Trillion Btu)' and updated == '2026-10-28T12:00:00-04:00' and remarks == []
    values, _label, _updated, remarks = usstats.read('eia', eia_zip(STEO, 'STEO.txt'), 'STEO.WTIPUUS.A', 2024, 2027)
    assert values == [{'year': 2024, 'value': 76.6}, {'year': 2025, 'value': 66.9},
                      {'year': 2026, 'value': 65.2, 'forecast': True}, {'year': 2027, 'value': 61.0, 'forecast': True}]
    assert remarks == ['Years after 2025 are EIA forecasts, not observed values.']
    unmarked = [{**STEO[0], 'lastHistoricalPeriod': None}]
    assert 'current and following year are EIA forecasts' in usstats.read('eia', eia_zip(unmarked, 'STEO.txt'), 'STEO.WTIPUUS.A', 2024, 2027)[3][0]
    with pytest.raises(ValueError, match='holds no series TOTAL.NOPE.A'):
        usstats.read('eia', eia_zip(), 'TOTAL.NOPE.A', 2020, 2026)
    for archive, problem in ((eia_zip(name='OTHER.txt'), 'does not contain TOTAL.txt'), (eia_zip(name='../TOTAL.txt'), 'does not accept'),
                             (eia_zip(name='data/TOTAL.txt'), 'does not accept'), (b'<html>', 'not a zip archive'),
                             (eia_zip(extra={f'x{i}.txt': 'x' for i in range(8)}), 'expected contents')):
        with pytest.raises(ValueError, match=problem):
            usstats.read('eia', archive, 'TOTAL.TETCBUS.A', 2020, 2026)
    # No more is unpacked than the limit, whatever the archive holds.
    monkeypatch.setattr(usstats, 'MAX_UNPACKED_BYTES', 2000)
    big = eia_zip([{'series_id': f'TOTAL.X{i}.A', 'name': 'x' * 200, 'data': []} for i in range(40)]
                  + [{'series_id': 'TOTAL.TETCBUS.A', 'data': [['2024', 1]]}])
    with pytest.raises(ValueError, match='does not accept|larger than the application reads'):
        usstats.read('eia', big, 'TOTAL.TETCBUS.A', 2020, 2026)


def test_the_debt_is_the_amount_on_the_last_reported_day_of_each_year():
    values, _label, updated, remarks = usstats.read('treasury', json.dumps(TREASURY).encode(), 'tot_pub_debt_out_amt', 2024, 2026)
    assert values == [{'year': 2025, 'value': 36900000000000.5, 'date': '2025-12-31'},
                      {'year': 2026, 'value': 38112345678901.23, 'date': '2026-11-13'}]      # 2024's only row has no amount
    assert updated == '2026-11-13' and 'last reported day of that year' in remarks[0]
    with pytest.raises(ValueError, match='not in the expected form \\(Invalid query parameter'):
        usstats.read('treasury', json.dumps({'error': 'Invalid query parameter', 'message': 'Invalid query parameter'}).encode(),
                     'tot_pub_debt_out_amt', 2024, 2026)
    assert usstats.read('treasury', b'{"data": []}', 'tot_pub_debt_out_amt', 2024, 2026) == ([], '', '', [])


# --- the tool ---------------------------------------------------------------------------------------------------

def test_stat_lookup_reads_the_four_agencies_and_keeps_their_files_for_a_day(tmp_path):
    async def run():
        answers = {'apps.bea.gov': BEA_FILE, 'api.bls.gov': bls_json(), 'TOTAL.zip': eia_zip(), 'STEO.zip': eia_zip(STEO, 'STEO.txt'),
                   'fiscaldata': TREASURY}
        tools, sent = tools_with(answers)
        tools.use_stat_store(statdata.IndicatorStore(tmp_path / 'stat-cache'))
        growth = await tools.execute('stat_lookup', {'source': 'bea', 'countries': ['USA'], 'indicator': 'gdp_growth',
                                                     'start_year': 2022, 'end_year': 2024})
        assert sent == [('https://apps.bea.gov/national/Release/TXT/NipaDataA.txt', {'wait': 90, 'size': usstats.MAX_FILE_BYTES, 'accept': '*/*'})]
        assert growth['source'] == 'bea' and growth['source_name'].startswith('U.S. Bureau of Economic Analysis') and growth['unit'] == 'percent'
        assert growth['indicator'] == {'id': 'A191RL', 'key': 'gdp_growth',
                                       'name': 'Real gross domestic product, percent change from preceding period'}
        assert growth['series'] == [{'country': 'United States', 'code': 'USA', 'latest': {'year': 2024, 'value': 2.8},
                                     'values': [{'year': 2022, 'value': 2.5}, {'year': 2023, 'value': 2.9}, {'year': 2024, 'value': 2.8}]}]
        assert growth['as_of_basis'] == 'retrieved' and growth['page_url'] == 'https://www.bea.gov/data/gdp/gross-domestic-product'
        # Another series of the same file costs no request: the file is kept.
        gdp = await tools.execute('stat_lookup', {'source': 'bea', 'countries': ['United States'], 'indicator': 'gdp',
                                                  'start_year': 2023, 'end_year': 2024})
        assert len(sent) == 1 and gdp['series'][0]['latest'] == {'year': 2024, 'value': 29184890} and gdp['unit'] == 'millions of dollars'
        jobless = await tools.execute('stat_lookup', {'source': 'bls', 'countries': ['USA'], 'indicator': 'unemployment'})
        assert jobless['series'][0]['latest'] == {'year': 2024, 'value': 4.0, 'months': 12} and 'Latest month: 2025-09 = 4.9' in jobless['note']
        assert jobless['page_url'] == 'https://data.bls.gov/timeseries/LNS14000000'
        oil = await tools.execute('stat_lookup', {'source': 'eia', 'countries': ['USA'], 'indicator': '原油価格', 'start_year': 2024, 'end_year': 2026})
        assert oil['indicator']['name'] == 'West Texas Intermediate Crude Oil Price, Annual (dollars per barrel)'
        assert oil['as_of'] == '2026-11-10T12:00:00-05:00' and oil['as_of_basis'] == 'provider_updated'
        assert oil['series'][0]['latest'] == {'year': 2026, 'value': 65.2, 'forecast': True} and 'forecasts' in oil['note']
        debt = await tools.execute('stat_lookup', {'source': 'treasury', 'countries': ['USA'], 'indicator': 'government_debt',
                                                   'start_year': 2025, 'end_year': 2026})
        assert debt['series'][0]['latest'] == {'year': 2026, 'value': 38112345678901.23, 'date': '2026-11-13'}
        assert debt['as_of'] == '2026-11-13' and debt['unit'] == 'dollars' and len(sent) == 4
        assert tools.use['lookups'] == 5
        for bad, problem in (({'source': 'bea', 'countries': ['Japan'], 'indicator': 'gdp'}, 'covers the United States only'),
                             ({'source': 'eia', 'countries': ['USA'], 'indicator': 'population'}, 'no built-in indicator')):
            with pytest.raises(WebToolError, match=problem):
                await tools.execute('stat_lookup', bad)
        # The next run of the application the same day asks nobody.
        later, sent = tools_with({})
        later.use_stat_store(statdata.IndicatorStore(tmp_path / 'stat-cache'))
        assert (await later.execute('stat_lookup', {'source': 'bea', 'countries': ['USA'], 'indicator': 'gdp_growth'}))['series']
        assert (await later.execute('stat_lookup', {'source': 'bls', 'countries': ['USA'], 'indicator': 'unemployment'}))['series']
        # A series the kept file does not hold is an error; the 12 MB file is not fetched again for it.
        with pytest.raises(WebToolError, match='holds no series A191RX'):
            await later.execute('stat_lookup', {'source': 'bea', 'countries': ['USA'], 'indicator': 'real_gdp'})
        assert sent == []
    asyncio.run(run())


def test_bls_is_not_asked_twice_for_an_answer_it_refused_and_a_missing_series_is_an_error():
    async def run():
        refused = bls_json(status='REQUEST_NOT_PROCESSED', message=['daily threshold reached'])
        tools, sent = tools_with({'api.bls.gov': refused, 'TOTAL.zip': eia_zip(), 'apps.bea.gov': _HTTPStatusError(503)})
        with pytest.raises(WebToolError, match='U.S. Bureau of Labor Statistics could not be read: BLS did not answer the request'):
            await tools.execute('stat_lookup', {'source': 'bls', 'countries': ['USA'], 'indicator': 'cpi'})
        assert len(sent) == 1, 'every request counts against the day'
        with pytest.raises(WebToolError, match='holds no series TOTAL.NOPE.A'):
            await tools.execute('stat_lookup', {'source': 'eia', 'countries': ['USA'], 'indicator': 'TOTAL.NOPE.A'})
        with pytest.raises(WebToolError, match='could not be read: Web service returned HTTP 503'):
            await tools.execute('stat_lookup', {'source': 'bea', 'countries': ['USA'], 'indicator': 'gdp'})
        assert len(sent) == 4, 'a server error is tried once more'
    asyncio.run(run())
