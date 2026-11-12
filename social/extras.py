"""Post ideas that look back in time: one fuel's yearly share since 2019, how each renewable has grown, and sites that recently opened.

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


# Why each fuel's yearly share changed. Each reason is a published fact, so a post can say why rather than just show two numbers.
WHY = {
    'gas': ('fell', "Gas fell as wind took over more of the work. It still fills the gap when the wind drops, so a calm year like 2021 pushed it back up."),
    'wind': ('grew', "Wind grew as big new offshore wind farms opened, such as Hornsea 2 in 2022 and Seagreen in 2023. It dipped in 2021, an unusually calm year."),
    'nuclear': ('fell', "Nuclear fell as older power stations closed, including Hunterston B in January 2022 and Hinkley Point B in August 2022."),
    'coal': ('ended', "Coal ended when Britain's last coal power station, Ratcliffe-on-Soar, closed on 30 September 2024."),
    'imports': ('grew', "Imports grew as new undersea cables opened to Norway in 2021 and Denmark in 2023. They dipped in 2022, when many French reactors were shut for repairs and Britain sent power to France instead."),
    'solar': ('grew', "Solar grew as more solar farms and rooftop panels were fitted."),
}
NAME = {'gas': 'Gas', 'wind': 'Wind', 'nuclear': 'Nuclear', 'coal': 'Coal', 'imports': 'Imports', 'solar': 'Solar'}


def year_trend(now):
    """One fuel's share of Britain's power, as a yearly average for every full year since 2019, with the published reason it changed.
    Whole years against whole years shows the trend; a single day against a single day mostly shows the weather."""
    data = json.loads((HERE / 'social' / 'annual_mix.json').read_text(encoding='utf8'))
    years = sorted(data['years'])
    first, last = years[0], years[-1]
    share = lambda y, f: data['years'][y]['mix'].get(f, 0)
    fuel = random.Random(f'{now.date()}trend').choice([f for f in WHY if abs(share(last, f) - share(first, f)) >= 1])
    a, b = share(first, fuel), share(last, fuel)
    fmt = lambda v: f'{v:.1f}%' if v < 2 else f'{round(v)}%'
    bars = [[y, round(share(y, fuel), 1)] for y in years]
    why = WHY[fuel][1]
    headline = (f"{NAME[fuel]} made {fmt(a)} of Britain's power in {first}. In {last}: {fmt(b)}." if b >= .5 else f"{NAME[fuel]} made {fmt(a)} of Britain's power in {first}. By {last}, none.")
    yearly = ', '.join(f'{y} {fmt(share(y, fuel))}' for y in years)
    words = f"{headline} Yearly averages: {yearly}. Why: {why}"
    return [{'id': 'year-trend', 'type': 'year-trend', 'cat': 'history', 'art': 'bars', 'limit': 90, 'novelty': .55, 'shows': words, 'caption': f'{headline} {why}', 'alt': f"Bar chart of {fuel} as a share of Britain's power each year: {yearly}.",
             'spec': {'art': 'bars', 'eyebrow': f'{first} TO {last}, YEAR BY YEAR', 'headline': headline, 'bars': bars, 'values': True, 'fuel': 'hydro' if fuel == 'imports' else fuel,
                      'rows': [[f'{first} average', fmt(a)], [f'{last} average', fmt(b)]], 'note': why, 'foot': ['Yearly averages. NESO Carbon Intensity API.']}}]


def money(v):
    return f'£{v:,}'


def demand_years(now):
    """How much electricity the UK uses each year since 2005, with the published reasons it changed."""
    d = json.loads((HERE / 'social' / 'annual_stats.json').read_text(encoding='utf8'))['demand']
    years = sorted(d['years'])
    first, last = years[0], years[-1]
    a, b = d['years'][first], d['years'][last]
    fall = round((1 - b / a) * 100)
    share = 'about a fifth' if 17 <= fall <= 23 else f'{fall}%'
    headline = f"The UK uses {share} less electricity than it did in {first}."
    why = ("Homes, appliances and lighting have become far more efficient, such as LED bulbs replacing old ones, and industry uses less: "
           f"industrial use in {last} was the lowest since 1983. Use dropped sharply in 2022 after high prices and a warm year, and has crept up since.")
    yearly = ', '.join(f'{y} {round(d["years"][y])} TWh' for y in years)
    words = f"{headline} Yearly totals: {yearly}. Why: {why} Source: {d['source']}."
    return [{'id': 'demand-years', 'type': 'demand-years', 'cat': 'history', 'art': 'bars', 'limit': 90, 'novelty': .55, 'source': d['source'], 'shows': words,
             'caption': f"{headline} In {first} the UK used {round(a)} TWh of electricity. In {last}: {round(b)} TWh. {why}\n\nYearly totals, {d['source']}.",
             'alt': f"Bar chart of electricity used in the UK each year from {first} to {last}, falling from {round(a)} TWh to {round(b)} TWh.",
             'spec': {'art': 'bars', 'eyebrow': f'{first} TO {last}, YEAR BY YEAR', 'headline': headline, 'bars': [[y if i % 10 == 0 or y == last else '', d['years'][y]] for i, y in enumerate(years)], 'fuel': 'wind',
                      'rows': [[f'{first}, whole year', f'{round(a)} TWh'], [f'{last}, whole year', f'{round(b)} TWh']], 'note': 'More efficient homes, appliances and lighting, and less heavy industry.', 'foot': ['Yearly totals. DESNZ, DUKES table 5.1.2.']}}]


BILL_WHY = {
    'electricity': "Gas prices soared as economies reopened after Covid and again after Russia invaded Ukraine in 2022. Gas sets the price of much of our electricity, so electricity bills rose too. Lower wholesale prices have brought them down since, but not back to where they were.",
    'gas': "Gas prices soared as economies reopened after Covid and again after Russia invaded Ukraine in 2022. Lower wholesale prices have brought bills down since, but not back to where they were.",
}


def bills_years(now):
    """A typical household's yearly electricity or gas bill since 2014, with the published reasons it changed."""
    data = json.loads((HERE / 'social' / 'annual_stats.json').read_text(encoding='utf8'))
    kind = random.Random(f'{now.date()}bills').choice(['electricity', 'gas'])
    d = data[f'{kind}_bill']
    years = sorted(d['years'])[-10:]  # ten bars leave room for each bar's £ figure
    v = d['years']
    peak = max(years, key=lambda y: v[y])
    first, last = years[0], years[-1]
    kwh = '3,400' if kind == 'electricity' else '11,200'
    headline = f"A typical {kind} bill: {money(v['2019'])} in 2019, {money(v[peak])} in {peak}, {money(v[last])} in {last}."
    why = BILL_WHY[kind]
    yearly = ', '.join(f'{y} {money(v[y])}' for y in years)
    words = f"{headline} Average yearly household {kind} bill for {kwh} kWh, not adjusted for inflation: {yearly}. Why: {why} Source: {d['source']}."
    return [{'id': 'bills-years', 'type': 'bills-years', 'cat': 'history', 'art': 'bars', 'limit': 90, 'novelty': .55, 'source': d['source'], 'shows': words,
             'caption': f"{headline} {why}\n\nAverage yearly household bill using {kwh} kWh, not adjusted for inflation. {d['source']}.",
             'alt': f"Bar chart of the average yearly household {kind} bill from {first} to {last}: {yearly}.",
             'spec': {'art': 'bars', 'eyebrow': f'{kind.upper()} BILLS, YEAR BY YEAR', 'headline': headline, 'bars': [[y, v[y]] for y in years], 'values': True, 'unit': '£', 'fuel': 'gas' if kind == 'gas' else 'solar',
                      'rows': [['2019', money(v['2019'])], [f'{last}', money(v[last])]], 'note': 'Gas prices soared after Covid and the invasion of Ukraine.', 'foot': [f'Typical bill, {kwh} kWh, not adjusted for inflation. DESNZ.']}}]


