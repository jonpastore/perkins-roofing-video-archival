-- Make an INTERRUPTED promotion recoverable. "promoting"/"publishing" were orphan states.
--
-- 0058 fixed the case where a promotion FAILED: `error` became claimable and `attempts` bounds
-- the retry. This is the case one step earlier — where the promotion never got to fail, because
-- the process died holding the claim.
--
-- jobs/promote_job.py claims a row by setting status='promoting'; jobs/social_job.py claims by
-- setting status='publishing'. core/scheduler.CLAIMABLE is ('scheduled', 'error'), so neither of
-- those two states is ever selected again. Both jobs release the claim on an EXCEPTION —
-- promote's `except` sets status='error', social's `finally` reverts to 'awaiting_social' — so
-- the exposed case is the process being KILLED rather than raising:
--
--   * a Cloud Run revision swap mid-render/mid-publish,
--   * an OOM (render/ingest run in memory-backed /tmp and social pulls signed media),
--   * /internal/promote outliving its request timeout on the API service.
--
-- In every one of those the row is left in 'promoting'/'publishing' with `attempts` NEVER
-- incremented, invisible to all future runs, while the job that survives reports success. That is
-- exactly the shape of the 277-row incident 0058 addressed, one state further along — and it is
-- the more dangerous shape, because 0058's `attempts` counter cannot even see it.
--
-- A status column alone cannot distinguish "a live sibling holds this claim" from "a dead run
-- held this claim", and promote runs every 15 minutes while a long render can overlap. That
-- distinction needs a TIMESTAMP, which is what this adds: the claim stamps claimed_at, and a row
-- still claimed well past any plausible runtime is reaped back to a claimable state with attempts
-- incremented, so a genuinely wedged row still stops at PROMOTE_MAX_ATTEMPTS instead of looping.
--
-- NULL default is deliberate: existing rows have no claim, and NULL reads as "not claimed" rather
-- than as "claimed at the epoch", which would make every historical row instantly reapable.

ALTER TABLE scheduled_content ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP NULL;

-- The reaper's predicate: find rows sitting in an in-flight state past the staleness threshold.
-- Partial index — only in-flight rows are ever scanned this way, and they are a tiny minority.
CREATE INDEX IF NOT EXISTS ix_scheduled_content_stale_claims
    ON scheduled_content (status, claimed_at)
    WHERE status IN ('promoting', 'publishing');

-- Recovery: release rows already stranded by this bug before the reaper existed.
--
-- ⚠️ THE claimed_at GUARD IS LOAD-BEARING AND IS NOT DECORATION. This runner has NO LEDGER — it
-- re-executes every migration from 0013 on EVERY run (see scripts/apply_migrations_adc.py). An
-- unguarded `WHERE status IN ('promoting','publishing')` would therefore fire again on every
-- future migration run and release claims that a LIVE job is holding right then, causing exactly
-- the double-publish the claim exists to prevent. The docstring in that script names this failure
-- mode explicitly ("an UPDATE without a WHERE guard re-asserts its original value on every run").
--
-- With the guard the statement is replay-safe and matches core.scheduler.stale_claims: only a
-- claim older than the staleness threshold — or one with no stamp at all, i.e. stranded before
-- this migration existed — is released. A claim taken seconds ago is untouched.
--
-- attempts is incremented so a row that keeps wedging still converges on PROMOTE_MAX_ATTEMPTS
-- rather than retrying forever.
UPDATE scheduled_content
   SET status   = CASE WHEN status = 'publishing' THEN 'awaiting_social' ELSE 'error' END,
       attempts = COALESCE(attempts, 0) + 1,
       claimed_at = NULL
 WHERE status IN ('promoting', 'publishing')
   AND (claimed_at IS NULL OR claimed_at < (now() AT TIME ZONE 'utc') - interval '30 minutes');
