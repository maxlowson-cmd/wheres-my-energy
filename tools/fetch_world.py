"""Saves each country's yearly electricity mix from Our World in Data (built on Ember's data) to social/world.json, for the 'Britain and the world' posts.
Run each January and August: python tools/fetch_world.py"""
import csv, io, json, pathlib, urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
URL = 'https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv'
COUNTRIES = ['United Kingdom', 'World', 'Denmark', 'Ireland', 'Germany', 'Netherlands', 'Spain', 'Portugal', 'France', 'Norway', 'Sweden',
             'Belgium', 'Italy', 'Poland', 'United States', 'China', 'India', 'Japan', 'Australia', 'Brazil', 'Canada']
FIELDS = ['wind_share_elec', 'solar_share_elec', 'renewables_share_elec', 'nuclear_share_elec', 'low_carbon_share_elec', 'fossil_share_elec', 'net_elec_imports_share_demand']
rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'wheresmyenergyfrom/1.0'}), timeout=120).read().decode('utf8'))))
year = max(int(r['year']) for r in rows if r['country'] == 'United Kingdom' and r['wind_share_elec'])
out = {'source': "Our World in Data, based on Ember's yearly electricity data", 'url': 'https://ourworldindata.org/electricity-mix', 'year': year, 'countries': {}}
for r in rows:
    if r['country'] in COUNTRIES and int(r['year']) == year and r['wind_share_elec']:
        out['countries'][r['country']] = {f.replace('_share_elec', '').replace('net_elec_imports_share_demand', 'imports'): round(float(r[f]), 1) for f in FIELDS if r[f]}
(HERE / 'social' / 'world.json').write_text(json.dumps(out, indent=1), encoding='utf8')
print(year, len(out['countries']), 'countries')
