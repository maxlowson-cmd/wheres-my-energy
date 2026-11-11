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


HERE = pathlib.Path(__file__).resolve().parent
EXPLAINERS = json.loads((HERE / 'explainers.json').read_text(encoding='utf8'))
LESSONS = json.loads((HERE / 'lessons.json').read_text(encoding='utf8'))  # what we've learned so far, added to at each review
REPEAT_DAYS = 30  # a pre-written post or fact can come back, but not within this many days


def repeat_cutoff():
    return (time.time() - REPEAT_DAYS * 86400) * 1000


def explainer_state(history):
    """How many explainers have gone out, how many posts ago the last one was, and how many posts there are."""
    ordered = sorted(history, key=lambda r: r['posted'], reverse=True)
    since = next((i for i, r in enumerate(ordered) if r['type'].startswith('explainer')), len(ordered))
    return sum(1 for r in ordered if r['type'].startswith('explainer')), since, len(ordered)


def explainers_free(history):
    """Explainers not used lately, the never-used ones first and then the longest ago."""
    last = {}
    for row in sorted(history, key=lambda r: r['posted']):
        found = re.search(r'\|explain(\d+)', row['type'])
        if found:
            last[int(found[1])] = row['posted']
    return sorted((n for n in range(len(EXPLAINERS)) if last.get(n, 0) < repeat_cutoff()), key=lambda n: (last.get(n, 0), n))


def explainer_due(history):
    """Every fourth post explains how the site works, so people understand and trust it, if one hasn't been used lately."""
    _, since, total = explainer_state(history)
    return total >= 3 and since >= 3 and bool(explainers_free(history))


def review_due(history):
    """True once only: at the point the next explainer would have been due and the first set has run out."""
    done, since, _ = explainer_state(history)
    return done == len(EXPLAINERS) and since == 3


def fact_tag(idea):
    """A short label recording which did-you-know fact a post used."""
    return 'fact:' + re.sub(r'\W+', '-', idea['shows'][:30]).strip('-').lower()


def next_explainer(history):
    number = (explainers_free(history) or [0])[0]
    return EXPLAINERS[number], number


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

Your job is to make someone stop scrolling and think "huh, that's interesting, I want to know more". Stats alone are boring. Find the human angle in today's figures: what it means for their washing, their car, their kettle, their part of the country, or their day. If the post has no natural link to home life, don't force one: the interesting fact is enough.

Voice: warm, curious, a bit playful, plain British English. Talk to "you". Short sentences. No jargon, no hype, no exclamation-mark enthusiasm, at most one emoji in the caption and none on the slides. Never preachy: nobody gets told off for using electricity. No politics, no blaming companies or governments, and no knocking the people of any region.

Truth rules, which matter more than being catchy:
- Use only numbers that appear in the data you are given, exactly as given. Don't calculate new figures or round them differently. Loose words like "about a third" or "nearly three times" are fine where the data clearly supports them.
- The data shows what is happening, not why. Don't claim a cause for today's figures unless the data shows it: no storms, weather events, records, outages, news or price changes for customers. Give two of today's figures as two plain facts ("Wind is only around 5% this evening. Gas is making around 66%.") and don't link them with "so" or "because".
- "how_things_connect" lists how the grid generally works, checked against published sources. Use these to join one part of a story to the next. Say what usually happens, never that it happened today: "Batteries can charge when power is cheap and sell it back when it's dear" is fine, "Batteries charged at 04:30" is not. Don't add any other explanation of your own.
- "lessons_so_far" lists what we have learned from earlier posts. Apply every one of them, but they never override the truth rules.
- "Renewable" only means wind, solar, hydro and biomass. A low renewable share doesn't mean a place is dirty or doing badly: it may be running on nuclear or imports. Never quote a region's low renewable share on its own. Say what it is mainly running on, using "mainly_running_on" in the data, and compare places only in a way that is fair to both.
- Mention an occasion only if the data names one under "occasion_today".
- The on-this-day slide uses metered main-grid figures, which differ from the wider "right now" mix. Never give both figures for the same fuel in one post, and call the on-this-day figure "on the main grid".
- The figures are forecasts and estimates, so say "right now" or "around" rather than sounding exact to the kilowatt.

