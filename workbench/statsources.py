"""Official statistics from providers other than the World Bank: the IMF, Eurostat, the ILO and the OECD.

Each provider publishes a keyless API. This module knows, for a small set of
well-known indicators, which address to ask and how to read the answer; it
sends nothing itself. The hosts are fixed. A model chooses a provider, an
indicator name, countries and years, never an address.

    IMF       https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/JPN.NGDP_RPCH.A
              World Economic Outlook, one country and one indicator per request (SDMX-JSON, or SDMX-ML).
    Eurostat  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tps00001?geo=DE&geo=FR
              One table for the asked countries (JSON-stat).
    ILO       https://sdmx.ilo.org/rest/data/ILO,DF_UNE_DEAP_SEX_AGE_RT/JPN.A..SEX_T.AGE_YTHADULT_YGE15?lastNObservations=10
              One country per request (SDMX-ML). Asked slowly: the service refused a machine that asked in quick succession.
    OECD      https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0/JPN+USA..._Z.Y._T.Y_GE15..A
              ?startPeriod=2020&format=csvfilewithlabels      (SDMX-CSV with labels)

The address shapes above answered from a real machine. The answers'
layouts are read as their standards describe them (SDMX-JSON, SDMX-ML,
JSON-stat) and tolerantly; what a reader does not recognise is an error that
says what it received, never a guessed number. Every result names the
provider's own label for what was read, so a wrong series cannot pass as the
right one unnoticed.
"""
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ElementTree

from . import statdata, usstats

MAX_BYTES = 4 * 1024 * 1024
NoSeries = usstats.NoSeries

# What a result says about each provider.
PROVIDERS = {
    'worldbank': 'World Bank Open Data',
    'imf': 'IMF World Economic Outlook',
    'eurostat': 'Eurostat',
    'ilo': 'ILOSTAT (International Labour Organization)',
    'oecd': 'OECD Data Explorer',
    **usstats.PROVIDERS,  # United States only: bea, bls, eia, treasury
}
# Seconds between two requests to one provider. The ILO refused (HTTP 403) a machine that asked in quick succession.
PAUSE = {'ilo': 3.0}

# source: {indicator key: specification}. The keys are the same plain names
# stat_lookup uses for the World Bank, so one name can be asked of several
# providers and the answers compared.
IMF = {
    # World Economic Outlook series. The latest years are IMF staff estimates and projections.
    'population': ('LP', 'Population', 'millions of persons'),
    'gdp': ('NGDPD', 'Gross domestic product, current prices', 'billions of U.S. dollars'),
    'gdp_growth': ('NGDP_RPCH', 'Gross domestic product, constant prices', 'percent change'),
    'gdp_per_capita': ('NGDPDPC', 'Gross domestic product per capita, current prices', 'U.S. dollars'),
    'gdp_per_capita_ppp': ('PPPPC', 'Gross domestic product per capita, current prices (PPP)', 'international dollars'),
    'inflation': ('PCPIPCH', 'Inflation, average consumer prices', 'percent change'),
    'cpi': ('PCPI', 'Inflation, average consumer prices', 'index'),
    'unemployment': ('LUR', 'Unemployment rate', 'percent of total labor force'),
    'government_debt': ('GGXWDG_NGDP', 'General government gross debt', 'percent of GDP'),
}
EUROSTAT = {
    # table, unit, and for each dimension that may hold several categories the one that is meant.
    'population': ('tps00001', 'persons (on 1 January)', {}),
    'gdp_growth': ('tec00115', 'percent change on previous year', {'unit': ('CLV_PCH_PRE',), 'na_item': ('B1GQ',)}),
    'inflation': ('tec00118', 'percent change (annual average, HICP)', {'unit': ('RCH_A_AVG',), 'coicop': ('CP00',)}),
    'unemployment': ('tps00203', 'percent of the labour force', {'unit': ('PC_ACT',), 'sex': ('T',), 'age': ('Y15-74',)}),
    'government_debt': ('sdg_17_40', 'percent of GDP', {'unit': ('PC_GDP',), 'sector': ('S13',), 'na_item': ('GD',)}),
}
ILO = {
    # dataflow, the key after the country (FREQ.MEASURE.SEX.AGE), unit
    'unemployment': ('DF_UNE_DEAP_SEX_AGE_RT', 'A..SEX_T.AGE_YTHADULT_YGE15', 'percent (age 15 and over)'),
    'youth_unemployment': ('DF_UNE_DEAP_SEX_AGE_RT', 'A..SEX_T.AGE_YTHADULT_Y15-24', 'percent (age 15 to 24)'),
}
OECD = {
    # dataflow, key with {countries} in the country's place, unit, and for a dimension left open the value that is meant.
    # The three keys answered from a real machine; Japan was absent from the consumer price series.
    'unemployment': ('OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0', '{countries}..._Z.Y._T.Y_GE15..A',
                     'percent of the labour force (seasonally adjusted, age 15 and over)',
                     {'MEASURE': ('UNE_LF_M', 'UNE_LF'), 'UNIT_MEASURE': ('PT_LF_SUB',)}),
    'gdp_growth': ('OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD,', 'A..{countries}.S1..B1GQ......GY.',
                   'percent change on the previous year', {'ADJUSTMENT': ('Y', 'N')}),
    'inflation': ('OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0', '{countries}.A.N.CPI.PA._T.N.GY',
                  'percent change on the previous year (consumer prices)', {}),
}
TABLES = {'imf': IMF, 'eurostat': EUROSTAT, 'ilo': ILO, 'oecd': OECD, **usstats.TABLES}

