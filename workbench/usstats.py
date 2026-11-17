"""United States government statistics for stat_lookup: BEA, BLS, EIA and the Treasury, without a key.

    BEA       https://apps.bea.gov/national/Release/TXT/NipaDataA.txt
              Every annual series of the national accounts in one text file (about 12 MB):
              %SeriesCode,Period,Value  /  A001RC,1929,"105,322"
    BLS       https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000
              One series as JSON, monthly. Without a key only a few requests a day are answered.
    EIA       https://api.eia.gov/bulk/TOTAL.zip   (also STEO.zip)
              A zip holding one text file, one JSON object per line and series.
    Treasury  https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny
              The public debt for every business day, as JSON.

These addresses answered from a real machine. This module names the series
and reads the answers; it sends nothing. The series are named by the
agencies' own codes, so a series that is not in a file is an error that says
so, never another series in its place. Where the application itself derives a
yearly figure from monthly or daily ones, the unit says how.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

from . import statdata

PROVIDERS = {
    'bea': 'U.S. Bureau of Economic Analysis (national accounts)',
    'bls': 'U.S. Bureau of Labor Statistics',
    'eia': 'U.S. Energy Information Administration',
    'treasury': 'U.S. Treasury Fiscal Data',
}
# The most that is downloaded and unpacked for one of these.
MAX_FILE_BYTES, MAX_UNPACKED_BYTES, MAX_ZIP_ENTRIES = 64 * 1024 * 1024, 400 * 1024 * 1024, 8

# key: (the agency's series code, what it is, unit)
BEA = {
    'gdp': ('A191RC', 'Gross domestic product, current dollars', 'millions of dollars'),
    'real_gdp': ('A191RX', 'Real gross domestic product, chained dollars', 'millions of chained dollars'),
    'gdp_growth': ('A191RL', 'Real gross domestic product, percent change from preceding period', 'percent'),
    'gdp_price_index': ('A191RG', 'Gross domestic product, price index', 'index'),
    'personal_consumption': ('DPCERC', 'Personal consumption expenditures, current dollars', 'millions of dollars'),
    'pce_price_index': ('DPCERG', 'Personal consumption expenditures, price index', 'index'),
}
BLS = {
    # Monthly series; a year's figure is the mean of its twelve monthly values.
    'unemployment': ('LNS14000000', 'Unemployment rate, seasonally adjusted, age 16 and over', 'percent'),
    'cpi': ('CUUR0000SA0', 'Consumer price index for all urban consumers, all items, not seasonally adjusted', 'index, 1982-84 = 100'),
    'payrolls': ('CES0000000001', 'Total nonfarm employment, seasonally adjusted', 'thousands of persons'),
    'labor_force_participation': ('LNS11300000', 'Labor force participation rate, seasonally adjusted', 'percent'),
}
EIA = {
    # (series id in a bulk file named by its first part, what it is, unit)
    'energy_consumption': ('TOTAL.TETCBUS.A', 'Total primary energy consumption', 'trillion Btu'),
    'energy_production': ('TOTAL.TEPRBUS.A', 'Total primary energy production', 'trillion Btu'),
    'electricity_generation': ('TOTAL.ELETPUS.A', 'Electricity net generation, all sectors', 'million kilowatthours'),
    'crude_oil_price': ('STEO.WTIPUUS.A', 'West Texas Intermediate crude oil spot price', 'dollars per barrel'),
    'brent_oil_price': ('STEO.BREPUUS.A', 'Brent crude oil spot price', 'dollars per barrel'),
}
TREASURY = {
    'government_debt': ('tot_pub_debt_out_amt', 'Total public debt outstanding', 'dollars'),
    'debt_held_by_public': ('debt_held_public_amt', 'Debt held by the public', 'dollars'),
}
TABLES = {'bea': BEA, 'bls': BLS, 'eia': EIA, 'treasury': TREASURY}
_EIA_FILES = {'TOTAL': 'https://www.eia.gov/totalenergy/data/monthly/', 'STEO': 'https://www.eia.gov/outlooks/steo/'}
NAMES = {'実質gdp': 'real_gdp', 'real gdp': 'real_gdp', '個人消費': 'personal_consumption', 'pce': 'personal_consumption',
         'pce物価指数': 'pce_price_index', 'pce price index': 'pce_price_index', 'gdpデフレーター': 'gdp_price_index',
         'gdp deflator': 'gdp_price_index', '雇用者数': 'payrolls', '非農業部門雇用者数': 'payrolls', 'nonfarm payrolls': 'payrolls',
         '労働参加率': 'labor_force_participation', '労働力率': 'labor_force_participation',
         'エネルギー消費': 'energy_consumption', 'エネルギー消費量': 'energy_consumption', 'エネルギー生産': 'energy_production',
         '発電量': 'electricity_generation', 'electricity': 'electricity_generation',
         '原油価格': 'crude_oil_price', 'oil price': 'crude_oil_price', 'wti': 'crude_oil_price', 'crude oil price': 'crude_oil_price',
         'ブレント': 'brent_oil_price', 'brent': 'brent_oil_price', '政府債務': 'government_debt', '公的債務': 'government_debt',
         'national debt': 'government_debt', 'public debt': 'government_debt'}
# An agency's own series code, as typed: capitals and digits only, so that an ordinary word is never taken for one.
_CODES = {'bea': r'[A-Z][A-Z0-9]{4,9}', 'bls': r'[A-Z]{2}(?=[A-Z0-9]*\d)[A-Z0-9]{6,20}', 'eia': r'(TOTAL|STEO)\.[A-Z0-9_]{3,24}\.A'}


class NoSeries(ValueError):
    """The file was read, and the series asked for is not in it."""


def indicator(provider, value):
    """(key, (series code, label, unit)) for a built-in name, or for one of the agency's own series codes."""
    table = TABLES[provider]
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError('indicator must be a name such as ' + ', '.join(table))
    plain = statdata._plain(value)
    key = NAMES.get(plain) or statdata._INDICATOR_NAMES.get(plain) or plain.replace(' ', '_')
    if key in table:
        return key, table[key]
    code = value.strip().upper()
    found = next((name for name, spec in table.items() if spec[0].upper() == code), None)
    if found:
        return found, table[found]
    known_word = plain in statdata._INDICATOR_NAMES or plain in NAMES or any(key in other for other in TABLES.values())
    if provider in _CODES and re.fullmatch(_CODES[provider], value.strip()) and not known_word:
        return code, (code, '', '')  # another series of this agency, by its code
    raise ValueError(f'{PROVIDERS[provider]} has no built-in indicator {value.strip()[:60]!r}. Available from this source: '
                     + ', '.join(table) + ('; or one of its own series codes' if provider in _CODES else ''))


