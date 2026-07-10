# Ez-Bids — Technical Requirements Document

**STATUS: SYNCED TO COUNCIL-REVISED PLAN — 2026-07-10.**
Derived from: `ralplan-ezbids-multitenant-DRAFT.md` (council-revised, APPROVED) and `docs/superpowers/specs/ezbids/COUNCIL-REVIEW.md` (Grok-4 + GPT-5, all 10 findings absorbed). All decisions below are final; do not relitigate.

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
- **Perkins (tenant 1) grandfathered** on the project-level GCIP pool. However, `_resolve_tenant`'s "no `firebase.tenant` claim → tenant 1" default is **replaced** by an explicit internal tenant-key binding at session establishment (J-2 / council #1). A missing claim FAILS CLOSED — it never infers a tenant. Grandfathering is an explicit mapping, not an inference-from-absence. (D-3 as revised)
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
| Email wrapper + Resend adapter | `core/email_template.py:12` (`wrap_email`), `adapters/resend.py:12` (from_name/from_email) | Per-tenant brand tokens (display name, reply-to) fed from `Tenant.settings.brand`; sender address is always the platform-controlled domain in v1 (J-1) |
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
- Unit: dynamic CORS middleware allows registered origins (exact-match only — a look-alike/suffix/subdomain variant is denied); denies unregistered origins; handles null `tenant_id` rows as platform-wide; emits `Vary: Origin` on every response (both allow and deny); denies a valid origin for tenant A when the request host belongs to tenant B (cross-tenant origin/host mismatch).
- Behavioral: `scripts/validate_cors_dynamic.py` — hits the running middleware with allowed origins, disallowed origins, look-alike origins, cross-tenant origin/host mismatches; asserts correct response codes; asserts `Vary: Origin` present on all responses; asserts **preflight (OPTIONS) allow-list exactly matches actual-request allow-list** (no "permissive preflight, strict actual" gap).
- Grep-clean check: `WP_URL`, `YT_OWNER_CHANNEL_ID`, `WORKSPACE_ADMIN_SUBJECT` absent from `scripts/deploy.sh` and `infra/`.

**Exit gates:** R1 core coverage holds; retired env vars gone from deploy.sh AND infra; drift 0; CORS exact-match + `Vary: Origin` + preflight-parity + cross-tenant-mismatch tests all green.
**Effort:** M (~1.5 days).

---

### W1 — Per-tenant SSO: activate flag + wire admin routes + validate

Goal: activate GCIP multi-tenancy and prove the end-to-end `create→map→resolve→delete` round-trip against a real GCIP tenant id. The GCIP adapter (`adapters/gcip.py`) is already built and tested — W1 does not re-implement it.

**Scope:**
- Activate `allow_tenants = true` on `google_identity_platform_config.multi_tenant` in `infra/main.tf`. The current tfstate has it `false`; `ignore_changes = [multi_tenant]` must be adjusted so the flip actually applies (not ignored). Stage on pre-prod substrate before prod (see §7a below).
- **J-2 / council #1 — Explicit tenant-1 binding (OWNED BY W1):** Replace `_resolve_tenant`'s "no `firebase.tenant` claim → tenant 1" default with an explicit internal tenant-key binding at session establishment. Invariant: every authed request resolves to a tenant where token claim, host, and mapping AGREE. A missing or ambiguous claim FAILS CLOSED — it never infers a tenant. Perkins (tenant 1) resolves ONLY via its explicit internal mapping key. This closes the silent-default-to-Perkins hazard in jobs, support tools, and future code.
- Wire the currently-unwired HTTP admin routes that call `provision.add_sso_provider` (per-tenant IdP: Google / email+password / Microsoft OIDC; SAML = seam only). **Note:** these SSO admin routes may be merged into W6 (where the admin UI backing them lives); if merged, W1 reduces to the `allow_tenants` flip + explicit-binding + real-tenant validation only.
- Prove end-to-end: `create_gcip_tenant → tenant_gcip_map insert → _resolve_tenant with firebase.tenant claim → delete` round-trip against a real GCIP tenant id.
- **Council #10 — Non-request context isolation (OWNED BY W1):** Audit and convert cron jobs, background workers, CLI/support tooling, and data exports that touch tenant data to use an explicit tenant-scoped session (same discipline as request paths). A representative non-request path without an explicit session must RAISE under `strict=True`. `for_each_tenant` / explicit binding is the single session-establishment discipline for all execution contexts.

