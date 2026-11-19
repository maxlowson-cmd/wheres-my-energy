"""Put worker/worker.js live as the relay, keeping every existing binding and secret, then confirm. Prints statuses only, never a key.
The Cloudflare token is read from Claude/wme-cloudflare-token.txt (or the .pages file). Optional: --instagram also stores the
token in Claude/Meta-Token.txt as the relay's INSTAGRAM_TOKEN secret.
Usage: python deploy_relay.py [--instagram]"""
import json, pathlib, re, sys, urllib.error, urllib.request, uuid, zipfile

HERE = pathlib.Path(__file__).resolve().parent
CODE, KEYS = HERE.parent, HERE.parent.parent
ACCT, NAME, API, UA = 'ced38c6956683936e25091d48e5edd93', 'wheres-my-energy-relay', 'https://api.cloudflare.com/client/v4', 'wheres-my-energy-deploy/1.0'


def text_of(name):
    p = KEYS / name
    if p.suffix == '.pages':
        with zipfile.ZipFile(p) as z:
            return b''.join(z.read(n) for n in z.namelist() if n.endswith('.iwa'))
    return p.read_bytes()


def raw_call(token, method, path, body=None, headers=None, raw_body=None):
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    h = {'Authorization': f'Bearer {token}', 'User-Agent': UA, **({'Content-Type': 'application/json'} if body is not None else {}), **(headers or {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(API + path, data=data, method=method, headers=h), timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def find_token():
    for name in ('wme-cloudflare-token.txt', 'wme-cloudflare-token.pages'):
        if not (KEYS / name).exists():
            continue
        for found in re.findall(rb'[A-Za-z0-9_-]{38,70}', text_of(name)):
            for start in range(4):  # a Pages file can stick a stray character on the front
                t = found[start:].decode()
                for path in ('/user/tokens/verify', f'/accounts/{ACCT}/tokens/verify'):
                    if raw_call(t, 'GET', path)[1].get('success'):
                        return t
    raise SystemExit('no working Cloudflare token: make a new one and save it as Claude/wme-cloudflare-token.txt')


token = find_token()
call = lambda *a, **k: raw_call(token, *a, **k)


def must(step, res):
    s, d = res
    if not d.get('success'):
        raise SystemExit(f"{step} failed: {s} {[(x.get('code'), x.get('message')) for x in d.get('errors', [])]}")
    print(step, 'ok')
    return d.get('result')


base = f'/accounts/{ACCT}/workers/scripts/{NAME}'
now = must('read settings', call('GET', f'{base}/settings'))['bindings']
print('bindings kept', sorted(b['name'] for b in now))
facts = json.dumps(json.loads((CODE / 'facts.json').read_text(encoding='utf8')), separators=(',', ':'))
code = (CODE / 'worker' / 'worker.js').read_text(encoding='utf8')
assert code.count('/*FACTS*/[]/*END*/') == 1
code = code.replace('/*FACTS*/[]/*END*/', facts).encode('utf8')
meta = {'main_module': 'worker.js', 'compatibility_date': '2026-10-01', 'bindings': [{'type': 'inherit', 'name': b['name']} for b in now]}
b = uuid.uuid4().hex
body = (f'--{b}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n'.encode() + json.dumps(meta).encode()
        + f'\r\n--{b}\r\nContent-Disposition: form-data; name="worker.js"; filename="worker.js"\r\nContent-Type: application/javascript+module\r\n\r\n'.encode()
        + code + f'\r\n--{b}--\r\n'.encode())
must('upload', call('PUT', base, headers={'Content-Type': f'multipart/form-data; boundary={b}'}, raw_body=body))
vers = must('versions', call('GET', f'{base}/versions'))
v = (vers['items'] if isinstance(vers, dict) else vers)[0]['id']
# the upload alone can leave the old code serving for minutes, so make the new version live explicitly
must('deploy', call('POST', f'{base}/deployments', {'strategy': 'percentage', 'versions': [{'version_id': v, 'percentage': 100}]}))
must('subdomain', call('POST', f'{base}/subdomain', {'enabled': True}))
if '--instagram' in sys.argv:
    ig = max(re.findall(r'(?:EA|IG)[A-Za-z0-9_-]{80,}', (KEYS / 'Meta-Token.txt').read_text(encoding='utf8')), key=len)
    must('INSTAGRAM_TOKEN secret', call('PUT', f'{base}/secrets', {'name': 'INSTAGRAM_TOKEN', 'text': ig, 'type': 'secret_text'}))
dep = must('deployments', call('GET', f'{base}/deployments'))['deployments'][0]
print('live version is newest:', dep['versions'][0]['version_id'] == v)
print('schedules', [x['cron'] for x in must('schedules', call('GET', f'{base}/schedules'))['schedules']])
