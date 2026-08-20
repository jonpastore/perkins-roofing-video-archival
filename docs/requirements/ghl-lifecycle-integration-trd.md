# TRD: GHL lifecycle integration

Status: DRAFT — contract and security requirements; no external configuration change

## Architecture and contract

1. Add server-side `IntegrationConnection` records scoped to `corporate` or exactly one branch;
   credentials are Secret Manager references only.
2. Add an immutable `ExternalEventLedger` and `Outbox` rather than writing GHL payloads directly
   from a request/UI action. Store provider, connection, external event/resource IDs, correlation
   ID, received/occurred time, payload fingerprint, ordering version/rule, status and error class.
3. Receive webhooks quickly after signature verification; enqueue processing. Deduplicate by
   provider event ID when present, otherwise approved deterministic fingerprint/idempotency key.
4. Reject unknown location, signature, scope, malformed payload, replay, unsupported event or
   stale transition without mutating commercial state; retain safe audit evidence.
5. Use bounded retry with jitter for transient errors, a dead-letter/review state for terminal
   errors, and reconciliation fetches only through the scoped connection.

The durable inbox commits receipt/fingerprint/connection and outbox work before a 2xx webhook
acknowledgment. If that transaction cannot commit, return a retryable failure. Ordering is event-
specific: provider monotonic version when available; otherwise occurred time plus deterministic
event-ID tie breaker, with ties/late facts retained and reconciliation scheduled rather than
overwriting newer projections. Projection rebuild consumes the append-only ledger deterministically.

## GHL mapping

| Direction | Events/resources | Required mapping |
| --- | --- | --- |
| Inbound | contact, opportunity, appointment/calendar, conversation/activity | `location_id`, external ID, event ID, occurred time, payload version, source and correlation ID. |
| Outbound | estimate/proposal created/sent, proposal signed, verified deposit, handoff readiness | app aggregate/event ID, app lifecycle version, branch location, authorized GHL opportunity/contact reference and idempotency key. |
| Conflict | identity, assignment, stage/value, duplicate/out-of-order delivery | authoritative source rule, compare version/time, retain both facts and route review; never last-write-wins by default. |

The existing visible workflow stages remain `New Lead`, `Contacted / In Conversation`,
`Inspection Booked`, `Inspection Complete / Quoted`, `Won`, and `Lost / Nurture` from the prior
read-only account review. Proposal/payment projection fields/stages must be verified in the
account before any compatibility/migration plan. Vendor guidance requires current Ed25519
`X-GHL-Signature` verification. During the vendor-documented transition only, legacy
`X-WH-Signature` is accepted solely if a read-only Perkins payload inspection proves it is still
emitted; the endpoint always prefers Ed25519, logs legacy use, has a dated sunset no later than
the vendor cutoff of 2026-09-01, and has a test that rejects legacy-only traffic after sunset. No permanent
legacy dependency is designed.

## Payment, retention, compatibility and rollback contract

The payment adapter must identify its provider, authenticated event/verification mechanism,
currency, proposal/invoice reference, branch deposit policy/version and immutable provider
transaction/payment ID before any `Won` transition. It handles insufficient/overpayment,
duplicate, refund, chargeback, stale and branch-mismatch evidence as reviewable states. Read-only
repository discovery establishes app-native billing events as the canonical local ledger and
Knowify as the finance/receivables source for imported payment records; neither is a processor
confirmation contract. A GHL stage or payment object is only authoritative if an account-specific
inspection proves GHL Payments is the processor and identifies its authenticated transaction
object/event. Until such a source contract is verified, the integration is read-only and no
`Won`/handoff transition is permitted.

The adapter maps only the authenticated provider's terminal-success semantics (for example,
captured, succeeded, collected, paid, or settled) to `DEPOSIT_VERIFIED`; it does not hard-code a
provider state name and never maps an authorization. It records immutable transaction/payment IDs
and accumulates independent verified payments against a versioned deposit requirement. Before
handoff, a negative provider event returns the workflow to payment-pending/review. After
irreversible handoff it creates `PAYMENT_EXCEPTION`/`PAYMENT_AT_RISK`, blocks later irreversible
actions, opens remediation/reconciliation and alerts the operational owner without rewriting the
original Won/handoff audit history.

The adapter does not embed legal or contract conclusions. It resolves the approved effective
`CommercialPaymentPolicy` by contract/account context, stores its source/version/effective date,
and applies only deterministic configured values. Policy may define deposit amount/percentage,
qualifying states, cumulative and negative-event treatment, tolerance, exception closure, and
notice content. No applicable policy, ambiguity, or absent required evidence produces a durable
`POLICY_REVIEW_REQUIRED` record and blocks gated action.

Provider authentication, provider-contract-approved terminal-success state, and exclusion of
authorization/pending/CRM/UI/mirror evidence are invariant validation rules, not policy settings.
The resolver uses provider-event occurred time and tenant/branch/contract context, rejects
overlapping or absent publications, persists an applied policy hash and decision instant, and never
retroactively reprocesses an old decision automatically. Policy publications are append-only,
content-hashed, maker-checker approved, supersedable/revocable records.

Revocation prevents new selection, fences/cancels unacknowledged outbox work that used the
publication, and opens `POLICY_REVIEW_REQUIRED`; acknowledged remote history is retained with an
exception/reconciliation record. Only explicit authorized re-evaluation may create a later command.
Invariant validation excludes authorization/pending/CRM/UI/mirror evidence and preserves history;
policy chooses only the listed configurable commercial dispositions.

## Handoff contract boundary

`HandoffEligible` is created only by a conditional commercial decision. The downstream consumer,
authorized dispatcher, idempotency key, acknowledgement payload, retry/reconciliation limit and
compensation action are an external integration contract. Until that contract is authenticated,
the system records local handoff readiness only and does not dispatch remotely. A received remote
acknowledgement is the irreversible boundary; absent/ambiguous acknowledgement remains reviewable.

Raw webhook payloads are encrypted, access-controlled, and retained for 30 days by default;
normalized integration/audit metadata for one year; and financial/payment transaction records
needed for accounting/reconciliation for seven years. Store minimized PI only; never store
secrets, authorization headers, or payment credentials in logs. An identified operational/legal
need may extend retention and an active legal/security hold overrides deletion until released.
Each retained class has a system owner and a deletion/hold audit record. These are engineering
and product baselines, not a legal-compliance claim; legal/privacy validation remains a
pre-production readiness gate.

The retention implementation must classify fields at ingest, start each retention clock at the
documented received/created event, record the legal/security hold authority, scope and release,
and propagate holds to associated raw payload, normalized metadata, derived payment evidence and
backups/restores. A deletion records class, object, clock, hold check and result; restore/key
rotation cannot recreate a deleted object without its applicable hold/audit state. These details
are implementation requirements, not permission to begin implementation.

All schema/API additions are additive and versioned. Existing proposals/payments without GHL
references remain valid; no historical backfill or stage migration is required for read-only
mirroring. Sent/accepted proposal snapshots, estimate revision chains, legacy-quote provenance
and public acceptance tokens keep their existing invariants.

## Rollback

Initial rollout is read-only mirroring behind a feature flag. Reversal disables outbound/outbox
delivery with a monotonically increasing connection generation; workers must not dispatch an old
generation after disable/re-enable. Pending outbound rows become explicitly `cancelled` or
`reconciliation_required`; inbound projections show last-confirmed freshness and can be rebuilt
from the ledger. Rollback never deletes GHL workflows, records, or commercial history. Any later
stage/field migration requires a separate approved rollback plan.
