# DDD: Content cadence

Status: **implemented-local**

## Domain
- **Dump** = create new pillar campaigns.
- **Freshness** = write on an existing open/stale pillar.
- **Potential** = catalogue of what could be written; fraction is generated/potential.

## Decisions
- PlatformConfig wins, then env, then defaults — same idiom as CompanyCam tag ids.
- Prime is a manual job, not the cron, so a huge first batch is operator-triggered.