def mix_years(now):
    """What powered Britain in each full year, one bold page per year, with the published reasons for the change."""
    data = json.loads((HERE / 'social' / 'annual_mix.json').read_text(encoding='utf8'))
    years = sorted(data['years'])
    first, last = years[0], years[-1]
    share = lambda y, f: data['years'][y]['mix'].get(f, 0)
    pages = []
    for i, y in enumerate(years):
        mix = sorted(((k, round(v)) for k, v in data['years'][y]['mix'].items() if v >= 3), key=lambda x: -x[1])
        text = f"{y}: what powered Britain, averaged over the whole year." + (' Swipe for each year since.' if i == 0 else '')
        pages.append({'look': 'flag', 'text': text, 'mix': [list(x) for x in mix]})
    moved = sorted((f for f in WHY if f != 'coal'), key=lambda f: -abs(share(last, f) - share(first, f)))[:2]
    change = ' '.join(f"{NAME[f]} went from {round(share(first, f))}% to {round(share(last, f))}%." for f in moved)
    why = ' '.join(WHY[f][1] for f in moved)
    caption = f"What powered Britain each year since {first}, averaged over the whole year. {change} {why}\n\nYearly averages from the NESO Carbon Intensity API."
    return [{'id': 'mix-years', 'type': 'mix-years', 'cat': 'history', 'art': 'pages', 'limit': 90, 'novelty': .6, 'pages': pages, 'shows': caption, 'caption': caption,
             'alt': f"One page per year from {first} to {last}, each showing Britain's yearly average power mix. " + change, 'spec': {'art': 'pages'}}]


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
        grown = 'gone from almost nothing' if then < 100 else f'grown about {round(ratio)} times over' if ratio >= 4 else 'more than tripled' if ratio >= 3 else 'more than doubled' if ratio >= 2 else 'grown by over half' if ratio >= 1.5 else 'kept growing'
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
        words = f"{name}, a new {kind}{' in ' + place if place else ''}, started operating in {when:%B %Y}. It can make up to {round(mw)} MW of power."
        return [{'id': 'new-site', 'type': 'new-site', 'cat': 'new', 'art': 'map', 'limit': 60, 'novelty': .8, 'shows': words, 'caption': words, 'alt': words,
                 'spec': {'art': 'map', 'glow': None, 'fuelGlow': fuel, 'eyebrow': 'NEW ON THE GRID', 'big': f'Up to {round(mw)} MW', 'sub': f'New {kind} now running: {name}.', 'list': [], 'spot': to_xy(lat, lon), 'spotFuel': fuel, 'spotLabel': name, 'foot': [f'Started operating {when:%B %Y}. Government planning database.']}}]
    return []


def build(now, posted):
    """Each source is optional: if one fails the agent simply has fewer ideas that day."""
    out = []
    for name, fn in (('year trend', lambda: year_trend(now)), ('mix years', lambda: mix_years(now)), ('demand years', lambda: demand_years(now)), ('bills years', lambda: bills_years(now)), ('growth', lambda: growth(repd_rows(), now)), ('new sites', lambda: new_sites(repd_rows(), posted))):
        try:
            out += fn()
        except Exception as e:
            print('extra failed', name, e)
    return out
