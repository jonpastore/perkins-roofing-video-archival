# Ez-Bids — Product Requirements Document

**STATUS: SYNCED TO COUNCIL-REVISED PLAN — 2026-07-10.**
Derived from: `ralplan-ezbids-multitenant-DRAFT.md` (council-revised, APPROVED) and `docs/superpowers/specs/ezbids/COUNCIL-REVIEW.md` (Grok-4 + GPT-5, all 10 findings absorbed). All decisions below are final; do not relitigate.

---

## 1. Vision

Ez-Bids is a multi-tenant SaaS platform for roofing and exterior contractors, built on the existing Perkins v2 GCP stack. It enables contracting businesses to spin up branded quoting, proposal, and customer-portal workflows under their own domain — backed by a single shared Cloud Run API, strict RLS-enforced Postgres, and per-tenant GCIP identity. The Ez-Bids brand (home: `ezbids.degenito.ai`) is operated by DeGenito AI; tenants pay $49/user/month for access to the full back-office suite.

---

## 2. Three Surfaces

### 2.1 Platform Admin — `ezbids.degenito.ai`

Audience: Jon, Tim, and the Ez-Bids admin team (platform-level operators).

Purpose:
- Public tenant signup page (request-access queue, D-1)
- Admin review and approval of pending signups
- Tenant provisioning status dashboard (GCIP tenant, domain lifecycle, email identity, billing status)
- Impersonation tooling for support (X-Tenant-ID flow, existing authz invariants)
- Platform-wide billing panel (placeholder; Stripe seam only in v1)
- Platform configuration management

This surface is part of the trusted admin bundle (the "1.5-build" Option A: see D-4 / ADR-001 in the plan). It shares a Vite build artifact with the tenant back office, distinguished at runtime by `window.location.host`.

### 2.2 Tenant Back Office — `app.{tenantDomain}`

Audience: The tenant's own staff — sales reps, marketing, admins — with role-based access (tenant_admin, sales, viewer roles in `core/authz.py`).

Purpose:
- The existing Perkins console feature set: knowledge base, marketing content, estimating, quoting, proposals, clip studio
- Onboarding checklist on first login: domain verification, SSO configuration, email identity, pricing, branding, user management
- User management (invite, enable/disable; billing seat count follows enabled logins — D-7)
- Per-tenant branding and settings
- Proposal lifecycle: create, send, track acceptance, revision requests

This surface shares the trusted admin bundle with the platform admin surface (host-routed at runtime). It connects to the shared API with a GCIP per-tenant identity token that `_resolve_tenant` maps to the platform tenant.

### 2.3 Customer Portal — `quote.{tenantDomain}`

Audience: The tenant's end customers — homeowners, property managers — who receive a proposal or quote link.

Purpose:
- View proposal/quote status and timeline
- Access and review proposal documents (Gotenberg PDF)
- E-sign (existing e-sign-lite flow via `/p/{token}`)
- Request revisions
- (v2+) Payments — explicitly out of scope for v1 (see §5)

This surface is a **separate Vite build on its own Firebase Hosting site**, isolated on trust-boundary grounds (D-4). It ships zero admin or impersonation code. It uses magic-link auth (primary) and the existing signed accept-token (deep-link fallback) — no password accounts (D-6).

---

## 3. User Roles and Journeys

### 3.1 Role Matrix

| Role | Surface | Key Capabilities |
|---|---|---|
| Platform Admin | ezbids.degenito.ai | Approve signups, provision tenants, impersonate, view billing, manage platform config |
| Tenant Admin | app.{d} | Full back-office: users, domain, SSO, brand, pricing, proposals, billing panel |
| Tenant Sales | app.{d} | Create/send/manage proposals and quotes; read KB and marketing content |
| Tenant Viewer | app.{d} | Read-only on proposals and content |
| End Customer | quote.{d} | View/sign/comment on proposals sent to them; no account creation |

