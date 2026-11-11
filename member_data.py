"""Last 30 days of real Agile prices and carbon, summarised per region, plus current Agile prices. Writes member.json."""
import json, pathlib, time, urllib.error, urllib.request, datetime as dt

HERE = pathlib.Path(__file__).resolve().parent
GSP = {1: 'P', 2: 'N', 3: 'G', 4: 'F', 5: 'M', 6: 'D', 7: 'K', 8: 'E', 9: 'B', 10: 'A', 11: 'L', 12: 'H', 13: 'C', 14: 'J'}
PRODUCT = 'AGILE-24-10-01'
UTC = dt.timezone.utc
HALF = dt.timedelta(minutes=30)


def last_sunday(year, month):
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def offset(t):
    start = dt.datetime.combine(last_sunday(t.year, 3), dt.time(1), UTC)
    end = dt.datetime.combine(last_sunday(t.year, 10), dt.time(1), UTC)
    return dt.timedelta(hours=1) if start <= t < end else dt.timedelta(0)


def at_uk(day, hour=0):
    guess = dt.datetime.combine(day, dt.time(hour), UTC)
    return guess - offset(guess)


def get(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/2.0'})
    for attempt in range(4):  # the data APIs sometimes return a one-off server error; try again before giving up
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3 or (isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429):
                raise
            time.sleep(5 * (attempt + 1))


def parse(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(UTC)


now = dt.datetime.now(UTC)
today = (now + offset(now)).date()
days = [today - dt.timedelta(days=i) for i in range(30, 0, -1)]
first = at_uk(days[0])

prices = {i: {} for i in GSP}
for i, letter in GSP.items():
    code = f'E-1R-{PRODUCT}-{letter}'
    url = f'https://api.octopus.energy/v1/products/{PRODUCT}/electricity-tariffs/{code}/standard-unit-rates/?period_from={first:%Y-%m-%dT%H:%MZ}&page_size=1500'
    while url:
        page = get(url)
        for row in page['results']:
            prices[i][parse(row['valid_from'])] = row['value_inc_vat']
        url = page.get('next')

carbon = {i: {} for i in GSP}
t = first
while t < now:
    end = min(t + dt.timedelta(days=13), now + dt.timedelta(hours=1))
    for row in get(f'https://api.carbonintensity.org.uk/regional/intensity/{t:%Y-%m-%dT%H:%MZ}/{end:%Y-%m-%dT%H:%MZ}')['data']:
        for reg in row['regions']:
            if reg['regionid'] in carbon:
                carbon[reg['regionid']][parse(row['from'])] = reg['intensity']['forecast']
    t = end


def slots(a, b):
    out = []
    while a < b:
        out.append(a)
        a += HALF
    return out


def best(span, n, score):
    """the n contiguous slots with the lowest average score"""
    top = None
    for i in range(len(span) - n + 1):
        w = span[i:i + n]
        s = sum(score[x] for x in w) / n
        if top is None or s < top[0]:
            top = (s, w)
    return top


def clock(t):
    return (t + offset(t)).strftime('%H:%M')


def avg(ts, score):
    return sum(score[x] for x in ts) / len(ts)


def summary(i, day):
    p, c = prices[i], carbon[i]
    next_day = day + dt.timedelta(days=1)
    whole, wash, car = slots(at_uk(day), at_uk(next_day)), slots(at_uk(day, 7), at_uk(day, 22)), slots(at_uk(day, 19), at_uk(next_day, 7))
    if any(x not in p or x not in c for x in whole + car):
        return None
    pw, pc = best(wash, 5, p), best(car, 12, p)
    cw, cc = best(wash, 5, c), best(car, 12, c)
    r = lambda x: round(x, 2)
    return {'pd': r(avg(whole, p)), 'pw': r(pw[0]), 'pc': r(pc[0]), 'cd': r(avg(whole, c)), 'cw': r(cw[0]), 'cc': r(cc[0]),
            'cwp': r(avg(pw[1], c)), 'ccp': r(avg(pc[1], c)), 'tw': clock(pw[1][0]), 'tc': clock(pc[1][0]), 'tcw': clock(cw[1][0]), 'tcc': clock(cc[1][0])}


current = {}
for i in GSP:
    start = at_uk(today)
    ts = sorted(x for x in prices[i] if x >= start)
    current[i] = {'start': start.strftime('%Y-%m-%dT%H:%MZ'), 'v': [round(prices[i][x], 2) for x in slots(start, ts[-1] + HALF)] if ts else []}

go = {}
for i, letter in GSP.items():
    code = 'GO-VAR-22-10-14'
    rows = get(f'https://api.octopus.energy/v1/products/{code}/electricity-tariffs/E-1R-{code}-{letter}/standard-unit-rates/?page_size=2')['results']
    values = [x['value_inc_vat'] for x in rows]
    go[i] = {'night': round(min(values), 2), 'day': round(max(values), 2)}

out = {'days': [d.isoformat() for d in days], 'regions': {i: [summary(i, d) for d in days] for i in GSP}, 'agile': current, 'go': go}
(HERE / 'member.json').write_text(json.dumps(out, separators=(',', ':')), encoding='utf8')
print('member days', len(days), 'complete', sum(x is not None for x in out['regions'][13]), 'agile slots', len(current[13]['v']))
