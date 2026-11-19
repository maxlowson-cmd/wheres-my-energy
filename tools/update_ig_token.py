"""Check the new Instagram token can read reach, then store it as the agent's GitHub secret. Prints statuses only, never the token.
Usage: python update_ig_token.py [--store]"""
import base64, json, pathlib, sys, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import social_keys as K
from nacl import encoding, public

STORE = '--store' in sys.argv
IG = '17841480414221894'
G = 'https://graph.facebook.com/v25.0'
found = K.meta()
print('tokens found:', len(found), '(want exactly 1)')
tok = found[0]


def g(path, **p):
    p['access_token'] = tok
    try:
        return json.load(urllib.request.urlopen(f'{G}{path}?{urllib.parse.urlencode(p)}', timeout=30))
    except urllib.error.HTTPError as e:
        return {'error': json.load(e).get('error', {})}


perms = g('/me/permissions')
granted = sorted(x['permission'] for x in perms.get('data', []) if x.get('status') == 'granted')
print('granted:', granted or perms.get('error', {}).get('message'))
need = {'instagram_basic', 'instagram_content_publish', 'instagram_manage_insights'}
print('missing:', sorted(need - set(granted)) or 'nothing')
media = g(f'/{IG}/media', fields='id,timestamp,media_type', limit=3)
ok = False
for m in media.get('data', [])[1:3]:  # skip the newest, which may be under a day old
    ins = g(f"/{m['id']}/insights", metric='reach,saved,shares')
    if 'error' in ins:
        print('post insights:', m['media_type'], 'refused:', ins['error'].get('message', '')[:120])
    else:
        ok = True
        print('post insights:', m['media_type'], [(x['name'], x['values'][0]['value']) for x in ins.get('data', [])])
acct = g(f'/{IG}/insights', metric='reach,profile_views,website_clicks', period='day', metric_type='total_value')
print('account insights:', acct.get('error', {}).get('message', '')[:120] or [(x['name'], x.get('total_value', {}).get('value')) for x in acct.get('data', [])])
pub = g(f'/{IG}', fields='username')
print('can still reach the account:', pub.get('username') == 'wheresmyenergyfrom')

if STORE:
    if not (ok and pub.get('username') == 'wheresmyenergyfrom'):
        raise SystemExit('not stored: the token cannot read reach or the account yet')
    R = 'https://api.github.com/repos/maxlowson-cmd/wheres-my-energy/actions/secrets'
    H = {'Authorization': f'Bearer {K.github()[0]}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'wme-token/1.0'}
    pk = json.load(urllib.request.urlopen(urllib.request.Request(R + '/public-key', headers=H), timeout=30))
    sealed = base64.b64encode(public.SealedBox(public.PublicKey(pk['key'].encode(), encoding.Base64Encoder())).encrypt(tok.encode())).decode()
    req = urllib.request.Request(f'{R}/INSTAGRAM_TOKEN', method='PUT', data=json.dumps({'encrypted_value': sealed, 'key_id': pk['key_id']}).encode(), headers={**H, 'Content-Type': 'application/json'})
    print('GitHub secret INSTAGRAM_TOKEN updated:', urllib.request.urlopen(req, timeout=30).status)
