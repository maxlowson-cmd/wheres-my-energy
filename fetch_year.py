"""One-off: average regional fuel mix over the last 12 months, in 13-day chunks. Writes year.json."""
import json, pathlib, urllib.request, urllib.error, datetime as dt, collections, time
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
FUELS = ['gas', 'wind', 'nuclear', 'imports', 'biomass', 'solar', 'hydro', 'coal', 'other']
end = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
start = end - dt.timedelta(days=364)
chunks = []
t = start
while t < end:
    chunks.append((t, min(t + dt.timedelta(days=13), end)))
    t += dt.timedelta(days=13)


def pull(c):
    a, b = c
    url = f'https://api.carbonintensity.org.uk/regional/intensity/{a:%Y-%m-%dT%H:%MZ}/{b:%Y-%m-%dT%H:%MZ}'
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/1.0'})
            with urllib.request.urlopen(req, timeout=120) as r:
                rows = json.load(r)['data']
            sums = collections.defaultdict(lambda: [0.0] * len(FUELS))
            n = collections.Counter()
            seen = set()
            for row in rows:
                if row['from'] in seen or row['from'] >= f'{b:%Y-%m-%dT%H:%MZ}':
                    continue
                seen.add(row['from'])
                for reg in row['regions']:
                    i = reg['regionid']
                    if 1 <= i <= 14 or i == 18:  # 18 is the whole of Great Britain
                        perc = {m['fuel']: m['perc'] for m in reg['generationmix']}
                        n[i] += 1
                        for k, f in enumerate(FUELS):
                            sums[i][k] += perc.get(f, 0)
            return dict(sums), dict(n), len(seen)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 3:
                raise
            time.sleep(3)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3)


with ThreadPoolExecutor(3) as ex:
    results = list(ex.map(pull, chunks))
total = collections.defaultdict(lambda: [0.0] * len(FUELS)); count = collections.Counter(); slots = 0
for sums, n, s in results:
    slots += s
    for i, vals in sums.items():
        count[i] += n[i]
        total[i] = [a + b for a, b in zip(total[i], vals)]
out = {'from': start.strftime('%Y-%m-%d'), 'to': end.strftime('%Y-%m-%d'), 'slots': slots, 'fuels': FUELS,
       'regions': {str(i): [round(v / count[i], 2) for v in total[i]] for i in sorted(total)}}
(HERE / 'year.json').write_text(json.dumps(out, separators=(',', ':')), encoding='utf8')
print('chunks', len(chunks), 'slots', slots, 'of expected', 364 * 48)
for i in (1, 2, 4, 7, 13):
    r = dict(zip(FUELS, out['regions'][str(i)]))
    print(i, 'renew', round(r['wind'] + r['solar'] + r['hydro'] + r['biomass']), 'fossil', round(r['gas'] + r['coal']), r)
