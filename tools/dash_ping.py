"""The numbers dashboard's two signals, using keys kept in the Claude folder (never printed):
  python dash_ping.py done   stamps the GitHub secret DASH_REFRESHED, which .github/workflows/dash_watch.yml checks each day
  telegram(text)             sends a message through the relay, for problems the script can see itself"""
import base64, datetime as dt, json, pathlib, re, sys, urllib.request, zipfile

KEYS = pathlib.Path(__file__).resolve().parent.parent.parent  # the Claude folder, outside the code
RELAY = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev/social'
SECRETS = 'https://api.github.com/repos/maxlowson-cmd/wheres-my-energy/actions/secrets'


def telegram(text):
    key = (KEYS / 'wme-social-key.txt').read_text(encoding='utf8').strip()
    req = urllib.request.Request(RELAY, data=json.dumps({'op': 'telegram', 'text': text}).encode(), method='POST',
                                 headers={'X-Key': key, 'Content-Type': 'text/plain', 'User-Agent': 'wme-dashboard/1.0'})
    return urllib.request.urlopen(req, timeout=30).status


def github_token():
    with zipfile.ZipFile(KEYS / 'Git-Token.pages') as z:
        raw = b''.join(z.read(n) for n in z.namelist() if n.endswith('.iwa'))
    return max(re.findall(rb'(?:github_pat_|ghp_)[A-Za-z0-9_]{30,}', raw), key=len).decode()


def stamp():
    from nacl import encoding, public
    head = {'Authorization': f'Bearer {github_token()}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'wme-dashboard/1.0'}
    pk = json.load(urllib.request.urlopen(urllib.request.Request(SECRETS + '/public-key', headers=head), timeout=30))
    when = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    sealed = base64.b64encode(public.SealedBox(public.PublicKey(pk['key'].encode(), encoding.Base64Encoder())).encrypt(when.encode())).decode()
    req = urllib.request.Request(SECRETS + '/DASH_REFRESHED', method='PUT', data=json.dumps({'encrypted_value': sealed, 'key_id': pk['key_id']}).encode(),
                                 headers={**head, 'Content-Type': 'application/json'})
    return when, urllib.request.urlopen(req, timeout=30).status


if __name__ == '__main__' and sys.argv[1:] == ['done']:
    when, status = stamp()
    print('stamped', when, status)
