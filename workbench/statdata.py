"""Country statistics read straight from World Bank Open Data (no key, no search).

Most searches of a statistics task only look for the page that holds a
well-known figure (population, GDP growth, consumer prices, unemployment). The
World Bank publishes those series through a public JSON API, so the application
can ask for the numbers directly:

    https://api.worldbank.org/v2/country/JPN;USA/indicator/SP.POP.TOTL?format=json&date=2015:2024

This module only names things and reads the answer; the request itself is sent
by WebTools with the same rules as every other fetch (public address, explicit
proxy only, size limit). The destination is fixed: the model chooses countries,
an indicator and years, never a host.
"""
from __future__ import annotations

import re
import unicodedata

API = 'https://api.worldbank.org/v2'
PAGE = 'https://data.worldbank.org/indicator'
SOURCE = 'World Bank Open Data'
MAX_COUNTRIES, MAX_YEARS, FIRST_YEAR = 12, 60, 1960

# key: (World Bank indicator code, what it is, other names a model or a person may use)
INDICATORS = {
    'population': ('SP.POP.TOTL', 'Population, total', ('人口', '総人口', 'total population')),
    'population_growth': ('SP.POP.GROW', 'Population growth (annual %)', ('人口増加率', '人口成長率')),
    'gdp': ('NY.GDP.MKTP.CD', 'GDP (current US$)', ('名目gdp', 'gdp current', 'nominal gdp', '国内総生産')),
    'gdp_growth': ('NY.GDP.MKTP.KD.ZG', 'GDP growth (annual %)',
                   ('gdp成長率', '経済成長率', '実質gdp成長率', 'real gdp growth', 'gdp growth rate', 'economic growth')),
    'gdp_per_capita': ('NY.GDP.PCAP.CD', 'GDP per capita (current US$)', ('一人当たりgdp', '1人当たりgdp', '一人あたりgdp', '1人あたりgdp')),
    'gdp_per_capita_ppp': ('NY.GDP.PCAP.PP.CD', 'GDP per capita, PPP (current international $)',
                           ('一人当たりgdp（購買力平価）', 'gdp per capita ppp')),
    'inflation': ('FP.CPI.TOTL.ZG', 'Inflation, consumer prices (annual %)',
                  ('インフレ率', '物価上昇率', '消費者物価上昇率', 'cpi inflation', 'inflation rate', 'cpi上昇率')),
    'cpi': ('FP.CPI.TOTL', 'Consumer price index (2010 = 100)', ('消費者物価指数', 'consumer price index')),
    'unemployment': ('SL.UEM.TOTL.ZS', 'Unemployment, total (% of total labor force) (modeled ILO estimate)',
                     ('失業率', 'unemployment rate')),
    'life_expectancy': ('SP.DYN.LE00.IN', 'Life expectancy at birth, total (years)', ('平均寿命', '出生時平均余命')),
    'fertility': ('SP.DYN.TFRT.IN', 'Fertility rate, total (births per woman)', ('合計特殊出生率', '出生率', 'fertility rate')),
    'urban_share': ('SP.URB.TOTL.IN.ZS', 'Urban population (% of total population)', ('都市人口比率', '都市人口割合')),
    'exports': ('NE.EXP.GNFS.ZS', 'Exports of goods and services (% of GDP)', ('輸出のgdp比', '輸出比率')),
    'imports': ('NE.IMP.GNFS.ZS', 'Imports of goods and services (% of GDP)', ('輸入のgdp比', '輸入比率')),
    'trade': ('NE.TRD.GNFS.ZS', 'Trade (% of GDP)', ('貿易のgdp比', '貿易依存度')),
    'government_debt': ('GC.DOD.TOTL.GD.ZS', 'Central government debt, total (% of GDP)',
                                     ('政府債務のgdp比', '政府債務残高')),
}

