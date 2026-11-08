"""Likely-sources model for one postcode: running stations + real high-voltage network + a simple size/distance rule."""
import json, csv, math, heapq, re, pathlib, collections, html
HERE = pathlib.Path(__file__).resolve().parent
D = HERE / 'data'
TARGET = ('SW9', 51.46935, -0.11389)
ALPHA = 2           # share is proportional to MW / distance^ALPHA  (a rule of thumb, not physics)
MIN_KM = 15
LAT0 = 54.0
def xy(lat, lon): return ((lon + 2.0) * 111.32 * math.cos(math.radians(LAT0)), (lat - 54.0) * 110.57)
def km(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])

# --- network
ways = [w for w in json.load(open(D / 'lines.json', encoding='utf8'))['elements'] if w.get('geometry')]
geoms = [[xy(p['lat'], p['lon']) for p in w['geometry']] for w in ways]
ends = []
for g in geoms: ends += [g[0], g[-1]]
parent = list(range(len(ends)))
def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]; i = parent[i]
    return i
TOL = 2.0
cells = collections.defaultdict(list)
for i, p in enumerate(ends): cells[(int(p[0] // TOL), int(p[1] // TOL))].append(i)
for i, p in enumerate(ends):
    cx, cy = int(p[0] // TOL), int(p[1] // TOL)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for j in cells.get((cx + dx, cy + dy), []):
                if j > i and km(p, ends[j]) <= TOL: parent[find(i)] = find(j)
adj = collections.defaultdict(list)
node_xy = {}
for k, g in enumerate(geoms):
    a, b = find(2 * k), find(2 * k + 1)
    node_xy.setdefault(a, g[0]); node_xy.setdefault(b, g[-1])
    L = sum(km(g[i], g[i + 1]) for i in range(len(g) - 1))
    adj[a].append((b, L, k, False)); adj[b].append((a, L, k, True))
# components
seen, comps = set(), []
for n in adj:
    if n in seen: continue
    st, c = [n], set()
    while st:
        x = st.pop()
        if x in c: continue
        c.add(x); st += [y for y, *_ in adj[x]]
    seen |= c; comps.append(c)
comps.sort(key=len, reverse=True)
main = comps[0]
nodes = [n for n in main]
def nearest(p):
    n = min(nodes, key=lambda q: km(p, node_xy[q]))
    return n, km(p, node_xy[n])

# --- stations
ids = list(csv.DictReader(open(D / 'ids.csv', encoding='utf8')))
loc = {r['dictionary_id']: r for r in csv.DictReader(open(D / 'locs.csv', encoding='utf8')) if r.get('latitude')}
code2id, stem2id = {}, {}
for r in ids:
    for c in (r['sett_bmu_id'] or '').split(','):
        c = c.strip()
        if c:
            code2id[c] = r['dictionary_id']
            stem2id.setdefault(re.sub(r'[-\d]+[A-Z]?$', '', c), r['dictionary_id'])
name_of = {r['dictionary_id']: r['name'] for r in ids}
MANUAL = {'T_TSREP-1': ('Teesside Renewable Energy Plant', 54.595, -1.165)}
units = json.load(open(HERE / 'units_all.json', encoding='utf8'))
stations = {}
matched = 0
for u in units:
    k = code2id.get(u['unit']) or stem2id.get(re.sub(r'[-\d]+[A-Z]?$', '', u['unit']))
    if k in loc:
        key, name, lat, lon = k, name_of[k], float(loc[k]['latitude']), float(loc[k]['longitude'])
    elif u['unit'] in MANUAL:
        name, lat, lon = MANUAL[u['unit']]; key = u['unit']
    else:
        continue
    matched += u['mw']
    s = stations.setdefault(key, {'name': name, 'lat': lat, 'lon': lon, 'mw': 0, 'fuels': collections.Counter()})
    s['mw'] += u['mw']; s['fuels'][u['fuel']] += u['mw']
# --- interconnector landing points
LAND = {'France (IFA)': (51.106, 0.975), 'France (IFA2)': (50.84, -1.27), 'France (ElecLink)': (51.09, 1.15), 'Netherlands': (51.44, 0.71),
        'Belgium': (51.30, 1.35), 'Norway': (55.14, -1.52), 'Denmark': (52.96, -0.20), 'Ireland': (55.07, -4.98),
        'Ireland (East-West)': (53.23, -3.07), 'Ireland (Greenlink)': (51.68, -4.99)}
grid = json.load(open(HERE / 'grid_snapshot.json', encoding='utf8'))
for m in grid['mix_now']:
    if m['group'] == 'Imports' and m['mw'] > 0 and m['fuel'] in LAND:
        lat, lon = LAND[m['fuel']]
        stations['I:' + m['fuel']] = {'name': m['fuel'].split(' (')[0] + ' by cable', 'cable': m['fuel'], 'lat': lat, 'lon': lon, 'mw': m['mw'], 'fuels': collections.Counter({'Imports': m['mw']})}

# --- route
start_xy = xy(TARGET[1], TARGET[2])
start, start_gap = nearest(start_xy)
dist, prev = {start: 0.0}, {}
pq = [(0.0, start)]
while pq:
    d, n = heapq.heappop(pq)
    if d > dist[n]: continue
    for m, L, k, rev in adj[n]:
        nd = d + L
        if nd < dist.get(m, 1e12):
            dist[m] = nd; prev[m] = (n, k, rev); heapq.heappush(pq, (nd, m))
rows = []
for s in stations.values():
    p = xy(s['lat'], s['lon'])
    n, gap = nearest(p)
    if n not in dist or gap > 150: continue
    total = dist[n] + gap + start_gap
    s.update(node=n, gap=gap, km=total, xy=p, score=s['mw'] / max(total, MIN_KM) ** ALPHA, fuel=s['fuels'].most_common(1)[0][0])
    rows.append(s)
T = sum(s['score'] for s in rows)
for s in rows: s['share'] = s['score'] / T
rows.sort(key=lambda s: -s['share'])

def route(s):
    """list of xy polylines from station to target along the network"""
    pts, n = [s['xy']], s['node']
    while n != start:
        m, k, rev = prev[n]
        g = geoms[k]
        pts += g[::-1] if not rev else g
        n = m
    pts.append(start_xy)
    return pts
# --- drawing
def simplify(pts, tol):
    if len(pts) < 3: return pts
    keep = {0, len(pts) - 1}; stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]; bx, by = pts[b]
        L = math.hypot(bx - ax, by - ay) or 1e-9
        best, at = 0, None
        for i in range(a + 1, b):
            d = abs((bx - ax) * (ay - pts[i][1]) - (ax - pts[i][0]) * (by - ay)) / L
            if d > best: best, at = d, i
        if at is not None and best > tol:
            keep.add(at); stack += [(a, at), (at, b)]
    return [pts[i] for i in sorted(keep)]

def simplify_ring(r, tol):
    # a closed ring starts and ends on one point, which the line simplifier can't split, so simplify it in two halves
    half = len(r) // 2
    return simplify(r[:half + 1], tol) + simplify(r[half:], tol)[1:]


def bng_to_ll(E, N):
    """British National Grid to approximate lat/lon (OSGB36, close enough for a map dot)."""
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
        if abs(N - N0 - M) < 0.01: break
    s, c, t = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * F0 / math.sqrt(1 - e2 * s * s); rho = a * F0 * (1 - e2) / (1 - e2 * s * s) ** 1.5; eta2 = nu / rho - 1
    d = E - E0
    VII = t / (2 * rho * nu); VIII = t / (24 * rho * nu ** 3) * (5 + 3 * t * t + eta2 - 9 * t * t * eta2)
    X = 1 / (c * nu); XI = 1 / (c * 6 * nu ** 3) * (nu / rho + 2 * t * t)
    return math.degrees(lat - VII * d ** 2 + VIII * d ** 4), math.degrees(lon0 + X * d - XI * d ** 3)


REPD_GROUP = {'Solar Photovoltaics': 'solar', 'Wind Onshore': 'wind', 'Wind Offshore': 'wind', 'Small Hydro': 'hydro', 'Large Hydro': 'hydro', 'Pumped Storage Hydroelectricity': 'hydro',
              'Landfill Gas': 'biomass', 'Anaerobic Digestion': 'biomass', 'Biomass (dedicated)': 'biomass', 'Biomass (co-firing)': 'biomass', 'EfW Incineration': 'biomass', 'Advanced Conversion Technologies': 'biomass', 'Sewage Sludge Digestion': 'biomass',
              'Battery': 'other'}


SITE_INFO = collections.defaultdict(list)


def load_sites():
    sites = collections.defaultdict(list)
    for r in csv.DictReader(open(D / 'repd.csv', encoding='latin-1')):
        if (r.get('Development Status (short)') or '').strip() != 'Operational' or r.get('Country') == 'Northern Ireland':
            continue
        g = REPD_GROUP.get(r.get('Technology Type'))
        try:
            mw = float((r.get('Installed Capacity (MWelec)') or '0').replace(',', ''))
            e, n = float(r['X-coordinate'].replace(',', '')), float(r['Y-coordinate'].replace(',', ''))
        except ValueError:
            continue
        if g and mw >= 1:
            p = xy(*bng_to_ll(e, n))
            sites[g].append(p)
            SITE_INFO[g].append((p, (r.get('Site Name') or 'Unnamed site').strip(), mw))
    return sites


SITES = load_sites()


def fuelvar(s):
    if 'solar' in s['name'].lower(): return 'solar'
    return {'Gas': 'gas', 'Gas peakers': 'gas', 'Nuclear': 'nuclear', 'Wind': 'wind', 'Biomass': 'biomass', 'Hydro': 'hydro', 'Pumped storage': 'hydro', 'Imports': 'imports', 'Coal': 'coal'}.get(s['fuel'], 'other')


def build_svg(view, top=4):
    W, H = (700, 340) if view == 'near' else (420, 770)
    chosen = rows[:top]
    if view == 'near':
        xs = [start_xy[0]] + [s['xy'][0] for s in chosen]; ys = [start_xy[1]] + [s['xy'][1] for s in chosen]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        px, py = (x1 - x0) * .16 + 8, (y1 - y0) * .22 + 8
        x0 -= px; x1 += px; y0 -= py; y1 += py
    else:
        x0, y0 = xy(49.85, -8.2); x1, y1 = xy(60.95, 2.0)
    if (x1 - x0) / (y1 - y0) < W / H:
        e = ((y1 - y0) * W / H - (x1 - x0)) / 2; x0 -= e; x1 += e
    else:
        e = ((x1 - x0) * H / W - (y1 - y0)) / 2; y0 -= e; y1 += e
    k = W / (x1 - x0)
    P = lambda p: (round((p[0] - x0) * k, 1), round((y1 - p[1]) * k, 1))
    inview = lambda p: x0 - 5 < p[0] < x1 + 5 and y0 - 5 < p[1] < y1 + 5
    path = lambda pts: 'M' + 'L'.join(f'{x},{y}' for x, y in map(P, pts))
    tol = .25 if view == 'near' else 1.5
    land = []
    for f in json.load(open(D / 'land.json'))['features']:
        polys = f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiPolygon' else [f['geometry']['coordinates']]
        for poly in polys:
            ring = [xy(lat, lon) for lon, lat in poly[0]]
            if any(inview(p) for p in ring): land.append(path(simplify_ring(ring, tol)) + 'Z')
    lines = [path(simplify(g, tol)) for g in geoms if any(inview(p) for p in g)]
    name = 'the high-voltage lines around ' + TARGET[0] if view == 'near' else 'Great Britain'
    out = [f'<svg class="map{"" if view == "near" else " tall"}" viewBox="0 0 {W} {H}" role="img" aria-label="Map of {name}, with power stations and renewable sites as coloured dots">']
    out.append(f'<path class="land" d="{"".join(land)}"/>')
    if view != 'all':
        out.append(f'<path class="net" d="{"".join(lines)}"/>')
    dot = 5 if view == 'near' else 3.4
    for g, pts in SITES.items():
        seen = [P(p) for p in pts if inview(p)]
        d = ''.join(f'M{x} {y}h0' for x, y in seen)
        if d: out.append(f'<path class="site" data-f="{g}" data-n="{len(seen)}" style="stroke:var(--{g});stroke-width:{dot}" d="{d}"/>')
    for s in (rows if view == 'all' else rows[top:]):
        if inview(s['xy']):
            x, y = P(s['xy'])
            r = max(2.2, math.sqrt(s['mw']) * (.22 if view == 'near' else .17))
            out.append(f'<circle class="run" data-f="{fuelvar(s)}" data-n="1" cx="{x}" cy="{y}" r="{r:.1f}" style="fill:var(--{fuelvar(s)})"><title>{s["name"]}, {s["fuel"]}</title></circle>')
    if view == 'all':
        out.append('<g id="allYou"></g></svg>')
        return ''.join(out), (x0, y1, k)
    for s in chosen[::-1]:
        out.append(f'<path class="route" data-f="{fuelvar(s)}" style="stroke:var(--{fuelvar(s)});stroke-width:{2 + s["share"] * 12:.1f}" d="{path(simplify(route(s), tol))}"/>')
    placed = []
    def label(x, y, text, cls):
        a = 'end' if x > W * .7 else 'start'
        tx = x - 14 if a == 'end' else x + 14
        ty = y + 5
        w = len(text) * 8.2
        L = tx - w if a == 'end' else tx
        while any(L < b[1] and L + w > b[0] and abs(ty - b[2]) < 20 for b in placed): ty += 20
        placed.append((L, L + w, ty))
        return f'<text class="{cls}" x="{tx}" y="{ty}" text-anchor="{a}">{text}</text>'
    tx, ty = P(start_xy)
    labels = [label(tx, ty, f'Your area ({TARGET[0]})', 'lab you' if view == 'near' else 'lab you big')]
    for s in chosen:
        x, y = P(s['xy'])
        scale = 1 if view == 'near' else .7
        out.append(f'<circle class="src" data-f="{fuelvar(s)}" data-n="1" cx="{x}" cy="{y}" r="{(5 + s["share"] * 16) * scale:.1f}" style="fill:var(--{fuelvar(s)})"><title>{s["name"]}, {s["fuel"]}, {s["share"]:.0%}</title></circle>')
        if view == 'near': labels.append(label(x, y, s['name'].replace(' Energy', ''), 'lab'))
    out.append(f'<circle class="ring" cx="{tx}" cy="{ty}" r="{13 if view == "near" else 17}"/><circle class="you" cx="{tx}" cy="{ty}" r="{6 if view == "near" else 8}"/>')
    out += labels
    out.append('</svg>')
    return ''.join(out)


def build_base():
    """Land and lines once, in km, shared by every fuel view through <use>."""
    q = lambda p: f'{round(p[0], 1)},{round(-p[1], 1)}'
    x0, y0 = xy(47.5, -11); x1, y1 = xy(62, 7)
    near = lambda p: x0 < p[0] < x1 and y0 < p[1] < y1
    land = []
    for f in json.load(open(D / 'land.json'))['features']:
        polys = f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiPolygon' else [f['geometry']['coordinates']]
        for poly in polys:
            ring = [xy(lat, lon) for lon, lat in poly[0]]
            if any(near(p) for p in ring):
                land.append('M' + 'L'.join(q(p) for p in simplify_ring(ring, .7)) + 'Z')
    lines = ['M' + 'L'.join(q(p) for p in simplify(g, .5)) for g in geoms]
    return f'<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><g id="gridbase"><path class="base-land" d="{"".join(land)}"/><path class="base-net" d="{"".join(lines)}"/></g></defs></svg>'


def tidy(n):
    n = re.sub(r'\s*-\s*$', '', n.strip())
    n = re.sub(r'\s+(Generator|Generating Station)$', '', n)
    return n.replace('Connahs', "Connah's")


def export_geo(view):
    """Everything the page needs to work out and draw any postcode by itself."""
    idx = {n: i for i, n in enumerate(nodes)}
    flat = lambda pts: [round(v, 1) for p in pts for v in p]
    ways, edges = [], []
    for n in nodes:
        for m, L, k, rev in adj[n]:
            if not rev and m in idx:
                edges.append([idx[n], idx[m], round(L, 1), len(ways)])
                ways.append(flat(simplify(geoms[k], .4)))
    outcodes = json.load(open(D / 'outcodes.json', encoding='utf8'))
    return {
        'nodes': flat(node_xy[n] for n in nodes), 'edges': edges, 'ways': ways,
        'stations': [[tidy(s['name']), tidy(s.get('cable') or s['name']).replace(' Energy', '').replace(' Power Station', ''), fuelvar(s), s['fuel'], s['mw'], round(s['xy'][0], 1), round(s['xy'][1], 1)] for s in rows],
        'sites': {g: flat(pts) for g, pts in SITES.items()},
        'out': {c: [round(v, 1) for v in xy(lat, lon)] for c, (lat, lon) in outcodes.items()},
        'all': {'x0': round(view[0], 3), 'y1': round(view[1], 3), 'k': round(view[2], 6)},
    }


def build_map():
    all_svg, view = build_svg('all')
    return {'fuels': build_base(), 'all': all_svg, 'geo': export_geo(view)}


if __name__ == '__main__':
    print('ways', len(ways), 'nodes', len(adj), 'components', [len(c) for c in comps[:6]], 'matched MW', matched, 'of', sum(u['mw'] for u in units))
    m = build_map()
    (HERE / 'map.json').write_text(json.dumps(m, separators=(',', ':')), encoding='utf8')
    print('bytes base', len(m['fuels']), 'all', len(m['all']), 'geo', len(json.dumps(m['geo'], separators=(',', ':'))))
