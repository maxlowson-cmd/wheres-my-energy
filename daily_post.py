"""Make the daily social post: yesterday's regions ranked by renewable share. Writes out/daily.png and out/daily.txt.

Usage: python daily_post.py [YYYY-MM-DD]   (defaults to yesterday, UK time)
"""
import datetime as dt, json, pathlib, sys, urllib.request
from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
SITE = 'wheresmyenergyfrom.co.uk'
RENEWABLE = {'wind', 'solar', 'hydro', 'biomass'}
BG, PANEL, INK, MUTED, LINE, GO = '#dfeae6', '#f4f8f6', '#10302a', '#4c6a62', '#bfd2cb', '#06704b'
W, H = 1080, 1350


def last_sunday(year, month):
    d = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def uk_offset(t):
    start = dt.datetime.combine(last_sunday(t.year, 3), dt.time(1), dt.timezone.utc)
    end = dt.datetime.combine(last_sunday(t.year, 10), dt.time(1), dt.timezone.utc)
    return dt.timedelta(hours=1) if start <= t < end else dt.timedelta(0)


def uk_midnight(day):
    guess = dt.datetime.combine(day, dt.time(0), dt.timezone.utc)
    return guess - uk_offset(guess - dt.timedelta(hours=2))


def league(day):
    start, end = uk_midnight(day), uk_midnight(day + dt.timedelta(days=1))
    url = f'https://api.carbonintensity.org.uk/regional/intensity/{start:%Y-%m-%dT%H:%MZ}/fw24h'
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/2.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)['data']
    first, last = start.strftime('%Y-%m-%dT%H:%MZ'), end.strftime('%Y-%m-%dT%H:%MZ')
    rows = [x for x in rows if first <= x['from'] < last]
    if len(rows) < 40:
        raise SystemExit(f'only {len(rows)} half hours came back for {day}, not posting')
    seen = {}
    for row in rows:
        for reg in row['regions']:
            share = sum(m['perc'] for m in reg['generationmix'] if m['fuel'] in RENEWABLE)
            seen.setdefault(reg['regionid'], {'name': reg['shortname'], 'r': [], 'c': []})
            seen[reg['regionid']]['r'].append(share)
            seen[reg['regionid']]['c'].append(reg['intensity']['forecast'])
    out = [{'id': i, 'name': v['name'], 'renewable': sum(v['r']) / len(v['r']), 'carbon': sum(v['c']) / len(v['c'])} for i, v in seen.items()]
    gb = next(x for x in out if x['id'] == 18)
    return sorted((x for x in out if 1 <= x['id'] <= 14), key=lambda x: -x['renewable']), gb


def font(name, size, weight):
    f = ImageFont.truetype(str(HERE / 'fonts' / f'{name}.ttf'), size)
    f.set_variation_by_axes([96, weight, 100] if name == 'Bricolage' else [weight])
    return f


def wrap(d, text, f, width):
    lines, cur = [], ''
    for word in text.split():
        trial = f'{cur} {word}'.strip()
        if d.textlength(trial, font=f) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def draw(day, rows, gb):
    im = Image.new('RGB', (W * 2, H * 2), BG)   # drawn double size, then shrunk, for smooth edges
    d = ImageDraw.Draw(im)
    S, M = 2, 72 * 2
    top = rows[0]
    y = 76 * S
    d.text((M, y), f'{day:%A} {day.day} {day:%B}'.upper(), font=font('Figtree', 28 * S, 600), fill=MUTED)
    y += 56 * S
    head = font('Bricolage', 74 * S, 700)
    for line in wrap(d, f"{top['name']} ran on the cleanest power yesterday.", head, im.width - 2 * M):
        d.text((M, y), line, font=head, fill=INK)
        y += 80 * S
    y += 18 * S
    d.text((M, y), f"Share of electricity from renewables. Great Britain: {round(gb['renewable'])}%", font=font('Figtree', 30 * S, 500), fill=MUTED)
    y += 66 * S
    label, value = font('Figtree', 29 * S, 500), font('Figtree', 29 * S, 600)
    label_w, value_w, bar_h = 370 * S, 86 * S, 24 * S
    row_h = (H * S - 112 * S - y) / len(rows)
    x0, x1 = M + label_w, im.width - M - value_w
    for i, r in enumerate(rows):
        cy = y + row_h * (i + .5)
        name = r['name']
        d.text((M, cy), name, font=label, fill=INK, anchor='lm')
        end = x0 + max(bar_h, (x1 - x0) * r['renewable'] / 100)
        d.rounded_rectangle((x0, cy - bar_h / 2, x1, cy + bar_h / 2), radius=8 * S, fill=LINE)
        d.rounded_rectangle((x0, cy - bar_h / 2, end, cy + bar_h / 2), radius=8 * S, fill=GO)
        d.text((im.width - M, cy), f"{round(r['renewable'])}%", font=value, fill=INK, anchor='rm')
    foot = H * S - 74 * S
    d.text((M, foot), SITE, font=font('Bricolage', 34 * S, 700), fill=INK, anchor='lm')
    d.text((im.width - M, foot), 'Estimates. Includes biomass.', font=font('Figtree', 25 * S, 500), fill=MUTED, anchor='rm')
    return im.resize((W, H), Image.LANCZOS)


def main():
    if len(sys.argv) > 1:
        day = dt.date.fromisoformat(sys.argv[1])
    else:
        now = dt.datetime.now(dt.timezone.utc)
        day = (now + uk_offset(now)).date() - dt.timedelta(days=1)
    rows, gb = league(day)
    out = HERE / 'out'
    out.mkdir(exist_ok=True)
    draw(day, rows, gb).save(out / 'daily.png', optimize=True)
    top, bottom = rows[0], rows[-1]
    caption = (f"Yesterday {top['name']} ran on {round(top['renewable'])}% renewable power, while {bottom['name']} managed {round(bottom['renewable'])}%. "
               f"Great Britain as a whole: {round(gb['renewable'])}%.\n\nWhere's yours from? {SITE}\n\n"
               "Estimates from the NESO Carbon Intensity API. Renewable includes biomass.")
    import json as _json, datetime as _dt
    facts = _json.loads((pathlib.Path(__file__).resolve().parent / 'facts.json').read_text(encoding='utf8'))
    fact = facts[_dt.date.today().toordinal() % len(facts)]['t']
    body, tags = caption.rsplit('\n\n', 1) if '\n\n' in caption and caption.rsplit('\n\n', 1)[1].startswith('#') else (caption, '')
    caption = f'{body}\n\nDid you know? {fact}' + (f'\n\n{tags}' if tags else '')
    (out / 'daily.txt').write_text(caption, encoding='utf8')
    print(caption)


main()
