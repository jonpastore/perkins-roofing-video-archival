# Design directions — Perkins Roofing operating platform

Status: COMPLETE
Phase: UX architecture and design directions
Last Updated: 2026-08-19
Inputs Used: `.ux-review/01-discovery.md`; `.ux-review/02-product-interview.md`; `.ux-review/03-ux-strategy.md`
Open Questions: Tim's final automated sender-identity policy; authenticated legacy UI remains unrendered
Blocking Findings: None for prototype construction
Next Recommended Phase: Build and render the recommended isolated prototype

## Shared design constraints

All directions use the same server-enforced branch/capability scope, lifecycle and risk semantics, async feedback, accessible keyboard operation, desktop/laptop-primary data density and focused phone capabilities. They differ in the mental model used to organize daily work.

## Capability preservation rule

**Existing production capabilities are preserved by default.** The representative command-center prototype is a design-direction proof, not a complete replacement inventory. A capability may move, consolidate, or receive a better hierarchy, but it may not silently disappear. Removal, deprecation, material reduction, or behavioral change requires an explicit entry in `.ux-review/feature-capability-parity.md` and product-owner approval.

## Direction A — Revenue command center (recommended)

**Mental model:** “What revenue needs a human decision from me now?”

- Default entry is a prioritized, role-aware work queue; managers see team/branch risk and corporate sees portfolio exceptions.
- Each row combines customer/property, risk reason, owner, deadline, latest human activity and one primary action.
- A compact, filterable lifecycle summary provides context without displacing the work list.
- A record side panel preserves context while logging an attempt, sending/opening GHL communication, reassigning work or reviewing proposal/payment status.
- Phone becomes a focused queue and action flow with one-tap contact, attempt logging and escalation visibility.

**Strengths:** directly serves the stated revenue priority; makes accountability and SLA visible; works for multi-hat users; has a clear role-aware home; avoids an empty dashboard.

**Tradeoffs:** needs precise risk ranking and event reliability; a poor row design could become too dense; managers still need an intentional way to inspect pipeline/capacity rather than only a queue.

**Visual character:** restrained operational surface, crisp hierarchy, modest Perkins brand accent, status color used sparingly and always paired with language/iconography.

## Direction B — Lifecycle pipeline cockpit

**Mental model:** “Where is work accumulating in the funnel?”

- Default entry is a columnar lifecycle/pipeline view with risk badges, capacity summaries and handoff milestones.
- Work actions happen from cards and a detail drawer; managers can visually identify conversion drop-offs and bottlenecks.
- Phone starts at a simplified current-stage list rather than showing the full board.

**Strengths:** strong shared vocabulary for sales and managers; visually explains the business funnel; supports pipeline coaching and branch-capacity discussion.

**Tradeoffs:** pipeline columns become hard to scan on laptops with rich data and poor on phones; urgency can be hidden among many cards; encourages manual stage movement unless event-driven controls are strong.

**Visual character:** measured color bands and clear stage progression; less dashboard-like than kanban-heavy CRM products.

## Direction C — Customer/property operating workspace

**Mental model:** “Every task is part of a customer and property relationship.”

- Default entry favors customer search/recent records, with a comprehensive record timeline and work checklist.
- The record panel becomes the central workspace for contacts, properties, appointments, proposals, payment and communication.
- Managers use saved record filters and an exception list layered around the workspace.

**Strengths:** cleanly supports multiple contacts/properties and identity-conflict handling; reduces duplicate entry; excellent for estimators working one job deeply.

**Tradeoffs:** weak as the default operating view for a branch with unattended risk; requires an additional task-discovery layer; makes corporate comparison less immediate.

**Visual character:** calmer and more relationship-oriented, with progressive disclosure and fewer simultaneous metrics.

## Comparison

| Criterion | A: Command center | B: Pipeline cockpit | C: Customer workspace |
| --- | --- | --- | --- |
| Recover revenue quickly | Strong | Moderate | Moderate |
| Salesperson phone utility | Strong | Moderate | Strong once in record |
| Manager accountability | Strong | Strong | Moderate |
| Customer/contact complexity | Moderate | Moderate | Strong |
| Corporate branch comparison | Strong | Strong | Moderate |
| Risk of generic CRM behavior | Low | Medium | Medium |
| Fit to owner priorities | Strongest | Strong | Supporting surface |

## Recommendation

