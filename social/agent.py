"""Daily Instagram agent: gather post ideas from the live site, pick one, publish it, and learn from how past posts did.

Every number comes from the site's own data feeds; nothing here writes figures. Run by .github/workflows/social.yml.
DRY_RUN=1 renders every idea into out/ and publishes nothing.
"""
from zoneinfo import ZoneInfo
import base64, datetime as dt, json, math, os, pathlib, random, re, time, urllib.error, urllib.parse, urllib.request
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import extras
from playwright.sync_api import sync_playwright

SITE = 'https://wheresmyenergyfrom.co.uk/'
RELAY = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev'
GRAPH = 'https://graph.facebook.com/v25.0'
IG = '17841480414221894'
UA = 'wheres-my-energy-agent/1.0'
TOKEN, KEY = os.environ.get('INSTAGRAM_TOKEN', ''), os.environ['SOCIAL_KEY']
DRY = os.environ.get('DRY_RUN') == '1'
OUT = pathlib.Path('out')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANGLES = ('guess', 'everyday', 'rivalry', 'surprise', 'question')


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
        for part in row['type'].split('|'):
            measured.append((value / st['reach'] if st.get('reach') else value, part))
    measured.sort(key=lambda x: x[0])
    by_type = {}
    for i, (_, kind) in enumerate(measured):
        by_type.setdefault(kind, []).append((i + .5) / len(measured))
    return by_type


def category_of(kind):
    lead = kind.split('|')[0]
    return 'explain' if lead == 'explainer' else 'new' if lead == 'new-site' else 'history' if lead in ('on-this-day', 'growth') else 'fact' if lead == 'fact' else 'now'


def explainer_due(history):
    """Every fourth post explains how the site works, so people understand and trust it."""
    ordered = sorted(history, key=lambda r: r['posted'], reverse=True)
    since = next((i for i, r in enumerate(ordered) if r['type'].startswith('explainer')), len(ordered))
    return len(ordered) >= 3 and since >= 3


def next_explainer(history):
    items = json.loads((pathlib.Path(__file__).resolve().parent / 'explainers.json').read_text(encoding='utf8'))
    done = sum(1 for r in history if r['type'].startswith('explainer'))
    return items[done % len(items)], done % len(items)


def choose(ideas, history, today):
    """Half how unusual today is, half what has worked, with enough randomness to keep trying everything."""
    rng = random.Random(today)
    perf = score_posts(history)
    ordered = sorted(history, key=lambda r: r['posted'], reverse=True)
    recent = [r['type'].split('|')[0] for r in ordered[:2]]
    last_cat = category_of(ordered[0]['type']) if ordered else None
    table = []
    for idea in ideas:
        got = perf.get(idea['type'], [])
        mean = sum(got) / len(got) if got else .5
        sampled = min(1, max(0, rng.gauss(mean, .35 / math.sqrt(len(got) + 1))))
        total = .5 * idea['novelty'] + .5 * sampled - (.5 if idea['type'] in recent else 0) - (.3 if idea['cat'] == last_cat else 0)
        table.append((round(total, 3), idea['id'], round(idea['novelty'], 2), round(mean, 2), len(got)))
    table.sort(reverse=True)
    for row in table:
        print(' ', row)
    return next(i for i in ideas if i['id'] == table[0][1])


def pick_angle(history, today):
    rng = random.Random(today + 'angle')
    perf = score_posts(history)
    def draw(name):
        got = perf.get(name, [])
        return rng.gauss(sum(got) / len(got) if got else .5, .35 / math.sqrt(len(got) + 1))
    return max(ANGLES, key=draw)


def moment_today(d):
    """Dates the wording may refer to. Anything not listed here is off limits, so it cannot invent an occasion."""
    last_sunday = lambda month: max(dt.date(d.year, month, day) for day in range(25, 32) if dt.date(d.year, month, day).weekday() == 6)
    fixed = {(1, 1): "New Year's Day", (1, 25): 'Burns Night', (2, 14): "Valentine's Day", (4, 23): "St George's Day", (6, 21): 'the longest day of the year', (10, 31): 'Halloween', (11, 5): 'Bonfire Night', (12, 21): 'the shortest day of the year', (12, 24): 'Christmas Eve', (12, 25): 'Christmas Day', (12, 26): 'Boxing Day', (12, 31): "New Year's Eve", (3, 1): "St David's Day", (3, 17): "St Patrick's Day", (11, 30): "St Andrew's Day"}
    if d == last_sunday(3):
        return 'the day the clocks go forward'
    if d == last_sunday(10):
        return 'the day the clocks go back'
    return fixed.get((d.month, d.day))


