# Ez-Bids — Technical Requirements Document

**STATUS: DRAFT — derived from consensus-approved plan; pending council + Jon validation.**
Derived from: `ralplan-ezbids-multitenant-DRAFT.md` (Planner→Architect SOUND-WITH-CHANGES→Critic APPROVE, all 7 changes applied) and `docs/superpowers/specs/2026-07-10-ezbids-multitenant-brief.md`.

---

## 1. Architecture Overview

### 1.1 Topology

```
ezbids.degenito.ai          app.{tenantDomain}          quote.{tenantDomain}
  (Firebase Hosting)          (Firebase Hosting)            (Firebase Hosting)
        |                           |                               |
        +------------- shared trusted-admin Vite bundle -----------+
                              (Option A / 1.5-build)               |
                                                          separate Vite build
                                                          (trust boundary, W4)
                                         |
                         Single Cloud Run API (shared, all tenants)
                                         |
                      RLS-enforced PostgreSQL (shared, tenant-scoped GUC)
                                         |
                              per-tenant GCS prefixes
                              per-tenant GCIP tenants
                              per-tenant Resend identities
```

### 1.2 Key Architectural Decisions (ADR-001)

- **Single shared Cloud Run API** serves all tenants. Data isolation = strict RLS (every table `SET app.current_tenant_id` GUC before any data read/write) + per-tenant GCS prefixes + per-tenant GCIP tenants. No per-tenant infrastructure. (T-2 resolved)
- **"1.5-build" SPA posture (D-4):** platform-admin and tenant back office share one Vite build artifact, distinguished at runtime by `window.location.host`. The untrusted `quote.{d}` customer portal is a **separate Vite build on its own Firebase Hosting site** from v1 — this is a trust-boundary decision, not a bundle-size optimization. The portal ships zero admin or impersonation code.
- **DB-backed runtime configuration:** all per-tenant and platform config that varies at request time (CORS origins, email identity, SSO config, brand tokens) lives in Postgres, read at request time. No env-var redeploys per tenant. The two configs with different ownership models:
  - `cors_origins` table — app-owned, no TF attribute, runtime writes are zero-drift (W0).
  - GCIP `authorized_domains` — TF-managed singleton attribute; single fully-runtime owner: written via Identity Platform admin API at domain onboarding, with `ignore_changes = [authorized_domains]` on the TF resource and a git-tracked audit reconciler (never writes the field). (W2 / pre-mortem #2)
- **Perkins (tenant 1) grandfathered** on the project-level GCIP pool. `_resolve_tenant` default — no `firebase.tenant` claim → tenant 1 — is preserved unchanged. (D-3)
- **Rate limiting at the Cloud Run origin** (W7): per-IP + per-token middleware, `platform_config`-backed. Cloudflare rules apply only to our zones (degenito.ai). (D-5 / T-3 resolved)

### 1.3 Existing Inventory Reused (Verified 2026-07-10)

| Component | File / Location | Reuse in Ez-Bids |
|---|---|---|
| Tenancy core | `core/tenant.py`, `get_db_session`, `PlatformSessionLocal`, `for_each_tenant` | All new routes use `get_db_session`; no new session patterns |
| Identity + authz | `api/auth.py:51` (`_resolve_tenant`), `:92` (`_apply_impersonation`), `:352` (`require_internal_tenants`), `core/authz.py:45` (platform_admin actions) | Grandfathering path unchanged; platform_admin actions already declared |
| Token-scoped session | `api/routes/proposals.py:93` (`_token_scoped_session`) | Extended for portal magic-link (W4); the RLS-token seam is already built + tested by migration 0022 policy |
| Provisioning + offboard | `core/provision.py` (9-step + rollback + SSO helpers), `core/offboard.py` | Called from signup approval (W6); SSO helper routes wired in W1/W6 |
| GCIP adapter | `adapters/gcip.py` (`create_gcip_tenant`, `delete_gcip_tenant`, `add_sso_provider`) | Already built + tested; W1 activates the flag, wires admin routes, validates end-to-end |
| Per-tenant settings | `Tenant.settings` JSONB column (`app/models.py:44`), read via `core/tenant_settings.py` | Extended with sub-keys for domain, email, brand (not a separate table) |
| Email wrapper + Resend adapter | `core/email_template.py:12` (`wrap_email`), `adapters/resend.py:12` (from_name/from_email) | Per-tenant brand tokens fed from `Tenant.settings.brand`; per-tenant from_email once domain verified (W3) |
| Metering | `core/metering.py` (ContextVar counters, reset/add/flush) | All new job/route paths emit per-tenant counters |
| Proposal accept flow | `api/routes/proposals.py:990` (GET), `:1062` (accept); RLS accept-token policy migration 0022 | Reused directly in W4 portal; magic-link is a new seam alongside it |

---

## 2. Wave Breakdown (W0–W7)

All waves are gated by R1–R5: `pytest --cov=core --cov-fail-under=97` + at least one behavioral validation script; `ruff check core adapters api jobs`; architect + critic deep review with no unaddressed HIGH findings; all infra in Terraform/Ansible applied from git; `scripts/drift_check.sh` clean. Migrations are additive `.sql` in `infra/migrations/` starting at **0026**.

### W0 — Foundation: DB-backed CORS + single-tenant env cleanup + brand rename

Goal: make platform configuration runtime-driven so new tenants never require a Cloud Run redeploy.

**Scope:**
- Move `CORS_ORIGINS` from `app/config.py:47` (env tuple) to a new `cors_origins` table, read at request time by a custom dynamic CORS middleware replacing the existing `CORSMiddleware` in `api/app.py:68`. (`CORSMiddleware` reads origins once at init — a custom middleware is required.)
- Per-tenant `allowed_origins` are derived from tenant domains (added to `cors_origins` automatically at domain onboarding in W2). The table is app-owned with no TF resource attribute — runtime writes cause zero drift.
- Retire single-tenant env leftovers (T-4): `WP_URL`, `YT_OWNER_CHANNEL_ID`, `WORKSPACE_ADMIN_SUBJECT` move from `scripts/deploy.sh:32-33` and `api/routes/proposals.py:932` to `Tenant.settings.integrations`.
- Establish Ez-Bids as the platform brand of record (T-5): add platform-brand constants distinct from tenant brand.

**Files:** `app/config.py`, `api/app.py` (dynamic CORS middleware), `scripts/deploy.sh`, `core/tenant_settings.py`, `app/models.py`, `adapters/resend.py` (reply_to from tenant settings, not env), `infra/` (remove retired env vars from Cloud Run env).

**Migration:** 0026 — `cors_origins(origin TEXT, tenant_id UUID REFERENCES tenants(id) NULLABLE, created_at TIMESTAMPTZ)`. `tenant_id NULL` = platform-wide origin; non-null = tenant-scoped origin added at domain onboarding.

**Tests:**
- Unit: dynamic CORS middleware allows registered origins, denies unregistered ones, handles null `tenant_id` rows as platform-wide.
- Behavioral: `scripts/validate_cors_dynamic.py` — hits the running middleware with allowed and disallowed `Origin` headers, asserts 200/403 respectively.
- Grep-clean check: `WP_URL`, `YT_OWNER_CHANNEL_ID`, `WORKSPACE_ADMIN_SUBJECT` absent from `scripts/deploy.sh` and `infra/`.

**Exit gates:** R1 core coverage holds; retired env vars gone from deploy.sh AND infra; drift 0.
**Effort:** M (~1.5 days).

---

### W1 — Per-tenant SSO: activate flag + wire admin routes + validate

Goal: activate GCIP multi-tenancy and prove the end-to-end `create→map→resolve→delete` round-trip against a real GCIP tenant id. The GCIP adapter (`adapters/gcip.py`) is already built and tested — W1 does not re-implement it.

**Scope:**
- Activate `allow_tenants = true` on `google_identity_platform_config.multi_tenant` in `infra/main.tf`. The current tfstate has it `false`; `ignore_changes = [multi_tenant]` must be adjusted so the flip actually applies (not ignored). Stage on pre-prod substrate before prod (§5.3 of plan).
- Wire the currently-unwired HTTP admin routes that call `provision.add_sso_provider` (per-tenant IdP: Google / email+password / Microsoft OIDC; SAML = seam only). **Note:** these SSO admin routes may be merged into W6 (where the admin UI backing them lives); if merged, W1 reduces to the `allow_tenants` flip + real-tenant validation only.
- Prove end-to-end: `create_gcip_tenant → tenant_gcip_map insert → _resolve_tenant with firebase.tenant claim → delete` round-trip against a real GCIP tenant id.

**Files:** `infra/main.tf` (multi_tenant block + `ignore_changes` adjustment); `api/routes/` SSO admin routes (wire `provision.add_sso_provider` — may land in W6).

**Migration:** none (mapping table `tenant_gcip_map` exists).

**IaC:** `google_identity_platform_config.multi_tenant.allow_tenants = true`. Per-tenant GCIP tenants are created at runtime by provisioning (not TF — they are tenant data, like GCS prefixes). This is an explicit TF-boundary exception: runtime-created tenant resources are data, not infrastructure.

**Tests:**
- Behavioral: `scripts/validate_gcip_tenant.py` — create→map→resolve→delete against a real GCIP tenant id.
- Unit: any new IdP-config validation on the wired routes.
- RLS (new): a token minted for GCIP tenant B cannot resolve to tenant A (cross-tenant identity denial, `tests/tenancy/`).
- Regression: no-firebase.tenant token still resolves to tenant 1 (grandfathering); Perkins login unaffected.

**Exit gates:** `allow_tenants=true` verified on pre-prod substrate before prod; Perkins smoke passes; grandfathering path confirmed.
**Effort:** S–M (~1–1.5 days).

---

### W2 — Domain lifecycle automation

Goal: automate the full `requested→dns_pending→cert_pending→live|failed` domain lifecycle for both `app.{d}` and `quote.{d}` with no human console step. The Firebase custom-domain REST path (`customDomains` API via ADC) is proven — W2 builds on it.

**Scope:**
- On tenant domain entry: call `sites.create` (Firebase Hosting REST) for `app.{d}` and `quote.{d}`, then add the custom domain via the `customDomains` REST path.
- Surface required CNAME + TXT records in the onboarding UI.
- Poll cert state; drive the domain state machine (see DDD §3).
- Write verified domain into GCIP `authorized_domains` via the Identity Platform admin API.
- Automatically add `app.{d}` and `quote.{d}` to the `cors_origins` table (W0) on domain reaching `live`.

**New files:** `adapters/firebase_hosting.py` (REST client: `sites.create` + `customDomains`), `core/domain_onboarding.py` (resumable state machine).

**State stored in:** `Tenant.settings.domains` (JSONB) for lightweight state, with the `tenant_domains` table (migration 0027) as the pollable, indexable source of truth for domain lifecycle.

**Migration:** 0027 — `tenant_domains(id UUID PK, tenant_id UUID FK, host TEXT, surface TEXT CHECK IN ('app','quote'), state TEXT CHECK IN ('requested','dns_pending','cert_pending','live','failed'), cname_target TEXT, txt_record TEXT, cert_state TEXT, last_polled_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`. RLS-forced on `tenant_id`.

**IaC:** `google_identity_platform_config.auth` singleton — set `ignore_changes = [authorized_domains]`. `authorized_domains` is written **fully at runtime** by the Identity Platform admin API. A git-tracked reconciler script audits parity and alerts on divergence but never writes the TF attribute. This is the single-owner rule: a field cannot have two owners (TF and runtime) without permanent R4 drift.

**Tests:**
- Unit: domain state machine — all transitions including failure/timeout/resume paths.
- Behavioral: `scripts/validate_domain_onboarding.py` — drives all state transitions with a faked Firebase Hosting client, including timeout and failure branches.
- Integration: full onboarding of a throwaway domain in dev reaches `live` state end-to-end.
- Verify: `authorized_domains` runtime write confirmed in dev; drift 0 with `ignore_changes` in place.

**Exit gates:** throwaway domain reaches `live` in dev; GCIP `authorized_domains` write verified; drift 0.
**Effort:** L (~3 days).

---

### W3 — Per-tenant email identity

Goal: each tenant sends email from their own domain (`user@{tenantdomain}`), verified via Resend's domain API.

**Scope:**
- Create Resend domain identity per tenant domain; surface DKIM/SPF/return-path records in onboarding UI; poll verification state.
- Per-tenant `EMAIL_HTML_HEADER` + brand tokens move from `platform_config` to `Tenant.settings.brand`.
- Sender address = `user@{tenantdomain}` once verified; fallback = `tenantslug@ezbids-mail.{ourdomain}` until then.
- `wrap_email` already accepts brand args — feed them from `Tenant.settings.brand`.
- `api/routes/proposals.py` `_send_accept_link_email` reply_to from tenant settings (not env).

**Files:** `adapters/resend.py` (domain-management calls + per-call from_email/header override), new `core/email_identity.py` (verification state machine), `api/routes/email.py`, `api/routes/proposals.py`.

**Migration:** email verification state stored in `Tenant.settings.email` JSONB or as columns on the `tenant_domains` table (W2) — `email_verified`, DKIM state, Resend domain id.

**Tests:**
- Behavioral: `scripts/validate_email_identity.py` — faked Resend client, verification state machine transitions + fallback sender selection.
- Unit: `wrap_email` fed tenant brand tokens produces correct headers; fallback sender logic.
- RLS (new): tenant A's brand header never renders in tenant B's email — explicit cross-tenant denial test.

**Effort:** M (~2 days). Depends on W2 (shares domain onboarding UI + polling infra).

---

### W4 — Customer portal (quote.{d}) — separate build, own trust boundary

Goal: ship the untrusted customer-portal surface as a standalone Vite artifact on its own Firebase Hosting site, with zero admin or impersonation code present in the bundle.

**Scope:**
- New Vite build under `web/` with a separate entry point and output directory; registered as its own Firebase Hosting site in `firebase.json`.
- Auth: magic-link (issue/redeem, `portal_magic_links` table) as the portal front door; the existing long-lived signed accept-token remains the deep-link into a specific proposal. No password accounts (D-6).
- Feature set: proposal/quote timeline (reuse `/p/{token}` + `proposal_events`), doc viewing, e-sign (exists), revision requests (exists).
- Backend: reuses `_token_scoped_session` (`api/routes/proposals.py:93`) — the RLS-token seam is already built and covered by the 0022 accept-token RLS policy. Magic-link redeem creates a session via the same pattern.
- CI build-level assertion: the `quote.{d}` artifact contains no admin or impersonation modules (bundle-content check).

**Files:** new portal Vite build under `web/` (separate entry/output), new `api/routes/portal.py` (magic-link issue/redeem), `firebase.json` (portal site config).

**Migration:** 0028 — `portal_magic_links(id UUID PK, token TEXT UNIQUE, tenant_id UUID FK, customer_email TEXT, expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ NULLABLE)`. RLS-forced on `tenant_id`.

**Tests:**
- Behavioral: `scripts/validate_portal_magiclink.py` — issue→redeem→expire flow; attempt reuse of used token fails.
- RLS (new): a magic-link token for tenant A's customer cannot read tenant B's proposals — mirrors the 0022 accept-token policy test in `tests/tenancy/`.
- Build assertion: CI confirms portal bundle contains no admin/impersonation module names.

**Effort:** L (~3 days). Depends on W2 (quote.{d} domain must resolve). Depends on W6 Firebase-sites wiring for deploy, but not on the admin-bundle host-router.

---

### W5 — Billing placeholders (Stripe seams)

Goal: wire entitlement checkpoints and seat-count math without live Stripe calls. Billing code is security-critical and stays on Claude per the token-economy policy.

**Scope:**
- `core/billing.py`: entitlement math (`$49 × active_enabled_users`), plan/status logic, "active user" = enabled login (D-7).
- `adapters/stripe_stub.py`: no live Stripe calls; mimics the Stripe Checkout + webhook interface for test assertions.
- `/billing/webhook` route: signature-verify seam (validates `Stripe-Signature` header), no-op handler body.
- `plans` and `subscriptions` tables.
- Entitlement checks wired: user-invite blocked when tenant `suspended`; tenant status gates sign-in (already in `_resolve_tenant` tenant status check — wire the billing-driven status update).
- Placeholder billing panel in W6 admin UI.

**Files:** new `core/billing.py`, `adapters/stripe_stub.py`, `api/routes/billing.py`, `app/models.py` (Plan, Subscription models).

**Migration:** 0029 — `plans(id UUID PK, name TEXT, price_cents INT, per_seat BOOL)` and `subscriptions(id UUID PK, tenant_id UUID FK UNIQUE, plan_id UUID FK, status TEXT CHECK IN ('active','past_due','suspended'), seat_count INT, stripe_subscription_id TEXT NULLABLE, updated_at TIMESTAMPTZ)`.

**Tests:**
- Unit: entitlement math for 0, 1, N enabled users; active-user definition; suspend-gate on user-invite.
- Behavioral: `scripts/validate_billing_seams.py` — webhook signature-verify path (valid + tampered sig); suspend-gates-signin flow.
- Note: billing tests stay on Claude (security-critical per token-economy policy).

**Effort:** M (~2 days). Can start any time after W0.

---

### W6 — Platform-admin UI + host-routing + tenant signup + SSO admin routes

Goal: deliver the two trusted admin surfaces (platform-admin + tenant back office) as a host-routed shared bundle, the tenant signup queue, and the SSO admin route wiring from W1.

**Scope:**
- (a) **Host-based surface routing** in the shared admin bundle: `window.location.host` → surface (`platform-admin` | `tenant-app`). The customer portal is a separate site (W4), not a branch of this router.
- (b) **Platform-admin UI**: tenant list + provisioning status, domain lifecycle health, impersonation trigger, billing panel placeholder (W5 seam), platform config management.
- (c) **Tenant signup flow** on `ezbids.degenito.ai`: public page → collect company/admin/plan → `signup_requests` table → platform admin approves → `core/provision.py` → onboarding checklist.
- (d) **Onboarding checklist UI** in tenant back office: domain (W2), SSO (W1), email identity (W3), pricing/branding, user management.
- (e) **SSO admin routes**: wire the currently-unwired HTTP endpoints that call `provision.add_sso_provider` (merged here from W1 since the admin UI backing them lives in this wave).
- (f) Ez-Bids platform branding (T-5): platform-brand constants in the shared bundle distinct from tenant brand.

**Files:** `web/src/` (host router, admin pages, signup page, onboarding checklist), `api/routes/signup.py` (queue), `api/routes/admin_platform.py` (UI-backing endpoints), `api/routes/` SSO admin routes, `firebase.json` (admin sites → shared bundle; portal site → W4 artifact).

**Migration:** 0030 — `signup_requests(id UUID PK, company TEXT, admin_email TEXT, plan TEXT, status TEXT CHECK IN ('pending','approved','rejected'), requested_at TIMESTAMPTZ, reviewed_by UUID NULLABLE, reviewed_at TIMESTAMPTZ NULLABLE)`. Platform-scoped table (no RLS tenant-filter; visible only to platform admins via `require_internal_tenants` + platform_admin action check).

**IaC:** Firebase Hosting sites for `ezbids.degenito.ai` (platform) + per-tenant sites (registered at runtime by W2 provisioning); `infra/` DNS for degenito.ai zone. **BLOCKER: requires `CLOUDFLARE_DEGENITO_API_KEY`** (degenito.ai zone, DNS:Edit — see §8 of PRD).

**Tests:**
- Behavioral: `scripts/validate_signup_provision.py` — signup→admin-approve→provision e2e with faked GCIP.
- Unit: host-routing (host string → surface enum); platform-admin authz on new endpoints.
- RLS: `signup_requests` visible only to platform admin role (not to tenant sessions).

**Effort:** XL (~5 days) — largest wave. Consider splitting W6a (routing + admin UI) / W6b (signup queue + SSO routes) if scope is too large to gate atomically.

---

### W7 — Edge / rate-limit generalization + hardening

Goal: generalize rate limiting to work for all tenant hostnames, not just `app.perkinsroofing.net`.

**Scope:**
- New `api/middleware/ratelimit.py`: origin-side per-IP + per-token rate limiting on `/p/*` and portal routes (D-5). `platform_config`-backed counter (consistent with `core/ratelimit.py` pattern).
- `infra/cloudflare.tf`: generalize WAF/rate-limit rules to cover our degenito.ai zone; tenant-owned zones stay tenant-owned.
- "Proxy through our Cloudflare" documented as an optional premium onboarding path; not required in v1.

**Files:** new `api/middleware/ratelimit.py`, `infra/cloudflare.tf`.

**Tests:**
- Behavioral: `scripts/validate_ratelimit.py` — trigger rate-limit trip on `/p/{token}/accept`; verify 429 after threshold.

**Effort:** M (~2 days).

---

### Wave Sequencing

```
W0 → W1 → W2 → W3 (parallel with W4 after W2)
                  ↘
                   W4
W0 → W5 (any time after W0)
W1 + W2 + W4 → W6 → W7
```

W1's SSO admin-route wiring may be pulled forward into W6; if so, W1 = `allow_tenants` flip + real-tenant validation only.

---

## 3. Migration List

All migrations are additive `.sql` in `infra/migrations/`. Next available number: **0026**.

| # | Wave | Description |
|---|---|---|
| 0026 | W0 | `cors_origins(origin, tenant_id NULLABLE, created_at)` |
| 0027 | W2 | `tenant_domains(id, tenant_id, host, surface, state, cname_target, txt_record, cert_state, last_polled_at, updated_at)` |
| 0028 | W4 | `portal_magic_links(id, token, tenant_id, customer_email, expires_at, used_at)` |
| 0029 | W5 | `plans(id, name, price_cents, per_seat)` + `subscriptions(id, tenant_id, plan_id, status, seat_count, stripe_subscription_id, updated_at)` |
| 0030 | W6 | `signup_requests(id, company, admin_email, plan, status, requested_at, reviewed_by, reviewed_at)` |

---

## 4. Behavioral Validation Scripts (R1 I/O Clause)

Adapters and API routes are coverage-omitted under R1, so each must have at least one behavioral validation script:

| Script | Wave | Covers |
|---|---|---|
| `scripts/validate_cors_dynamic.py` | W0 | Dynamic CORS middleware allow/deny by registered origin |
| `scripts/validate_gcip_tenant.py` | W1 | GCIP create→map→resolve→delete round-trip (real GCIP tenant id) |
| `scripts/validate_domain_onboarding.py` | W2 | Domain state machine all transitions incl. failure/timeout (faked Hosting client) |
| `scripts/validate_email_identity.py` | W3 | Resend domain identity state machine + fallback sender (faked Resend) |
| `scripts/validate_portal_magiclink.py` | W4 | Magic-link issue→redeem→expire; token reuse blocked |
| `scripts/validate_billing_seams.py` | W5 | Webhook signature-verify + suspend-gates-signin |
| `scripts/validate_signup_provision.py` | W6 | Signup→approve→provision e2e (faked GCIP) |
| `scripts/validate_ratelimit.py` | W7 | Rate-limit trip on `/p/{token}/accept` |

---

## 5. RLS / Isolation Requirements (R1 Behavioral Clause)

Every wave touching tenant data must add at least one cross-tenant denial test to `tests/tenancy/`. The `assert_rls_role_hardened` exit-gate verifies tests run as the non-superuser `NOBYPASSRLS` role `app_rls_test`.

| Wave | New RLS test |
|---|---|
| W1 | GCIP tenant B token cannot resolve to tenant A |
| W2 | `tenant_domains` row for tenant A not readable in tenant B session |
| W3 | Tenant A brand header never renders in tenant B email |
| W4 | Magic-link token for tenant A customer cannot read tenant B proposals (mirrors 0022 accept-token policy test) |
| W5 | `subscriptions` row for tenant A not readable in tenant B session |
| W6 | `signup_requests` table not readable in any tenant session (platform-admin only) |

---

## 6. Infra-as-Code Compliance (R3–R5)

- All Cloud Run env vars, Firebase Hosting site configs, GCIP config (except `authorized_domains` — see §1.2), Cloudflare DNS rules in Terraform under `infra/`.
- `authorized_domains` exception: single runtime owner (Identity Platform admin API), `ignore_changes = [authorized_domains]` in TF, git-tracked reconciler audits parity. This is the only documented TF-boundary exception alongside runtime-created GCIP tenants (tenant data, not infra).
- Per-tenant GCIP tenants and GCS prefixes are created at runtime by `core/provision.py` — explicit TF-boundary exception (runtime tenant data). Documented in W1 and W2 wave notes.
- `scripts/drift_check.sh` must show `terraform plan` clean + `ansible --check` changed=0 at every wave exit gate.
- Retired env vars (`WP_URL`, `YT_OWNER_CHANNEL_ID`, `WORKSPACE_ADMIN_SUBJECT`) removed from both `scripts/deploy.sh` and `infra/` Cloud Run env in W0.

---

## 7. Security Requirements

- Cross-tenant data leakage is a CRITICAL failure (pre-mortem #1). Every new path that touches tenant data must resolve tenant via a token/host before any data read, then immediately stamp a tenant-scoped session. No tenant data on a platform-scoped session.
- SPA trust-boundary split (pre-mortem #4): the `quote.{d}` artifact must contain zero admin or impersonation modules. Enforced by a CI build-content assertion (bundle-content check) in addition to the separate-build architecture.
- `portal_magic_links` tokens: short-lived (TTL to be defined at implementation; recommend ≤15 minutes), single-use (mark `used_at` on redeem), RLS-forced.
- Billing webhook route: signature verification must be the first operation before any processing. Test both valid and tampered signatures. Billing code stays on Claude (security-critical).
- Perkins smoke regression check at every wave exit gate: no-firebase.tenant token still resolves to tenant 1; Perkins login unaffected.
- `allow_tenants=true` flip must be staged on a pre-prod substrate before production. The W1 exit gate is not satisfied by a prod-only flip unless explicitly documented as a risk acceptance with rollback plan.
