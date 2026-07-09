# PRD — Quoting & Proposal Builder (Wave F3)

**Product:** Perkins Roofing Full-Funnel Platform  
**Section:** Quoting (sidebar section 4 of 4)  
**Wave:** F3 — the commercial deliverable  
**Version:** 1.0 · 2026-07-08  
**Status:** DRAFT (R2 fixes applied — pending Jon approval)  
**Author:** DeGenito AI  
**Commercial clock:** ~3 weeks from 2026-07-08 payment  

---

## 1. Purpose & commercial context

Wave F3 delivers the last piece of the full funnel: **quote → proposal → client acceptance → job handoff.** It displaces Knowify's proposal feature entirely, eliminating a $99–399/mo line item from Perkins' stack and from every future licensee's stack.

The three features Knowify cannot do — **multiple self-serve templates, proposal revisioning, and client-selectable tiered/optional pricing** — are the primary competitive differentiators. They are Must-have and cannot be cut under any schedule pressure. The slip rule: cut automated reminders and the lightweight leads tracker first; never touch templates, revisions, tiers, or e-sign.

The module is the licensable core of the Ez-Bids SaaS product (formerly the Ez-Bids LLC proposal, now rebuilt on the GCP/PostgreSQL/FastAPI/React stack). A homeowner who receives a proposal link never logs in; the contractor creates and sends from a browser or phone.

---

## 2. Personas & user stories

### 2.1 Tim Perkins — owner / sales lead

| Story | Acceptance |
|---|---|
| As Tim, I can open the Quoting section on my phone and build a proposal from a saved estimate in under 5 minutes | Proposal created and sent entirely from an iOS Safari / Chrome mobile session |
| As Tim, I can pick which proposal template to use for this job and know the client sees our brand | Template selector at proposal creation; rendered PDF matches logo/colors/T&C |
| As Tim, I can send a proposal and see in real time when the client opens it | Event timeline on the proposal detail page updates without page refresh |
| As Tim, I can edit a sent proposal (e.g., correct a line item the client questioned) without the client seeing the old version | New version created; old accept link returns "superseded" page; Tim sees version chain |
| As Tim, I can offer the client a good-better-best choice and let them pick on the acceptance page | Client sees option cards; their selection is recorded in the audit trail |
| As Tim, I know a deposit is owed the moment the client accepts, and the new job appears in the job list | Deposit amount/instructions shown on acceptance confirmation; proposal status → accepted; job record created |

### 2.2 Josh — office coordinator

| Story | Acceptance |
|---|---|
| As Josh, I can look up any proposal by customer name or address | Search returns results within 1 s on the proposal list |
| As Josh, I can import our existing Knowify customer list and catalog via XLS upload | Upload runs, duplicates skipped/flagged, results summary shown |
| As Josh, I can manage proposal templates: upload a logo, set colors, edit T&C text, and preview the PDF result | Template editor in Admin → Quoting; PDF preview generated via Gotenberg |
| As Josh, I can see which proposals are overdue for a follow-up | Status board surfaces proposals sent > N days ago without a view or response |

### 2.3 Homeowner — proposal recipient

| Story | Acceptance |
|---|---|
| As a homeowner, I can open the proposal link on my phone without creating an account | Acceptance page renders without any login flow |
| As a homeowner, I can see the full proposal PDF and choose between the tiers Tim offered | PDF viewer embedded; tier/option cards visible before signing |
| As a homeowner, I can accept by typing my name and checking the electronic-consent box | Accept button disabled until consent checked and name field non-empty; signed PDF emailed within 60 s |
| As a homeowner, I cannot re-use the link after I have accepted | Revisiting the token URL after acceptance shows a terminal "already accepted" state |

---

## 3. Functional requirements

Requirements are numbered `Q-NNN`. Must / Should / Won't follow MoSCoW.

### 3.1 Customer & property management

**Q-001 (Must)** The system maintains a `customers` table (name, company, email, phone) with one or more associated `contacts` and one or more `properties`.

**Q-002 (Must)** Each `property` stores street address, city, state, zip, and a `code_zone` flag (`HVHZ` | `FBC`), defaulting to the branch default but overridable per property. An optional `knowify_customer_id` field survives migration.

**Q-003 (Must)** All customer, property, and proposal records are scoped to `tenant_id` and never cross tenant boundaries (RLS enforcement is Wave F4; ORM filter is applied from F3 day one per F0 discipline).

