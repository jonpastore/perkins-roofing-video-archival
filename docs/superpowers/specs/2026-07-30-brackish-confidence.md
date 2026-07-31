# Spec — measured brackish confidence, a learning cache, and visible progress

**2026-07-30.** Successor to `docs/BRACKISH_DATA_SOURCES.md` (the research) and
`docs/WARRANTY_TOOL_TIDAL_LAYER.md` (what shipped). Nothing here is built yet.

## Why

The warranty tool now measures distance to tidal/brackish water, but 80% of the time it agrees
with reality and the 20% is not random — it is concentrated exactly where customers live. Measured
against 64 USGS gauges:

- **Loxahatchee River at US-1, Jupiter reads 55,100 µS/cm — seawater** — and we classify that reach
  as a connectivity guess, so it raises a caveat instead of moving the verdict. That is Tim's own
  branch territory and his original example.
- **One OSM-`tagged` reach measures fresh** (Upstream Broad River, 460 µS/cm) — and `tagged` is the
  only bucket allowed to change a warranty answer. OSM's tidal tags are not gospel.
- Seven salt/brackish gauges sit on water we do not map at all.

The fix is not more inference. There is a free, keyless API that *measures* the thing, plus an
authoritative state dataset, and we should be standing on both.

## Part 1 — Gauge anchoring

**What it does.** At build time, snap every salinity gauge to the nearest reach and propagate its
reading through the connected network until a control structure interrupts it. Each reach then
carries a measurement with provenance instead of a label with a rationale.

```
reach → { conductance_us_cm, station_id, station_name, measured_at,
          distance_along_channel_m, source: "usgs" | "sfwmd" }
```

**Precedence — measurement wins.** A reading overrides both an OSM tag and connectivity:

| evidence | classification | moves a verdict? |
|---|---|---|
| gauge on this reach, no structure between, ≥ 1,500 µS/cm | **measured salt** | yes — cite the reading |
| gauge on this reach, no structure between, < 1,500 µS/cm | **measured fresh** | yes — *suppresses* a false positive |
| inside SFWMD's 250 mg/L isochlor, or OSM-tagged and not contradicted | **mapped** | yes — cite SFWMD 2024 |
| connectivity only | **inferred** | no — caveat, today's behaviour |
| no water mapped | none | no |

**Propagation limit.** A reading is evidence about the reach it sits on and its immediate
neighbours, not about the whole network. Propagate along channel distance with a cap (start at
2 mi, calibrate against the gauge pairs we already have — C-8 has two gauges reading 473 and 29,900
on opposite sides of structure S-28, which is exactly the calibration case).

**Staleness.** Conductance moves with tide, season and rainfall. Bake readings at build time,
store `measured_at`, and treat anything older than 30 days as `mapped` rather than `measured`.
Prefer a median of recent readings over a single instantaneous value.

**Success test.** `scripts/validate_tidal_against_gauges.py` agreement rises from 80%. Holding out
gauges (fit on n−1, score the held-out one) is the honest version — otherwise we are scoring the
model on its own training data, which is the same circularity trap the overhead analysis fell into.

## Part 2 — Low-confidence triggers research, and the answer is kept

**The loop.** When a check resolves to `inferred` or `none` *and* the water is within the mile that
can change a verdict, that is a question we could not answer — so record it and go find out.

```
1. tool records a research request   (reach id + coarse cell, NOT the address)
2. scheduled job picks up pending requests
3. it queries: USGS IV gauges near that reach · SFWMD DBHYDRO stations ·
   SFWMD 250 mg/L isochlor containment · a targeted Overpass re-query for
   unmapped structures in that area
4. it writes a determination with provenance, confidence and an expiry
5. the nightly rebuild folds determinations into tidal.geojson
```

**The plugin stays static.** Determinations feed the *build*, not a runtime call — so there is
still no API dependency and no new secret in the browser, and an improvement lands within a day.
A runtime lookup is possible later; it is a product decision, not a technical one.

**Privacy is a hard constraint.** Store the **reach id and a coarse grid cell (~1 km)** — never the
address, never the exact coordinate. Today's CompanyCam finding was that we published a client's
building to 0.1 m without noticing; a table of "addresses people checked" is the same mistake with
a database instead of a photo. `core/pii.py` and the gate apply.

**Why this is worth building.** It is demand-driven: the map fills in where Perkins actually sells,
not uniformly across Florida, and every unanswered question becomes an answer exactly once.

## Part 3 — Say what you are doing

Today the tool prints one spinner, `Locating and measuring…`, and then either answers or (until
this week) hung forever with no explanation. Every step should report:

```
✓ Found the address
✓ Loaded coastline and tidal water (3.0 MB)
✓ Measured to the nearest salt water
✓ Checked salinity records for this waterway
→ Building your warranty summary…
```

Cheap in `checker.js` — the phases already exist as promise stages. Two rules: never leave a step
without a terminal state (that is what made the hang invisible), and report the *last* step
reached on failure so an error says where it died.

⚠️ **Open question for Jon:** "each of the rendering actions" may also mean the platform's
long-running SPA actions (proposal PDF render, publish, batch article generation), which have the
same silent-wait problem. Scope confirmed as the warranty tool; the SPA is a separate pass if
wanted.

## Out of scope

- Live per-request salinity lookups from the browser.
- Statewide coverage. Tidal water stays South Florida; outside it the tool already says so.
- Replacing the manufacturer provisions in `zones.json` — this changes the *distance*, never the
  warranty terms.
