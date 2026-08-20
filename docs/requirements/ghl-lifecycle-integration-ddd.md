# DDD: GHL lifecycle integration

Status: DRAFT — external contract details marked explicitly

## Authority and identity

| Concept / field | Authority | App behavior |
| --- | --- | --- |
| App customer, contacts, properties, estimates, proposals, invoices, verified payments | App | Immutable commercial history and controlled revisions remain canonical; app-native billing events are the local commercial ledger. |
| Imported Knowify invoice/payment facts | Knowify | Current finance/receivables source for imported records; preserve `knowify_payment_id`, but do not treat a mirrored row as processor-authenticated deposit confirmation. |
| GHL location, contact ID, opportunity ID, calendar/appointment ID, conversation/activity ID | GHL | Store an external reference scoped to one connection; never infer cross-branch ownership. |
| GHL pre-quote opportunity fields (pipeline, stage, owner, status, value) | GHL | Mirror only mapped pre-quote facts; every outbound app projection carries origin/correlation ID and lifecycle version. Reflected inbound event matching its origin is acknowledged/deduplicated, not republished. Unmatched/stale/conflicting facts enter review. |
| Contact email/phone from GHL | App identity graph; GHL is operational projection/source | Add or update only an unambiguous mapped fact. GHL merge/delete never destroys or merges canonical app identity; preserve aliases, provider IDs and correlation history and queue deterministic reconciliation otherwise. |
| Communication and appointment facts | GHL | Mirror source/time/external ID; do not let them overwrite commercial state. |
| Proposal signed, deposit verified, handoff | App/payment provider | Publish projection to GHL only after server transition succeeds. |

## Capability × action × data-scope matrix

The existing server has coarse roles (`admin`, `web_admin`, `sales`, `platform_admin`). This
matrix is the target composable policy; it does not claim the current role matrix implements it.

| Target role/capability | Allowed data scope | Conditions |
| --- | --- | --- |
| Branch operator: view/update owned revenue work, contacts, appointments, attempts | OWN / BRANCH | Assigned or branch-granted; no cross-branch export. |
| Branch manager: assign/reassign, view branch queue/metrics, branch-hours configuration | BRANCH | Changes constrained by corporate-approved bounds and audited. |
| Estimator/sales: create/revise pre-proposal estimates and drafts | BRANCH | Customer/property scope; sent/signed artifacts use revision/change-order flow. |
| Finance/payment operator: view payment facts, initiate allowed collection actions | BRANCH | Cannot verify provider event or transition Won without server evidence. |
| Corporate executive/cross-branch operations: aggregate/report and authorized drill-down | CORPORATE / selected BRANCH | Explicit grant, aggregate-first default, audited PII drill-down; Chris grant must have owner/review/expiry. |
| Product admin: users, branches, policy/pricing configuration | TENANT / CORPORATE | Cannot read secrets, raw platform logs or bypass tenant scope. |
| Platform admin: connection health, secrets-adjacent remediation, raw diagnostics, tenant/SSO | SYSTEM | Separate from corporate reporting; no operational customer data absent an audited support scope. |
| Public recipient: proposal acceptance | single token-bound proposal | High-entropy token, no list/search/tenant data. |

### Authorization realization and migration

Authorization is deny-by-default. A request is allowed only when its effective tenant, branch
grant, capability and object scope all allow it; an explicit deny/revoked/expired grant wins over
an allow. Existing `admin`, `web_admin`, `sales` and `platform_admin` roles remain backward-
compatible coarse grants until a migration assigns the target capabilities. The migration is
additive and auditable: default no new cross-branch access; each corporate/cross-branch grant
has issuer, reason, selected branches/capabilities, issued/reviewed/expires timestamps and
revocation event. Existing `platform_admin` remains system-scoped and cannot silently acquire
operational/customer access. Tests must cover direct API, stale session/grant, revoked grant,
same-tenant wrong-branch and cross-tenant denies.

| Object / operation | Branch operator | Branch manager | Corporate/cross-branch | Product admin | Platform admin |
| --- | --- | --- | --- | --- | --- |
| Risk/customer/contact: read/list | OWN/BRANCH | BRANCH | aggregate; selected BRANCH drill-down | no by default | no by default |
| Risk/activity: create/update | OWN assignment | BRANCH | selected BRANCH only | no | no |
| Assignment/escalation | no | BRANCH | selected BRANCH | no | no |
| Estimate/proposal draft: create/revise | BRANCH | BRANCH | selected BRANCH review | pricing-policy only | no |
| Signed proposal/payment/handoff transition | no direct transition | no direct transition | no direct transition | policy only | no direct transition |
| Finance export/reconciliation | no | branch aggregate only | CORPORATE + selected BRANCH | no | no |
| Grant/policy management | no | hours within bounds | no | TENANT/CORPORATE | SYSTEM only |
| Integration/log/raw diagnostic | record sync state only | branch health summary | corporate health summary | configuration status | SYSTEM, audited |

