"""Fetch live GB grid data and write grid_snapshot.json for the GB Grid Live dashboard.

Sources: Elexon BMRS Insights API and the National Grid ESO Carbon Intensity API (both free, no key).
Run: python refresh.py   -> writes grid_snapshot.json next to this file and prints a one-line summary.
"""
import json, collections, datetime as dt, time, urllib.error, urllib.request, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
B = 'https://data.elexon.co.uk/bmrs/api/v1'
CI = 'https://api.carbonintensity.org.uk'
POSTCODE = 'SW9'


def get(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'gb-grid-live/1.0'})
    for attempt in range(4):  # retry one-off server errors and timeouts
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3 or (isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429):
                raise
            time.sleep(5 * (attempt + 1))


def last_sunday(year, month):
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def uk_offset(t):
    """UTC offset for UK local time at UTC instant t (BST: last Sun Mar 01:00 UTC to last Sun Oct 01:00 UTC)."""
    start = dt.datetime.combine(last_sunday(t.year, 3), dt.time(1), dt.timezone.utc)
    end = dt.datetime.combine(last_sunday(t.year, 10), dt.time(1), dt.timezone.utc)
    return dt.timedelta(hours=1) if start <= t < end else dt.timedelta(0)


now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
local = now + uk_offset(now)
today = local.date()
yday = today - dt.timedelta(days=1)
# settlement period = half hours since local midnight (handles clock-change days)
mid_local = dt.datetime.combine(today, dt.time(0), dt.timezone.utc)
mid_utc = mid_local - uk_offset(mid_local - dt.timedelta(hours=1))
sp_now = int((now - mid_utc).total_seconds() // 1800) + 1
iso = lambda t: t.strftime('%Y-%m-%dT%H:%MZ')
half = now.replace(minute=0 if now.minute < 30 else 30)

cur = get(f'{B}/generation/outturn/current?format=json')
fh = get(f'{B}/datasets/FUELHH?settlementDateFrom={yday}&settlementDateTo={today}&format=json')['data']
sp_rows = get(f'{B}/balancing/settlement/system-prices/{yday}?format=json')['data'] + \
          get(f'{B}/balancing/settlement/system-prices/{today}?format=json')['data']
mid_rows = get(f'{B}/datasets/MID?from={iso(now - dt.timedelta(hours=25))}&to={iso(now + dt.timedelta(hours=1))}&format=json')['data']
pn = get(f'{B}/datasets/PN?settlementDate={today}&settlementPeriod={sp_now}&format=json')['data']
bmu_list = get(f'{B}/reference/bmunits/all')
ci_now = get(f'{CI}/regional/postcode/{POSTCODE}')
ci_fw = get(f'{CI}/regional/intensity/{iso(half)}/fw24h/postcode/{POSTCODE}')

NAMES = {'CCGT': 'Gas', 'OCGT': 'Gas peakers', 'NUCLEAR': 'Nuclear', 'WIND': 'Wind', 'BIOMASS': 'Biomass',
         'NPSHYD': 'Hydro', 'PS': 'Pumped storage', 'COAL': 'Coal', 'OIL': 'Oil', 'OTHER': 'Other'}
INT = {'INTFR': 'France (IFA)', 'INTIFA2': 'France (IFA2)', 'INTELEC': 'France (ElecLink)', 'INTNED': 'Netherlands',
       'INTNEM': 'Belgium', 'INTNSL': 'Norway', 'INTVKL': 'Denmark', 'INTIRL': 'Ireland',
       'INTEW': 'Ireland (East-West)', 'INTGRNL': 'Ireland (Greenlink)'}


def group(f):
    if f.startswith('INT'):
        return 'Imports'
    return {'CCGT': 'Gas', 'OCGT': 'Gas', 'NUCLEAR': 'Nuclear', 'WIND': 'Wind', 'BIOMASS': 'Biomass',
            'NPSHYD': 'Hydro & storage', 'PS': 'Hydro & storage'}.get(f, 'Other')


mix_now = [{'fuel': INT.get(r['fuelType'], r['fuelType']) if r['fuelType'].startswith('INT') else NAMES.get(r['fuelType'], r['fuelType']),
            'group': group(r['fuelType']), 'mw': r['currentUsage'],
            'share': round(r['currentPercentage'] / 100, 4), 'share_24h': round(r['twentyFourHourPercentage'] / 100, 4)}
           for r in cur]

times = sorted({r['startTime'] for r in fh})[-48:]
agg = collections.defaultdict(int)
for r in fh:
    if r['startTime'] in times:
        agg[(r['startTime'], group(r['fuelType']))] += r['generation']
mix_hh = [{'time': t, 'source': g, 'mw': v} for (t, g), v in sorted(agg.items())]

sp = {r['startTime']: r for r in sp_rows}
mid = {r['startTime']: r['price'] for r in mid_rows if r['dataProvider'] == 'APXMIDP'}
prices = [{'time': t, 'system_price': round(float(sp[t]['systemSellPrice']), 2),
           'market_price': round(mid[t], 2) if mid.get(t) else None,
           'imbalance_mwh': round(float(sp[t]['netImbalanceVolume']), 1)}
          for t in sorted(sp) if t >= times[0]][-48:]

bmu = {b['elexonBmUnit']: b for b in bmu_list}
lvl = collections.defaultdict(float); dur = collections.defaultdict(float)
for r in pn:
    if not r.get('bmUnit'):
        continue
    a = dt.datetime.fromisoformat(r['timeFrom'].rstrip('Z')); b = dt.datetime.fromisoformat(r['timeTo'].rstrip('Z'))
    d = max((b - a).total_seconds(), 1)
    lvl[r['bmUnit']] += (r['levelFrom'] + r['levelTo']) / 2 * d; dur[r['bmUnit']] += d
units = []
for u in lvl:
    mw = lvl[u] / dur[u]
    if mw <= 0 or u.startswith('I_'):
        continue
    b = bmu.get(u, {})
    units.append({'unit': u, 'name': b.get('bmUnitName') or u,
                  'fuel': NAMES.get(b.get('fuelType') or '', (b.get('fuelType') or 'Unknown').title()),
                  'company': b.get('leadPartyName') or 'Unknown',
                  'capacity_mw': float(b.get('generationCapacity') or 0), 'mw': round(mw)})
units.sort(key=lambda x: -x['mw'])
comp = collections.defaultdict(float)
for u in units:
    comp[u['company']] += u['mw']
companies = [{'company': c, 'mw': round(v)} for c, v in sorted(comp.items(), key=lambda x: -x[1])[:12]]

ci = ci_now['data'][0]['data'][0]
london_now = [{'fuel': m['fuel'].title(), 'share': round(m['perc'] / 100, 4)} for m in ci['generationmix'] if m['perc'] > 0]
london_fw = [{'time': r['from'].replace('Z', ':00Z') if len(r['from']) == 17 else r['from'],
              'intensity': r['intensity']['forecast'], 'index': r['intensity']['index']}
             for r in ci_fw['data']['data']]

out = {'mix_now': mix_now, 'mix_hh': mix_hh, 'prices': prices, 'units_now': units[:30],
       'companies_now': companies, 'london_now': london_now, 'london_forecast': london_fw,
       'snapshot_at': now.strftime('%Y-%m-%dT%H:%M:00Z')}
empty = [k for k, v in out.items() if not v]
if empty:
    sys.exit(f'FAILED: empty sections {empty}')
(HERE / 'units_all.json').write_text(json.dumps(units, separators=(',', ':')), encoding='utf8')  # every running unit, for the where-my-energy map
(HERE / 'grid_snapshot.json').write_text(json.dumps(out, separators=(',', ':')), encoding='utf8')
gas = sum(r['share'] for r in mix_now if r['group'] == 'Gas')
print(f"OK snapshot_at={out['snapshot_at']} SP{sp_now} gas={gas:.0%} units={len(units)} "
      f"last_price={prices[-1]['system_price'] if prices else None} sw9={ci['intensity']['forecast']}")
