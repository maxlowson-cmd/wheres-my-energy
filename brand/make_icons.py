"""Draw the site icon (green circle, lightning bolt) as real files, because search engines only show an icon they can download.
Run once: python brand/make_icons.py. Writes brand/icon-512.png, icon-192.png, icon-48.png, favicon.ico and favicon.svg."""
import pathlib
from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
GREEN, PALE = (6, 112, 75), (242, 251, 247)
BOLT = [(18, 5), (9, 18), (15, 18), (14, 27), (23, 14), (17, 14)]  # the same path as the tab icon, on a 32-unit square
SVG = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='16' fill='#06704b'/><path d='M18 5 9 18h6l-1 9 9-13h-6z' fill='#f2fbf7'/></svg>\n"


def draw(size):
    big = size * 8  # draw large and shrink, for smooth edges
    im = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, big - 1, big - 1), fill=GREEN)
    d.polygon([(x * big / 32, y * big / 32) for x, y in BOLT], fill=PALE)
    return im.resize((size, size), Image.LANCZOS)


for n in (512, 192, 48):
    draw(n).save(HERE / f'icon-{n}.png')
draw(48).save(HERE / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])
(HERE / 'favicon.svg').write_text(SVG, encoding='utf8')
print('icons written')
