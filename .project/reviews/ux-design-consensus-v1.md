# UX design consensus review — v1

Status: ITERATE
Iteration: 1
Evidence Readiness: 88/100 for consequential planning; design-direction evidence is stronger but does not independently clear the 95/100 plan threshold.
Residual Uncertainty: GHL technical contract, server enforcement, payment authority, role/capability/data scope, accessibility proof and outcome baselines remain unverified or incomplete.
Reviewer Verdicts: Architect `APPROVE_WITH_CONDITIONS`; Critic `ITERATE`; Evidence Verifier `ITERATE`.
Blocking Findings: No prototype or capability-parity blocker prevents a conditional Direction A decision. The listed High findings block consequential delivery/implementation planning.
Open User Decisions: sender identity; final granular role/capability/data-scope policy; acceptance of the Direction A scope and its planning prerequisites.

## Frozen snapshot

The v1 review covered the product-owner interview, UX strategy, design directions,
prototype review, adversarial review and feature/capability matrix in `.ux-review/`,
plus the approved sales-flow and estimate/proposal requirement set. The snapshot
hashes are recorded in the session evidence on 2026-08-20. It intentionally did not
rescan the repositories or alter production code.

## Consensus result

Direction A, the role- and branch-scoped Revenue command center, remains the
recommended operating shell. Direction B remains the Pipeline destination and
Direction C remains the customer/property workspace. No source-evidenced capability
is approved for removal; CallRail remains unapproved and out of scope.

The design is conditionally presentable because its authoritative user decisions,
capability dispositions, representative rendered prototypes and adversarial fixes
are preserved. It does not authorize production work or a broad implementation plan.

## Required conditions before consequential delivery planning

| ID | Condition | Owner / next specialist |
| --- | --- | --- |
| CON-UX-01 | Define a capability × action × data-scope matrix for branch, corporate, platform and tenant boundaries, including sensitive finance, payment, pricing, export, user and audit actions. | Requirements engineering |
| CON-UX-02 | Perform read-only GHL contract discovery: field/event authority, IDs, stages, webhook ordering, idempotency, retries, conflicts, workflow compatibility and rollback. | Requirements engineering + DevSecOps |
| CON-UX-03 | Resolve or explicitly time-box sender identity for automated customer messages, including owner, fallback wording and acceptance test. | Product owner |
| CON-UX-04 | Define branch-calendar/timezone/DST SLA semantics and measurable outcome baselines/telemetry. | Requirements engineering + Test verification |
| CON-UX-05 | Create the objective verification matrix: automated accessibility scan, keyboard/focus/dialog behavior, contrast, 200% zoom/text scaling, supported-browser/device checks, async/error/race and authorization tests. | Test verification design |
| CON-UX-06 | Preserve the technical gates: server-authoritative conditional lifecycle/payment transitions, append-only idempotent activity, scoped authorization/audit, correlation/versioned integration events and transactional outbox handoff. | Requirements engineering + DevSecOps |
| CON-UX-07 | Reconcile the CompanyCam source/rendered-mapping wording in the parity registry during requirements reconciliation; it is a preservation discovery item, not an approved omission. | Requirements engineering |

## Pre-mortem

| Failure | Detection | Mitigation / recovery |
| --- | --- | --- |
| Risk queue clears or ranks work from stale/local activity. | SLA and event/version mismatch telemetry; duplicate-event tests. | Server-confirmed append-only events; preserve follow-up/pending state; rebuild projections from ledger. |
| GHL stage changes break existing workflows or cross branches. | Read-only dependency inventory, contract tests and per-connection health. | Branch-scoped connections, compatibility mapping, pilot/feature flag and rollback to read-only mirroring. |
| Payment or handoff becomes `Won` without verified deposit. | Provider-ID reconciliation and negative transition tests. | Conditional server state machine, idempotency ledger and transactional outbox; block transition and expose remediation. |
| Corporate drill-down leaks branch/tenant data. | Negative authorization and audit tests. | Server-derived scope on every operation; aggregate-first reporting; audit and revoke access. |
| Phone workflow is unusable at scale or with assistive technology. | A11y scans, keyboard/screen-reader/device tests and completion metrics. | Retain laptop-first dense work; use task-focused phone flows; correct before rollout. |

## Traceability handoff

`sales-flow / estimate-proposal requirements → Direction A/B/C and parity matrix → CON-UX conditions → TST verification matrix → delivery work packages`.

The next consensus iteration must assess the revised requirements/verification and
technical-discovery evidence. It must not claim a 95/100 executable-plan gate until
all High conditions are covered or explicitly resolved by the product owner.