def plan(provider, indicator_name, countries, start, end):
    """The one request of a lookup: (key, spec, url, page, size limit, seconds to wait)."""
    if isinstance(countries, str):
        countries = [countries]
    if (not isinstance(countries, list) or not countries
            or any(not isinstance(item, str) or statdata._COUNTRY_NAMES.get(statdata._plain(item)) != 'USA' for item in countries)):
        raise ValueError(f'{PROVIDERS[provider]} covers the United States only: ask for countries ["USA"], '
                         'or use an international source (worldbank, imf, oecd) for other countries')
    key, spec = indicator(provider, indicator_name)
    code = spec[0]
    if provider == 'bea':
        return key, spec, 'https://apps.bea.gov/national/Release/TXT/NipaDataA.txt', 'https://www.bea.gov/data/gdp/gross-domestic-product', \
            MAX_FILE_BYTES, 90
    if provider == 'bls':
        # Without a key at most ten years are answered: the newest ten, starting a year before the asked
        # range where that fits, so that a change from a year earlier can be given.
        first = max(start - 1, end - 9)
        return key, spec, f'https://api.bls.gov/publicAPI/v1/timeseries/data/{code}?startyear={first}&endyear={end}', \
            f'https://data.bls.gov/timeseries/{code}', 4 * 1024 * 1024, 45
    if provider == 'eia':
        name = code.split('.', 1)[0]
        return key, spec, f'https://api.eia.gov/bulk/{name}.zip', _EIA_FILES[name], MAX_FILE_BYTES, 90
    return key, spec, ('https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny'
                       f'?fields=record_date,{code}&filter=record_date:gte:{start}-01-01&sort=-record_date&page%5Bsize%5D=10000'), \
        'https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/', 8 * 1024 * 1024, 45


