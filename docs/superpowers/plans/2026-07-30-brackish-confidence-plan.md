# Plan — measured brackish confidence

Spec: `docs/superpowers/specs/2026-07-30-brackish-confidence.md`. Waves are independently
shippable; W1 alone fixes the known errors, so stop after it if the rest does not earn its keep.

## W1 — Gauge anchoring (the one that pays for itself)

| # | task | file | done when |
|---|---|---|---|
| 1.1 | Fetch and cache gauge readings at build time — USGS IV param `00095`, all sites in the bbox; keep a 30-day window, store the median and the latest | `scripts/fetch_salinity_readings.py` (new) → `~/perkins-corpus/osm/salinity-readings.json` | cache written, rerun is idempotent, no key needed |
| 1.2 | Snap each gauge to its nearest reach; reject a snap beyond 250 m as "not on mapped water" and log it — those are the seven reaches we do not map | `build_tidal_layer.py` | every gauge either snapped or logged with a reason |
| 1.3 | Propagate readings along channel distance, stopping at barriers, capped at `PROPAGATE_MI` (start 2.0) | `build_tidal_layer.py` | C-8's two gauges (473 / 29,900) stay on their own sides of S-28 |
| 1.4 | Emit `confidence: "measured"` with `{us_cm, station, measured_at, distance_m}`; measurement overrides tag and connectivity **in both directions** | `build_tidal_layer.py` | Broad River (tagged, 460 µS/cm) demotes to fresh; Loxahatchee promotes to measured salt |
| 1.5 | Consume `measured` in the verdict path alongside `tagged`; render the citation | `assets/checker.js` | a measured reach shows "29,500 µS/cm at USGS 02277100, 1.2 mi downstream" |
| 1.6 | Hold-one-out scoring so we are not grading on training data | `scripts/validate_tidal_against_gauges.py` | prints in-sample and held-out agreement separately |

**Gate:** held-out agreement > 80%, and the three never-tagged pins still pass. Ship only if both.

## W2 — The learning cache

| # | task | file | done when |
|---|---|---|---|
| 2.1 | Migration `0052`: `water_research_request` (reach id, grid cell, first_seen, hits, status) and `water_determination` (reach id, classification, evidence json, confidence, source, expires_at) — **no address, no exact coordinate** | `db/migrations/0052_*.sql` | applied to prod manually, both tables + indexes verified |
| 2.2 | Record a request when a check lands `inferred`/`none` inside 1 mi | `api/routes/` + `assets/checker.js` | request rows appear; nothing personal stored — verified by inspecting rows |
| 2.3 | Resolver job: USGS + DBHYDRO + isochlor containment + targeted Overpass re-query for missing structures | `jobs/resolve_water_research.py` (new) | pending → determined with provenance; unresolvable marked, not silently dropped |
| 2.4 | Fold determinations into the build ahead of inference | `build_tidal_layer.py` | a determination beats connectivity; expired ones are ignored |
| 2.5 | Schedule the job + a rebuild, both incremental | `infra/` (Terraform, R3) | `drift_check.sh` clean; job visible in Cloud Run |

**Gate:** R1 coverage on new `core/` logic, R2 architect + critic review, R4 drift check. Prove the
privacy claim by querying the tables and showing no address or fine-grained coordinate is present.

## W3 — Visible progress

| # | task | file | done when |
|---|---|---|---|
| 3.1 | Per-phase status with terminal states on every branch | `assets/checker.js` | each phase ticks; a forced failure at each phase names that phase |
| 3.2 | Report the last phase reached on error | `assets/checker.js` | blocking the Maps host says "while finding the address", not a bare message |
| 3.3 | Confirm scope with Jon before touching the SPA's long-running actions | — | answered |

## Constraints carried from today

- **Staging only.** `PlatformConfig.WP_URL` is the GoDaddy temp domain and that is correct.
- **Measurement can *remove* a warning as well as add one.** The Broad River case is the reason
  `measured fresh` exists; without it we keep a known false positive to look conservative.
- **`check_tidal_layer.py` and `validate_tidal_against_gauges.py` both gate the rebuild.** The
  address pins caught nothing on their own — the gauge score is the real gate.
- **The build must stay byte-reproducible** (sorted seeds and geometries) or the 0.93 MB asset diff
  hides regressions.
- **SFWMD's host 403s a default curl UA.** Send a browser UA.
- **Plugin upload:** bump `PERKINS_MWC_VERSION`, zip, `scripts/wp_install_plugin.py` with
  `WP_LOGIN_PW="$WP_PWD"` (the web login, not the REST app password).

## Deliberately not doing

Runtime salinity lookups from the browser; statewide tidal coverage; any change to `zones.json`
warranty terms.
