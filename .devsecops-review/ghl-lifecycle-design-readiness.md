# GHL lifecycle security design readiness

Mode: DESIGN_READINESS
Status: DRAFT — design controls, not an assurance or compliance claim

## Trust boundaries and data

`GHL webhook/API ↔ server integration adapter/queue ↔ tenant RLS database/outbox ↔ authenticated web client`.
Data includes PI (contact/appointment), PAYMENT state (not raw card data), AUTH tokens/signatures,
SECRETS (connection credentials), and AUDIT_LOG records. The client receives only scoped business
state; it never receives GHL credentials, webhook verification material, or raw diagnostic payloads.

## SEC requirements

| ID | Control | Evidence / test |
| --- | --- | --- |
| SEC-GL-01 | Verify current GHL Ed25519 webhook signature before parse/process; reject unknown location and replay. | Signature, malformed, wrong-location and replay API tests. |
| SEC-GL-02 | Derive tenant/branch connection from verified server records, never client IDs/body scope. | BOLA/IDOR/direct-API/cross-tenant tests. |
| SEC-GL-03 | Ledger/outbox processing is idempotent, version-aware and append-only. | duplicate, out-of-order, concurrent and restart/fault tests. |
| SEC-GL-04 | Payment/Won/handoff require server conditional transition plus verified provider event. | negative payment/stale/replay/unauthorized transition tests. |
| SEC-GL-05 | Secrets remain server-side references; redact payload/credential data in logs and audit records. | secret scan, response/log review and configuration tests. |
| SEC-GL-06 | Identity conflict retains history and requires scoped reviewer action. | conflict, role and audit tests. |
| SEC-GL-07 | Webhook ingress has per-connection rate/size limits, bounded queue/backpressure and no sensitive error reflection. | overload, malformed/oversize and dependency-degraded tests. |
| SEC-GL-08 | Connection credential rotation, revocation/offboarding and rollback-generation fencing prevent use of stale secrets/work. | rotation/revocation/old-generation worker and audit tests. |
| SEC-GL-09 | Ledger/audit storage minimizes PI, encrypts raw payloads, redacts restricted payloads, and enforces this engineering baseline: raw webhooks 30 days, normalized integration/audit metadata one year, required financial/payment records seven years; no secrets, authorization headers, or payment credentials in logs. | storage/access/redaction/retention/deletion/hold evidence review. |
| SEC-GL-10 | Messaging requires a server-side per-channel consent decision. `UNKNOWN`/`OPTED_OUT` and stale/replayed relaxation attempts deny send; aliases and cross-branch references cannot bypass the most-restrictive state. | negative consent, replay, alias-merge, cross-branch and audited non-send tests. |
| SEC-GL-11 | Commercial-policy configuration is least-privilege, versioned, effective-dated and auditable. Missing/ambiguous policy denies automated gated action and creates `POLICY_REVIEW_REQUIRED`. | role/approval/version/tamper/expiry and fail-closed policy tests. |

## Credible attack paths and dispositions

| Risk | Disposition |
| --- | --- |
| Forged/replayed webhook changes lifecycle | MITIGATE with SEC-GL-01/03; external account details still required. |
| Cross-branch location/resource reference leaks data | MITIGATE with SEC-GL-02 and RLS/negative tests. |
| Duplicate/out-of-order event marks Won or clears SLA | MITIGATE with ledger/version/outbox rules and DOM-GL-01/05. |
| Client or GHL stage bypasses payment confirmation | MITIGATE with SEC-GL-04. |
| OAuth/API credential leaks to browser/logs | MITIGATE with server secret references and SEC-GL-05. |
| Webhook flood exhausts queue or causes unsafe retries | MITIGATE with SEC-GL-07 and degraded-service tests. |
| Rotated/revoked connection still dispatches work | MITIGATE with SEC-GL-08 and generation fencing. |

## Retention ownership and hold policy

| Data class | Retention | Deletion / exception mechanism | System owner |
| --- | --- | --- | --- |
| Raw webhook payload | 30 days by default | encrypted restricted store; scheduled deletion with auditable completion; extend only for identified operational/legal need | platform operations |
| Normalized integration/audit metadata | 1 year | lifecycle deletion job with access/audit evidence | platform operations |
| Financial/payment transaction records | 7 years unless applicable policy requires longer | accounting retention workflow; preserve immutable provider transaction/payment ID | finance operations |
| Active legal/security investigation evidence | hold overrides normal deletion until formally released | legal/security hold marker blocks deletion and release is audited | legal/security owner |

This is an engineering/product baseline, not a legal-compliance claim. Pre-production legal/privacy
validation must confirm applicability, owner, and any jurisdictional variation.

Retention implementation evidence must define field-to-class classification, retention-clock
start/reset semantics, hold authority/scope/propagation, deletion audit, backup/restore behavior,
and key-rotation interaction. Tests must prove a held object is not deleted and cannot be restored
without its hold/audit context.

## External evidence required

Credential rotation and account access are required to verify Perkins-specific location IDs,
installed-app scopes, field/stage IDs, event payloads, workflow dependencies and webhook log/retry
behavior. A previous automation trace exposed the GHL password, so the currently configured
credential is not eligible for further use; rotation is a pre-production security gate and a
prerequisite to any renewed read-only account discovery. This report does not claim those controls
are currently deployed.

## Operational evidence proposal

Platform operations owns daily connection-health and dead-letter review, weekly authorization-denial
and duplicate-event review, and monthly credential/grant/retention-control review. Alert when a
signature failure, unknown-location event or cross-scope denial occurs; when queue age exceeds the
approved SLA; or when any connection has terminal failures above 1% in a rolling hour. Retention
durations and deletion mechanisms follow the documented engineering baseline; legal/privacy
validation before production confirms legal basis and exceptions. Credential rotation/revocation evidence records request, approver, old/new
secret version references (not values), generation fence and successful stale-worker rejection.
