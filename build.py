"""Fetch the 48-hour regional carbon forecast plus GB grid data, and write index.html from template.html + lookup.json."""
from html import escape as esc_html
import json, pathlib, shutil, subprocess, sys, time, urllib.error, urllib.request, datetime as dt, collections

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
def fetch(req):
    """Open a URL, retrying one-off server errors and timeouts rather than failing the whole build."""
    for attempt in range(4):
        try:
            return urllib.request.urlopen(req, timeout=60)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3 or (isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429):
                raise
            time.sleep(5 * (attempt + 1))


url = f'https://api.carbonintensity.org.uk/regional/intensity/{midnight:%Y-%m-%dT%H:%MZ}/fw48h'
req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'when-to-run/1.0'})
with fetch(req) as r:
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
    with fetch(urllib.request.Request(u, headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/1.0'})) as r:
        return json.load(r)['data']
system = {x['startTime']: float(x['systemSellPrice']) for day in (today_uk - dt.timedelta(days=1), today_uk) for x in get(f'{B}/balancing/settlement/system-prices/{day}?format=json')}
market = {x['startTime']: x['price'] for x in get(f"{B}/datasets/MID?from={yesterday:%Y-%m-%dT%H:%MZ}&to={now:%Y-%m-%dT%H:%MZ}&format=json") if x['dataProvider'] == 'APXMIDP' and x['price']}
first = yesterday.strftime('%Y-%m-%dT%H:%M:00Z')
prices = [{'t': t, 'p': round(market.get(t, system[t]), 2)} for t in sorted(system) if t >= first]

snapshot = {'taken': now.strftime('%Y-%m-%dT%H:%M:00Z'), 'start': rows[0]['from'], 'regions': regions, 'mix': mix, 'fuels': FUELS,
            'topImport': top_import, 'prices': prices, 'year': json.loads((HERE / 'year.json').read_text(encoding='utf8')),
            'world': json.loads((HERE / 'social' / 'world.json').read_text(encoding='utf8'))}  # Britain and the world, refreshed by tools/fetch_world.py

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
page = page.replace('/*FACTS*/[]/*END*/', json.dumps(json.loads((HERE / 'facts.json').read_text(encoding='utf8')), separators=(',', ':')))
page = page.replace('/*ALERTS*/false/*END*/', 'true' if config.get('alerts') else 'false')
(HERE / 'index.html').write_text(page, encoding='utf8')

# the public website: a complete document (index.html above is the same page without its <head>)
TITLE = "Where's My Energy From?"
DESCRIPTION = "Type your postcode to see what's powering your area right now, where your gas came from, and the cleanest time to run the washing. Free, across Great Britain."
SEARCH_TITLE = "Where's My Energy From? What's powering your postcode right now"  # the line a search result shows; shares keep the plain name
SITE = 'https://wheresmyenergyfrom.co.uk/'
# the icon as real files, linked from every page: search engines only show an icon they can download
ICONS = '<link rel="icon" href="/favicon.ico" sizes="48x48">\n<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n<link rel="icon" href="/icon-192.png" type="image/png" sizes="192x192">\n<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
# tells search engines the site's name (shown above the result instead of the bare address), its logo and its Instagram
SCHEMA = json.dumps({'@context': 'https://schema.org', '@graph': [
    {'@type': 'WebSite', '@id': SITE + '#website', 'name': TITLE, 'alternateName': ['Wheres My Energy From', 'wheresmyenergyfrom.co.uk'], 'url': SITE},
    {'@type': 'Organization', '@id': SITE + '#org', 'name': TITLE, 'url': SITE, 'logo': SITE + 'icon-512.png', 'sameAs': ['https://www.instagram.com/wheresmyenergyfrom/']},
    {'@type': 'WebApplication', 'name': TITLE, 'url': SITE, 'applicationCategory': 'UtilitiesApplication', 'operatingSystem': 'Any', 'areaServed': 'GB', 'isAccessibleForFree': True,
     'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'GBP'}, 'publisher': {'@id': SITE + '#org'}}]}, ensure_ascii=False).replace('</', '<\\/')
ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='16' fill='%2306704b'/%3E%3Cpath d='M18 5 9 18h6l-1 9 9-13h-6z' fill='%23f2fbf7'/%3E%3C/svg%3E"
split = page.index('</style>') + len('</style>')
head, body = page[:split], page[split:]
head = head.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', '').replace('<meta charset="utf-8">\n', '')
head = head.replace(f'<title>{TITLE}</title>\n', '')
beacon = '<script defer src="hit.js" data-page="home"></script>'
document = f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{SEARCH_TITLE}</title>
<meta name="description" content="{DESCRIPTION}">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{TITLE}">
<meta property="og:locale" content="en_GB">
<meta property="og:url" content="https://wheresmyenergyfrom.co.uk/">
<link rel="canonical" href="https://wheresmyenergyfrom.co.uk/">
<meta name="theme-color" content="#06704b">
<meta property="og:image" content="https://wheresmyenergyfrom.co.uk/share.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
{ICONS}
<script type="application/ld+json">{SCHEMA}</script>
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
    (HERE / 'site' / extra.name).write_text(extra.read_text(encoding='utf8').replace('</title>\n', '</title>\n' + ICONS + '\n', 1), encoding='utf8')
for icon in ('favicon.ico', 'favicon.svg', 'icon-192.png', 'icon-512.png'):
    shutil.copy(HERE / 'brand' / icon, HERE / 'site' / icon)
shutil.copy(HERE / 'brand' / 'share_preview.png', HERE / 'site' / 'share.png')
shutil.copy(HERE / 'gas_net.json', HERE / 'site' / 'gas_net.json')
shutil.copy(HERE / 'pages' / 'hit.js', HERE / 'site' / 'hit.js')
shutil.copy(HERE / 'brand' / 'apple_touch_icon.png', HERE / 'site' / 'apple-touch-icon.png')  # the icon a phone shows when the site is added to the home screen
# a page for every postcode area, written as plain text so search engines can read each area's answer
import places
AREA_PAGES = places.build(snapshot, m['geo'], lookup, HERE / 'site', ICONS, json.loads((HERE / 'social' / 'facts.json').read_text(encoding='utf8')))
# let search engines find every page
PAGES = ['', 'method.html', 'privacy.html', 'credits.html'] + AREA_PAGES
(HERE / 'site' / 'robots.txt').write_text('User-agent: *\nAllow: /\n\nSitemap: https://wheresmyenergyfrom.co.uk/sitemap.xml\n', encoding='utf8')
(HERE / 'site' / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + ''.join(f'  <url><loc>https://wheresmyenergyfrom.co.uk/{p}</loc><lastmod>{snapshot["taken"][:10]}</lastmod></url>\n' for p in PAGES) + '</urlset>\n', encoding='utf8')
credit_rows = '\n'.join(f'''  <li><strong>{esc_html(p['place'])}</strong>: <a href="{esc_html(p['source'])}">{esc_html(p['title'])}</a> by {esc_html(p['artist'])}, <a href="{esc_html(p['license_url'] or p['source'])}">{esc_html(p['license'])}</a></li>''' for p in sorted(json.loads((HERE / 'social' / 'photos.json').read_text(encoding='utf8')), key=lambda p: p['place']))
credits_page = (HERE / 'pages' / 'method.html').read_text(encoding='utf8')
credits_page = credits_page[:credits_page.index('<main>')] + f'''<main>
  <a href="./">&#8592; Back to the site</a>
  <h1>Photo credits</h1>
  <p>The photos on our Instagram posts come from Wikimedia Commons, and we're grateful to the photographers who share them. We crop each one and add words on top. Our edited versions of the CC BY-SA photos are shared under the same licence as the original. The photos show real sites, but they don't mean your power came from that place.</p>
  <ul>
{credit_rows}
  </ul>
</main>
</body>
</html>
'''
(HERE / 'site' / 'credits.html').write_text(credits_page.replace("How it works | Where's My Energy From?", "Photo credits | Where's My Energy From?").replace('</title>', '</title>\n' + ICONS, 1), encoding='utf8')
print('OK', snapshot['taken'], 'slots', len(rows), 'bytes', len(page.encode('utf8')), 'top import', top_import)
