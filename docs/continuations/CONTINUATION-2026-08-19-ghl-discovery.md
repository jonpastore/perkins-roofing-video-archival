# Continuation — 2026-08-19: Product discovery and GHL integration mapping

## Scope and guardrails

- This work is still **discovery only**. No production application code or GHL configuration was changed.
- The current product-review workflow must stop before redesign, prototypes, or implementation unless the owner explicitly approves the next phase.
- Browser-created artifacts currently remain untracked under `.playwright-cli/` and `output/`; preserve or remove them deliberately rather than including them unintentionally in a commit.

## Product direction established with the owner

The repository began as video archival/content intelligence and has grown into Perkins' intended operating system for repeatable growth:

1. Generate demand: public site, SEO/AIO, social, paid media, Maps, and content.
2. Capture and automate lead lifecycle: GHL, CallRail attribution, and scheduling.
3. Convert revenue: customers, estimating, proposals, signing, invoicing, and payments in this app.
4. Hand off signed/paid work to external project-management software; project execution is explicitly out of scope for this repository for now.
5. Provide branch-level operating visibility and corporate accountability; ultimately support geographically isolated franchise tenants.

The primary branch-dashboard objective is **at-risk revenue**, especially:

- leads not contacted within the expected SLA;
- appointments missed or not dispositioned;
- completed appointments lacking estimates/proposals;
- proposals stalled before signature;
- signed work missing a deposit/payment or external handoff.

Branch managers own the operational queue. Tim owns company-level performance and brand/revenue accountability. Chris currently needs the same cross-branch operational access as Tim while advising on processes.

## Owner decisions

- GHL owns lead workflow automation, contacts/opportunities, calendars, appointment lifecycle, and nurture.
- CallRail is attribution input to the app, not the workflow authority.
- This app owns customer/project commercial records, estimates, proposals, signing state, invoices, payments, knowledge, and routing/control-plane behavior.
- The public site should send leads to GHL. A dedicated `sign.perkinsroofing.net` public surface is the intended proposal/e-signature route.
- The desired UX is lifecycle/funnel based rather than a collection of functional modules.
- The app should automate extensively, but public/reputation, legal, financial, and contract actions need stricter controls than a confidence score alone.
- Existing Perkins branches are organizational scopes. Future franchisees should be separate tenants with isolated data and optional explicit lead delivery to their GHL sub-account.
- Branches are geographically segmented and return a percentage of revenue to Tim/corporate.

## Product direction evidence

Read during discovery:

- `DeGenito-Perkins-Partnership-Proposal-2026-08.pdf` (Aug 17): positions the public site, app, GHL, CallRail, AI attendant, and marketing stack as one integrated operating system.
- `DeGenito-Perkins-Marketing-Management-2026-08.pdf` (Aug 19): defines the weekly/Friday operating view around spend, shown appointments, cost per show, seasonal caps, branch growth gates, and company-scale accountability.

## Current repository discovery findings

- React/Vite/TypeScript SPA with FastAPI/SQLAlchemy backend and Firebase authentication.
- Internal navigation is role-specific in-memory tab state; only public proposal URLs are path-addressable.
- `apiFetch` centralizes Firebase bearer token attachment and 401 refresh retry, but many page components still make inline endpoint calls, creating a mixed API-access layer.
- No normal CRUD flow was found to explicitly full-page reload. OAuth handoffs intentionally use `window.location.href`; error recovery includes an explicit reload button.
- The visual system is fragmented: shared UI primitives/tokens exist in `web/src/ui.tsx`, but CSS tokens and JavaScript constants coexist and page code has extensive inline styles.
- Browser validation was limited to unauthenticated login and an invalid public-proposal route because no Firebase user was available. Authenticated app behavior, full responsive behavior, and most UI states are still unverified.
- Security discovery found server-side role/tenant mechanisms, RLS-oriented sessions, CORS controls, and OAuth state handling. Key open concerns include concurrent public-proposal state transitions, upload resource pressure, and deployment-level verification of proxy/rate-limit/RLS controls.

## GHL discovery: read-only browser evidence

Accessed the DeGenito Innovations agency account and switched to the **Perkins Roofing — Jupiter, FL** sub-account. The visible browser was closed and the headless browser session was also closed after review.