**Q-004 (Should)** A lightweight `leads` table captures source (web form, phone, referral) + status (new / contacted / quoted / converted / lost) and converts to a customer+property record on quote creation. A lead is a status flag, not a CRM — no pipeline views, no email sequences.

### 3.2 Proposal builder

**Q-010 (Must)** A user with the `quoting_create` permission can create a new proposal by: selecting or creating a customer, selecting or creating a property, and attaching a saved estimate (snapshot of the estimator output at that moment).

**Q-011 (Must)** The proposal stores a `quote_snapshot` JSONB field containing the full estimator output at creation time. The snapshot is immutable once the proposal is sent; editing after send creates a new version (see Q-040).

**Q-012 (Must)** The proposal builder allows selection of any active template owned by the tenant. At least one default template must exist for Perkins before F3 ships.

**Q-013 (Must)** The user can add a cover message (plain text or rich text, not HTML-injected into the PDF template) and a set of optional line-item notes visible on the proposal.

**Q-014 (Must)** A proposal can be saved as `draft` and returned to before sending. Draft proposals do not generate an accept token and cannot be opened by the client.

**Q-015 (Should)** The builder displays a PDF preview (rendered by Gotenberg) before the user sends.

### 3.3 Templates (Knowify gap #1)

**Q-020 (Must)** The tenant can maintain **multiple named templates**. There is no limit enforced in v1 beyond practical UI usability.

**Q-021 (Must)** Each template is edited entirely within the platform — no vendor IT contact required. The template editor (Admin → Quoting → Templates) exposes: tenant logo upload, primary/secondary color pickers, cover page text (rich text), body layout selection (line-item table style), Terms & Conditions text block (rich text, persisted separately as a reusable T&C entry), attachment list (uploaded PDFs appended after the main body), license number token (auto-inserted in footer).

**Q-022 (Must)** Template changes do not retroactively alter sent proposals; the `quote_snapshot` stores a rendered reference and the template version ID used.

**Q-023 (Must)** PDF rendering uses **Gotenberg** deployed on Cloud Run, called server-side over internal VPC. No client-side PDF generation. Gotenberg is IAM-locked (no public endpoint).

**Q-024 (Should)** The template editor shows a live preview (re-rendered on save, not on every keystroke) using a synthetic line-item fixture so the layout is visible without a real quote.

**Q-025 (Must)** A T&C library stores named, versioned T&C blocks (`tc_versions` table, created in TRD-F3 migration 0017) that can be reused across templates. The version used on a sent proposal is recorded in the audit trail.

### 3.4 Tiered & optional pricing (Knowify gap #2)

**Q-030 (Must)** A proposal can include a **good-better-best tier structure**: up to three named tiers (e.g., "Essential / Premium / Premium+ with 20-year warranty"), each with its own line-item set derived from the estimator. The builder populates tiers from distinct estimate snapshots or from manual line-item overrides.

**Q-031 (Must)** A proposal can include **optional add-on line items** (e.g., "Attic insulation upgrade +$1,200") that the client can individually include or exclude on the acceptance page.

**Q-032 (Must)** The client's tier selection and add-on choices are recorded in `proposal_events` with a timestamp. The accepted total is computed server-side from the snapshot + selections — never from a client-submitted price.

**Q-033 (Must)** A single-tier proposal with no optional items is fully supported and is the default flow. Tiers and options are additive, not mandatory.

**Q-034 (Should)** The acceptance page renders option cards clearly on mobile (single-column stacked layout, large tap targets). The selected tier is visually distinguished before the client proceeds to sign.

### 3.5 Revisioning (Knowify gap #3)

**Q-040 (Must)** If a user edits a proposal that is in `sent`, `viewed`, or `revision_requested` status, the system creates a **new proposal record** with `parent_id` pointing to the previous version and increments `version` (starting at 1).

**Q-041 (Must)** When a new version is created, the previous version's `accept_token` is invalidated immediately. A client who follows the old link sees a "This proposal has been updated" page with no quote details visible and a prompt to contact the contractor for the new link.

**Q-042 (Must)** The proposal detail view shows the full version chain (version number, created timestamp, status of each version). Users can view any historical version in read-only mode.

**Q-043 (Must)** Only the current (highest-version) proposal in a chain can transition to `accepted` or `declined`. Older versions are permanently `superseded`.

**Q-044 (Should)** When creating a revision, the builder pre-populates with the previous version's content so the user edits a diff, not a blank form.

### 3.6 E-sign lite — no-login accept page (Knowify parity + legal grounding)

