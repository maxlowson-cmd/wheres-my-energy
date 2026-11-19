"""Dispatch a no-post test of the agent and report what it did. Prints statuses only."""
import io, json, pathlib, sys, time, urllib.error, urllib.request, zipfile
S = pathlib.Path(__file__).resolve().parent  # tools/
sys.path.insert(0, str(S))
import social_keys as K
gh = K.github()[0]
R = 'https://api.github.com/repos/maxlowson-cmd/wheres-my-energy'
H = {'Authorization': f'Bearer {gh}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'wme-test/1.0'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


op = urllib.request.build_opener(NoRedirect)


def api(path, method='GET', body=None, raw=False):
    req = urllib.request.Request(R + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers=H)
    try:
        with op.open(req, timeout=120) as r:
            d = r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307):
            raise
        with urllib.request.urlopen(urllib.request.Request(e.headers['Location'], headers={'User-Agent': 'wme-test/1.0'}), timeout=180) as r:
            d = r.read()
    return d if raw else (json.loads(d) if d else None)


raw_api = api
def api(*a, **k):
    for i in range(30):
        try:
            return raw_api(*a, **k)
        except urllib.error.URLError:
            if isinstance(sys.exc_info()[1], urllib.error.HTTPError): raise
            time.sleep(20)
    raise SystemExit('no connection')
# def safe
sha = sys.argv[1]
for _ in range(40):
    run = api('/actions/workflows/build.yml/runs?per_page=1')['workflow_runs'][0]
    if run['head_sha'].startswith(sha) and run['status'] == 'completed':
        break
    time.sleep(15)
print('site build', run['head_sha'][:7], run['conclusion'])
before = api('/actions/workflows/social.yml/runs?per_page=1')['total_count']
api('/actions/workflows/social.yml/dispatches', 'POST', {'ref': 'main', 'inputs': json.loads(sys.argv[2])})
run = None
for _ in range(60):
    time.sleep(10)
    d = api('/actions/workflows/social.yml/runs?per_page=1')
    if d['total_count'] > before and d['workflow_runs'][0]['status'] == 'completed':
        run = d['workflow_runs'][0]
        break
if not run:
    raise SystemExit('run did not finish')
print('agent run', run['conclusion'])
job = api(f"/actions/runs/{run['id']}/jobs")['jobs'][0]
log = api(f"/actions/jobs/{job['id']}/logs", raw=True).decode(errors='replace')
for line in log.splitlines():
    t = line[29:]
    if t.startswith(('archived', 'pick', 'format', 'mock check', 'wording check', 'no usable', 'posted', 'image bytes', 'Traceback', 'RuntimeError', 'NameError', 'TypeError', 'KeyError', 'AttributeError', 'ValueError', 'playwright', 'anthropic')) or ' Error' in t[:60]:
        print(t[:300])
if run['conclusion'] == 'success' and sys.argv[3:4] == ['art']:
    art = api(f"/actions/runs/{run['id']}/artifacts")['artifacts'][0]
    z = zipfile.ZipFile(io.BytesIO(api(f"/actions/artifacts/{art['id']}/zip", raw=True)))
    from PIL import Image
    names = sorted(n for n in z.namelist() if n.startswith('post_'))
    print(names)
    d = json.loads(z.read('ideas.json'))
    print(d['kind'], d['album'])
    print(json.dumps(d['plan'], indent=1, ensure_ascii=False))
    print(d['caption'])
    (S / 'preview' / 'ideas.json').write_bytes(z.read('ideas.json'))
    got = [Image.open(io.BytesIO(z.read(n))) for n in names]
    cols, w, h = 4, 405, 506
    sheet = Image.new('RGB', (cols * (w + 10), ((len(got) + cols - 1) // cols) * (h + 10)), 'white')
    for i, im in enumerate(got):
        sheet.paste(im.resize((w, h), Image.LANCZOS), (i % cols * (w + 10), i // cols * (h + 10)))
    sheet.save(S / 'preview' / (sys.argv[4] if len(sys.argv) > 4 else 'album.jpg'), quality=88)
    if 'story.jpg' in z.namelist():
        (S / 'preview' / ('story_' + (sys.argv[4] if len(sys.argv) > 4 else 'album.jpg'))).write_bytes(z.read('story.jpg'))
elif run['conclusion'] != 'success':
    print(log[-1800:])
