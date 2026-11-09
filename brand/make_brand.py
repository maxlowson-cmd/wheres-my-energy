"""Draw the social account images into this folder. Run: python brand/make_brand.py"""
import math, pathlib
from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
FONTS = HERE.parent / 'fonts'
PALE, PANEL, INK, MUTED, GREEN, MINT = '#dfeae6', '#f4f8f6', '#10302a', '#4c6a62', '#06704b', '#f2fbf7'
DARK = '#0f211d'
FUELS = [('#c8553d', 30), ('#2f7fb5', 26), ('#6a4fa3', 15), ('#b0719a', 9), ('#6f8f3a', 8), ('#d9a21b', 6), ('#2aa198', 6)]
SITE = 'wheresmyenergyfrom.co.uk'
S = 3


def canvas(w, h, bg):
    im = Image.new('RGB', (w * S, h * S), bg)
    return im, ImageDraw.Draw(im)


def font(name, size, weight):
    f = ImageFont.truetype(str(FONTS / f'{name}.ttf'), size * S)
    f.set_variation_by_axes([96, weight, 100] if name == 'Bricolage' else [weight])
    return f


def save(im, w, h, name):
    out = im.resize((w, h), Image.LANCZOS)
    out.save(HERE / f'{name}.png', optimize=True)
    return out


def bolt(d, cx, cy, size, fill):
    k = size * S / 22
    pts = [(18, 5), (9, 18), (15, 18), (14, 27), (23, 14), (17, 14)]
    d.polygon([(cx * S + (x - 16) * k, cy * S + (y - 16) * k) for x, y in pts], fill=fill)


def pin(d, cx, cy, h, fill, inner):
    h *= S; cx *= S; cy *= S
    r = h * .37
    hx, hy, tip = cx, cy - h / 2 + r, cy + h / 2
    a = math.asin(r / (tip - hy))
    d.ellipse((hx - r, hy - r, hx + r, hy + r), fill=fill)
    d.polygon([(hx - r * math.cos(a), hy + r * math.sin(a)), (hx + r * math.cos(a), hy + r * math.sin(a)), (hx, tip)], fill=fill)
    bolt(d, hx / S, hy / S, r * 1.28 / S, inner)


def bezier(p0, p1, p2, p3, n=40):
    out = []
    for i in range(n):
        t = i / n
        u = 1 - t
        out.append(tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t ** 3 * e for a, b, c, e in zip(p0, p1, p2, p3)))
    return out


FLAME = (bezier((.5, 1), (.85, 1), (1, .75), (.92, .52)) + bezier((.92, .52), (.86, .35), (.62, .25), (.52, 0))
         + bezier((.52, 0), (.55, .22), (.25, .3), (.14, .5)) + bezier((.14, .5), (.02, .72), (.18, 1), (.5, 1)))


def flame(d, cx, cy, h, fill, inner):
    k = h * S
    d.polygon([(cx * S + (x - .5) * k, cy * S + (y - .5) * k) for x, y in FLAME], fill=fill)
    d.polygon([(cx * S + (x - .5) * k * .46, cy * S + ((y - 1) * .46 + .43) * k) for x, y in FLAME], fill=inner)


def bars(d, cx, cy, size, fill):
    w, h, gap = size * S, size * S * .18, size * S * .15
    top = cy * S - (3 * h + 2 * gap) / 2
    left = cx * S - w / 2
    for i, part in enumerate((1, .72, .44)):
        y = top + i * (h + gap)
        d.rounded_rectangle((left, y, left + w * part, y + h), radius=h * .32, fill=fill)


