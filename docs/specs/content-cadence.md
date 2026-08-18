# Spec: Content cadence

Status: **implemented-local** (not on `origin/main`). Architect + critic: **do not ship**
until freshness is real or removed, and persist stays off ScheduledContent (fixed 2026-08-18).

## Why
Operators want a large initial dump of pillars + supporting articles, then a daily
freshness drip — as config, not a one-off script.

## What
`CONTENT_GEN_MODE`: `off` | `dump` | `freshness`. Dump creates pillar campaigns + clusters
until `CONTENT_TARGET_FRACTION` of potential is generated. Freshness writes N articles/day
on open pillars until the budget is spent. Persist drafts; do not auto-publish to WordPress.

## Non-goals
- 50% dump until the prime batch is reviewed.
- Replacing Wendy/WP publish (still blocked on staging/prod app password until 2026-08-18).
