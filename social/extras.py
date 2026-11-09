"""Post ideas that look back in time: this day ten years ago, how each renewable has grown, and sites that recently opened.

Sources: Elexon generation records, and the government's Renewable Energy Planning Database (large-scale sites only).
"""
import collections, csv, datetime as dt, json, math, pathlib, random, urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
LAT0 = 54.0
ELEXON = 'https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH'
GROUP = {'CCGT': 'gas', 'OCGT': 'gas', 'COAL': 'coal', 'NUCLEAR': 'nuclear', 'WIND': 'wind', 'BIOMASS': 'biomass', 'NPSHYD': 'hydro'}
LABEL = {'coal': 'coal', 'gas': 'gas', 'wind': 'wind', 'nuclear': 'nuclear'}
TECH = {'Wind Offshore': ('offshore wind', 'wind'), 'Solar Photovoltaics': ('large-scale solar', 'solar'), 'Battery': ('grid batteries', 'hydro'), 'Wind Onshore': ('onshore wind', 'wind')}


def clip(v):
    return max(.15, min(1, v))


def bng_to_ll(E, N):
    a, b, F0, lat0, lon0, N0, E0 = 6377563.396, 6356256.909, 0.9996012717, math.radians(49), math.radians(-2), -100000, 400000
    e2 = 1 - b * b / (a * a); n = (a - b) / (a + b)
    lat, M = lat0, 0
    while True:
        lat = (N - N0 - M) / (a * F0) + lat
        Ma = (1 + n + 5 / 4 * n ** 2 + 5 / 4 * n ** 3) * (lat - lat0)
        Mb = (3 * n + 3 * n ** 2 + 21 / 8 * n ** 3) * math.sin(lat - lat0) * math.cos(lat + lat0)
        Mc = (15 / 8 * n ** 2 + 15 / 8 * n ** 3) * math.sin(2 * (lat - lat0)) * math.cos(2 * (lat + lat0))
        Md = 35 / 24 * n ** 3 * math.sin(3 * (lat - lat0)) * math.cos(3 * (lat + lat0))
        M = b * F0 * (Ma - Mb + Mc - Md)
        if abs(N - N0 - M) < 0.01:
            break
    s, c, t = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * F0 / math.sqrt(1 - e2 * s * s); rho = a * F0 * (1 - e2) / (1 - e2 * s * s) ** 1.5; eta2 = nu / rho - 1
    d = E - E0
    VII = t / (2 * rho * nu); VIII = t / (24 * rho * nu ** 3) * (5 + 3 * t * t + eta2 - 9 * t * t * eta2)
    X = 1 / (c * nu); XI = 1 / (c * 6 * nu ** 3) * (nu / rho + 2 * t * t)
    return math.degrees(lat - VII * d ** 2 + VIII * d ** 4), math.degrees(lon0 + X * d - XI * d ** 3)


def to_xy(lat, lon):
    return [round((lon + 2.0) * 111.32 * math.cos(math.radians(LAT0)), 1), round((lat - 54.0) * 110.57, 1)]


def day_mix(day, up_to):
    url = f'{ELEXON}?settlementDateFrom={day}&settlementDateTo={day}&format=json'
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'wheres-my-energy-agent/1.0', 'Accept': 'application/json'}), timeout=60) as r:
        rows = json.load(r)['data']
    totals, periods = collections.Counter(), set()
    for row in rows:
        if row['settlementPeriod'] > up_to:
            continue
        periods.add(row['settlementPeriod'])
        key = 'imports' if row['fuelType'].startswith('INT') else GROUP.get(row['fuelType'], 'other')
        totals[key] += max(0, row['generation'])
    total = sum(totals.values())
    return ({k: v / total * 100 for k, v in totals.items()}, len(periods)) if total else ({}, 0)


def lookback(now, choices, salt):
    """A different distance back on different days, so the history posts don't all read the same."""
    return random.Random(f'{now.date()}{salt}').choice(choices)


def ago_words(n):
    return 'a year ago' if n == 1 else f'{n} years ago'


def on_this_day(now):
    """Today so far against the same hours of the same date in an earlier year. Metered generation on both sides, so it compares like with like."""
    back = lookback(now, (1, 2, 3, 5, 8, 10), 'day')
    try:
        then_day = now.date().replace(year=now.year - back)
    except ValueError:
        return []
    period = now.hour * 2 + (now.minute >= 30)
    if period < 8:
        return []
    today, got = day_mix(now.date(), period)
    then, got_then = day_mix(then_day, period)
    if got < 8 or got_then < 8:
        return []
    fuel = max(('coal', 'wind', 'gas'), key=lambda k: abs(today.get(k, 0) - then.get(k, 0)))
    a, b = round(then.get(fuel, 0)), round(today.get(fuel, 0))
    renew = lambda m: round(m.get('wind', 0) + m.get('biomass', 0) + m.get('hydro', 0))
    date_words = f'{then_day.day} {then_day:%B %Y}'
    words = f'On {date_words}, {LABEL[fuel]} made {a}% of the power on Britain\'s main grid at this point in the day. Today it is {b}%.'
    return [{'id': 'on-this-day', 'type': 'on-this-day', 'cat': 'history', 'art': 'year', 'limit': 60, 'novelty': clip(abs(a - b) / 25), 'shows': words, 'caption': words, 'alt': words,
             'spec': {'art': 'year', 'eyebrow': f'THIS DAY IN {then_day.year}', 'big': f'{a}%', 'sub': f'of our grid power came from {LABEL[fuel]}. Today: {b}%.', 'mixBars': [[str(then_day.year), then, renew(then)], [str(now.year), today, renew(today)]], 'month': [], 'foot': ['Metered generation so far today against the same hours then. Elexon.']}}]