Adopt **Direction A as the primary shell**, using Direction B as the `Pipeline` view and Direction C as the customer/property record workspace. This is not a compromise of three competing home pages: it assigns each mental model to the task it best supports.

```text
Today / Revenue risk  → Direction A
Pipeline and branch capacity → Direction B
Customer, contacts and property details → Direction C
```

This preserves a simple navigation model while avoiding the false choice between operational urgency, funnel visibility and customer context.

## Prototype decision

Prototype the recommended Direction A across three representative contexts:

1. Branch-manager laptop Today view: risk queue, SLA, filters, branch performance context and record/action panel.
2. Salesperson phone Today view: immediate prioritized tasks, customer/property context, contact action and human-attempt logging.
3. Corporate portfolio view: branch comparison with an exception drill-down, without exposing unneeded operational controls.

Include dense, empty, loading, integration-error and long-content states. Prototype uses static mock data only.

## Final decision package

**Decision status:** updated pending review of the feature/capability preservation matrix. Do not approve from the command-center prototype alone.

### What the prototypes demonstrate

- The original Perkins logo retained unchanged; a role-aware, branch-scoped revenue-risk Today experience; phone-first contact/outcome flow; corporate exception drill-down; async, identity-conflict and integration feedback states.
- An Estimate workspace that keeps customer/property, multiple-contact context, measurements, provenance, pricing version, complex pricing data and explicit proposal creation together without crowding Today.
- A restricted Platform Operations workspace for readiness gates, per-integration status, remediations, processing failures, audit history, diagnostics and usage/cost context.

### What is intentionally not yet prototyped

The prototype does not reproduce every full CRUD, table, filter, report, content-production, public-signing, configuration or administration screen. Those capabilities are mapped—rather than inferred removed—in [the feature/capability preservation matrix](feature-capability-parity.md). They retain their current behavior by default and will adopt shared target patterns during approved implementation planning.

### Preservation outcome

- **Preserved:** all existing source-evidenced capabilities, including content operations, video/archive workflows, public proposal acceptance, customer/contact/property CRUD, estimating, invoices/payments, reports, integration diagnostics, readiness, admin configuration, access management and audit/log capabilities.
- **Relocated or consolidated:** current dashboard content becomes four role-appropriate destinations—Today, Reports, Content Operations, and Platform Operations. Email becomes context-specific entry points plus shared templates; scheduling remains two explicitly distinct domains (content publishing vs. branch appointments).
- **Still requiring detailed design work:** full estimator interactions, customer/property CRUD states, public signing, finance tables/reconciliation, content production screens, access administration, and the approved GHL integration surfaces. Their target location is defined; production behavior remains preserved pending detailed design/implementation. CallRail is not approved and is out of scope.
- **Proposed deprecations:** none.
- **Approved GHL topology:** the current marketing account becomes Tim's corporate account/location, and each branch receives its own GHL sub-account/location. GHL credentials are server-side connection secrets, never browser-visible configuration values. App use of GHL is not implemented yet, so its API/webhook/identity/retry contract remains a mandatory pre-planning discovery. CallRail is not approved and is outside this design scope.

### Data hierarchy

Urgent revenue/action data belongs in Today; customer, measurement, pricing and lifecycle detail belongs in contextual workspaces; aging/funnel/branch performance belongs in Reports; content and processing data belongs in Content Operations; and secrets, readiness, health checks, integrations, diagnostics, logs, audit and platform cost belong in restricted Platform Operations. The matrix records the full data-placement rationale.

**Decision readiness:** the targeted preservation review and independent re-check are complete. All source-evidenced current capabilities have an explicit disposition in [the feature/capability preservation matrix](feature-capability-parity.md); no deprecations are proposed. GHL is an approved but not-yet-implemented integration with a corporate/branch topology and an explicit pre-planning technical-contract discovery. CallRail is unapproved and out of scope, not an omitted capability.

**Decision requested:** approve Direction A, the Revenue command center, as the primary operating shell, with Direction B retained as Pipeline, Direction C as Customer/property workspace, and the preservation mapping as binding scope for later planning.

The representative prototype and independent review are complete in `.ux-review/05-prototype-review.md` and `.ux-review/06-adversarial-design-review.md`. Approval authorizes implementation planning only; it does not authorize production code changes. Any implementation plan must include the mandatory server-side payment/activity/scope/integration safeguards recorded in the adversarial review.
