"""Draw the 14 GB electricity regions as an SVG with empty colours; the page fills them in from the regional mix."""
import json, math, pathlib

HERE = pathlib.Path(__file__).resolve().parent
TO_REGION = {17: 1, 18: 2, 16: 3, 15: 4, 23: 5, 13: 6, 21: 7, 14: 8, 11: 9, 10: 10, 22: 11, 20: 12, 12: 13, 19: 14}
H = 560
MIN_AREA_KM2 = 30


def ring_area(r):
    return sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r))) / 2


def centroid(r):
    a = ring_area(r) or 1e-9
    cx = sum((r[i][0] + r[(i + 1) % len(r)][0]) * (r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1]) for i in range(len(r))) / (6 * a)
    cy = sum((r[i][1] + r[(i + 1) % len(r)][1]) * (r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1]) for i in range(len(r))) / (6 * a)
    return cx, cy


def simplify(pts, tol):
    if len(pts) < 4: return pts
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


features = json.load(open(HERE / 'data' / 'dno.geojson', encoding='utf8'))['features']
regions = {}
for f in features:
    polys = []
    for poly in f['geometry']['coordinates']:
        ring = [(x / 1000, y / 1000) for x, y, *_ in poly[0]]
        if abs(ring_area(ring)) >= MIN_AREA_KM2:
            polys.append(ring)
    regions[TO_REGION[f['properties']['ID']]] = polys

xs = [p[0] for polys in regions.values() for r in polys for p in r]
ys = [p[1] for polys in regions.values() for r in polys for p in r]
x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
k = (H - 8) / (y1 - y0)
W = round((x1 - x0) * k + 90)  # room on the right for the London label
P = lambda p: (round((p[0] - x0) * k + 4, 1), round((y1 - p[1]) * k + 4, 1))

# (dx, dy) label nudges in px where the shape's centre isn't the best spot
NUDGE = {1: (10, 20), 2: (0, 4), 6: (-4, 4), 11: (14, -8), 12: (-6, 2), 14: (10, 8)}
paths, labels = [], []
for rid, polys in sorted(regions.items()):
    d = ''.join('M' + 'L'.join(f'{x},{y}' for x, y in map(P, simplify_ring(r, 1.2))) + 'Z' for r in polys)
    paths.append(f'<path class="reg" data-id="{rid}" d="{d}"><title></title></path>')
    x, y = P(centroid(max(polys, key=lambda r: abs(ring_area(r)))))
    if rid == 13:
        lx, ly = W - 46, y - 16
        labels.append(f'<path class="lead" d="M{x},{y}L{lx - 22},{ly - 4}"/><text class="regval" data-id="13" x="{lx}" y="{ly}" text-anchor="middle"></text><text class="regname" x="{lx}" y="{ly - 18}" text-anchor="middle">London</text>')
    else:
        dx, dy = NUDGE.get(rid, (0, 0))
        labels.append(f'<text class="regval" data-id="{rid}" x="{round(x + dx, 1)}" y="{round(y + dy + 5, 1)}" text-anchor="middle"></text>')

svg = f'<svg class="regions" viewBox="0 0 {W} {H}" role="img" aria-label="Map of the 14 electricity regions of Great Britain, coloured by share of power">{"".join(paths)}{"".join(labels)}</svg>'
(HERE / 'regions.svg').write_text(svg, encoding='utf8')
print('regions svg bytes', len(svg), 'W', W, 'H', H)
