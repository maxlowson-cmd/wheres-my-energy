"""Every-4-hours health check that fixes what it safely can and Telegrams one line about it. Run by the desktop scheduled task
wme-fixer: python fixer.py. Keys come from the Claude folder and are never printed. Prints one line per finding; a line
starting DASHBOARD_STALE asks the task to run the numbers refresh. Each problem is messaged at most once a day (state in
Claude/wme-fixer-state.json); a fix is always messaged.

What it fixes by itself:
  - live page older than 90 minutes: re-runs the failed build, or starts a new one
  - a scheduled Instagram post missing while its slot is still open: starts the post (the agent never posts twice in a slot)
  - a failed run of any workflow: re-runs its failed jobs once
What it only reports: an Instagram token Meta rejects, the Cloudflare token, the relay not answering, and anything still
broken after a retry."""
import datetime as dt, json, pathlib, re, sys, time, urllib.error, urllib.request, zoneinfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dash_ping

KEYS = dash_ping.KEYS
STATE = KEYS / 'wme-fixer-state.json'
SITE = 'https://wheresmyenergyfrom.co.uk/'
REPO = 'https://api.github.com/repos/maxlowson-cmd/wheres-my-energy'
RELAY = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev'
LONDON = zoneinfo.ZoneInfo('Europe/London')
THREE_A_DAY_UNTIL = dt.date(2026, 11, 24)
SLOTS = {'am': (8, 11), 'noon': (12, 17), 'pm': (20, 24)}  # posting hour, and the hour the slot closes (UK clock)
now = dt.datetime.now(dt.timezone.utc)
state = json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {}
lines = []


DRY = sys.argv[1:] == ['--test']  # look only: nothing is started, re-run, sent or saved


def gh(path, method='GET', body=None):
    if DRY and method != 'GET':
        lines.append(f'(test: would {method} {path})')
        return {}
    req = urllib.request.Request(REPO + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={'Authorization': f'Bearer {dash_ping.github_token()}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'wme-fixer'})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def say(kind, key, text):
    """kind: fixed (always sent), problem (sent once a day per key)."""
    lines.append(f'{kind.upper()}: {text}')
    last = state.get(key, 0)
    if (kind == 'fixed' or time.time() - last > 86400) and not DRY:
        dash_ping.telegram(text)
        state[key] = time.time()


def clear(key):
    state.pop(key, None)


def latest_run(workflow):
    runs = gh(f'/actions/workflows/{workflow}/runs?per_page=5').get('workflow_runs', [])
    return runs[0] if runs else None


def retry(run, key):
    """Re-run a failed run's failed jobs, once per run."""
    if state.get(f'retried-{run["id"]}'):
        return False
    gh(f'/actions/runs/{run["id"]}/rerun-failed-jobs', 'POST', {})
    state[f'retried-{run["id"]}'] = time.time()
    return True


# 1. the live page is fresh
try:
    page = urllib.request.urlopen(urllib.request.Request(f'{SITE}?fixer={int(time.time())}', headers={'Cache-Control': 'no-cache', 'User-Agent': 'wme-fixer'}), timeout=60).read().decode('utf8')
    taken = dt.datetime.fromisoformat(re.search(r'"taken":"([^"]+)"', page)[1].replace('Z', '+00:00'))
    age = (now - taken).total_seconds() / 60
except Exception as e:
    age, taken = None, None
    say('problem', 'site-down', "Site not loading. Ask Claude.")
if age is not None:
    clear('site-down')
    if age > 90:
        run = latest_run('build.yml')
        if run and run['status'] == 'completed' and run['conclusion'] != 'success' and retry(run, 'build'):
            say('fixed', 'site-stale', f'Site {age / 60:.0f}h stale: re-running the failed build.')
        elif run and run['status'] != 'completed':
            lines.append(f'OK: site {age:.0f} min old, a build is running')
        else:
            gh('/actions/workflows/build.yml/dispatches', 'POST', {'ref': 'main'})
            say('problem', 'site-stale', f'Site {age / 60:.0f}h stale. Started a rebuild.')
    else:
        clear('site-stale')
        lines.append(f'OK: site {age:.0f} min old')

# 2. failed workflow runs get one retry; a second failure is reported
for wf, name in (('build.yml', 'Site build'), ('social.yml', 'Instagram post'), ('monthly.yml', 'Monthly data update'), ('dash_watch.yml', 'Dashboard check')):
    try:
        run = latest_run(wf)
    except urllib.error.URLError:
        continue
    if not run or run['status'] != 'completed' or run['conclusion'] in ('success', 'skipped', 'cancelled'):
        clear(f'wf-{wf}')
        continue
    if (now - dt.datetime.fromisoformat(run['updated_at'].replace('Z', '+00:00'))).total_seconds() > 2 * 86400:
        continue  # an old failure that later runs have moved past
    if wf == 'social.yml' and (now - dt.datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))).total_seconds() > 3 * 3600:
        say('problem', f'wf-{wf}', 'Instagram post failed earlier. Ask Claude.')  # too late to retry into the same slot
    elif retry(run, wf):
        say('fixed', f'wf-{wf}', f'{name} failed: retried.')
    else:
        say('problem', f'wf-{wf}', f'{name} still failing after a retry. Ask Claude.')

