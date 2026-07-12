# Sales Flow Consolidation DDD

## Domain terms
- Customer: buyer/account.
- Property: physical roof location.
- Measurement: roof measurement data linked to a property.
- Estimate: internal pricing calculation/configuration.
- Proposal: customer-facing frozen offer/version with e-sign lifecycle.
- Legacy Quote: Knowify contract/proposal imported read-only from Knowify.

## Invariants
- A Proposal must have customer_id and property_id.
- Proposal quote_snapshot is immutable once sent.
- Legacy quote import must be idempotent by source/source_ref.
- Discounts in proposals/invoices must be frozen as explicit dollar lines before billing.
- Public accept links must be unguessable and single-transaction accepted.

## Aggregates
- Customer aggregate: contacts, properties, measurements, estimates, proposals, invoices, payments rollups.
- Proposal aggregate: root/version chain, events, accept token, quote snapshot.
- LegacyQuote projection: KnowifyRawRecord contract + deliverables + project address.
