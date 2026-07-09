# CONTINUATION — 2026-07-09 (Perkins full-funnel platform)

Handoff for resuming after `/clear`. Read this + the memory index (auto-loaded, esp.
`perkins-full-funnel-reorg`) + `prompt.txt`. Prior handoff: `CONTINUATION-2026-07-08-pm.md`.

## TL;DR — where we are
F0–F6 are **all built, deployed to prod, deepsec-hardened, and the infra drift is reconciled.**
The remaining substantive engineering task is **C1 Part 2** (the `strict=True` tenant-2 gate).
Everything else open is either external/gated-on-Jon or a discrete buildable (Contract-FAQ engine).

## Live in prod
- **Backend**: Cloud Run service `api`, image **`d9e2e5b`** (was f111e19 before C1 Part 1). `/health` → `{"ok":true}`. API + 4 jobs (ingest/render/article/social) + `gotenberg` PDF service + `proposal-reminders` scheduler.
- **Frontend**: Firebase Hosting `https://video-archival-and-content-gen.web.app`.
- **DB**: Cloud SQL `video-archival-and-content-gen-pg`, db `perkins`, role `app` (NOSUPERUSER NOBYPASSRLS). **Migrations 0013–0022 applied.** 29 tenant tables RLS-FORCED; PITR ON.
- Only **tenant 1 (Perkins)** exists. No tenant 2 yet — that's what C1 gates.

## Deploy mechanics (IMPORTANT)
- Backend: `scripts/deploy.sh` (Cloud Build → AR → Run). **Refuses a dirty tree** (image tagged with git SHA). Needs a fresh **gcloud CLI** token — run `! gcloud auth login` (this is SEPARATE from ADC).
- Frontend: `cd web && npm run build && firebase deploy --only hosting --project video-archival-and-content-gen`. Needs `! firebase login --reauth` (Firebase CLI has its own creds).
- Migrations: `GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen MIN_MIGRATION=00XX .venv/bin/python scripts/apply_migrations_adc.py` — ADC-only (fetches db-password via Secret Manager client; sidesteps stale gcloud CLI). Uses ADC = jon@perkinsroofing.net (already set).
- Terraform: `infra/`, ADC works. `terraform plan` clean except `domain_mapping.api` (DNS-gated) + one benign gotenberg scaling perpetual diff. **NEVER gcloud-by-hand for infra (R3).**

## THE ACTIVE TASK — C1 Part 2 (Jarvis task; local task #38)
**C1 = make the app tenant-aware so `strict=True` can be flipped (the tenant-2 gate).**
`strict=True` (app/models.py ~line 638) makes the after_begin event RAISE for any UNSTAMPED
tenant `SessionLocal` session instead of silently defaulting to tenant 1. It's a **GLOBAL** flag
on the `SessionLocal` factory, so EVERY request-path unstamped session must be converted first.