VOICE = """You write daily Instagram posts for Where's My Energy From?, a free British site that shows people where their electricity and gas come from.

Your job is to make someone stop scrolling and think "huh, that's interesting, I want to know more". Stats alone are boring. Find the human angle in today's figures: what it means for their washing, their car, their kettle, their part of the country, or their day.

Voice: warm, curious, a bit playful, plain British English. Talk to "you". Short sentences. No jargon, no hype, no exclamation-mark enthusiasm, at most one emoji in the caption and none on the slides. Never preachy: nobody gets told off for using electricity. No politics, no blaming companies or governments, and no knocking the people of any region.

Truth rules, which matter more than being catchy:
- Use only numbers that appear in the data you are given, exactly as given. Don't calculate new figures or round them differently. Loose words like "about a third" or "nearly three times" are fine where the data clearly supports them.
- The data shows what is happening, not why. Don't claim a cause unless the data shows it: no storms, weather events, records, outages, news or price changes for customers. It is fair to say that with little wind, gas is doing more of the work.
- Mention an occasion only if the data names one under "occasion_today".
- The on-this-day slide uses metered main-grid figures, which differ from the wider "right now" mix. Never give both figures for the same fuel in one post, and call the on-this-day figure "on the main grid".
- The figures are forecasts and estimates, so say "right now" or "around" rather than sounding exact to the kilowatt.

Slides: an album is a little story, one thought per slide, each making you want the next. The opening slide is a hook that opens a question and doesn't give the answer away. The closing slide brings it back to the reader. Keep to the character limit given for each slide. A slide's text sits beside the chart or map it describes, so it must match that slide's figures.

Angles:
- guess: ask the reader to guess something, with the answer on the next swipe or later in the caption.
- everyday: translate it into a real household moment.
- rivalry: friendly comparison between places.
- surprise: lead with the most counter-intuitive thing in the data.
- question: ask something the reader has never thought to ask.

Write the caption as a short story of two or three short paragraphs, ending with a question people would want to answer. Don't include links or hashtags, as those are added afterwards."""

PLAN_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['hook_kicker', 'hook', 'slides', 'closing', 'caption', 'alt'], 'properties': {
    'hook_kicker': {'type': 'string'}, 'hook': {'type': 'string'},
    'slides': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'text'], 'properties': {'id': {'type': 'string'}, 'text': {'type': 'string'}}}},
    'closing': {'type': 'string'}, 'caption': {'type': 'string'}, 'alt': {'type': 'string'}}}
NUMBER = re.compile(r'\d+(?:[.:,]\d+)*')
BANNED = re.compile(r'\b(storms?|record|records|record-breaking|ever|blackouts?|outages?|heatwave|government|ministers?|bills? (?:will|are going))\b', re.I)


def allowed_numbers(sheet, ideas):
    text = json.dumps(sheet) + ' '.join(i['shows'] for i in ideas)
    return {n.strip('.,:').replace(',', '') for n in NUMBER.findall(text)} | {'24', '12'}


def check_plan(plan, ideas, sheet, album):
    """Returns the problems found. The model's wording only goes out if this comes back empty."""
    problems = []
    by_id = {i['id']: i for i in ideas}
    allowed = allowed_numbers(sheet, ideas)
    fields = [plan['caption'], plan['alt']]
    for s in plan['slides']:
        if s['id'] not in by_id:
            problems.append(f"unknown slide id {s['id']}")
        elif by_id[s['id']]['art'] != 'fact' and len(s['text']) > by_id[s['id']]['limit']:
            problems.append(f"slide {s['id']} is over {by_id[s['id']]['limit']} characters")
        fields.append(s['text'])
    if album:
        fields += [plan['hook'], plan['hook_kicker'], plan['closing']]
        if not 3 <= len(plan['slides']) <= 6:
            problems.append('an album needs 3 to 6 chart slides')
        if len(plan['hook']) > 90 or len(plan['closing']) > 140 or len(plan['hook_kicker']) > 28:
            problems.append('hook, kicker or closing is too long')
        if len({s['id'] for s in plan['slides']}) != len(plan['slides']):
            problems.append('a slide is used twice')
        ids = {s['id'] for s in plan['slides']}
        if 'on-this-day' in ids and any(x.startswith('fuel-') for x in ids):
            problems.append('on-this-day uses main-grid figures, so it cannot share an album with a fuel-mix slide')
    elif len(plan['slides']) != 1:
        problems.append('a single post needs exactly one slide')
    if len(plan['caption']) > 1800:
        problems.append('caption too long')
    for text in fields:
        for n in NUMBER.findall(text):
            if n.strip('.,:').replace(',', '') not in allowed:
                problems.append(f'number not in the data: {n}')
        hit = BANNED.search(text)
        if hit:
            problems.append(f'banned claim word: {hit.group(0)}')
    return problems


