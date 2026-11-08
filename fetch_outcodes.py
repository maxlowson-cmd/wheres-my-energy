"""One-off: centre point of every GB postcode district, from postcodes.io. Writes data/outcodes.json."""
import json, pathlib, string, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
AREAS = """AB AL B BA BB BD BH BL BN BR BS CA CB CF CH CM CO CR CT CV CW DA DD DE DG DH DL DN DT DY E EC EH EN EX FK FY G GL GU HA HD HG HP HR HS HU HX IG IP IV KA KT KW KY L LA LD LE LL LN LS LU M ME MK ML N NE NG NN NP NR NW OL OX PA PE PH PL PO PR RG RH RM S SA SE SG SK SL SM SN SO SP SR SS ST SW SY TA TD TF TN TQ TR TS TW UB W WA WC WD WF WN WR WS WV YO ZE""".split()
SPLIT = ['EC1', 'EC2', 'EC3', 'EC4', 'WC1', 'WC2', 'W1', 'SW1', 'E1', 'N1', 'NW1', 'SE1']
found = {}


def get(code):
    try:
        req = urllib.request.Request(f'https://api.postcodes.io/outcodes/{code}', headers={'Accept': 'application/json', 'User-Agent': 'where-my-energy/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)['result']
        return code, (d['latitude'], d['longitude']) if d.get('latitude') else None
    except urllib.error.HTTPError:
        return code, None
    except Exception:
        return code, 'retry'


def area(a):
    out, miss = {}, 0
    for n in range(0, 100):
        code, v = get(f'{a}{n}')
        if v == 'retry':
            code, v = get(code)
        if isinstance(v, tuple):
            out[code] = v; miss = 0
        else:
            miss += 1
            if miss >= 15 and n >= 15:
                break
    return out


with ThreadPoolExecutor(8) as ex:
    for out in ex.map(area, AREAS):
        found.update(out)
    letters = [d + c for d in SPLIT for c in string.ascii_uppercase]
    for code, v in ex.map(get, letters):
        if isinstance(v, tuple):
            found[code] = v
(HERE / 'data' / 'outcodes.json').write_text(json.dumps(found, separators=(',', ':')), encoding='utf8')
print('districts', len(found), 'areas', len({''.join(c for c in k if c.isalpha())[:2] for k in found}), {k: found.get(k) for k in ['SW9', 'M3', 'EC4Y', 'EH2', 'CF10']})
