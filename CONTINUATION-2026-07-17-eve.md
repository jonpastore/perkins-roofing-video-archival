# Continuation — 2026-07-17 evening (autopilot Monday-demo wave)

**HEAD at writing: in flight — see `git log`; branch main.** Everything through `ebee617`
is committed; UI executor commits land after. **Deadline: Tim expects visible improvement
MONDAY, then demos to Josh/Marco.**

## Shipped earlier today (all deployed + verified in prod)
- max_length audit (`6ddaf70`) + meta-test + 231 negative tests (three agent clusters merged).
- Human-readable API errors (`ce6737a`) — `[object Object]` fixed; shared errText/formatDetail.
- Gutters v1 + New-construction/Demo pair + editable pending-Tim config cells (`f02790b`).
- Comments OAuth: connect/switch buttons + post-as confirmation; capture flow LIVE end-to-end
  (`8531005`); Google redirect URI registered; `/oauth/youtube/start` verified 200.
  **Remaining human step: TIM clicks Connect and picks the channel-owner account.**
- Price book seeded in prod: 171 items from Tim's 4/29 sheet (`8b40b4a` fixed the seed's RLS).
- Coastal setback checker LIVE: https://perkins-setback.web.app (`1597d36`) — verified warranty
  thresholds (per-brand PDFs cited in zones.json). Flag: Coastalume 300ft claim unverified;
  Dynamic Metals has no public warranty doc (call 772-247-2465).
- MCP media server: /home/jon/projects/mcp-media-transcribe (transcribe/extract_frames/list_media)
  — fixed amd-halo whisper (bad HF token, root-owned cache, DEVICE=cuda→cpu/int8).
- Zoom deep-analysis: docs/plans/2026-07-17-zoom-analysis.md (action items w/ timestamps+frames).

## Autopilot wave (this evening) — branch mgmt + estimating overhaul
Backend DONE, verified SQLite+PG, **migration 0041 APPLIED TO PROD** (branches
miami/jupiter/naples/gc; 7,413 customers backfilled miami):
- Branch model + /branches CRUD (read estimating_view, write manage_config) + customer.branch
  (validated active) + dashboard ?branch= filtering (all analytics fns) — `7191b06`+`ebee617`.
- Gutters engine = Tim's style-based email model; seed script scripts/seed_gutters_config.py
  (tested, idempotent) — **RUN AGAINST PROD AFTER API DEPLOY** (creates v+1 configs per branch).
- existing_roof selector semantics; package_options on quote (adders exact vs Greener PDF;
  TILE PREFERRED 160→165).
- GC branch: NO pricing config yet — GC quotes 503 until Tim provides values.
In flight at writing: exec-ui-admin (branches admin UI/customers/dashboard selector/marketing
YouTube connect), exec-ui-builder (builder overhaul: existing-roof, gutters UI, daily-OH days,
package menu, profit slider, branch-from-customer), security review, full-suite baseline,
duration-training template (docs/templates/).

## To finish the wave (if interrupted)
1. Verify+build UI executor work (npm run build), run full backend suite, ruff.
2. Phase-4 reviews (security running; add architect+code-review on full diff), fix HIGHs.
3. Deploy: bash scripts/deploy.sh (API) + SPA hosting deploy.
4. PYTHONPATH=. DB_URL=<prod> .venv/bin/python scripts/seed_gutters_config.py (after deploy).
5. E2E prod check: quote w/ existing_roof+gutters+daily OH via a Jupiter customer; dashboards
   by branch; branches admin CRUD.
6. /oh-my-claudecode:cancel to clear autopilot state.

## Monday-demo remaining gaps (from zoom-analysis, not in this wave)
RoofR ingestion (Jon needs account access/call), CompanyCam (Tim adds Jon), original
calculator sheets sharing (comments!), copper commodity pricing, low-slope deck/coating
builder inputs, Qvinci/QuickBooks-per-branch + franchise ACH (B8-B10).

*Standing archive directive performed: moved the oldest top-level CONTINUATION
(2026-07-11-eve) into docs/continuations/; only the latest 3 remain at top level.*
