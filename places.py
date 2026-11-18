"""A page for every postcode area ("Where does Leeds get its electricity from?"), written as plain HTML so search engines can read
the answer without running the app. Rebuilt with the site every 30 minutes. Called from build.py: places.build(snapshot, geo, lookup, site_dir)."""
import collections, csv, datetime as dt, heapq, html, json, math, pathlib, re, zoneinfo

HERE = pathlib.Path(__file__).resolve().parent
SITE = 'https://wheresmyenergyfrom.co.uk/'
LONDON = zoneinfo.ZoneInfo('Europe/London')
SLOT = 30 * 60

# postcode areas in Great Britain, by the name people know them by
AREAS = {
    'AB': 'Aberdeen', 'AL': 'St Albans', 'B': 'Birmingham', 'BA': 'Bath', 'BB': 'Blackburn', 'BD': 'Bradford', 'BH': 'Bournemouth', 'BL': 'Bolton',
    'BN': 'Brighton', 'BR': 'Bromley', 'BS': 'Bristol', 'CA': 'Carlisle', 'CB': 'Cambridge', 'CF': 'Cardiff', 'CH': 'Chester', 'CM': 'Chelmsford',
    'CO': 'Colchester', 'CR': 'Croydon', 'CT': 'Canterbury', 'CV': 'Coventry', 'CW': 'Crewe', 'DA': 'Dartford', 'DD': 'Dundee', 'DE': 'Derby',
    'DG': 'Dumfries and Galloway', 'DH': 'Durham', 'DL': 'Darlington', 'DN': 'Doncaster', 'DT': 'Dorchester', 'DY': 'Dudley', 'E': 'East London',
    'EC': 'the City of London', 'EH': 'Edinburgh', 'EN': 'Enfield', 'EX': 'Exeter', 'FK': 'Falkirk', 'FY': 'Blackpool', 'G': 'Glasgow',
    'GL': 'Gloucester', 'GU': 'Guildford', 'HA': 'Harrow', 'HD': 'Huddersfield', 'HG': 'Harrogate', 'HP': 'Hemel Hempstead', 'HR': 'Hereford',
    'HS': 'the Outer Hebrides', 'HU': 'Hull', 'HX': 'Halifax', 'IG': 'Ilford', 'IP': 'Ipswich', 'IV': 'Inverness', 'KA': 'Kilmarnock',
    'KT': 'Kingston upon Thames', 'KW': 'Caithness and Orkney', 'KY': 'Kirkcaldy', 'L': 'Liverpool', 'LA': 'Lancaster', 'LD': 'Llandrindod Wells',
    'LE': 'Leicester', 'LL': 'Llandudno', 'LN': 'Lincoln', 'LS': 'Leeds', 'LU': 'Luton', 'M': 'Manchester', 'ME': 'Medway', 'MK': 'Milton Keynes',
    'ML': 'Motherwell', 'N': 'North London', 'NE': 'Newcastle', 'NG': 'Nottingham', 'NN': 'Northampton', 'NP': 'Newport', 'NR': 'Norwich',
    'NW': 'North West London', 'OL': 'Oldham', 'OX': 'Oxford', 'PA': 'Paisley', 'PE': 'Peterborough', 'PH': 'Perth', 'PL': 'Plymouth',
    'PO': 'Portsmouth', 'PR': 'Preston', 'RG': 'Reading', 'RH': 'Redhill', 'RM': 'Romford', 'S': 'Sheffield', 'SA': 'Swansea',
    'SE': 'South East London', 'SG': 'Stevenage', 'SK': 'Stockport', 'SL': 'Slough', 'SM': 'Sutton', 'SN': 'Swindon', 'SO': 'Southampton',
    'SP': 'Salisbury', 'SR': 'Sunderland', 'SS': 'Southend-on-Sea', 'ST': 'Stoke-on-Trent', 'SW': 'South West London', 'SY': 'Shrewsbury',
    'TA': 'Taunton', 'TD': 'the Scottish Borders', 'TF': 'Telford', 'TN': 'Tonbridge', 'TQ': 'Torquay', 'TR': 'Truro', 'TS': 'Teesside',
    'TW': 'Twickenham', 'UB': 'Uxbridge and Southall', 'W': 'West London', 'WA': 'Warrington', 'WC': 'the West End of London', 'WD': 'Watford',
    'WF': 'Wakefield', 'WN': 'Wigan', 'WR': 'Worcester', 'WS': 'Walsall', 'WV': 'Wolverhampton', 'YO': 'York', 'ZE': 'Shetland'}