BEA_QUARTERS = 'https://apps.bea.gov/national/Release/TXT/NipaDataQ.txt'
COMPUTED = 'change_percent is the change from a year earlier, computed by the application from the index.'


def is_index(spec):
    """An index series: its level means little by itself, so the change from a year earlier is added."""
    return str(spec[2]).startswith('index')


# --- reading the answers -------------------------------------------------------------------------------

def _years(values, start, end):
    return [{'year': year, **entry} for year, entry in sorted(values.items()) if start <= year <= end]


def _change(now, before):
    """Percent change, to one decimal as the agencies publish it; None when it cannot be formed."""
    if type(now) not in {int, float} or type(before) not in {int, float} or not before:
        return None
    return round((now / before - 1) * 100, 1)


def _yearly_changes(values):
    for year, entry in values.items():
        change = _change(entry['value'], values.get(year - 1, {}).get('value'))
        if change is not None:
            entry['change_percent'] = change


def _bea_rows(data, code):
    """(period, number) of one series in a BEA text file, by its exact code."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_FILE_BYTES:
        raise ValueError('the BEA file is larger than the application reads')
    head = bytes(data[:200]).decode('utf-8-sig', 'replace')
    if 'SeriesCode' not in head.split('\n', 1)[0]:
        raise ValueError('the BEA file does not begin with its column names (it begins: ' + head[:60].replace('\n', ' ') + ')')
    prefix, rows, seen = (code + ',').encode('ascii'), [], False
    for line in bytes(data).split(b'\n'):
        if not line.startswith(prefix):
            continue
        seen = True
        parts = line.decode('ascii', 'replace').strip().split(',', 2)
        number = statdata._number(parts[2].strip().strip('"').replace(',', '')) if len(parts) == 3 else None
        if number is not None:
            rows.append((parts[1].strip(), number))
    if not seen:
        raise NoSeries(f'the BEA file holds no series {code}; report this indicator from this source as unconfirmed')
    return rows


def read_bea(data, code, start, end, index=False):
    """One series out of NipaDataA.txt. -> (yearly values, label, update time, remarks, extra)"""
    values = {int(period): {'value': number} for period, number in _bea_rows(data, code) if re.fullmatch(r'\d{4}', period)}
    if index:
        _yearly_changes(values)
    return _years(values, start, end), '', '', [COMPUTED] if index and values else [], {}


def read_bea_quarter(data, code, index=False):
    """The latest quarter of one series out of NipaDataQ.txt (seasonally adjusted at annual rates)."""
    quarters = {period: number for period, number in _bea_rows(data, code) if re.fullmatch(r'\d{4}Q[1-4]', period)}
    if not quarters:
        return [], '', '', [], {}
    period = max(quarters)
    latest = {'period': period, 'value': quarters[period], 'basis': 'quarterly, seasonally adjusted at annual rates'}
    change = _change(quarters[period], quarters.get(f'{int(period[:4]) - 1}{period[4:]}')) if index else None
    if change is not None:
        latest['change_percent'] = change
    return [], '', '', [], {'latest_period': latest}


def read_bls(payload, code, start, end, index=False):
    """A monthly BLS series as yearly means of complete years, with the latest month beside them."""
    if not isinstance(payload, dict) or 'status' not in payload:
        raise ValueError('the BLS answer was not in the expected form')
    messages = '; '.join(str(item)[:200] for item in payload.get('message') or [] if item)
    if payload.get('status') != 'REQUEST_SUCCEEDED':
        raise ValueError('BLS did not answer the request' + (f' ({messages})' if messages else '')
                         + '. Without a key it answers only a few requests a day; try again tomorrow or use another source')
    series = (payload.get('Results') or {}).get('series') if isinstance(payload.get('Results'), dict) else None
    rows = next((item.get('data') for item in series or [] if isinstance(item, dict) and str(item.get('seriesID', '')).upper() == code), None)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'BLS returned no data for series {code}' + (f' ({messages})' if messages else ''))
    months, annual = {}, {}
    for row in rows:
        period, year = str(row.get('period', '')), str(row.get('year', ''))
        number = statdata._number(str(row.get('value', '')))
        if number is None or not re.fullmatch(r'\d{4}', year):
            continue
        if re.fullmatch(r'M(0[1-9]|1[0-2])', period):
            months.setdefault(int(year), {})[int(period[1:])] = number
        elif period in {'M13', 'A01'}:
            annual[int(year)] = number  # the agency's own annual figure, where the series has one
    values = {}
    for year, by_month in months.items():
        if year in annual:
            values[year] = {'value': annual[year]}
        elif len(by_month) == 12:
            values[year] = {'value': round(sum(by_month.values()) / 12, 3), 'months': 12}
    if index:
        _yearly_changes(values)
    remarks, extra = [], {}
    if months:
        year = max(months)
        month = max(months[year])
        latest = {'period': f'{year}-{month:02d}', 'value': months[year][month]}
        change = _change(months[year][month], months.get(year - 1, {}).get(month)) if index else None
        if change is not None:
            latest['change_percent'] = change
        extra['latest_period'] = latest
        remarks.append(f'Latest month: {year}-{month:02d} = {months[year][month]}. A year is given only when all twelve months '
                       'are published; its figure is the mean of the monthly values, computed by the application.')
        for year in sorted(months):
            if start <= year <= end and year not in values:
                missing = [f'{at:02d}' for at in range(1, 13) if at not in months[year]]
                remarks.append(f'{year} has no yearly figure: {12 - len(missing)} of 12 months are published (missing: '
                               + ', '.join(missing) + ').')
    if index and values:
        remarks.append(COMPUTED)
    return _years(values, start, end), '', '', remarks, extra


def read_eia(data, series_id, start, end, this_year=None):
    """One series out of an EIA bulk zip (one JSON object per line), read without unpacking to disk."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_FILE_BYTES:
        raise ValueError('the EIA file is larger than the application reads')
    try:
        archive = zipfile.ZipFile(io.BytesIO(bytes(data)))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise ValueError('the EIA file was not a zip archive') from None
    wanted_name = series_id.split('.', 1)[0] + '.txt'
    with archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= MAX_ZIP_ENTRIES:
            raise ValueError('the EIA file does not have the expected contents')
        for entry in entries:
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}', entry.filename) or '..' in entry.filename or entry.is_dir()
                    or entry.flag_bits & 0x1 or entry.file_size > MAX_UNPACKED_BYTES):
                raise ValueError('the EIA file has an entry the application does not accept (name, size or encryption)')
        chosen = [entry for entry in entries if entry.filename.upper() == wanted_name.upper()]
        if len(chosen) != 1:
            raise ValueError(f'the EIA file does not contain {wanted_name}')
        needle, read, record = ('"series_id":"' + series_id + '"').encode('ascii'), 0, None
        try:
            with archive.open(chosen[0]) as handle:
                for line in handle:
                    read += len(line)
                    if read > MAX_UNPACKED_BYTES:
                        raise ValueError('the EIA data is larger than the application reads')
                    if needle in line.replace(b'": "', b'":"'):
                        record = line
                        break
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError):
            raise ValueError('the EIA data could not be unpacked') from None
    if record is None:
        raise NoSeries(f'the EIA file holds no series {series_id}; report this indicator from this source as unconfirmed')
    try:
        entry = json.loads(record.decode('utf-8', 'replace'))
    except json.JSONDecodeError:
        raise ValueError('the EIA series could not be read as JSON') from None
    values = {}
    for pair in entry.get('data') if isinstance(entry.get('data'), list) else []:
        if isinstance(pair, list) and len(pair) >= 2 and re.fullmatch(r'\d{4}', str(pair[0])):
            number = statdata._number(pair[1]) if isinstance(pair[1], str) else (
                pair[1] if type(pair[1]) in {int, float} and pair[1] == pair[1] else None)
            if number is not None:
                values[int(pair[0])] = {'value': number}
    remarks = []
    if series_id.startswith('STEO.'):
        # The Short-Term Energy Outlook mixes observed years and forecasts. Where the file says which period
        # was the last observed one, that decides; otherwise the current year and later are taken as forecasts.
        marker = next((str(value) for key, value in entry.items()
                       if 'histor' in str(key).lower() and re.match(r'\d{4}', str(value or ''))), '')
        if marker:
            whole = not re.fullmatch(r'\d{4}(0[1-9]|1[01]|-?(0[1-9]|1[01])|-?Q[1-3])', marker)
            first = int(marker[:4]) + 1 if whole else int(marker[:4])
            basis = f'the file gives {marker} as the last observed period'
        else:
            first = this_year if type(this_year) is int else None
            basis = 'the file does not say where forecasts begin, so the current year and later are taken as forecasts'
        if first is not None:
            for year, value in values.items():
                value['status'] = 'forecast' if year >= first else 'actual'
            if any(year >= first for year in values):
                remarks.append(f'Years from {first} on are wholly or partly EIA forecasts, marked status "forecast" ({basis}).')
    label = str(entry.get('name') or '')[:200] + (f" ({str(entry.get('units'))[:60]})" if entry.get('units') else '')
    return _years(values, start, end), label, str(entry.get('last_updated') or '')[:25], remarks, {}


