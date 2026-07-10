# Ez-Bids — Product Requirements Document

**STATUS: DRAFT — derived from consensus-approved plan; pending council + Jon validation.**
Derived from: `ralplan-ezbids-multitenant-DRAFT.md` (Planner→Architect SOUND-WITH-CHANGES→Critic APPROVE, all 7 changes applied) and `docs/superpowers/specs/2026-07-10-ezbids-multitenant-brief.md`.

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

1. A prospective tenant visits `ezbids.degenito.ai` and fills out the public signup form (company name, primary admin email, intended plan).
2. The submission lands in the **request-access queue** (`signup_requests` table, migration 0030) with status `pending`. (D-1: no self-serve provisioning; an Ez-Bids admin approves every signup to prevent abuse during early onboarding.)
3. A platform admin reviews and approves the request in the admin UI. Approval triggers `core/provision.py` (9-step engine with rollback): creates the Postgres tenant row, GCIP tenant, GCS prefix, and default admin invite.
4. The new tenant admin receives an invite email (Resend, branded as Ez-Bids until tenant email is configured).
5. On first login, the tenant admin lands on the **onboarding checklist**:
   - Domain entry: admin provides their domain; the platform registers `app.{d}` and `quote.{d}` Firebase Hosting sites, surfaces CNAME/TXT records to add at their DNS registrar, polls cert state. (W2)
   - SSO configuration: choose Google / email+password / Microsoft OIDC; platform wires GCIP tenant IdP. (W1 / W6 SSO routes)
   - Email identity: admin confirms domain; platform creates Resend domain identity, surfaces DKIM/SPF records, polls verification. (W3)
   - Pricing/branding: upload brand assets, configure pricing rules. (existing tenant settings)
   - User management: invite team members; each enabled login is a billable seat. (D-7)
6. Once domain is `live` and email is verified, the tenant back office and customer portal are operational under the tenant's domain.

### 3.3 End Customer Journey (W4)

1. A tenant sales rep creates a proposal and sends it. The customer receives an email with a link to `quote.{tenantDomain}/p/{token}` (the existing accept-token deep-link).
2. For repeated portal access, the customer uses a **magic-link** emailed to them (D-6): clicks the link → receives a short-lived session on `quote.{tenantDomain}`.
3. Customer reviews the proposal, signs (e-sign-lite), or requests revisions.

---

## 4. Billing (Stripe — Placeholder v1)

- Price: **$49/user/month**, no setup fee.
- Billable seat definition: **enabled login** (provisioned + not disabled, measured at invoice time). Invited-but-not-accepted users are not charged. "MAU" is not used in v1. (D-7)
- Tenant status lifecycle: `active` → `past_due` (payment overdue) → `suspended` (blocks sign-in). Suspension already uses tenant status in `_resolve_tenant`; the billing wave (W5) wires the check.
- Card-on-file: **deferred entirely in v1** (D-2). Signup collects plan intent only; no Stripe Checkout page. Card collection launches when billing goes live.
- Perkins (tenant 1): **grandfathered** — no per-seat charge applies during the v1 build period. Grandfather status is reviewed at Ez-Bids GA or the 5th onboarded tenant, whichever comes first (ADR-001 de-fork criterion).
- v1 deliverables: `plans` table, `subscriptions` table, `core/billing.py` entitlement math, `adapters/stripe_stub.py`, `/billing/webhook` signature-verify stub, entitlement gate on user-invite and tenant-status.

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

---

## 6. Resolved Product Decisions (D-1..D-7)

| ID | Decision | Resolution |
|---|---|---|
| D-1 | Signup gating | Request-access queue. Public form → `pending` queue → platform admin approves → provisioning runs. No self-serve in v1. |
| D-2 | Trial/billing timing | Defer card-on-file entirely. Signup collects plan intent only; no Stripe Checkout stub. |
| D-3 | Perkins GCIP migration | Grandfather on the project pool. `_resolve_tenant` default (no `firebase.tenant` claim → tenant 1) remains unchanged. Review at GA+1Q or 5th tenant. |
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

## 8. Open Blockers (Jon Action Required)

- `CLOUDFLARE_DEGENITO_API_KEY`: degenito.ai zone, DNS:Edit permission. Required for W6 (ezbids.degenito.ai DNS). The vaulted Perkins token is scoped to perkinsroofing.net only.
- Ez-Bids legal/brand assets timing (jarvis #329 PDFs): affects signup page copy only; not a code blocker.
- Council: formally retire jarvis #82 (the Cloudflare/D1/iOS reseller path) for Ez-Bids or scope it to a separate product line.
- W1 pre-prod substrate: before flipping `allow_tenants=true` in GCIP, name the validation environment (preferred: separate GCP project; alternative: prod with documented risk acceptance + rollback plan).
