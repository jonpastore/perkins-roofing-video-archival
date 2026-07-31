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

## Part 2 — Sweep every sensor daily, on our own clock

**Jon, 2026-07-31:** *"we should just poll all of the data from all sensors every day and build the
cache to hit and not do this per query. spread out the requests over the day and hit them all as a
background service on continuous run."*

This replaces the demand-driven design (a low-confidence check enqueuing a research request), and
it is better on every axis that mattered:

| concern | demand-driven | daily sweep |
|---|---|---|
| plugin stays static | needed a beacon call on low confidence | **no runtime call at all** |
| consumer privacy | needed a rule about what not to store | **nothing about a person is ever recorded** |
| upstream protection | needed Cloud Tasks rate limiting | **we set the pace; load is constant and known** |
| coverage | fills in only where people happen to look | **complete, every day** |

**Shape.** A background sweep walks every station on a fixed cadence, a slice at a time, so the
daily load is flat instead of bursty: 64 USGS gauges plus SFWMD stations, spread across 24 hourly
slices, is a handful of requests an hour. Each slice merges into the cache; a slice that fails
leaves the previous day's value in place rather than blanking the reach.

**Cadence over a long-running container.** An hourly slice job achieves "spread over the day,
all of them daily" without paying for an always-on instance, and it matches the scheduled-job
pattern the repo already uses. Same effect, lower cost, one less thing to keep alive.

**What the cache holds.** Station id, coordinates, a 30-day median / max / latest, sample count,
and the timestamp. Nothing else. No addresses, no queries, no per-user anything — the question
"who looked at what" is never asked, so it cannot leak.

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