**Q-050 (Must)** Each sent proposal generates a **single-use high-entropy accept token** (512-bit CSPRNG entropy, URL-safe base64: `secrets.token_bytes(64)` encoded as ~86-char urlsafe string). The token is embedded in the accept link sent to the client. Token generation is owned by TRD-F3.

**Q-051 (Must)** The accept page requires no login. It is served at a public route (e.g., `/p/{token}`) and displays the proposal PDF inline plus the tier/option selector (if applicable).

**Q-052 (Must)** Before the Accept button activates, the client must: (a) check a checkbox labeled "I consent to conduct this transaction by electronic means" (ESIGN/UETA consent requirement), and (b) type their full name in a text field (typed-name signature, attribution requirement).

**Q-053 (Must)** On submission, the server records a `proposal_event` of type `accepted` capturing: accepted_at (UTC), client IP address, User-Agent string, typed name, tier selected, options selected, T&C version ID. This is the legally significant audit record.

**Q-054 (Must)** Within 60 seconds of acceptance, the system emails a signed-PDF copy to the client's address on file. The PDF includes the signed name, acceptance timestamp, and selected options appended as a signature page. This satisfies ESIGN/UETA's record delivery requirement.

**Q-055 (Must)** The accept token is single-version: once a proposal is accepted, declined, or superseded, the token returns HTTP 200 with a terminal state page showing a clear human-readable message ("already accepted", "proposal updated — contact contractor for new link", etc.) — never 404, never 410. Tokens for unknown/non-existent proposals return HTTP 404 with a generic page indistinguishable from any other 404 on the domain (constant-time lookup to prevent timing oracle). The Q-052 consent/name step and Q-055 terminal-state response must both be consistent with this model.

**Q-056 (Should — F6 hard requirement before prod go-live)** The accept page endpoint will be rate-limited at the Cloudflare WAF layer (≤20 requests/minute per IP) as an F6 deliverable. **F3 interim protection:** 512-bit token entropy makes enumeration computationally infeasible; unknown tokens return 404-indistinguishable; the accept POST is a single-transaction operation (single-use token invalidated atomically). There is no effective cross-instance rate limit until F6. A Cloudflare WAF rate-limit rule covering the `/p/{token}` route is a hard requirement before any production go-live with a second tenant; it is not optional for Perkins prod either once public traffic is non-trivial.

**Q-057 (Should)** The accept page renders acceptably on a 375px-wide mobile viewport (iPhone SE minimum). Proposal PDF is viewable without horizontal scroll.