**Part 1 — DONE (commit `d9e2e5b`, deployed):** ~70 tenant-scoped API route blocks across 16
files converted from `with SessionLocal()` → `db: Session = Depends(get_db_session)` (RLS-stamped
to the caller's verified tenant). Insert `tenant_id` → `db.info["tenant_id"]` (was hardcoded 1).
Platform routes (config.py, brand-upload, email header) → `PlatformSessionLocal`. topics
`_derive_subtopics` threads caller db. `/status`+`/status/retry` converted. Gate green (core 100%,
api + tenancy-PG, ruff clean).

**THE PATTERN (proven — copy it):** for a tenant-scoped route, add `db: Session =
Depends(get_db_session)` after `require_role(...)`; delete `with SessionLocal() as db:` and dedent;
`db.commit()`→`db.flush()`; keep `db.refresh()`; insert `tenant_id=db.info["tenant_id"]`.
Platform-table routes → `with PlatformSessionLocal() as db: db.info["platform_scope"]=True`.
Reference file already correct: `api/routes/customers.py`, `api/routes/measurements.py`.

**Part 2 — REMAINING (do in order, then flip strict):**
1. **Thread stamped `db` through the retrieval chain** (all query RLS-forced chunks/content_graph unstamped today): `app/store.py:vector_search`, `app/retrieval.py:hybrid_search`+`search`, `app/answer.py:ask`+`answer_faq`. Use a `db=None` param; if None open own SessionLocal (compat), else use+don't-close the passed one. Update callers: `api/app.py` `/search`(line ~211 `R.search`) + `/ask`(~216 `A.ask`) add `db: Session = Depends(get_db_session)` and pass it; `api/routes/faq.py` (~100 `answer_faq`) pass its `db`; `jobs/prime_backlog.py` (~71) is a script — pass a stamped session or accept it runs outside strict.
2. **`core/tenant_loop.py:for_each_tenant`** enumerates tenants via a RAW unstamped `SessionLocal` on the platform `tenants` table → would RAISE under strict. Change the enumeration to `PlatformSessionLocal` (the per-tenant `fn(db, tenant_id)` sessions are already stamped — leave those).
3. **Audit job top-level sessions**: `jobs/ingest_worker.py:36`, `jobs/article_job.py:649/692` — if they touch the platform `tenants` table for enumeration use PlatformSessionLocal; per-tenant bodies run under for_each_tenant (stamped, fine).
4. **Flip `strict=True`** in `app/models.py` (~line 638: `register_tenant_session_events(SessionLocal, strict=False)` → `strict=True`).
5. **Verify**: full gate (SQLite is a no-op for the event — strict only bites on Postgres), tenancy PG suite, then DEPLOY + **prod smoke**: hit `/search`, `/ask`, `/status`, a CRUD route with a real token, and run one job — confirm no 500s. This is the real test since SQLite can't exercise strict.

## Other open work
- **#39 / H1 — public edge** (GATED ON JON): accept-page rate-limit + origin lockdown. Needs Jon's **Cloudflare token** (jarvis #330 DNS: Tucows→Cloudflare via Amber) + a load balancer. Also un-blocks the `domain_mapping` terraform drift and deepsec M4 (stop trusting XFF for e-sign IP).
- **#321 Contract-FAQ engine** (BUILDABLE): `web/src/pages/ContractFaq.tsx` is a "Coming in F5" STUB — no backend. Build: parse Perkins T&Cs → LLM FAQ (reuse the FAQ/JSON-LD/safety-gate machinery from `core/` + `api/routes/faq.py`).
- **#40 deepsec M/L backlog**: L2 (sandbox-review proposal template render), `pip-audit`+`npm audit` in CI. M4 rides on H1.
- **#89 → 90%**: only the retrieval/eval harness remains of the "production v1" checklist.
- External/Tim (Jarvis): #317 intro/outro clips + Two Cows registrar, #318/#324 estimator base-cost + Roofr-quote validation, #88 comment-bot ToS opt-in, #327 Google Earth Premium, #329/#323 Ez-Bids/Knowify PDFs+legal, YouTube reply-OAuth mint. **#86** (client GCP standup) + the client-project proposal/deposit tasks: reconcile the deposit/ownership status — code deliverable exists (pipeline deployed) but the business fact is Jon's.

## CRITICAL GOTCHAS (learned this session — don't rediscover)
- **RLS GUC + pooled connections**: an RLS policy `current_setting('app.tenant_id', true)::int` is NOT safe on pooled connections — a set-then-reset custom GUC reads back as `''` (not NULL), and `''::int` RAISES. ALWAYS `NULLIF(current_setting(name,true),'')::int`. (Fixed in 0022; a fresh-connection probe passes but the pooled path 500s — only the PG-fixture test caught it: `tests/tenancy/test_proposals_token_policy.py`.)
- **Migrations doing DML on RLS-FORCED tables FAIL** under the `app`-role runner (NOBYPASSRLS, no app.tenant_id → policy raises). Use DDL (`ADD COLUMN ... DEFAULT`) for backfills, or set app.tenant_id, or a bypass role. (0021 was reworked for this.)
- **Headroom garbles inline pytest output.** Always run `(.venv/bin/python -m pytest ... > /tmp/x.log 2>&1; echo EXIT=$? >> /tmp/x.log)` and trust ONLY the log summary + EXIT marker. Use `-p no:cacheprovider`.
- **Coverage gate**: `.venv/bin/python -m pytest tests/ --cov=core --cov-config=.coveragerc --cov-fail-under=100`. core/ must be 100%; adapters/api/jobs are coverage-omitted (so api-route regressions are caught by `tests/api/*`, NOT the % gate). CI also runs `ruff check core adapters api jobs` — keep it clean (`ruff check --fix`).
- **Tenancy PG suite** needs Docker/testcontainers (pgvector/pgvector:pg15). `tests/tenancy/conftest.py` applies 0018+0022 on top of create_all + connects as a NON-BYPASSRLS role.
- `get_db_session` 403s a caller with NO tenant_id (platform_admin without impersonation) — that's intended. `PlatformSessionLocal` has NO after_begin event (never raises; use for platform tables). `SessionLocal` has the event.
- `strict=True` is GLOBAL; SQLite tests no-op the event (dialect guard) so they can't validate it — prod smoke is the real test.

## Locked decisions (unchanged — don't relitigate)
GCP + Postgres RLS + tenant_id; GCIP (Firebase Identity Platform) claim mapping; Cloudflare
ingress; app.perkinsroofing.net; e-sign-lite + Gotenberg PDF; royalty-free music only; no
payments/CRM/native-iOS v1; eaglepoint/SquareQuote reference-only. TDD fail-first ALWAYS; R2
architect+critic review per wave; 100% core coverage; R3 IaC-only (git→apply, never reverse);
implementation subagents = sonnet, opus for plan/review/security only; migrations `.sql` only;
no prod DB changes / deploys without explicit Jon OK (he has been saying "do it / greenfield").

---
**Standing archive directive (performed this session):** moved the oldest top-level
`CONTINUATION-2026-07-06-pm.md` → `docs/continuations/`, kept the latest 3 at top level
(2026-07-09, 2026-07-08-pm, 2026-07-08), fixed inbound links (README.md, CONTINUATION-2026-07-08.md),
and updated `prompt.txt` to point here. Apply this directive on every continuation.
