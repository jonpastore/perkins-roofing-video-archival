# Metal-roof warranty tool — the tidal/brackish layer

**Shipped 2026-07-30.** Tool: `wp-plugin/perkins-metal-warranty/`, live on staging at
<https://1228404.us6.myftpupload.com/metal-roofing-warranty/> (plugin **1.1.2**).

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

Input scale (statewide since 2026-07-31): 55,749 waterways, 674,049 nodes, **12,292 barrier nodes**
(1,810 recovered by geometric snapping), split into 54,509 reaches, over `24.30,-87.80,31.10,-79.80`.
Output: `assets/tidal.geojson`, **1.96 MB**, 6,482 geometries, of which 388 `tagged`, 86 `measured`
salt and 54 `measured` fresh. Was South Florida only (`24.40,-82.60,27.70,-79.90`): 21,914 waterways,
0.93 MB, 3,639 geometries.

✅ **FIXED 2026-07-31 — the clip now applies to `inferred` only.** It measures distance to the
COASTLINE while the 1-mile provision bounds ADDRESS-to-water distance, so clipping evidence by it
hid brackish water people live beside: a house 500 ft from the tidal St. Johns got no answer because
the river is 14 mi from the ocean. Anything carrying evidence — a gauge reading or an explicit OSM
tidal tag — is kept wherever it is; only `inferred` reaches are clipped at `REACH_MI`. Cost
**+0.09 MB**, because evidence is rare. Widening `REACH_MI` for everything was rejected: it would
have multiplied the asset with inland ditches, the reaches most likely to be wrong.

⚠️ **Two limits remain, and they are not the same limit.** 8 of the 18 far live gauges are still
absent because they never snap to mapped water within `GAUGE_SNAP_M` (250 m) — OSM maps those wide
rivers as `natural=water` polygons rather than `waterway` lines, so there is no line to snap to.

⚠️ **A reading is evidence about the water TODAY.** `siteStatus=active` does not mean "reporting":
65 of 171 gauges had last reported over 30 days ago, 33 of them classified salt/brackish, the worst
5,415 days old carrying 42,300 µS/cm into live verdicts. `_reading_expired` drops them, and an
undateable timestamp expires closed.

## The honesty rule — read this before changing the UI

**388 reaches are `tagged`; 9,282 are `inferred`.** `tagged` means OSM tags *that reach*
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
| 1701 NW N River Dr, Miami (Miami River) | 2.1 mi, no mention of the river | 2.1 mi headline + **"water 488 ft away may be tidal"** and an "if tidal: VOID for some brands" column |
| 1350 SW 21st Ter, Fort Lauderdale (New River) | 2,341 ft, no mention | 2,341 ft + the river at 1,404 ft raised as a caveat |
| 10307 Utopia Cir N, Boynton Beach | 5.6 mi | 5.6 mi open, **possible** tidal flagged, verdicts unchanged |
| 100 Worth Ave, Palm Beach | 361 ft | 361 ft — open salt water still dominates |
| Golden Gate Blvd W, Naples | — | 9.7 mi open, possible tidal 9.2 mi, **all materials warranty-safe** (was VOID on two) |
| 1 Independent Dr, Jacksonville | 2,640 ft + a claim about water 193 mi away | 491 ft, and states tidal water is unmapped there |

⚠️ After the fix the Miami River is `inferred`, not `tagged` — OSM does not tag it. So it raises the
caveat and the "if that canal is tidal" second verdict rather than moving the headline. That is the
deliberate trade: we accept some under-warning to eliminate false "void".

## Rebuilding

```sh
.venv/bin/python scripts/build_tidal_layer.py --fetch   # Overpass + FDEP + NHD -> caches
.venv/bin/python scripts/build_tidal_layer.py           # caches -> assets/tidal.geojson
.venv/bin/python scripts/check_tidal_layer.py           # sanity-check against known addresses
```

`--fetch` pulls three sources; `--fetch-wbid` and `--fetch-nhd` refresh one each (minutes, versus
the better part of an hour for the statewide Overpass pull). **The NHD fetch is bounded by the FDEP
cache** — it walks the 165 quarter-degree tiles the marine WBIDs touch — so fetch WBIDs first.

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

## ✅ CLOSED 2026-08-07 — the geometry hole under `mapped` (USGS NHD)

`mapped` classifies reaches. It cannot classify a reach that is not in the graph, and every reach
came from an OSM `waterway=*` **line**. **South Florida finger canals are routinely drawn in OSM as
untagged `natural=water` polygons instead** — no line, no tidal tag, invisible to the fill.

Found the day Tim finally sent the address of the client this whole feature was built for:

| 188 Lone Pine Drive, Palm Beach Gardens | |
|---|---|
| what the live tool said | 3,079 ft to salt water → **all three steels warranty-safe** |
| USGS NHD | `CANAL/DITCH` **117 ft** from the house |
| the canal's NHD network | Earman River, North Palm Beach Waterway, Frenchmans Creek → the ICWW |
| FDEP at that canal | WBID 3226W1, ESTUARY, **Class III-Marine** |
| on the ground (Tim) | "that canal is literally in her backyard; she has a dock and a boat" |
| OSM | 19 unnamed pond polygons, no waterway line |