# Eurostat writes Greece and the United Kingdom differently, and has codes for its own groups.
_EUROSTAT_GEO = {'GRC': 'EL', 'GBR': 'UK', 'EUU': 'EU27_2020', 'EMU': 'EA20'}
_EXTRA_NAMES = {'youth unemployment': 'youth_unemployment', 'youth unemployment rate': 'youth_unemployment',
                '若年失業率': 'youth_unemployment', '若者の失業率': 'youth_unemployment'}


def source(value):
    """The provider's id: one of PROVIDERS (the World Bank when none is given)."""
    if value is None:
        return 'worldbank'
    name = statdata._plain(value) if isinstance(value, str) else ''
    name = {'world bank': 'worldbank', 'wb': 'worldbank', '世界銀行': 'worldbank', 'ilostat': 'ilo', 'weo': 'imf',
            '国際通貨基金': 'imf', 'ユーロスタット': 'eurostat', '国際労働機関': 'ilo', '経済協力開発機構': 'oecd',
            '商務省': 'bea', '経済分析局': 'bea', '労働省': 'bls', '労働統計局': 'bls', 'エネルギー省': 'eia',
            'エネルギー情報局': 'eia', '財務省': 'treasury', 'fiscaldata': 'treasury'}.get(name, name)
    if name not in PROVIDERS:
        raise ValueError('source must be one of: ' + ', '.join(PROVIDERS))
    return name


def indicator(provider, value):
    """(key, specification) of a built-in indicator for this provider; IMF also takes a WEO series code."""
    if provider in usstats.PROVIDERS:
        return usstats.indicator(provider, value)
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError('indicator must be a name such as ' + ', '.join(TABLES[provider]))
    plain = statdata._plain(value)
    key = _EXTRA_NAMES.get(plain) or statdata._INDICATOR_NAMES.get(plain) or plain.replace(' ', '_')
    table = TABLES[provider]
    if key in table:
        return key, table[key]
    code = value.strip().upper()
    if provider == 'imf' and re.fullmatch(r'[A-Z][A-Z0-9_]{1,24}', code):
        found = next((name for name, spec in IMF.items() if spec[0] == code), None)
        return (found, IMF[found]) if found else (code, (code, '', ''))  # another WEO series, by its code
    raise ValueError(f'{PROVIDERS[provider]} has no built-in indicator {value.strip()[:60]!r}. Available from this source: '
                     + ', '.join(table) + ('; or a World Economic Outlook series code such as NGDP_RPCH' if provider == 'imf' else '')
                     + '. Other sources: ' + ', '.join(name for name in PROVIDERS if name != provider))


# World Economic Outlook aggregates: the code used here -> the IMF's own. WLD and EMU are the codes the other
# providers' groups already have; the two below exist only at the IMF and are returned under its code.
IMF_AREAS = {'WLD': 'G001', 'EMU': 'G163', 'G110': 'G110', 'G200': 'G200'}
_IMF_GROUPS = {name: code for code, names in {
    'G110': ('g110', 'advanced economies', 'advanced economy', '先進国', '先進国・地域', '先進経済'),
    'G200': ('g200', 'emerging market and developing economies', 'emerging and developing economies',
             'emerging markets and developing economies', 'emde', '新興国・途上国', '新興市場国・発展途上国',
             '新興市場国と発展途上国', '新興国と途上国'),
    'WLD': ('g001',), 'EMU': ('g163',)}.items() for name in names}