Clarity, which matters as much as the truth rules: every sentence has to make sense the first time it is read, by someone who knows nothing about the energy grid. One idea per sentence. Say the plain thing rather than a figure of speech ("doing more of the work", "the timing is yours to play with"). The caption has to stand on its own, because many people read it without swiping, so don't answer a question it hasn't asked yet. If a guess is used, ask it in the caption first. Read each sentence back and rewrite any that needs reading twice.

Shape, which matters as much as clarity: every post is one of two shapes, and never half of each. Choose one and put it in "shape".
- "story": one thread from start to finish, and the reader should never feel the subject change. Write the thread in "story" as one sentence. Each slide answers the question the one before it raised, and says how it connects: if the post moves from how many batteries Britain has to the price of power, a line must say that batteries can charge when power is cheap and sell it back when it's dear. Leave out any slide or fact that doesn't serve the thread, however interesting it is. Two slides that connect beat five that don't. A household tip, such as when to run the washing, only belongs if the thread leads to it.
- "bulletin": a plain run-through of today's facts, like a news round-up. Say so from the first line, such as "Today on the grid: three things worth knowing", and in "story" write what the round-up covers. Each slide is its own fact and needs no link to the next, so don't invent links or build up to anything. Don't open like a story and then turn into a list.
Pick "story" when the facts really connect, and "bulletin" when they don't.

Slides: one thought per slide. In a story, the opening slide is a hook that opens a question and doesn't give the answer away, and each slide makes you want the next. In a bulletin, the opening slide says what the round-up is. The closing slide always ends by inviting the reader to look up their own area on the site, using the words "your area", "your postcode" or "your region". Only promise what the site shows: what's powering their area right now, where their gas started out and the cleanest time to run the washing. If there's room, wrap up the post's subject first in one short line. Keep to the character limit given for each slide. A slide's text sits beside the chart or map it describes, so it must match that slide's figures.
Some slides show a big figure in large type with your words straight underneath it ("big_figure_above_your_words"). People read the two together, so carry on from the figure and never repeat it. Under "57%", for example: "of Britain's power is coming from gas right now. Over the last year it averaged 25%." Write every slide in plain sentences, never as notes or labels such as "All of Britain: gas around 57% now."

Angles:
- guess: ask the reader to guess something, with the answer on the next swipe or later in the caption.
- everyday: translate it into a real household moment.
- rivalry: friendly comparison between places, like for like, saying what each one is running on.
- surprise: lead with the most counter-intuitive thing in the data.
- question: ask something the reader has never thought to ask.

Write the caption in the same shape as the slides, in two or three short paragraphs: for a story, each paragraph picks up where the last one stopped; for a bulletin, it reads as a clear run-through from the first line. End with a question people would want to answer. Don't include links or hashtags, as those are added afterwards."""