So the tool cleared steel for the exact customer whose rusted-out steel chimney cap was the reason
Tim asked for it — arguing the competing roofers' case, on his own showcase job.

**The fix**: NHD flowlines (ftype 336/460/558/334) over the marine-WBID tiles are merged into the
graph as untagged ways *before* the barrier snap, so they are cut by structures and must earn
`mapped` on exactly the same terms as OSM geometry. NHD reaches that only reach `inferred` are
dropped at emit — they move no verdict and NHD's coastal density is ~10x OSM's.

```
https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query
where=ftype IN (336,460,558,334)   →  ~164k flowlines over 165 tiles, free, keyless
```

### Two lessons, both cheap to repeat

1. **A false CLEAR is silent.** Every pin in this file bounded the false VOID, because a homeowner
   wrongly told VOID complains. Nobody reports being wrongly told their steel roof is fine — they
   just buy it from the roofer who said yes. `MUST_REACH_NEAR` / the waterfront pins in
   `tests/jobs/test_tidal_asset_invariants.py` are the mirror gate, and 188 Lone Pine Drive fails
   them on the pre-fix asset while every inland pin stays green.
2. **Do not verify hydrology against OSM.** The review that blessed `mapped` checked the layer by
   querying Overpass for waterways near the address — the layer's own upstream source. A check that
   shares a blind spot with the thing it checks always agrees with it. Cross-check against NHD.

A third, smaller one: `2400 PGA Blvd` sat in `check_tidal_layer.py` as "Tim's client" for a day.
It was a **stand-in picked before anyone had her address**, it passed, and it made the real case
look covered. A pin against a guessed address tests the guess.

## ✅ CLOSED 2026-08-06 — FDEP's marine classification (`mapped`)

The gap below was real for six days. It is closed by a source neither Tim nor we had looked at:
**FDEP classifies every Florida water body in law**, and `3M` (Class III-Marine) / `2` (Class II,
shellfish) *is* the state saying that water is marine.

```
https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/WBIDS/MapServer/0/query
where=CLASS IN ('2','3M')   →  1,358 polygons, free, keyless, statewide
```

⚠️ **The host 403s a default curl/urllib user agent** — same trap as SFWMD.

⚠️ **WBID polygons are BASIN polygons and cover dry land.** A dry inland lot inside an estuarine
basin returns 3M, so classifying the *address* would ship exactly the false VOID this file is
about. Only **reach geometry** is classified — a reach is in water by construction.

**The safety argument is the conjunction.** A reach becomes `mapped` only if it is *already*
`inferred` (connected to tidewater without crossing a structure) *and* FDEP independently
classifies its water body marine. Connectivity is weak because OSM's barrier coverage is
incomplete; the class is weak because the polygon covers land. They fail in unrelated ways.

