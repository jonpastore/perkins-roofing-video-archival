# Verification design: GHL lifecycle integration

Status: DRAFT — implementation-independent test/verification strategy

## Traceability matrix

| ID | Verification |
| --- | --- |
| TST-GL-01 / PRD-GL-01 | Domain projection tests for risk ordering, source labeling, pending/failed states and no client-side SLA clearing. |
| TST-GL-02 / PRD-GL-02/03, SEC-GL-01/02 | API/contract tests for location mapping, webhook signature, unknown location, allowed/denied scope, cross-tenant and direct API attempts. |
| TST-GL-03 / PRD-GL-05/08, DOM-GL-01/02/05, SEC-GL-03/04 | Property/domain tests for valid, invalid, duplicate, stale, concurrent and partial-failure lifecycle/activity/payment/outbox transitions. Assert provider terminal-success mapping to `DEPOSIT_VERIFIED`, cumulative verified payment, immutable IDs, and idempotency; no authorization, GHL state, client action, or unverified Knowify mirror may transition Won. Assert pre-handoff negative-event recovery and post-handoff exception/remediation without rewriting history. |
| TST-GL-04 / PRD-GL-04 | Unit/property tests for IANA zones, DST spring/fall transitions, holidays, after-hours, reassignment, policy versions and UTC due instants. |
| TST-GL-05 / PRD-GL-06, SEC-GL-06 | Contract/integration tests for ambiguous identity, source history and authorized review. |
| TST-GL-06 / NFR-GL-03/04 | Automated axe/WCAG 2.2 AA scan has no serious/critical finding; keyboard can complete queue, task sheet, dialog and return focus; visible focus and live announcements are asserted; contrast is AA; 200% browser zoom and text scaling have no clipped/overlapped critical control. Release pins exact Playwright/browser revisions in its evidence manifest and tests Chromium/Firefox/WebKit at 1440×900 and 390×844; manual evidence covers current-and-previous iOS Safari/VoiceOver and Android Chrome/TalkBack plus current NVDA/Firefox. |
| TST-GL-07 / NFR-GL-02/06 | Adapter contract tests with recorded/redacted GHL payloads; duplicate/out-of-order/retry/timeout/dead-letter/reconciliation fault injection and telemetry assertions. |
| TST-GL-08 / SEC-GL-07/08/09 | Rate/size/backpressure, secret rotation/revocation, rollback-generation, payload redaction/access/retention/hold/deletion and degraded-dependency tests/evidence. |
| TST-GL-09 / PRD-GL-09, NFR-GL-08 | Contract/fault tests verify that uncorrelated GHL Won, manual stage change and legacy-client/workflow effects do not create app Won/handoff; reconciliation uses cursor/overlap/lag bounds and preserves discrepancies. Tests cover sender/template version, branch fallback, Reply-To, consent/opt-out and no unapproved individual sender. |
| TST-GL-10 / PRD-GL-10, NFR-GL-09, DOM-GL-03 | Contract/property tests prove GHL merge/delete cannot destructively alter app identity; aliases/provider IDs/correlation survive; unambiguous facts update; ambiguous identity or consent conflict uses deterministic reconciliation and the most restrictive messaging state. |
| TST-GL-11 / PRD-GL-11 | Policy tests cover effective-dated selection, configured payment/cancellation/notice values, audit evidence, authorized exception closure, and fail-closed `POLICY_REVIEW_REQUIRED` when policy is missing or ambiguous. |
| TST-GL-12 / DOM-GL-05, SEC-GL-11 | Property/fault tests prove authorization/pending/CRM/UI/mirror evidence never qualifies; policy publications cannot overlap or mutate; delayed/replayed events use occurred-time selection and applied hash; explicit re-evaluation is required; tampered/out-of-contract configuration fails closed. |
| TST-GL-13 / handoff boundary | Contract/fault tests cover idempotent handoff command, acknowledgement absent/duplicate/ambiguous, retry/reconciliation, compensation, and no remote dispatch without authenticated downstream contract. |
| TST-GL-14 / policy revocation | Property/fault tests cover revocation before decision, after decision/before dispatch, after acknowledgement, retry and duplicate revoke; assert command fencing, review creation, immutable history and explicit re-evaluation only. |
| TST-GL-15 / policy-review UX | API/UI/a11y tests cover role-scoped `POLICY_REVIEW_REQUIRED`, reason/hash/evidence visibility, owner/action, mobile/keyboard flow, audit and no unsafe retry. |

## Test tiers and gates

- Inner loop: unit/domain/component/adapter contract tests with 100% differential coverage.
- Merge: API authorization/integration/UI/a11y slices plus first-party 100% statement/line/function and branch target.
- Release: supported-browser visual regression, manual accessibility/device script, integration staging contract evidence, rollback/read-only-flag test and security adversarial review.

- Payment-release evidence: a finance-approved qualifying-state/allocation/reversal policy; a
  provider account contract; uniqueness/fingerprint conflict, cumulative-deposit, refund,
  chargeback and two-session public-acceptance/outbox tests. Existing tests must be runnable in a
  pinned environment; the current missing `jcs` dependency is not an exclusion.

Critical tests may not be quarantined. Generated clients may be excluded only under the central policy;
first-party adapters, state machine, authorization predicates and UI behavior may not.

The manual release script gives a branch operator a named overdue lead and asks them to complete
the next action, log its outcome, recover from a delayed/failed sync and return to the queue;
an authorized corporate user must identify a branch exception without reaching another tenant;
an assistive-tech tester repeats the task at 200% zoom. Capture completion, elapsed time,
unexpected path, accessibility defect and browser/device/version. No script tells a tester which
control to select.