**Files:** `infra/main.tf` (multi_tenant block + `ignore_changes` adjustment); `api/auth.py` (`_resolve_tenant` — explicit binding replaces claim-absence inference); `api/routes/` SSO admin routes (wire `provision.add_sso_provider` — may land in W6); cron/worker entry points (explicit session binding).

**Migration:** none (mapping table `tenant_gcip_map` exists).

**IaC:** `google_identity_platform_config.multi_tenant.allow_tenants = true`. Per-tenant GCIP tenants are created at runtime by provisioning (not TF — they are tenant data, like GCS prefixes). This is an explicit TF-boundary exception: runtime-created tenant resources are data, not infrastructure.

**Tests:**
- Behavioral: `scripts/validate_gcip_tenant.py` — create→map→resolve→delete against a real GCIP tenant id.
- Unit: any new IdP-config validation on the wired routes.
- RLS (new): a token minted for GCIP tenant B cannot resolve to tenant A (cross-tenant identity denial, `tests/tenancy/`).
- **Explicit-binding tests (J-2 / council #1):** (i) a request with a missing `firebase.tenant` claim FAILS CLOSED (does NOT resolve to tenant 1); (ii) tenant 1 resolves ONLY via its explicit internal mapping key; (iii) a request where token/host/mapping disagree fails closed; (iv) Perkins login on `app.perkinsroofing.net` unaffected and resolves via explicit key — NOT via claim absence.
- **Non-request context tests (council #10):** a cron/CLI/worker path without an explicit tenant session raises under `strict=True`; a per-tenant batch path using `for_each_tenant` correctly scopes each iteration.
- Regression: the old "no-firebase.tenant → tenant 1 still passes" test is RETIRED and INVERTED — that path must now fail closed.

**Exit gates:** `allow_tenants=true` verified on pre-prod substrate before prod (§7a); Perkins smoke passes AND Perkins resolves via explicit key; missing-claim→fail-closed test green.
**Effort:** S–M (~1–1.5 days).

---

### W2 — Domain lifecycle automation

Goal: automate the full `requested→dns_pending→cert_pending→live|failed` domain lifecycle for both `app.{d}` and `quote.{d}` with no human console step. The Firebase custom-domain REST path (`customDomains` API via ADC) is proven — W2 builds on it.

**Scope:**
- On tenant domain entry: **proof-of-control gate FIRST (council #6)** — a DNS TXT challenge is issued and must be verified before the domain is trusted for auth (`authorized_domains`) or email (W3). The state machine adds a `control_pending`/`control_verified` stage before any auth/email trust.
- Once proof-of-control is verified: call `sites.create` (Firebase Hosting REST) for `app.{d}` and `quote.{d}`, then add the custom domain via the `customDomains` REST path.
- Surface required CNAME + TXT records in the onboarding UI.
- Poll cert state; drive the domain state machine (see DDD §3).
- Write verified domain into GCIP `authorized_domains` via the Identity Platform admin API.
- Automatically add `app.{d}` and `quote.{d}` to the `cors_origins` table (W0) on domain reaching `live`.
- **Council #6 additional scope:**
  - **Collision / squatting policy:** registrable-domain ownership is checked; a conflicting apex/subdomain claim by a different tenant is blocked and routed to manual moderation (ties to W6 namespace reservation).
  - **Dangling-DNS / subdomain-takeover detection:** periodic re-verification that the CNAME still points at our origin; a domain whose DNS drifts away is auto-quarantined (removed from `authorized_domains` + CORS) to prevent takeover.
  - **Deprovisioning on churn:** `core/offboard.py` removes the domain from Hosting sites, `authorized_domains`, CORS, and Resend (W3) on tenant offboarding; a released domain cannot auth as the departed tenant.
- **Council #3 — `authorized_domains` runtime guardrails (OWNED BY W2):** the runtime writer gets: an **append-only journal** (`domain_ownership_log` table) with actor + request-correlation id for every add/remove; a **domain-ownership gate before add** (proof-of-control state must be `verified`); **quota alarms** (alert when domain count or write-rate crosses a threshold); and a **break-glass path** to rapidly remove a suspicious/abusive domain. A reconciler audits `authorized_domains` parity and alarms on divergence but never writes the TF attribute. ADR line: **Terraform is explicitly NOT the source of truth for `authorized_domains`** — the journal is; codified in ADR-001.
- **Council #4 (non-RLS isolation inventory for W2):** `tenant_domains` is RLS-forced on `tenant_id`; the `domain_ownership_log` journal is tenant-scoped and inventoried in the per-wave non-RLS gate. GCS object paths and signed-URL tenant scoping for any W2-introduced objects are enrolled in the §5.2 inventory.

**New files:** `adapters/firebase_hosting.py` (REST client: `sites.create` + `customDomains`), `core/domain_onboarding.py` (resumable state machine with proof-of-control stage).

**State stored in:** `Tenant.settings.domains` (JSONB) for lightweight state, with the `tenant_domains` table (migration 0027) as the pollable, indexable source of truth for domain lifecycle.

**Migration:** 0027 — `tenant_domains(id UUID PK, tenant_id UUID FK, host TEXT, surface TEXT CHECK IN ('app','quote'), state TEXT CHECK IN ('control_pending','control_verified','requested','dns_pending','cert_pending','live','failed'), cname_target TEXT, txt_record TEXT, cert_state TEXT, last_polled_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`. RLS-forced on `tenant_id`. Plus `domain_ownership_log(id UUID PK, host TEXT, action TEXT, actor TEXT, correlation_id TEXT, occurred_at TIMESTAMPTZ)` — append-only journal, tenant-scoped.

**IaC:** `google_identity_platform_config.auth` singleton — set `ignore_changes = [authorized_domains]`. `authorized_domains` is written **fully at runtime** by the Identity Platform admin API. A git-tracked reconciler script audits parity and alerts on divergence but **never writes the TF attribute**. ADR: TF is explicitly NOT the source of truth for `authorized_domains`. This is the single-owner rule: a field cannot have two owners (TF and runtime) without permanent R4 drift.

**Tests:**
- Unit: domain state machine — all transitions including proof-of-control gate, failure/timeout/resume paths.
- Behavioral: `scripts/validate_domain_onboarding.py` — drives all state transitions with a faked Firebase Hosting client, including timeout and failure branches; **proof-of-control gate blocks trust before `control_verified`; collision/squatting claim by a second tenant is rejected; dangling-DNS re-check auto-quarantines a drifted domain; deprovisioning removes domain from `authorized_domains`+CORS+Hosting; `authorized_domains` writes are journaled with actor+correlation and blocked without a verified ownership gate (council #3); break-glass removal path exercised.**
- Integration: full onboarding of a throwaway domain in dev reaches `live` state end-to-end.
- Verify: `authorized_domains` runtime write confirmed in dev; drift 0 with `ignore_changes` in place.
- Non-RLS isolation inventory gate (council #4): `tenant_domains` and `domain_ownership_log` isolation mechanisms documented and negative tests present.

**Exit gates:** throwaway domain reaches `live` in dev; GCIP `authorized_domains` write verified AND journaled; proof-of-control + collision + dangling-DNS + deprovision tests green; drift 0.
**Effort:** L–XL (~3.5–4 days).

---

### W3 — Branded email on a platform-controlled sending domain (J-1)

Goal: deliver per-tenant branded email from a single platform-controlled sending domain. **Per-tenant custom sender domains are a Non-goal in v1** (J-1 / council #9) — see §5 Non-goals.

**Scope:**
- Configure and verify the **one** platform sending domain in Resend (done once, IaC/runbook, not per tenant).
- Per-tenant `EMAIL_HTML_HEADER` + brand tokens move from `platform_config` to `Tenant.settings.brand`.
- Per-send envelope: `from = "{Tenant Display Name} <noreply@ezbids-mail.{ourdomain}>"`, `reply-to = {tenant reply address from Tenant.settings.brand.reply_to}`.
- `wrap_email` already accepts brand args — feed them from `Tenant.settings.brand`.
- `api/routes/proposals.py` `_send_accept_link_email` reply_to from tenant settings (not env).
- **Deferred-scope stub only:** leave a clean seam (`core/email_identity.py` interface) for the future per-tenant-sender-domain wave. Do NOT build Resend per-tenant domain API calls or a DKIM verification state machine in v1.

**Files:** `adapters/resend.py` (per-call `from_name`/`reply_to` override against the fixed platform sender; NO per-tenant domain-management calls in v1), `api/routes/email.py`, `api/routes/proposals.py`, new `core/email_identity.py` (interface stub only).

**Migration:** `Tenant.settings.brand` (JSONB) for header/reply-to; no per-tenant email-domain state table in v1.

**Tests:**
- Behavioral: `scripts/validate_email_identity.py` — faked Resend client, verifies platform-controlled sender + per-tenant branded display name + per-tenant reply-to; verifies no code path sends from a per-tenant sender domain in v1.
- Unit: `wrap_email` fed tenant brand tokens produces correct headers; assert `from` address always uses the platform sending domain.
- RLS (new): tenant A's brand header never renders in tenant B's email — explicit cross-tenant denial test.

**Effort:** S–M (~1–1.5 days). **No longer depends on W2** (J-1 decision: the platform sender domain is domain-independent; W2 domain onboarding is not a prerequisite). Depends on W0 (brand tokens in `Tenant.settings`).

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

**Council #7 — Bearer-token hardening (OWNED BY W4):** magic-links and accept-tokens are bearer credentials. Requirements:
- **Single-use:** redemption marks `used_at`; replay (re-POST of a used token) is rejected.
- **Short TTL:** magic-link ≤15 minutes; accept-token stays long-lived but is scoped tightly.
- **Bound to recipient + tenant + host + proposal:** a token minted for customer X / tenant A / `quote.a.com` / proposal 7 is invalid on any other combination.
- **Email-scanner-safe redemption:** GET on the magic-link performs NO state change (scanners/prefetchers pre-fetch links). Redemption/consumption happens on an explicit POST/interstitial, so a scanner GET cannot burn a single-use token or accept a proposal.
- **Session establishment is separate from proposal acceptance:** landing on the portal establishes a scoped session; accepting a proposal is a distinct, explicitly authenticated action — never a side effect of opening a link.
- **E-sign legal-evidence review:** existing e-sign must be reviewed for: intent capture, identity binding, timestamp, document hash, IP/UA logging — flag gaps for legal before customer-facing acceptance is trusted as binding.

**Migration:** 0028 — `portal_magic_links(id UUID PK, token TEXT UNIQUE, tenant_id UUID FK, customer_email TEXT, host TEXT NOT NULL, proposal_id UUID NULLABLE REFERENCES proposals(id), expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ NULLABLE, consumed_via TEXT)`. RLS-forced on `tenant_id`. `host` and `proposal_id` enforce binding per council #7.

**Tests:**
- Behavioral: `scripts/validate_portal_magiclink.py` — issue→redeem→expire flow; attempt reuse of used token rejected; expired link rejected; **a GET on the link performs no state change** (used_at stays NULL, proposal not accepted); session-establishment and proposal-acceptance are separately authenticated steps.
- **Council #7 binding tests:** a token bound to (customer A, tenant A, host a, proposal 7) rejected when presented with a different recipient/tenant/host/proposal.
- RLS (new): a magic-link token for tenant A's customer cannot read tenant B's proposals — mirrors the 0022 accept-token policy test in `tests/tenancy/`.
- Build assertion: CI confirms portal bundle contains no admin/impersonation module names.

**Effort:** L (~3 days). Depends on W2 (quote.{d} domain must resolve). Depends on W6 Firebase-sites wiring for deploy, but not on the admin-bundle host-router.

---

### W5 — Billing placeholders (Stripe seams)

Goal: wire entitlement checkpoints and seat-count math without live Stripe calls. Billing code is security-critical and stays on Claude per the token-economy policy.

**Scope (council #8 — cutover-proof billing core):** even though v1 makes no live Stripe calls, the data model and control-plane semantics are designed and built now so going live later is a config flip, not a redesign.
- **Canonical immutable billing-event ledger:** an append-only `billing_events` table (event id, type, tenant, payload, received_at, source) is the system of record. Entitlements are *derived* from it, never overwritten in place. No in-place mutation of billing state.
- **Webhook signature-verify + idempotency:** the stub `/billing/webhook` implements real Stripe **signature verification** (against a test secret) and **idempotency keys** (dedupe on Stripe event id), so the live handler is the same code with a real secret. Invalid signatures are rejected before any processing.
- **Entitlement snapshotting:** on each billing event, snapshot the tenant's entitlement state (`entitlement_snapshots` table) so historical state is auditable and a replayed/duplicate event cannot corrupt current entitlement.
- **Grace/dunning semantics:** `past_due` → grace window → `suspended` transitions defined (timers stubbed); what a **suspended tenant's quote portal does** is specified: read-only / accept-blocked with a billing notice, but existing signed proposals remain viewable.
- `core/billing.py`: entitlement math (`$49 × active_enabled_users`), plan/status logic, "active user" = enabled login (D-7).
- `adapters/stripe_stub.py`: no live Stripe calls; mimics the Stripe Checkout + webhook interface for test assertions.
- `plans` and `subscriptions` tables.
- Entitlement checks wired: user-invite blocked when tenant `suspended`; tenant status gates sign-in (already in `_resolve_tenant` tenant status check — wire the billing-driven status update).
- Placeholder billing panel in W6 admin UI.

**Files:** new `core/billing.py`, `adapters/stripe_stub.py`, `api/routes/billing.py`, `app/models.py` (Plan, Subscription, BillingEvent, EntitlementSnapshot models).

**Migration:** 0029 — `plans(id UUID PK, name TEXT, price_cents INT, per_seat BOOL)`; `subscriptions(id UUID PK, tenant_id UUID FK UNIQUE, plan_id UUID FK, status TEXT CHECK IN ('active','past_due','suspended'), seat_count INT, stripe_subscription_id TEXT NULLABLE, updated_at TIMESTAMPTZ)`; **`billing_events(id UUID PK, stripe_event_id TEXT UNIQUE, event_type TEXT, tenant_id UUID FK, payload JSONB, received_at TIMESTAMPTZ, source TEXT)` — append-only, no UPDATE/DELETE permitted**; **`entitlement_snapshots(id UUID PK, tenant_id UUID FK, billing_event_id UUID FK, plan TEXT, status TEXT, seat_count INT, effective_at TIMESTAMPTZ)`**.

**Non-RLS isolation inventory (council #4):** `billing_events` and `entitlement_snapshots` accumulate cross-tenant rows — both are tenant-scoped and RLS-forced, enrolled in the W5 isolation gate.

**Tests:**
- Unit: entitlement math for 0, 1, N enabled users; active-user definition; suspend-gate on user-invite; grace/dunning state transitions (`active→past_due→suspended`).
- Behavioral: `scripts/validate_billing_seams.py` — **webhook signature-verify (valid + tampered sig rejected before any processing); idempotency (duplicate Stripe event id is a no-op); immutable-ledger (no in-place mutation, append-only asserted); entitlement-snapshot on each event; suspend-gates-signin; suspended-portal behavior (read-only, accept-blocked)**.
- Note: billing tests stay on Claude (security-critical per token-economy policy).

**Effort:** M–L (~2.5–3 days). Can start any time after W0.

---

### W6 — Platform-admin UI + host-routing + tenant signup + SSO admin routes

Goal: deliver the two trusted admin surfaces (platform-admin + tenant back office) as a host-routed shared bundle, the tenant signup queue, and the SSO admin route wiring from W1.

**Scope:**
- (a) **Host-based surface routing** in the shared admin bundle: `window.location.host` → surface (`platform-admin` | `tenant-app`). The customer portal is a separate site (W4), not a branch of this router. Host-route allowlists: the router only activates a surface on its allow-listed host; an unexpected host renders nothing privileged.
- (b) **Platform-admin UI**: tenant list + provisioning status, domain lifecycle health, impersonation trigger, billing panel placeholder (W5 seam), platform config management.
- (c) **Tenant signup flow** on `ezbids.degenito.ai`: public page → collect company/admin/plan → `signup_requests` table → platform admin approves → `core/provision.py` → onboarding checklist.
- (d) **Onboarding checklist UI** in tenant back office: domain (W2), SSO (W1), email identity (W3), pricing/branding, user management.
- (e) **SSO admin routes**: wire the currently-unwired HTTP endpoints that call `provision.add_sso_provider` (merged here from W1 since the admin UI backing them lives in this wave).
- (f) Ez-Bids platform branding (T-5): platform-brand constants in the shared bundle distinct from tenant brand.
- **(g) Council #2 — shared admin bundle client-side hardening (OWNED BY W6):** the two trusted surfaces share a *bundle*, not a *trust context*. Required: **distinct GCIP auth audiences/clients per surface** (platform-admin vs tenant-staff get different OAuth client ids/audiences so a token minted for one is not valid for the other); **separate browser-storage keys** (auth state keyed per surface/origin — no shared localStorage/IndexedDB slot); **no shared service worker** across surfaces (a shared SW is a cross-origin credential/cache bridge); **per-surface CSP + `frame-ancestors`** (each origin locks its framing and script sources independently); **host-route allowlists** (unexpected host renders nothing privileged). A browser test proving an admin-surface token is **rejected** on the staff origin (and vice versa) is the gate that proves the boundary is real.
- **(h) Council #5 — signup abuse controls (OWNED BY W6):** the public signup page plus runtime domain/GCIP provisioning is an abuse magnet. Before anything is provisioned: **rate limits** (per-IP + per-email signup throttle); **CAPTCHA/Turnstile** on the signup form; **disposable-email block** (reject throwaway domains for the admin email); **domain moderation / manual-review path** (the D-1 request-access queue is the human gate — no GCIP tenant or domain created before admin approval); **tenant-namespace reservation** (reserve the tenant slug/subdomain at request time, blocklist reserved/abusive names, prevent two signups racing the same namespace).

**Files:** `web/src/` (host router with **per-surface auth config + storage keys + CSP**, admin pages, signup page **with Turnstile**), `api/routes/signup.py` (queue **+ rate limit + disposable-email check + namespace reservation**), `api/routes/admin_platform.py` (UI-backing endpoints), `api/routes/` SSO admin routes, `firebase.json` (admin sites → shared bundle **with distinct per-site headers/CSP + no shared service worker**; portal site → W4 artifact).

**Migration:** 0030 — `signup_requests(id UUID PK, company TEXT, admin_email TEXT, plan TEXT, status TEXT CHECK IN ('pending','approved','rejected'), requested_at TIMESTAMPTZ, reviewed_by UUID NULLABLE, reviewed_at TIMESTAMPTZ NULLABLE)`. Platform-scoped (no RLS tenant-filter; visible only to platform admins via `require_internal_tenants` + `admin_tenants` action check). Plus `reserved_namespaces(slug TEXT PK, tenant_id UUID NULLABLE, reserved_at TIMESTAMPTZ)` — for namespace reservation (council #5).

**IaC:** Firebase Hosting sites for `ezbids.degenito.ai` (platform) + per-tenant sites (registered at runtime by W2 provisioning); `infra/` DNS for degenito.ai zone. **BLOCKER: requires `CLOUDFLARE_DEGENITO_API_KEY`** (degenito.ai zone, DNS:Edit).

**Tests:**
- Behavioral: `scripts/validate_signup_provision.py` — signup→admin-approve→provision e2e with faked GCIP; **signup rate-limit trips; disposable email rejected; namespace reservation blocks a racing duplicate; no GCIP tenant/domain created before approval**.
- Unit: host-routing (host string → surface enum); platform-admin authz on new endpoints.
- **Council #2 browser test:** an admin-surface token is REJECTED on the staff origin and vice-versa (distinct audiences); storage keys don't collide; no shared service worker registered; each surface serves its own CSP.
- RLS: `signup_requests` and `reserved_namespaces` not readable in any tenant session (platform-admin only).

**Effort:** XL (~5–6 days) — largest wave. Consider splitting W6a (routing + admin UI + council #2 hardening) / W6b (signup queue + council #5 abuse controls + SSO routes) if scope is too large to gate atomically.

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
| 0027 | W2 | `tenant_domains(id, tenant_id, host, surface, state [+control_pending/control_verified], cname_target, txt_record, cert_state, last_polled_at, updated_at)` + `domain_ownership_log(id, host, action, actor, correlation_id, occurred_at)` — append-only journal for `authorized_domains` writes (council #3) |
| 0028 | W4 | `portal_magic_links(id, token, tenant_id, customer_email, host, proposal_id, expires_at, used_at, consumed_via)` — `host` + `proposal_id` enforce token binding (council #7) |
| 0029 | W5 | `plans(id, name, price_cents, per_seat)` + `subscriptions(id, tenant_id, plan_id, status, seat_count, stripe_subscription_id, updated_at)` + **`billing_events(id, stripe_event_id UNIQUE, event_type, tenant_id, payload, received_at, source)` — append-only immutable ledger** + **`entitlement_snapshots(id, tenant_id, billing_event_id, plan, status, seat_count, effective_at)`** (council #8) |
| 0030 | W6 | `signup_requests(id, company, admin_email, plan, status, requested_at, reviewed_by, reviewed_at)` + `reserved_namespaces(slug PK, tenant_id NULLABLE, reserved_at)` — namespace reservation (council #5) |

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

- **Cross-tenant data leakage is a CRITICAL failure** (pre-mortem #1). Every new path that touches tenant data must resolve tenant via a token/host before any data read, then immediately stamp a tenant-scoped session. No tenant data on a platform-scoped session. `strict=True` is already prod-verified — an unstamped tenant session RAISES on Postgres (does not silently return empty rows). This is the invariant we never trade against.
- **Explicit tenant-1 binding (J-2 / council #1):** A missing `firebase.tenant` claim FAILS CLOSED — it never infers tenant 1. Every authed request must resolve to a tenant where token, host, and mapping agree. Perkins resolves via explicit internal mapping key only. The old "no-firebase.tenant → tenant 1" path is retired and must now fail closed.
- **CORS hardening (council CORS TOCTOU):** Dynamic CORS middleware must use exact-match only; emit `Vary: Origin` on all responses; enforce tenant/host/origin alignment; preflight allow-list must match actual-request allow-list exactly.
- **SPA trust-boundary split** (pre-mortem #4): the `quote.{d}` artifact must contain zero admin or impersonation modules. Enforced by a CI build-content assertion (bundle-content check) in addition to the separate-build architecture. Per-surface CSP + `frame-ancestors` for each origin.
- **Shared admin bundle is packaging, not a security boundary (council #2):** enforced by distinct GCIP auth audiences per surface, separate browser-storage keys, no shared service worker, per-surface CSP, host-route allowlists, and a browser test proving cross-origin token rejection.
- **`portal_magic_links` tokens (council #7):** single-use (`used_at` marked on redeem; replay rejected), short-TTL (≤15 minutes), bound to recipient + tenant + host + proposal. GET on link performs no state change. Session establishment and proposal acceptance are distinct steps.
- **`authorized_domains` writes (council #3):** append-only journaled, ownership-gated, quota-alarmed, break-glass path. Terraform is NOT the source of truth for this field.
- **Signup abuse controls (council #5):** Turnstile, per-IP/email rate limits, disposable-email block, namespace reservation, human gate before any GCIP/domain creation.
- **Billing webhook route (council #8):** signature verification must be the first operation before any processing. Idempotency (dedupe on Stripe event id) is required. Billing code stays on Claude (security-critical). Immutable billing-event ledger — no in-place mutation.
- **Non-request context sessions (council #10):** cron/workers/CLI/support tooling/exports must use explicit tenant-scoped sessions. An unscoped path over tenant data must raise under `strict=True`.
- Perkins smoke regression check at every wave exit gate: Perkins resolves via explicit mapping key (NOT by claim absence); login unaffected.
- `allow_tenants=true` flip must be staged on a pre-prod substrate before production. The W1 exit gate is not satisfied by a prod-only flip unless explicitly documented as a risk acceptance with rollback plan (see §7a below).

## 7a. Pre-Prod Substrate for the `allow_tenants` Flip (W1)

Before W1 executes, one of the following must be named in the W1 wave notes:

- **Recommended:** a separate pre-prod GCP project carrying a mirror of the Identity Platform config. The `allow_tenants=true` flip + create→map→resolve→delete round-trip on a throwaway GCIP tenant is exercised against real GCIP behavior; a no-firebase.tenant token still resolves to the grandfathered tenant. Perkins's project remains untouched during validation.
- **Alternative (elevated risk, documented):** prod-only verification with Perkins-smoke regression check run immediately before and after, a rehearsed `allow_tenants=false` rollback, and the apply scheduled in a low-traffic window. This is a documented risk acceptance, not a silent prod change.

Whichever path is chosen must be recorded in the W1 wave notes. The W1 exit gate is not satisfied by prod-only verification unless the alternative risk acceptance is explicitly stated.
