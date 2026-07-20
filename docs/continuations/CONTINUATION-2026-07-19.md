# CONTINUATION — 2026-07-19 (Perkins v2 platform)

Resume after `/clear`. Big multi-part session: finished Zoom estimator items, built CompanyCam +
B9 scaffolds, resolved nearly all Cloudflare IaC drift (incl. a v4→v5 provider migration on live
email DNS), ran a 6-way deep review, and fixed the review's demo-critical items. **All shipped +
deployed + prod-verified. Tree clean, `main` == origin.**

## Current prod state
- HEAD `b9777a2` on `main` (pushed). API image **b9777a2** (Cloud Run rev `api-00109-lbb`, 100%).
  SPA deployed to **app.perkinsroofing.net** (CNAME → `video-archival-and-content-gen.web.app`, the
  Firebase `app` hosting target — one deploy updates both; the `.web.app` URL is just Firebase's
  canonical alias). app + api both 200.
- Cloudflare provider now **v5.22.0**. `terraform plan` = **0 add / 0 destroy / 1 benign in-place**
  (gotenberg `0↔null` scaling cosmetic — provider quirk, unfixable, documented).
- CREDS unchanged: all gcloud/terraform/firebase run under the non-expiring SA
  `export GOOGLE_APPLICATION_CREDENTIALS=/home/jon/.config/gcloud/perkins-deploy-sa.json`
  (also in ~/.bashrc; re-export after any `source .env`). CF token in Secret Manager
  `cloudflare-api-token`; `drift_check.sh` now self-injects it.

## What shipped this session (commits a8d6260..b9777a2)
1. **Zoom 1d — low-slope estimator inputs** (`75941ad`): deck/attach-system selector + Insulation +
   Tapered-ISO toggles in Quoting.tsx (low-slope roof types only). Backend: `roof_type` boundary was
   a stale Pydantic `Literal` that 422'd granular exhibit_b keys → now `str` + config-driven
   validation + config-driven low/sloped routing.
2. **B8 branch admin** — was already built; fixed `BranchesConfig.canManage` to admin-only (matches
   backend `manage_config`).
3. **R6 rule** (docs/ENGINEERING_RULES.md): every commit updates docs + drift_check + Jarvis + memory.
4. **CompanyCam connector** (`0c35be9`) — ahead-of-account, inert until `COMPANYCAM_PAT`: adapter
   (REST v2, urllib+UA, paginated), hash-gated tenant-scoped mirror, model + migration 0043 (RLS),
   backfill job (advisory lock 8274126, tenant-1 scoped), health probe, **HMAC-verified webhook**
   `/companycam/webhook` (raw-body-before-parse, constant-time, 503-fail-closed).
5. **B9 QB per-branch scaffold** (`6d03915`) — `branch_accounting` model + migration 0044 (the
   (qb_realm, qb_company, knowify_sub) triple), `qb_client_for_branch` credential seam (raises
   `NotImplementedError` — live QBO HELD), GET/PUT `/branches/{branch}/accounting` admin API.
6. **422 boundary fix** (`3738e33`) — prod e2e caught it: unknown `roof_type` reached the engine →
   `KeyError` → 500. Now validated at the boundary → clean 422. (`scripts/prod_smoke.py` = the
   reusable prod-verify helper: firebase custom-token → ID token → hit prod → delete smoke user.)
7. **Cloudflare IaC drift — nearly cleared**: `drift_check.sh` now injects the CF token (was always
   erroring on the placeholder → false "creds error" masking all drift); untainted 2 tainted
   replaces that a blind apply would've DESTROYED (live SSL + api domain); gated `waf_rate_limits`
   (needs paid plan) + `origin_routing` (unused) behind default-off vars; **removed the vestigial
   `app.perkinsroofing.net` Cloud Run domain mapping** (`ff32417` — impossible/never-Ready: the host
   is Firebase-served); **v4→v5 provider migration** (`9554833` — 13 imports, 0 destroy, verified
   zero-change on live email DNS before apply; resolved the zone_settings perpetual diff).
8. **6-way deep review + fixes** (`b9777a2`) — see below.

