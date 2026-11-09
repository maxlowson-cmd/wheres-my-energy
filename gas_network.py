"""Turn an OpenStreetMap export of gas pipelines into gas_net.json, a small routable network for the share images.

Pipeline data (c) OpenStreetMap contributors, Open Database Licence. Run by hand when the routes need refreshing:
    python gas_network.py path/to/overpass.json
The export is the Overpass query: way["man_made"="pipeline"]["substance"~"^(gas|natural_gas|cng|lng|fuel_gas)$"](49.5,-8,62,6.5);out tags geom;
"""
import collections, heapq, json, math, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
LAT0 = float(re.search(r'^LAT0\s*=\s*([\d.]+)', (HERE / 'model.py').read_text(encoding='utf8'), re.M).group(1))
SNAP_KM, TOL_KM, BRIDGE_KM, STUB_KM, LINK_KM = 1.5, 1.5, 70, 6, 6
ABROAD = ('natran', 'fluxys', 'gasunie', 'gas networks ireland', 'creos', 'belfast', 'grtgaz', 'thyssengas', 'open grid', 'ontras', 'gascade', 'nowega', 'bord gais', 'mutual energy', 'gaz', 'energinet')
OFFSHORE = ('langeled', 'vesterled', 'flags', 'cats', 'central area transmission', 'bbl', 'interconnector', 'sage', 'seal', 'shearwater', 'fulmar', 'frigg', 'mcp', 'lancelot', 'lots', 'teesside', 'esmond', 'bacton', 'statpipe', 'dimlington', 'rough', 'cms', 'caister', 'sean', 'sleipner', 'tampen', 'gjoa', 'miller')


def xy(lon, lat):
    return (round((lon + 2.0) * 111.32 * math.cos(math.radians(LAT0)), 2), round((lat - 54.0) * 110.57, 2))


def in_ireland(lon, lat):
    return (lon < -5.45 and 51.2 < lat < 55.5) or (lon < -5.2 and 54 < lat < 55.5 and lat < 55.5 and lon > -8.5 and lon < -5.4)


def at_sea(lon, lat):
    return (lat >= 56 and lon > -1.5) or (54.6 <= lat < 56 and lon > -1.0) or (53.7 <= lat < 54.6 and lon > .35) or (52.95 <= lat < 53.7 and lon > 1.75) or lat > 58.75


def keep(tags, geom):
    text = ' '.join(str(tags.get(k, '')) for k in ('operator', 'name')).lower()
    if any(a in text for a in ABROAD) or 'ireland' in text.replace('uk-ireland interconnector', 'ic'):
        return False
    if tags.get('usage') in ('distribution', 'industrial', 'flare_header', 'injection'):
        return False
    lons = [p['lon'] for p in geom]; lats = [p['lat'] for p in geom]
    named = any(a in text for a in OFFSHORE)
    # this network is for the journey over land: gas does not travel between terminals by sea, and the sea pipes are added as named legs
    if named or sum(at_sea(a, b) for a, b in zip(lons, lats)) > len(lons) / 2:
        return False
    if all(in_ireland(a, b) for a, b in zip(lons, lats)):
        return False
    if max(lons) > 3.2 and max(lats) < 56.5 and not named:  # the Low Countries and France
        return False
    if min(lats) < 50.5 and min(lons) > -1.5 and not named and max(lons) > 1.2:
        return False
    return True


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    seg = dist(a, b) or 1e-9
    best, at = -1, 0
    for i, p in enumerate(pts[1:-1], 1):
        d = abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / seg
        if d > best:
            best, at = d, i
    return simplify(pts[:at + 1], tol)[:-1] + simplify(pts[at:], tol) if best > tol else [a, b]


raw = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf8'))['elements']
ways = [[xy(p['lon'], p['lat']) for p in e['geometry']] for e in raw if e.get('geometry') and keep(e.get('tags', {}), e['geometry'])]
print('ways kept', len(ways), 'of', len(raw))

