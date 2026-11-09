"""Replace data/repd.csv with the government's latest Renewable Energy Planning Database, if the new file looks sound."""
import csv, io, json, pathlib, re, urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = 'https://www.gov.uk/api/content/government/publications/renewable-energy-planning-database-quarterly-extract'
UA = {'User-Agent': 'wheres-my-energy-data/1.0'}
NEEDED = {'Technology Type', 'Development Status (short)', 'Installed Capacity (MWelec)', 'X-coordinate', 'Y-coordinate', 'Operational', 'Site Name'}

with urllib.request.urlopen(urllib.request.Request(PAGE, headers=UA), timeout=60) as r:
    text = json.dumps(json.load(r))
links = re.findall(r'https://assets\.publishing\.service\.gov\.uk/[^"\ ]+?\.csv', text)
if not links:
    raise SystemExit('no CSV link on the database page')
with urllib.request.urlopen(urllib.request.Request(links[0], headers=UA), timeout=120) as r:
    raw = r.read()
rows = list(csv.DictReader(io.StringIO(raw.decode('latin-1'))))
target = HERE / 'data' / 'repd.csv'
old = sum(1 for _ in csv.DictReader(io.StringIO(target.read_bytes().decode('latin-1'))))
missing = NEEDED - set(rows[0].keys() if rows else [])
if missing or len(rows) < old * .9:
    raise SystemExit(f'new file rejected: {len(rows)} rows against {old}, missing {sorted(missing)}')
target.write_bytes(raw)
print('updated', len(rows), 'rows from', links[0].rsplit('/', 1)[-1])
