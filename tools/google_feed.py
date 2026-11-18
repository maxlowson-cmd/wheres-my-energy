"""Google Search Console figures for the private dashboard, read-only, with the service-account key kept outside the code folder
(Claude/wme-search-console.json). Never prints the key. Used by dashboard_feed.py; run alone to test: python google_feed.py"""
import datetime as dt, json, pathlib, re, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
KEY = HERE.parent.parent / 'wme-search-console.json'
SITE = 'sc-domain:wheresmyenergyfrom.co.uk'
API = 'https://www.googleapis.com/webmasters/v3/sites/' + urllib.parse.quote(SITE, safe='')
HOME = 'https://wheresmyenergyfrom.co.uk/'


def token():
    from google.oauth2 import service_account
    import google.auth.transport.requests as transport
    creds = service_account.Credentials.from_service_account_file(str(KEY), scopes=['https://www.googleapis.com/auth/webmasters.readonly'])
    creds.refresh(transport.Request())
    return creds.token


def call(auth, url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method='POST' if body is not None else 'GET',
                                 headers={'Authorization': f'Bearer {auth}', 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=60))


def page_name(url):
    path = url.replace(HOME, '/').split('?')[0]
    found = re.match(r'/area/([a-z0-9-]+)/$', path)
    return {'/': 'Home page', '/area/': 'All areas', '/method.html': 'How it works'}.get(path) or (found[1].replace('-', ' ').title() + ' area page' if found else path)


def rows():
    """Dashboard rows: search clicks and showings by day, top searches, top pages, and how many of the sitemap's pages Google has added."""
    auth = token()
    end = dt.date.today()
    start = end - dt.timedelta(days=30)
    query = lambda dims, limit: call(auth, API + '/searchAnalytics/query', {'startDate': str(start), 'endDate': str(end), 'dimensions': dims, 'rowLimit': limit}).get('rows', [])
    out = [{'table': 'google_daily', 'day': r['keys'][0], 'clicks': r['clicks'], 'shown': r['impressions'], 'position': round(r['position'], 1)} for r in query(['date'], 40)]
    out += [{'table': 'google_query', 'query': r['keys'][0], 'clicks': r['clicks'], 'shown': r['impressions']} for r in query(['query'], 10)]
    out += [{'table': 'google_page', 'page': page_name(r['keys'][0]), 'clicks': r['clicks'], 'shown': r['impressions']} for r in query(['page'], 10)]
    maps = call(auth, API + '/sitemaps').get('sitemap', [])
    listed = sum(int(c.get('submitted', 0)) for m in maps for c in m.get('contents', []))
    # which sitemap pages Google has added to search: one URL inspection each (the daily allowance is 2,000)
    urls = re.findall(r'<loc>(.*?)</loc>', urllib.request.urlopen(HOME + 'sitemap.xml', timeout=60).read().decode('utf8'))
    def on_google(u):
        try:
            got = call(auth, 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect', {'inspectionUrl': u, 'siteUrl': SITE})
            return got.get('inspectionResult', {}).get('indexStatusResult', {}).get('verdict') == 'PASS'
        except (urllib.error.URLError, TimeoutError):
            return False  # over the allowance or slow: counted as not yet added
    with ThreadPoolExecutor(8) as pool:
        added = sum(pool.map(on_google, urls))
    out.append({'table': 'google_summary', 'pages_listed': listed or len(urls), 'pages_checked': len(urls), 'pages_on_google': added,
                'sitemap_read': (maps[0].get('lastDownloaded') if maps else None), 'data_to': max((r['day'] for r in out if r['table'] == 'google_daily'), default=None)})
    return out


if __name__ == '__main__':
    got = rows()
    s = next(r for r in got if r['table'] == 'google_summary')
    print('google rows', len(got), '; days', sum(r['table'] == 'google_daily' for r in got), '; pages on Google', s['pages_on_google'], 'of', s['pages_checked'])
