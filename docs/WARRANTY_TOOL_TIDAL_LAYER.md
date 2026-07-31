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
| split | every way is **cut at its barrier nodes first** — a canal with a weir in the middle is fresh on one side, so a way is not an atomic unit |
| spread | breadth-first through shared OSM node ids across `waterway=canal\|river\|stream\|drain\|ditch` |
| stop | `lock_gate`, `weir`, `dam`, `floodgate`, `sluice_gate`, `tidal_gate`, `check_dam` — on a node, as a crossing way, **or within 25 m of the channel** (most structures are drawn offset and share no node) |
| clip | **clip the coordinates** to within 3 mi of the coast, emitting each surviving run separately (strictest provision is 1 mi) |

Input scale: 21,914 waterways, 136,068 nodes, **2,936 barrier nodes** (1,307 recovered by
geometric snapping), split into 20,726 reaches, over `24.40,-82.60,27.70,-79.90`. Output:
`assets/tidal.geojson`, **0.93 MB**, 3,639 geometries.

## The honesty rule — read this before changing the UI

**159 reaches are `tagged`; 4,855 are `inferred`.** `tagged` means OSM tags *that reach*
`tidal=yes`/`salt=yes`. Everything else the fill reaches — including a canal that plainly opens
onto the Intracoastal — is `inferred`, because touching salt water at one end says nothing about
the other end. OSM barrier coverage is incomplete, so an inferred reach can be wrong, and a false
positive tells a homeowner their warranty is void when it is not. Therefore:

- **Only `tagged` water may move a verdict.** `nearestSaltwater()` takes `min(coastline, tagged)`.
- An `inferred` reach that is nearer gets a separate dashed line on the map, a plain-language
  block saying it *may* be tidal, and — only when it would actually change the answer — an "If
  tidal" column beside the verdict. It never silently flips anything.
- Outside the layer's coverage box the tool says so ("tidal canals and rivers are mapped for South
  Florida only") instead of implying there is none — `coastline.geojson` is statewide, this is not.
- `scripts/check_tidal_layer.py` **asserts** this and exits non-zero on failure. Its pins are
  Golden Gate Estates (Naples), the inland reach of Snake Creek Canal behind S-29, and Plantation:
  nothing may be `tagged` within a mile of any of them.

### The bug this rule was written for, which we shipped anyway

The first build (2722947) labelled a reach `tagged` if *either endpoint* touched the coastline, and
applied that to the **whole way**. Result: a 43-mile Intracoastal way, `Golden Gate Main Canal`
(23.6 mi), `Snake Creek Canal` (18.9 mi) and `Little River Canal` (10.9 mi) all shipped as
authoritative salt water for their entire length, past unsplit control structures. Golden Gate
Estates — a large residential area in the Naples branch's own territory, 8.2 mi from the sea and
miles behind the weirs — was told two of four materials were **VOID**, from fresh water. Caught in
review, not by the tool's own checks, which is why those checks now assert.

## What it changed, verified live (Playwright, rendered output)

| address | before | after |
|---|---|---|
| 1701 NW N River Dr, Miami (Miami River) | 2.1 mi → everything safe | **488 ft to salt water (tidal)** → ZAM steel VOID for some brands |
| 1350 SW 21st Ter, Fort Lauderdale (New River) | 2,341 ft | **1,404 ft tidal** — crosses the 1,500 ft line |
| 10307 Utopia Cir N, Boynton Beach | 5.6 mi | 5.6 mi open, **possible** tidal flagged, verdicts unchanged |
| 100 Worth Ave, Palm Beach | 361 ft | 361 ft — open salt water still dominates |
| Golden Gate Blvd W, Naples | — | 9.7 mi open, possible tidal 9.2 mi, **all materials warranty-safe** (was VOID on two) |
| 1 Independent Dr, Jacksonville | 2,640 ft + a claim about water 193 mi away | 491 ft, and states tidal water is unmapped there |

⚠️ After the fix the Miami River is `inferred`, not `tagged` — OSM does not tag it. So it raises the
caveat and the "if that canal is tidal" second verdict rather than moving the headline. That is the
deliberate trade: we accept some under-warning to eliminate false "void".

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
