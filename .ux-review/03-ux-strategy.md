# UX strategy — Perkins Roofing operating platform

Status: COMPLETE
Phase: UX architecture and design strategy
Last Updated: 2026-08-20
Inputs Used: `.ux-review/01-discovery.md`; `.ux-review/02-product-interview.md`; current `ui-ux-product-review` strategy, information-architecture, design-system, accessibility, responsive, interaction, form-feedback, and security guidance
Open Questions: Authenticated production UI remains unrendered; exact integration mappings remain implementation discovery
Blocking Findings: None for isolated prototype work
Next Recommended Phase: Design directions and representative mock-data prototype

## Executive assessment

Perkins should evolve from a set of functional modules into a branch-scoped revenue operating system. The primary experience is not a generic dashboard: it is a role-aware view of the next revenue-risk action, backed by a coherent lifecycle and a customer/property record. Corporate needs portfolio oversight and intervention without making branch users navigate corporate marketing or other branches' data.

The strategy is **action first, lifecycle backed, record grounded**:

```text
Events from web, Facebook, GHL and the app
                    ↓
Canonical customer / contact / property record + lifecycle projection
                    ↓
Role- and branch-scoped risk queue, pipeline and reporting
                    ↓
Human action, accountable escalation, async event reconciliation
```

This explicitly avoids treating a dashboard number, a GHL tag, or a manually moved card as the complete operating truth.

## Product principles

1. Protect revenue before displaying vanity metrics. Every home view begins with owned, time-bound work.
2. Keep branch users in their branch and corporate users in a portfolio view. Scope is an authorization boundary, not a filter convention.
3. Make exceptions actionable. A risk item always shows why it matters, who owns it, the deadline, the most useful next action, and activity history.
4. Organize the product around the customer/property and lifecycle, not around vendor systems or internal databases.
5. Preserve specialist ownership: GHL runs communication, calendar and opportunity automation; the app owns customer/contact/property, estimates, proposals, payment facts and operating visibility. CallRail is not approved and is outside the current scope.
6. Give phones decisive field work, not shrunken administration. Laptop remains the primary surface for dense reporting, configuration and bulk operations.
7. Automation creates or updates a visible work state; it does not conceal the absence of human follow-up.

## Information architecture

### Global shell

Use a persistent desktop sidebar and a compact mobile bottom/action navigation. Retain the existing Perkins Roofing logo as the brand anchor; do not replace it with a new mark. The top bar contains the active branch/scope, global search, sync/notification health, and user menu. Scope switching appears only for users who hold authorized cross-branch grants; it must never expose data before server authorization succeeds.

### Role-aware navigation

| Area                | Salesperson / estimator                 | Sales or branch manager             | Corporate / authorized cross-branch                                                               |
| ------------------- | --------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------- |
| Today               | Personal owned work                     | Branch risk + team follow-up        | Portfolio exceptions + branch comparison                                                          |
| Pipeline            | Assigned/branch lifecycle               | Branch lifecycle and capacity       | Cross-branch comparison and drill-down                                                            |
| Customers           | Customer/contact/property workspace     | Same, branch-scoped                 | Authorized branch/customer access                                                                 |
| Sales work          | Estimates, proposals, payments          | Same + approval context             | Authorized review and financial oversight                                                         |
| Schedule            | GHL calendar context                    | Branch calendar context             | Portfolio capacity, not all appointment detail by default                                         |
| Knowledge           | FAQs and approved operational knowledge | Same                                | Knowledge and content/marketing workspace where authorized                                        |
| Reports             | Personal/branch-relevant outcomes       | Team and branch outcomes            | Revenue, royalty, branch and brand outcomes                                                       |
| Content Operations  | Hidden                                  | Hidden unless separately authorized | Content production/approval/navigation only for authorized content roles                          |
| Product Admin       | Hidden                                  | Limited settings where granted      | Branches, users, pricing and product configuration                                                |
| Platform Operations | Hidden                                  | Hidden                              | Integrations, readiness, diagnostics, raw logs and privileged remediation only for Platform Admin |

Platform Operations is separate from Corporate reporting: **Corporate** sees authorized portfolio/finance performance; **Product Admin** manages branches, users, pricing and product configuration; **Platform Admin** additionally controls integrations, readiness, diagnostics, raw logs, tenant/SSO and privileged remediations. Navigation may reflect these distinctions, but every visibility and action decision remains server-authorized.

`Today` replaces a generic dashboard as the default entry. `Pipeline` remains a secondary lifecycle view rather than the sole place where work is discovered. Marketing/content remains a separately authorized workspace, absent from normal branch operations.

