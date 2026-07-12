# Sales Flow Consolidation Spec

## Intent
Unify the sales workflow into one coherent operator path:

1. Customer first.
2. Property/contact/measurement attached to the customer.
3. Estimate generated against that customer/property.
4. Proposal created from an estimate or imported legacy quote.
5. Proposal sent to a public e-sign surface.
6. Accepted proposal becomes invoice/milestone/payment workflow.

## Current user-visible defects
- `Estimator` and `Estimates` are separate/confusing UIs.
- `Quotes` is a separate legacy Knowify view; quote data is not visible in native Proposals.
- `New Proposal` is separate from the Proposals list.
- Knowify proposals/contracts are imported as read-only quotes and do not appear in Proposals.
- Discounts support amount-only and are not reusable.
- Public e-sign uses the app origin, not `sign.perkinsroofing.net`.
- Roofr import and appointment webhook are not wired into customer/property creation.

## Non-goals for first deploy slice
- Do not delete legacy routes; preserve backward compatibility.
- Do not rewrite the money core without golden tests.
- Do not perform destructive DNS changes or Cloudflare NS migration.
- Do not live-sync QuickBooks payments yet; keep stubs/seams.

## Users
- Sales/admin users need one flow, not several parallel tabs.
- Customers need a focused signing surface.
- Operators need imported Knowify quote/proposal history visible where they work now.

## Success criteria
- Sidebar exposes one `Estimates` tab and one `Proposals` tab for the sales path.
- Proposals page can create a new proposal in-place.
- Proposals page can show/import legacy Knowify quotes/contracts as proposal candidates.
- New proposal form can prefill from a legacy quote/contract.
- `sign.perkinsroofing.net` DNS/IaC plan is prepared with rollback and token sourcing.
- Tests enumerate conversion, routing, and safety cases.
