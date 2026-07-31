# Metal-roof warranty tool — the tidal/brackish layer

**Shipped 2026-07-30.** Tool: `wp-plugin/perkins-metal-warranty/`, live on staging at
<https://1228404.us6.myftpupload.com/metal-roofing-warranty/> (plugin **1.1.0**).

## Why it exists

Tim, 2026-07-19: *"It does need a little bit of work though, the river my house is on in FTL
definitely is brackish, which carries salt water."* He sent three salinity sources (USGS water
level & salinity mapper, salinity.oceansciences.org, NOAA tides & currents salinity nowcast).
None had been used: the tool measured distance to OSM `natural=coastline` only and covered
brackish with one sentence telling the homeowner to judge for themselves.

That is a real mispricing of risk, because every provision in `zones.json` is written against
*"seacoast, salt or **brackish** water"*, out to a mile.

## The model

A South Florida canal is tidal **seaward** of a salinity control structure and fresh **landward**
of it. So *salt-carrying = connected to tidewater without crossing a structure.* That is what the
NOAA/USGS tools show interactively, and it is what `scripts/build_tidal_layer.py` computes once, at
build time, from OpenStreetMap:

| step | rule |
|---|---|
| seed | ways tagged `tidal=yes` / `salt=yes`, plus any waterway whose end lands within 60 m of the mapped coastline |
| spread | breadth-first through shared OSM node ids across `waterway=canal\|river\|stream\|drain\|ditch` |
| stop | `lock_gate`, `weir`, `dam`, `floodgate`, `sluice_gate`, `tidal_gate`, `check_dam` — tagged on a node or as a crossing way |
| clip | keep only geometry within 3 mi of the coast (strictest provision is 1 mi, so further inland cannot change a verdict) |

Input scale: 21,914 waterways, 136,068 nodes, 1,629 barrier nodes over
`24.40,-82.60,27.70,-79.90`. Output: `assets/tidal.geojson`, **0.97 MB**, 3,486 reaches.

## The honesty rule — read this before changing the UI

**813 reaches are `tagged`; 9,933 were `inferred` by connectivity.** OSM barrier coverage is
incomplete, so an inferred reach can be wrong — and a false positive tells a homeowner their
warranty is void when it is not. Therefore:

- **Only `tagged` water may move a verdict.** `nearestSaltwater()` takes `min(coastline, tagged)`.
- An `inferred` reach that is nearer gets a separate dashed line on the map, a plain-language
  block saying it *may* be tidal, and — only when it would actually change the answer — an "If
  tidal" column beside the verdict. It never silently flips anything.
- `scripts/check_tidal_layer.py` pins this against addresses whose answer we can reason about
  independently. The load-bearing one: **1200 S Pine Island Rd, Plantation** sits 5.92 mi from open
  water and shows an *inferred* reach 1,657 ft away. That must stay a caveat, never a "void".

## What it changed, verified live (Playwright, rendered output)

| address | before | after |
|---|---|---|
| 1701 NW N River Dr, Miami (Miami River) | 2.1 mi → everything safe | **488 ft to salt water (tidal)** → ZAM steel VOID for some brands |
| 1350 SW 21st Ter, Fort Lauderdale (New River) | 2,341 ft | **1,404 ft tidal** — crosses the 1,500 ft line |
| 10307 Utopia Cir N, Boynton Beach | 5.6 mi | 5.6 mi open / 5.7 mi confirmed tidal, **possible** tidal 1.0 mi flagged, verdicts unchanged |
| 100 Worth Ave, Palm Beach | 361 ft | 361 ft — open salt water still dominates |

## Rebuilding

```sh
.venv/bin/python scripts/build_tidal_layer.py --fetch   # Overpass -> ~/perkins-corpus/osm/ cache
.venv/bin/python scripts/build_tidal_layer.py           # cache -> assets/tidal.geojson
.venv/bin/python scripts/check_tidal_layer.py           # sanity-check against known addresses
```

Then bump `PERKINS_MWC_VERSION` (WordPress cache-busts assets on `?ver=`), zip the plugin folder,
and upload:

```sh
set -a; source .env; set +a
export WP_LOGIN_PW="$WP_PWD"      # the wp-admin WEB login, not the REST app password
PYTHONPATH=. .venv/bin/python scripts/wp_install_plugin.py /path/to/perkins-metal-warranty.zip
```

## Gotchas paid for once

- **Overpass answers HTTP 406 to a bare POST body.** It wants the query form-encoded as `data=`.
- **The Maps browser key is referrer-restricted and is NOT Terraform-managed** (only `squares_key`
  is). Key `perkins-setback-widget` now allows `perkins-setback.web.app`, `*.perkinsroofing.net`
  and the staging host. A rejected referrer returns HTTP 200 and reports through `gm_authFailure`,
  so `onerror` never fires — which is why the tool used to spin on "Locating and measuring…"
  forever. `checker.js` now handles that and has a 12 s backstop.
- **Nominatim does not know every address** (the Boynton one fails); Google's geocoder does. The
  offline checker uses Nominatim, so a miss there is a geocoder gap, not a layer gap.

## Not done

Live salinity readings. NOAA is model output and USGS is an interactive mapper — neither is a
per-address API. They informed the model (structures divide fresh from tidal) but nothing queries
them, and nothing should at runtime.