def _imf_group(value):
    return _IMF_GROUPS.get(statdata._plain(value)) if isinstance(value, str) else None


def plan(provider, indicator_name, countries, start_year, end_year, this_year):
    """What to request: {'key', 'label', 'unit', 'codes', 'start', 'end', 'requests': [(url, [ISO3, ...])], 'page'}."""
    if provider in usstats.PROVIDERS:
        return _plan_us(provider, indicator_name, countries, start_year, end_year, this_year)
    if isinstance(countries, str):
        countries = [countries]
    if not isinstance(countries, list) or not 1 <= len(countries) <= statdata.MAX_COUNTRIES:
        raise ValueError(f'countries must be a list of 1 to {statdata.MAX_COUNTRIES} names or ISO codes')
    # The IMF publishes groups under its own codes; two of them have no ISO-like code elsewhere.
    codes = list(dict.fromkeys(_imf_group(item) or statdata.country(item) if provider == 'imf' else statdata.country(item)
                               for item in countries))
    key, spec = indicator(provider, indicator_name)
    end = this_year if end_year is None else end_year
    start = max(statdata.FIRST_YEAR, end - 9) if start_year is None else start_year
    for name, year in (('start_year', start), ('end_year', end)):
        if type(year) is not int or not statdata.FIRST_YEAR <= year <= this_year + 1:
            raise ValueError(f'{name} must be a year from {statdata.FIRST_YEAR} to {this_year + 1}')
    if start > end or end - start + 1 > statdata.MAX_YEARS:
        raise ValueError(f'start_year must not be after end_year, and the range may cover at most {statdata.MAX_YEARS} years')
    areas = {}
    if provider == 'imf':
        series, label, unit = spec
        areas = {code: IMF_AREAS[code] for code in codes if code in IMF_AREAS}
        requests = [(f'https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/{areas.get(code, code)}.{series}.A', [code])
                    for code in codes]
        page = f'https://www.imf.org/external/datamapper/{series}@WEO'
    elif provider == 'eurostat':
        table, unit, _wanted = spec
        label = ''
        geo = '&'.join('geo=' + _EUROSTAT_GEO.get(code, statdata.COUNTRIES.get(code, ('',))[0] or code) for code in codes)
        requests = [(f'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{table}?format=JSON&lang=EN&{geo}', codes)]
        page = f'https://ec.europa.eu/eurostat/databrowser/view/{table}/default/table?lang=en'
    elif provider == 'oecd':
        flow, key_shape, unit, _wanted = spec
        label = ''
        asked = key_shape.format(countries='+'.join(codes))
        requests = [('https://sdmx.oecd.org/public/rest/data/' + flow + '/' + asked
                     + f'?startPeriod={start}&format=csvfilewithlabels', codes)]
        # The Data Explorer page of the same table and selection (a person can open it; brackets and '+' are encoded).
        agency, table = flow.split(',')[:2]
        page = ('https://data-explorer.oecd.org/vis?df%5Bds%5D=dsDisseminateFinalDMZ&df%5Bid%5D=' + table.replace('@', '%40')
                + '&df%5Bag%5D=' + agency + '&dq=' + asked.replace('+', '%2B'))
    else:
        flow, rest, unit = spec
        label = ''
        # One country per request and only the latest years: the shape that answered in two seconds.
        # Several countries with a period filter took over thirty.
        last = max(1, min(statdata.MAX_YEARS, this_year - start + 1))
        requests = [(f'https://sdmx.ilo.org/rest/data/ILO,{flow}/{code}.{rest}?lastNObservations={last}', [code]) for code in codes]
        page = 'https://ilostat.ilo.org/data/'
    return {'key': key, 'spec': spec, 'label': label, 'unit': unit, 'codes': codes, 'start': start, 'end': end,
            'requests': requests, 'page': page, 'areas': areas}


