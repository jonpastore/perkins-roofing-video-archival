# Spec: GHL lifecycle integration

Status: DRAFT — reconciled from product-owner decisions; no implementation approval

## Why

The revenue-risk experience needs timely, auditable projections of lead, appointment,
proposal, deposit, and handoff status without making the client or GHL a second
commercial-record authority.

## What

Integrate the app with one corporate GHL location and one location per branch. GHL owns
communications, calendars, appointments, and pre-quote opportunity automation. The app owns
customer/contact/property structure, estimates, proposals, verified payment facts, commercial
records, and revenue-risk projections.

## Scope

- Receive and reconcile contact, opportunity, appointment, and conversation/activity events.
- Publish app-owned estimate/proposal, signed, verified-deposit, and handoff facts to GHL.
- Preserve an immutable cross-system event ledger, branch/location mapping, retries, conflicts,
  and operator-visible health.
- Support the approved risk/SLA model and role-scoped views in `.ux-review/03-ux-strategy.md`.

## Non-goals

- Replacing GHL, syncing post-sale project execution, or configuring a live GHL account.
- Treating CallRail as an approved dependency.
- Letting a GHL stage, client action, payment link, or automation alone mark a sale Won.

## Sender-identity policy analysis

Where it matters: initial acknowledgments, appointment reminders/recovery, no-show recovery,
quote follow-up, and long-term nurture. The approved policy is team identity rather than a named
individual, except where an existing approved workflow explicitly requires an individual.

Approved product-owner policy: automated messages identify `Perkins Roofing — <Branch> Team`.
When branch identity is unavailable or inappropriate, they identify `Perkins Roofing Team`.
An individual employee is never exposed as the sender unless an existing approved workflow
explicitly requires it. Human messages identify their actual sender. This is scalable, avoids
implying a person authored automation, and keeps reply routing attributable.

Acceptance for any chosen policy: every automated message renders the configured identity and
branch context, has an auditable template/version/actor-or-system source, and cannot use a
personal sender identity unless that configuration is explicitly approved and server-authorized.
`From` identifies the approved team/personal identity; `Reply-To` must route to the authorized
branch inbox or assigned human workflow. Stale/missing branch configuration falls back to the
team identity and does not send a personal identity. Template approval, revocation, consent/
opt-out handling and reply-routing failures create an auditable failed/review state.

## Payment-source hierarchy

Read-only repository discovery establishes the current hierarchy: app-native billing events are
the canonical local commercial ledger; Knowify is the finance/receivables source for imported
invoices and payments. The existing app exposes manual, idempotent payment recording and a
Knowify mirror, but no processor adapter or authenticated provider settlement event. A GHL stage,
payment link, or mirrored payment row is therefore not proof for `Won` or handoff. Until an
authenticated source contract is evidenced, the integration remains read-only and proposals stay
`Accepted — payment pending`. At implementation, the selected source must preserve the immutable
provider transaction/payment ID and support idempotent webhook/reconciliation processing.