# junctions: any point on a way where another way touches, or where ends are close enough to be the same pipe
counts = collections.Counter(p for w in ways for p in w)
ends = sorted({p for w in ways for p in (w[0], w[-1])})
cell = collections.defaultdict(list)
for p in ends:
    cell[(int(p[0] // SNAP_KM), int(p[1] // SNAP_KM))].append(p)
parent = {p: p for p in ends}


def find(p):
    while parent[p] != p:
        parent[p] = parent[parent[p]]
        p = parent[p]
    return p


for p in ends:
    cx, cy = int(p[0] // SNAP_KM), int(p[1] // SNAP_KM)
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            for q in cell[(cx + i, cy + j)]:
                if p < q and dist(p, q) <= SNAP_KM:
                    parent[find(p)] = find(q)
canon = lambda p: find(p) if p in parent else p

# a way's end that lands part-way along another way needs a junction there
points = collections.defaultdict(list)
for w in ways:
    for p in w:
        points[(int(p[0] // SNAP_KM), int(p[1] // SNAP_KM))].append(p)
extra = {}
for p in ends:
    if counts[p] > 1:
        continue
    cx, cy = int(p[0] // SNAP_KM), int(p[1] // SNAP_KM)
    near = [q for i in (-1, 0, 1) for j in (-1, 0, 1) for q in points[(cx + i, cy + j)] if q != p and dist(p, q) <= SNAP_KM]
    if near:
        extra[p] = min(near, key=lambda q: dist(p, q))
junction = set(p for p, n in counts.items() if n > 1) | {canon(p) for p in ends} | set(extra.values())

edges = []
for w in ways:
    path = [canon(extra.get(p, p)) if i in (0, len(w) - 1) else p for i, p in enumerate(w)]
    start = 0
    for i in range(1, len(path)):
        if path[i] in junction or i == len(path) - 1:
            part = path[start:i + 1]
            if part[0] != part[-1]:
                edges.append(part)
            start = i
seen, unique = set(), []
for e in edges:
    key = (e[0], e[-1], len(e))
    if key not in seen and (e[-1], e[0], len(e)) not in seen:
        seen.add(key); unique.append(e)
# OpenStreetMap has gaps: join separate pieces at their closest points, longest gaps last, with short straight links
ends_all = sorted({e[0] for e in unique} | {e[-1] for e in unique})
root = {p: p for p in ends_all}


def top(p):
    while root[p] != p:
        root[p] = root[root[p]]
        p = root[p]
    return p


for e in unique:
    root[top(e[0])] = top(e[-1])
print('pieces before joining', len({top(p) for p in ends_all}))
grid = collections.defaultdict(list)
for p in ends_all:
    grid[(int(p[0] // BRIDGE_KM), int(p[1] // BRIDGE_KM))].append(p)
pairs = []
for p in ends_all:
    cx, cy = int(p[0] // BRIDGE_KM), int(p[1] // BRIDGE_KM)
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            for q in grid[(cx + i, cy + j)]:
                if p < q and top(p) != top(q) and dist(p, q) <= BRIDGE_KM:
                    pairs.append((dist(p, q), p, q))
pairs.sort()
joined = []
for d, p, q in pairs:
    if top(p) != top(q):
        root[top(p)] = top(q); unique.append([p, q]); joined.append(d)
print('joins', len(joined), 'longest', round(max(joined or [0]), 1), 'over 10 km', sum(d > 10 for d in joined), 'pieces after', len({top(p) for p in ends_all}))
main = collections.Counter(top(p) for p in ends_all).most_common(1)[0][0]
unique = [e for e in unique if top(e[0]) == main]
# pipes that meet at a compressor or offtake are often mapped a little apart: link every loose end to the closest other piece of network
# Teesside's feeder to Bishop Auckland compressor is missing from the mapping
for a, b in (((54.59, -1.25), (54.68, -1.66)),):
    pts_all = sorted({p for e in unique for p in (e[0], e[-1])})
    unique.append([min(pts_all, key=lambda p: dist(p, xy(a[1], a[0]))), min(pts_all, key=lambda p: dist(p, xy(b[1], b[0])))])
deg = collections.Counter(p for e in unique for p in (e[0], e[-1]))
live = sorted({p for e in unique for p in (e[0], e[-1])})
grid2 = collections.defaultdict(list)
for p in live:
    grid2[(int(p[0] // LINK_KM), int(p[1] // LINK_KM))].append(p)
owner = collections.defaultdict(set)
for i, e in enumerate(unique):
    owner[e[0]].add(i); owner[e[-1]].add(i)
links = 0
for p in live:
    cx, cy = int(p[0] // LINK_KM), int(p[1] // LINK_KM)
    near = [(dist(p, q), q) for i in (-1, 0, 1) for j in (-1, 0, 1) for q in grid2[(cx + i, cy + j)] if q != p and dist(p, q) <= LINK_KM and not (owner[p] & owner[q])]
    near.sort()
    for d, q in near[:1 if deg[p] > 1 else 3]:
        unique.append([p, q]); links += 1
print('extra links', links)
while True:
    degree = collections.Counter(p for e in unique for p in (e[0], e[-1]))
    stubs = [e for e in unique if (degree[e[0]] == 1 or degree[e[-1]] == 1) and sum(dist(e[i], e[i + 1]) for i in range(len(e) - 1)) < STUB_KM]
    if not stubs:
        break
    gone = {id(e) for e in stubs}
    unique = [e for e in unique if id(e) not in gone]

ids = {}
nodes = []
out_edges = []
geoms = []
for e in unique:
    for end in (e[0], e[-1]):
        if end not in ids:
            ids[end] = len(nodes); nodes.append(end)
    length = sum(dist(e[i], e[i + 1]) for i in range(len(e) - 1))
    s = simplify(e, TOL_KM)
    out_edges.append([ids[e[0]], ids[e[-1]], round(length, 1), len(geoms)])
    geoms.append([c for p in s[1:-1] for c in p])
net = {'nodes': [c for p in nodes for c in p], 'edges': out_edges, 'ways': geoms}


def named_leg(names, origin, terminal):
    """The real offshore pipe between the point nearest the origin and the terminal, joined across small gaps in the mapping."""
    lines = [[xy(p['lon'], p['lat']) for p in e['geometry']] for e in raw if e.get('geometry') and any(n in str(e.get('tags', {}).get('name', '')).lower() for n in names)]
    pts = sorted({p for w in lines for p in w})
    g = collections.defaultdict(list)
    for w in lines:
        for a, b in zip(w, w[1:]):
            g[a].append((b, dist(a, b))); g[b].append((a, dist(a, b)))
    ends = [p for p in pts if len(g[p]) == 1]
    for p in ends:
        for q in ends:
            if p < q and dist(p, q) < 40:
                g[p].append((q, dist(p, q) * 3)); g[q].append((p, dist(p, q) * 3))
    a, b = min(pts, key=lambda p: dist(p, origin)), min(pts, key=lambda p: dist(p, terminal))
    pq, best, prev = [(0, a)], {a: 0}, {}
    while pq:
        d, n = heapq.heappop(pq)
        if n == b:
            break
        for m, L in g[n]:
            if d + L < best.get(m, 1e12):
                best[m] = d + L; prev[m] = n; heapq.heappush(pq, (d + L, m))
    if b not in prev:
        return None, 0
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    path.reverse()
    return simplify(path, TOL_KM), best[b]


LEGS = {'Easington|norway': (('langeled',), (58.4, 1.9), (53.646, .117)), 'St Fergus|norway': (('vesterled',), (59.6, 2.2), (57.578, -1.835)), 'St Fergus|uk': (('flags',), (58.2, .2), (57.578, -1.835)), 'Teesside|uk': (('cats', 'central area'), (56.9, 1.9), (54.625, -1.19)), 'Bacton|europe': (('bbl',), (52.3, 3.0), (52.862, 1.468))}
legs = {}
for key, (names, o, tm) in LEGS.items():
    path, km = named_leg(names, xy(o[1], o[0]), xy(tm[1], tm[0]))
    print(key, None if path is None else (len(path), round(km)))
    if path:
        legs[key] = [c for p in path for c in p]
net['legs'] = legs
(HERE / 'gas_net.json').write_text(json.dumps(net, separators=(',', ':')), encoding='utf8')
print('nodes', len(nodes), 'edges', len(out_edges), 'bytes', (HERE / 'gas_net.json').stat().st_size)

adj = collections.defaultdict(list)
for a, b, L, _ in out_edges:
    adj[a].append((b, L)); adj[b].append((a, L))


def route(a, b):
    pq, best = [(0, a)], {a: 0}
    while pq:
        d, n = heapq.heappop(pq)
        if n == b:
            return d
        for m, L in adj[n]:
            if d + L < best.get(m, 1e9):
                best[m] = d + L; heapq.heappush(pq, (d + L, m))
    return None


def nearest(p):
    i = min(range(len(nodes)), key=lambda k: dist(nodes[k], p))
    return i, dist(nodes[i], p)


T = {'St Fergus': (57.578, -1.835), 'Easington': (53.646, 0.117), 'Bacton': (52.862, 1.468), 'Teesside': (54.625, -1.190), 'Milford Haven': (51.700, -5.100), 'Isle of Grain': (51.445, 0.708)}
S = {'Enfield': (51.67, -.01), 'Pembroke': (51.68, -4.99), 'Didcot B': (51.62, -1.27), 'Connahs Quay': (53.23, -3.08), 'Peterhead': (57.48, -1.79), 'Saltend': (53.73, -.25), 'West Burton': (53.36, -.81), 'Staythorpe': (53.07, -.85), 'Medway': (51.43, .70), 'Seabank': (51.54, -2.67), 'Rocksavage': (53.32, -2.72), 'Keadby': (53.60, -.75), 'Marchwood': (50.90, -1.44), 'Spalding': (52.82, -.13)}
O = {'Easington norway': (58.4, 1.9), 'St Fergus norway': (59.6, 2.2), 'St Fergus uk': (58.2, .2), 'Easington uk': (53.9, 1.6), 'Bacton uk': (53.4, 2.2), 'Teesside uk': (56.9, 1.9), 'Bacton europe': (52.3, 3.0)}
print('\nterminals, km from nearest node'); tn = {}
for n, (la, lo) in T.items():
    i, d = nearest(xy(lo, la)); tn[n] = i; print(f'  {n}: {d:.1f}')
print('\nnetwork km / straight km, terminal to station')
for sn, (la, lo) in S.items():
    p = xy(lo, la); i, d = nearest(p)
    row = []
    for n, (tla, tlo) in T.items():
        r = route(tn[n], i)
        row.append('--' if r is None else f'{r / max(dist(xy(tlo, tla), p), 1):.1f}')
    print(f'  {sn:14s} snap {d:5.1f}  ' + ' '.join(row))
print('\noffshore legs: snap km, network km, straight km')
for k, (la, lo) in O.items():
    t = k.rsplit(' ', 1)[0]; p = xy(lo, la); i, d = nearest(p); r = route(i, tn[t])
    print(f'  {k}: {d:.0f}, {r}, {dist(p, nodes[tn[t]]):.0f}')