def _years(start_year, end_year, this_year):
    end = this_year if end_year is None else end_year
    start = max(statdata.FIRST_YEAR, end - 9) if start_year is None else start_year
    for name, year in (('start_year', start), ('end_year', end)):
        if type(year) is not int or not statdata.FIRST_YEAR <= year <= this_year + 1:
            raise ValueError(f'{name} must be a year from {statdata.FIRST_YEAR} to {this_year + 1}')
    if start > end or end - start + 1 > statdata.MAX_YEARS:
        raise ValueError(f'start_year must not be after end_year, and the range may cover at most {statdata.MAX_YEARS} years')
    return start, end


def _plan_us(provider, indicator_name, countries, start_year, end_year, this_year):
    """A United States agency: one request, one country."""
    start, end = _years(start_year, end_year, this_year)
    key, spec, url, page, size, wait = usstats.plan(provider, indicator_name, countries, start, end)
    return {'key': key, 'spec': spec, 'label': spec[1], 'unit': spec[2], 'codes': ['USA'], 'start': start, 'end': end,
            'requests': [(url, ['USA'])], 'page': page, 'size': size, 'wait': wait, 'this_year': this_year,
            'index': usstats.is_index(spec),
            # The BEA's quarterly file gives the latest quarter beside the yearly figures.
            'extras': [(usstats.BEA_QUARTERS, 'quarter')] if provider == 'bea' else []}


# --- reading the answers -------------------------------------------------------------------------------

def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value == value and abs(value) != float('inf') else None
    if isinstance(value, str):
        return statdata._number(value)
    return None


def _shape(payload):
    """A few words on what was received, for an error a person can act on."""
    if isinstance(payload, dict):
        return 'an object with ' + (', '.join(sorted(str(key) for key in payload)[:8]) or 'no keys')
    if isinstance(payload, list):
        return f'a list of {len(payload)}'
    return type(payload).__name__


def sdmx_json(payload):
    """Series of an SDMX-JSON data message: [{'dims': {id: (value id, value name)}, 'obs': {period: number}}].

    Both layouts in use are read: version 1 (``structure``) and version 2
    (``data.structures``), with observations grouped by series or flat.
    """
    body = payload.get('data') if isinstance(payload, dict) and isinstance(payload.get('data'), dict) else payload
    if not isinstance(body, dict) or not isinstance(body.get('dataSets'), list):
        raise ValueError('the answer was not an SDMX data message (received ' + _shape(payload) + ')')
    structures = body.get('structures') if isinstance(body.get('structures'), list) else [body.get('structure')]
    structure = next((item for item in structures if isinstance(item, dict)), None)
    dimensions = structure.get('dimensions') if structure else None
    if not isinstance(dimensions, dict):
        raise ValueError('the SDMX answer has no description of its dimensions')

    def parts(name):
        rows = dimensions.get(name) if isinstance(dimensions.get(name), list) else []
        # A value is named by "id"; the IMF's time periods come as {"value": "1980"} without one.
        return [(str(row.get('id', '')), [(str(value.get('id') if value.get('id') is not None else value.get('value', '')),
                                           str(value.get('name', '') if not isinstance(value.get('name'), dict)
                                               else value['name'].get('en', '')))
                                          for value in row.get('values', []) if isinstance(value, dict)])
                for row in rows if isinstance(row, dict)]
    series_dims, obs_dims = parts('series'), parts('observation')

    def pick(dims, key):
        chosen = {}
        for (name, values), index in zip(dims, str(key).split(':')):
            if index.isdigit() and int(index) < len(values):
                chosen[name] = values[int(index)]
        return chosen
    found = {}
    for data_set in body['dataSets']:
        if not isinstance(data_set, dict):
            continue
        groups = data_set.get('series') if isinstance(data_set.get('series'), dict) else {'': data_set}
        for series_key, group in list(groups.items())[:2000]:
            observations = group.get('observations') if isinstance(group, dict) else None
            if not isinstance(observations, dict):
                continue
            series = pick(series_dims, series_key) if series_key else {}
            for obs_key, cell in list(observations.items())[:20000]:
                at = pick(obs_dims, obs_key)
                period = next((value[0] for name, value in at.items() if name in {'TIME_PERIOD', 'TIME'}), None)
                rest = {name: value for name, value in {**series, **at}.items() if name not in {'TIME_PERIOD', 'TIME'}}
                number = _number(cell[0] if isinstance(cell, list) and cell else cell)
                if period is None or number is None:
                    continue
                entry = found.setdefault(tuple(sorted((name, value[0]) for name, value in rest.items())), {'dims': rest, 'obs': {}})
                entry['obs'][period] = number
    return list(found.values())