### Core object hierarchy

```text
Tenant
  └─ Canonical Person
       └─ Branch-scoped operational relationship (household/account context)
            ├─ Contact aliases and consent/source facts
            ├─ Property / properties
            └─ Opportunities / sales lifecycle
                 ├─ Communication and appointment events (GHL)
                 ├─ Estimate / quote / proposal
                 ├─ Acceptance and deposit/payment facts
                 └─ Risk, ownership, escalation and integration events
```

The customer/property record must distinguish the canonical Person from the currently authorized branch operational relationship. A cross-branch association is an authorized, audited link—not an automatic merge or an invitation to reveal other branch data. The record is a drill-down destination, not the primary way to discover urgent work.

## Workflow simplification

### Revenue lifecycle and exception model

```text
Captured
  → Assigned
  → Human attempted
  → Connected
  → Inspection booked
  → Inspection complete / quoted
  → Proposal sent
  → Accepted — payment pending
  → Deposit received / won
  → Project-system handoff

Terminal: Lost | Disqualified
           └─ required reason + optional note
```

Lifecycle, human-activity and risk are distinct state dimensions. For example, an opportunity can be `Proposal sent`, `Connected`, and `At risk: no response` at the same time. This prevents one overloaded pipeline status from carrying all business meaning.

### Default risk order

1. Accepted — payment pending
2. New lead with no verified human attempt
3. Appointment cancelled or no-show
4. Proposal sent with no response
5. Contacted but not booked
6. Long-term nurture

Every risk item has an owner, branch, due time, escalation state and prescribed next action. Business-hours defaults are: first human attempt within five minutes; reminders every 15 minutes; reassignment or sales-manager escalation at 60 minutes; after-hours clock begins at next branch opening. Corporate controls permitted ranges; branches configure values within them, with an audit trail.

### Human-activity semantics

- Automated SMS/email never satisfies the human-response SLA.
- Automated customer messages display the approved sender `Perkins Roofing – <Branch> Team`, falling back to `Perkins Roofing Team` when branch identity is unavailable or inappropriate; the event retains template/sender provenance. Human outreach is recorded separately and does not impersonate an automated team sender.
- A verified outbound call, personal SMS/email, or logged equivalent outreach marks `Attempted`.
- A two-way conversation marks `Connected`.
- A free-form note alone does not clear an at-risk state unless it contains a structured outreach event.
- Action logging uses async submission, duplicate protection and a visible sync result; the client never assumes the stage/event was accepted until the server confirms it.

### Integration and failure UX

The app should expose integration state at the affected record/work item: `Synced`, `Pending`, `Retrying`, `Needs review`, or `Failed`. A failed GHL stage update, duplicate webhook, delayed payment confirmation or contact-identity conflict must create a recoverable exception rather than silently diverging. Contact changes add or match unambiguous values; conflicting identity changes never silently overwrite or remove existing contact data.

### GHL tenancy and credential boundary

The approved target is one corporate GHL account/location for Tim and one GHL account/location for every branch. The existing marketing account is the intended corporate starting point, subject to a read-only workflow/data verification before any migration, rename or configuration change. The corporate connection supports corporate marketing and authorized cross-branch automation; a branch connection supports only that branch's calendar, communications and lifecycle workflow.

The application must model this as server-side `IntegrationConnection` records scoped to either `corporate` or exactly one branch. Configuration may reveal connection name, scope, lifecycle/health state, last successful event and authorized remediation. It must never expose, store in browser state, log, or return raw API keys. Credential material belongs in the server's secret store/references, and every webhook/API operation must derive the permitted branch/corporate connection server-side. CallRail is not an approved dependency and receives no target design or credential model.

## Design-system strategy

### Current state

FACT: the implementation has useful shared primitives but a fragmented implicit system: CSS and JavaScript token sources differ, and pages use extensive inline styling. The smallest useful next step is a semantic foundation and a short set of shared operational patterns—not a new standalone design-system project.

### Semantic foundations

| Foundation       | Strategy                                                                                                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Color            | Separate Perkins brand from semantic risk. Define surface/text/border/action plus success/warning/danger/info and lifecycle-status tokens. Never rely on red or green alone to communicate state. |
| Type             | Replace the oversized global display scale with an operational hierarchy: page title, section title, card label, body, metadata, numeric metric. Favor legibility over marketing hero treatment.  |
| Space            | One compact-but-breathable scale used in shell, list rows, panels, forms and mobile task cards.                                                                                                   |
| Elevation/radius | Two surface elevations and a small radius scale; avoid rounded-card accumulation and unnecessary shadow hierarchy.                                                                                |
| States           | Shared pending, empty, error, success, disabled, focus-visible, selected, destructive-confirmation and sync-state patterns.                                                                       |
| Breakpoints      | Explicit compact/mobile, tablet, laptop and desktop behavior. Layout priority changes at breakpoints; it is not merely a smaller desktop.                                                         |