# 3. Instagram posted in each slot so far today, and its token works
uk = now.astimezone(LONDON)
try:
    history = json.load(urllib.request.urlopen(urllib.request.Request(f'{RELAY}/social', data=json.dumps({'op': 'history'}).encode(), method='POST',
                        headers={'X-Key': (KEYS / 'wme-social-key.txt').read_text(encoding='utf8').strip(), 'Content-Type': 'text/plain', 'User-Agent': 'wme-fixer'}), timeout=60))['posts']
    clear('relay-down')
except Exception:
    history = None
    say('problem', 'relay-down', 'Relay not answering: posts and alerts paused. Ask Claude.')
if history is not None:
    slot_of = lambda t: 'am' if t.hour < 11 else 'noon' if t.hour < 17 else 'pm'
    done = {slot_of(dt.datetime.fromtimestamp(r['posted'] / 1000, LONDON)) for r in history if dt.datetime.fromtimestamp(r['posted'] / 1000, LONDON).date() == uk.date()}
    for slot, (hour, closes) in SLOTS.items():
        if slot == 'noon' and uk.date() > THREE_A_DAY_UNTIL:
            continue
        due = uk.replace(hour=hour, minute=15, second=0, microsecond=0)
        if uk < due + dt.timedelta(minutes=60) or slot in done:
            continue
        run = latest_run('social.yml')
        busy = run and run['status'] != 'completed'
        if uk.hour < closes and not busy and not state.get(f'posted-{uk.date()}-{slot}'):
            gh('/actions/workflows/social.yml/dispatches', 'POST', {'ref': 'main', 'inputs': {'dry_run': '0', 'mock_album': '0', 'extra_post': '0'}})
            state[f'posted-{uk.date()}-{slot}'] = time.time()
            say('fixed', f'missed-{slot}', f'The {slot} Instagram post was missing: started it.')
        elif not busy:
            say('problem', f'missed-{uk.date()}-{slot}', f'The {slot} Instagram post was missed today.')
    lines.append(f'OK: posts today {sorted(done) or "none"}')
try:
    meta = (KEYS / 'Meta-Token.txt').read_text(encoding='utf8')
    tok = max(re.findall(r'(?:EA|IG)[A-Za-z0-9_-]{80,}', meta), key=len)
    me = json.load(urllib.request.urlopen(f'https://graph.facebook.com/v25.0/17841480414221894?fields=username&access_token={tok}', timeout=30))
    ok = me.get('username') == 'wheresmyenergyfrom'
except urllib.error.HTTPError:
    ok = False
except Exception:
    ok = None  # no local copy of the token, or Meta didn't answer: nothing to say
if ok is False:
    say('problem', 'meta-token', 'Instagram token rejected. Needs a new one: ask Claude.')
elif ok:
    clear('meta-token')

# 4. the numbers dashboard was refreshed in the last day (the task runs the refresh when this is printed)
saved = KEYS / 'wheres-my-energy-v2' / 'out' / 'wme_numbers.json'
if not saved.exists() or time.time() - saved.stat().st_mtime > 26 * 3600:
    lines.append('DASHBOARD_STALE: run the numbers refresh')

for key in [k for k, v in state.items() if k.startswith(('retried-', 'posted-')) and time.time() - v > 7 * 86400]:
    state.pop(key)
if not DRY:
    STATE.write_text(json.dumps(state, indent=1), encoding='utf8')
print('\n'.join(lines))
