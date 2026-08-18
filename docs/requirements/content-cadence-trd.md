# TRD: Content cadence

Status: **implemented-local**. Modes are `off` | `dump` only. Freshness was removed
(it could not select stale pillars). Persist writes drafts; no ScheduledContent.

## Config keys (`api/routes/config.py` EDITABLE_KEYS)
- `CONTENT_GEN_MODE` default off
- `CONTENT_DUMP_PER_RUN` default 10
- `CONTENT_DUMP_CLUSTERS` default 2
- `CONTENT_TARGET_FRACTION` default 0.5
- `CONTENT_FRESHNESS_PER_DAY` default 1
- `CONTENT_FRESHNESS_BUDGET` default 10

## Interfaces
- `core.content_cadence.cadence()` / `should_stop_dump` / `read_mode`.
- `jobs/daily_content_job.py` honors mode (dump / freshness / off).
- `jobs/batch_article_job.py` `persist` mode; Vertex via `chat`, not `_ensure_chat`.
- `jobs/prime_content.py` one-shot primer.

## Tests
- `tests/core/test_content_cadence.py`
- `tests/jobs/test_daily_content_job.py` mode branches
