# GHL lifecycle consensus — cycle 2, v6

Status: FROZEN — targeted independent review pending
Cycle: 2
Iteration: 6
System Design Readiness: 95/100 target under review.
Implementation Readiness: BLOCKED (external contracts/configuration).
Production Release Readiness: BLOCKED (external contracts/configuration plus release evidence).
Targeted scope: revocation-versus-dispatch/acknowledgement race; accessible `POLICY_REVIEW_REQUIRED`; canonical three-layer readiness state.

`not_dispatched` work may be cancelled by revocation. `dispatch_attempted` with no conclusive
acknowledgement is `ACKNOWLEDGEMENT_UNKNOWN`, frozen and reconciled by idempotency key before any
retry/re-evaluation. CAS establishes the winning local acknowledgement/revocation transition.
