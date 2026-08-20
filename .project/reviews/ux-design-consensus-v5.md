# UX design consensus review — v5

Status: MAX_ITERATIONS_REACHED — SUPERSEDED_BY_NEW_USER_DECISIONS; retained as historical evidence
Iteration: 5
Evidence Readiness: 82/100; hard cap 89/100 pending external account and payment-source contract evidence.
Residual Uncertainty: `EXT-GL-01`, `EXT-GL-02`, `EXT-GL-04`, `EXT-GL-05`, `DEC-GL-06`, and `DEC-GL-07`.
Reviewer Verdicts: Architect `ITERATE`; Critic `ITERATE`; Evidence Verifier `ITERATE`.
Blocking Findings: high-impact external evidence and non-inferable finance/contact policy prevent executable-plan authorization.
Open User Decisions: `DEC-GL-06`, `DEC-GL-07`.

## Frozen v5 revision

This snapshot incorporates the 2026-08-20 product-owner decisions and repository discovery:

- `DEC-GL-01` is approved: automated sender is `Perkins Roofing — <Branch> Team`, with
  `Perkins Roofing Team` fallback; no individual sender unless an existing approved workflow
  explicitly requires it.
- `DEC-GL-05` is approved as an engineering/product baseline: raw webhook payloads 30 days,
  normalized integration/audit metadata one year, required financial/payment records seven years,
  and legal/security holds override deletion. This is explicitly not a legal-compliance claim;
  legal/privacy validation remains a pre-production gate.
- Read-only repository discovery resolves `DEC-GL-04` into a source hierarchy rather than a
  product-owner selection: app-native billing events are the canonical local commercial ledger;
  Knowify is the current imported finance/receivables source; GHL is a projection. No inspected
  code provides an authenticated processor settlement contract, so no source may transition Won
  or handoff until that contract is evidenced. The immutable provider transaction/payment ID and
  idempotent reconciliation remain mandatory.
- The request to use currently configured GHL credentials cannot be executed safely: prior
  discovery records that the GHL password was exposed in an automation trace. Credential rotation
  is therefore a pre-production security gate and prerequisite to renewed read-only account
  discovery. No GHL access or configuration change was attempted in this revision.

## Evidence classification

| Claim | Classification | Evidence |
| --- | --- | --- |
| Sender and retention policy | VERIFIED_AUTHORITATIVE_SOURCE | 2026-08-20 product-owner decision in this engagement; decisions and owning artifacts updated. |
| App-native ledger supports idempotent payment recording | VERIFIED_DIRECTLY | `api/routes/invoices.py` records a payment and ledger event in one transaction with idempotency-key replay protection. |
| Knowify is imported finance/receivables source | VERIFIED_DIRECTLY | `core/knowify/promote.py` imports receivable payments with `knowify_payment_id`; the mirror DDD/TRD document the imported record boundary. |
| Processor-authenticated settlement source | UNVERIFIED | No inspected code/configuration identifies an external processor adapter, verified provider event, or account contract. |
| Perkins GHL exact mapping and installed-payment capabilities | UNVERIFIED | Requires read-only account discovery, unavailable until exposed credential is rotated. |

## Deliberate-mode pre-mortem

| Failure | Cause | Detection | Impact | Mitigation | Recovery |
| --- | --- | --- | --- | --- | --- |
| GHL stage marks a sale Won without settled deposit | stage/workflow is treated as payment authority | negative transition tests and ledger audit | uncollected work/handoff | server conditional transition requires authenticated source event | retain pending state; reconcile source and audit rejection |
| Wrong or compromised credential reads/changes account data | prior password exposure reused | security gate and access audit | account compromise / unsafe discovery | rotate before any renewed discovery; scoped read-only account | revoke/rotate, investigate access log, re-establish mapping |
| Retention job deletes investigation evidence | missing hold enforcement | hold/deletion audit and resilience tests | lost security/legal evidence | hold marker blocks deletion; release is audited | restore from approved backup where available; incident review |
| Delayed/duplicate provider event creates inconsistent handoff | non-idempotent webhook or missed delivery | correlation/outbox/reconciliation telemetry | duplicate or absent handoff | immutable transaction ID, idempotency keys, bounded retry/reconciliation | rebuild projection from ledger and route exception review |

## Hard-gate assessment

- Requirements/domain/UX/security/verification traceability is updated for all new decisions.
- No production implementation, GHL configuration, payment-provider configuration, secrets, or
  account data was changed.
- `EXT-GL-01`: credential rotation plus read-only GHL mapping remains unavailable.
- `EXT-GL-04`: an authenticated payment-provider/account contract remains unavailable.
- Both are high-impact factual premises for an executable outbound/payment plan, so readiness is
  capped at 89/100. The bounded read-only UX/design outcome remains conditionally acceptable.

## Independent review synthesis and remediation

All three independent reviewers returned `ITERATE`. Agent-resolvable findings were incorporated
into the owning PRD/DDD/TRD/security/verification/traceability artifacts: payment evidence is now
explicitly separate from manual and Knowify records; external GHL Won containment and
reconciliation requirements are traceable; retention lifecycle/hold/restore mechanics are
testable; and sender behavior has an end-to-end verification target.

The remaining findings are deliberately visible rather than inferred:

| ID | Classification | Required evidence or decision |
| --- | --- | --- |
| EXT-GL-01 | EXTERNAL_ACCESS_REQUIRED | Rotate the credential exposed in prior automation evidence before further account access. |
| EXT-GL-02 | EXTERNAL_AUTHORIZATION_REQUIRED | Approve a least-privilege GHL OAuth/private-integration discovery method, scopes, locations, log access and non-production webhook evidence; identify any account-state-changing step separately. |
| EXT-GL-04 | EXTERNAL_ACCESS_REQUIRED | Obtain the authoritative provider/account event contract for provider-authenticated payment confirmation. |
| EXT-GL-05 | EXTERNAL_LEGAL_PRIVACY_VALIDATION_REQUIRED | Validate legal basis, jurisdictional application, hold/deletion, backup/restore and data-subject obligations before production. |
| DEC-GL-06 | USER_DECISION_REQUIRED | Set qualifying payment state, allocation/cumulative-deposit rule, and reversal/refund/chargeback impact on Won/handoff. |
| DEC-GL-07 | USER_DECISION_REQUIRED | Set field-level contact authority and GHL merge/delete/consent/correlation rules. |

Evidence Verifier scored this snapshot 82/100: strong design traceability, but unverified
processor/account, GHL, legal, and runnable-test evidence remain. The configured fifth iteration
has been used; this synthesis does not claim a sixth consensus round or implementation approval.
