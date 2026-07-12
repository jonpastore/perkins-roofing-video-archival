# Sales Flow Consolidation PRD

## Must
- One visible `Estimates` entry for the customer/property/measurement estimate workflow.
- One visible `Proposals` entry containing list + create + legacy quote candidates.
- Existing native proposals remain visible and sendable.
- Legacy Knowify quotes/contracts are accessible from Proposals.
- Creating from a legacy quote must prefill title/customer/property/scope where possible and preserve source metadata.
- E-sign link generation must be configurable for `sign.perkinsroofing.net`.

## Should
- Customer detail should show estimate/proposal/invoice/payment status rollup.
- Estimate records should attach to customer/property and support multiple estimate configurations per property.
- Reusable discounts should support amount and percent.

## Won't in first slice
- Live QuickBooks write integration.
- Destructive Knowify record mutation.
- Full DNS cutover/NS migration.