Agency structure:

- 8 active sub-accounts were listed.
- Separate active sub-accounts exist for **Perkins Roofing** (Jupiter) and **Perkins Roofing — Miami**.

Jupiter GHL setup:

- Pipeline: **Roofing Leads**.
- Visible pipeline stages:
  `New Lead` → `Contacted / In Conversation` → `Inspection Booked` → `Inspection Complete / Quoted` → `Won` → `Lost / Nurture`.
- The account dashboard showed no currently visible opportunities under its current filters; do not infer that this is a full data count without checking filters/time range.
- Published workflows visible in the first list page:
  1. `01. FB Lead - Speed to Lead & Nurture`
  2. `02. Appointment - Confirmation & Reminders`
  3. `03. Appointment Cancelled - Recovery`
  4. `04. Review Request - Won Jobs`
  5. `05. Long-Term Nurture`
  6. `06. Stale Lead Alert`
  7. `07. No-Show Recovery`
  8. `08. Quote Follow-Up`
  9. `09. Uncalled Lead Escalation - 30 Min`
  10. `10. Post-Job - Referral & Annual Check-Up`

## Recommended integration contract (not implemented)

| Business event | Authority | Required integration behavior |
| --- | --- | --- |
| Web/call/social lead | GHL | App mirrors canonical GHL contact/opportunity IDs plus attribution. |
| Appointment booked/cancelled/no-show | GHL | App receives status for branch dashboard and revenue-risk escalation. |
| Estimate/proposal created or sent | App | Upsert GHL opportunity data and set/retain the appropriate quoted state. |
| Proposal signed | App | Update GHL to `Won`, retain signed date/value, and emit an auditable event. |
| Deposit/payment received | App | Update GHL financial-status fields/tags and record handoff readiness. |
| Project-management handoff | App | Record a terminal handoff event only; do not synchronize project execution yet. |

Before implementation, produce a versioned integration contract specifying:

- GHL custom fields/tags and their data types;
- inbound/outbound event mapping, direction, and authority;
- GHL contact, opportunity, calendar, pipeline, and app IDs;
- idempotency keys, retries, reconciliation, and duplicate/conflict rules;
- branch/sub-account resolution;
- audit events and failure/alert behavior;
- the precise branch-manager and Tim escalation SLAs.

## RBAC direction to carry forward

- Platform admin: infrastructure/support across tenants.
- Company executive: all Perkins branches and company roll-ups (Tim).
- Cross-branch operations: all Perkins operational data (Chris during the current process-improvement phase).
- Branch operator: only assigned branch operations, commercial records, and dashboard.
- Marketing operator: marketing/content tools with only the branch context required for execution.
- Franchise admin: strictly isolated tenant/sub-account; no corporate or other-franchise visibility.
- Public recipient: narrowly scoped, high-entropy signing link only.

Require server-enforced roles/scopes, tenant/branch checks, and audit logging; the owner reports that users are effectively admins today.

## Credential/session note

- 1Password item used: `Go High Level - DeGenito Innovations, LLC` in the personal-account `DeGenito Innovations` vault. Do not record its values in this repository.
- A password was inadvertently echoed in an automation CLI trace during the first headed login attempt. The owner was informed. Rotate the GHL password and update the 1Password item before reusing the account.
- Subsequent credential/OTP entry suppressed command output. No GHL records, workflows, settings, messages, or other data were changed.

## Suggested next session

1. Update the `ui-ux-product-review` skill as the owner requested, preserving its discovery-only approval gate.
2. Resume product interview only for unresolved operational decisions:
   - exact response/booking/no-show/proposal/deposit SLAs;
   - what counts as revenue-share eligible revenue and settlement timing;
   - precise branch versus corporate visibility after Chris' temporary broad access;
   - public automation policy and human-approval exceptions.
3. Create a feature spec and requirements set for `ghl-lifecycle-integration` before implementing or requesting an API key.
4. Perform a dedicated, read-only GHL technical mapping after credential rotation: detailed workflow triggers/actions, calendars, custom fields/tags, users, pipeline settings, and API/webhook capabilities.

