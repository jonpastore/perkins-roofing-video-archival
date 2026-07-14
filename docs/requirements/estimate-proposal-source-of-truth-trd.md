# TRD: estimate-linked proposals

## Data
- estimates: optional parent_id, root_id, version_number, source_proposal_id.
- proposals: optional estimate_id.
- quote_snapshot must include estimate_id, estimate_result, estimate_input, recommended_tier when created from Estimates.

## API
- POST /estimator/quote accepts discounts, selected_tier, parent_estimate_id, source_proposal_id.
- Response includes estimate_id, estimate_version, pre_discount_total when discounts are applied.
- POST /quoting/proposals accepts estimate_id and persists it.

## UI
- Estimates search must call /quoting/customers?search=... instead of browser filtering only.
- Estimates must expose key pricing inputs and discounts.
- Create proposal must include estimate linkage and recommended tier.
