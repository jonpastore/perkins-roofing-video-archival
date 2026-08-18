# PRD: Content cadence

Status: **implemented-local**

## Requirements
- Dump: huge first pass (N pillars × M supporting) then stop at the configured fraction.
- Freshness: **not implemented**. Do not enable `CONTENT_GEN_MODE=freshness` expecting
  stale-pillar rewrites. Architect/critic 2026-08-18: after dump it is a green no-op.
- Off: cron is a no-op.
- Generated rows stay drafts/scheduled until a human (or a later publish job) ships WP.

## Acceptance
- Mode `off` writes zero articles.
- `should_stop_dump` is true at/above the fraction and false below.
- Freshness does not invent new pillars.
