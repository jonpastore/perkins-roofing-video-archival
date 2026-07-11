# CONTINUATION — 2026-07-10 (Perkins full-funnel platform)

Handoff for resuming after `/clear`. Read this + the memory index (auto-loaded, esp.
`c1-deploy-blocked-gcloud`) + `prompt.txt`. Prior handoff: `docs/continuations/CONTINUATION-2026-07-09.md`.

## TL;DR — where we are
**C1 Part 2 (strict=True) and #321 Contract-FAQ are BUILT, GATED, R2-REVIEWED, and COMMITTED
— but NOT DEPLOYED.** Deploy + migration 0023 + prod smoke are blocked on ONE thing: both the
gcloud CLI token AND user ADC hit Google's reauth (rapt) expiry mid-session. Jon must run
`! gcloud auth login` and `! gcloud auth application-default login`, then follow the runbook below.

## Committed this session (all on main, NOT pushed — push blocked? no, push works via SSH; push if not already)
- **`a5b694d` feat(C1): strict=True** — the tenant-2 gate. Retrieval chain threads the caller's
  stamped session (db=None compat); for_each_tenant enumeration platform_scope; proposal_reminders
  refactored onto for_each_tenant (deployed scheduler would have crashed); render_job PlatformConfig
  reads → PlatformSessionLocal; app/ingest.py ingest_video/status stamped via tenant_id param
  (deployed every-minute cron — found by R2 review, incl. the transcript-error branch); grounding
  catches escalate strict RuntimeError to CRITICAL. NOTE: also contains the ContractFaqEntry model
  (builder-agent contamination, harmless/unreferenced at that commit).
- **`4caa493` fix(security): deepsec L2 + M/L** — proposal template render → Jinja2
  SandboxedEnvironment (tenant-editable html_body was SSTI→RCE; autoescape ≠ template-source
  safety) + `npm audit --omit=dev --audit-level=high` gate in CI.
- **`7afcf69` feat(contract-faq): #321** — T&C→grounded-FAQ engine (core prompt/parse/grounding,
  5 routes, SPA page, migration 0023, 60+ tests). R2 findings fixed: H1 grounding-gate hardened
  (≥20 chars/≥4 tokens verbatim), H2 **generic after_create RLS hook** (create_all can never
  again create a tenant table without RLS — platform-wide fix), H3 list/jsonld gated on
  `kb_contract_faq_read` (sales 403s), M1 dedup + skipped_duplicates, M2 model↔migration
  alignment, L1 tc_version_id provenance wired.

## Gate evidence (all green)
ruff clean (`core adapters api jobs`); full suite core **100.00%** (a5b694d run: 2656 stmts;
7afcf69 run: 2688 stmts with the one residual line covered in a follow-up targeted run — CI
re-verifies on push); tenancy PG suite green **with strict registered** (incl. new PG tests:
stamped/unstamped ingest path, contract_faq_entries RLS-forced via the create_all hook);
`cd web && npm run build` green; R2 architect+critic reviews on BOTH waves — all HIGHs fixed.

## RUNBOOK — after Jon reauths (IN THIS ORDER)
1. `! gcloud auth login` (CLI, for deploy.sh) and `! gcloud auth application-default login` (ADC).
2. Push if needed: `git push origin main` (CI runs the full gate + npm audit).
3. **Migration 0023 FIRST** (routes in the image query the table):
   `GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen MIN_MIGRATION=0023 .venv/bin/python scripts/apply_migrations_adc.py`
4. `scripts/deploy.sh` (needs CLEAN tree — it is clean at c3e7868+3).
5. `cd web && npm run build && firebase deploy --only hosting --project video-archival-and-content-gen`
   (needs `! firebase login --reauth`) — ships the Contract FAQ page.
6. **PROD SMOKE (the authoritative strict=True validation — SQLite no-ops the event):**
   - Mint token: recipe in memory `c1-deploy-blocked-gcloud` (SA-key-signed custom token via
     vertex-dev-sa-key secret + web/.env API key; signInWithPassword is DISABLED).
   - `POST /search`, `POST /ask` (now stamped via get_db_session), `GET /status`, one CRUD route
     (e.g. GET /customers), `GET /contract-faq` (admin token), and
     `gcloud run jobs execute ingest --region us-central1` — expect no 500s; check Cloud Logging
     for `tenant_id not set on session.info` (the strict raise signature) — must be absent.
   - Watch the every-minute `run-ingest` cron for one cycle post-deploy.
7. If a strict raise appears in ANY prod path: rollback = redeploy image `d9e2e5b`
   (previous good) or flip `strict=False` in app/models.py:659 + redeploy; then fix forward.

## Open / not done
- **#89 retrieval/eval harness** (the last "production v1" checklist item) — not in this
  session's scope, still open.
- **MEDIUM noted, not fixed (intended contracts, documented):** proposal reminders now iterate
  ACTIVE tenants only (for_each_tenant contract); /contract-faq/generate has no _estimate_cost
  helper (count≤20 + one LLM call + dedup judged sufficient for now).
- **Gated on Jon (unchanged):** H1 Cloudflare edge/DNS (jarvis #330), Tim's estimator pricing +
  clips + ToS, YouTube reply-OAuth mint, deposit/ownership reconcile, GSuite domain-wide delegation.

## Lessons (this session)
- **Agent worktree isolation can silently fail** — the #321 builder wrote into the main tree
  while the C1 release was in flight (quarantine + explicit-path commits saved it). Verify
  `git worktree list` shows a real worktree before letting a builder run concurrently.
- **Background pytest under headroom block-buffers**: a "stuck at 23%" log with no visible
  pytest process can still be a live run — trust the EXIT marker, monitor with staleness+pgrep.
- **SQLite can't validate strict**; the ONLY unstamped-session detector pre-prod is
  `grep -rn "SessionLocal()" app/ api/ jobs/` + tracing each hit to a deployed entrypoint.

---
**Standing archive directive (performed this session):** moved the oldest top-level
`CONTINUATION-2026-07-08.md` → `docs/continuations/`, kept the latest 3 at top level
(2026-07-10, 2026-07-09, 2026-07-08-pm), fixed inbound links (README.md,
docs/superpowers/specs/full-funnel/PRD-estimating.md), and updated `prompt.txt` to point here.
Apply this directive on every continuation.
