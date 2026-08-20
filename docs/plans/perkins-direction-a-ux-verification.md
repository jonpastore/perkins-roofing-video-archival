# Verification design: Perkins Direction A v5 UX implementation

Status: **PLANNED — awaiting product-owner implementation authorization**  
Baseline: [Direction A v5 UX package](../../.project/reviews/perkins-uiux-direction-a-v5.md) (approved, UX Design Readiness 97/100)  
Scope: implementation verification only. This plan neither enables GHL/payment/handoff integrations nor closes production-release gates.

## Governing rules

- Preserve every meaningful existing capability and data group in the [capability/data parity matrix](../../.ux-review/feature-capability-parity.md). A missing target is a failed implementation, not a design simplification.
- The approved UX contract is authoritative. A material IA, state, role, hierarchy, sender, responsive, or interaction change requires a UX change proposal.
- UI visibility is never authorization evidence. Role, tenant, branch and support-context rules must be tested at the API/server boundary.
- New or changed first-party executable code has 100% differential line/function coverage and the project 100% first-party coverage gate. Critical/high requirements require a 100% verification path; medium requirements require at least 95% unless explicitly deferred.
- Use Superpowers TDD after implementation authorization where practical: observed RED → smallest GREEN → refactor. Use systematic debugging for unexpected failures and fresh verification-before-completion evidence before a package is complete.

## Requirement-to-verification matrix

| ID | Approved behavior / risk | Layers and objective evidence | Delivery package |
| --- | --- | --- | --- |
| TST-UX-01 | Capability/data parity: no silently lost route, operation, data group or status. | Matrix-driven route/API inventory; component and API assertions for preserved/re-located surfaces; manual parity review against the current nav/page list. | PLAN-UX-01…04 |
| TST-UX-02 | Role × capability × data scope: branch/sales, corporate/content and platform destinations are distinct; Platform has no branch/customer/revenue context without audited support scope. | API authorization, tenant/BOLA and branch-scope negative tests; UI navigation/reachability tests for each role; direct-route denial tests. | PLAN-UX-01, PLAN-UX-04 |
| TST-UX-03 | Today master/detail queue exposes risk, owner, next action, freshness and stable payment labels without reload. | Component/UI tests for loading, empty, stale, error, duplicate and success states; API contract tests for queue/order/cursors; browser flow with async mutation and return-to-queue focus. | PLAN-UX-02 |
| TST-UX-04 | Customer/property/sales workflows retain multiple contacts/properties, measurement/provenance, estimates, proposals, invoices, payments, revisions and public proposal flow. | Existing API regression suite plus targeted component/UI tests using zero/one/many, long/Unicode/null/duplicate and stale data; visual evidence for dense record and narrow widths. | PLAN-UX-03 |
| TST-UX-05 | Outreach distinguishes human activity from automation and exposes approved sender provenance: `Perkins Roofing — <Branch> Team`, fallback `Perkins Roofing Team`; individual sender is never implied for automated work. | Component and contract tests for sender/template source/fallback; negative assertion against unapproved personal automation; relevant existing email API auth/error tests. | PLAN-UX-03 |
| TST-UX-06 | Responsive hierarchy survives large desktop (1440×900), representative laptop (1280×800), tablet (768×1024) and mobile (390×844), including long/dense/ugly data. | Playwright visual baselines with controlled fixtures; layout assertions for navigation, queue/detail transition, overflow and dialogs; browser 200% zoom/text-scaling check. | PLAN-UX-01…04 |
| TST-UX-07 | WCAG 2.2 AA critical flows: focus, keyboard, screen-reader semantics, contrast, dialog/drawer behavior and master/detail navigation. | Automated axe scan without serious/critical findings; keyboard scripts; contrast-token checks; manual NVDA/Firefox and VoiceOver/Safari critical-flow evidence at release. Explicitly test row focus, selection/announcement, entry to detail/actions, return to queue, and focus after async success/failure. | PLAN-UX-01, PLAN-UX-02 |
| TST-UX-08 | Risk/financial integrations remain user-legible but fail closed: Payment pending, verified, exception and Policy review required; no provider terminology is exposed as the UX source of truth. | UI/API states for missing/late/duplicate/error/stale data and blocked action; server authorization tests. Exact provider/GHL mappings remain deferred to TST-GL after external evidence. | PLAN-UX-02, PLAN-UX-05 |
| TST-UX-09 | Destructive actions and account controls are explicit, cancellable where possible, scoped and auditable. | Direct API authz/BOLA tests; UI confirmation/error/retry tests; no optimistic destructive disappearance before server success. | PLAN-UX-03, PLAN-UX-04 |
| TST-UX-10 | Implementation refinements: Call CTA is non-destructive primary treatment; selected rows do not communicate error/destruction; prototype-only scenario control is absent. | Token/contrast tests, visual regression, DOM/route negative test for prototype control, 200% small-text checks, mobile/tablet hierarchy tests. | PLAN-UX-01, PLAN-UX-02 |