### Reusable patterns

Prioritize a composable application shell, scope switcher, risk item, lifecycle badge, activity timeline, customer/property summary, action drawer, record side panel, async feedback region, status/filter bar, data table/card-list adapter, empty state and destructive-confirmation dialog. Do not create an over-configured universal card or form component.

## Accessibility, responsive and performance strategy

- Use semantic buttons/links, labeled inputs, headings and landmarks; preserve a visible focus indicator and a keyboard-operable, non-hover-only action model.
- Announce async activity logging, risk reassignment and integration failure/success without depending only on visual color.
- Desktop/laptop uses a persistent sidebar, visible filters and dense but scanable rows. Tables maintain appropriate horizontal access or transform to prioritized cards where comparison no longer fits.
- Phone shows the assigned work queue, customer/property context, immediate communication actions, appointment status, notes/attempt capture, estimate/media capture and proposal/payment-link actions. It does not force dense reports, bulk operations or policy configuration into a narrow view.
- Render pending, success, empty, validation, unauthorized, sync-failure and long-content states intentionally. Do not use reloads or navigation resets to reconcile activity.
- Keep the first meaningful risk queue and record context fast; defer nonessential charts and load historical activity progressively.

## Security and authorization implications

- Server-side authorization must validate branch scope, cross-branch grants, customer/property ownership and transition permissions on every action. Client scope switchers are presentation only.
- The server validates allowed lifecycle transitions, required `Lost`/`Disqualified` reasons, branch deposit requirements and payment/handoff prerequisites.
- Integration events require idempotency keys, source/event identifiers and conditional state transitions to defend against duplicates and out-of-order delivery.
- Payment, proposal acceptance, handoff and reassignment actions expose clear pending/result states and prevent duplicate submission. The existing public-proposal concurrency finding remains a production implementation blocker, not something the prototype claims to solve.
- A proposal can reach `Won`/handoff only through a server-owned conditional state machine after the branch-required deposit is verified by its payment-provider event. Persist provider identifiers in an idempotency ledger and publish downstream handoff through a transactional outbox; no client, GHL workflow or payment link may infer this transition.
- Human activity is append-only, actor/timestamped and idempotent. The UI distinguishes app-confirmed activity from `GHL sync pending`, retains the prescribed follow-up, and exposes retry/review rather than treating a local click as SLA reconciliation.
- Every queue, aggregate, drill-down, reassignment, activity, payment and export query derives scope server-side. Corporate starts from aggregate/exception context; cross-branch PII drill-down is grant-checked and audited.
- Sync state is per event/record, with source, correlation identifier, last-confirmed time and a monotonic lifecycle version. Conflicting external identity data produces an authorized review item and never silently overwrites a contact.
- Price-changing estimate work is lifecycle-aware: a pre-proposal estimate can produce a draft proposal after required measurement confirmation; a signed proposal requires an explicit revision/change-order path with version lineage and consent. A client cannot reinterpret an accepted agreement as an editable draft.

## Priorities

| Priority | Problem                                                                                                     | Recommendation                                                                                                       |
| -------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| P0       | Revenue leaks are obscured by a generic, broad application structure and weak human-accountability signals. | Establish the role-aware Today/risk queue and human-activity model.                                                  |
| P0       | Current lifecycle cannot distinguish proposal/payment risk or terminal reasons.                             | Add explicit lifecycle projections and structured loss/disqualification reasons; synchronize GHL via durable events. |
| P0       | Effective all-admin access conflicts with branch isolation.                                                 | Server-enforced branch scope and reviewable cross-branch/capability grants.                                          |
| P1       | Fragmented styling makes consistent operational redesign costly.                                            | Introduce semantic tokens plus shared shell, states and task/record patterns.                                        |
| P1       | Mobile is unsuitable for dense pages yet field work is mobile-relevant.                                     | Build task-focused mobile capability parity for urgent sales workflows.                                              |
| P2       | Marketing/content breadth competes with branch focus.                                                       | Separate marketing/content workspace by authorization and navigation context.                                        |

## Non-goals for this direction

- Replacing GHL, CompanyCam or the post-sale project-management system; or introducing CallRail before it is approved.
- Delivering a pixel-identical phone version of every laptop page.
- Building a large cross-platform design-system repository.
- Changing production UI, API behavior, GHL configuration or access controls in this phase.
