-- 0028: video availability tracking — additive columns only, no data loss.
--
-- Two nullable timestamp columns added to the videos table:
--
--   unavailable_since  — set to NOW() when a KPI poll batch returns stats for
--                        other videos but not this one (deleted or made private
--                        on YouTube). Cleared back to NULL if the video later
--                        reappears (e.g. re-published). NULL = available or not
--                        yet determined.
--
--   hidden_at          — set to NOW() by the POST /{video_id}/hide endpoint
--                        (requires manage_archive role). Cleared by /unhide.
--                        The GET /archive/videos list excludes hidden rows by
--                        default; pass ?include_hidden=true to include them.
--
-- The GCS archive copy is NEVER deleted by either mechanism.
-- RLS policy is inherited from the existing table (tenant_id isolation).

ALTER TABLE videos
    ADD COLUMN IF NOT EXISTS unavailable_since TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS hidden_at         TIMESTAMP NULL;
