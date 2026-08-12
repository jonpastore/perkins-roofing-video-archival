-- Make a failed promotion RETRYABLE. `error` was a terminal state nothing could leave.
--
-- jobs/promote_job.py set status='error' on any exception, and both core/scheduler.py::due and
-- the row-claim filtered on status == 'scheduled'. So a single transient failure parked an
-- article permanently: the cron kept running every 15 minutes, kept returning 200, and never
-- looked at the row again.
--
-- Measured in prod 2026-08-12: 277 of 434 scheduled_content rows sat in 'error', every one of
-- them overdue, none pending — 270 for staging and 7 for production. The cause was WordPress
-- auth on the publish call: 401 Unauthorized on 2026-07-27/28, then 403 Forbidden on
-- 2026-08-04 through 08-07. Both were transient (a probe row published cleanly on 2026-08-12),
-- so every one of those 277 articles would have published on a later run if anything had been
-- willing to try again.
--
-- `attempts` bounds the retry so a genuinely broken row still stops rather than hammering
-- WordPress every 15 minutes forever: promote retries an errored row until attempts reaches
-- PROMOTE_MAX_ATTEMPTS, after which it stays error and is left alone.

ALTER TABLE scheduled_content ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;

-- Index the retry predicate: the promoter scans (tenant, status) already, and the retry check
-- adds attempts to the same lookup.
CREATE INDEX IF NOT EXISTS ix_scheduled_content_status_attempts
    ON scheduled_content (tenant_id, status, attempts);