def write_plan(lead, ideas, sheet, angle, album, recent, today):
    if not ANTHROPIC_KEY:
        return None
    import anthropic
    client = anthropic.Anthropic()
    brief = {'data': {**sheet, 'occasion_today': moment_today(today)}, 'format': 'album' if album else 'single image', 'angle_to_use': angle, 'lead_slide_id': lead['id'],
             'available_slides': [{'id': i['id'], 'shows': i['shows'], 'character_limit': i['limit'], 'interest_score': round(i['novelty'], 2)} for i in ideas],
             'instructions': ('Write 3 to 6 chart slides in story order, starting from the lead slide if it suits the story, plus the hook and closing. Hook at most 90 characters, kicker at most 28, closing at most 140. The fact slide cannot be reworded.' if album else 'Write exactly one slide: the lead slide. Leave hook, hook_kicker and closing as empty strings.'),
             'recent_captions_to_avoid_repeating': recent}
    messages = [{'role': 'user', 'content': json.dumps(brief, ensure_ascii=False)}]
    for attempt in range(2):
        response = client.beta.messages.create(model='claude-opus-5-5', max_tokens=16000, system=VOICE, messages=messages, betas=['server-side-fallback-2026-07-01'], fallbacks='default', output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': PLAN_SCHEMA}})
        if response.stop_reason in ('refusal', 'max_tokens'):
            print('no usable wording:', response.stop_reason)
            return None
        text = next(b.text for b in response.content if b.type == 'text')
        plan = json.loads(text)
        problems = check_plan(plan, ideas, sheet, album)
        print('wording check', attempt, problems or 'passed')
        if not problems:
            return plan
        messages += [{'role': 'assistant', 'content': text}, {'role': 'user', 'content': 'Please fix these and return the whole post again: ' + '; '.join(problems)}]
    return None


def publish_album(urls, caption):
    kids = []
    for url in urls:
        s, d = graph(f'/{IG}/media', 'POST', image_url=url, is_carousel_item='true')
        if s >= 300:
            raise RuntimeError(f'album item: {s} {d}')
        wait_ready(d['id'])
        kids.append(d['id'])
    s, d = graph(f'/{IG}/media', 'POST', media_type='CAROUSEL', children=','.join(kids), caption=caption)
    if s >= 300:
        raise RuntimeError(f'album: {s} {d}')
    wait_ready(d['id'])
    s, d = graph(f'/{IG}/media_publish', 'POST', creation_id=d['id'])
    if s >= 300:
        raise RuntimeError(f'album publish: {s} {d}')
    return d['id']


def wait_ready(box):
    for _ in range(18):
        s, st = graph(f'/{box}', fields='status_code')
        if st.get('status_code') == 'FINISHED':
            return
        if st.get('status_code') in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'container status: {st}')
        time.sleep(10)
    raise RuntimeError('container never became ready')


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
    wait_ready(box)
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
        if ideas:
            signoff = page.evaluate('WMESocial.signoff')
            uk = dt.datetime.now(ZoneInfo('Europe/London'))
            more = extras.build(uk, [r.get('caption', '') for r in history])
            page.evaluate('(x) => WMESocial.addExtras(x)', more)
            for x in more:
                x['caption'] += signoff
                x.pop('spec')
            ideas += more
        print('ideas', [(i['id'], round(i['novelty'], 2)) for i in ideas])
        if not ideas:
            if not DRY:
                relay('telegram', text='Instagram agent skipped today: the site data is too old to post.')
            return
        pick = choose(ideas, history, today)
        print('pick', pick['id'])
        sheet = page.evaluate('WMESocial.facts()')
        signoff = page.evaluate('WMESocial.signoff')
        day = dt.date.fromisoformat(today)
        album = pick['novelty'] >= .8 or day.weekday() in (1, 3, 6)
        angle = pick_angle(history, today)
        print('format', 'album' if album else 'single', 'angle', angle)
        plan = None if explainer_due(history) or os.environ.get('MOCK_ALBUM') == 'explain' else write_plan(pick, ideas, sheet, angle, album, [r.get('caption', '')[:200] for r in history[:7]], day)
        if plan is None and DRY and os.environ.get('MOCK_ALBUM') == '1':
            lead = [pick['id']] + [i['id'] for i in ideas if i['id'] != pick['id'] and i['type'] != 'fact'][:3]
            plan = {'hook_kicker': 'TEST KICKER', 'hook': 'Test hook: this slide opens the story without giving it away.', 'slides': [{'id': x, 'text': 'Test wording for this slide.'} for x in lead], 'closing': 'Test closing that brings the story back to the reader.', 'caption': 'Test caption.', 'alt': 'Test.'}
            album = True
            print('mock check', check_plan(plan, ideas, sheet, True))
        image = lambda a, fmt, over=None: page.evaluate('([a, b, c]) => WMESocial.image(a, b, c)', [a, fmt, over])
        no_text = lambda s: None if next(i for i in ideas if i['id'] == s['id'])['art'] == 'fact' else {'text': s['text']}
        cat = pick.get('cat', 'now')
        force = os.environ.get('MOCK_ALBUM') == 'explain'
        if explainer_due(history) or force:
            item, number = next_explainer(history)
            album, cat = True, 'explain'
            caption, alt = item['caption'] + signoff, item['hook']
            parts = [('explain', {'text': item['hook'], 'eyebrow': item['kicker'], 'swipe': True})] + [('explain', {'text': s, 'eyebrow': item['kicker']}) for s in item['slides']] + ([('key', {'eyebrow': item['kicker']})] if item.get('colour_key') else []) + [('closing', {'text': item['closing'], 'eyebrow': item['kicker'], 'cat': 'explain'})]
            kind = f'explainer|album|explain{number}'
            plan = {'explainer': number}
        elif plan is None:
            album = False
            caption, alt = pick['caption'], pick['alt']
            parts = [(pick['id'], None)]
            kind = f"{pick['type']}|single|template"
            if ANTHROPIC_KEY and not DRY:
                relay('telegram', text='Instagram agent used plain template wording today because the written version failed its checks.')
        else:
            caption, alt = plan['caption'].strip() + signoff, plan['alt']
            parts = [(s['id'], no_text(s)) for s in plan['slides']]
            if album:
                parts = [('hook', {'text': plan['hook'], 'eyebrow': plan['hook_kicker'].upper(), 'cat': cat})] + [(a, {**(o or {}), 'cat': cat}) for a, o in parts] + [('closing', {'text': plan['closing'], 'cat': cat})]
            kind = f"{pick['type']}|{'album' if album else 'single'}|{angle}"
        if DRY:
            OUT.mkdir(exist_ok=True)
            for n, (a, over) in enumerate(parts):
                (OUT / f'post_{n:02d}_{a}.jpg').write_bytes(base64.b64decode(image(a, 'feed', over).split(',', 1)[1]))
            for idea in ideas:
                (OUT / f"{idea['id']}_feed.jpg").write_bytes(base64.b64decode(image(idea['id'], 'feed').split(',', 1)[1]))
            (OUT / 'ideas.json').write_text(json.dumps({'pick': pick['id'], 'kind': kind, 'album': album, 'plan': plan, 'facts': sheet, 'caption': caption}, indent=1, ensure_ascii=False), encoding='utf8')
            return
        if any(r['day'] == today for r in history):
            print('already posted today')
            return
        feeds = [image(a, 'feed', over) for a, over in parts]
        story = image(parts[0][0], 'story', parts[0][1])
        browser.close()
    urls = []
    for n, data in enumerate(feeds):
        url, size = upload(f'{today}-{n}', data)
        urls.append(url)
        print('image bytes', size)
    media = publish_album(urls, caption) if album else publish(urls[0], caption=caption, alt=alt)
    relay('log', media_id=media, day=today, type=kind, caption=caption, novelty=pick['novelty'])
    s, d = graph(f'/{media}', fields='permalink')
    relay('telegram', text=f"Posted to Instagram ({kind}):\n{caption.split(chr(10))[0][:200]}\n{d.get('permalink', '')}")
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
