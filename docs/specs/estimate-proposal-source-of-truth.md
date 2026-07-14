# Estimate-linked proposal source of truth

## Why
Sales users expect proposal amounts, tiers, discounts, and margin warnings to come from an estimate, not from an unrelated proposal text editor. Editing or revising pricing must preserve auditability: what estimate inputs changed, what margin changed, and which proposal revision used that estimate.

## What
- Estimates are immutable calculation records and may be linked as revisions.
- Proposals can reference the estimate that generated them.
- Proposal snapshots carry estimate inputs/results, default/recommended tier, discounts, and totals.
- Customer search in Estimates is server-side across all customers.
- Proposal editing must preserve native tier totals instead of converting estimate-created proposals into legacy Knowify snapshots.

## Users
- Sales: create estimate, select package/tier, apply discounts, generate proposal.
- Admin/Estimator: inspect margin drivers and pricing config hash.
- Customer: select Good/Better/Best at signing.

## Constraints
- Do not mutate sent/accepted proposal snapshots in-place; use revisions.
- Preserve Knowify-import legacy proposal values.
- No secret material in code.

## Non-goals
- Full Roofr measurement import implementation.
- Perfect material-cost modeling for Good/Better/Best; package multipliers remain a bridge until package BOMs are configured.