REGION = {1: 'North Scotland', 2: 'South Scotland', 3: 'North West England', 4: 'North East England', 5: 'Yorkshire', 6: 'North Wales & Merseyside',
          7: 'South Wales', 8: 'West Midlands', 9: 'East Midlands', 10: 'East of England', 11: 'South West England', 12: 'South England', 13: 'London',
          14: 'South East England'}
FUEL = {'gas': 'gas', 'wind': 'wind', 'nuclear': 'nuclear', 'imports': 'imports', 'biomass': 'biomass', 'solar': 'solar', 'hydro': 'hydro', 'coal': 'coal', 'other': 'other sources'}
COLOUR = {'gas': '#c8553d', 'wind': '#2f7fb5', 'nuclear': '#6a4fa3', 'imports': '#b0719a', 'biomass': '#6f8f3a', 'solar': '#d9a21b', 'hydro': '#2aa198', 'coal': '#2f2d2b', 'other': '#8d8577'}
RENEW = ('wind', 'solar', 'hydro', 'biomass')
TECH = {'Wind Onshore': 'onshore wind farm', 'Wind Offshore': 'offshore wind farm', 'Solar Photovoltaics': 'solar farm', 'Battery': 'battery',
        'Pumped Storage Hydroelectricity': 'pumped hydro station', 'Large Hydro': 'hydro station', 'Small Hydro': 'hydro scheme',
        'Biomass (dedicated)': 'biomass plant', 'Anaerobic Digestion': 'biogas plant', 'Tidal Stream': 'tidal power site', 'Shoreline Wave': 'wave power site'}
NEAR_KM = 25
esc = html.escape


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower().removeprefix('the ')).strip('-')


def bng_to_ll(E, N):
    """British National Grid to approximate lat/lon, close enough to measure a few kilometres."""
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
    return math.degrees(lat - VII * d * d + VIII * d ** 4), math.degrees(lon0 + X * d - XI * d ** 3)