def ring(d, cx, cy, r, width, gap=3.5):
    box = ((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S)
    total, at = sum(v for _, v in FUELS), -90
    for colour, v in FUELS:
        sweep = 360 * v / total
        d.arc(box, at + gap / 2, at + sweep - gap / 2, fill=colour, width=width * S)
        at += sweep


def strip(d, x, y, w, h, gap=6):
    total = sum(v for _, v in FUELS)
    usable = w - gap * (len(FUELS) - 1)
    for colour, v in FUELS:
        part = usable * v / total
        d.rounded_rectangle((x * S, y * S, (x + part) * S, (y + h) * S), radius=min(8, h / 2) * S, fill=colour)
        x += part + gap


def text(d, xy, value, f, fill, anchor='la'):
    d.text((xy[0] * S, xy[1] * S), value, font=f, fill=fill, anchor=anchor)


def block(d, x, y, lines, f, fill, step):
    for line in lines:
        text(d, (x, y), line, f, fill)
        y += step
    return y


made = {}

# profile pictures: everything sits inside the circle Instagram crops to
def profile_pin():
    im, d = canvas(1080, 1080, GREEN); pin(d, 540, 535, 720, MINT, GREEN); return im
def profile_bolt():
    im, d = canvas(1080, 1080, GREEN); bolt(d, 540, 540, 660, MINT); return im
def profile_ring():
    im, d = canvas(1080, 1080, DARK); ring(d, 540, 540, 430, 66); bolt(d, 540, 540, 480, MINT); return im
def profile_light():
    im, d = canvas(1080, 1080, PALE); pin(d, 540, 535, 720, GREEN, MINT); return im
for name, fn in (('profile_1_pin', profile_pin), ('profile_2_bolt', profile_bolt), ('profile_3_fuel_ring', profile_ring), ('profile_4_light', profile_light)):
    made[name] = save(fn(), 1080, 1080, name)

# highlight covers: Instagram shows the middle as a circle
def cover(draw):
    im, d = canvas(1080, 1920, GREEN); draw(d); return save(im, 1080, 1920, draw.__name__)
def highlight_today(d): bolt(d, 540, 960, 500, MINT)
def highlight_league(d): bars(d, 540, 960, 480, MINT)
def highlight_my_area(d): pin(d, 540, 955, 540, MINT, GREEN)
def highlight_gas(d): flame(d, 540, 955, 540, MINT, GREEN)
def highlight_how(d): text(d, (540, 960), '?', font('Bricolage', 520, 700), MINT, 'mm')
for fn in (highlight_today, highlight_league, highlight_my_area, highlight_gas, highlight_how):
    made[fn.__name__] = cover(fn)

# three launch posts, which sit side by side on the profile grid
M = 90
def post_1():
    im, d = canvas(1080, 1350, GREEN)
    pin(d, 170, 240, 240, MINT, GREEN)
    y = block(d, M, 430, ["Where's", 'my energy', 'from?'], font('Bricolage', 170, 700), MINT, 178)
    block(d, M, y + 40, ['Type your postcode. See where your', 'power is likely coming from right now.'], font('Figtree', 44, 500), MINT, 60)
    text(d, (M, 1240), SITE, font('Bricolage', 42, 700), MINT)
    return im
def post_2():
    im, d = canvas(1080, 1350, PALE)
    y = block(d, M, 100, ['Three things', 'in one postcode.'], font('Bricolage', 104, 700), INK, 114)
    y += 60
    head, body = font('Bricolage', 54, 700), font('Figtree', 40, 500)
    rows = [(pin, 'Your power', ['What is powering your area, and', 'the stations it is likely coming from.']),
            (flame, 'Your gas', ['Which terminal it landed at,', 'and where it started out.']),
            (bolt, 'The best time', ['When to charge the car', 'or put the washing on.'])]
    for draw, title, lines in rows:
        d.ellipse((M * S, y * S, (M + 130) * S, (y + 130) * S), fill=GREEN)
        if draw is pin: draw(d, M + 65, y + 63, 92, MINT, GREEN)
        elif draw is flame: draw(d, M + 65, y + 63, 86, MINT, GREEN)
        else: draw(d, M + 65, y + 65, 86, MINT)
        text(d, (M + 170, y - 4), title, head, INK)
        block(d, M + 170, y + 66, lines, body, MUTED, 52)
        y += 250
    text(d, (M, 1240), SITE, font('Bricolage', 42, 700), INK)
    return im
def post_3():
    im, d = canvas(1080, 1350, DARK)
    bars(d, 190, 225, 200, MINT)
    y = block(d, M, 400, ['Which part of', 'Britain ran on', 'the cleanest', 'power?'], font('Bricolage', 128, 700), MINT, 138)
    block(d, M, y + 36, ['A new league table every morning.'], font('Figtree', 44, 500), '#9db8b0', 60)
    strip(d, M, 1150, 900, 34)
    text(d, (M, 1240), SITE, font('Bricolage', 42, 700), MINT)
    return im
for name, fn in (('post_1_what', post_1), ('post_2_how', post_2), ('post_3_daily', post_3)):
    made[name] = save(fn(), 1080, 1350, name)

# banners: text stays central, clear of each platform's profile picture and phone crop
def banner(w, h, name):
    im, d = canvas(w, h, GREEN)
    title = font('Bricolage', int(h * .2), 700)
    text(d, (w / 2, h * .4), "Where's my energy from?", title, MINT, 'mm')
    text(d, (w / 2, h * .58), SITE, font('Figtree', int(h * .075), 500), MINT, 'mm')
    bar_w = w * .46
    strip(d, (w - bar_w) / 2, h * .7, bar_w, h * .04, gap=4)
    made[name] = save(im, w, h, name)
banner(1640, 624, 'banner_facebook')
banner(1500, 500, 'banner_x')

# one sheet showing the lot
W, P = 2200, 70
sheet = Image.new('RGB', (W, 3000), PALE)
d = ImageDraw.Draw(sheet)
def label(x, y, value, size=30, weight=600, fill=INK):
    f = ImageFont.truetype(str(FONTS / 'Figtree.ttf'), size); f.set_variation_by_axes([weight]); d.text((x, y), value, font=f, fill=fill)
def place(name, x, y, w, circle=False):
    src = made[name]
    h = round(w * src.height / src.width)
    thumb = src.resize((w, h), Image.LANCZOS)
    if circle:
        big = Image.new('L', (w * 4, h * 4), 0); ImageDraw.Draw(big).ellipse((0, 0, w * 4, h * 4), fill=255)
        sheet.paste(thumb, (x, y), big.resize((w, h), Image.LANCZOS))
    else:
        sheet.paste(thumb, (x, y))
    return h
f = ImageFont.truetype(str(FONTS / 'Bricolage.ttf'), 76); f.set_variation_by_axes([96, 700, 100]); d.text((P, 60), "Where's my energy from? Account images", font=f, fill=INK)
y = 190
label(P, y, 'Profile picture, shown as Instagram crops it. Pick one.'); y += 56
for i, n in enumerate(['profile_1_pin', 'profile_2_bolt', 'profile_3_fuel_ring', 'profile_4_light']):
    x = P + i * 520
    place(n, x, y, 400, True)
    place(n, x + 410, y + 300, 90, True)
    label(x, y + 412, f'{i + 1}', 28, 600, MUTED)
y += 490
label(P, y, 'Highlight covers: daily, league table, my area, gas, how it works'); y += 56
for i, n in enumerate(['highlight_today', 'highlight_league', 'highlight_my_area', 'highlight_gas', 'highlight_how']):
    src = made[n]
    crop = src.crop((0, 420, 1080, 1500))
    made[n + '_c'] = crop
    place(n + '_c', P + i * 410, y, 300, True)
y += 370
label(P, y, 'Launch posts, in posting order'); y += 56
hh = 0
for i, n in enumerate(['post_1_what', 'post_2_how', 'post_3_daily']):
    hh = place(n, P + i * 700, y, 660)
y += hh + 60
label(P, y, 'Facebook and X banners'); y += 56
h1 = place('banner_facebook', P, y, 1200)
place('banner_x', P + 1240, y, 820)
y += h1 + 70
sheet = sheet.crop((0, 0, W, y))
sheet.save(HERE / 'overview_sheet.png', optimize=True)
print('made', len([p for p in HERE.glob('*.png')]), sheet.size)
