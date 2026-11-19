# Where's My Energy From?

Type a British address and see where your electricity is likely coming from right now, plus the greenest hours to use it.

`build.py` fetches fresh data and writes the public page to `site/index.html`. It uses only the Python standard library.

| File | Purpose |
|---|---|
| `template.html` | The page itself: layout, styling and browser code |
| `build.py` | Fetches the forecast, mix and prices, then assembles the page |
| `refresh.py` | Fetches running stations and national mix from Elexon |
| `model.py` | Builds the map data from the grid lines, stations and renewable sites |
| `regions.py` | Draws the 14 electricity regions |
| `fetch_year.py` | Recalculates `year.json`, run monthly by GitHub Actions |
| `fetch_outcodes.py`, `build_lookup.py` | One-off lookups for postcode locations and regions |
| `data/` | Grid lines, station locations, renewable sites, boundaries and postcodes |

`.github/workflows/build.yml` rebuilds and publishes the site every 30 minutes.

To refresh the source files in `data/`, download new copies from the sources listed on the site. The renewables register is updated quarterly.

## Tools

Keys never live in this folder: every tool reads them from the Claude folder above it and never prints them.

| File | What it does |
|---|---|
| `tools/fixer.py` | Every-4-hours health check (desktop task `wme-fixer`): retries failed builds and posts, restarts a stale site, one-line Telegram |
| `tools/dashboard_feed.py` | Morning numbers for the private dashboard (desktop task `wme-numbers-refresh`), with Google figures from `google_feed.py` |
| `tools/dash_ping.py`, `tools/dash_watch.py` | The dashboard's finish stamp and the 11:30 GitHub check that warns if it's missing |
| `tools/build_alert.py` | Telegram when site builds start or stop failing |
| `tools/update_ig_token.py` | Check a new Instagram token, then `--store` it as the agent's GitHub secret |
| `tools/deploy_relay.py` | Put `worker/worker.js` live as the relay (needs a working Cloudflare token); `--instagram` also updates its token |
| `tools/dry2.py` | Run the Instagram agent on GitHub without posting and fetch what it would have made |
| `tools/fetch_world.py` | Refresh `social/world.json` (January and August) |

## Publishing

Work on `main` in this folder, then: `git pull --rebase origin main && git push origin main`. The pull picks up the monthly data commits the bot makes from 1 December.
