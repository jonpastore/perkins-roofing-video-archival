# CONTINUATION — 2026-07-10 PM (Perkins platform + Ez-Bids multi-tenant)

Handoff for resuming after `/clear`. Read this + the memory index (auto-loaded) + `prompt.txt`.
Prior handoff: `CONTINUATION-2026-07-10.md` (this session's morning: C1 strict=True deploy).
HEAD at write time: `8f5008d`. CI: GREEN. This was a very large evening session — everything
below is committed + pushed unless marked otherwise.

## TL;DR — resume in AUTOPILOT and build everything buildable
Jon is (a) handling the IG/TikTok social-API setup himself via `docs/SOCIAL_API_SETUP.md`,
and (b) waiting on Tim to send real estimates/proposals. On resume, **autopilot every
buildable item** (see "Buildable now"). First analyze Tim's 2 pricing workbooks (below).

## PRIMARY RESUME TASK — analyze Tim's 2 pricing workbooks
Tim's pricing lives in TWO Google Sheets (Drive, shared by tim@perkinsroofing.net):
- **Sloped/"regular" roofs**: "Copy of ***Sloped Roof Price Calculator"
  — Drive id `1ptSxJYPumUKtxJk66JgbZ8tljVJMbyCAyaSyz_BCwg0`
- **Low-slope/flat roofs**: "Copy of **Low-Slope Roof Price Calculator"
  — Drive id `1SGLYoOIU13nILqGxJCIxuVZ8A2I_BTEjJ03PUuuRteo`

**The confusion to resolve** (Jon's explicit ask): "figure out why we have so many and what
the differences are." Two conflicting signals this session: (1) the two workbooks split by
ROOF TYPE (sloped vs low-slope); (2) Jon also said the Miami sheet is the *Miami branch* and
"the other workbook has the Jupiter branch — they're both HVHZ." Likely reality: each workbook
has **per-branch TABS** (miami / jupiter / naples) and the Drive connector's `read_file_content`
only returns **tab 1**. RESUME ACTION: use the Google Sheets/Drive connector to read **every
tab** of both workbooks (the connector reads tab 1 only — find a way to enumerate tabs, e.g.
Sheets API `spreadsheets.get` for sheet titles, then per-tab reads, or ask Jon to point at
specific tabs), map the full structure (roof-type × branch × zone), and reconcile against
`infra/fixtures/pricing_config_exhibit_b.json`. See memory `perkins-pricing-verified`.

**What's already verified** (memory `perkins-pricing-verified`): the Miami *sloped* sheet
(tab 1) == seeded Exhibit B **HVHZ** zone EXACTLY (all base costs, OHs, pitch adder, profit
scale, specialty tiles). HVHZ = Miami-Dade + Broward ONLY (175/170 mph); Jupiter/Palm Beach =
Wind-Borne-Debris FBC, NOT HVHZ. **Zone (HVHZ/FBC) and branch (miami/jupiter/naples ops cost)
are separate axes.** Prod's jupiter/naples branch configs currently DUPLICATE Miami's Exhibit B
and need their own values from the correct tab. Low-slope values were filled this session from
tab 1 of the low-slope workbook (all-in coating composition, $50 wood-deck OH per Jon).

## Buildable now (autopilot these — sonnet impl subagents; opus for plan/review only)
1. **Estimator v2** (task #10, spec `docs/superpowers/specs/2026-07-10-estimator-v2-tim-feedback.md`):
   Tim wants (a) **day-based overhead** entered per work series to the half-day
   (Demo/Dry-in/Flat $1,050/day, Tile $745, Metal $850, Shingle $700; OH_total=Σ(days×rate),
   per_sq=OH_total/squares), and (b) **absolute-dollar profit** entry alongside the % sliding
   scale, with $2,500/week-on-site + $2,500/job floors surfaced. Engine needs OH MODE +
   profit MODE (selectable) so Exhibit B goldens still pass. Tim's 2 worked examples are the
   golden cases. Editable via the versioned pricing-config flow.
2. **Ez-Bids W0** (plan APPROVED by Jon — start executing): DB-backed CORS (`cors_origins`
   table + dynamic middleware; exact-match, Vary: Origin), retire single-tenant env leftovers
   (WP_URL/YT_OWNER_CHANNEL_ID/WORKSPACE_ADMIN_SUBJECT → Tenant.settings.integrations), Ez-Bids
   brand tokens. Then W1 (explicit tenant-1 binding — see below), W2 (domain onboarding on
   ezbids.degenito.ai — degenito CF token READY, see memory `ezbids-degenito-cloudflare`,
   zone `63d609f219b48dafafdb02afa31d403f`), etc. Plan: `.omc/plans/ralplan-ezbids-multitenant-DRAFT.md`.
3. **Sync Ez-Bids PRD/TRD/DDD** (`docs/superpowers/specs/ezbids/`) to the council-revised plan
   (they were written pre-council-revision — reconcile before W-execution).
4. **Clip Studio v2** (optional): multi-speaker tracking, semantic b-roll (CLIP embeddings),
   feedback-trained virality once we have post-performance data.
5. Minor: Squares `imagery_date`/`imagery_quality` come back null (route doesn't parse the
   buildingInsights imagery fields → staleness defaults to "warn"). DMARC → `p=reject` after
   ~2 weeks of clean aggregate reports.

## Ez-Bids — where the multi-tenant SaaS plan stands (APPROVED)
Consensus (Planner→Architect SOUND-WITH-CHANGES→Critic APPROVE) + external council (Grok-4 +
GPT-5 both DO-NOT-SHIP → all 10 findings folded in). Jon's 3 decisions encoded: platform-domain
email default v1 (per-tenant sender domains deferred), **explicit tenant-1 binding** (invert
"missing claim → tenant 1" to fail-closed — this is W1, touches the live login path, has a
Perkins-smoke regression gate), revise-then-build. 8 waves W0–W7, migrations 0026–0030, on the
existing RLS+strict-session foundation (strict=True already fail-closes unset GUC — shipped this
AM). Council review: `docs/superpowers/specs/ezbids/COUNCIL-REVIEW.md`. **W2 needs the degenito
CF token (READY).** Ez-Bids = brand of record (not "SquareQuote"); jarvis #82 (CF reseller model)
retired for Ez-Bids.

## Shipped + LIVE this session (all deployed to prod)
- **C1 strict=True** (AM) — tenant-2 gate, prod-smoked. **Deepsec** SSTI sandbox + npm-audit CI.
  **Contract-FAQ** engine. **app.perkinsroofing.net** custom domain (TLS+auth+CORS). **Email auth**:
  Google DKIM + DMARC p=quarantine + dmarc@ group. **YouTube reply posting** enabled. run-ingest
  hourly 9–6 ET.
- **Estimator** healed (prod crash: no seeded config + dead fallback) — Exhibit B seeded, verified
  == Tim's Miami sheet, low-slope filled. **Proposals** section reorg + **Quotes/Proposals UIs**
  + Tim-demo polish. **Squares** via Google Solar API (#331) — verified live (1200 Brickell →
  158.2 sq, 27 segments), Roofr-comparison field. **Clip Studio v1** (items 1–11): karaoke
  captions, preview, emoji, hook overlay, multi-aspect, speaker-track math, Pixabay music, Pexels
  b-roll, audio enhance, virality badge. **Ask-cache** (semantic /ask cache + suggestions + trgm
  index). **Email compose** overhaul (sends as user, branded wrapper, full TinyMCE toolbar) +
  **TinyMCE blank-editor fix**. **YouTube-link fix** — root cause was graph.py secs() zeroing bad
  LLM timecodes; fixed + **675 prod rows recovered** (210 real timestamps, 465 bare links, 0 left
  at start=0) via `scripts/recover_graph_timestamps.py`.
- **CI is GREEN** — was red all session from a testcontainers-vs-CI coverage gap; gate now mirrors
  CI (`-m "not postgres"`, core 100%). ALWAYS run that gate, not a Docker-having local gate.

## External / waiting (NOT buildable — Jon or Tim)
- **Jon**: IG/TikTok developer apps (`docs/SOCIAL_API_SETUP.md`, secrets are empty containers);
  LinkedIn partner review worth starting. Jon is doing this himself.
- **Tim**: sending real estimates/proposals now. Still owed: 5× golden proposals/quotes/contracts/
  Roofr reports (end-to-end validation), Jupiter branch pricing values, pm_incentive sign-off.

## CRITICAL GOTCHAS (learned this session — don't rediscover)
- **CI gate ≠ local gate.** Backend CI has NO testcontainers → `@pytest.mark.postgres` tests SKIP
  → any coverage that only those tests provide FAILS the 100% gate in CI while passing locally
  (Docker runs them). ALWAYS gate with `pytest tests/ -m "not postgres" --cov=core
  --cov-config=.coveragerc --cov-fail-under=100` (background to /tmp log + EXIT marker).
- **Shared-tree agent discipline**: NEVER let a subagent run `git` (one ran `git stash` and
  reverted 3 engineers' work). Subagents = file edits only; the main lane commits. Give each
  concurrent agent a NON-overlapping FILE BOUNDARY. Verify worktree isolation actually happened.
- **Subagent gate scoping**: with concurrent core/ work, the global `--cov=core` gate fails on
  other lanes' WIP; tell agents to gate scoped (`--cov=core.<their_module>`); the main lane runs
  the global gate after all land — ideally on a CLEAN CLONE of the commit, not the live tree.
- **Output-compressor garbles piped JSON/curl** — write to a temp file, parse with a separate
  python step (bit us twice: cloudflare token store + curl JSON). Also garbled a stored secret
  once (had to destroy+re-add clean via `--data-file`).
- **Deploy backgrounding**: `bash scripts/deploy.sh &` gets SIGHUP'd when the tool shell exits
  (Cloud Build runs server-side but the Cloud Run update dies). Use `run_in_background: true`.
- strict=True is LIVE — any new session must be stamped (get_db_session / for_each_tenant /
  tenant_id param) or platform_scope; migrations additive .sql; R3 infra via terraform only.
- Prod smoke token recipe: memory `c1-deploy-blocked-gcloud` (SA-key-signed custom token).

## Deploy mechanics
Backend `scripts/deploy.sh` (clean tree; fresh gcloud CLI token). Frontend `cd web && npm run
build && firebase deploy --only hosting --project video-archival-and-content-gen`. Migrations
`GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen MIN_MIGRATION=00XX .venv/bin/python
scripts/apply_migrations_adc.py` (ADC-only). Infra `cd infra && TF_VAR_cloudflare_api_token=$(...)
terraform apply` — never gcloud-by-hand (R3).

---
**Standing archive directive (performed this session):** moved oldest top-level
`CONTINUATION-2026-07-08-pm.md` → `docs/continuations/`, kept latest 3 top-level (2026-07-10-pm,
2026-07-10, 2026-07-09), fixed inbound links (README.md, CONTINUATION-2026-07-09.md), updated
prompt.txt to point here. Apply on every continuation.
