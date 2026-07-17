# Continuation — 2026-07-17 evening (autopilot Monday-demo wave) — COMPLETE

**Everything below is committed to `main`, deployed, and PROD-VERIFIED.** Tim demos to
Josh/Marco after Monday; the wave is demo-ready. Deep code audit run at handoff (findings +
fixes in the "Deep validation" section).

## Completed-work breakdown (this session)

### The 7 shipped features (all live on app.perkinsroofing.net)
1. **Branch management** — `branches` table + `/branches` CRUD (read `estimating_view`,
   write `manage_config`); every branch selector reads from it; `customers.branch` (validated
   active); dashboards filter by `?branch=` or show all. Admin Config → Branches tab (CRUD).
   Migration 0041 (RLS-seeded miami/jupiter/naples/gc; 7,413 customers backfilled miami).
2. **Existing-roof / demo selector** — quote builder asks "Existing roof (what are we tearing
   off?)" (new construction / shingle / tile / metal / flat); demo cost + tile dumpster follow
   what's TORN OFF, not the new roof (Zoom [13:03]). Legacy `demo` bool preserved.
3. **Gutters** — engine + UI on Tim's real style price list (7/17 email): 6"/7" K-style, box,
   half-round, aluminum/copper; per-LF incl. downspouts; 2-story uplift (gated to styles that
   have the rate); elbows, leaf guards, leaderheads, removal; <100 LF surcharge.
4. **Time-based overhead** — builder "By time (days)" mode; engine computes OH from days×daily
   targets. Prod-verified: 4 demo + 6 tile days = **$8,670 = 4×1050 + 6×745, exact**.
5. **Full package menu** — every quote returns `package_options`: Protector (engine total) +
   Preferred + 3 premiums (Caribbean/Mediterranean/Modern) + Coastal as flat catalog adders.
   **Matches the Greener proposal to the dollar** (Caribbean +$12,470 / Med +$15,695 / Modern
   +$20,855 @ 43 sq). TILE PREFERRED corrected 160→165. Computed post-discount (coherent).
6. **Profit slider + floors** — target-margin presets (13% min / 15% / 20%) + min-$ floor
   re-price via `profit_mode="flat"`; red when below the 13%/33% config floors (config-driven).
7. **YouTube comment posting** — connect/switch-account button + "post as {channel}?" confirm
   (Comments page + Marketing social-accounts row).

### Schema fixes (both the SQLite-hides-constraints class)
- **0041** — branches table + `customers.branch`; RLS policy + tenant-GUC-stamped seed.
- **0042** — pricing-config "one active per branch" was `UNIQUE(tenant,branch,is_active)`,
  which capped each branch at **2 versions**; once the gutters+daily seeds made branches
  2-version, Admin config-save (POST → 409) and re-activation broke. Fixed to a partial index
  `UNIQUE(tenant,branch) WHERE is_active` (postgresql_where + sqlite_where). **Applied to prod;
  config-save verified unblocked through the deployed API.**

### Prod data seeded (all branches now v3 active)
`scripts/seed_gutters_config.py` + `scripts/seed_daily_overhead_config.py` — idempotent,
create-new-version. v3 = base + gutters (email prices) + daily overhead (Zoom targets: demo
1050 / tile 745 / metal 850 / shingle 700, $2,500 weekly floor). GC has NO config (503 —
expected until Tim provides values).

### Deploys
- API image **f9c13e8** on Cloud Run (branches, gutters engine, existing_roof, package_options
  post-discount, floors exposure). SPA on Firebase `app` target. HEAD is ahead of the deployed
  image only by DDL-only model-index declaration (0042, prod already has it via migration) +
  seed scripts + docs — **a redeploy is NOT required** (runtime unchanged).

### Also this session (earlier, all deployed)
max_length audit + 231 negative tests; human-readable API errors; comments OAuth capture;
price book seeded (171 items); coastal setback checker (perkins-setback.web.app, verified
warranty PDFs); MCP media server (transcribe/frames — fixed the amd-halo whisper box); Zoom
transcription + deep-analysis (docs/plans/2026-07-17-zoom-analysis.md).

