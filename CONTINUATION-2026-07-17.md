# Continuation — 2026-07-17

Big session. Everything below is committed to `main` and **deployed + verified in prod**
unless marked otherwise. HEAD is `b609fe3`.

## The one-time thing that changed everything: deploy SA
The Workspace reauth policy expires all of Jon's Google creds (gcloud/ADC/Firebase) and
blocks non-interactive refresh — that's why deploys kept dying. **Fixed permanently** by
`perkins-deploy-sa` (owner, non-expiring):
- Key at `~/.config/gcloud/perkins-deploy-sa.json`, backed up in Secret Manager
  (`perkins-deploy-sa-key`), and `export GOOGLE_APPLICATION_CREDENTIALS=…` is in `~/.bashrc`.
- gcloud is activated as the SA; terraform (ADC) and Firebase both use it. **No more approvals.**
- Codified in `infra/main.tf` + imported into state (84b83ff). Owner-scoped (Jon's call);
  least-privilege hardening is a documented follow-up.
- **To act on GCP in the next session:** `export GOOGLE_APPLICATION_CREDENTIALS=/home/jon/.config/gcloud/perkins-deploy-sa.json`
  (or rely on the bashrc export). Everything runs non-interactively.

## Shipped this session (deployed + verified)
- **SEO sanitizer** unified + YouTube-only iframe allow-list (earlier commits).
- **A2 real active-speaker tracking** (YuNet, head-cut-avoidance) — `c9e1b15` era.
- **Prompt-to-clip**: `POST /clips/search` cross-corpus NL clip search.
- **Clip Studio parity**: 16:9 export, honest Cut/Fade transitions, brand caption theming, PEXELS wiring.
- **#316 titles**: `clean_title` parser fixed; 40 hashtag-only video titles backfilled in prod.
- **#335 DMARC** flipped to `p=reject` (verified live); 28 report emails trashed.
- **#319** social app-registration plan: `docs/plans/2026-07-17-social-app-registrations.md`.
- **Comments E1 gate** (a00cd78): the live YouTube reply path now runs `run_gate` (was unwired — real bug).
- **OAuth health alarm + capture backend** (ralplan consensus-approved, plan at
  `docs/plans/2026-07-17-comments-oauth-plan.md`): `integration_status`/`oauth_state_nonces`
  (migration 0039, platform-level NO-RLS), `core/integration_health.py` (severity-split),
  `adapters/integration_probes.py` (liveness-only), `jobs/integration_health_job.py` +
  `/internal/integration-health` + 30-min scheduler + Cloud Monitoring. **Alarm is LIVE and
  verified**: probes wordpress/resend/knowify/youtube_reply, emails admins on transition-to-broken.
  `core/oauth_state.py` (HMAC state, 100% cov) + `api/routes/connections.py` (capture routes,
  deployed but dark until wired — see KNOWN_GAPS).
- **Phase 2 comments** (a645a64, migration 0040 applied): `comment_drafts.platform` column +
  tenant-scoped `(tenant_id, platform, comment_id)` unique.
- **Production-readiness panel** (ee1ec4d): `core/production_gates.py` (7 gates) +
  `GET /config/production-readiness` + dashboard-top banner (`Status.tsx`) + Admin Config
  section (`Settings.tsx`). **Prod eval: READY=True, 0 blockers, 4 warnings** (email test-mode,
  WP staging, knowify unconfigured, oauth-capture off — all expected).

## Gaps: repaired or documented
See **`docs/KNOWN_GAPS.md`** (drafted via Hermes, corrected). Highlights:
- RLS security gate **passes** (app role is already NOSUPERUSER NOBYPASSRLS — verified; earlier "blocker" guess was wrong).
- Terraform **drift** (7 resources, cloudflare/gotenberg/domain) — needs Jon's review, not a blind apply.
- Migration-replay `;`-splitter still can't handle enum/complex statements (DR-only gap; inline-comment strip fixed).

## What's LEFT — "finish the gaps" (next session)
Ordered by value:
1. **Least-privilege the deploy SA** (drop owner → scoped roles) — security hardening.
2. **Migration replay robustness** — swap the `;`-splitter for `sqlparse`/`psql -f` so DR rebuild works.
3. **Terraform drift** — review the cloudflare WAF + custom-domain + gotenberg intent with Jon; apply or codify.
4. **Pexels real key** — add the secret version to light up b-roll.
5. **OAuth capture UI** — only when #319 lands (build `Connections.tsx`, wire HMAC key + redirect base + register redirect URIs).
6. Optional: email → live mode when a verified sending domain is ready; flip WP staging→prod (#317, clears noindex).

## Verify / operate
- Full test suite was running at hand-off (slow ~15min); targeted suites for everything
  shipped are green. Re-run: `.venv/bin/python -m pytest -q`.
- Prod DB access: `/tmp/cloud-sql-proxy --port 5432 video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg &`
  then `DB_URL=postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins`.
- Deploy: `bash scripts/deploy.sh` (API+jobs, needs clean tree); `cd web && npm run build && npx firebase deploy --only hosting --project video-archival-and-content-gen`.
- Migrations 0039 + 0040 are applied to prod. Apply future ones directly (the full replay has the documented splitter gap).

## Afternoon update (post the sections above)
- **CompanyCam / Roofr research** (agent, cited): CompanyCam = integrate-now (self-serve
  Personal Access Token, REST v2, photos/docs pull + webhooks). Roofr = **no public API**;
  can't order/pay/pull a report PDF via API — keep the manual PDF import. For programmatic
  order→pay→PDF+structured-measurements: **EagleView Measurement Orders API** (best),
  RoofScope cheaper; **Google Solar API** (already in #331) = free instant first-pass.
- **YouTube reply 403 — root-caused + fixed** (`d2a6dc4`, deployed): the reply token
  authorizes a Google account with **no YouTube channel**, but comments.insert posts AS a
  channel → 403. Token is valid + force-ssl-scoped, so every old check read green.
  Fix: `posting_channel()` precheck (channels?mine=true); `/comments/reply-config` returns
  can_post + reason; 403→409 reconnect_required; probe now reads youtube_reply BROKEN; UI
  shows a reconnect prompt. **Still needs**: re-mint the token as the "Perkins Roofing Corp."
  channel owner (Tim), and enable the one-click connect button (HMAC value + redirect base +
  callback URI registration).

## ⚠️ Property-save 500 + the TDD gap it exposed (`16a662b`, deployed)
**Bug**: POST/PUT `/quoting/customers/{id}/properties` 500'd in prod —
`value too long for type character varying(2)` (user sent `state="Florida"`).
`PropertyCreate/Update` had no length limits; the DB columns do.
**Why TDD missed it — the important lesson**: the test suite runs on **SQLite, which IGNORES
`VARCHAR(n)` length limits**; prod is Postgres, which enforces them. Any oversized-string
input passes on SQLite and 500s on prod. No negative test for oversized fields existed.
**Fix**: Pydantic `max_length` mirroring the columns → clean 422 on both DBs. 5 negative
tests written TDD-first (failed at 200, pass at 422).

**This is SYSTEMIC, not one endpoint.** ~90 length-bounded `String(n)` columns exist and
**21 route files** have create/update/request Pydantic schemas — most likely share the gap.

## What's LEFT — next session's primary task: endpoint coverage + negative tests
1. **max_length audit across ALL create/update schemas** (21 route files): every Pydantic
   str field mapping to a length-bounded DB column needs `max_length` matching it. This is the
   root-cause class of the property 500. Grep `Column(String(N))` in app/models.py, map table→
   schema, add bounds + a negative test each. Parallelize across route-file clusters (agents).
2. **Negative tests for every endpoint**: oversized fields, missing-required (422), wrong-type,
   not-found (404), cross-tenant/authz (403/401), and — critically — run the length/constraint
   ones under the Postgres harness (`scripts/test_pg.sh`), since SQLite hides these.
3. **Push endpoint coverage toward 100%** with the above; adapters/api/jobs are coverage-omitted
   by R1 but behavioral validation is required — negative tests ARE that validation.
4. Consider a conftest/CI note: SQLite hides VARCHAR + some constraint violations — the
   constraint-sensitive suites belong on the PG harness.

Earlier remaining items still stand: least-privilege the deploy SA, migration-replay robustness
(sqlparse), terraform drift review, Pexels key, OAuth capture-UI + YouTube token re-mint,
CompanyCam adapter build, EagleView measurement API (optional estimator upgrade).

---
*Standing archive directive performed: moved the oldest top-level CONTINUATION into
`docs/continuations/`; only the latest 3 remain at top level.*