## Deep review (2026-07-19): deepsec + critic + architect + designer + local gpt-oss/qwen
**Platform SOUND — 0 critical, 0 live-high.** Confirmed sound: webhook HMAC, migrations 0043/0044
RLS, invoice numbering + payment idempotency + sandboxed PDF, B9 seam (no cred leak), CORS,
proposal-accept, injection/SSRF/IDOR, pip-audit clean. Local models were mostly false positives on
verification (good signal + reminder to verify local output). Full detail in memory
`deep-review-findings-2026-07-19`.

**FIXED in `b9777a2`:** CompanyCam probe `TypeError` on activation (added `ping()` + regression
test), 4 Quoting UX (cut-calc copy = "reference" not a phantom selector; low-slope deck dropdown
"Pending Tim" placeholder; customer picker browsable on empty search; removed dead legacy-calc ref).

## OPEN ITEMS

**Gated on Tim (Jarvis #350/#352 + memory):**
- CompanyCam PAT (Jon on account) → then wire secrets into deploy.sh, apply migration 0043, enable
  backfill, confirm webhook signature envelope/format, add replay protection, **build a
  `companycam_photos` reader** (mirror is write-only today — no consumer).
- B9 live: 4 QuickBooks OAuth + Qvinci accounts; price low-slope systems in prod config (currently
  pending → UI shows "Pending Tim").
- Gutters 7"/6" 2-story price discrepancy; per-branch daily OH; GC branch pricing; YouTube owner token.

**Before activating each scaffold (real, latent — verified):**
- **B9 `account_id` collision (HIGH):** `SecretManagerOAuthStore._secret_name` uses
  `tenants-{tenant}-{platform}-{key}` and IGNORES `account_id` → all 4 QB subs resolve to ONE secret.
  Fix before QB live: fold `account_id` into the secret name — shared with youtube/instagram, so
  needs a compat shim or one-time secret rename. (MockOAuthStore keys on account_id → hid it in tests.)

**Before tenant #2 (latent multi-tenant, harmless single-tenant today):**
- Flip `register_tenant_session_events(strict=True)` (core/tenant.py); migrate tenant routes to
  `require_role_db`; add `(tenant_id, branch)` referential integrity + branch validation in
  `create_config`.

**Jon decisions:**
- Pay for Cloudflare plan? → flip `var.cloudflare_rate_limiting_enabled=true` to enable WAF rate limits.
- Orphan `web/src/pages/Estimator.tsx` + `Quotes.tsx` — rendered on tab keys no nav sets (App.tsx
  560/569), invisible to users → delete or wire.
- Remaining UX (non-blocking): dup add-customer UIs (Customers.tsx vs Quoting inline), dense
  overhead/margin/commission panel + "Per-square (guide)" jargon, MarketingConfig brand-asset previews.
- Terraform state is local (git-ignored) — migrate to GCS backend before a 2nd operator.

## OPERATE
- Deploy API+jobs: `bash scripts/deploy.sh` (needs CLEAN tree; tags image w/ git SHA).
- Deploy SPA: `cd web && npm run build && npx --no-install firebase deploy --only hosting:app
  --project video-archival-and-content-gen` (updates app.perkinsroofing.net).
- Drift: `bash scripts/drift_check.sh` (self-injects CF token). terraform ops need
  `export TF_VAR_cloudflare_api_token="$(gcloud secrets versions access latest --secret=cloudflare-api-token)"`.
- Prod smoke: `.venv/bin/python scripts/prod_smoke.py` (mints transient admin token, hits prod).
- Prod DB: `/tmp/cloud-sql-proxy --port 5432 video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg &`

## KEY GOTCHAS LEARNED
- Relaxing a Pydantic `Literal` at a trust boundary REMOVES validation → engine `KeyError` becomes a
  500. Restore explicit validation.
- CF `drift_check`/terraform need the real token injected or the provider errors on the placeholder
  and masks ALL drift as a creds error.
- v4→v5 CF migration on live DNS: `state rm` old-type entries (forget, not destroy) + `import` blocks
  → verify a zero-change plan BEFORE apply (imports/removed change nothing until apply, so it's safe
  to build+plan+verify).
- Local models (gpt-oss/qwen) are useful but produce false positives — always verify their claims.
- Never `pkill -f <pattern>` that matches your own shell (self-SIGTERM).

---
_Archive directive (standing): on the next continuation, move the OLDEST top-level `CONTINUATION-*.md`
into `docs/continuations/`, keep only the latest 3 at top level, fix inbound links, and refresh the
README "most recent" pointer. Done this session: archived `CONTINUATION-2026-07-17.md`._
