# CONTINUATION — 2026-07-11 (Knowify MCP restart + late-session build wrap)

Handoff for resuming after a Claude restart. The restart's PURPOSE: load the newly
registered **Knowify MCP** so we can pull Knowify data. Read this + the memory index
(auto-loaded) + `prompt.txt`. HEAD at write time: `d1ced04`. CI: green at last gate.
Prior handoff: `CONTINUATION-2026-07-10-pm.md`.

## ⚡ DO THESE FIRST, IN ORDER

### 1. Get the Knowify MCP working (the reason for the restart)
- It's already registered in this project's Claude Code config (`claude mcp list` →
  `knowify: https://assistant.knowify.com/api/v2/mcp (HTTP) - Needs authentication`).
- **Jon action:** run `/mcp` → select **knowify** → **Authenticate** → browser opens →
  log in with **Knowify admin credentials**. OAuth (no passwords stored). After auth,
  two READ-ONLY tools appear: **Platform Knowledge** + **Query Knowify**. Use them to
  explore (e.g. "list all open invoices", "which jobs are underbilled").
- The MCP is read-only + conversational (2 tools only). For **bulk extraction** (the
  Knowify-replacement migration, task #15) use the REST importer instead (below).

### 2. T&C AI-FAQ (task #17) — DONE + COMMITTED (`db01b57`); just verify the deploy landed
The `tc-aifaq` build finished, was self-reviewed + gated (core 100%, ruff clean), and is
**committed** (`db01b57`). I added an lru_cache so the 2 LLM calls run once per T&C text,
not per PDF render. Migration 0029 (DRAFT TcVersion seed) was applied; a backend deploy was
kicked off right before the restart. **On resume:** confirm the deploy completed —
`gcloud run services describe api --region=us-central1 --format='value(spec.template.spec.containers[0].image)'`
should show `:db01b57` (or newer). If it shows an older sha (the deploy was interrupted by
the restart), re-run `bash scripts/deploy.sh` (run_in_background). What it does: proposal PDFs
gain a cover letter + AI bullet summary of the T&C + recommended AI-review prompts + attorney
disclaimer + last-page FAQ (terms UNCHANGED; best-effort — proposal renders even if generation
fails). DEFERRED to JB3: formal R2 (architect+critic), Tim's real-T&C sign-off (currently
`core/tc_seed.py` DRAFT v0.1 from Josh's proposal), per-tenant T&C from the DB TcVersion, and
SPA surfacing of the cover/FAQ.

### 3. Then continue autopilot on the approved plan (see "Pending" below).

## Knowify integration — full details (memory: `knowify-integration`)
- **Read-only MCP**: `https://assistant.knowify.com/api/v2/mcp` (2 tools). Registered;
  auth via `/mcp`.
- **REST API v2 (the real bulk source)**: `https://api.knowify.com/v2/<entity>` — full
  granular read/write scopes (invoices, clients, projects, bills, payments, milestones,
  items, purchases, time-entries, contracts, documents, vendors, submittals, assets,
  users, …).
- **OAuth AS**: `https://developers-v2.knowify.com` — Dynamic Client Registration is
  OPEN (verified live: accepts a public PKCE client). So NO custom MCP server needed and
  NO passwords in `.env`.
- **Bulk importer (built + committed, `scripts/knowify/`):**
  ```
  python scripts/knowify/knowify_oauth.py     # browser login once (read-only scopes)
  python scripts/knowify/knowify_pull.py       # dump every entity → /tmp/knowify_data
  ```
  Tokens → `~/.config/knowify/tokens.json` (chmod 600, OUTSIDE repo). Read-only only;
  `:write` scopes reserved for future QuickBooks/write-back. First `knowify_pull` run
  reveals the exact pagination shape (defensive; tweak if `_summary.json` shows gaps).
- Use the pulled data to validate + finalize the invoicing/milestone/numbering model
  (task #15) and QuickBooks mapping.

## Shipped + LIVE this session (all deployed to prod unless noted)
- **Pricing analysis**: all-tabs export of Tim's 2 workbooks → 3-axis answer (roof-type ×
  zone × branch); OI-7 (HVHZ commission 15%) + OI-8 (pm_incentive) sheet-evidenced; Naples
  has no source tab. Doc: `docs/superpowers/specs/2026-07-10-pricing-workbooks-analysis.md`.
- **Estimator v2** (task #10 done): day-based overhead + flat-dollar profit, Tim's 2 golden
  examples pass, R2-reviewed, deployed. Validated against Tim's silent screen-recording
  (`Part 1.mp4`): $29,406/mo ÷ 20 days = $1,470/day ÷ 11 men = $134/man-day, and the
  per-series rates ($1,050/$745/$850/$700) = crew-size × $134 — internally consistent.
- **Ez-Bids W0** (deployed): DB-backed dynamic CORS + council hardening + T-4 settings seam
  + brand tokens; migrations 0026 + 0027 (CORS scope hotfix) applied. R2-reviewed.
- **Tim's link bug** (task #13 done): `/ask` renderer regex swallowed the comma between
  citations → fixed + prompt hardened; live.
- **Invite email**: `/admin/users/invite` now sends a branded HTML invite (Perkins logo on
  white header) via Resend; adapter gained bcc + explicit User-Agent (Cloudflare-1010 fix);
  reusable `scripts/send_invite.py`. Vlad (burademirung@) invited + emailed. Deployed.
- **Video-unavailable** (deployed): KPI poll flags deleted/private-on-YouTube videos
  (transient-failure-guarded), amber badge + reversible Hide/Unhide + "Show hidden";
  NO hard-delete (GCS archive kept). Migration 0028.
- **Estimator admin cleanup** (deployed): EstimatingConfig grouped into 5 collapsible
  sections + NEW Day-Based Overhead & Profit controls (Tim can now edit daily rates/floors).
- **Knowify tooling** (committed): CLI OAuth login + read-only importer (above).
- **Tim doc corpus** analyzed → `docs/superpowers/specs/2026-07-10-tim-docs-requirements-brief.md`
  + `docs/superpowers/specs/tim-docs/{proposals,invoices,details_orders_roofr}.md`.
- **Ez-Bids PRD/TRD/DDD** synced to the council-revised plan.
- **Job-docs & billing plan** APPROVED (consensus): `.omc/plans/ralplan-perkins-jobdocs-billing-DRAFT.md`
  — 6 waves JB1–JB5 (price book → measurements/details → order engine/Roofr → proposal
  engine → invoicing/milestones → e-sign/QuickBooks), migrations 0028–0033 provisional
  (renumber above whatever Ez-Bids lands).

## Pending / buildable (autopilot after steps 1–3)
- **#17 T&C AI-FAQ** — SHIPPED (`db01b57`, backend). Follow-ups only: SPA surfacing of the
  cover/FAQ, Tim's real-T&C sign-off, per-tenant T&C from DB, formal R2 at JB3.
- **#12 Material price book** (JB1) — ABC (42926) tab import + admin edit UI + estimator
  material-side wiring. Daily-cost variables confirmed present (OH Metrics tab + video).
- **#14 Proposal generation** (JB3) — master template + tiers + scope blocks + payment
  schedules; the T&C-FAQ (step 2) is a JB3 component.
- **#15 Invoicing/milestones/e-sign/QuickBooks** (JB4/JB5) — use the Knowify import to
  validate; align with Ez-Bids W4 (tokens) + W5 (billing patterns).
- **Ez-Bids W1** (explicit tenant-1 binding + Perkins-smoke gate) → W2 (ezbids.degenito.ai
  onboarding; CF token ready) → W3–W7.

## Waiting on people
- **Tim** (follow-up logged in Jarvis for 7/13): milestone schedule (15/30/30/25 inferred,
  not observed), HVHZ commission 15% (sheet says so; engine defaults 10%), pm_incentive
  sign-off, Naples OH basis, invoice payment methods; share master calc files + the "2026
  Overhead Breakdown" sheet + an AUDIO walkthrough (Part 1.mp4 had no audio).
- **Jon**: Knowify `/mcp` auth (step 1); Facebook/Meta Business admin access (blocks IG+FB
  social posting — see below); optional terraform apply of Cloudflare WAF/rate-limits on
  perkinsroofing.net (pre-existing drift, customer-facing — do in a low-traffic window).

## Social/repurpose.io (assessed, not built)
Distribution pipeline already exists (adapters + scheduler + Clip Studio). Replicating
repurpose.io is mostly an APPROVALS problem, not code. IG API posting REQUIRES Facebook
account + linked Page (2026) — Jon's IG-only login can't post to IG/FB without Meta
Business access. Recommendation: hybrid (own YouTube/X/LinkedIn; keep repurpose.io for
TikTok/Meta until approvals clear), or feed repurpose.io. TikTok bans app-added
watermarks → needs a clean clip variant.

## Critical gotchas (memories carry details)
- **Deploy is NOT concurrency-safe** ([[deploy-not-concurrency-safe]]) — never run two
  `deploy.sh` at once (Cloud Run job optimistic-lock ABORT); verify image sha vs HEAD, don't
  thrash. Deploy via `run_in_background`, not `&` (SIGHUP).
- **CI gate ≠ Docker gate**: always `pytest -m "not postgres" --cov=core --cov-fail-under=100`
  (postgres tests skip in CI). Subagents = file edits only, never git; non-overlapping
  boundaries; main lane commits.
- **Resend UA** ([[resend-ua-cloudflare-1010]]) — adapter sends explicit UA (Cloudflare 1010).
- **strict=True LIVE** — stamp every DB session; migrations additive .sql; R3 infra via
  terraform only. Output-compressor garbles piped JSON → write to file, parse separately.
- **Jarvis O365 mail** ([[jarvis-o365-degenito-mail]]) — pull jon@degenito.ai mail via
  cerberus `~/gmail-enhanced-mcp` (verify_ms.py + Graph). Session-local gmail MCP has no accounts.

## Deploy mechanics
Backend `bash scripts/deploy.sh` (clean tree; fresh gcloud token; run_in_background).
Frontend `cd web && npm run build && firebase deploy --only hosting --project
video-archival-and-content-gen`. Migrations `GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen
MIN_MIGRATION=00XX .venv/bin/python scripts/apply_migrations_adc.py`. Infra `cd infra &&
TF_VAR_cloudflare_api_token=$(gcloud secrets versions access latest --secret=cloudflare-api-token
--project=video-archival-and-content-gen) terraform apply`.

---
**Standing archive directive (performed this session):** moved oldest top-level
`CONTINUATION-2026-07-09.md` → `docs/continuations/`, kept latest 3 top-level
(2026-07-11, 2026-07-10-pm, 2026-07-10), fixed inbound links (README.md,
CONTINUATION-2026-07-10.md, CONTINUATION-2026-07-10-pm.md), refreshed the README
most-recent pointer to this file. Apply on every continuation.
