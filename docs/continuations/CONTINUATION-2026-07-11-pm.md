# CONTINUATION — 2026-07-11 (PM): Perkins platform — quote→proposal→invoice engines, renderers & APIs

Massive build session. Executed the JB job-docs/billing lane far beyond the restart plan:
the complete **price book → proposal → invoice** pipeline now exists as validated,
R2-reviewed engines + PDF renderers + API routes. Plus Knowify data validation, a Tim
material-price email draft, and the SquareQuote/anu measurement investigation (PR to Vlad).

## Commits this session (main, in order) — HEAD = 3bfa4a0
```
da0b702 fix(knowify): correct REST base host + kill token-burning refresh recursion
5728355 feat(billing): JB4 billing-core schema slice (migration 0030) + self-check
038b7f3 feat(pricebook): JB1 price-book engine — versioned, hash-pinned, immutable (R2-passed)
2b59247 feat(pricebook): JB1 seed from Tim's authoritative material sheet + validator
5507860 feat(proposals): JB3 proposal-generation engine (R2 BLOCK findings fixed)
783b639 feat(billing): JB4 invoicing engine — draw math, numbering, ledger, milestone snapshot
80c7bc1 fix(billing): JB4 R2 fixes — per-scope draw allocation + ledger/immutability hardening
60e36a4 feat(billing): JB4 invoice PDF renderer (Knowify-anatomy HTML)
99573ae feat(proposals): JB3 proposal/contract PDF renderer
b7f23c8 feat(billing): invoicing + payments API — atomic numbering (R2 C2 closed)
12b7bf3 feat(pricebook): price-book API — list/edit items + freeze immutable versions
3bfa4a0 feat(proposals): proposal generation API — compose, freeze snapshot, persist, PDF
```

## Platform state — engines + renderers + APIs all committed & validated
- **JB1 price book**: engine (R2-passed) + seed (Tim's ABC 4/29/26 + Beacon tabs) + API
  (`api/routes/price_book.py`). Immutable hash-pinned versions.
- **JB3 proposal**: engine (R2-fixed; **8/8 golden emailed proposals reproduce to the penny**)
  + PDF renderer (`core/proposal_doc_render.py`) + generation API (`api/routes/proposal_gen.py`).
- **JB4 billing**: schema (migration `0030_billing_core.sql`), invoicing engine (R2-fixed;
  **7 golden invoices to the penny**), invoice PDF renderer (`core/invoice_render.py`),
  invoicing+payments API (`api/routes/invoices.py`, **atomic numbering — R2 C2 closed**).
- Validators: `scripts/validate_{pricebook,pricebook_seed,proposal_gen,invoicing,
  invoice_render,proposal_doc_render,invoice_api,billing_schema}.py` — all green; tenancy 76/76.

## Outstanding (next session, in priority order)
1. **Admin UIs** (web/ React/TS) — price-book editor, proposal builder, invoicing/payments
   screens against `/price-book`, `/proposal-gen`, `/invoices`. Pattern: `web/src/pages/EstimatingConfig.tsx`.
   THIS is the "then UIs" step the user paused before.
2. **Deploy (gated, R3/R4)** — NOT applied to prod: apply migrations **0030** + **0031**,
   run `scripts/seed_pricebook.py` (loads Tim's material data), deploy the API. Deploy is
   NOT concurrency-safe — one at a time, verify image sha vs HEAD.
3. **Security/critic pass on the 3 new routes** — engines were R2'd; routes were NOT.
   Check authz (they reuse `estimating_manage`; add a `billing_manage` role), tenant
   isolation, money-path. The invoicing route is fresh money-path I/O.
4. **C2 concurrency proof** — atomic numbering is implemented (`UPDATE tenant_invoice_counters
   ... RETURNING`); add a real Postgres two-session concurrency test to `tests/tenancy/`.
5. **JB2** (measurements/orders + Roofr-PDF parser) — not started.
6. **Tim follow-ups** — the ~13-item stale-material-cost email is a **DRAFT in jon@degenito.ai
   Drafts** (review + send once Tim confirms); still awaiting golden files + T&C sign-off.

## Key facts / decisions
- **Invoice numbering**: Perkins live Knowify max = **18732 → next 18733** (NOT the plan's
  stale 653). Counter seeded in migration 0030; re-confirm the live max at cutover.
- **Knowify access**: MCP `query` is the working data path. REST base = `assistant.knowify.com/api/v2`
  (the old `api.knowify.com/v2` was wrong). Importer fixed (`scripts/knowify/`) but DCR-token REST
  entitlement is unverified — use MCP. See memory `knowify-integration`.
- **Material costs**: Knowify's `OurCost` is stale/unmaintained vs Tim's 4/29/26 sheet
  (5/8 CDX $27 vs $55, Elastobase $127.78 vs $82, …). Seed costs+coverage from Tim's tabs;
  use Knowify only for per-square SELL prices + the `knowify_item_id` crosswalk.
- FL roofing services = **$0 tax**; **metal proposals = 15-day expiry** (else 30).
- Analysis artifacts in **`docs/perkins-analysis/`** (gitignored — client PII): `tim_materials.json`,
  `proposal_fixtures.json`, `roofr_baseline.json`, `VALIDATION_*.md`, `ANALYSIS_*.md`.

## SquareQuote / measurement accuracy (asked repeatedly)
- **eaglepoint** (`~/projects/eaglepoint`) and **anu** (`~/projects/anu`) are both DIY
  OSM + public-3DEP-LiDAR — **NOT drop-in Roofr replacements**. anu's measured pipeline had
  never run end-to-end (missing PDAL, dead CONUS endpoint, wrong-CRS bounds — 3 fixed; a 4th
  degrees-vs-meters plane-fitter bug remains). 3DEP coverage EXISTS for these FL homes — the
  code is the blocker, not the data.
- **Recommendation: Google Solar API** (real pitch/segments from Google's DSM, ~$0.01/lookup;
  the `Measurement` model already has Solar columns from migration 0024) OR ingest Roofr via the
  JB2 PDF parser (already paid for). NOT the DIY LiDAR path.
- anu fixes pushed for Vlad: **PR https://github.com/burademirung/anu/pull/1** (+ a sanitized
  analysis comment). Local uncommitted changes remain in `~/projects/anu` and `~/projects/eaglepoint`.

## Resume steps
1. `git status --short` (clean; HEAD `3bfa4a0`) and re-read the memory index.
2. Build the admin UIs (see `web/src/pages/EstimatingConfig.tsx`) against the three new API prefixes.
3. When ready: gated deploy (apply 0030/0031 + seed + deploy, one at a time).

---
**Standing archive directive (performed this session):** moved the oldest top-level
`CONTINUATION-2026-07-10.md` into `docs/continuations/`, kept the latest 3 at top level,
fixed inbound links, and refreshed the README "most recent" pointer. Apply on every continuation.