# ISO 3166 alpha-3: (alpha-2, English name, other names)
COUNTRIES = {
    'ARG': ('AR', 'Argentina', ('アルゼンチン',)), 'AUS': ('AU', 'Australia', ('オーストラリア', '豪州')),
    'AUT': ('AT', 'Austria', ('オーストリア',)), 'BGD': ('BD', 'Bangladesh', ('バングラデシュ',)),
    'BEL': ('BE', 'Belgium', ('ベルギー',)), 'BRA': ('BR', 'Brazil', ('ブラジル',)),
    'CAN': ('CA', 'Canada', ('カナダ',)), 'CHE': ('CH', 'Switzerland', ('スイス',)),
    'CHL': ('CL', 'Chile', ('チリ',)), 'CHN': ('CN', 'China', ('中国', '中華人民共和国')),
    'COL': ('CO', 'Colombia', ('コロンビア',)), 'CZE': ('CZ', 'Czechia', ('チェコ', 'czech republic')),
    'DEU': ('DE', 'Germany', ('ドイツ',)), 'DNK': ('DK', 'Denmark', ('デンマーク',)),
    'EGY': ('EG', 'Egypt', ('エジプト', 'egypt, arab rep.')), 'ESP': ('ES', 'Spain', ('スペイン',)),
    'ETH': ('ET', 'Ethiopia', ('エチオピア',)), 'FIN': ('FI', 'Finland', ('フィンランド',)),
    'FRA': ('FR', 'France', ('フランス',)), 'GBR': ('GB', 'United Kingdom', ('イギリス', '英国', 'uk', 'britain', 'great britain')),
    'GRC': ('GR', 'Greece', ('ギリシャ',)), 'HKG': ('HK', 'Hong Kong', ('香港', 'hong kong sar, china')),
    'HUN': ('HU', 'Hungary', ('ハンガリー',)), 'IDN': ('ID', 'Indonesia', ('インドネシア',)),
    'IND': ('IN', 'India', ('インド',)), 'IRL': ('IE', 'Ireland', ('アイルランド',)),
    'IRN': ('IR', 'Iran', ('イラン', 'iran, islamic rep.')), 'ISR': ('IL', 'Israel', ('イスラエル',)),
    'ITA': ('IT', 'Italy', ('イタリア',)), 'JPN': ('JP', 'Japan', ('日本',)),
    'KEN': ('KE', 'Kenya', ('ケニア',)), 'KOR': ('KR', 'South Korea', ('韓国', '大韓民国', 'korea', 'korea, rep.', 'republic of korea')),
    'MEX': ('MX', 'Mexico', ('メキシコ',)), 'MYS': ('MY', 'Malaysia', ('マレーシア',)),
    'NGA': ('NG', 'Nigeria', ('ナイジェリア',)), 'NLD': ('NL', 'Netherlands', ('オランダ',)),
    'NOR': ('NO', 'Norway', ('ノルウェー',)), 'NZL': ('NZ', 'New Zealand', ('ニュージーランド',)),
    'PAK': ('PK', 'Pakistan', ('パキスタン',)), 'PER': ('PE', 'Peru', ('ペルー',)),
    'PHL': ('PH', 'Philippines', ('フィリピン',)), 'POL': ('PL', 'Poland', ('ポーランド',)),
    'PRT': ('PT', 'Portugal', ('ポルトガル',)), 'ROU': ('RO', 'Romania', ('ルーマニア',)),
    'RUS': ('RU', 'Russia', ('ロシア', 'russian federation')), 'SAU': ('SA', 'Saudi Arabia', ('サウジアラビア',)),
    'SGP': ('SG', 'Singapore', ('シンガポール',)), 'SWE': ('SE', 'Sweden', ('スウェーデン',)),
    'THA': ('TH', 'Thailand', ('タイ',)), 'TUR': ('TR', 'Türkiye', ('トルコ', 'turkey', 'turkiye')),
    'TWN': ('TW', 'Taiwan', ('台湾',)), 'UKR': ('UA', 'Ukraine', ('ウクライナ',)),
    'ARE': ('AE', 'United Arab Emirates', ('アラブ首長国連邦', 'uae')),
    'USA': ('US', 'United States', ('アメリカ', '米国', 'アメリカ合衆国', 'us', 'united states of america', 'america')),
    'VNM': ('VN', 'Vietnam', ('ベトナム', 'viet nam')), 'ZAF': ('ZA', 'South Africa', ('南アフリカ', '南アフリカ共和国')),
    # Groups the World Bank publishes under their own codes.
    'WLD': ('1W', 'World', ('世界', '全世界')), 'EUU': ('EU', 'European Union', ('欧州連合', 'eu')),
    'OED': ('OE', 'OECD members', ('oecd', 'oecd加盟国')), 'EMU': ('XC', 'Euro area', ('ユーロ圏', 'eurozone')),
}


def _plain(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value)).casefold()).strip()


_INDICATOR_NAMES = {}
for _key, (_code, _label, _others) in INDICATORS.items():
    for _name in (_key, _key.replace('_', ' '), _code, _label, *_others):
        _INDICATOR_NAMES[_plain(_name)] = _key
_COUNTRY_NAMES = {}
for _iso3, (_iso2, _english, _others) in COUNTRIES.items():
    for _name in (_iso3, _iso2, _english, *_others):
        _COUNTRY_NAMES.setdefault(_plain(_name), _iso3)

# Words that tell two questions apart even when everything else is the same
# ("... Japan ..." and "... Germany ..."): every word of every country name.
COUNTRY_WORDS = frozenset(word for _iso2, english, others in COUNTRIES.values() for name in (english, *others)
                          for word in re.findall(r'[^\W_]+', _plain(name))
                          if len(word) > 2 and word not in {'and', 'the', 'rep', 'sar', 'members', 'area', 'arab', 'islamic'})


