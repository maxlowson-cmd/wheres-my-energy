"""Daily check that the private numbers dashboard refreshed this morning. The refresh runs on the owner's computer and stamps the
secret DASH_REFRESHED when it finishes; if the stamp is over 20 hours old, Telegram says so. Silent while all is well."""
import datetime as dt, json, os, urllib.request

RELAY = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev/social'
stamp = os.environ.get('DASH_REFRESHED', '').strip()
now = dt.datetime.now(dt.timezone.utc)
try:
    age = (now - dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds() / 3600
except ValueError:
    age = None
if age is not None and age <= 20:
    print(f'refreshed {age:.1f} hours ago')
else:
    when = f'Its last good update was {age / 24:.0f} days ago.' if age and age >= 36 else 'Its last good update was yesterday.' if age else 'It has no record of a good update.'
    text = (f"The numbers dashboard didn't update this morning. {when} The refresh runs on your computer at about 09:00, so the Claude app "
            "may have been closed, or the run stopped partway. Ask Claude to check the 'Where's My Energy Numbers refresh' run.")
    req = urllib.request.Request(RELAY, data=json.dumps({'op': 'telegram', 'text': text}).encode(), method='POST',
                                 headers={'X-Key': os.environ['SOCIAL_KEY'], 'Content-Type': 'text/plain', 'User-Agent': 'wme-dash-watch'})
    print('telegram', urllib.request.urlopen(req, timeout=30).status)
