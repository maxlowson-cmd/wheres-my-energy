"""Save the private dashboard's numbers to a local file. The key stays in wme-stats-url.txt and is never printed.

Usage: python dashboard_feed.py <output.json>
"""
import json, pathlib, re, sys, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
link = re.search(r'https://\S+', (HERE.parent.parent / 'wme-stats-url.txt').read_text(encoding='utf8', errors='ignore')).group(0)
key = re.search(r'[?&]key=([^&\s]+)', link).group(1)
base = link.split('/stats')[0]
request = urllib.request.Request(f'{base}/dashboard?key={key}', headers={'User-Agent': 'wme-dashboard/1.0'})
import dash_ping
try:
    rows = json.load(urllib.request.urlopen(request, timeout=60))
except Exception as e:
    dash_ping.telegram(f"The numbers dashboard couldn't update this morning: the site's counter didn't answer ({type(e).__name__}). It shows yesterday's figures. Ask Claude to look.")
    raise
try:  # Google's figures are a bonus: if they fail, the rest still updates, and Telegram says Google wasn't read
    import google_feed
    rows += google_feed.rows()
    google = 'google ok'
except Exception as e:
    google = f'google FAILED ({type(e).__name__})'
    dash_ping.telegram(f"The numbers dashboard updated, but Google's search figures couldn't be read ({type(e).__name__}: {str(e)[:150]}). The rest is fine. Ask Claude to look.")
pathlib.Path(sys.argv[1]).write_text(json.dumps(rows, separators=(',', ':')), encoding='utf8')
summary = next(r for r in rows if r['table'] == 'summary')
print('saved', len(rows), 'rows; followers', summary['followers'], '; counting since', summary['counting_since'], ';', google)
