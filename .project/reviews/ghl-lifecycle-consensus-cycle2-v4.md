# GHL lifecycle consensus — cycle 2, v4

Status: FROZEN — independent review pending
Cycle: 2
Iteration: 4
System Design Readiness: 95/100 target under independent review.
Implementation Readiness: BLOCKED — authenticated provider, GHL and handoff contracts are absent.
Production Release Readiness: BLOCKED — credentials, external configuration, legal/privacy and release evidence are absent.
Residual Design Uncertainty: none known; external facts are contract/configuration evidence, not design premises.
Open User Decisions: none.

## Readiness boundaries

| Item | Category | Why |
| --- | --- | --- |
| GHL field/workflow/account IDs | IMPLEMENTATION_CONTRACT_EVIDENCE | Adapter, ordering, idempotency, reconciliation and read-only fallback are designed without IDs; IDs map the deployed connection. |
| Provider terminal-state names | IMPLEMENTATION_CONTRACT_EVIDENCE | Canonical adapter contract and non-qualifying invariants are designed; authenticated mapping is required before enabling eligibility. |
| Handoff destination/acknowledgement | IMPLEMENTATION_CONTRACT_EVIDENCE | Local conditional outbox/readiness semantics are designed; remote dispatch is disabled until contract exists. |
| Credentials, policy values/content | PRE_PRODUCTION_EXTERNAL_CONFIGURATION | Needed to configure/operate, not to select the architecture. |
| Legal/privacy validation and current-build runtime call | RELEASE_EVIDENCE | Required before release closure; neither changes system-design boundaries. |

## Frozen design contract

External references use `tenant+provider+connection+resource_type+external_id`; aliases/tombstones
are append-only. `CommercialPaymentPolicy` is append-only, content-hashed, maker-checker approved,
effective-dated by provider-event occurred time, and applied by immutable snapshot. Invariants—not
policy—exclude authorization, pending, CRM/UI and mirror evidence. Missing/ambiguous policy or
external contract fails closed to review. Remote handoff remains local readiness until its
authenticated idempotent acknowledgement contract is supplied.