## DOM-GL state rules

`Captured → Assigned → Attempted → Connected → Inspection booked → Inspection complete/quoted → Proposal sent → Accepted/payment pending → Won/deposit received → Handoff`.

`Lost` and `Disqualified` require a context-specific reason; they do not erase events. Activity,
lifecycle and risk are separate dimensions.

| ID | Event and preconditions | Result / side effects |
| --- | --- | --- |
| DOM-GL-01 | GHL event has known branch connection, unique external event identity and non-stale version. | Append ledger event; update projection only if ordering rule permits; otherwise retain as ignored/conflict. |
| DOM-GL-02 | Human attempt has authenticated actor, allowed scope and idempotency key. | Append confirmed attempt; compute follow-up, never locally clear SLA. |
| DOM-GL-03 | Contact conflict, GHL merge/delete, or cross-system consent disagreement has nonmatching/ambiguous identity or state. | Preserve aliases/provider IDs/correlation and source facts; create deterministic authorized reconciliation; no canonical overwrite/delete/merge. For a messaging channel, enforce the most restrictive applicable consent/opt-out until reconciliation completes. |
| DOM-GL-04 | SLA clock needs a branch-local instant. | Evaluate with branch IANA timezone, approved hours/holiday calendar and next-open calculation; persist the due instant in UTC plus policy version. |
| DOM-GL-05 | A provider-confirmed financial event is evaluated only under the approved effective policy for its contract/account context. | Policy determines qualifying states, cumulative treatment, tolerances and negative-event handling. Missing/ambiguous policy produces `POLICY_REVIEW_REQUIRED`; no commercial transition is inferred. Historical payment/handoff events are immutable. |
| DOM-GL-06 | Appointment/calendar event comes from known connection and order rule permits it. | Update appointment projection only; preserve prior lifecycle/risk unless a separately authorized domain rule applies. Failed/revoked events are retained for review. |
| DOM-GL-07 | Assignment/reassignment comes from authorized actor or mapped GHL owner and has a current assignment version. | Append assignment event, create/recalculate SLA owner/due state and notify; stale/concurrent assignment loses to compare-and-set and is visible for retry. |
| DOM-GL-08 | Reminder/escalation evaluates an open due work item under its policy version. | Deliver or record failed delivery idempotently; never treat email send as acknowledgment. Escalation remains open until confirmed activity/terminal state. |
| DOM-GL-09 | Lost/Disqualified is selected by authorized actor with required context-specific reason. | Append terminal event and retain reason/note; invalid reason, stale state or later duplicate does not erase recovery/audit history. |

### Calendar semantics

The branch record owns an IANA timezone and approved business-hours/holiday calendar. Compute
business minutes in that timezone; persist every deadline as UTC instant plus branch timezone,
policy version and calculation input. A nonexistent local time advances to the next valid local
instant; an ambiguous fall-back time uses the later offset. Deadlines already created retain the
policy version that created them unless an authorized policy-change job explicitly recalculates
and audits them. Reassignment changes the owner atomically but not the original elapsed-clock
history; the new owner receives the remaining due time or an immediate overdue escalation.

The first-human-attempt numerator is a server-confirmed `DOM-GL-02` event with an allowed
channel and authenticated actor. Its denominator is every nonterminal captured lead assigned to
the measured branch whose clock opened in the cohort; exclude only leads with a recorded
Disqualified reason before the clock opens, and publish exclusion counts. Missing assignment
creates an immediate manager exception. Branch closure/holiday overrides use the approved calendar
version; late external events use received time for processing but recorded occurred time for
analysis, with clock-skew flags rather than silently moving an already-calculated deadline.

## External GHL contract discovery status

### Payment-evidence boundary

The current `Payment` row and imported Knowify facts are records, not eligible settlement proof.
The future payment adapter must create immutable settlement evidence keyed by
`provider + connection + provider_transaction_id`, bind it to one proposal/payment intent,
invoice, branch, currency, required-deposit amount and policy version, and reject a key replay
whose request fingerprint or binding differs. A single provider transaction cannot satisfy two
allocations. Cumulative/partial deposits, reversals/refunds/chargebacks, rounding and a policy
change are explicit reviewable states. Provider-specific terminal-success semantics map to
`DEPOSIT_VERIFIED`; authorization never does. Before handoff, a negative event returns the
workflow to payment-pending/review. After irreversible handoff, it preserves historical truth and
sets `PAYMENT_EXCEPTION`/`PAYMENT_AT_RISK`, blocks later irreversible actions and opens an
alerted remediation task.

