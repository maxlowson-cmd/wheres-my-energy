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
    dash_ping.telegram("Numbers dashboard: site counter didn't answer. Ask Claude.")
    raise
try:  # Google's figures are a bonus: if they fail, the rest still updates, and Telegram says Google wasn't read
    import google_feed
    rows += google_feed.rows()
    google = 'google ok'
except Exception as e:
    google = f'google FAILED ({type(e).__name__})'
    dash_ping.telegram("Numbers dashboard updated, but Google figures failed.")
pathlib.Path(sys.argv[1]).write_text(json.dumps(rows, separators=(',', ':')), encoding='utf8')
summary = next(r for r in rows if r['table'] == 'summary')
try:  # tells the 11:30 watchdog (.github/workflows/dash_watch.yml) the morning figures were fetched and saved
    dash_ping.stamp()
except Exception as e:
    print('stamp failed', type(e).__name__)
print('saved', len(rows), 'rows; followers', summary['followers'], '; counting since', summary['counting_since'], ';', google)
