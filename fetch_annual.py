"""One-off (re-run each January): Great Britain's average fuel mix for each full calendar year since 2019. Writes social/annual_mix.json.

Source: NESO Carbon Intensity API, national (region 18) half-hourly mix, averaged over the year. Includes estimated
small solar and wind that the metered main-grid figures leave out.
"""
import collections, datetime as dt, json, pathlib, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
FUELS = ['gas', 'wind', 'nuclear', 'imports', 'biomass', 'solar', 'hydro', 'coal', 'other']


def pull(chunk):
    a, b = chunk
    url = f'https://api.carbonintensity.org.uk/regional/intensity/{a:%Y-%m-%dT%H:%MZ}/{b:%Y-%m-%dT%H:%MZ}'
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/1.0'}), timeout=120) as r:
                rows = json.load(r)['data']
            sums, seen = [0.0] * len(FUELS), set()
            for row in rows:
                if row['from'] in seen or row['from'] >= f'{b:%Y-%m-%dT%H:%MZ}':
                    continue
                gb = next((g for g in row['regions'] if g['regionid'] == 18), None)
                if not gb:
                    continue
                seen.add(row['from'])
                perc = {m['fuel']: m['perc'] for m in gb['generationmix']}
                for k, f in enumerate(FUELS):
                    sums[k] += perc.get(f, 0)
            return sums, len(seen)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))


out = {'source': 'NESO Carbon Intensity API, Great Britain half-hourly generation mix, averaged over each calendar year', 'fuels': FUELS, 'years': {}}
last = dt.date.today().year - 1
for year in range(2019, last + 1):
    t, end, chunks = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc), dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc), []
    while t < end:
        chunks.append((t, min(t + dt.timedelta(days=13), end)))
        t += dt.timedelta(days=13)
    with ThreadPoolExecutor(6) as pool:
        parts = list(pool.map(pull, chunks))
    n = sum(p[1] for p in parts)
    mix = [round(sum(p[0][k] for p in parts) / n, 1) for k in range(len(FUELS))]
    out['years'][str(year)] = {'slots': n, 'mix': dict(zip(FUELS, mix))}
    print(year, n, dict(zip(FUELS, mix)))
(HERE / 'social' / 'annual_mix.json').write_text(json.dumps(out, indent=1), encoding='utf8')