## Fixtures and state coverage

Every UI/API slice uses deterministic tenant-scoped fixtures covering:

- no work, one work item, a large queue and pagination/cursor boundaries;
- duplicate names, very long names/addresses, Unicode/emoji, null contact fields, multiple properties and multi-contact households;
- overdue, blocked, stale, failed, permission-denied, loading and retryable states;
- inactive/deactivated customer/property, proposal revision lineage, partial data and duplicate async completion;
- roles: branch/sales, corporate/content, platform admin, denied user and audited support context.

Never use provider-state labels, field IDs, credentials or raw payloads as client fixtures. Use the approved stable UX states and redacted contract fixtures only.

## Tiers, gates and evidence

| Tier | Required evidence | Gate |
| --- | --- | --- |
| Inner loop / PR | targeted Vitest and pytest unit/component/API tests; typecheck/lint; differential coverage | 100% changed first-party lines/functions; critical new branches exercised |
| Merge | relevant existing API/tenant/role tests; Playwright UI + visual slice; axe and keyboard tests; full first-party coverage | no unapproved coverage exclusion; critical/high matrix rows represented |
| Release | supported-browser visual checks; manual assistive-tech and 200% scale script; performance/resilience smoke; server authorization and rollback check | fresh artifact/version/environment/device evidence; no unresolved critical UX/security defect |

Evidence records must name the product/component, commit, environment, viewport/device/browser, test command, timestamp and result. Prototype screenshots are baseline design evidence only; production implementation needs fresh evidence.

## Deferred boundaries

| Dependency | Classification | UX behavior now | Later proof required |
| --- | --- | --- | --- |
| GHL account IDs, fields, stages, workflow/send suppression | IMPLEMENTATION_CONTRACT_EVIDENCE / PRE_PRODUCTION_EXTERNAL_CONFIGURATION | stable integration/freshness/error language only | EXT-GL-01/02 and TST-GL-02/07/09/10 |
| Payment provider terminal states | IMPLEMENTATION_CONTRACT_EVIDENCE | only canonical pending/verified/exception/review labels | EXT-GL-04 and TST-GL-03/11/12 |
| Remote handoff endpoint/acknowledgement | IMPLEMENTATION_CONTRACT_EVIDENCE | no enabled remote handoff UI | EXT-GL-07 and TST-GL-13/14 |
| Contract/legal policy values and notices | PRE_PRODUCTION_EXTERNAL_CONFIGURATION | configured content/rules or safe policy review state | EXT-GL-05/06 and TST-GL-11/12/15 |

These are not blockers to the approved UX implementation packages unless a package attempts to enable the named integration.

## Human critical-flow script

Give an authorized branch operator a named overdue customer with multiple properties and ask them to complete the next action, inspect its recent activity/source, recover from a delayed update, and return to the queue. Give a corporate user a branch exception and a platform user a restricted health task. Do not tell participants which controls to choose. Capture completion, time, hesitation, wrong path, data misunderstanding, accessibility issue, browser/device/scale and version. Repeat keyboard-only and at 200% zoom/text scaling.

## Completion record

After each authorized package, add its exact commits/files, command results, visual/a11y/security evidence and any approved deviation to `.project/implementation-verification.md`. A package cannot claim completion from an implementer report alone.
