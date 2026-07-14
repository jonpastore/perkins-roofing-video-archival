# Plan: estimate-linked proposal source of truth

1. Add persistence links: estimate revision metadata and proposal.estimate_id.
2. Return estimate id/version from /estimator/quote.
3. Support discounts in estimate calculations so total/margin reflect concessions.
4. Send estimate_id and estimate snapshot metadata when creating proposals from Estimates.
5. Add Estimates UI fields for major pricing drivers and selected/default tier.
6. Keep proposal UI native-tier-safe and amount-safe.
7. Verify with focused backend/UI tests, build, deploy, and keep PDF backfill running.
