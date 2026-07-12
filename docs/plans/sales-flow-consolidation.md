# Sales Flow Consolidation Plan (Ralplan)

## Phase 0 — Planning gate
- Inventory current UIs/routes/models.
- Identify canonical surfaces and non-goals.
- Run planner/critic pass before implementation.

## Phase 1 — UI consolidation, no schema changes
- Rename sidebar labels:
  - `estimator` tab becomes `Estimate Calculator` or hidden behind canonical `Estimates`.
  - `quoting` tab becomes canonical `Estimates` workflow.
- Preserve old route keys for backward compatibility, but remove duplicate sidebar entries.
- Merge `ProposalBuilder` into `Proposals` as an in-page create drawer/modal.
- Add a `Legacy Quotes` tab/filter inside `Proposals` using existing `/quotes` read-only API.
- Add "Create proposal from quote" action that prefills the proposal drawer from `/quotes/{id}`.

## Phase 2 — API composition / promotion helpers
- Add a bounded backend adapter that maps Knowify quote detail to a native proposal draft payload.
- Prefer creating native `Proposal` rows with `quote_snapshot.source = "knowify_import"`.
- Idempotency key: tenant + Knowify `contract_id` stored in `quote_snapshot.source_ref` (no schema change first slice).
- If duplicate source_ref exists, return the existing draft instead of creating another.

## Phase 3 — Estimates canonicalization
- Keep pricing engine and customer-linked quoting flow; retire duplicate quick calculator from sidebar.
- If a quick calculator remains, embed it as an "Unattached quick estimate" mode inside the `Estimates` page.
- Attach manual measurements to `property_id` when created from the customer/property flow.

## Phase 4 — Discounts
- Design-first; not a blind edit.
- Add `discount_type: amount|percent`, `value`, reusable preset catalog.
- Percent base = pre-discount included-line subtotal.
- Convert percent to dollars once when snapshotting the proposal; invoices consume the frozen dollar line.
- Add golden money tests before schema migration.

## Phase 5 — e-sign FQDN / Cloudflare
- Token source: GCP Secret Manager `cloudflare-api-token`.
- Terraform manages DNS/WAF where possible.
- Add `sign.perkinsroofing.net` as a DNS record and app config (`SIGN_PUBLIC_URL`).
- Public sign routes served by the SPA; API accept endpoints remain token-gated.
- Rollback: remove DNS record / unset SIGN_PUBLIC_URL; old app-origin links continue to work.
- Do not proxy/sign traffic until cert/WAF verified.

## Phase 6 — Roofr + appointment webhook
- Roofr import: create an adapter route/job that creates/updates Measurement rows with property linkage.
- Appointment webhook: signed/idempotent endpoint creates or updates Lead/Customer + Contact + Property candidate.
- No unauthenticated side effects without signature/idempotency.

## Test matrix
- Proposals page create drawer renders and submits existing native proposal payload.
- Legacy quote list appears under Proposals; detail import creates proposal snapshot.
- Quote import idempotency prevents duplicate native proposals.
- Sidebar has no Quotes/New Proposal duplicate entries after consolidation.
- Existing `/quotes` route remains available for backward compatibility.
- Estimate workflow still produces pricing; quick calculator not lost.
- Cloudflare plan can read token and identify zone without exposing secret.
- e-sign link base honors `SIGN_PUBLIC_URL` when set.

## Risks / rollback
- Money-risk: discounts and invoice effects deferred until tested.
- DNS-risk: plan/apply with token is non-destructive for CNAME add; rollback deletes record.
- UX-risk: hiding old tabs could confuse users; route keys remain accessible and redirects can be added.
- Data-risk: legacy quote promotion uses snapshot only; no destructive mutation of KnowifyRawRecord.

## Planner/Critic pass
### Planner stance
Unify via composition first. Avoid model/migration churn until the UI and snapshot semantics are proven. Preserve source systems and add promotion adapters.

### Critic stance
Potential failure modes:
- Hiding the quick calculator may remove a useful standalone workflow.
- Mapping Knowify contracts to native proposals without stable customer/property crosswalk can create bad proposals.
- `quote_snapshot.source_ref` idempotency without an indexed column could be slow or ambiguous.
- `sign.perkinsroofing.net` may require Firebase custom-domain auth/cert steps, not just DNS.
- Discounts cannot be safely added without a migration and invoice golden tests.

### Revisions from critic
- First implementation slice keeps quick calculator code and only changes sidebar/canonical page composition.
- Quote promotion requires operator confirmation of customer/property before create.
- Use `quote_snapshot` idempotency as first-slice; add indexed crosswalk migration only after usage stabilizes.
- DNS work separated into plan/verification first; no destructive Cloudflare changes in the same slice as UI consolidation.
- Discounts remain spec/design until money tests and migration are agreed.