def sdmx_xml(data):
    """Series of an SDMX-ML data message (generic or structure-specific), read by element names only."""
    text = data.decode('utf-8-sig', 'replace') if isinstance(data, (bytes, bytearray)) else str(data)
    if '<!DOCTYPE' in text[:4000].upper() or '<!ENTITY' in text.upper():
        raise ValueError('the XML answer declares entities, which the application does not read')
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ValueError('the answer was not readable XML') from None

    def local(element):
        return element.tag.rsplit('}', 1)[-1]
    result = []
    for series in root.iter():
        if local(series) != 'Series' or len(result) >= 2000:
            continue
        dims = {name: (value, '') for name, value in series.attrib.items()}
        obs, remarks = {}, {}

        def remark(name, value):
            # Attributes (a source, a note, a status): what can tell two records of one series apart.
            if name and value and len(remarks.setdefault(str(name)[:40], set())) < 4:
                remarks[str(name)[:40]].add(str(value)[:80])
        for child in series:
            name = local(child)
            if name == 'SeriesKey':
                for value in child:
                    if value.get('id') and value.get('value') is not None:
                        dims[value.get('id')] = (value.get('value'), '')
            elif name == 'Attributes':
                for value in child:
                    remark(value.get('id'), value.get('value'))
            elif name == 'Obs':
                period, number = child.get('TIME_PERIOD'), child.get('OBS_VALUE')
                for key, value in child.attrib.items():
                    if key not in {'TIME_PERIOD', 'OBS_VALUE'}:
                        remark(key, value)
                for part in child:
                    if local(part) == 'ObsDimension':
                        period = part.get('value')
                    elif local(part) == 'ObsValue':
                        number = part.get('value')
                    elif local(part) == 'Attributes':
                        for value in part:
                            remark(value.get('id'), value.get('value'))
                number = _number(number)
                if period and number is not None:
                    obs[period] = number
        result.append({'dims': dims, 'obs': obs, 'remarks': remarks})
    if not result and not any(local(element) in {'DataSet', 'GenericData', 'StructureSpecificData'} for element in root.iter()):
        raise ValueError(f'the XML answer was not an SDMX data message (its root is {local(root)[:40]})')
    return result


def sdmx(data):
    """Either SDMX layout, told apart by its first character."""
    text = data.decode('utf-8-sig', 'replace').lstrip() if isinstance(data, (bytes, bytearray)) else str(data).lstrip()
    if text.startswith('<'):
        return sdmx_xml(text)
    try:
        return sdmx_json(json.loads(text))
    except json.JSONDecodeError:
        raise ValueError('the answer was neither JSON nor XML') from None


def _annual(observations, start, end):
    return [{'year': int(period), 'value': observations[period]} for period in sorted(observations)
            if re.fullmatch(r'\d{4}', str(period)) and start <= int(period) <= end]


def _area(dims):
    """The country of a series, whatever the provider calls that dimension."""
    for name in ('COUNTRY', 'REF_AREA', 'GEO', 'geo', 'AREA'):
        if name in dims:
            return str(dims[name][0]).upper()
    return ''


