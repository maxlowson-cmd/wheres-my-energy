"""Post ideas that look back in time: one fuel's yearly share since 2019, how each renewable has grown, and sites that recently opened.

Sources: Elexon generation records, and the government's Renewable Energy Planning Database (large-scale sites only).
"""
import collections, csv, datetime as dt, json, math, pathlib, random, re, urllib.request

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


def pct(v):
    """Round .5 upwards, the way the charts do, so the words and the bars never disagree (Python's round() sends 12.5 to 12)."""
    return int(math.floor(v + .5))


def year_trend(now):
    """One fuel's share of Britain's power, as a yearly average for every full year since 2019, with the published reason it changed.
    Whole years against whole years shows the trend; a single day against a single day mostly shows the weather."""
    data = json.loads((HERE / 'social' / 'annual_mix.json').read_text(encoding='utf8'))
    years = sorted(data['years'])
    first, last = years[0], years[-1]
    share = lambda y, f: data['years'][y]['mix'].get(f, 0)
    fuel = random.Random(f'{now.date()}trend').choice([f for f in WHY if abs(share(last, f) - share(first, f)) >= 1])
    a, b = share(first, fuel), share(last, fuel)
    fmt = lambda v: f'{v:.1f}%' if v < 2 else f'{pct(v)}%'
    bars = [[y, round(share(y, fuel), 1)] for y in years]
    why = WHY[fuel][1]
    headline = (f"{NAME[fuel]} made {fmt(a)} of Britain's power in {first}. In {last}: {fmt(b)}." if b >= .5 else f"{NAME[fuel]} made {fmt(a)} of Britain's power in {first}. By {last}, none.")
    yearly = ', '.join(f'{y} {fmt(share(y, fuel))}' for y in years)
    words = f"{headline} Yearly averages: {yearly}. Why: {why}"
    return [{'id': 'year-trend', 'type': 'year-trend', 'cat': 'history', 'subjects': [f'fuel-{fuel}', 'year-trend'], 'art': 'bars', 'limit': 90, 'novelty': .55, 'shows': words, 'caption': f'{headline} {why}', 'alt': f"Bar chart of {fuel} as a share of Britain's power each year: {yearly}.",
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
        mix = sorted(((k, pct(v)) for k, v in data['years'][y]['mix'].items() if v >= 3), key=lambda x: -x[1])
        text = f"{y}: what powered Britain, averaged over the whole year." + (' Swipe for each year since.' if i == 0 else '')
        pages.append({'look': 'flag', 'text': text, 'mix': [list(x) for x in mix]})
    moved = sorted((f for f in WHY if f != 'coal'), key=lambda f: -abs(share(last, f) - share(first, f)))[:2]
    change = ' '.join(f"{NAME[f]} went from {pct(share(first, f))}% to {pct(share(last, f))}%." for f in moved)
    why = ' '.join(WHY[f][1] for f in moved)
    caption = f"What powered Britain each year since {first}, averaged over the whole year. {change} {why}\n\nYearly averages from the NESO Carbon Intensity API."
    return [{'id': 'mix-years', 'type': 'mix-years', 'cat': 'history', 'art': 'pages', 'limit': 90, 'novelty': .6, 'pages': pages, 'shows': caption, 'caption': caption,
             'alt': f"One page per year from {first} to {last}, each showing Britain's yearly average power mix. " + change, 'spec': {'art': 'pages'}}]


FACTS = json.loads((HERE / 'social' / 'facts.json').read_text(encoding='utf8'))
HOMES_SOURCE = 'homes estimate from DESNZ 2025 load factors and Ofgem typical use of 2,500 kWh a year'


def homes(mw, tech):
    """How many typical homes' electricity a site of this size makes over a year, from how often that kind of site actually runs (DESNZ load factors)."""
    h = FACTS['homes']
    lf = h['load_factors'].get(tech)
    if not lf:
        return None
    n = mw * 8760 * lf * 1000 / h['kwh_per_home']
    return f'{n / 1e6:.1f}'.removesuffix('.0') + ' million' if n >= 1e6 else f'{round(n, -3):,.0f}' if n >= 10000 else f'{round(n, -2):,.0f}'


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
        n = homes(latest, tech)
        if n:
            words += f" Between them, these sites can make enough electricity for around {n} homes over a year."
        out.append({'id': 'growth-' + tech.lower().replace(' ', '-'), 'type': 'growth', 'cat': 'history', 'subjects': [f'tech:{fuel}', 'growth'], 'art': 'bars', 'limit': 85, 'novelty': .45 + (.2 if ratio >= 3 else 0), 'shows': words, 'caption': words, 'alt': words,
                    **({'source': f'government planning database (REPD); {HOMES_SOURCE}'} if n else {}),
                    'spec': {'art': 'bars', 'eyebrow': f'{back} YEARS OF CHANGE', 'headline': f"Britain's {name} {have} {grown} in {back} years." if then >= 100 else f"Britain's {name}: from almost nothing to {round(latest):,} MW in {back} years.", 'bars': bars, 'fuel': fuel, 'rows': [[f'{then_day:%B %Y}', f'{round(then):,} MW'], [f'{newest:%B %Y}', f'{round(latest):,} MW']], 'foot': ['Large-scale operating sites, government planning database.']}})
    return out


def new_sites(rows, posted):
    newest = max(w for w, _, _ in rows)
    picks = sorted((x for x in rows if x[0] >= newest - dt.timedelta(days=150) and x[1] >= 20 and x[2].get('Technology Type') in ('Solar Photovoltaics', 'Wind Onshore', 'Wind Offshore', 'Battery')), key=lambda x: x[1], reverse=True)
    for when, mw, r in picks:
        name = (r.get('Site Name') or '').split(' - ')[0].strip()
        core = re.sub(r'\s+(solar|wind|battery|energy|storage|bess|park|farm|pv|extension|project|scheme|limited|ltd)\b.*$', '', name, flags=re.I).strip() or name
        if not name or any(core.lower() in text.lower() for text in posted):
            continue
        try:
            lat, lon = bng_to_ll(float(r['X-coordinate'].replace(',', '')), float(r['Y-coordinate'].replace(',', '')))
        except ValueError:
            continue
        kind, fuel = {'Solar Photovoltaics': ('solar farm', 'solar'), 'Wind Onshore': ('wind farm', 'wind'), 'Wind Offshore': ('offshore wind farm', 'wind'), 'Battery': ('battery site', 'hydro')}[r['Technology Type']]
        place = (r.get('County') or r.get('Region') or '').strip()
        words = f"{name}, a new {kind}{' in ' + place if place else ''}, started operating in {when:%B %Y}. It can make up to {round(mw)} MW of power."
        n = homes(mw, r['Technology Type'])
        if n:
            words += f" Over a year, that's enough electricity for around {n} homes."
        return [{'id': 'new-site', 'type': 'new-site', 'cat': 'new', 'subjects': [f'site:{core.lower()}', f'tech:{fuel}'], 'art': 'map', 'limit': 60, 'novelty': .8, 'shows': words, 'caption': words, 'alt': words,
                 **({'source': f'government planning database (REPD); {HOMES_SOURCE}'} if n else {}),
                 'spec': {'art': 'map', 'glow': None, 'fuelGlow': fuel, 'eyebrow': 'NEW ON THE GRID', 'big': f'Up to {round(mw)} MW', 'sub': f'New {kind} now running: {name}.', 'list': [], 'spot': to_xy(lat, lon), 'spotFuel': fuel, 'spotLabel': name, 'foot': [f'Started operating {when:%B %Y}. Government planning database.']}}]
    return []


def plain(s):
    return s.replace('**', '')


def milestones(now):
    """On the anniversary of a turning point in Britain's power, a post saying how long ago it was and, where we can, what there is now."""
    out = []
    for m in FACTS['milestones']:
        when = dt.date.fromisoformat(m['date'])
        years = now.year - when.year
        if (now.month, now.day) != (when.month, when.day) or years < 1:
            continue
        ago = f"{years} year{'s' if years > 1 else ''}"
        pages = [{'photo_tag': m['photo_tag'], 'eyebrow': f'ON THIS DAY IN {when.year}', 'big': ago, 'text': m['then']}]
        now_words, source = m.get('now'), m['source']
        if m.get('now_tech'):
            total = sum(mw for w, mw, r in repd_rows() if r.get('Technology Type') == m['now_tech'])
            now_words = f"Today Britain's {TECH[m['now_tech']][0]} farms can make up to **{round(total):,} MW**, enough electricity for around **{homes(total, m['now_tech'])} homes** over a year."
            source += f'; government planning database (REPD); {HOMES_SOURCE}'
        if now_words:
            pages.append({'photo_tag': m['photo_tag'], 'eyebrow': 'AND NOW', 'text': now_words})
        event = m['then'].removeprefix('since ')
        caption = f"{ago} ago today, {event}" + (f"\n\n{plain(now_words)}" if now_words else '')
        out.append({'id': 'milestone', 'type': f"milestone-{m['key']}", 'cat': 'history', 'art': 'pages', 'limit': 90, 'novelty': 1, 'must': True, 'pages': pages, 'source': source,
                    'shows': caption, 'caption': caption, 'alt': caption, 'spec': {'art': 'pages'}})
    return out[:1]


def savings(now):
    """What wind and solar are saving Britain, quoted from published analysis. Each set of figures stops being used after its expiry date."""
    out = []
    for s in FACTS['savings']:
        if now.date() > dt.date.fromisoformat(s['expires']):
            continue
        pages = [{'photo_tag': s['photo_tag'], **pg} for pg in s['pages']]
        out.append({'id': 'savings', 'type': f"savings-{s['key']}", 'cat': 'history', 'art': 'pages', 'limit': 90, 'novelty': .7, 'pages': pages, 'source': s['source'],
                    'shows': s['caption'], 'caption': s['caption'], 'alt': ' '.join(plain(f"{pg['big']} {pg['text']}") for pg in s['pages']), 'spec': {'art': 'pages'}})
    return out[:1]


KIND = {'Solar Photovoltaics': ('solar farm', 'solar'), 'Wind Onshore': ('wind farm', 'wind'), 'Wind Offshore': ('offshore wind farm', 'wind'), 'Battery': ('battery site', 'hydro')}
REPD_SOURCE = 'government Renewable Energy Planning Database (REPD)'


def repd_all():
    """Every Great Britain row in the planning database, with its status, size and place."""
    out = []
    for r in csv.DictReader(open(HERE / 'data' / 'repd.csv', encoding='latin-1')):
        if r.get('Country') == 'Northern Ireland':
            continue
        try:
            mw = float((r.get('Installed Capacity (MWelec)') or '0').replace(',', '') or 0)
        except ValueError:
            continue
        out.append((r.get('Development Status (short)', '').strip(), mw, r))
    return out


def site_name(r):
    return re.sub(r'\s*\(.*?\)', '', (r.get('Site Name') or '').split(' - ')[0]).strip()


def spot(r):
    try:
        return to_xy(*bng_to_ll(float(r['X-coordinate'].replace(',', '')), float(r['Y-coordinate'].replace(',', ''))))
    except (ValueError, KeyError):
        return None


def building_now(now):
    """What is being built right now: wind, solar and batteries under construction, and the biggest single project."""
    rows = [(mw, r) for s, mw, r in repd_all() if s == 'Under Construction' and r.get('Technology Type') in KIND]
    gen = [(mw, r) for mw, r in rows if r['Technology Type'] != 'Battery']
    total = sum(mw for mw, _ in gen)
    if total < 500:
        return []
    homes_n = sum(mw * 8760 * FACTS['homes']['load_factors'][r['Technology Type']] * 1000 / FACTS['homes']['kwh_per_home'] for mw, r in gen)
    homes_txt = f'{homes_n / 1e6:.1f}'.removesuffix('.0') + ' million'
    big_mw, big = max(gen, key=lambda x: x[0])
    batt = sum(mw for mw, r in rows if r['Technology Type'] == 'Battery')
    pages = [{'photo_tag': 'building', 'eyebrow': 'BEING BUILT RIGHT NOW', 'big': f'{round(total):,} MW', 'text': f"of new wind and solar farms are being built across Britain, enough for around **{homes_txt} homes** once they're running."},
             {'photo_tag': 'offshore' if big['Technology Type'] == 'Wind Offshore' else KIND[big['Technology Type']][1], 'eyebrow': 'THE BIGGEST', 'big': site_name(big), 'text': f"a new {KIND[big['Technology Type']][0]}, will be able to make up to **{round(big_mw):,} MW** on its own."}]
    if batt >= 500:
        pages.append({'photo_tag': 'battery', 'eyebrow': 'AND TO STORE IT', 'big': f'{round(batt):,} MW', 'text': 'of grid batteries are being built too, to save power for when it is needed.'})
    caption = (f"Right now, {round(total):,} MW of new wind and solar farms are being built across Britain. Once they're running, that's enough electricity for around {homes_txt} homes over a year.\n\n"
               f"The biggest is {site_name(big)}, {'an' if KIND[big['Technology Type']][0][0] in 'aeiou' else 'a'} {KIND[big['Technology Type']][0]} that will be able to make up to {round(big_mw):,} MW on its own."
               + (f" Alongside them, {round(batt):,} MW of grid batteries are being built to store power for when it's needed." if batt >= 500 else ''))
    return [{'id': 'building', 'type': 'building', 'cat': 'new', 'art': 'pages', 'limit': 90, 'novelty': .75, 'pages': pages, 'subjects': ['building'],
             'source': f'{REPD_SOURCE}, sites under construction; {HOMES_SOURCE}', 'shows': caption, 'caption': caption, 'alt': caption, 'spec': {'art': 'pages'}}]


def biggest(now):
    """Britain's biggest running site of one kind, a different kind on different days."""
    tech = random.Random(f'{now.date()}big').choice(['Wind Offshore', 'Wind Onshore', 'Solar Photovoltaics', 'Battery'])
    rows = [(mw, r) for s, mw, r in repd_all() if s == 'Operational' and r.get('Technology Type') == tech]
    if not rows:
        return []
    mw, r = max(rows, key=lambda x: x[0])
    kind, fuel = KIND[tech]
    name, xy, n = site_name(r), spot(r), homes(mw, tech)
    place = (r.get('County') or '').strip()
    where = '' if not place or place.lower() == 'offshore' else f' in {place}'
    words = f"Britain's biggest {kind} running today is {name}{where}. It can {'deliver' if tech == 'Battery' else 'make'} up to {round(mw):,} MW." + (f" Over a year, that's enough electricity for around {n} homes." if n else ' It stores power when there is plenty and gives it back when it is needed.')
    if not xy:
        return []
    return [{'id': 'biggest', 'type': 'biggest', 'cat': 'new', 'art': 'map', 'limit': 60, 'novelty': .6, 'subjects': [f'site:{name.lower()}', 'biggest'], 'shows': words, 'caption': words, 'alt': words,
             'source': f'{REPD_SOURCE}' + (f'; {HOMES_SOURCE}' if n else ''),
             'spec': {'art': 'map', 'glow': None, 'fuelGlow': fuel, 'eyebrow': f"BRITAIN'S BIGGEST {kind.upper()}", 'big': f'Up to {round(mw):,} MW', 'sub': f'{name}{where}.', 'list': [], 'spot': xy, 'spotFuel': fuel, 'spotLabel': name, 'foot': ['Biggest operating site of its kind. Government planning database.']}}]


def county(now):
    """A spotlight on one county's large wind, solar and battery sites, a different county each time."""
    by = collections.defaultdict(list)
    for s, mw, r in repd_all():
        if s == 'Operational' and r.get('Technology Type') in ('Wind Onshore', 'Solar Photovoltaics', 'Battery') and (r.get('County') or '').strip() not in ('', 'Offshore'):
            by[r['County'].strip()].append((mw, r))
    names = sorted(k for k, v in by.items() if sum(mw for mw, _ in v) >= 300)
    if not names:
        return []
    name = names[(now.date() - dt.date(2026, 1, 1)).days // 3 % len(names)]
    sites = by[name]
    total = sum(mw for mw, _ in sites)
    mix = collections.Counter()
    for mw, r in sites:
        mix[r['Technology Type']] += mw
    top = mix.most_common(1)[0][0]
    word = {'Wind Onshore': 'wind', 'Solar Photovoltaics': 'solar', 'Battery': 'batteries'}[top]
    homes_n = sum(homes_raw(mw, r['Technology Type']) for mw, r in sites)
    homes_txt = f'{homes_n / 1e6:.1f}'.removesuffix('.0') + ' million' if homes_n >= 1e6 else f'{round(homes_n, -3):,.0f}'
    pts = [spot(r) for _, r in sites]
    pts = [x for x in pts if x]
    centre = [round(sum(x for x, _ in pts) / len(pts), 1), round(sum(y for _, y in pts) / len(pts), 1)] if pts else None
    words = f"{name} has {len(sites)} large wind, solar and battery sites running. Between them they can make up to {round(total):,} MW, mostly from {word}. Over a year, the wind and solar farms make enough electricity for around {homes_txt} homes."
    if not centre:
        return []
    return [{'id': 'county', 'type': 'county', 'cat': 'new', 'art': 'map', 'limit': 60, 'novelty': .6, 'subjects': [f'county:{name.lower()}', 'county'], 'shows': words, 'caption': words, 'alt': words,
             'source': f'{REPD_SOURCE}; {HOMES_SOURCE}',
             'spec': {'art': 'map', 'glow': None, 'fuelGlow': 'solar' if word == 'solar' else 'wind' if word == 'wind' else 'hydro', 'eyebrow': f'SPOTLIGHT: {name.upper()}', 'big': f'{round(total):,} MW', 'sub': f'from {len(sites)} large wind, solar and battery sites in {name}.', 'list': [], 'spot': centre, 'spotFuel': 'solar' if word == 'solar' else 'wind', 'spotLabel': name, 'foot': ['Operating sites over 1 MW. Government planning database.']}}]


def homes_raw(mw, tech):
    lf = FACTS['homes']['load_factors'].get(tech)
    return mw * 8760 * lf * 1000 / FACTS['homes']['kwh_per_home'] if lf else 0


UA = {'User-Agent': 'wheresmyenergyfrom/1.0 (https://wheresmyenergyfrom.co.uk)'}
LONDON = __import__('zoneinfo').ZoneInfo('Europe/London')
FUEL_COL = {'gas': '#e0735c', 'wind': '#58a6da', 'solar': '#e8bb49', 'imports': '#cf93b9', 'nuclear': '#9a82d6', 'biomass': '#9dbb5f', 'hydro': '#4cc4ba'}
CABLES = {'Eleclink': 'France', 'France(IFA)': 'France', 'IFA2': 'France', 'Netherlands': 'the Netherlands', 'Belgium': 'Belgium', 'North Sea Link': 'Norway',
          'Denmark': 'Denmark', 'Ireland(East-West)': 'Ireland', 'Ireland (Greenlink)': 'Ireland', 'Northern Ireland': 'Northern Ireland'}


def fetch(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))


def local(iso):
    return dt.datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(LONDON)


def cables(now):
    """Which countries Britain is trading power with right now, through its undersea cables (Elexon interconnector flows)."""
    rows = fetch('https://data.elexon.co.uk/bmrs/api/v1/generation/outturn/interconnectors?format=json')['data']
    last = max(r['startTime'] for r in rows)
    when = local(last)
    if (now.astimezone(LONDON) - when).total_seconds() > 3 * 3600:
        return []
    flow = collections.Counter()
    for r in rows:
        if r['startTime'] == last:
            country = next((v for k, v in CABLES.items() if r['interconnectorName'].startswith(k)), None)
            if country:
                flow[country] += r['generation']
    imp = sum(v for v in flow.values() if v > 0)
    exp = -sum(v for v in flow.values() if v < 0)
    if imp + exp < 500:
        return []
    order = sorted(flow.items(), key=lambda x: -abs(x[1]))
    biggest = max(abs(v) for _, v in order)
    ins = [k for k, v in order if v > 50]
    outs = [k for k, v in order if v < -50]
    names = lambda xs: ', '.join(xs[:-1]) + ' and ' + xs[-1] if len(xs) > 1 else xs[0]
    head = f"Right now Britain is bringing in {round(imp):,} MW of power through undersea cables, most of it from {ins[0]}." if ins else f"Right now Britain is sending {round(exp):,} MW of power abroad through undersea cables."
    more = (f" At the same time it's sending {round(exp):,} MW to {names(outs)}." if ins and outs else '')
    caption = head + more + f"\n\nBritain's grid is linked by cable to {names(sorted(set(CABLES.values()) - {'Northern Ireland'}))}, and to Northern Ireland. Power flows whichever way it's needed: in when we're short or it's cheaper abroad, out when we have plenty to spare."
    rows_out = [[k, f"{abs(round(v)):,} MW {'in' if v > 0 else 'out'}", abs(v) / biggest, FUEL_COL['imports'] if v > 0 else '#14c4a8'] for k, v in order if abs(v) > 50][:7]
    page = {'look': 'rows', 'colour': 'paper', 'eyebrow': f'UNDERSEA CABLES AT {when:%H:%M}', 'text': head, 'rows': rows_out, 'note': 'Pink: power coming in. Green: power going out.'}
    return [{'id': 'cables', 'type': 'cables', 'cat': 'now', 'art': 'pages', 'limit': 90, 'novelty': .5 + min(.3, exp / 3000), 'pages': [page], 'subjects': ['cables', 'fuel-imports'],
             'source': 'Elexon, interconnector flows', 'shows': caption, 'caption': caption, 'alt': head + more, 'spec': {'art': 'pages'}}]


PLACES = [('Lerwick', 60.15, -1.15), ('Stornoway', 58.21, -6.39), ('Inverness', 57.48, -4.22), ('Aberdeen', 57.15, -2.09), ('Glasgow', 55.86, -4.25), ('Edinburgh', 55.95, -3.19),
          ('Newcastle', 54.98, -1.61), ('Leeds', 53.80, -1.55), ('Manchester', 53.48, -2.24), ('Norwich', 52.63, 1.30), ('Birmingham', 52.49, -1.89), ('Aberystwyth', 52.42, -4.08),
          ('Cardiff', 51.48, -3.18), ('London', 51.51, -0.13), ('Brighton', 50.82, -0.14), ('Plymouth', 50.38, -4.14), ('Penzance', 50.12, -5.54)]


def weather_tomorrow(now):
    """Tomorrow's windiest or sunniest places, from the Open-Meteo forecast."""
    lat = ','.join(str(p[1]) for p in PLACES); lon = ','.join(str(p[2]) for p in PLACES)
    d = fetch(f'https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=wind_speed_10m_max,sunshine_duration&wind_speed_unit=mph&timezone=Europe%2FLondon&forecast_days=2')
    tomorrow = (now.astimezone(LONDON) + dt.timedelta(days=1)).date().isoformat()
    vals = []
    for (name, _, _), x in zip(PLACES, d):
        i = x['daily']['time'].index(tomorrow)
        vals.append((name, x['daily']['wind_speed_10m_max'][i] or 0, (x['daily']['sunshine_duration'][i] or 0) / 3600))
    day = (now.astimezone(LONDON) + dt.timedelta(days=1)).strftime('%A')
    windy = sorted(vals, key=lambda v: -v[1])
    sunny = sorted(vals, key=lambda v: -v[2])
    out = []
    if windy[0][1] >= 25:
        top = windy[:6]
        head = f"{day}'s windiest place: {top[0][0]}, with winds forecast up to {round(top[0][1])} mph."
        caption = head + f"\n\nWindy weather usually means more power from Britain's wind farms. Here are the windiest places on {day}'s forecast: " + ', '.join(f'{n} {round(w)} mph' for n, w, _ in top) + '.'
        page = {'look': 'rows', 'colour': 'blue', 'eyebrow': f"{day.upper()}'S FORECAST", 'text': head, 'rows': [[n, f'{round(w)} mph', w / top[0][1], FUEL_COL['wind']] for n, w, _ in top], 'note': "Windy weather usually means more power from Britain's wind farms."}
        out.append({'id': 'weather-wind', 'type': 'weather-wind', 'cat': 'now', 'art': 'pages', 'limit': 90, 'novelty': min(.85, windy[0][1] / 60), 'pages': [page], 'subjects': ['weather'],
                    'source': 'Open-Meteo weather forecast (open-meteo.com)', 'shows': caption, 'caption': caption, 'alt': head, 'spec': {'art': 'pages'}})
    if sunny[0][2] >= 3:
        top = sunny[:6]
        hours = lambda h: f'{h:.1f}'.removesuffix('.0') + ' hours'
        head = f"{day}'s sunniest place: {top[0][0]}, with about {hours(top[0][2])} of sunshine forecast."
        caption = head + f"\n\nSunshine means more power from solar panels. Here are the sunniest places on {day}'s forecast: " + ', '.join(f'{n} {hours(h)}' for n, _, h in top) + '.'
        page = {'look': 'rows', 'colour': 'sun', 'eyebrow': f"{day.upper()}'S FORECAST", 'text': head, 'rows': [[n, hours(h), h / top[0][2], '#e8a200'] for n, _, h in top], 'note': 'Sunshine means more power from solar panels.'}
        out.append({'id': 'weather-sun', 'type': 'weather-sun', 'cat': 'now', 'art': 'pages', 'limit': 90, 'novelty': min(.8, sunny[0][2] / 10), 'pages': [page], 'subjects': ['weather'],
                    'source': 'Open-Meteo weather forecast (open-meteo.com)', 'shows': caption, 'caption': caption, 'alt': head, 'spec': {'art': 'pages'}})
    return out


def week_review(now):
    """The last seven days on Britain's grid: wind's best moment, solar's best, and the cleanest half hour (NESO generation mix)."""
    if now.astimezone(LONDON).weekday() not in (6, 0):  # Sundays and Mondays
        return []
    end = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    d = fetch(f"https://api.carbonintensity.org.uk/generation/{(end - dt.timedelta(days=7)):%Y-%m-%dT%H:%MZ}/{end:%Y-%m-%dT%H:%MZ}")['data']
    if len(d) < 300:
        return []
    mix = [(local(x['from']), {m['fuel']: m['perc'] for m in x['generationmix']}) for x in d]
    wind_avg = sum(m.get('wind', 0) for _, m in mix) / len(mix)
    w_t, w = max(mix, key=lambda x: x[1].get('wind', 0))
    s_t, s = max(mix, key=lambda x: x[1].get('solar', 0))
    g_t, g = min(mix, key=lambda x: x[1].get('gas', 0) + x[1].get('coal', 0))
    when = lambda t: f'{t:%a} {t.day} {t:%b}, {t:%H:%M}'
    head = f"Britain's week on the grid: wind made {pct(wind_avg)}% of its power on average."
    rows = [[f"Wind's best moment", f"{pct(w['wind'])}%", w['wind'] / 100, FUEL_COL['wind'], when(w_t)],
            [f"Solar's best moment", f"{pct(s['solar'])}%", s['solar'] / 100, FUEL_COL['solar'], when(s_t)],
            [f"Least gas", f"{pct(g.get('gas', 0))}%", g.get('gas', 0) / 100, FUEL_COL['gas'], when(g_t)],
            [f"Wind, all week", f"{pct(wind_avg)}%", wind_avg / 100, FUEL_COL['wind'], 'average over 7 days']]
    caption = (f"{head}\n\nWind's best moment was {when(w_t)}, when it made {pct(w['wind'])}% of Britain's electricity. Solar peaked at {pct(s['solar'])}% on {when(s_t)}. "
               f"The least gas came on {when(g_t)}, at {pct(g.get('gas', 0))}%.")
    page = {'look': 'rows', 'colour': 'mint', 'eyebrow': 'THE LAST 7 DAYS', 'text': head, 'rows': rows}
    return [{'id': 'week', 'type': 'week', 'cat': 'now', 'art': 'pages', 'limit': 90, 'novelty': .7, 'pages': [page], 'subjects': ['week'],
             'source': 'NESO Carbon Intensity API, Great Britain generation mix, last 7 days', 'shows': caption, 'caption': caption, 'alt': caption, 'spec': {'art': 'pages'}}]


def build(now, posted):
    """Each source is optional: if one fails the agent simply has fewer ideas that day."""
    out = []
    for name, fn in (('year trend', lambda: year_trend(now)), ('mix years', lambda: mix_years(now)), ('demand years', lambda: demand_years(now)), ('bills years', lambda: bills_years(now)), ('growth', lambda: growth(repd_rows(), now)), ('new sites', lambda: new_sites(repd_rows(), posted)), ('milestones', lambda: milestones(now)), ('savings', lambda: savings(now)), ('building', lambda: building_now(now)), ('biggest', lambda: biggest(now)), ('county', lambda: county(now)), ('cables', lambda: cables(now)), ('weather', lambda: weather_tomorrow(now)), ('week', lambda: week_review(now))):
        try:
            out += fn()
        except Exception as e:
            print('extra failed', name, e)
    return out