Platform admin roles are checked via `platform_admins` table + `core/authz.py` platform_admin action set (`admin_tenants`, `provision_tenant`, `impersonate_tenant`). Tenant roles are enforced by RLS + the per-tenant GCIP token claim.

### 3.2 Tenant Signup → Provisioning → Onboarding Journey (W6)

1. A prospective tenant visits `ezbids.degenito.ai` and fills out the public signup form (company name, primary admin email, intended plan). The form is gated by Turnstile CAPTCHA; disposable-email domains are rejected; the requested tenant slug/subdomain is reserved at submission time to prevent namespace races (council #5).
2. The submission lands in the **request-access queue** (`signup_requests` table, migration 0030) with status `pending`. No GCIP tenant or domain is created before admin approval (D-1). Rate limits per-IP and per-email prevent signup flooding.
3. A platform admin reviews and approves the request in the admin UI. Approval triggers `core/provision.py` (9-step engine with rollback): creates the Postgres tenant row, GCIP tenant, GCS prefix, and default admin invite.
4. The new tenant admin receives an invite email (Resend, platform-controlled sending domain — see §3.4 below; Ez-Bids branded display name with reply-to set to the admin's address).
5. On first login, the tenant admin lands on the **onboarding checklist**:
   - Domain entry: admin provides their domain; proof-of-control (DNS TXT challenge) must be verified before the domain is trusted for auth or email (council #6). The platform then registers `app.{d}` and `quote.{d}` Firebase Hosting sites, surfaces CNAME/TXT records to add at their DNS registrar, polls cert state. (W2)
   - SSO configuration: choose Google / email+password / Microsoft OIDC; platform wires GCIP tenant IdP. (W1 / W6 SSO routes)
   - Email identity: platform sends from the platform-controlled sending domain with the tenant's branded display name and reply-to. No per-tenant sender domain in v1 (J-1). (W3)
   - Pricing/branding: upload brand assets, configure pricing rules. (existing tenant settings)
   - User management: invite team members; each enabled login is a billable seat. (D-7)
6. Once domain is `live`, the tenant back office and customer portal are operational under the tenant's domain.

### 3.3 End Customer Journey (W4)

1. A tenant sales rep creates a proposal and sends it. The customer receives an email with a link to `quote.{tenantDomain}/p/{token}` (the existing accept-token deep-link). The link is opened by clicking a **POST-interstitial** — GET on the link performs no state change, so email scanners and prefetchers cannot burn the token or trigger acceptance (council #7).
2. For repeated portal access, the customer uses a **magic-link** emailed to them (D-6): clicks the link → an interstitial issues a POST that redeems the single-use token → receives a short-lived session on `quote.{tenantDomain}`.
3. Magic-link tokens are: **single-use** (marked `used_at` on redeem; replay rejected), **short-TTL** (minutes-scale), **bound** to the recipient email + tenant + host + proposal where applicable. A token issued for `quote.a.com` cannot be redeemed on `quote.b.com` (council #7).
4. **Session establishment is separate from proposal acceptance.** Landing on the portal and establishing a session is one step; accepting/signing a proposal is an explicit, separately authenticated action (council #7).
5. Customer reviews the proposal, signs (e-sign-lite), or requests revisions.

### 3.4 Email Identity (W3)

All tenant email in v1 sends from a **single platform-controlled sending domain** (e.g. `ezbids-mail.{ourdomain}`), DKIM/SPF/DMARC-authenticated once by us. Per-tenant identity is expressed via:
- `from` = `"{Tenant Display Name} <noreply@ezbids-mail.{ourdomain}>"`
- `reply-to` = the tenant's reply address

**Per-tenant custom sender domains are explicitly deferred** to a post-v1 wave gated on the abuse controls from W2/W5 (J-1 / council #9). This is a binding v1 decision. The `core/email_identity.py` interface is stubbed as a clean seam for that future wave, but no Resend per-tenant domain management is built in v1.


---

## 4. Billing (Stripe — Placeholder v1)

- Price: **$49/user/month**, no setup fee.
- Billable seat definition: **enabled login** (provisioned + not disabled, measured at invoice time). Invited-but-not-accepted users are not charged. "MAU" is not used in v1. (D-7)
- Tenant status lifecycle: `active` → `past_due` (payment overdue) → `suspended` (blocks sign-in). Suspension already uses tenant status in `_resolve_tenant`; the billing wave (W5) wires the check.
- Card-on-file: **deferred entirely in v1** (D-2). Signup collects plan intent only; no Stripe Checkout page. Card collection launches when billing goes live.
- Perkins (tenant 1): **grandfathered** — no per-seat charge applies during the v1 build period. Grandfather status is reviewed at Ez-Bids GA or the 5th onboarded tenant, whichever comes first (ADR-001 de-fork criterion).
- **Suspended tenant portal behavior (council #8):** a suspended tenant's quote portal is read-only / accept-blocked with a billing notice; existing signed proposals remain viewable. This behavior is defined in v1 even though no live billing runs.
- v1 deliverables (council #8 — cutover-proof billing core): `plans` table, `subscriptions` table, **`billing_events` append-only immutable ledger** (event id, type, tenant, payload, received_at, source — the system of record; entitlements derived from it, never overwritten in place), **`entitlement_snapshots`** (snapshot on each billing event for auditability and duplicate-event safety), `core/billing.py` entitlement math, `adapters/stripe_stub.py`, `/billing/webhook` route with **real Stripe signature verification** (against a test secret) and **idempotency keys** (dedupe on Stripe event id so the live handler is the same code with a real secret), entitlement gate on user-invite and tenant-status, grace/dunning semantics (past_due → grace window → suspended, timers stubbed).

---

## 5. Non-Goals (v1)

The following are explicitly out of scope for v1 and must not influence design decisions unless separately approved:

- Payments in the customer portal (no credit card collection from end customers)
- Native iOS app
- SAML integration (design the seam only; no live provider)
- Live Stripe charges (stub adapter only)
- Tenant-supplied custom code or templates beyond existing branding upload
- Per-tenant GCP infrastructure (single shared Cloud Run API + RLS is the isolation model)
- Migration of Perkins (tenant 1) data or identity to the per-tenant GCIP path
- The Cloudflare/D1/iOS per-customer reseller model (jarvis #82 — retired for Ez-Bids; if revived, scoped to a separate product line)
- **Per-tenant custom sender domains** (J-1 / council #9) — v1 sends all tenant email from a single platform-controlled sending domain with per-tenant branded display name + reply-to. Custom sender domains are deferred behind the W2/W5 abuse controls (proof-of-control, moderation). A clean seam (`core/email_identity.py`) is left for that future wave.

---

## 6. Resolved Product Decisions (D-1..D-7)

| ID | Decision | Resolution |
|---|---|---|
| D-1 | Signup gating | Request-access queue. Public form → `pending` queue → platform admin approves → provisioning runs. No self-serve in v1. |
| D-2 | Trial/billing timing | Defer card-on-file entirely. Signup collects plan intent only; no Stripe Checkout stub. |
| D-3 | Perkins GCIP migration | Grandfather on the project pool. Perkins stays on the project-level GCIP pool; however, `_resolve_tenant`'s "no `firebase.tenant` claim → tenant 1" default is **replaced** by an explicit internal tenant-key mapping (J-2 / council #1). A missing claim FAILS CLOSED — it never infers a tenant. Grandfathering is an explicit mapping, not an inference-from-absence. Review migration to per-tenant GCIP pool at GA+1Q or 5th tenant. |
| D-4 | SPA packaging | "1.5-build": platform-admin + tenant back office share one host-routed Vite artifact; `quote.{d}` is a separate build/site from v1 on trust-boundary grounds (not bundle-size). |
| D-5 | Rate limiting on tenant-owned domains | Origin middleware (per-IP + per-token, `platform_config`-backed). "Proxy through our Cloudflare" is an optional premium onboarding path. |
| D-6 | Customer portal auth | Magic-link email (primary portal front door) + existing long-lived signed accept-token (deep-link into a specific proposal). No password accounts. |
| D-7 | Billable seat definition | Enabled login (provisioned + not disabled), measured at invoice time. Not invited, not MAU. |

---

## 7. Success Metrics (v1)

- First non-Perkins tenant reaches `domain.live` state through the automated onboarding flow without manual engineering intervention.
- Tenant admin can complete the full onboarding checklist (domain, SSO, email, users) from the back-office UI in under 30 minutes.
- End customer receives and signs a proposal on `quote.{tenantDomain}` with no cross-tenant data visible.
- Platform admin can approve a signup, monitor provisioning status, and impersonate a tenant from the admin UI.
- Zero cross-tenant data leakage detected by the RLS PG-fixture suite (behavioral: `tests/tenancy/` denial tests pass for all new W0–W7 paths).
- Perkins (tenant 1) login and proposal flow unaffected through all wave deployments (Perkins smoke regression check passes at every wave exit gate).

---

## 8. Security Architecture Decisions (council-absorbed)

These are not optional hardening items — they are binding scope for the named wave.

**W0 — CORS hardening (council CORS TOCTOU):** The dynamic CORS middleware must use exact-match only (no substring/suffix/regex). Every response emits `Vary: Origin`. A request's resolved tenant, its `Host`, and its `Origin` must all belong to the same tenant — a valid origin for tenant A presented on tenant B's host is denied. Preflight (OPTIONS) allow-list must exactly match what the actual request would honor (no "permissive preflight, strict actual" gap).

**W1 — Explicit tenant-1 binding (J-2 / council #1):** `_resolve_tenant`'s "no `firebase.tenant` claim → tenant 1" default is replaced by an explicit internal tenant-key binding at session establishment. Every authed request must resolve to a tenant where token, host, and mapping all agree. A missing or ambiguous claim fails closed — it never infers a tenant. Perkins resolves via its explicit mapping key, not by absence. This closes the "silent default-to-Perkins leaks into jobs, support tools, and future code" hazard. Combined with `strict=True` (already prod-verified — raises on unstamped session), an unbound session cannot silently read data.

**W1 — Non-request context isolation (council #10):** Cron jobs, background workers, CLI/support tooling, and data exports must run on explicit tenant-scoped sessions (not platform sessions over tenant data). The session-establishment primitive from W1 is the single discipline for all execution contexts.

**W2 — Domain proof-of-control + guardrails (council #6 / #3):** A domain is not trusted for auth (`authorized_domains`) or email until DNS TXT proof-of-control is verified. `authorized_domains` writes are journaled (append-only, actor + request correlation), ownership-gated, quota-alarmed, and have a break-glass removal path. Terraform is explicitly NOT the source of truth for `authorized_domains` (ADR-001).

**W4 — Bearer-token hardening (council #7):** Magic-link and accept-tokens are single-use, short-TTL, bound to recipient + tenant + host + proposal. GET on any link performs no state change (scanner-safe). Session establishment and proposal acceptance are distinct authenticated steps. E-sign legal-evidence sufficiency requires a legal review before customer-facing acceptance is trusted as binding.

**W5 — Cutover-proof billing core (council #8):** Even while stubbed, v1 builds: an immutable `billing_events` ledger (the system of record), idempotent signature-verified webhook (same code path as production, different secret), entitlement snapshotting, and grace/dunning state semantics. Going live later is a config flip, not a redesign.

**W6 — Shared admin bundle is packaging, not a security boundary (council #2):** Platform-admin and tenant-staff surfaces share a Vite bundle but must not share a trust context. Required: distinct GCIP auth audiences/clients per surface; separate browser-storage keys; no shared service worker; per-surface CSP + `frame-ancestors`; host-route allowlists. A browser test proving an admin token is unusable on the staff origin (and vice versa) is the gate that proves the boundary is real.

**W6 — Signup abuse controls (council #5):** Turnstile CAPTCHA on the signup form; per-IP and per-email rate limits; disposable-email domain block; no GCIP tenant or domain created before admin approval; tenant-namespace reservation at submission time (blocklist reserved/abusive names, prevent racing duplicates).

## 8a. Pre-Mortem: Four Failure Scenarios

**Failure 1 — Cross-tenant data leakage via a new unscoped path (CRITICAL).** A new path (portal magic-link handler, CORS/email lookup) runs a query on a platform-scoped session before tenant resolution and leaks another tenant's row. Detection: PG-fixture RLS denial suite extended in every data-touching wave with a cross-tenant negative test. Mitigation: mirror `_token_scoped_session` — resolve tenant via token/host on a platform session, immediately stamp tenant-scoped session; no tenant data on a platform session.

**Failure 2 — Domain onboarding wedged in half-state (HIGH).** Firebase custom-domain add succeeds but cert stalls, or `authorized_domains` write is missed, so sign-in on `app.{tenant}` fails silently. Detection: W2 state machine with explicit `failed`/timeout states; platform-admin health panel; alert when domain stuck in `cert_pending` past threshold. Mitigation: idempotent resumable state machine; `authorized_domains` single runtime owner with `ignore_changes` + reconciler audit.

**Failure 3 — Perkins regression from a "global" change (HIGH).** Moving CORS to DB (W0), flipping `allow_tenants=true` (W1), or host-routing the SPA (W6) breaks `app.perkinsroofing.net` login. Detection: standing Perkins smoke behavioral check at every wave exit gate. Mitigation: grandfathering (D-3) as primary shield; stage `allow_tenants=true` on pre-prod substrate before prod (§8b).

**Failure 4 — SPA-layer cross-surface privilege bleed (HIGH).** Admin/impersonation code is present on or reachable from the untrusted `quote.{d}` origin — e.g., portal left inside the shared bundle, or a host-detect branch reachable via XSS. Detection: CI build-content assertion that the portal artifact contains no admin/impersonation module names; per-site CSP that would break if admin origins were referenced. Mitigation: the v1 "1.5-build" trust-boundary split is the primary shield — the portal is a separate build shipping zero admin code.

## 8b. Pre-Prod Substrate for the `allow_tenants` Flip (W1)

Before W1 executes, one of the following must be named:

- **Recommended:** a separate pre-prod GCP project carrying a mirror of the Identity Platform config. The `allow_tenants=true` flip + create→map→resolve→delete round-trip on a throwaway GCIP tenant is exercised against real GCIP behavior, and a no-firebase.tenant token still resolves to the grandfathered tenant. This keeps Perkins's project untouched during validation.
- **Alternative (elevated risk):** explicitly accept prod-only verification, stated in the W1 wave notes, with: Perkins-smoke regression check run immediately before and after the flip, a rehearsed `allow_tenants=false` rollback, and the apply scheduled in a low-traffic window.

Whichever is chosen must be recorded in the W1 wave notes. The W1 exit gate is not satisfied by a prod-only flip unless the alternative is explicitly documented.

## 9. Open Blockers (Jon Action Required)

- `CLOUDFLARE_DEGENITO_API_KEY`: degenito.ai zone, DNS:Edit permission. Required for W6 (ezbids.degenito.ai DNS). The vaulted Perkins token is scoped to perkinsroofing.net only.
- Ez-Bids legal/brand assets timing (jarvis #329 PDFs): affects signup page copy only; not a code blocker.
- Council: formally retire jarvis #82 (the Cloudflare/D1/iOS reseller path) for Ez-Bids or scope it to a separate product line.
- W1 pre-prod substrate: before flipping `allow_tenants=true` in GCIP, name the validation environment (preferred: separate GCP project; alternative: prod with documented risk acceptance + rollback plan).
