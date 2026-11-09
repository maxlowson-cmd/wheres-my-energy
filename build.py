"""Fetch the 48-hour regional carbon forecast plus GB grid data, and write index.html from template.html + lookup.json."""
import json, pathlib, shutil, subprocess, sys, urllib.request, datetime as dt, collections

HERE = pathlib.Path(__file__).resolve().parent
FUELS = ['gas', 'wind', 'nuclear', 'imports', 'biomass', 'solar', 'hydro', 'coal', 'other']

# 1. regional forecast and fuel mix, per half hour
now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)


def last_sunday(year, month):
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def uk_offset(t):
    start = dt.datetime.combine(last_sunday(t.year, 3), dt.time(1), dt.timezone.utc)
    end = dt.datetime.combine(last_sunday(t.year, 10), dt.time(1), dt.timezone.utc)
    return dt.timedelta(hours=1) if start <= t < end else dt.timedelta(0)


today_uk = (now + uk_offset(now)).date()
def uk_midnight(day):
    guess = dt.datetime.combine(day, dt.time(0), dt.timezone.utc)
    return guess - uk_offset(guess - dt.timedelta(hours=2))


midnight = uk_midnight(today_uk)
yesterday = uk_midnight(today_uk - dt.timedelta(days=1))
url = f'https://api.carbonintensity.org.uk/regional/intensity/{midnight:%Y-%m-%dT%H:%MZ}/fw48h'
req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'when-to-run/1.0'})
with urllib.request.urlopen(req, timeout=60) as r:
    rows = [x for x in json.load(r)['data'] if x['from'] >= midnight.strftime('%Y-%m-%dT%H:%MZ')]
regions = {i: [] for i in range(1, 15)}
mix = {i: [] for i in [*range(1, 15), 18]}  # 18 is the whole of Great Britain
for row in rows:
    for reg in row['regions']:
        i = reg['regionid']
        if i in regions:
            regions[i].append(reg['intensity']['forecast'])
        if i in mix:
            perc = {m['fuel']: m['perc'] for m in reg['generationmix']}
            mix[i].append([round(perc.get(f, 0)) for f in FUELS])

# 2. GB-wide stations, imports and prices, from the dashboard's refresh script
subprocess.run([sys.executable, str(HERE / 'refresh.py')], check=True, stdout=subprocess.DEVNULL)
grid = json.loads((HERE / 'grid_snapshot.json').read_text(encoding='utf8'))
imports = collections.Counter()
for m in grid['mix_now']:
    if m['group'] == 'Imports' and m['mw'] > 0:
        imports[m['fuel'].split(' (')[0]] += m['mw']
top_import = imports.most_common(1)[0][0] if imports else None
B = 'https://data.elexon.co.uk/bmrs/api/v1'
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/1.0'}), timeout=60) as r:
        return json.load(r)['data']
system = {x['startTime']: float(x['systemSellPrice']) for day in (today_uk - dt.timedelta(days=1), today_uk) for x in get(f'{B}/balancing/settlement/system-prices/{day}?format=json')}
market = {x['startTime']: x['price'] for x in get(f"{B}/datasets/MID?from={yesterday:%Y-%m-%dT%H:%MZ}&to={now:%Y-%m-%dT%H:%MZ}&format=json") if x['dataProvider'] == 'APXMIDP' and x['price']}
first = yesterday.strftime('%Y-%m-%dT%H:%M:00Z')
prices = [{'t': t, 'p': round(market.get(t, system[t]), 2)} for t in sorted(system) if t >= first]

snapshot = {'taken': now.strftime('%Y-%m-%dT%H:%M:00Z'), 'start': rows[0]['from'], 'regions': regions, 'mix': mix, 'fuels': FUELS,
            'topImport': top_import, 'prices': prices, 'year': json.loads((HERE / 'year.json').read_text(encoding='utf8'))}

lookup = json.loads((HERE / 'lookup.json').read_text())
lookup['areas'].update({'EC': 13, 'WC': 13})  # central London; the API only accepts these with a letter suffix (EC1A)

subprocess.run([sys.executable, '-I', str(HERE / 'model.py')], check=True, stdout=subprocess.DEVNULL)
subprocess.run([sys.executable, '-I', str(HERE / 'regions.py')], check=True, stdout=subprocess.DEVNULL)
m = json.loads((HERE / 'map.json').read_text(encoding='utf8'))
subprocess.run([sys.executable, '-I', str(HERE / 'member_data.py')], check=True, stdout=subprocess.DEVNULL)
subprocess.run([sys.executable, '-I', str(HERE / 'gas_data.py')], check=True, stdout=subprocess.DEVNULL)

page = (HERE / 'template.html').read_text(encoding='utf8')
for key in ('fuels', 'all'):
    page = page.replace('<!--MAP_%s-->' % key.upper(), m[key])
page = page.replace('<!--REGIONS_SVG-->', (HERE / 'regions.svg').read_text(encoding='utf8'))
page = page.replace('/*GEO*/null/*END*/', json.dumps(m['geo'], separators=(',', ':')))
page = page.replace('/*SNAPSHOT*/null/*END*/', json.dumps(snapshot, separators=(',', ':')))
page = page.replace('/*LOOKUP*/null/*END*/', json.dumps(lookup, separators=(',', ':')))
page = page.replace('/*MEMBER*/null/*END*/', (HERE / 'member.json').read_text(encoding='utf8'))
page = page.replace('/*GAS*/null/*END*/', (HERE / 'gas.json').read_text(encoding='utf8'))
config = json.loads((HERE / 'site_config.json').read_text(encoding='utf8'))
page = page.replace("/*API*/''/*END*/", json.dumps(config['api'].rstrip('/')))
(HERE / 'index.html').write_text(page, encoding='utf8')

# the public website: a complete document (index.html above is the same page without its <head>)
TITLE = "Where's My Energy From?"
DESCRIPTION = "Type your address to see where your electricity is likely coming from right now, and the greenest hours to use it."
ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='16' fill='%2306704b'/%3E%3Cpath d='M18 5 9 18h6l-1 9 9-13h-6z' fill='%23f2fbf7'/%3E%3C/svg%3E"
split = page.index('</style>') + len('</style>')
head, body = page[:split], page[split:]
head = head.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', '').replace('<meta charset="utf-8">\n', '')
head = head.replace(f'<title>{TITLE}</title>\n', '')
beacon = ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{"token": "%s"}\'></script>' % config['beacon']) if config['beacon'] else ''
document = f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{TITLE}</title>
<meta name="description" content="{DESCRIPTION}">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:type" content="website">
<meta property="og:image" content="https://wheresmyenergyfrom.co.uk/share.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{ICON}">
<style>:root{{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0}}img{{max-width:100%}}</style>
{head}
</head>
<body>
{body}
{beacon}
</body>
</html>
"""
(HERE / 'site').mkdir(exist_ok=True)
(HERE / 'site' / 'index.html').write_text(document, encoding='utf8')
for extra in (HERE / 'pages').glob('*.html'):
    shutil.copy(extra, HERE / 'site' / extra.name)
shutil.copy(HERE / 'brand' / 'share_preview.png', HERE / 'site' / 'share.png')
print('OK', snapshot['taken'], 'slots', len(rows), 'bytes', len(page.encode('utf8')), 'top import', top_import)
