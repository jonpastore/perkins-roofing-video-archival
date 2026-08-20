# PRD: GHL lifecycle integration

Status: DRAFT — requirements reconciliation, not implementation authorization

## Requirements

| ID | Requirement | Acceptance / metric |
| --- | --- | --- |
| PRD-GL-01 | The app shall project revenue risk from durable lifecycle, human-activity, appointment, proposal and verified-payment facts. | A projection always names its source facts, branch, owner, due time, sync state and version. Local UI activity cannot clear work. |
| PRD-GL-02 | GHL shall be the authority for communications, calendars, appointments and pre-quote opportunity automation; the app shall be the authority for commercial records and verified payment/handoff. | Authority table in DDD is applied to every mapped field/event; conflicting authority produces a review item. |
| PRD-GL-03 | The system shall associate each GHL resource with exactly one authorized branch location or the corporate location. | A cross-branch or cross-tenant location/resource reference is rejected and audited. |
| PRD-GL-04 | The system shall implement the owner-approved response policy: five business-minute first human attempt, 15-minute reminders, and reassignment/escalation at 60 minutes; after-hours starts at next branch opening. | See DOM-GL-04 and TST-GL-04 for calendar, DST, holiday and reassignment cases. |
| PRD-GL-05 | Commercial eligibility is derived from provider-confirmed payment-ledger events, contract/account context, and the approved effective policy version. CRM stage, app UI state, authorization, and unverified mirrors are never proof. | Missing, ambiguous, or inapplicable policy fails closed to `POLICY_REVIEW_REQUIRED`; preserve provider transaction IDs, policy version, idempotency, and audit evidence. |
| PRD-GL-06 | Contact identity changes from GHL may add/match an unambiguous contact; conflicts never silently overwrite existing app identity. | A conflict retains both source facts and creates an authorized review action. |
| PRD-GL-07 | Existing application capability and important data remain preserved according to `.ux-review/feature-capability-parity.md`; no deprecation is approved. | Planning trace includes a target, acceptance and TST reference for each material capability. |
| PRD-GL-08 | Existing immutable proposal snapshot, estimate lineage, legacy-quote provenance and token-gated public acceptance rules remain authoritative when GHL facts are projected. | GHL references are additive; no event may mutate a sent/accepted snapshot, reinterpret a legacy import, or bypass the existing public-acceptance transaction. |
| PRD-GL-09 | GHL-side `Won` must not trigger customer-facing/post-job effects unless the app has already conditionally recorded verified deposit and handoff readiness. | Manual, legacy-client, or workflow-originated GHL `Won` is detected, contained/reviewed and reconciled; no automatic app commercial transition follows it. |
| PRD-GL-10 | The application is canonical for customer identity; GHL is an operational CRM/contact projection. | GHL changes only unambiguous mapped facts; GHL merge/delete never silently merges/deletes app identity; aliases/provider IDs/correlation history persist; conflict reconciliation is deterministic, never last-write-wins. |
| PRD-GL-11 | Commercial payment, exception, cancellation, and notice rules are externally approved configuration, not application legal interpretation. | Policy values and content are effective-dated/versioned; missing or ambiguous policy fails closed to manual review; the application records the configured rule and evidence of its application. |

## NFRs

| ID | Requirement | Target / evidence |
| --- | --- | --- |
| NFR-GL-01 | Authorization | Server derives tenant/branch/capability scope for every read and mutation; direct API negative tests pass. |
| NFR-GL-02 | Integrity | Every inbound/outbound event has source, external ID, correlation ID, monotonic version or ordering rule, idempotency key, processing result and retry state. |
| NFR-GL-03 | Accessibility | Critical web flows meet the TST accessibility matrix: automated scan, keyboard/focus, contrast, 200% text/zoom and manual critical-flow checks. |
| NFR-GL-04 | Browser/device | Chromium, Firefox and WebKit headless checks cover critical desktop/mobile web flows; physical-device validation is release evidence. |
| NFR-GL-05 | Quality | Changed first-party code meets 100% statement/line/function and branch target plus 100% differential coverage; critical domain/security paths have semantic tests. |
| NFR-GL-06 | Observability | Emit lead-response, exception-resolution, sync-lag/failure, duplicate-event, authorization-denial and transition-rejection telemetry. |
| NFR-GL-07 | Retention | Retain encrypted, access-controlled raw webhooks for 30 days by default; normalized integration/audit metadata for one year; required financial/payment records for seven years; minimize PI and retain no secrets, authorization headers, or payment credentials in logs. Active legal/security holds override deletion until released. This is an engineering baseline, not a legal-compliance claim. |
| NFR-GL-08 | Reconciliation | Reconcile each scoped external resource with a documented watermark, overlap window, maximum recovery lag, pause/health detection and authorized read scope; retain every skipped/conflicting source fact for review. |
| NFR-GL-09 | Messaging consent | GHL opt-out is authoritative for GHL-originated messaging. When systems disagree for a channel, enforce the most restrictive applicable state until deterministic reconciliation completes. |

## Outcome baselines

Current values are unavailable and must be captured for two operating weeks before cohort comparison.

| Outcome | Baseline | Target | Measurement |
| --- | --- | --- | --- |
| First verified human attempt within policy | two-week pre-rollout baseline, per branch | ≥95% during business hours for four consecutive weeks | event ledger, branch calendar and assignment records; owner: sales operations |
| Accepted-to-verified-deposit resolution | two-week pre-rollout median/P90, by branch and job type | reduce both median and P90 by ≥20% over the next four weeks without increasing refund/chargeback rate | proposal/payment event timestamps; owner: finance operations |
| Unresolved risk work | two-week daily baseline, per branch/owner/risk type | reduce overdue count and P90 age by ≥25% over four weeks | daily queue snapshot; owner: branch operations |
| Integration reliability | two-week read-only-mirror baseline | ≥99% terminal event processing without manual repair for four consecutive weeks | correlation ledger and retry outcomes; owner: platform operations |
