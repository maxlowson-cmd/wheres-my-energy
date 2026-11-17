"""After each site build, tell Telegram (through the relay) when building starts failing, every 6 hours while it keeps failing,
and when it works again. Silent while all is well. Needs SOCIAL_KEY, GITHUB_TOKEN, RESULT (success or failure) and the run's ids."""
import json, os, urllib.request

REPO, RUN, RESULT = os.environ['GITHUB_REPOSITORY'], int(os.environ['GITHUB_RUN_ID']), os.environ['RESULT']
RELAY = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev'
GH = {'Authorization': f"Bearer {os.environ['GITHUB_TOKEN']}", 'Accept': 'application/vnd.github+json', 'User-Agent': 'wme-build-alert'}
REMIND = 12  # builds run every 30 minutes, so a reminder every 6 hours


def gh(path):
    return json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.github.com/repos/{REPO}{path}', headers=GH), timeout=30))


def telegram(text):
    req = urllib.request.Request(f'{RELAY}/social', data=json.dumps({'op': 'telegram', 'text': text}).encode(), method='POST',
                                 headers={'X-Key': os.environ['SOCIAL_KEY'], 'Content-Type': 'text/plain', 'User-Agent': 'wme-build-alert'})
    print('telegram', urllib.request.urlopen(req, timeout=30).status)


def main():
    runs = [r for r in gh('/actions/workflows/build.yml/runs?status=completed&per_page=40')['workflow_runs'] if r['id'] != RUN]
    streak = 0  # failures in a row before this one
    for r in runs:
        if r['conclusion'] != 'failure':
            break
        streak += 1
    link = f'https://github.com/{REPO}/actions/runs/{RUN}'
    if RESULT == 'failure':
        if streak % REMIND == 0:
            hours = (streak + 1) / 2
            telegram(("The site build failed, so the live page isn't getting new readings." if streak == 0 else f'The site build is still failing ({streak + 1} in a row, about {hours:g} hours).')
                     + "\n\nVisitors still get a live power mix and best times; the station map, gas flows and prices pause once the page's readings are 12 hours old."
                     + f'\n\nIt retries every 30 minutes by itself. Log: {link}')
        else:
            print('failure', streak + 1, 'in a row; next reminder at', (streak // REMIND + 1) * REMIND + 1)
    elif streak:
        telegram(f'Fixed: the site build is working again after {streak} failed {"build" if streak == 1 else "builds"}. The live page has fresh readings.')
    else:
        print('all well')


try:
    main()
except Exception as e:  # never fail the run over the alert itself, or the next good build would read as a recovery
    print('alert not sent:', type(e).__name__, e)
