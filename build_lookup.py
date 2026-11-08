"""One-off: map GB postcode districts to Carbon Intensity regions, stored compactly as area default + exceptions."""
import json, collections, pathlib, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
AREAS = """AB AL B BA BB BD BH BL BN BR BS CA CB CF CH CM CO CR CT CV CW DA DD DE DG DH DL DN DT DY E EC EH EN EX FK FY G GL GU HA HD HG HP HR HS HU HX IG IP IV KA KT KW KY L LA LD LE LL LN LS LU M ME MK ML N NE NG NN NP NR NW OL OX PA PE PH PL PO PR RG RH RM S SA SE SG SK SL SM SN SO SP SR SS ST SW SY TA TD TF TN TQ TR TS TW UB W WA WC WD WF WN WR WS WV YO ZE""".split()
def region(pc):
    try:
        req = urllib.request.Request(f'https://api.carbonintensity.org.uk/regional/postcode/{pc}', headers={'Accept': 'application/json', 'User-Agent': 'when-to-run/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return pc, json.load(r)['data'][0]['regionid']
    except urllib.error.HTTPError:
        return pc, None
    except Exception:
        return pc, 'retry'
codes = [f'{a}{n}' for a in AREAS for n in range(0, 31)]
with ThreadPoolExecutor(8) as ex: got = dict(ex.map(region, codes))
retry = [c for c, v in got.items() if v == 'retry']
with ThreadPoolExecutor(3) as ex: got.update(dict(ex.map(region, retry)))
found = {c: v for c, v in got.items() if isinstance(v, int)}
by = collections.defaultdict(dict)
for c, v in found.items():
    by[''.join(x for x in c if x.isalpha())][c] = v
areas, exc = {}, {}
for a, d in by.items():
    top = collections.Counter(d.values()).most_common(1)[0][0]
    areas[a] = top
    exc.update({c: v for c, v in d.items() if v != top})
pathlib.Path(__file__).with_name('lookup.json').write_text(json.dumps({'areas': areas, 'exceptions': exc}, separators=(',', ':')))
print('calls', len(codes), 'matched', len(found), 'failed', sum(1 for v in got.values() if v == 'retry'), 'areas', len(areas), 'exceptions', len(exc), 'missing', sorted(set(AREAS) - set(areas)))
print({k: areas.get(k) for k in ['SW', 'M', 'EH', 'CF', 'B', 'AB', 'BS']})