def _one_series(rows, code, wanted=None):
    """(the series of a country, a remark or '') — or an error when several are different things.

    Several series that differ in a dimension are different statistics. Where
    the indicator says which value of that dimension it means, that one is
    taken; otherwise it is an error that shows the values, never a choice.

    Several records with the same dimensions are one statistic kept more than
    once (the ILO keeps one per national source). The record with the most
    recent year is used, and the remark says so and what tells them apart.
    """
    mine = [row for row in rows if _area(row['dims']) == code and row['obs']]
    if len(mine) <= 1:
        return (mine[0] if mine else None), ''

    def differing(group):
        return sorted({name for row in group for name, value in row['dims'].items()
                       if any(other['dims'].get(name, ('',))[0] != value[0] for other in group)})
    names = differing(mine)
    if names and wanted:
        for name in names:
            choice = next((value for value in wanted.get(name, ()) if any(row['dims'].get(name, ('',))[0] == value for row in mine)), None)
            if choice is not None:
                mine = [row for row in mine if row['dims'].get(name, ('',))[0] == choice]
        names = differing(mine)
        if len(mine) == 1:
            return mine[0], ''
    if names:
        shown = '; '.join(f"{name}: " + ' / '.join(sorted({str(row['dims'].get(name, ('',))[0]) for row in mine})[:6]) for name in names[:5])
        raise ValueError(f'the answer holds {len(mine)} different series for {code} ({shown}); the application does not choose '
                         'between them. Report this indicator from this source as unconfirmed')

    def recent(row):
        years = [int(period) for period in row['obs'] if re.fullmatch(r'\d{4}', str(period))]
        return (max(years, default=0), len(years))
    best = max(mine, key=recent)
    apart = sorted({name for row in mine for name in row.get('remarks', {})
                    if any(other.get('remarks', {}).get(name) != row.get('remarks', {}).get(name) for other in mine)})
    told = '; '.join(f"{name}: " + ' | '.join(' / '.join(sorted(row.get('remarks', {}).get(name, {'-'}))[:2]) for row in mine[:4])
                     for name in apart[:3])
    return best, (f'{code}: the provider keeps {len(mine)} records of this series' + (f' ({told})' if told else '')
                  + f'; the one with the most recent year ({recent(best)[0]}) was used')


def _series_result(rows, plan_, codes, wanted=None):
    result, label, remarks = {}, '', []
    for code in codes:
        # A group is asked for and answered under the provider's own code (the IMF's G001 for the world).
        row, remark = _one_series(rows, (plan_.get('areas') or {}).get(code, code), wanted)
        if row is None:
            continue
        values = _annual(row['obs'], plan_['start'], plan_['end'])
        if values:
            result[code] = (row['dims'].get('COUNTRY', row['dims'].get('REF_AREA', ('', '')))[1], values)
            if remark:
                remarks.append(remark)
        label = label or ' — '.join(value[1] for name, value in row['dims'].items()
                                    if value[1] and name not in {'COUNTRY', 'REF_AREA', 'FREQ', 'FREQUENCY'})[:200]
    return result, label, '', remarks


def read_series(data, plan_, codes):
    """IMF and ILO: the asked countries out of SDMX series."""
    return _series_result(sdmx(data), plan_, codes)


def read_csv(data, plan_, codes):
    """OECD: the asked countries out of SDMX-CSV with labels (a code column, then its label column).

    The columns up to TIME_PERIOD are the dimensions; what follows OBS_VALUE are attributes.
    """
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('the answer was not UTF-8 text') from None
    try:
        table = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        raise ValueError('the answer was not readable CSV') from None
    header = [cell.strip() for cell in table[0]] if table else []
    if not {'REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'} <= set(header):
        start = text.lstrip()[:60].replace('\n', ' ')
        raise ValueError('the answer was not an SDMX-CSV table with REF_AREA, TIME_PERIOD and OBS_VALUE (it begins: ' + start + ')')
    time_at, value_at = header.index('TIME_PERIOD'), header.index('OBS_VALUE')
    dimensions = [(index, name) for index, name in enumerate(header[:time_at])
                  if re.fullmatch(r'[A-Z][A-Z0-9_]*', name) and name not in {'STRUCTURE', 'STRUCTURE_ID', 'STRUCTURE_NAME', 'ACTION'}]
    codes_named, found = {name for _, name in dimensions}, {}
    for row in table[1:200001]:
        if len(row) <= max(time_at, value_at):
            continue
        number = _number(row[value_at])
        if number is None:
            continue
        # A code column is followed by its label column, unless the next column is another code.
        dims = {name: (row[index].strip(), row[index + 1].strip() if index + 1 < time_at and header[index + 1] not in codes_named else '')
                for index, name in dimensions}
        entry = found.setdefault(tuple(sorted((name, value[0]) for name, value in dims.items())), {'dims': dims, 'obs': {}})
        entry['obs'][row[time_at].strip()] = number
    return _series_result(list(found.values()), plan_, codes, plan_['spec'][3])


