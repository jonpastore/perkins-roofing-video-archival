# Full-Funnel Platform Plan — Perkins v2 → multi-tenant sales & marketing platform

**Date:** 2026-07-08 · **Version:** v2 (Fable ultrathink pass) · **Status:** DRAFT for Jon's approval — no build until approved
**Grounding:** phase-2 spec · Ez-Bids proposal + full legal package (63pp incl. Exhibit B pricing +
Exhibit C acceptance) · Knowify teardown · Opus Clip / repurpose.io teardowns · FL competitor research ·
Jon's locked decisions · the 2026-07-08 payment-schedule email (commercial clock, §10).

**What changed in v2 (ultrathink deltas over the v1 draft):**
re-sequenced waves around the commercial clock (quoting demo ≈ 3-week deadline) · thin-tenancy-first
(columns now, RLS/GCIP hardening before tenant #2) · login-time tenant resolution instead of
per-tenant subdomains (avoids the Firebase wildcard-domain trap) · Perkins stays on the project-level
auth pool (zero-disruption GCIP path) · named the RLS session pattern + job tenant-loop · cost-category
tagging on line items (fixes the 13%/33% floor + commission math) · Gotenberg for PDF · e-sign legal
specifics · per-tenant usage metering + per-tenant social creds · Cloud SQL PITR + edge rate limits.

---

## 0. Locked decisions (inputs, not open questions)

| Decision | Value |
|---|---|
| Cloud | **Everything on GCP** (Cloud Run, Cloud SQL, GCS, Vertex) |
| Database | **PostgreSQL** (existing Cloud SQL instance) |
| Edge | **Cloudflare ingress** (DNS + WAF/proxy, Full-strict TLS) → GCP origin; client-owned custom domain |
| Auth | **Firebase Auth → GCIP** (multi-tenant; per-tenant SAML/OIDC/Microsoft/Apple later) |
| Tenancy | **Whole platform multi-tenant** — including content management (second revenue stream) |
| Ez-Bids | **Rebuilt on our GCP stack**; `core/estimator.py` is the foundation |
| Knowify | **Displace proposal feature only**; no QuickBooks/accounting (Tim's backend is elsewhere) |
| IA | Sidebar: **Knowledge Base · Marketing · Estimating · Quoting** + **Admin** (config tabs per section) |
| Non-goals | engagement-sim bots · accounting/billing/QBO · payment *processing* in v1 · native iOS in v1 |

## 1. Product thesis

One platform, one funnel: **content → leads → quote → proposal → job handoff.** The platform
generates the marketing that drives leads, and converts them. Perkins is tenant #1; the licensable
product is a **turnkey roofing growth platform** (content + SEO/AIO + quoting + proposals), a bigger
offer and ARPU than Ez-Bids-the-quoting-tool. Displacing Knowify also deletes a $99–399/mo line item
from every licensee's stack — part of the pitch.

## 2. Information architecture

```
┌─ Knowledge Base   corpus (videos), Search/Ask, FAQ, Contract-FAQ
├─ Marketing        Clip Studio (Track A editor), Articles, Social/Distribution,
│                   Publish pipeline (pillar/cluster), Comments, Email
├─ Estimating       pricing engine (Exhibit-B complete), branches, code zones,
│                   measurements (SquareQuote | manual)
├─ Quoting          quote → Proposal builder → send / e-sign / track → deposit → handoff
└─ Admin            per-section config tabs (§7) + Users + Tenant provisioning (platform-admin)
```

- Existing tab keys stay as routes; the sidebar adds a grouping level only (no broken bookmarks).
- **Responsive requirement:** the owner sales flow (create quote → send proposal) must work on a
  phone — Knowify's mobile app is field-only; this is a differentiator (F4 acceptance criterion).

## 3. Tenancy architecture

**Single Postgres DB, `tenant_id` + Row-Level Security, defense-in-depth.** Schema-per-tenant
rejected: on one Cloud SQL instance it buys no real blast-radius, multiplies migrations, and
duplicates the expensive 3072-dim HNSW pgvector indexes. Ez-Bids' contractual isolation rigor is
preserved **as tests**, which RLS can pass.

Mechanics (named precisely — this is where RLS designs usually fail):
1. `tenants` (id, name, slug, status, settings JSONB). **Perkins = tenant 1**; migration backfills.
2. `tenant_id` FK on every tenant-scoped table; platform tables exempt.
3. RLS policy per table: `USING (tenant_id = current_setting('app.tenant_id')::int)`. App role is
   non-superuser, **no BYPASSRLS**.
4. **Session pattern:** transaction-scoped `SET LOCAL app.tenant_id` issued by a SQLAlchemy
   after-begin event from the verified token — never from a header/param. Pool-safe by construction
   (SET LOCAL dies with the transaction; nothing to leak across checkouts).
5. **Jobs:** a `for_each_tenant()` wrapper — crons iterate tenants, set context, reset per-tenant
   Cost counters, drain. No job touches data outside a tenant context.
6. **Defense-in-depth (Exhibit-C rigor):** ORM base-query tenant filter (belt) + RLS (suspenders) +
   **≥30 denial tests in CI** + cross-tenant probe (404-indistinguishable, ≤100ms timing differential)
   + CI grep blocking raw `text()`/execute outside approved modules + tenant_id on every log line.
7. GCS: per-tenant prefixes (`tenants/{id}/…`); per-tenant social/API creds in Secret Manager under
   `tenants/{id}/…` (the distribution `oauth_store` interface already anticipates this).
8. **Offboarding:** tenant delete = RLS-scoped cascade + GCS prefix delete + audit record.
9. **Scaling lever (not v1):** if tenant count/corpora grow, list-partition `chunks` by tenant_id —
   per-partition HNSW indexes, clean pruning — without changing the app model.
10. **Usage metering:** per-tenant counters (LLM tokens, STT minutes, render minutes) emitted on the
    existing structured-log path — the future billing story for licensees costs ~nothing to record now.

## 4. Identity & access (GCIP)

- Upgrade Firebase Auth → Identity Platform. **Perkins keeps the project-level user pool as
  tenant 1** (no user migration, zero disruption); *new licensees* get real GCIP tenants. Token
  claim mapping: no `firebase.tenant` claim → tenant 1; else GCIP-tenant → platform-tenant lookup.
- **Tenant resolution at login (v1): invite links + email-domain discovery on a single app domain.**
  Per-tenant subdomains are deliberately deferred — Firebase Hosting can't do wildcard custom
  domains, and single-digit tenants don't need them. When they do, SPA hosting moves to GCS+LB or
  Cloud Run with a wildcard cert (revisit at ~10 tenants).
- `core/authz.py` extends to section-scoped actions (`kb_*`, `marketing_*`, `estimating_*`,
  `quoting_*`, `admin_*`) over existing roles + new **platform_admin** (cross-tenant provisioning,
  DeGenito-only — the Ez-Bids "SaaS Web Admin," generalized). `DEFAULT_ADMINS` → per-tenant config.
- GCIP cost: free ≤50k MAU (email/social); SAML/OIDC $0.015/MAU. Negligible at this scale.

## 5. Estimating — Exhibit-B completion (contract-grade engine)

1. **Config-driven pricing:** rate tables move from code constants to versioned **`pricing_configs`**
   (JSONB, per tenant per branch), edited in Admin → Estimating. Engine becomes pure
   `estimate(config, input)` — stays 100%-coverable; Exhibit B ships as the committed seed fixture.
2. **`pricing_config_hash`** — RFC 8785 JSON-Canonical + SHA-256 of the active config stamped on
   every quote (audit reproducibility, per SOW).
3. **Line items carry cost-category tags** (Labor / Materials / Equipment / Sub / Misc / OH / Profit).
   This is what makes the **13% profit and 33% profit+OH floors** computable correctly (Exhibit B
   marks insulation "no profit added", tapered "no OH or profit") and powers **commission = % of
   profit dollars** (10% sloped / 15% low-slope; sloped-HVHZ 15%? → open item #3). Fixes a real gap
   in the current stub (`margin_ok` used the wrong denominator basis).
4. **Low-slope category** (Exhibit B §4): TPO/coatings/silicone/BUR base costs, insulation tiers,
   deck types, per-layer tear-off extras, flat/TPO/coatings OH, crane/trash-chute height rules.
5. **Branches** (Miami/Jupiter/Naples) with default `code_zone`; **code_zone is per-property,
   overridable per quote; mixed-tier applies per slope/line** (Adv-2).
6. Remaining delta fixes: PM incentive = zone×job-size matrix · tile dumpster = threshold count
   (HVHZ every >15sq, FBC every 30sq) · 7% materials-tax flag on some tile · sliding-scale
   **boundary-band rule confirmed with Tim** (Adv-1: lower-inclusive/upper-exclusive presumed).
7. **County coverage:** Broward + Miami-Dade = the HVHZ zone (Exhibit B HVHZ tables apply as-is);
   Palm Beach/Lee/St. Lucie = FBC. Pricing config supports **per-county overrides** on top of the
   zone tables (permit fees, materials-tax flag, county line items) since code_zone is per-property.
7. **Acceptance = the 5 golden files** (Exhibit C): 498-SQ low-slope HVHZ · 15-SQ low-slope FBC ·
   28-SQ sloped HVHZ · 28-SQ sloped FBC · 41.5-SQ standing-seam FBC — **±$0.01 or ±0.01%**, via
   manual entry AND measurement-fed. Permanent CI fixtures; Josh's Roofr quotes validate on top.
8. **Measurements:** `Measurement` model (SQ, hips, ridges, valleys, rakes, eaves, wall flashings) +
   `MeasurementProvider` interface. **SquareQuote adapter** (B2B `/api/reports`, royalty-free,
   DO-hosted; mocked until the API key lands) with **manual entry as a first-class, clearly-labeled
   fallback** (Exhibit C Scenario 5: never silently substitute).

## 6. Quoting — proposal builder (Knowify displacement)

Data model: `customers` (+contacts) · `properties` (address, code_zone flag, optional
`knowify_customer_id`) · `proposals` (tenant, customer, property, **quote_snapshot** JSONB, template
ref, **version + parent_id** chain, status draft→sent→viewed→accepted|declined|revision_requested,
accept_token, audit fields) · `proposal_events` (sent/viewed/accepted/declined + IP/UA/timestamp) ·
lightweight `leads` (source → convert to customer+property; a status field, not a CRM).

Build (parity + the four openings the teardown found):
1. **Templates — self-serve and multiple** (Knowify's #1 complaint requires emailing their IT):
   tenant-branded HTML templates (logo, colors, cover page, T&C, attachments) edited in Admin.
   **PDF via Gotenberg on Cloud Run** — battle-tested HTML→PDF container, IAM-locked, zero new
   Python deps (Terraformed like any service).
2. **Tiered/optional pricing** (Knowify can't): good-better-best + optional line items,
   client-selectable on the accept page.
3. **Revisioning** (Knowify can't): edit-after-send = new version; old link dies
   ("superseded"), chain preserved.
4. **E-sign lite** (what Knowify itself does in-house): tokenized **no-login accept page** —
   view → select options → **consent-to-electronic-business checkbox** → typed name → accept —
   full audit trail, **signed-PDF copy emailed to the client** (ESIGN/UETA: intent, consent,
   attribution, record delivery). High-entropy single-version tokens, 404-indistinguishable,
   Cloudflare rate-limited. Seam left for a named provider (Dropbox Sign/SignWell) if a client's
   counsel ever demands one.
5. **Status + follow-ups:** real-time sent/viewed/accepted; **automated reminder nudges**
   (Knowify has none).
6. **Deposit + handoff:** on acceptance, record deposit due (% or fixed, configurable) with payment
   instructions — *no processing in v1* — and convert proposal → job status + notification.
7. **Knowify migration:** XLS import (customers, catalog) + one-time PDF archive of historical
   proposals into per-property GCS; then cancel. No Zapier bridge unless Tim wants overlap.

## 7. Admin — config tabs

| Tab | Manages |
|---|---|
| Knowledge Base | corpus/channel sources, ingest controls, abstain threshold, FAQ policy |
| Marketing | brand kit (logo/colors/fonts/intro-outro), voice samples, caption prompts (v5), publish cadence + seed %, social accounts, safety-gate denylist |
| Estimating | branches, pricing-config versioned editor (+hash display), code-zone defaults, measurement provider |
| Quoting | proposal templates, T&C library, deposit policy, reminder cadence |
| Users & Roles | Users page + per-tenant default admins |
| Tenants *(platform_admin)* | provision tenant, seed configs, GCIP tenant, invite admin, usage metering view |

## 8. Infra & edge

- **Cloudflare ingress:** client domain on CF DNS, proxied (Full-strict) → Firebase Hosting (SPA
  custom domain) + Cloud Run API (domain mapping). WAF + rate limiting (accept pages, auth
  endpoints) at edge. Later hardening: Cloud Armor allowlist of CF IP ranges at origin.
  **Needs the domain name (open item #1).**
- **Cloud SQL PITR turned ON** (currently a flagged gap) — multi-tenant contractual data demands it.
- All new infra Terraformed (R3), drift-checked (R4). CI adds golden-file + tenancy-denial suites to
  the existing ruff/bandit/pip-audit/100%-coverage gates.

## 9. Waves — re-sequenced around the commercial clock

The 2026-07-08 email sets the schedule: video phase-1 payment now, **quoting build starts next week,
deposit the week after, completion payment ~2 weeks later** → the Estimating+Quoting demo path has a
**~3–4 week commercial deadline**. Full tenancy hardening is required **before tenant #2**, not
before Tim's demo. Hence:

| Wave | Scope | Exit gate | Est. |
|---|---|---|---|
| **F0 — Thin tenancy** | `tenants` table + `tenant_id` (default 1) on all tables + ORM filter discipline. *No GCIP/RLS yet.* Every subsequent table is born tenant-scoped — kills the retrofit risk | migration green; Perkins unchanged | 0.5 s |
| **F1 — IA reorg** | two-level sidebar (4 sections + Admin), Admin config-tab shell | all pages reachable, role-gated; Jon sees the new product shape | 1–2 s |
| **F2 — Estimating complete** | config-driven PricingConfig + hash, cost-category tags, low-slope, branches, per-property code zone, delta fixes, Measurement model + SquareQuote adapter (mock) | **5 golden files ±$0.01 in CI**; config editable in Admin | 2 s |
| **F3 — Quoting/Proposals** *(the commercial deliverable)* | customers/properties/leads, proposal builder + templates + tiers + revisions, e-sign-lite accept page, tracking + reminders, deposit + handoff, Gotenberg, Knowify import tooling | end-to-end on a phone: quote → send → client accepts → audit trail + PDF copy. Then mirror the SDA: **3-day preprod validation by Tim → 14-day acceptance** | 3–4 s |
| **F4 — Tenancy hardening** *(before tenant #2; ∥ F5)* | RLS policies + SET LOCAL pattern, GCIP upgrade (Perkins stays project-pool), platform_admin, ≥30 denial tests + cross-tenant probe, PITR | denial suite + probe green; Perkins login unchanged | 2 s |
| **F5 — Marketing/KB tenant-ization** | `for_each_tenant` job wrapper, per-tenant configs/creds/metering, brand kit, **wire Track A engines into Clip Studio UI** | test tenant publishes to its own corpus safely; clips render with transitions/music/text | 2–3 s |
| **F6 — Edge + onboarding** | Cloudflare ingress + custom domain, tenant provisioning UI, per-tenant SSO, security re-review (opus), load pass | onboard a tenant < 1 hr; drift clean; R2 sign-off | 2 s |

~13–16 sessions. Critical path to Tim's deliverable: **F0 → (F1 ∥ F2) → F3**.

## 10. Open items (human-owned; none block F0–F2)

1. ~~Custom domain name~~ **RESOLVED: `app.perkinsroofing.net`** (Jon, 2026-07-08). Remaining
   dependency: DNS/registrar control of perkinsroofing.net (Tucows — via Amber, already a tracked
   ask). Existing website + Google Workspace MX untouched; we only add the app subdomain. Cloudflare
   onboarding of the zone (free plan needs the apex zone; import ALL existing records incl. MX/SPF/DKIM
   before nameserver change) or interim direct CNAME if CF onboarding waits — decided at F6.
2. **5 golden-file quotes** (Tim/Josh; Exhibit C anchors) — mid-F2.
3. **Sloped-HVHZ commission 10% vs 15%** + sliding-scale boundary rule (Tim) — F2 seed.
4. **SquareQuote API key/base URL** (DeGenito internal) — F2 adapter goes live; mock until then.
5. **Knowify XLS exports + proposal-PDF archive** (Josh/Tim) — F3 migration.
6. **⚠️ Entity/IP/branding:** Ez-Bids LLC (90/10, $25k cap, deemed-acceptance) vs the unified
   multi-tenant platform — which entity owns what; does "Ez-Bids" stay the quoting brand?
   **Counsel + business decision. Flagged, not solved.**
7. Standing blockers (jarvis #315–329): social app reviews, creds, voice samples, music catalog,
   Pexels/HeyGen/ElevenLabs keys.

## 11. Risks

- **RLS discipline** — one unscoped raw query leaks; mitigated by the four-layer defense + CI grep.
  RLS also *covers* raw SQL (unlike ORM-only filtering) since the app role can't bypass it.
- **GCIP flip** — mitigated to near-zero for Perkins by keeping the project-level pool as tenant 1.
- **pgvector + RLS at scale** — filtered HNSW recall degrades with many tenants; partition-by-tenant
  is the pre-planned lever (§3.9).
- **Scope gravity in Quoting** — the §0 non-goals list is the fence (no CRM, no payments, no ERP).
- **Golden-file dependency** — engine can ship on Exhibit-B unit fixtures if Tim's exemplars are
  late; *contract-grade* sign-off waits for them.
- **Commercial clock** — F3 is deadline-driven; if it slips, cut reminders + leads (Should-tier)
  before touching templates/e-sign/revisions (the differentiators).
