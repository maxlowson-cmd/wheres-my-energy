"""Daily Instagram agent: gather post ideas from the live site, pick one, publish it, and learn from how past posts did.

Every number comes from the site's own data feeds; nothing here writes figures. Run by .github/workflows/social.yml.
DRY_RUN=1 renders every idea into out/ and publishes nothing.
"""
import base64, datetime as dt, json, math, os, pathlib, random, time, urllib.error, urllib.parse, urllib.request
from playwright.sync_api import sync_playwright

SITE = 'https://wheresmyenergyfrom.co.uk/'
RELAY = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev'
GRAPH = 'https://graph.facebook.com/v25.0'
IG = '17841480414221894'
UA = 'wheres-my-energy-agent/1.0'
TOKEN, KEY = os.environ.get('INSTAGRAM_TOKEN', ''), os.environ['SOCIAL_KEY']
DRY = os.environ.get('DRY_RUN') == '1'
OUT = pathlib.Path('out')


def http(url, method='GET', data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers={'User-Agent': UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {'raw': raw[:200].decode(errors='replace')}


def relay(op, **body):
    s, d = http(f'{RELAY}/social', 'POST', json.dumps({'op': op, **body}).encode(), {'X-Key': KEY, 'Content-Type': 'text/plain'})
    if s >= 300:
        raise RuntimeError(f'relay {op}: {s} {d}')
    return d


def graph(path, method='GET', **params):
    params['access_token'] = TOKEN
    q = urllib.parse.urlencode(params)
    return http(f'{GRAPH}{path}?{q}', method) if method == 'GET' else http(f'{GRAPH}{path}', method, q.encode(), {'Content-Type': 'application/x-www-form-urlencoded'})


def upload(name, data_url):
    raw = base64.b64decode(data_url.split(',', 1)[1])
    s, d = http(f'{RELAY}/social/image?id={name}', 'POST', raw, {'X-Key': KEY, 'Content-Type': 'image/jpeg'})
    if s >= 300:
        raise RuntimeError(f'image upload: {s} {d}')
    return f'{RELAY}/social/img/{name}.jpg', len(raw)


def score_posts(history):
    """Turn each measured post into 0..1 by rank, so one lucky post cannot dominate."""
    measured = []
    for row in history:
        st = row.get('stats') or {}
        if not st:
            continue
        value = st.get('likes', 0) + 2 * st.get('comments', 0) + 3 * st.get('saved', 0) + 3 * st.get('shares', 0)
        measured.append((value / st['reach'] if st.get('reach') else value, row['type']))
    measured.sort(key=lambda x: x[0])
    by_type = {}
    for i, (_, kind) in enumerate(measured):
        by_type.setdefault(kind, []).append((i + .5) / len(measured))
    return by_type


def choose(ideas, history, today):
    """Half how unusual today is, half what has worked, with enough randomness to keep trying everything."""
    rng = random.Random(today)
    perf = score_posts(history)
    recent = [r['type'] for r in sorted(history, key=lambda r: r['posted'], reverse=True)[:2]]
    table = []
    for idea in ideas:
        got = perf.get(idea['type'], [])
        mean = sum(got) / len(got) if got else .5
        sampled = min(1, max(0, rng.gauss(mean, .35 / math.sqrt(len(got) + 1))))
        total = .5 * idea['novelty'] + .5 * sampled - (.5 if idea['type'] in recent else 0)
        table.append((round(total, 3), idea['id'], round(idea['novelty'], 2), round(mean, 2), len(got)))
    table.sort(reverse=True)
    for row in table:
        print(' ', row)
    return next(i for i in ideas if i['id'] == table[0][1])


def publish(image_url, caption=None, story=False, alt=None):
    params = {'image_url': image_url}
    if story:
        params['media_type'] = 'STORIES'
    else:
        params.update(caption=caption, alt_text=alt or '')
    s, d = graph(f'/{IG}/media', 'POST', **params)
    if s >= 300:
        raise RuntimeError(f'container: {s} {d}')
    box = d['id']
    for _ in range(12):
        s, st = graph(f'/{box}', fields='status_code')
        if st.get('status_code') == 'FINISHED':
            break
        if st.get('status_code') in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'container status: {st}')
        time.sleep(10)
    s, d = graph(f'/{IG}/media_publish', 'POST', creation_id=box)
    if s >= 300:
        raise RuntimeError(f'publish: {s} {d}')
    return d['id']


def refresh_stats(history):
    """Read how recent posts did. Likes and comments always work; reach, saves and shares need the insights permission."""
    now = time.time()
    for row in history:
        age = now - row['posted'] / 1000
        if age < 86400 or age > 30 * 86400:
            continue
        s, d = graph(f"/{row['media_id']}", fields='like_count,comments_count')
        if s >= 300:
            continue
        stats = {'likes': d.get('like_count', 0), 'comments': d.get('comments_count', 0)}
        s, ins = graph(f"/{row['media_id']}/insights", metric='reach,saved,shares')
        if s < 300:
            stats.update({m['name']: m['values'][0]['value'] for m in ins.get('data', [])})
        relay('stats', media_id=row['media_id'], stats=stats)
        row['stats'] = stats


def weekly(history):
    week = [r for r in history if time.time() - r['posted'] / 1000 < 7 * 86400 and r.get('stats')]
    if not week:
        return
    best = max(week, key=lambda r: r['stats'].get('likes', 0) + 2 * r['stats'].get('comments', 0))
    relay('telegram', text=f"Instagram this week: {len(week)} posts measured, {sum(r['stats'].get('likes', 0) for r in week)} likes, {sum(r['stats'].get('comments', 0) for r in week)} comments, {sum(r['stats'].get('reach', 0) for r in week)} reach.\nBest: {best['type']} ({best['stats'].get('likes', 0)} likes).")


def main():
    today = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    history = relay('history').get('posts', [])
    if not DRY:
        refresh_stats(history)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1080, 'height': 1400})
        page.goto(f'{SITE}?agent={int(time.time())}', wait_until='load', timeout=120000)
        page.wait_for_function('window.WMESocial && document.fonts.status === "loaded"', timeout=60000)
        ideas = page.evaluate('WMESocial.candidates()')
        print('ideas', [(i['id'], round(i['novelty'], 2)) for i in ideas])
        if not ideas:
            if not DRY:
                relay('telegram', text='Instagram agent skipped today: the site data is too old to post.')
            return
        pick = choose(ideas, history, today)
        print('pick', pick['id'])
        if DRY:
            OUT.mkdir(exist_ok=True)
            for idea in ideas:
                for fmt in ('feed', 'story'):
                    data = page.evaluate('([a, b]) => WMESocial.image(a, b)', [idea['id'], fmt])
                    (OUT / f"{idea['id']}_{fmt}.jpg").write_bytes(base64.b64decode(data.split(',', 1)[1]))
            (OUT / 'ideas.json').write_text(json.dumps({'pick': pick['id'], 'ideas': ideas}, indent=1), encoding='utf8')
            return
        if any(r['day'] == today for r in history):
            print('already posted today')
            return
        feed = page.evaluate('([a, b]) => WMESocial.image(a, b)', [pick['id'], 'feed'])
        story = page.evaluate('([a, b]) => WMESocial.image(a, b)', [pick['id'], 'story'])
        browser.close()
    url, size = upload(f'{today}-feed', feed)
    print('feed bytes', size)
    media = publish(url, caption=pick['caption'], alt=pick['alt'])
    relay('log', media_id=media, day=today, type=pick['type'], caption=pick['caption'], novelty=pick['novelty'])
    try:
        story_url, _ = upload(f'{today}-story', story)
        publish(story_url, story=True)
    except Exception as e:
        relay('telegram', text=f'Instagram story failed, the feed post went out: {str(e)[:300]}')
    if dt.datetime.now(dt.timezone.utc).weekday() == 6:
        weekly(history)
    print('posted', media)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        try:
            relay('telegram', text=f'Instagram agent failed: {str(e)[:500]}')
        finally:
            raise
