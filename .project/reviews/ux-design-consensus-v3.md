# UX design consensus review — v3

Status: UNDER_INDEPENDENT_REVIEW
Iteration: 3
Evidence Readiness: 89/100 maximum for an executable plan until `EXT-GL-01` has direct Perkins-account evidence.
Residual Uncertainty: Perkins GHL contract facts and final automated sender wording only.
Reviewer Verdicts: pending independent Architect, Critic and Evidence Verifier review.
Blocking Findings: `EXT-GL-01` is an external-validation cap; no known agent-resolvable High finding remains.
Open User Decisions: `DEC-GL-01` only.

## Frozen v3 revision

In addition to v2, this revision resolves the iteration-2 requirements and verification findings:

| Finding class | v3 evidence |
| --- | --- |
| Authorization realization | DDD defines deny precedence, backward-compatible role migration, grant issuer/reason/scope/expiry/revocation, and objective negative cases. |
| Payment and commercial integrity | PRD-GL-08, DOM-GL-05 and TRD add provider-neutral evidence fields, review states and preserved snapshot/lineage/public-acceptance invariants. |
| Inbox/ordering/rollback | TRD defines durable receipt-before-ack, ordering fallbacks, deterministic projection rebuild, connection generations and pending-row disposition. |
| SLA/lifecycle | DOM-GL-06…09 and calendar rules define appointment, assignment, reminder/escalation, terminal and DST/policy-change behavior. |
| Outcomes and accessibility | PRD provides baseline windows/owners/numeric targets; TST-GL-06/08 provides executable a11y, browser/device, operational-security and manual-script criteria. |
| Security operations | SEC-GL-07…09 add rate/backpressure, credential lifecycle and payload/audit retention controls. |
| GHL compatibility | TRD defines field-level discovery output, signature transition/sunset policy, additive compatibility and read-only rollback. |

## External and user boundary

`EXT-GL-01` remains `EXTERNAL_ACCESS_REQUIRED`: rotated credentials and read-only account access
are needed for location/sub-account semantics and IDs, installed scopes, custom fields, pipeline
and stage IDs, workflow triggers, actual webhook payloads/logs/retries and provider/account
compatibility. This requirement is deliberately not satisfied by public vendor documentation.

`DEC-GL-01` remains `USER_DECISION_REQUIRED`: choose final automated sender wording and whether
personal identity is ever permitted. The requirements are otherwise executable with the
recommended team identity and safe fallback.

## Trace and reversal conditions

`.project/traceability.md` connects PRD/NFR/DOM/SEC/UX requirements to TST evidence. Delivery
work-package IDs remain pending because design and implementation approval have not occurred.
Reconsider Direction A if scoped GHL identity, authenticated payment evidence, server capability
enforcement or safe event reconciliation cannot be demonstrated. Rollback remains read-only
mirror disable plus generation fencing and ledger rebuild; no destructive vendor change is planned.