def read_treasury(payload, field, start, end):
    """The public debt on the last reported day of each year (the date is given with the value)."""
    rows = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        detail = str(payload.get('message') or payload.get('error') or '')[:200] if isinstance(payload, dict) else ''
        raise ValueError('the Treasury answer was not in the expected form' + (f' ({detail})' if detail else ''))
    latest = {}
    for row in rows:
        date = str(row.get('record_date', '')) if isinstance(row, dict) else ''
        number = statdata._number(str(row.get(field, ''))) if isinstance(row, dict) else None
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) and number is not None and date > latest.get(int(date[:4]), {}).get('date', ''):
            latest[int(date[:4])] = {'value': number, 'date': date}
    newest = max((entry['date'] for entry in latest.values()), default='')
    remarks = ['Each year\'s figure is the amount on the last reported day of that year (its date is given); '
               'the current year shows the latest day.'] if latest else []
    return _years(latest, start, end), '', newest, remarks, {}


def read(provider, data, code, start, end, *, index=False, this_year=None, role=''):
    """(yearly values, the agency's label, its update time, remarks, extra fields for the series such as latest_period)."""
    if provider == 'bea':
        return read_bea_quarter(data, code, index) if role == 'quarter' else read_bea(data, code, start, end, index)
    if provider == 'eia':
        return read_eia(data, code, start, end, this_year)
    try:
        payload = json.loads(bytes(data).decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('the answer was not JSON') from None
    return read_bls(payload, code, start, end, index) if provider == 'bls' else read_treasury(payload, code, start, end)