| | before | after |
|---|---|---|
| New River south fork, FTL (Tim's own case) | 1,407 ft `inferred` — caveat | 1,407 ft **`mapped`** — moves the verdict |
| Miami River | 266 ft `inferred` | 266 ft **`mapped`** (C-6/Miami River lower segment) |
| PGA Blvd, Palm Beach Gardens (Tim's customer) | 3,517 ft to open water, steel CLEARED | 853 ft **`mapped`** (ICWW above Royal Palm Bridge) |
| Golden Gate Estates / Snake Creek inland / Plantation | safe | **unchanged** — 4.1 / 8.0 / 4.1 mi to verdict-moving water |

Layer: 310 tagged, **3,501 mapped**, 5,798 inferred, 61 measured salt, 42 measured fresh.
Asset 2.31 MB (was 1.96).

### ⚠️ Do NOT cite "82% held-out, up from 75%" — RETRACTED 2026-08-07

That comparison was written here and in PR #33 and it is not apples-to-apples. It is also not
evidence about the thing it was cited for.

- **The denominator changed before either build.** `42c1ead` (2026-07-31) made `readings()` omit
  stations with no series in the 30-day window and score a median instead of an instantaneous
  value. That dropped the 65 stale stations — "33 of them classified salt/brackish", i.e. exactly
  the gauges that were scoring as misses — taking the gauge population from 171 to 106. The 75%
  baseline is 128/171 under the old rule; today's 82% is 87/106 under the new one.
- **The metric is insensitive to the defect class it was quoted about.** Clipping `mapped` to the
  polygon removed 16.5 mi of live false-VOID geometry and held-out agreement did not move: still
  82%, still 16 salt / 1 fresh. A number unchanged by the removal of the worst false-VOID defect
  this feature has shipped cannot be offered as evidence about false-VOID risk.
- Half the numerator is free credit: of 106 gauges, 53 land in `none` and 45 of those are "we map
  no water here, gauge reads fresh". And the score weights a missed warning identically to a false
  VOID — the one asymmetry this layer exists for.

**The supportable sentence is "the clip cost no agreement", and it is now measured rather than
asserted.** `validate_tidal_against_gauges.py --asset <path>` scores an arbitrary asset, so a
before/after delta is reproducible. Run back-to-back on 2026-08-07 over the same 106 reporting
gauges:

```
pre-clip  (cb83aee)   HELD-OUT 87/106 = 82%   verdict-moving bucket 16 salt / 1 fresh
post-clip (96aafec)   HELD-OUT 87/106 = 82%   verdict-moving bucket 16 salt / 1 fresh
```

Identical — which is the point twice over: the clip cost nothing, **and** a metric that cannot see
16.5 mi of false-VOID geometry appear or disappear must never again be quoted as evidence about
false-VOID risk. (Two consecutive runs, not one frozen snapshot; USGS values move between runs, so
treat small deltas as noise.)

**Precedence is unchanged: a gauge still outranks everything, in both directions.** The single
held-out false positive is `LOXAHATCHEE RIVER AT MILE 9.1` (711 µS/cm — fresh) sitting inside the
Loxahatchee marine polygon. In the *shipped* asset that reach is `fresh`, because the gauge is
there and wins. ⚠️ **n=17 in that bucket** — a 1-in-17 false-positive rate has a 95% upper bound
near 25–30%, so "16 salt / 1 fresh" is not a precision guarantee. The residual risk is reaches
inside a marine polygon more than `PROPAGATE_MI` from any gauge, and hold-one-out is structurally
blind to exactly that population, because a gauge is what creates a scoreable point.

`mapped` is **exempt from the `REACH_MI` clip**, and unlike the `tagged` exemption that shipped
Dunns Creek, that is bounded: a marine WBID ends where the class turns `3F`. Measured — farthest
mapped reach 7.8 mi inland (Indian River above Max Brewer Causeway, a Class II estuary), median
0.27 mi, none beyond 10 mi.

### Two things this cost, both now pinned

- **19 closed rings became verdict-moving.** The fill can *reach* a pond outline, and the tagged
  seed's ring exclusion did not apply to the new class. Rings are now left `inferred`.
- **`validate_tidal_against_gauges.py` kept its own copy of the verdict-moving list** and silently
  scored all 3,491 mapped reaches as absent — a 77% that was grading a layer we do not ship. There
  is now one `VERDICT_MOVING` in `build_tidal_layer.py`, imported by the validator and the pin
  script, and a test asserts `checker.js` agrees with it.
- **The inland pins were blind to the worst breaches.** `_inland_mi` returned `inf` when no
  coastline sat in the surrounding 3×3 grid block and both callers *skipped* `inf` — so the
  further a runaway ran, the less likely it was caught. A Dunns-Creek-class breach at 25 mi passed
  silently. The helper now widens its search; proved by re-running each pin against a doctored
  asset and watching it fail.

## ⚠️ The capability gap this had until 2026-08-06 — kept for the pattern

**OSM does not tag South Florida's tidal rivers.** Measured across the named rivers:

| river | OSM ways | tagged `tidal`/`salt` |
|---|---|---|
| Miami River | 4 | **0** |
| New River | 33 | **0** |
| Caloosahatchee | 19 | **0** |
| Hillsboro | 13 | **0** |
| Loxahatchee | 17 | 1 |

The 159 tagged reaches are Everglades backcountry creeks, Keys development canals, and 108
unnamed. Checked across 30 populated places in all three branches' territory, **the `tagged` layer
is decisive in 0 of them** — every populated address behaves as the pre-feature tool did, plus a
caveat. New River downtown still reads VOID, but from `coastline.geojson`, which already contained
the river mouth.

So the CRITICAL above was closed by *narrowing the capability*, not by fixing the label — Tim's
2026-07-19 complaint stayed open for the Miami River class of address until the FDEP class landed.

The lesson worth keeping: **we went looking for a better inference and the answer was a register.**
Two planned fixes — a curated allowlist of ~10 named tidal reaches, and bounding the tagged label
by channel distance — were both attempts to guess better from the same OSM data. Neither was
needed. Florida already publishes which water bodies are marine.

## Rejected

**Tim's three links (2026-07-19), all checked.** `salinity.oceansciences.org` is NASA
Aquarius/SMAP satellite sea-surface salinity — open ocean, cannot see a canal. The NOAA
tides & currents salinity nowcast is model output, and its `ofsregion=sj` is the **St. Johns River,
Jacksonville**: NOAA's OFS list has **no southeast-Florida model at all** (nearest are SJROFS,
Tampa Bay and the northern Gulf), so it covers no Perkins branch. The USGS Water Level and Salinity
Analysis Mapper is the one real source — it maps the USGS South Florida network — but it is a
viewer, and the same network is already read programmatically via NWIS IV `00095`. None of the
three is a per-address API, and nothing queries them at runtime.