def miles(lat1, lon1, lat2, lon2):
    p = math.radians
    h = math.sin(p(lat2 - lat1) / 2) ** 2 + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(p(lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


class Grid:
    """The same likely-sources model as the page: each fuel's share of the region is split between its stations by MW / km², along the real lines."""
    def __init__(self, geo):
        g = geo
        self.nodes = [(g['nodes'][i], g['nodes'][i + 1]) for i in range(0, len(g['nodes']), 2)]
        self.adj = [[] for _ in self.nodes]
        for a, b, L, _ in g['edges']:
            self.adj[a].append((b, L)); self.adj[b].append((a, L))
        self.stations = []
        for name, short, f, fuel, mw, x, y in g['stations']:
            node, gap = self.nearest((x, y))
            self.stations.append({'name': name, 'f': f, 'mw': mw, 'node': node, 'gap': gap})

    def nearest(self, p):
        best = min(range(len(self.nodes)), key=lambda i: math.hypot(p[0] - self.nodes[i][0], p[1] - self.nodes[i][1]))
        return best, math.hypot(p[0] - self.nodes[best][0], p[1] - self.nodes[best][1])

    def likely(self, p, mix):
        start, gap0 = self.nearest(p)
        dist = [math.inf] * len(self.nodes); dist[start] = 0
        heap = [(0, start)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            for v, L in self.adj[u]:
                if d + L < dist[v]:
                    dist[v] = d + L; heapq.heappush(heap, (d + L, v))
        rows = []
        for s in self.stations:
            if s['gap'] <= 200 and math.isfinite(dist[s['node']]):
                k = dist[s['node']] + s['gap'] + gap0
                rows.append({**s, 'km': k, 'score': s['mw'] / max(k, 15) ** 2})
        total = collections.Counter()
        for s in rows:
            total[s['f']] += s['score']
        for s in rows:
            s['share'] = mix.get(s['f'], 0) * s['score'] / total[s['f']]
        return sorted(rows, key=lambda s: -s['share'])


def projects(facts):
    """Large-scale renewable and battery projects: being built, approved, or switched on in the last two years."""
    seen, today = {}, dt.date.today()
    lf, per_home = facts['homes']['load_factors'], facts['homes']['kwh_per_home']
    for r in csv.DictReader(open(HERE / 'data' / 'repd.csv', encoding='latin-1')):
        status, tech = (r.get('Development Status (short)') or '').strip(), r.get('Technology Type') or ''
        if r.get('Country') == 'Northern Ireland' or tech not in TECH:
            continue
        try:
            mw = float((r.get('Installed Capacity (MWelec)') or '0').replace(',', ''))
            lat, lon = bng_to_ll(float(r['X-coordinate']), float(r['Y-coordinate']))
        except (ValueError, KeyError):
            continue
        if mw < 1:
            continue
        if status == 'Operational':
            try:
                when = dt.datetime.strptime((r.get('Operational') or '')[:10], '%d/%m/%Y').date()
            except ValueError:
                continue
            if (today - when).days > 730:
                continue
            stage = 'opened'
        elif status == 'Under Construction':
            stage, when = 'building', None
        elif status == 'Awaiting Construction':
            try:  # approvals from long ago often never get built, so only recent ones count
                granted = dt.datetime.strptime((r.get('Planning Permission  Granted') or '')[:10], '%d/%m/%Y').date()
            except ValueError:
                continue
            if (today - granted).days > 5 * 365:
                continue
            stage, when = 'approved', None
        else:
            continue
        homes = mw * 8760 * lf[tech] * 1000 / per_home if tech in lf else 0
        place = (r.get('Site Name') or '').strip()
        if not place:
            continue
        key = (place.lower(), tech, status)
        if key in seen and seen[key]['mw'] >= mw:  # phases of one site share a name: keep the biggest, never add them up
            continue
        seen[key] = row = {'name': place, 'tech': TECH[tech], 'mw': mw, 'lat': lat, 'lon': lon, 'stage': stage, 'when': when, 'homes': homes,
                    'county': (r.get('County') or '').strip()}
    return list(seen.values())


def homes_words(n):
    if n < 500:
        return ''
    n = round(n, -3) if n >= 10000 else round(n, -2)
    return f', enough for about {n:,.0f} homes'


def a_an(words):
    """'an 18 MW', 'an 8 MW', 'an 80 MW', 'an 11 MW', but 'a 50 MW'."""
    whole = words.split()[0].split('.')[0]
    groups = whole.split(',')  # spoken by its first group: 18 ('eighteen'), 11,000 ('eleven thousand'), 800 ('eight hundred')
    return 'an' if groups[0].startswith('8') or groups[0] in ('11', '18') else 'a'


def mw_words(mw):
    return f'{mw:,.0f} MW' if mw >= 10 else f'{mw:.1f} MW'.replace('.0 MW', ' MW')


def mix_bar(mix):
    parts = [(f, p) for f, p in sorted(mix.items(), key=lambda x: -x[1]) if p >= 1]
    bar = ''.join(f'<i style="flex:{p} 1 0;background:{COLOUR[f]}" title="{esc(FUEL[f])} {p:.0f}%"></i>' for f, p in parts)
    key = ''.join(f'<li><i style="background:{COLOUR[f]}"></i>{esc(FUEL[f].capitalize())} {p:.0f}%</li>' for f, p in parts)
    return f'<div class="bar" role="img" aria-label="{esc(mix_words(mix))}">{bar}</div><ul class="key">{key}</ul>'


def mix_words(mix):
    top = [(f, p) for f, p in sorted(mix.items(), key=lambda x: -x[1]) if p >= 5][:3]
    words = [f'{p:.0f}% {FUEL[f]}' for f, p in top]
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' and ' + words[-1]


def clock(t):
    return t.astimezone(LONDON).strftime('%H:%M')


def day_word(t, now):
    d = t.astimezone(LONDON).date()
    return 'today' if d == now.astimezone(LONDON).date() else 'tomorrow' if d == now.astimezone(LONDON).date() + dt.timedelta(days=1) else t.astimezone(LONDON).strftime('%A')


STYLE = """
  :root { --bg: #dfeae6; --panel: #f4f8f6; --ink: #10302a; --muted: #4c6a62; --line: #bfd2cb; --brand: #06704b; color-scheme: light dark; }
  @media (prefers-color-scheme: dark) { :root { --bg: #0f211d; --panel: #18302a; --ink: #e6f2ee; --muted: #9db8b0; --line: #2d4a42; --brand: #3fbf8f; } }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 17px/1.6 "Segoe UI", system-ui, -apple-system, sans-serif; }
  main { max-width: 42rem; margin: 0 auto; padding: 1.6rem 16px 4rem; }
  nav.crumbs { font-size: .92rem; color: var(--muted); } nav.crumbs a { color: inherit; }
  h1 { font-size: clamp(2rem, 7vw, 2.9rem); line-height: 1.08; margin: .6rem 0 .7rem; letter-spacing: -.01em; }
  h2 { font-size: 1.3rem; margin: 2.2rem 0 .4rem; line-height: 1.25; }
  .lead { font-size: 1.15rem; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 16px 18px; margin: 1rem 0; }
  .bar { display: flex; gap: 2px; height: 18px; border-radius: 9px; overflow: hidden; margin: .6rem 0 .5rem; }
  .bar i { display: block; }
  ul.key { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: .2rem 1rem; font-size: .95rem; }
  ul.key i { display: inline-block; width: .8em; height: .8em; border-radius: 3px; margin-right: .35em; vertical-align: -.05em; }
  ol.list, ul.list { padding-left: 1.3rem; margin: .4rem 0; } ol.list li, ul.list li { margin: .35rem 0; }
  .small { color: var(--muted); font-size: .92rem; }
  a { color: inherit; }
  .go { display: inline-block; background: var(--brand); color: #f2fbf7; text-decoration: none; font-weight: 700; border-radius: 999px; padding: 13px 22px; margin: .4rem 0; }
  @media (prefers-color-scheme: dark) { .go { color: #0f211d; } }
  form.pc { display: flex; gap: 8px; flex-wrap: wrap; margin: .6rem 0 0; }
  form.pc input { flex: 1 1 10rem; min-width: 0; font: inherit; padding: 11px 14px; border-radius: 999px; border: 1px solid var(--line); background: var(--bg); color: var(--ink); }
  form.pc button { font: inherit; font-weight: 700; border: 0; border-radius: 999px; padding: 11px 20px; background: var(--brand); color: #f2fbf7; cursor: pointer; }
  .districts { display: flex; flex-wrap: wrap; gap: 6px; padding: 0; list-style: none; }
  .districts a { display: inline-block; padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; text-decoration: none; font-size: .95rem; }
  .cols { columns: 2 12rem; padding-left: 1.2rem; } .cols li { break-inside: avoid; }
  footer { margin-top: 3rem; font-size: .92rem; color: var(--muted); }
"""


def page(title, description, path, body, crumbs, modified, icons):
    url = SITE + path
    schema = json.dumps({'@context': 'https://schema.org', '@graph': [
        {'@type': 'WebPage', 'name': title, 'url': url, 'description': description, 'dateModified': modified, 'inLanguage': 'en-GB',
         'isPartOf': {'@id': SITE + '#website'}},
        {'@type': 'BreadcrumbList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': n, 'item': SITE + p} for i, (n, p) in enumerate(crumbs)]}]},
        ensure_ascii=False).replace('</', '<\\/')
    trail = ' &rsaquo; '.join(f'<a href="/{p}">{esc(n)}</a>' for n, p in crumbs[:-1]) + f' &rsaquo; {esc(crumbs[-1][0])}'
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{url}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Where's My Energy From?">
<meta property="og:locale" content="en_GB">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}share.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#06704b">
{icons}
<script type="application/ld+json">{schema}</script>
<style>{STYLE}</style>
</head>
<body>
<main>
<nav class="crumbs" aria-label="Breadcrumb">{trail}</nav>
{body}
<footer><p><a href="/">Where's My Energy From?</a> &middot; <a href="/area/">All areas</a> &middot; <a href="/method.html">How the estimates work</a> &middot; <a href="/privacy.html">Privacy</a></p></footer>
</main>
<script defer src="/hit.js" data-page="area"></script>
</body>
</html>
"""


def postcode_form(example):
    return f"""<form class="pc" action="/" method="get"><label class="small" for="pc" style="flex-basis:100%">See your own postcode, with your map, your gas and the cleanest times:</label>
