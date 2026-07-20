# Continuation — 2026-07-17 night (roof-cuts custom calculator) — SHIPPED + PROD-VERIFIED

**Priority 1a from prompt.txt is done, deployed, and verified against the live API.** Commit
`5ca984c` on `main`; API image `platform:5ca984c` on Cloud Run; SPA on Firebase; prod configs
seeded to v4 (jupiter/miami/naples) with `cuts_calc`.

## What shipped
The roof-cuts custom calculator — Tim's "Custom Tile Calc" tab, **decoded from his LIVE Google
sheet** (read-only via the perkins-deploy-sa service account under domain-wide delegation
impersonating tim@perkinsroofing.net; Jon granted DWD + enabled the Sheets API this session).
Full derivation: `docs/plans/2026-07-17-cut-calculator-spec.md`. Reproduces Tim's sheet cell
B22 ($811) to the dollar.

- **Engine** (`core/estimator.py`): `compute_cut_adjusted_base()` replaces the flat tile base
  with a geometry-derived base from the 6 RoofR cut LFs (eaves/hips/ridges/valleys/rakes/
  wall_flashings), each CEILING-rounded to material pieces (valleys→50ft, rest→10ft) then priced.
  13" tile computed directly; other roof types scale their flat base by the tile custom/standard
  ratio. `QuoteInput` gains the 6 LF fields + `base_tile_brand` + `has_cut_measurements()`.
- **Config** (`core/pricing_config.py` `cuts_calc()`, fixture `cuts_calc` block): FBC calibrated
  (fixed 519 + coeffs + Eagle/Crown/West Lake tile brands); **HVHZ null → graceful flat fallback
  with a `cut_calc_uncalibrated_zone` warning**.
- **API** (`api/routes/estimator.py`): 6 cut-LF + `base_tile_brand` request fields; cut LFs
  resolved from `measurement_id` (merged per-field, tenant-checked); `/rates` exposes tile brands
  + `cut_calc_available`.
- **FE** (`web/src/pages/Quoting.tsx`): base tile-brand dropdown (tile roofs, calibrated zones);
  cut-adjusted base $/sq shown in the result; the double-count / uncalibrated warnings render.
  The builder already sends `measurement_id`, so **every RoofR-measurement quote auto-applies the
  cut calc — no other FE change needed.**
- **Prod seed** (`scripts/seed_cuts_calc_config.py`): adds `cuts_calc` as a new immutable config
  version. Applied to prod (jupiter/miami/naples → v4; GC has no config, skipped).

## Prod e2e (live API, smoke admin token, user deleted after)
| case (jupiter/FBC/13_tile/29sq) | base $/sq | note |
|---|---|---|
| no cuts | **770** | flat |
| + RoofR cuts (Eagle default) | **820.90** | cut-adjusted |
| + cuts, `base_tile_brand=crown` | **810.58** | = Tim's sheet B22 ($811) |
| + cuts, `roof_cuts=high` | 820.90 + **roof_cuts_double_count warning** | guard fires |
Premium menu shifts correctly with the base (PROTECTOR + fixed adders).

## Validation
- 19 engine + 5 API cut tests (Crown selection = $811 oracle). Full backend suite green **except
  8 pre-existing live-LLM article tests** (`api/routes/topics.py → adapters/llm.py _ollama` — real
  ollama generation, env-dependent; unrelated to this wave — see full6.log stack). Ruff clean.
- R2: architect + critic. Converged HIGH = geometry base + categorical `roof_cuts` double-count →
  per Jon "keep both, low=$0 default", now a **warning** not silent sum. MED fixes: measurement
  per-field merge; HVHZ uncalibrated warning. Accepted/documented: barrel via ratio (no barrel
  coeffs — estimate only), standalone tiers bypass cut base (pre-existing), tiny num_squares GIGO,
  latent county 7% double-tax (inactive).

## Still blocked on DATA (not code)
- **Greener $51,950 exact match** — NOT reproduced. Its 6 RoofR cut LFs aren't in email (searched
  degenito Outlook + both Gmails + Drive; only a forwarded Knowify proposal + CompanyCam link
  `app.companycam.com/timeline/M54pEMur54P2YtVC`, no measurement attachment). Need Tim's Greener
  RoofR report PDF or the CompanyCam data. Engine is validated against Tim's sheet formula instead.
- **HVHZ (Miami/Broward) cut calc** — needs Tim's HVHZ base detail (`fixed_per_sq.HVHZ` + ideally a
  zone-scoped `standard_tile`); falls back to flat + warns. Demo is Jupiter/FBC.

## Still blocked on TIM (chase — unchanged from eve)
GC branch pricing; per-branch daily OH if different; YouTube channel-owner token; gutter 2 tiny
discrepancies. NEW: cell-comment material↔price mapping (#9) now UNBLOCKED via DWD sheet access —
raw pre-tax tile prices already captured in the cut spec; can extend to the full price book.

## Reusable access (memory: [[tim-sheets-dwd-access]])
Read Tim's Workspace sheets read-only: SA `perkins-deploy-sa@…` + `.with_subject("tim@perkinsroofing.net")`
+ `valueRenderOption=FORMULA`. Sheets API enabled; Drive API NOT (Drive search 403s). jon@degenito.ai
Outlook mail: drive the cerberus `~/gmail-enhanced-mcp` install over SSH (session MCP has no accounts).

## Outstanding Zoom items not yet built (prompt.txt priority order)
RoofR ingestion (real reports), duration-training predictor, low-slope builder inputs (1d),
CompanyCam photo pull (1e), franchise/accounting B8-B10.

## Operate / verify
Prod DB proxy + DB_URL: see prompt.txt. Deploy: `bash scripts/deploy.sh` (API) + firebase
hosting:app (SPA). Prod e2e recipe: firebase_admin custom-token(role=admin) → identitytoolkit
signInWithCustomToken(web api key) → Bearer to `api-981279422576.us-central1.run.app`; delete the
smoke user after (script was `scratchpad/prod_e2e_cutcalc.py`). Full suite: exclude the LLM files
(`--ignore=tests/api/test_topics.py` …) or accept the ollama-dependent timeouts.

*Standing archive directive performed: CONTINUATION-2026-07-16.md rotated into docs/continuations/;
only the latest 3 remain at top level.*