def indicator(value):
    """(World Bank code, label) for a built-in name or a World Bank indicator code."""
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError('indicator must be a name such as ' + ', '.join(list(INDICATORS)[:6]) + ' …, or a World Bank indicator code')
    key = _INDICATOR_NAMES.get(_plain(value))
    if key:
        return INDICATORS[key][0], INDICATORS[key][1]
    code = value.strip().upper()
    if re.fullmatch(r'[A-Z0-9]{2,10}(\.[A-Z0-9]{1,10}){1,6}', code):
        return code, ''  # any other World Bank series, by its code
    raise ValueError(f'Unknown indicator {value.strip()[:60]!r}. Use one of: ' + ', '.join(INDICATORS)
                     + '; or a World Bank indicator code such as NY.GDP.MKTP.KD.ZG')


def country(value):
    """ISO alpha-3 code for a name, an alpha-2 or an alpha-3 code."""
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValueError('each country must be a name or an ISO code, e.g. "Japan", "日本", "JPN"')
    found = _COUNTRY_NAMES.get(_plain(value))
    if found:
        return found
    code = value.strip().upper()
    if re.fullmatch(r'[A-Z]{3}', code):
        return code  # a country the table does not list, by its ISO alpha-3 code
    raise ValueError(f'Unknown country {value.strip()[:40]!r}. Use an English or Japanese name of a major economy, '
                     'or the ISO alpha-3 code (e.g. JPN, USA, DEU, WLD for the world)')


def request(countries, indicator_name, start_year, end_year, this_year):
    """(API URL, page URL, indicator code, label, codes, start, end) for one lookup."""
    if isinstance(countries, str):
        countries = [countries]
    if not isinstance(countries, list) or not 1 <= len(countries) <= MAX_COUNTRIES:
        raise ValueError(f'countries must be a list of 1 to {MAX_COUNTRIES} names or ISO codes')
    codes = list(dict.fromkeys(country(item) for item in countries))
    code, label = indicator(indicator_name)
    end = this_year if end_year is None else end_year
    start = max(FIRST_YEAR, end - 9) if start_year is None else start_year
    for name, year in (('start_year', start), ('end_year', end)):
        if type(year) is not int or not FIRST_YEAR <= year <= this_year + 1:
            raise ValueError(f'{name} must be a year from {FIRST_YEAR} to {this_year + 1}')
    if start > end or end - start + 1 > MAX_YEARS:
        raise ValueError(f'start_year must not be after end_year, and the range may cover at most {MAX_YEARS} years')
    url = f'{API}/country/{";".join(codes)}/indicator/{code}?format=json&date={start}:{end}&per_page=1000'
    places = '-'.join(COUNTRIES[item][0] for item in codes if item in COUNTRIES)
    return url, f'{PAGE}/{code}' + (f'?locations={places}' if places else ''), code, label, codes, start, end


def read(payload, code, label, codes):
    """Turn the API's answer into series per country; raise ValueError when it is an error or not understood."""
    if isinstance(payload, list) and payload and isinstance(payload[0], dict) and 'message' in payload[0]:
        messages = payload[0]['message'] if isinstance(payload[0]['message'], list) else []
        detail = '; '.join(str(item.get('value') or item.get('key') or '')[:200] for item in messages if isinstance(item, dict))
        raise ValueError('World Bank did not accept the request' + (f' ({detail})' if detail else '')
                         + '. Check the country codes and the indicator code')
    if not (isinstance(payload, list) and len(payload) == 2 and isinstance(payload[0], dict)):
        raise ValueError('The World Bank answer was not in the expected form; report that the figures could not be read')
    rows = payload[1] if isinstance(payload[1], list) else []
    series, names = {item: [] for item in codes}, {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        place = row.get('country') if isinstance(row.get('country'), dict) else {}
        iso3 = str(row.get('countryiso3code') or '').upper()
        if iso3 not in series:
            # Groups such as the world come back with a two-character id only.
            iso3 = next((item for item in codes if COUNTRIES.get(item, ('',))[0] == str(place.get('id') or '').upper()), iso3)
        value, year = row.get('value'), str(row.get('date') or '')
        if iso3 not in series or not re.fullmatch(r'\d{4}', year):
            continue
        names.setdefault(iso3, str(place.get('value') or '')[:80])
        name = row.get('indicator', {}).get('value') if isinstance(row.get('indicator'), dict) else ''
        label = label or str(name or '')[:200]
        if type(value) in {int, float} and value == value and abs(value) != float('inf'):
            series[iso3].append({'year': int(year), 'value': value})
    result, missing = [], []
    for item in codes:
        values = sorted(series[item], key=lambda entry: entry['year'])
        if not values:
            missing.append(item)
            continue
        result.append({'country': names.get(item) or COUNTRIES.get(item, ('', item))[1], 'code': item,
                       'values': values, 'latest': values[-1]})
    updated = str(payload[0].get('lastupdated') or '')[:20]
    return {'indicator': {'id': code, 'name': label}, 'series': result, 'no_values': missing, 'last_updated': updated}