Lifecycle, financial condition, and handoff are separate append-only aggregates. A conditional
transition creates exactly one handoff outbox command with lifecycle/financial versions; the
irreversible boundary is the recorded remote acknowledgment carrying its idempotency key. A
negative provider event before enqueue cancels the command; after enqueue it fences dispatch by
version; after acknowledgement it records an exception without rewriting history. Duplicate or
reordered negative events deduplicate to one remediation task. Exact cumulative allocation,
policy values are external configuration. A `CommercialPaymentPolicy` is immutable and effective
dated, carrying required deposit, qualifying provider states, cumulative treatment, refund/reversal/
chargeback/dispute treatment, rounding/currency tolerance, remedial repayment, exception closure
roles/evidence/reason, and externally supplied cancellation/notice content. The policy source ID,
version, effective interval, approver and applied decision are auditable. Missing, conflicting, or
out-of-range policy yields `POLICY_REVIEW_REQUIRED` rather than an inferred commercial/legal result.

Non-configurable invariants: only an authenticated provider event whose state is approved by the
provider contract may qualify; an authorization, pending state, CRM stage, UI state, or mirror
never qualifies. Policy selects only from that contract-approved terminal-success set. The lookup
key is tenant, branch, contract/account context and provider-event occurred instant; it selects one
non-overlapping published policy range. Store the applied immutable policy publication hash and
decision instant. Policies are append-only publications with creator, separate approver, timestamps,
canonical content hash, supersedes/revokes relation and effective interval. No retroactive automated
re-evaluation occurs; resolving `POLICY_REVIEW_REQUIRED` requires an authorized explicit re-evaluation
that snapshots current evidence and creates a new conditional outbox command.

`PAYMENT_EXCEPTION` is operational only: its configured closure rule requires authorized actor,
reason/disposition, timestamp, required evidence, related provider transaction IDs and audit trail.
Closure never rewrites historic payment or handoff facts.

Policy revocation is a first-class append-only event. A revoked publication is never selected for a
new decision. Revocation cancels only `not_dispatched` commands. A `dispatch_attempted` command
with absent/ambiguous acknowledgement becomes `ACKNOWLEDGEMENT_UNKNOWN`: it is frozen, queried by
idempotency key, and cannot retry/re-evaluate until reconciliation establishes remote outcome.
First committed local acknowledgement versus revocation wins by compare-and-set version; a remote
ack observed after local revocation is retained as historical truth and opens reconciliation. A
later decision requires explicit authorized re-evaluation on the same command lineage.

`POLICY_REVIEW_REQUIRED` is a role-scoped operational work item, showing non-sensitive reason,
policy publication hash, affected command/evidence, owner and permitted re-evaluation action. It
is keyboard/mobile accessible, auditable and never exposes secrets or raw restricted payloads.

| Non-configurable invariant | Policy-configurable disposition |
| --- | --- |
| Authorization/pending/CRM/UI/mirror never proves payment; missing policy blocks action; history is immutable. | qualifying contract-approved terminal states, deposit/netting/tolerance, negative-event review disposition, exception closure evidence/roles. |
| A post-acknowledgement negative event never rewrites handoff history. | whether the event triggers review, exception severity, and later remediation under approved policy. |

### Identity and consent reconciliation baseline

Canonical identity is a tenant-global Person with separately scoped branch operational
relationships. External references are unique by tenant+provider+connection+resource_type+external_id;
a cross-branch match
may link to the same Person only through an authorized, audited relationship and otherwise remains
an isolated review item. Normalize email and phone only for candidate matching; an exact verified
external reference plus one unambiguous canonical identity permits a mapped update, otherwise
create a conflict. Alias/tombstone facts are append-only and retain source event ID, version,
occurred/received time, actor and reason.

Consent is an immutable per-channel, per-identity-or-alias fact: `UNKNOWN`, `OPTED_IN`,
`OPTED_OUT`, `REVIEW`. `OPTED_OUT` and `UNKNOWN` block send; the most restrictive applicable fact
wins. A stale/replayed event cannot relax consent; only an authorized, newer reconciliation with
auditable evidence can do so. Transactional-versus-marketing classification and GHL field semantics
remain implementation-contract evidence; Person scope is approved tenant-global.

### External-state containment and reconciliation

Inbound GHL `Won` is never a commercial transition. Until the app has emitted the correlated,
verified-deposit projection, it is retained as a discrepancy and no app handoff or GHL-originated
customer-facing post-job action is treated as authorized. Account discovery must inventory every
Won trigger, actor, workflow and legacy client; implementation then requires an approved
server-controlled write/permission/compensation strategy.

For each external resource type, the adapter specifies connection-scoped read authority,
watermark/cursor, overlap/replay window, maximum recovery lag, ordering source, paused-delivery
detection, and a manual-recovery record. Reconciliation retains late/unknown/conflicting facts
without overwriting the newer projection.

Public vendor documentation verifies that locations, contacts, opportunities, calendars/appointments,
OAuth scopes and webhooks exist, and that webhook IDs/retries/signatures must be handled. The exact
Perkins field IDs, pipeline/stage IDs, workflow dependencies, current connection health and app
installation scope are `EXTERNAL_ACCESS_REQUIRED`. A prior automation trace exposed the GHL
password; that is compromise evidence, so the current credential must not be reused and rotation
is a pre-production security gate before any further account access. No undocumented field, stage,
or workflow change is authorized.