## Validation — confirmed correct
- **Full backend suite: 4322 passed, 0 failed, 0 errors** (post-schema-change).
- **PG harness** (scripts/test_pg.sh) green on branches/dashboard/gutters/packages.
- **Phase-4 reviews**: security (1 MED fixed — create_branch tenant stamp), architect (all 7
  items VERIFIED-COMPLETE), code-review (1 HIGH + 3 MED + 2 LOW fixed).
- **Prod e2e** (smoke admin token → live API, user deleted after): GET /branches; gutters
  384LF 2-story 7" = **$6,988.80 exact**; daily OH **$8,670 exact**; all package tiers = Greener
  PDF to the $; tile-demo + dumpster on tile teardown; new-construction clean; dashboard
  ?branch=miami; floors exposed; unknown branch rejected (503); **config-save POST = 200**
  (was 409 pre-0042). PROTECTOR $53,100 vs Tim's $51,950 (~2%; gap = manual roof-cuts calc).
- **Free-fleet offload** (Jon's directive): demo walkthrough drafted on Cloudflare free tier
  (Hermes), gutter math cross-checked on local smart-router — both matched.

## Documentation + memory — updated
- `docs/plans/2026-07-17-zoom-analysis.md` — Tim's estimating model + all action items (timestamps + frames).
- `docs/plans/2026-07-17-monday-demo-walkthrough.md` — presenter click-paths for all 7 features.
- `docs/templates/duration-training-{template.csv,README.md}` — for Tim's per-phase day labeling.
- `README.md` continuation index updated; this file is "most recent". Archive rotated
  (oldest top-level CONTINUATION moved to docs/continuations/).
- Local memory: `branches-and-monday-demo.md`, `estimator-pricing-linkage.md` (+ MEMORY.md index).

## Outstanding (nothing blocks the Monday demo)
**Zoom action items not yet built** (see zoom-analysis.md — prioritized in prompt.txt):
- Roof-cuts custom calculator (closes the ~2% PROTECTOR gap — round-to-10ft + waste per cut).
- RoofR ingestion (no public API — Jon needs account access/call; website-widget data; PDF parse).
- Duration-training predictor (Tim labels 20-30 reports via the template).
- Low-slope builder inputs (deck type, coating system — configs exist, UI doesn't).
- CompanyCam photo pull (Tim adds Jon; REST v2 + webhooks researched).
- Franchise/accounting (B8-B10): Qvinci/QuickBooks-per-branch, royalty+marketing ACH via Stripe,
  owner cross-tenant admin view.

**Blocked on Tim** (chase): share ORIGINAL calculator sheets (cell comments = material mapping);
GC pricing values; per-branch daily overhead if different; connect the YouTube channel-owner
token; confirm 2 tiny gutter price discrepancies (proposal vs email).

**Known, non-blocking**: API deployed image trails HEAD by inert changes (no redeploy needed);
specialty_tile_upgrade still falls back to legacy rates (pre-existing TODO, bd0c1d9, graceful).

## Deep validation (code audit at handoff)
Ran read-only deep audits (backend `critic` + frontend `code-reviewer`) for gaps/slop/stubs/
unwired code across the wave, plus a manual TODO/FIXME/console.log/as-any sweep. Manual sweep:
**zero stubs/slop/unwired in wave code**; the only TODO in scope (estimator.py specialty_tile)
is pre-existing (bd0c1d9) and a graceful config→legacy fallback. Audit-agent findings + any
fixes are appended below.

<!-- DEEP-VALIDATION-FINDINGS -->

## Operate / verify
- Prod DB proxy + DB_URL: see prompt.txt. Deploy: `bash scripts/deploy.sh` (API) + firebase
  hosting:app (SPA). Suite: `.venv/bin/python -m pytest -q`. PG harness: `scripts/test_pg.sh`.

*Standing archive directive performed: oldest top-level CONTINUATION already rotated into
docs/continuations/ this session; only the latest 3 remain at top level.*
