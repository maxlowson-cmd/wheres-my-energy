"""Latest gas flowing into Britain at each terminal, with the likely origin of each entry point. Writes gas.json.

Origins are estimates. Langeled is Norwegian, the LNG terminals are tanker gas, and the interconnectors are Europe.
St Fergus NSMP takes both Norwegian (Vesterled) and UK gas, so it is split by assumption. With that split the
result sits close to the 2025 national shares (Norway 47%, domestic 30%). Storage withdrawals are left out.
"""
import json, math, pathlib, re, urllib.request, datetime as dt

HERE = pathlib.Path(__file__).resolve().parent
LAT0 = float(re.search(r'^LAT0\s*=\s*([\d.]+)', (HERE / 'model.py').read_text(encoding='utf8'), re.M).group(1))


def xy(lat, lon):
    return [round((lon + 2.0) * 111.32 * math.cos(math.radians(LAT0)), 1), round((lat - 54.0) * 110.57, 1)]


TERMINALS = {'St Fergus': (57.578, -1.835), 'Easington': (53.646, 0.117), 'Bacton': (52.862, 1.468), 'Teesside': (54.625, -1.190), 'Milford Haven': (51.700, -5.100), 'Isle of Grain': (51.445, 0.708)}
ENTRIES = {
    'EASINGTON LANGELED': ('Easington', {'norway': 1}), 'EASINGTON DIMLINGTON': ('Easington', {'uk': 1}),
    'ST FERGUS NSMP': ('St Fergus', {'norway': .75, 'uk': .25}), 'ST FERGUS MOBIL': ('St Fergus', {'uk': 1}), 'ST FERGUS SHELL': ('St Fergus', {'uk': 1}),
    'BACTON PERENCO': ('Bacton', {'uk': 1}), 'BACTON SEAL': ('Bacton', {'uk': 1}), 'BACTON SHELL': ('Bacton', {'uk': 1}),
    'BACTON BBL': ('Bacton', {'europe': 1}), 'BACTON IC': ('Bacton', {'europe': 1}),
    'TEESSIDE CATS': ('Teesside', {'uk': 1}), 'TEESSIDE NSMP': ('Teesside', {'uk': 1}),
    'MILFORD HAVEN - DRAGON': ('Milford Haven', {'lng': 1}), 'MILFORD HAVEN - SOUTH HOOK': ('Milford Haven', {'lng': 1}),
    'GRAIN NTS 1': ('Isle of Grain', {'lng': 1}), 'GRAIN NTS 2': ('Isle of Grain', {'lng': 1}),
}
# 2025 tanker gas by country, TWh (Energy Trends figures, as published by Sunsave)
LNG_2025 = {'US': 104.4, 'Algeria': 8.3, 'Qatar': 8.2, 'Trinidad and Tobago': 4.2, 'Angola': 2.9, 'Nigeria': 2.6, 'Peru': 2.1, 'Equatorial Guinea': 1.1, 'Brazil': .9, 'Mexico': .9}

# a point on the way in, for the map
ORIGINS = {
    ('Easington', 'norway'): (58.4, 1.9, 'Norway'), ('St Fergus', 'norway'): (59.6, 2.2, 'Norway'),
    ('St Fergus', 'uk'): (58.2, 0.2, 'North Sea'), ('Easington', 'uk'): (53.9, 1.6, 'North Sea'), ('Bacton', 'uk'): (53.4, 2.2, 'North Sea'), ('Teesside', 'uk'): (56.9, 1.9, 'North Sea'),
    ('Milford Haven', 'lng'): (50.2, -7.8, 'Tanker'), ('Isle of Grain', 'lng'): (50.9, 1.4, 'Tanker'), ('Bacton', 'europe'): (52.3, 3.0, 'Europe'),
}

out = HERE / 'gas.json'
try:
    req = urllib.request.Request('https://data.nationalgas.com/api/latest-gas-flows', headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/2.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)['data']['Supply from entry points']['data']
    flows = {}
    known = set()
    for row in rows:
        name = row['SYSTEM ENTRY NAME']
        known.add(name)
        readings = [v for k, v in row.items() if ':' in k and isinstance(v, (int, float))]
        flows[name] = readings[-1] if readings else 0
    missing = set(ENTRIES) - known
    if missing:
        raise ValueError(f'entry points missing from feed: {sorted(missing)}')
    terminals = {n: {'name': n, 'xy': xy(*ll), 'flow': 0.0, 'mix': {}} for n, ll in TERMINALS.items()}
    for (where, src), (lat, lon, label) in ORIGINS.items():
        terminals[where].setdefault('from', {})[src] = {'xy': xy(lat, lon), 'label': label}
    for name, (where, mix) in ENTRIES.items():
        f = max(0.0, flows[name])
        terminals[where]['flow'] += f
        for src, part in mix.items():
            terminals[where]['mix'][src] = terminals[where]['mix'].get(src, 0.0) + f * part
    for t in terminals.values():
        t['mix'] = {k: round(v, 2) for k, v in t['mix'].items() if v > 0}
        t['flow'] = round(t['flow'], 2)
    total = sum(LNG_2025.values())
    out.write_text(json.dumps({'taken': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:00Z'), 'terminals': [t for t in terminals.values() if t['flow'] > 0],
                               'lngTop': ['US', round(LNG_2025['US'] / total * 100)]}, separators=(',', ':')), encoding='utf8')
except Exception as e:
    if not out.exists():
        # a fresh build has no earlier reading: leave the gas card out rather than stop the whole site updating
        out.write_text(json.dumps({'taken': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:00Z'), 'terminals': [], 'lngTop': ['US', 0]}, separators=(',', ':')), encoding='utf8')
    print('gas feed unavailable, keeping the last good reading if there is one:', e)
print(out.read_text(encoding='utf8')[:400])