PLAN_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['shape', 'story', 'hook_kicker', 'hook', 'slides', 'closing', 'caption', 'alt'], 'properties': {
    'shape': {'type': 'string', 'enum': ['story', 'bulletin']}, 'story': {'type': 'string'}, 'hook_kicker': {'type': 'string'}, 'hook': {'type': 'string'},
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
        elif by_id[s['id']].get('big') and by_id[s['id']]['big'] in s['text']:
            problems.append(f"slide {s['id']} repeats {by_id[s['id']]['big']}, which is already shown in large type above it; carry on from it instead")
        fields.append(s['text'])
    if album:
        fields += [plan['hook'], plan['hook_kicker'], plan['closing']]
        if not 2 <= len(plan['slides']) <= 5:
            problems.append('an album needs 2 to 5 chart slides')
        if len(plan['hook']) > 90 or len(plan['closing']) > 140 or len(plan['hook_kicker']) > 28:
            problems.append('hook, kicker or closing is too long')
        if not re.search(r'your (area|postcode|region)', plan['closing'], re.I):
            problems.append('the closing slide must invite the reader to look up your area')
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
        for r in sheet.get('regions_renewable_now_percent', []):
            fuels = [f['fuel'] for f in r.get('mainly_running_on', [])]
            if r['percent'] < 30 and r['region'] in text and f"{r['percent']}%" in text and not any(f in text.lower() for f in fuels):
                problems.append(f"{r['region']} is given as {r['percent']}% renewable without saying it is mainly running on {' and '.join(fuels)}")
    return problems


EDITOR = """You are the last check on an Instagram post from a free British site about where electricity comes from. Picture someone with no knowledge of the energy grid, reading quickly on their phone.

List every sentence or slide line they would have to read twice, or could not act on or picture. Flag lines that are vague or sound nice but say nothing ("the timing is yours to play with"), figures of speech standing in for a plain statement ("gas is doing more of the work"), two facts joined as if one caused the other without saying how, and anything that answers a question not yet asked or relies on something the reader hasn't seen. Read in order, the caption and the slides must each make sense.

You are told the post's shape. If it is a "story", also flag any jump: a place in the caption, or between one slide and the next, where the subject changes and no words say how the two connect, so it feels like a new post has started. Quote the words on either side of it. The closing slide always invites the reader to look up their own area, and that invitation is never a jump. If it is a "bulletin", separate facts are correct and are not jumps, but flag it if the opening doesn't make clear this is a round-up, or if it starts like a story and turns into a list. A post that is half story and half list is always worth flagging.

You only see the words. Each slide sits beside a chart or map that carries the rest of its figures, so don't flag a slide for leaving out part of a breakdown. If "already_raised" is given, this is a rewrite: check only whether those points are now fixed, and raise something new only if a line makes no sense at all.

Some slides start with a big figure shown in large type, written in square brackets; the words underneath are read straight after it. Flag a slide that repeats that figure or that reads as notes or labels rather than sentences, such as "All of Britain: gas around 57% now. 12-month average: 25%."

Quote the exact words and say in a few words what is unclear. Don't flag tone, style, length or the figures themselves. Units such as MW or grams of CO2 are fine when the post gives a sense of scale or comparison. Flag only what would really trip someone up, and list at most the two worst. A post doesn't have to explain every term: never ask for more explanation of a single fact, such as why a time is cleaner or what CO2 is. Different figures can come from different sources, so don't flag those. If everything is clear first time, return an empty list."""
EDITOR_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['unclear'], 'properties': {'unclear': {'type': 'array', 'items': {'type': 'string'}}}}


