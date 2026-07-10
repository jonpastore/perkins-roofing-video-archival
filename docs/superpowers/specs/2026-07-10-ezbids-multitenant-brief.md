# Ez-Bids Multi-Tenant SaaS — Requirements Brief (ralplan input)

Author: main lane (Fable) from Jon's 2026-07-10 directive. This brief seeds ralplan; the
consensus plan, PRD, TRD, and DDD derive from it. Target confidence: 95% — open questions
are enumerated in §8 for council + Jon validation.

## 1. Product shape (Jon's words, structured)

Three web surfaces on one multi-tenant platform (this repo's GCP project):

| Surface | Host | Audience | Purpose |
|---|---|---|---|
| Platform admin | **ezbids.degenito.ai** | Jon, Tim, admin team | Tenant management, provisioning, billing, health; PUBLIC TENANT SIGNUP page |
| Tenant back office | **app.{tenantDomain}** | Tenant's staff (sales/marketing/admin roles) | The existing console: KB, marketing, estimating, quoting, proposals, clip studio |
| Customer portal | **quote.{tenantDomain}** | Tenant's END CUSTOMERS | Quote/proposal status, docs, e-sign, (later: payments) |

Tenants supply their own domain; we automate pointing (Firebase Hosting custom domains +
DNS instructions), their SSO choice, and their email sending identity.

Billing: **$49/user/month, no setup fee** — Stripe, PLACEHOLDERS now (adapter + webhook
stubs + entitlement seams), real integration later.

## 2. What already exists (build ON this — do not reinvent)

- **Tenancy core (hardened TODAY)**: `tenants` table, 30 RLS-FORCED tables, strict=True
  session discipline, `get_db_session`, `PlatformSessionLocal`, `for_each_tenant` jobs.
- **Identity (F4)**: GCIP (Identity Platform) with claim mapping, `tenant_gcip_map`
  (GCIP tenant id → platform tenant), `platform_admins` table + X-Tenant-ID impersonation
  invariants, deny-by-default role matrix (`core/authz.py`) incl. platform_admin actions
  (`admin_tenants`, `provision_tenant`, `impersonate_tenant`...).
- **Provisioning (F6)**: `core/provision.py` engine + `core/offboard.py`; tested.
- **Per-tenant config**: `tenant_settings` (JSONB, marketing/KB settings), versioned
  per-tenant pricing configs (branch-aware), brand kit upload (GCS per-tenant paths).
- **Customer-facing seed**: proposal accept pages `/p/{token}` (rate-limit-designed in F6
  edge plan, e-sign-lite, PDF via Gotenberg) — the embryo of quote.{tenantDomain}.
- **Domain automation (proven TODAY)**: Firebase Hosting custom-domain API + Cloudflare
  TF records + GCIP authorized_domains via TF (app.perkinsroofing.net went live this way).
- **Metering**: per-tenant cost counters emitted per job run (caps deferred).
- **Email**: branded wrapper (core/email_template.py, TODAY), Resend adapter with
  from_email, EMAIL_HTML_HEADER platform config, perkinsroofing.net fully authenticated.

## 3. Net-new work (the plan's substance)

1. **Tenant signup flow** (ezbids.degenito.ai): public page → collect company/admin/plan →
   create tenant row + GCIP tenant + default admin invite → drive `core/provision.py` →
   onboarding checklist (domain, SSO, email, pricing config, branding, users).
2. **Per-tenant SSO**: real GCIP *tenants* (Identity Platform multi-tenancy — the
   `multi_tenant` block currently ignore_changes'd in TF) with per-tenant IdP selection
   (Google / Microsoft / email+password / SAML later). `tenant_gcip_map` already models
   the mapping. Migration path for tenant 1 (Perkins) from project-level pool → its own
   GCIP tenant (or grandfather it — decision D-3).
3. **Domain lifecycle automation**: tenant enters domain → we register app.{d} and
   quote.{d} on Firebase Hosting via API, surface required CNAME + TXT records in the
   onboarding UI, poll cert state (all proven today), add domains to GCIP
   authorized_domains, and add origins to CORS — **adjustment: CORS_ORIGINS must move
   from env var to a DB-backed platform table read at request time** (env redeploys per
   tenant don't scale).
4. **Customer portal (quote.{d})**: light SPA (or same bundle, host-routed) — magic-link
   or token auth (extend accept-token model; no password accounts v1), quote/proposal
   timeline, doc viewing, e-sign, revision requests. Reuses /p/{token} backend.
5. **Host-based surface routing**: one repo; decide (D-4) between (a) single SPA bundle
   with runtime host detection, (b) three Vite builds → three Firebase sites. Platform
   admin surface (tenant list, provisioning status, impersonation, billing) partially
   exists as routes (`admin_tenants` etc.) but has NO UI yet.
6. **Per-tenant email identity**: Resend domain API per tenant domain (DKIM/SPF records
   in onboarding UI, verification polling), per-tenant EMAIL_HTML_HEADER + wrapper brand
   tokens (extend today's platform-wide header to tenant_settings), sender = user@tenant
   domain once verified (fallback: tenantname@ezbids-mail domain until verified).
7. **Billing placeholders (Stripe)**: `core/billing.py` seams + `adapters/stripe_stub.py`,
   plans table ($49/user/mo, quantity = active users), webhook route stub
   (`/billing/webhook`), entitlement checks at user-invite + tenant-status
   (`active|past_due|suspended` — suspend gates sign-in via tenant status, already
   modeled), admin billing panel placeholder. NO live Stripe calls v1.
8. **Ez-Bids branding** for platform surfaces (signup + admin) distinct from tenant brand.

## 4. Alignment review — tensions the plan MUST resolve

- **T-1 (biggest)**: memory `perkins-ezbids-proposal` — the original Ez-Bids proposal
  assumed Cloudflare/D1/iOS single-tenant-per-customer; jarvis #82 models a per-customer
  Cloudflare reseller path. THIS directive puts Ez-Bids on the GCP multi-tenant platform.
  Treat GCP multi-tenant as the decision of record (locked decisions already say "GCP,
  Ez-Bids rebuilt on this stack"); the plan should explicitly retire #82's applicability
  to Ez-Bids or scope it to a different product line. Council should sanity-check.
- **T-2**: single Cloud Run API serves all tenants (current architecture) — fine at this
  scale; the "client-owned GCP" philosophy applies to Perkins-as-first-tenant history,
  not to Ez-Bids SaaS tenants. Data isolation = RLS (now strict) + per-tenant GCS paths.
- **T-3**: H1 edge plan (WAF/rate limits) was written for app.perkinsroofing.net; must
  generalize to per-tenant hostnames (Cloudflare for OUR zones only — tenant zones are
  theirs; rate-limiting moves to origin or a shared proxy decision D-5).
- **T-4**: deploy.sh CFG_ENV single-tenant leftovers (WP_URL, YT_OWNER_CHANNEL_ID,
  WORKSPACE_ADMIN_SUBJECT) → belong in tenant_settings / per-tenant integrations.
- **T-5**: naming — repo/memories call the SaaS both "SquareQuote" and "Ez-Bids"; brand
  of record per Jon today: **Ez-Bids** (ezbids.degenito.ai as home).

## 5. Non-goals v1 (guardrails)

No payments in the customer portal; no native iOS; no SAML (design the seam only); no
live Stripe charges; no tenant-supplied custom code/templates beyond existing branding;
no per-tenant infrastructure (single shared stack + RLS); no migration of Perkins data.

## 6. Constraints

R1–R5 (100% core cov, R2 dual review, IaC-only, drift checks). Strict tenancy everywhere.
TDD fail-first. Migrations .sql additive. Firebase Hosting for all three surfaces.
GCIP for identity. Resend for email. Stripe for billing (stub v1). $49/user/mo flat.

## 7. Immediate blockers/asks (Jon)

- **Cloudflare token for degenito.ai zone** — the vaulted token is scoped to
  perkinsroofing.net only; ezbids.degenito.ai DNS needs a token with degenito.ai zone
  DNS:Edit (drop it in .env as CLOUDFLARE_DEGENITO_API_KEY; I vault + wire it).
- Confirm Ez-Bids legal/brand assets timing (#329 PDFs) — affects signup page copy only.

## 8. Open decisions for council + Jon (target: resolve to reach 95%)

- D-1: signup gating — open self-serve vs invite/approval queue (recommend: request-
  access queue v1; Jon/Tim approve in admin → provisioning runs).
- D-2: trial/billing timing — placeholder now, but does signup collect card-on-file
  intent (Stripe Checkout stub page) or defer entirely?
- D-3: migrate Perkins (tenant 1) to a GCIP tenant now or grandfather on the project
  pool until Ez-Bids GA?
- D-4: SPA packaging — host-routed single bundle vs 3 builds/sites (cost: build times,
  bundle size (already 1.9MB), blast radius; benefit: shared components).
- D-5: customer-portal + tenant-app rate limiting when domains are tenant-owned (origin
  middleware vs require CNAME-through-our-Cloudflare (proxied) as onboarding option).
- D-6: quote.{d} auth — magic-link email vs long-lived signed token links vs both.
- D-7: per-seat billing definition — "active user" = enabled login? invited? MAU?
  (pricing page copy + entitlement math depend on it).
