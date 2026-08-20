# Perkins Roofing UX Design Package — Direction A Hybrid (v1)

Status: FROZEN FOR UX-ONLY CONSENSUS REVIEW  
Date: 2026-08-20  
Scope: Brownfield product UX and disposable prototype only; no production implementation or external configuration.

## Decision under review

Adopt the Direction A hybrid: a role- and branch-scoped revenue command center for immediate work, with dedicated customer/property, estimate/proposal, reporting, content-operations, and restricted platform-operations workspaces. Preserve every current meaningful capability using the approved feature/data parity matrix; no capability is silently removed.

## Product experience contract

- **Today** is an exception-first, scope-labelled work queue—not a replacement for pipeline, reporting, customer records, finance, content, or operations.
- **Phone** prioritizes the next safe action; desktop/tablet preserve operational density and visible scope.
- **Customer/property** remains the context for contacts, multi-property work, measurements, estimates, proposals, invoices, and payment history.
- **Sales Work** retains estimator/proposal depth in a dedicated workspace; the prototype explicitly keeps draft/pre-proposal work distinct from signed revision/change-order work.
- **Platform Operations** is a restricted diagnostic/remediation workspace; branch users see only contextual, non-sensitive status.
- User-facing financial states use stable abstractions: `Payment pending`, `Payment verified`, `Payment exception`, and `Policy review required`. The prototype does not expose provider-state jargon or make payment/handoff decisions.
- Role preview controls are reviewer-only mock harnesses. Production role, branch, and data scope are server-authorized.

## Information architecture

| Target workspace | Purpose | Preserved capability groups |
| --- | --- | --- |
| Today | Branch/corporate revenue-risk work queue and focused action context | dashboard risk, lifecycle visibility, notifications, contextual activity |
| Customers | Searchable customer/property operating context | customer/contact/property CRUD, multi-property, media context |
| Sales Work | Detailed estimate, proposal, invoice and payment work | measurements, Squares, estimator, proposal revisions/PDF/public signing, ledger detail |
| Schedule | Branch appointment context, distinct from publishing calendar | appointment/calendar work |
| Knowledge / Content Operations | Knowledge consumption and content-production workflows | search/Ask, FAQ, archive, clips, articles, portfolio, approval, community, email |
| Reports | Corporate/finance performance and drill-down | revenue, receivables, funnel, branch/date reporting |
| Admin / Platform Operations | Restricted configuration, diagnostics and remediation | integrations, Knowify, logs/audit, readiness, users/RBAC, SSO, costs |

## Parity and design evidence

- Canonical parity: `.ux-review/feature-capability-parity.md` — every source-evidenced capability has a disposition; no deprecation is proposed.
- Strategy and selected direction: `.ux-review/03-ux-strategy.md`, `.ux-review/04-design-directions.md`.
- Current-state prototype review and constraints: `.ux-review/05-prototype-review.md`.
- UX-only independent adversarial dispositions: `.ux-review/06-adversarial-design-review.md`.
- Disposable prototype: `.ux-review/prototype/`.
- Fresh rendered evidence: `output/playwright/ux-remediated-tablet.png`, `output/playwright/ux-remediated-mobile-drawer.png`, `output/playwright/ux-estimate-mobile-navigation.png`, and `output/playwright/ux-platform-mobile-navigation.png`.

## Responsive and accessibility contract

- Desktop/laptop: labeled workspace navigation, dense queue and contextual record view.
- Tablet: retains labelled navigation rather than an unlabeled icon rail.
- Mobile: queue-first layout, explicit menu/drawer close, Escape, focus return, focus containment, and an explicit route back from specialist workspaces.
- Keyboard: visible focus on prototype controls; drawer controls are keyboard contained while open; concise feedback uses a dedicated status surface rather than an entire live queue.
- The prototype renders long names, long addresses, payment-review, loading/error, empty, stale, integration-conflict and scoped-role scenarios.
- Real assistive-technology and system text-size validation are production acceptance evidence, not claims from this static mock.

## Deferred implementation dependencies (not UX-design blockers)

| Dependency | UX handling | Why deferred |
| --- | --- | --- |
| GHL IDs, workflows, fields and credentials | Stable CRM/sync/error abstractions; no ID is exposed | Account-specific mapping and safe access are implementation discovery. |
| Provider terminal state mapping | Stable payment state labels; ambiguous cases surface `Policy review required` | Provider contract/configuration is required before enabled payment workflows. |
| Handoff destination/acknowledgement | UI shows only user-safe eligibility/review states | Remote handoff is an implementation contract and must not be simulated as complete. |
| Contract/legal/payment-policy values | Versioned policy/review abstraction; no legal conclusion | Approved external configuration is needed before production configuration. |
| iOS build 91 runtime call evidence | Preserved parallel release evidence lane | It does not change this web/product UX candidate absent a material user-visible finding. |

## Review question and readiness boundary

Does this UX package provide a coherent, accessible, responsive Direction A design that preserves current capability/data scope and is feasible at a design-contract level, without treating deferred integration/release evidence as UX defects?

Target: **UX Design Readiness ≥95/100.** This target never authorizes implementation or production release.