def unclear_lines(client, plan, album, raised):
    """A fresh read of the finished wording. Returns the lines that need rewriting."""
    post = {'shape': plan['shape'], 'caption': plan['caption'], 'slides': ([plan['hook']] if album else []) + [s['text'] for s in plan['slides']] + ([plan['closing']] if album else []), **({'already_raised': raised} if raised else {})}
    response = client.beta.messages.create(model='claude-opus-5-5', max_tokens=4000, system=EDITOR, messages=[{'role': 'user', 'content': json.dumps(post, ensure_ascii=False)}], betas=['server-side-fallback-2026-07-01'], fallbacks='default', output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': EDITOR_SCHEMA}})
    if response.stop_reason in ('refusal', 'max_tokens'):
        return ['the editor could not read this post']
    return [f'unclear: {x}' for x in json.loads(next(b.text for b in response.content if b.type == 'text'))['unclear']]


# General background the writer may use to join facts together. Sources: Modo Energy (battery income), First Hydro (pumped storage), Carbon Brief and Institute for Government (gas and price), UKERC and Modo Energy (Scottish constraints), NESO (carbon intensity).
HOW_THINGS_CONNECT = [
    "Grid batteries earn much of their money by charging when electricity is cheap and selling it back when it is dear. They are also paid to help keep the grid steady.",
    "Pumped hydro works like a giant battery: water is pumped uphill when power is plentiful and let back down through turbines when it's needed.",
    "Wholesale prices are often set by gas plants, because the last power station needed sets the price for everyone in that period, and that is often a gas plant.",
    "The cables from Scotland to England have a limit. When they are full, some Scottish wind farms are asked to turn down and power stations further south, often gas, are asked to run instead.",
    "A time of day counts as cleaner when each unit of electricity comes with less CO2, which happens when less of the power is being made by burning gas.",
]


def write_plan(lead, ideas, sheet, angle, album, recent, today):
    if not ANTHROPIC_KEY:
        return None
    import anthropic
    client = anthropic.Anthropic()
    brief = {'data': {**sheet, 'occasion_today': moment_today(today)}, 'how_things_connect': HOW_THINGS_CONNECT, 'lessons_so_far': [x['lesson'] for x in LESSONS if x['area'] == 'writing'], 'format': 'album' if album else 'single image', 'angle_to_use': angle, 'lead_slide_id': lead['id'],
             'available_slides': [{'id': i['id'], 'shows': i['shows'], 'character_limit': i['limit'], 'interest_score': round(i['novelty'], 2), **({'big_figure_above_your_words': i['big']} if i.get('big') else {})} for i in ideas],
             'instructions': ('Choose the shape first, story or bulletin. Then write 2 to 5 chart slides in order, plus the hook and closing. The post is about the lead slide, so it must be included, usually first. In a story, use only the slides that belong to its thread. Hook at most 90 characters, kicker at most 28, closing at most 140. The fact slide cannot be reworded.' if album else 'Write exactly one slide: the lead slide. Leave hook, hook_kicker and closing as empty strings.'),
             'recent_captions_to_avoid_repeating': recent}
    messages = [{'role': 'user', 'content': json.dumps(brief, ensure_ascii=False)}]
    raised = []
    for attempt in range(4):
        response = client.beta.messages.create(model='claude-opus-5-5', max_tokens=16000, system=VOICE, messages=messages, betas=['server-side-fallback-2026-07-01'], fallbacks='default', output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': PLAN_SCHEMA}})
        if response.stop_reason in ('refusal', 'max_tokens'):
            print('no usable wording:', response.stop_reason)
            return None
        text = next(b.text for b in response.content if b.type == 'text')
        plan = json.loads(text)
        problems = check_plan(plan, ideas, sheet, album) + ([] if any(s['id'] == lead['id'] for s in plan['slides']) else [f"the post must include the lead slide {lead['id']}"])
        if not problems:
            big = {i['id']: i.get('big') for i in ideas}
            shown = {**plan, 'slides': [{**s, 'text': f"[{big[s['id']]} in large type] {s['text']}" if big.get(s['id']) else s['text']} for s in plan['slides']]}
            problems = unclear_lines(client, shown, album, raised)
            raised += problems
        print('wording check', attempt, problems or 'passed')
        if not problems:
            return plan
        messages += [{'role': 'assistant', 'content': text}, {'role': 'user', 'content': 'Please fix these and return the whole post again. Fix an unclear line by cutting it or saying the plain thing. Fix a jump by adding a short line that connects the two parts, using how_things_connect, or by removing the part that does not belong. If the facts do not really connect, make it a bulletin instead. Otherwise shorter is better: ' + '; '.join(problems)}]
    return None


PHOTOS = json.loads((pathlib.Path(__file__).resolve().parent / 'photos.json').read_text(encoding='utf8'))
POSTER_COLOURS = {'now': ['sun', 'mint', 'blue'], 'history': ['sun', 'paper', 'mint'], 'new': ['blue', 'mint'], 'explain': ['lilac'], 'fact': ['coral', 'paper']}
LOOK_WEIGHT = {'photo': 0, 'flag': .1, 'price': .1, 'battery': .1, 'scene': .2, 'poster': .6}
SUBJECTS = {'fuel-wind': ('wind', ['offshore', 'onshore']), 'fuel-solar': ('solar', ['solar']), 'fuel-gas': ('gas', ['gas']), 'fuel-nuclear': ('nuclear', ['nuclear']), 'fuel-imports': ('pylons', ['pylons']), 'gas-origin': ('hob', ['gas_import']), 'day': ('wash', []), 'prices': ('pylons', ['pylons']), 'league': ('wind', ['pylons']), 'divide': ('pylons', ['pylons']), 'on-this-day': ('pylons', ['pylons']), 'growth-battery': (None, []), 'growth-solar-photovoltaics': ('solar', ['solar']), 'growth-wind-offshore': ('wind', ['offshore']), 'growth-wind-onshore': ('wind', ['onshore'])}
FACT_SUBJECTS = [(r'hydro|\bdam\b|reservoir|Cruachan|Dinorwig|pumped', ('hydro', ['hydro'])), (r'nuclear|Sizewell|Calder Hall|Torness', ('nuclear', ['nuclear'])), (r'wind|turbine', ('wind', ['offshore', 'onshore'])), (r'solar', ('solar', ['solar'])), (r'\bgas\b|North Sea|LNG', ('hob', ['gas_import']))]


def cover_subject(pick, spec):
    """Which illustrated scene and which photos suit this post. Returns (scene or None, photo tags)."""
    if pick['id'] == 'fact':
        return next((v for pattern, v in FACT_SUBJECTS if re.search(pattern, spec.get('text', ''), re.I)), (None, []))
    if pick['id'] == 'new-site':
        fuel = str(spec.get('spotFuel') or spec.get('fuelGlow') or '')
        return ('wind', ['offshore', 'onshore']) if fuel == 'wind' else ('solar', ['solar']) if fuel == 'solar' else (None, [])
    return SUBJECTS.get(pick['id'], ('pylons', ['pylons']))


def data_cover(pick, spec, sheet):
    """A cover drawn entirely from the post's own figures, for posts that aren't opening with a hook."""
    if pick['id'].startswith('fuel-'):
        mix = sorted(((k, v) for k, v in sheet['britain_now_percent'].items() if v >= 3), key=lambda x: -x[1])
        return {'look': 'flag', 'text': "What's powering Britain right now", 'mix': [list(x) for x in mix]}
    if pick['id'] == 'prices':
        found = [re.search(r'(\d\d:\d\d) \((£[\d,]+)\)', str(r[2])) for r in spec.get('rows', [])]
        if len(found) == 2 and all(found):
            return {'look': 'price', 'low': [found[0][2], found[0][1]], 'high': [found[1][2], found[1][1]]}
    if pick['id'] == 'growth-battery':
        (d0, v0), (d1, v1) = spec['rows']
        number = lambda v: int(v.replace(' MW', '').replace(',', ''))
        return {'look': 'battery', 'then': [number(v0), v0, d0], 'now': [number(v1), v1, d1]}
    return None


def choose_cover(pick, spec, sheet, history, is_hook, explainer, seed):
    """Picks the look least used lately, so neighbouring squares on the grid differ. Returns (cover, label, caption credit)."""
    rng = random.Random(seed)
    past = [part.split(':', 1)[1] for row in sorted(history, key=lambda r: r['posted'], reverse=True) for part in row['type'].split('|') if part.startswith('cover:')]
    recent = [p.split(':')[0] for p in past[:3]]
    scene, tags = (('explain', []) if explainer else cover_subject(pick, spec))
    cat = 'explain' if explainer else pick.get('cat', 'now')
    colours = POSTER_COLOURS[cat]
    fresh = [c for c in colours if f'poster:{c}' not in past[:2]] or colours
    options = {'poster': {'look': 'poster', 'colour': rng.choice(fresh)}}
    if scene and (scene != 'wash' or not is_hook):
        options['scene'] = {'look': 'scene', 'scene': scene}
    photos = [p for p in PHOTOS if p['tag'] in tags]
    fresher = [p for p in photos if f"photo:{p['file']}" not in past[:12]] or photos
    if fresher and not explainer:
        named = [p for p in fresher if p['place'].split(',')[0] in str(spec.get('text', ''))]
        options['photo'] = {'look': 'photo', 'chosen': rng.choice(named or fresher)}
    extra = None if is_hook or explainer else data_cover(pick, spec, sheet)
    if extra:
        options[extra['look']] = extra
    name = min(options, key=lambda k: recent.count(k) + LOOK_WEIGHT[k] + rng.random() * .3)
    cover = dict(options[name])
    credit, label = '', name
    if name == 'photo':
        p = cover.pop('chosen')
        raw = (pathlib.Path(__file__).resolve().parent / 'photos' / p['file']).read_bytes()
        cover['photo'] = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode()
        cover['credit'] = f"Photo: {p['place']}. {p['artist']}, {p['license']}"
        credit = f"{cover['credit']}, cropped. All photo credits: wheresmyenergyfrom.co.uk/credits"
        label = f"photo:{p['file']}"
    elif name == 'poster':
        label = f"poster:{cover['colour']}"
    elif name == 'scene':
        label = f"scene:{cover['scene']}"
    return cover, label, credit


def with_credit(caption, credit):
    """Puts the photo credit above the hashtags."""
    if not credit:
        return caption
    head, sep, tags = caption.rpartition('\n\n#')
    return f'{head}\n\n{credit}{sep}{tags}' if sep else f'{caption}\n\n{credit}'


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


def slot_name(moment):
    """Which of the day's posting times this falls in, by the UK clock."""
    hour = moment.astimezone(ZoneInfo('Europe/London')).hour
    return 'am' if hour < 11 else 'noon' if hour < 17 else 'pm'


def main():
    today = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    history = relay('history').get('posts', [])
    now_utc = dt.datetime.now(dt.timezone.utc)
    slot = f'x{now_utc:%H%M}' if os.environ.get('EXTRA_POST') == '1' else slot_name(now_utc)  # a post asked for by hand gets its own slot
    same_slot = lambda r: r['day'] == today and slot_name(dt.datetime.fromtimestamp(r['posted'] / 1000, dt.timezone.utc)) == slot
    if not DRY and any(same_slot(r) for r in history):
        print('already posted in this slot')
        return
    if not DRY:
        refresh_stats(history)
        if review_due(history):
            relay('telegram', text=f"All {len(EXPLAINERS)} how-it-works posts have now gone out. Each can only come back after {REPEAT_DAYS} days. Time to review how the posts have done and plan the next lot.")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1080, 'height': 1400})
        page.goto(f'{SITE}?agent={int(time.time())}', wait_until='load', timeout=120000)
        page.wait_for_function('window.WMESocial && document.fonts.status === "loaded"', timeout=60000)
        page.add_script_tag(path=str(pathlib.Path(__file__).resolve().parent / 'covers.js'))
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
        used = {part for r in history if r['posted'] >= repeat_cutoff() for part in r['type'].split('|')}
        ideas = [i for i in ideas if i['id'] != 'fact' or fact_tag(i) not in used]
        print('ideas', [(i['id'], round(i['novelty'], 2)) for i in ideas])
        if not ideas:
            if not DRY:
                relay('telegram', text='Instagram agent skipped today: the site data is too old to post.')
            return
        pick = choose(ideas, history, f'{today}{slot}')
        test_pick = os.environ.get('MOCK_ALBUM', '').partition(':')[2] if DRY else ''  # a no-post test can name the story to try
        if test_pick:
            pick = next(i for i in ideas if i['id'] == test_pick)
        print('pick', pick['id'])
        sheet = page.evaluate('WMESocial.facts()')
        signoff = page.evaluate('WMESocial.signoff')
        day = dt.date.fromisoformat(today)
        album = pick['novelty'] >= .8 or day.weekday() in (1, 3, 6) or os.environ.get('MOCK_ALBUM', '').startswith('album')
        if DRY and os.environ.get('MOCK_ALBUM', '').startswith('single'):
            album = False
        angle = pick_angle(history, f'{today}{slot}')
        print('format', 'album' if album else 'single', 'angle', angle)
        for idea, big in zip(ideas, page.evaluate('ids => ids.map((id) => String((WMESocial.spec(id) || {}).big || ""))', [i['id'] for i in ideas])):
            idea['big'] = big
        plan = None if explainer_due(history) or os.environ.get('MOCK_ALBUM') == 'explain' else write_plan(pick, ideas, sheet, angle, album, [r.get('caption', '')[:200] for r in history[:7]], day)
        if plan is None and DRY and os.environ.get('MOCK_ALBUM') == '1':
            lead = [pick['id']] + [i['id'] for i in ideas if i['id'] != pick['id'] and i['type'] != 'fact'][:3]
            plan = {'hook_kicker': 'TEST KICKER', 'hook': 'Test hook: this slide opens the story without giving it away.', 'slides': [{'id': x, 'text': 'Test wording for this slide.'} for x in lead], 'closing': 'Test closing that brings the story back to the reader.', 'caption': 'Test caption.', 'alt': 'Test.'}
            album = True
            print('mock check', check_plan(plan, ideas, sheet, True))
        def image(a, fmt, over=None):
            if over and over.get('cover'):
                return page.evaluate('([s, f]) => WMECovers[f](s)', [over['cover'], fmt])
            return page.evaluate('([a, b, c]) => WMESocial.image(a, b, c)', [a, fmt, over])
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
        spec = page.evaluate('id => WMESocial.spec(id)', pick['id']) or {}
        explainer = kind.startswith('explainer')
        cover, label, credit = choose_cover(pick, spec, sheet, history, album, explainer, f'{today}{slot}cover')
        if album:
            first = parts[0][1]
            parts[0] = (parts[0][0], {**first, 'cover': {**cover, 'text': first['text'], 'eyebrow': first['eyebrow'], 'swipe': True}})
        else:
            words = spec.get('headline') or spec.get('sub') or re.split(r'(?<=[.!?])\s', spec.get('text', ''))[0]
            parts.insert(0, ('cover', {'cover': {**cover, 'big': spec.get('big'), 'text': words, 'eyebrow': spec.get('eyebrow', ''), 'swipe': True}}))
            parts.append(('closing', {'text': "What's powering your area right now? Look it up in seconds.", 'label': 'NOW FOR YOUR AREA'}))
            album = True
        if parts[-1][0] == 'closing':
            shade = random.Random(f'{today}{slot}end').choice(POSTER_COLOURS[pick.get('cat', 'now')])
            parts[-1] = ('closing', {**parts[-1][1], 'cover': {'look': 'poster', 'colour': shade, 'text': parts[-1][1]['text'], 'eyebrow': parts[-1][1].get('label', 'WHAT IT MEANS FOR YOU'), 'note': 'Put in your postcode at the link in our bio.'}})
        caption = with_credit(caption, credit)
        kind += f'|cover:{label}'
        if plan and plan.get('shape'):
            kind += f"|shape:{plan['shape']}"  # so a review can compare stories with bulletins
        fact = next((i for i in ideas if i['id'] == 'fact'), None)
        if fact and any(a == 'fact' for a, _ in parts):
            kind += f'|{fact_tag(fact)}'
        print('cover', label)
        lead_part = next((p for p in parts if p[0] not in ('cover', 'hook', 'closing')), parts[0])
        story_over = {k: v for k, v in (lead_part[1] or {}).items() if k not in ('cover', 'swipe')} or None
        if DRY:
            OUT.mkdir(exist_ok=True)
            for n, (a, over) in enumerate(parts):
                (OUT / f'post_{n:02d}_{a}.jpg').write_bytes(base64.b64decode(image(a, 'feed', over).split(',', 1)[1]))
            for idea in ideas:
                (OUT / f"{idea['id']}_feed.jpg").write_bytes(base64.b64decode(image(idea['id'], 'feed').split(',', 1)[1]))
            (OUT / 'story.jpg').write_bytes(base64.b64decode(image(lead_part[0], 'story', story_over).split(',', 1)[1]))
            (OUT / 'ideas.json').write_text(json.dumps({'pick': pick['id'], 'kind': kind, 'album': album, 'plan': plan, 'facts': sheet, 'caption': caption}, indent=1, ensure_ascii=False), encoding='utf8')
            return
        feeds = [image(a, 'feed', over) for a, over in parts]
        story = image(lead_part[0], 'story', story_over)
        browser.close()
    urls = []
    for n, data in enumerate(feeds):
        url, size = upload(f'{today}-{slot}-{n}', data)
        urls.append(url)
        print('image bytes', size)
    media = publish_album(urls, caption) if album else publish(urls[0], caption=caption, alt=alt)
    relay('log', media_id=media, day=today, type=kind, caption=caption, novelty=pick['novelty'])
    s, d = graph(f'/{media}', fields='permalink')
    relay('telegram', text=f"Posted to Instagram ({kind}):\n{caption.split(chr(10))[0][:200]}\n{d.get('permalink', '')}")
    try:
        story_url, _ = upload(f'{today}-{slot}-story', story)
        publish(story_url, story=True)
    except Exception as e:
        relay('telegram', text=f'Instagram story failed, the feed post went out: {str(e)[:300]}')
    if now_utc.weekday() == 6 and not any(r['day'] == today for r in history):
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
