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

---
*Standing archive directive performed: moved the oldest top-level CONTINUATION into
`docs/continuations/`; only the latest 3 remain at top level.*