def read_jsonstat(payload, plan_, codes):
    """Eurostat: the asked countries out of a JSON-stat dataset. -> (found rows, table label, last update)."""
    if not (isinstance(payload, dict) and isinstance(payload.get('id'), list) and isinstance(payload.get('size'), list)
            and isinstance(payload.get('dimension'), dict) and 'value' in payload):
        detail = ''
        if isinstance(payload, dict) and isinstance(payload.get('error'), list) and payload['error']:
            first = payload['error'][0] if isinstance(payload['error'][0], dict) else {}
            detail = ': ' + str(first.get('label') or first.get('id') or '')[:200]
        raise ValueError('the answer was not a JSON-stat dataset' + (detail or ' (received ' + _shape(payload) + ')'))
    names, sizes = [str(name) for name in payload['id']], payload['size']
    if len(names) != len(sizes) or not all(type(size) is int and size >= 0 for size in sizes):
        raise ValueError('the JSON-stat dataset describes its dimensions inconsistently')
    categories = []
    for name, size in zip(names, sizes):
        category = payload['dimension'].get(name, {}).get('category', {}) if isinstance(payload['dimension'].get(name), dict) else {}
        index, labels = category.get('index'), category.get('label') if isinstance(category.get('label'), dict) else {}
        if isinstance(index, dict):
            ordered = [key for key, _ in sorted(index.items(), key=lambda item: item[1])]
        elif isinstance(index, list):
            ordered = [str(key) for key in index]
        else:
            ordered = list(labels)
        if len(ordered) != size:
            raise ValueError(f'the JSON-stat dimension {name[:30]} does not list its {size} categories')
        categories.append((ordered, labels))
    wanted = plan_['spec'][2]
    fixed, detail = {}, []
    for position, name in enumerate(names):
        if name.lower() in {'geo', 'time'}:
            continue
        ordered, labels = categories[position]
        if len(ordered) == 1:
            fixed[position] = 0
        else:
            choice = next((ordered.index(code) for code in wanted.get(name.lower(), ()) if code in ordered), None)
            if choice is None:
                raise ValueError(f'the table holds several categories for {name[:30]} (' + ', '.join(ordered[:8])
                                 + ') and none is the one this indicator means; the application does not choose. '
                                   'Report this indicator from this source as unconfirmed')
            fixed[position] = choice
        detail.append(f'{labels.get(ordered[fixed[position]], ordered[fixed[position]])}')
    try:
        geo_at, time_at = next(i for i, name in enumerate(names) if name.lower() == 'geo'), next(
            i for i, name in enumerate(names) if name.lower() == 'time')
    except StopIteration:
        raise ValueError('the JSON-stat dataset has no geo or time dimension') from None
    values = payload['value']

    def cell(indexes):
        flat = 0
        for index, size in zip(indexes, sizes):
            flat = flat * size + index
        raw = values.get(str(flat)) if isinstance(values, dict) else (values[flat] if isinstance(values, list) and flat < len(values) else None)
        return _number(raw)
    result = {}
    geo_codes, geo_labels = categories[geo_at]
    for code in codes:
        geo = _EUROSTAT_GEO.get(code, statdata.COUNTRIES.get(code, ('',))[0] or code)
        if geo not in geo_codes:
            continue
        observations = {}
        for at, period in enumerate(categories[time_at][0]):
            indexes = [fixed.get(position, 0) for position in range(len(names))]
            indexes[geo_at], indexes[time_at] = geo_codes.index(geo), at
            number = cell(indexes)
            if number is not None:
                observations[period] = number
        chosen = _annual(observations, plan_['start'], plan_['end'])
        if chosen:
            result[code] = (str(geo_labels.get(geo, ''))[:80], chosen)
    label = str(payload.get('label') or '')[:200] + (' (' + '; '.join(detail)[:200] + ')' if detail else '')
    return result, label, str(payload.get('updated') or '')[:25], []


def read(provider, data, plan_, codes):
    """(rows by ISO3 code, the provider's own label for what was read, the provider's update time or '', remarks)."""
    if provider in usstats.PROVIDERS:
        values, label, updated, remarks, extra = usstats.read(
            provider, data, plan_['spec'][0], plan_['start'], plan_['end'], index=plan_.get('index', False),
            this_year=plan_.get('this_year'), role=plan_.get('role', ''))
        return ({'USA': ('United States', values, extra)} if values or extra else {}), label, updated, remarks
    if provider == 'oecd':
        return read_csv(data, plan_, codes)
    if provider == 'eurostat':
        try:
            payload = json.loads(data.decode('utf-8-sig'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError('the answer was not JSON') from None
        return read_jsonstat(payload, plan_, codes)
    return read_series(data, plan_, codes)