def repd_rows():
    rows = []
    for r in csv.DictReader(open(HERE / 'data' / 'repd.csv', encoding='latin-1')):
        if (r.get('Development Status (short)') or '').strip() != 'Operational' or r.get('Country') == 'Northern Ireland':
            continue
        try:
            when = dt.datetime.strptime((r.get('Operational') or '')[:10], '%d/%m/%Y').date()
            mw = float((r.get('Installed Capacity (MWelec)') or '0').replace(',', ''))
        except ValueError:
            continue
        rows.append((when, mw, r))
    return rows


def growth(rows, now):
    newest = max(w for w, _, _ in rows)
    out = []
    for tech, (name, fuel) in TECH.items():
        mine = [(w, mw) for w, mw, r in rows if r.get('Technology Type') == tech]
        at = lambda d: sum(mw for w, mw in mine if w <= d)
        back = lookback(now, (3, 5, 7, 10), tech)
        latest, then_day = at(newest), newest.replace(year=newest.year - back)
        then = at(then_day)
        if latest < 500:
            continue
        years = list(range(newest.year - back, newest.year + 1))
        bars = [[str(y), round(at(min(dt.date(y, newest.month, min(newest.day, 28)), newest)))] for y in years]
        ratio = latest / max(then, 1)
        grown = 'gone from almost nothing' if then < 100 else 'more than tripled' if ratio >= 3 else 'more than doubled' if ratio >= 2 else 'grown by over half' if ratio >= 1.5 else 'kept growing'
        have = 'have' if name.endswith('s') else 'has'
        words = f"In {back} years, Britain's {name} {have} {grown}: from {round(then):,} MW to {round(latest):,} MW."
        out.append({'id': 'growth-' + tech.lower().replace(' ', '-'), 'type': 'growth', 'cat': 'history', 'art': 'bars', 'limit': 85, 'novelty': .45 + (.2 if ratio >= 3 else 0), 'shows': words, 'caption': words, 'alt': words,
                    'spec': {'art': 'bars', 'eyebrow': f'{back} YEARS OF CHANGE', 'headline': f"Britain's {name} {have} {grown} in {back} years." if then >= 100 else f"Britain's {name}: from almost nothing to {round(latest):,} MW in {back} years.", 'bars': bars, 'fuel': fuel, 'rows': [[f'{then_day:%B %Y}', f'{round(then):,} MW'], [f'{newest:%B %Y}', f'{round(latest):,} MW']], 'foot': ['Large-scale operating sites, government planning database.']}})
    return out


def new_sites(rows, posted):
    newest = max(w for w, _, _ in rows)
    picks = sorted((x for x in rows if x[0] >= newest - dt.timedelta(days=150) and x[1] >= 20 and x[2].get('Technology Type') in ('Solar Photovoltaics', 'Wind Onshore', 'Wind Offshore', 'Battery')), key=lambda x: x[1], reverse=True)
    for when, mw, r in picks:
        name = (r.get('Site Name') or '').split(' - ')[0].strip()
        if not name or any(name in text for text in posted):
            continue
        try:
            lat, lon = bng_to_ll(float(r['X-coordinate'].replace(',', '')), float(r['Y-coordinate'].replace(',', '')))
        except ValueError:
            continue
        kind, fuel = {'Solar Photovoltaics': ('solar farm', 'solar'), 'Wind Onshore': ('wind farm', 'wind'), 'Wind Offshore': ('offshore wind farm', 'wind'), 'Battery': ('battery site', 'hydro')}[r['Technology Type']]
        place = (r.get('County') or r.get('Region') or '').strip()
        words = f"{name}, a {round(mw)} MW {kind}{' in ' + place if place else ''}, started operating in {when:%B %Y}."
        return [{'id': 'new-site', 'type': 'new-site', 'cat': 'new', 'art': 'map', 'limit': 60, 'novelty': .8, 'shows': words, 'caption': words, 'alt': words,
                 'spec': {'art': 'map', 'glow': None, 'fuelGlow': fuel, 'eyebrow': 'NEW ON THE GRID', 'big': f'{round(mw)} MW', 'sub': f'{kind} now running: {name}.', 'list': [], 'spot': to_xy(lat, lon), 'spotFuel': fuel, 'spotLabel': name, 'foot': [f'Started operating {when:%B %Y}. Government planning database.']}}]
    return []


def build(now, posted):
    """Each source is optional: if one fails the agent simply has fewer ideas that day."""
    out = []
    for name, fn in (('on this day', lambda: on_this_day(now)), ('growth', lambda: growth(repd_rows(), now)), ('new sites', lambda: new_sites(repd_rows(), posted))):
        try:
            out += fn()
        except Exception as e:
            print('extra failed', name, e)
    return out