<input id="pc" name="pc" placeholder="e.g. {esc(example)}" autocomplete="postal-code" required><button type="submit">Show me</button></form>"""


def build(snapshot, geo, lookup, site, icons, facts):
    outcodes = json.loads((HERE / 'data' / 'outcodes.json').read_text(encoding='utf8'))
    taken = dt.datetime.fromisoformat(snapshot['taken'].replace('Z', '+00:00'))
    start = dt.datetime.fromisoformat(snapshot['start'].replace('Z', '+00:00'))
    now_i = max(0, int((taken - start).total_seconds() // SLOT))
    fuels = snapshot['fuels']
    as_mix = lambda row: {f: row[i] for i, f in enumerate(fuels) if row[i]}
    now_mix = {int(i): as_mix(rows[min(now_i, len(rows) - 1)]) for i, rows in snapshot['mix'].items()}
    year_mix = {int(i): as_mix(row) for i, row in snapshot['year']['regions'].items()}
    intensity = {int(i): v for i, v in snapshot['regions'].items()}
    ranked = sorted(range(1, 15), key=lambda i: intensity[i][min(now_i, len(intensity[i]) - 1)])
    grid, found = Grid(geo), projects(facts)
    modified = taken.isoformat().replace('+00:00', 'Z')
    local = taken.astimezone(LONDON)
    stamp = f"{clock(taken)} on {local:%A} {local.day} {local:%B}"

    def region_of(district):
        return lookup['exceptions'].get(district) or lookup['areas'].get(re.match(r'[A-Z]+', district)[0])

    areas = {}
    for code, name in AREAS.items():
        districts = sorted((d for d in geo['out'] if re.match(r'[A-Z]+', d)[0] == code), key=lambda d: (int(re.search(r'\d+', d)[0]), d))
        if not districts:
            continue
        regions = collections.Counter(region_of(d) for d in districts if region_of(d))
        if not regions:
            continue
        pts = [geo['out'][d] for d in districts]
        ll = [outcodes[d] for d in districts if d in outcodes]
        areas[code] = {'code': code, 'name': name, 'slug': slug(name), 'districts': districts, 'region': regions.most_common(1)[0][0], 'regions': regions,
                       'xy': (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)),
                       'll': (sum(p[0] for p in ll) / len(ll), sum(p[1] for p in ll) / len(ll)) if ll else None}
    assert len({a['slug'] for a in areas.values()}) == len(areas), 'two areas share a web address'

    out_dir = site / 'area'
    out_dir.mkdir(exist_ok=True)
    paths = []
    for a in areas.values():
        rid, name = a['region'], a['name']
        Name = name[0].upper() + name[1:]
        mix = now_mix[rid]
        renew = sum(mix.get(f, 0) for f in RENEW)
        low = renew + mix.get('nuclear', 0)
        place = ranked.index(rid) + 1
        rank = ('the cleanest of Britain\'s 14 regions right now' if place == 1 else 'the most carbon-heavy of Britain\'s 14 regions right now' if place == 14
                else f"the {place}{'th' if 10 <= place % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(place % 10, 'th')} cleanest of Britain's 14 regions right now")
        series = intensity[rid][now_i:now_i + 48]
        best = min(range(len(series) - 3), key=lambda i: sum(series[i:i + 4])) if len(series) >= 4 else None
        rows = [s for s in grid.likely(a['xy'], mix) if s['share'] >= 0.5][:6]
        first = a['districts'][0]
        lead = f"Right now {name}'s electricity is most likely {mix_words(mix)}."
        if renew < 30:
            lead += f" Renewables are {renew:.0f}% of the mix at the moment."
        else:
            lead += f" That's {renew:.0f}% renewable."
        body = [f'<h1>Where does {esc(name)} get its electricity from?</h1>',
                f'<p class="lead">{esc(lead)}</p>',
                f'<div class="card"><strong>{esc(REGION[rid])} electricity region, at {esc(stamp)}</strong>{mix_bar(mix)}'
                f'<p class="small" style="margin:.6rem 0 0">{esc(Name)} ({a["code"]} postcodes) is in the grid\'s {esc(REGION[rid])} region, {esc(rank)}. '
                f'{low:.0f}% of its power is low-carbon: renewables plus nuclear. Updated every 30 minutes.</p></div>']
        if rows:
            items = ''.join(f"<li><strong>{esc(s['name'])}</strong>, {esc(FUEL[s['f']])}: about {s['share']:.0f}% of the area's power, {s['km']:,.0f} km away along the grid</li>" for s in rows)
            body.append(f'<h2>The power stations most likely supplying {esc(name)}</h2>'
                        f'<p>Electricity mixes once it\'s on the grid, so nobody can trace it exactly. This is our best estimate: each fuel\'s share of the region is split between the stations running now, '
                        f'with bigger and closer ones along the real high-voltage lines counting for more.</p><ol class="list">{items}</ol>')
        if best is not None:
            t0 = start + dt.timedelta(seconds=SLOT * (now_i + best))
            body.append(f'<h2>The cleanest time to use power in {esc(name)}</h2>'
                        f'<p>Over the next day, the cleanest two hours in {esc(REGION[rid])} start at <strong>{clock(t0)} {day_word(t0, taken)}</strong>. '
                        f"That's the best time for the washing machine, the dishwasher or charging a car. Look up your postcode for your own day chart.</p>")
        body.append(f'<h2>{esc(Name)} over the last 12 months</h2><div class="card">{mix_bar(year_mix[rid])}'
                    f'<p class="small" style="margin:.6rem 0 0">The {esc(REGION[rid])} region\'s average mix, {esc(snapshot["year"]["from"][:7])} to {esc(snapshot["year"]["to"][:7])}.</p></div>')
        if a['ll']:
            near = sorted(((miles(*a['ll'], p['lat'], p['lon']), p) for p in found), key=lambda x: x[0])
            near = [(d, p) for d, p in near if d <= NEAR_KM]
            groups = [('building', 'Being built now'), ('approved', 'Approved, not built yet'), ('opened', 'Switched on in the last two years')]
            parts = []
            for stage, label in groups:
                sites = {}  # a site with solar and a battery is one place: one line, both parts
                for d, p in sorted((x for x in near if x[1]['stage'] == stage), key=lambda x: -x[1]['mw']):
                    sites.setdefault(p['name'].lower(), (d, p, []))[2].append(f"{a_an(mw_words(p['mw']))} {mw_words(p['mw'])} {esc(p['tech'])}{homes_words(p['homes'])}")
                mine = list(sites.values())[:6]
                if mine:
                    li = ''.join(f"<li><strong>{esc(p['name'])}</strong>, {' and '.join(what)}. {d:.0f} miles away"
                                 + (f", opened {p['when']:%B %Y}" if p['when'] else '') + '.</li>' for d, p, what in mine)
                    parts.append(f'<h3 style="margin:1.2rem 0 .2rem;font-size:1.05rem">{label}</h3><ul class="list">{li}</ul>')
            if parts:
                total = sum(p['mw'] for d, p in near if p['stage'] in ('building', 'approved'))
                intro = (f"There are {sum(1 for d, p in near if p['stage'] in ('building', 'approved'))} large renewable and battery projects being built or approved within {NEAR_KM} miles of {esc(name)}, "
                         f"{mw_words(total)} between them." if total else f"New renewable and battery sites within {NEAR_KM} miles of {esc(name)}.")
                body.append(f'<h2>What\'s being built near {esc(name)}</h2><p>{intro}</p>' + ''.join(parts)
                            + '<p class="small">Large-scale sites only. Homes figures use how often each kind of site actually runs over a year.</p>')
        others = [d for d in a['districts'] if region_of(d) != rid]
        if others:
            split = collections.Counter(region_of(d) for d in others)
            body.append('<p class="small">' + '; '.join(f"{', '.join(d for d in others if region_of(d) == r)} {'is' if n == 1 else 'are'} in the {esc(REGION[r])} region" for r, n in split.items()) + ', so their mix differs. Your postcode page shows the right one.</p>')
        body.append(f'<h2>Your own postcode</h2><div class="card">{postcode_form(first + " 1AA")}'
                    f'<p class="small" style="margin:.8rem 0 .3rem">Or pick your district:</p><ul class="districts">'
                    + ''.join(f'<li><a href="/?pc={d}">{d}</a></li>' for d in a['districts']) + '</ul></div>')
        neighbours = sorted((b for b in areas.values() if b['code'] != a['code']), key=lambda b: math.hypot(b['xy'][0] - a['xy'][0], b['xy'][1] - a['xy'][1]))[:6]
        body.append('<h2>Nearby areas</h2><ul class="list">' + ''.join(f'<li><a href="/area/{b["slug"]}/">Where {esc(b["name"])} gets its electricity</a></li>' for b in neighbours) + '</ul>')
        title = f"Where does {name} get its electricity from? Live | Where's My Energy From?"
        description = f"{lead} See the power stations most likely supplying {a['code']} postcodes, the cleanest time today and what's being built nearby."
        path = f"area/{a['slug']}/"
        (out_dir / a['slug']).mkdir(exist_ok=True)
        (out_dir / a['slug'] / 'index.html').write_text(page(title, description, path, '\n'.join(body), [('Home', ''), ('Areas', 'area/'), (Name, path)], modified, icons), encoding='utf8')
        paths.append(path)

    by_region = collections.defaultdict(list)
    for a in areas.values():
        by_region[a['region']].append(a)
    sections = ''.join(f'<h2>{esc(REGION[r])}</h2><p class="small">{esc(mix_words(now_mix[r]).capitalize())} right now.</p><ul class="cols">'
                       + ''.join(f'<li><a href="/area/{a["slug"]}/">{esc(a["name"][0].upper() + a["name"][1:])}</a> <span class="small">{a["code"]}</span></li>' for a in sorted(by_region[r], key=lambda a: a['name'].removeprefix('the ')))
                       + '</ul>' for r in sorted(by_region, key=lambda r: REGION[r]))
    index = (f'<h1>Where does your area get its electricity from?</h1>'
             f'<p class="lead">Pick your area to see what\'s powering it right now, the stations most likely supplying it, the cleanest time today and what\'s being built nearby. Updated every 30 minutes.</p>'
             f'<div class="card">{postcode_form("SW9 8AA")}</div>'
             f'<p class="small">Areas are grouped by the grid\'s 14 electricity regions, which follow the local power networks rather than county lines.</p>{sections}')
    (out_dir / 'index.html').write_text(page("Where does your area get its electricity from? Every part of Great Britain | Where's My Energy From?",
                                             "Live electricity for every postcode area in Great Britain: what's powering it now, the likely power stations, the cleanest time today and what's being built nearby.",
                                             'area/', index, [('Home', ''), ('Areas', 'area/')], modified, icons), encoding='utf8')
    return ['area/'] + paths
