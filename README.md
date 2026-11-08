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