**Q-058 (Won't — v1)** Integration with a named e-sign provider (Dropbox Sign, SignWell, BoldSign). The data model and accept flow are designed so this integration can be added as a seam without re-architecting the proposal status model. A `esign_provider` nullable field on `proposals` marks the upgrade path.

### 3.7 Status tracking & automated follow-ups

**Q-060 (Must)** The `proposals` table carries a status enum: `draft` → `sent` → `viewed` → `accepted` | `declined` | `revision_requested` | `superseded`.

**Q-061 (Must)** `proposal_events` records every transition with type, timestamp, IP/UA (where applicable). Viewed events are recorded on first open of the accept page (server-side pixel, not client JS).

**Q-062 (Must)** The proposal list and detail views display current status with the most recent event timestamp. Users with `quoting_read` permission can see all proposals for their tenant.

**Q-063 (Must)** The contractor can manually mark a proposal `declined` or `revision_requested` (to record a phone/email conversation that didn't go through the accept link).

**Q-064 (Should)** Automated reminder nudges: if a sent proposal has not been viewed within N days (configurable in Admin → Quoting, default 3), an email reminder is sent to the client. If viewed but not accepted within M days (default 5), a second reminder is sent. Reminders stop on any terminal state.

**Q-065 (Should)** The proposal list has a "needs attention" filter: proposals in `sent` or `viewed` status beyond the reminder threshold, surfaced for Josh's daily workflow.

**Q-066 (Won't — v1)** SMS reminders, WhatsApp, or any channel other than email.

### 3.8 Deposit & job handoff

**Q-070 (Must)** Each tenant has a deposit policy configured in Admin → Quoting: type (`percentage` | `fixed`), amount (percent or dollar value), and payment instructions (free-text, e.g., "Check payable to Perkins Roofing" or "Zelle: 561-xxx-xxxx").

**Q-071 (Must)** On proposal acceptance, the system records: deposit amount due (computed from accepted total + policy), payment instructions, and due date (configurable, default acceptance date + 7 days).

**Q-072 (Must)** Acceptance triggers a job-handoff notification (in-app notification + email to the tenant's configured ops contact). The notification includes: customer name, property address, accepted total, deposit due, and a link to the proposal.

**Q-073 (Must)** A `jobs` stub record is created on acceptance, carrying: `proposal_id`, `customer_id`, `property_id`, `accepted_total`, `deposit_due`, `status = new`. The `jobs` stub table is included in TRD-F3 migration 0017 alongside `catalog_items` and `tc_versions`. Job management beyond this stub is out of scope for F3.

**Q-074 (Won't — v1)** Payment processing of any kind (Stripe, ACH, card). The deposit amount and instructions are informational only.

### 3.9 Knowify migration

**Q-080 (Must)** A one-time XLS import tool (CLI script, not a UI) ingests Knowify's customer export: maps name/company/email/phone/address to the `customers` and `properties` tables, records `knowify_customer_id` on each property for traceability, skips duplicates by email+address match, and produces a summary log (imported / skipped / errors).

**Q-081 (Must)** A one-time proposal archive script (CLI, not UI) accepts a directory of Knowify-exported proposal PDFs and uploads them to GCS under `tenants/{tenant_id}/knowify-archive/{customer_id}/{filename}`. No structured data is extracted — PDFs are stored verbatim for historical reference.

**Q-082 (Must)** The XLS import also ingests the Knowify price catalog (line item names + unit prices) into the `catalog_items` table (created in TRD-F3 migration 0017), so Josh doesn't have to re-enter standard line items manually. The `catalog_items` table is a Must-tier delivery in F3 regardless of whether the Knowify XLS import runs — it is also used for hand-entered line items.

**Q-083 (Won't — v1)** A live Knowify→platform sync or Zapier bridge. The migration is a one-time cutover. If Tim wants a brief overlap period, the Knowify "Contract Job created" Zapier trigger can send a webhook; this is a one-line addition but is not built unless requested.

### 3.10 Mobile requirement (acceptance criterion)

**Q-090 (Must)** The full owner-side flow — create customer, create/select property, choose estimate, select template, configure tiers/options, preview, send — must complete successfully in mobile Safari and Chrome on iOS (tested at 390px viewport, iPhone 14 form factor). This is an F3 acceptance criterion, not a nice-to-have.

**Q-091 (Must)** The accept page (homeowner-facing) must complete — view PDF, select tier/options, consent, type name, accept — in mobile Safari on iOS (390px). This is also an F3 acceptance criterion.

---

## 4. Acceptance criteria

The following must all be true before F3 is marked done and the SDA clock starts.

### 4.1 End-to-end smoke test (performed on preprod, on a real phone)

1. Tim logs in on an iPhone. Creates a customer + property. Selects an estimate from Wave F2.
2. Chooses a template. Adds a good-better-best tier structure.
3. Sends the proposal. The system transitions status to `sent`.
4. Opens the accept link in a private browser tab. Status transitions to `viewed`.
5. Selects a tier. Checks the consent box. Types a name. Clicks Accept.
6. Status transitions to `accepted`. Within 60 seconds: a signed PDF arrives in the client email inbox.
7. A job stub appears in the jobs list. Deposit amount and instructions are shown.
8. Revisiting the accept URL shows the terminal "already accepted" page.
9. Tim's proposal detail view shows the full event timeline: sent → viewed → accepted with timestamps and IP.

### 4.2 Version chain test

1. Create and send proposal v1. Send accept link to client.
2. Edit and resend → creates v2. v1 token returns "superseded" page.
3. Client accepts via v2 token. v1 token still returns "superseded." v2 token returns "already accepted."

### 4.3 Template test

1. Josh creates a second template with a different logo and T&C.
2. Creates a proposal using the new template. PDF preview shows new branding.
3. Edits the template. Sent proposals are unaffected.

### 4.4 SDA acceptance (post-smoke-test)

- **3 business days:** Tim and two named testers run real quotes on preprod. All flagged issues resolved.
- **14-day acceptance window:** No material defects remaining. Acceptance is deemed if Tim doesn't respond within 14 days (per SDA terms).

---

## 5. Non-goals (v1)

These are explicitly out of scope. Do not add them without a scope-change conversation.

- **Payment processing.** No Stripe, ACH, card capture. Deposit is informational.
- **Accounting / QuickBooks integration.** Tim's accounting backend is separate; no QBO sync.
- **CRM / ERP.** Leads is a status flag. No pipeline views, scoring, drip sequences, contact history.
- **Native iOS app.** The mobile requirement is mobile-web (Safari/Chrome). A native app is a future contract item.
- **Client portal.** Homeowners do not have accounts. They receive a one-time link. No "view all my proposals" portal.
- **Named e-sign provider.** Built-lite tokenized accept is sufficient for B2C roofing under ESIGN/UETA. Seam exists for upgrade.
- **Knowify live sync / Zapier bridge.** Migration is one-time cutover.
- **SMS / WhatsApp reminders.** Email only in v1.

---

## 6. Differentiators vs Knowify — explicit comparison

| Feature | Knowify (Core/Advanced) | This platform |
|---|---|---|
| **Multiple proposal templates** | One template; changes require emailing Knowify IT | Unlimited self-serve templates, edited entirely in Admin |
| **Proposal revisioning** | No version history; no revision flow | Full version chain; old link shows "superseded"; chain preserved |
| **Tiered / optional pricing** | No — one fixed price per proposal | Good-better-best + optional add-ons, client-selectable at accept |
| **Mobile owner sales flow** | Mobile app is field-tracking only; can't create/send proposals | Full create/send/track flow in mobile browser |
| **Automated follow-up reminders** | Not available | Configurable multi-stage email reminders |
| **E-sign** | esign.knowify.com (in-house, no client login) | Tokenized no-login accept page + audit trail + emailed signed PDF |
| **Real-time status tracking** | Sent / viewed / signed visible | Same, plus manual override (declined / revision_requested) |
| **Deposit on acceptance** | Auto-generates deposit invoice | Records deposit due + instructions; no processing |
| **Proposal → job conversion** | Accept → active job | Accept → job stub + ops notification |
| **Client portal** | Advanced tier only (~$329–399/mo) | Not in v1 (non-goal) |
| **Price** | $99–399/mo + per-user | Included in platform license |
| **API / data portability** | No proposal API; PDF export only | Full structured data in PostgreSQL; GCS archive |

---

## 7. Multi-tenant considerations

The Quoting module is tenant-scoped from the first migration. Every table carries `tenant_id` with an ORM base-query filter (F3) upgraded to PostgreSQL RLS (F4, before any second tenant is onboarded).

**Template isolation:** Each tenant's templates are fully isolated. Perkins' logo, T&C, and brand colors are never visible to another tenant. Template IDs are opaque UUIDs; enumeration is not useful without a valid auth session.

**Accept tokens:** High-entropy tokens carry no tenant signal. The server resolves tenant from the proposal record, not from the URL. A valid token for one tenant cannot be used to probe another tenant's proposals.

**Deposit policy:** Per-tenant. Perkins' deposit % is not inherited by any other tenant.

**Knowify migration tooling:** The CLI scripts are tenant-parameterized (`--tenant-id`). They will work for any future tenant that migrates off Knowify. Running them against the wrong tenant_id is prevented by the ORM filter.

**Gotenberg:** Shared service (one Cloud Run deployment). Template rendering is stateless; no tenant data persists in Gotenberg beyond the HTTP request/response cycle. No cross-tenant data leakage risk.

**Accept-page rate limiting:** Cloudflare WAF rate limiting is an F6 deliverable. F3 interim protection is 512-bit token entropy + 404-indistinguishable unknown tokens + single-transaction atomic accept (no effective cross-instance rate limit until F6). A WAF rate-limit rule on `/p/{token}` is a hard requirement before prod go-live. When future tenants use separate custom domains, the same WAF ruleset must be applied to each (F6 scope).

---

## 8. Data model (reference — detail in TRD-F3)

This section names the entities; column-level specs and migration SQL live in TRD-F3.

| Entity | Key fields | Notes |
|---|---|---|
| `customers` | id, tenant_id, name, company, email, phone, knowify_customer_id | Email unique within tenant |
| `contacts` | id, tenant_id, customer_id, name, role, email, phone | Multiple per customer |
| `properties` | id, tenant_id, customer_id, address, city, state, zip, code_zone, knowify_customer_id | code_zone per-property, overridable |
| `proposal_templates` | id, tenant_id, name, logo_gcs_path, colors JSONB, cover_text, body_layout, tc_version_id, is_active | Soft-delete via is_active |
| `tc_versions` | id, tenant_id, name, content_html, created_at | Append-only; never edited in place |
| `proposals` | id, tenant_id, customer_id, property_id, template_id, tc_version_id, quote_snapshot JSONB, version, parent_id, status, accept_token, tier_config JSONB, option_config JSONB, deposit_policy_snapshot JSONB, esign_provider (nullable), created_by, sent_at, accepted_at | parent_id → self for version chain |
| `proposal_events` | id, proposal_id, type, occurred_at, ip_address, user_agent, actor_id (nullable), metadata JSONB | Append-only audit log |
| `leads` | id, tenant_id, source, status, contact_name, contact_email, contact_phone, notes, converted_proposal_id, created_at | Status field only — not a CRM |
| `jobs` | id, tenant_id, proposal_id, customer_id, property_id, accepted_total, deposit_due, due_date, status, created_at | Stub only in F3 |
| `catalog_items` | id, tenant_id, name, unit, unit_price, category, knowify_item_id | From Knowify import; also hand-entered |

---

## 9. Dependencies & open items

| # | Item | Owner | Blocks |
|---|---|---|---|
| **#322** | Knowify admin access for Josh / Jon (john@perkinsroofing.net) | Josh | Q-080, Q-081, Q-082 |
| **#323** | Knowify XLS export: customer list + price catalog | Josh/Tim | Q-080, Q-082 |
| **#324** | Knowify historical proposal PDFs exported (PDF-by-PDF; no API) | Josh | Q-081 |
| **TBD** | Tim's T&C text + deposit policy + license number + a past proposal to match | Tim | Q-021, Q-070 (template seeding, not build gate) |
| **TBD** | Golden-file estimates (5 Exhibit-C quotes) from Wave F2 | Tim/Josh | F2 gate (not F3 gate, but F3 demo quality) |
| **⚠️ #OI-6** | Ez-Bids LLC entity / IP / branding decision — which entity owns the quoting module, and does "Ez-Bids" remain the brand? | Jon + counsel | Commercial; not a build blocker but must resolve before any tenant #2 onboarding or external marketing of the quoting feature |
| **TBD** | Cloudflare WAF token for accept-page rate-limit rule | Jon | Q-056 (F6 hard dependency — hard requirement before prod go-live) |
| **TBD** | Client email sender config for signed-PDF delivery via Resend (`adapters/resend.py`); from-domain verification for `perkinsroofing.net` is a deployment prerequisite | Jon/DeGenito | Q-054 |

---

## 10. Security notes (not exhaustive — full review in Wave F4/F6)

- Accept tokens are generated server-side with `secrets.token_bytes(64)` encoded as a ~86-char URL-safe base64 string (512-bit entropy). Never generated client-side. Token generation mechanism is owned by TRD-F3.
- Accept-page endpoints accept only GET (view) and POST (submit). No PUT/PATCH/DELETE on public routes.
- The signed-PDF email is sent to the address stored in `customers.email` at the time of acceptance — not to an address supplied in the POST body. Email is delivered via Resend (`adapters/resend.py`).
- IP and UA are logged for audit, not for blocking. They are stored in `proposal_events`, not in a separate analytics system.
- Gotenberg is called only from the API service's VPC service account; it has no public Cloud Run ingress URL.
- The `accept_token` column has a unique index. Collision probability at 512-bit entropy with realistic proposal volumes is negligible (birthday bound >> 10^76 proposals).
- F3 interim accept-page protection relies on 512-bit token entropy + 404-indistinguishable unknown tokens + single-transaction atomic accept. App-level `SingleFlightGuard` is in-process only and does not protect across multiple Cloud Run instances. Cloudflare WAF rate limiting (Q-056) is required before prod go-live.

---

## 11. Slip rule (schedule protection)

If the ~3-week commercial clock is under pressure, the following cuts are pre-approved in order:

1. **Cut first:** Automated reminder nudges (Q-064, Q-065) — Josh can send manual follow-ups.
2. **Cut second:** Lightweight leads tracker (Q-004) — customers + properties suffice.
3. **Cut third:** T&C library versioning UI (Q-025) — T&C as free text in template suffices.
4. **Never cut:** Templates (Q-020–Q-024), Revisioning (Q-040–Q-044), Tiered/optional pricing (Q-030–Q-034), E-sign lite (Q-050–Q-057), Deposit + handoff (Q-070–Q-073), Mobile requirement (Q-090–Q-091).

The four differentiators (templates / revisions / tiers / e-sign) are the commercial reason to build this instead of keeping Knowify.
