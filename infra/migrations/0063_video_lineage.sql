-- Chopped YouTube clips must point at the long original so ingest / topics /
-- FAQs / article suggestions do not treat the slices as new source material.

ALTER TABLE videos ADD COLUMN IF NOT EXISTS parent_video_id TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS derived_urls JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS ix_videos_parent_video_id ON videos (parent_video_id)
    WHERE parent_video_id IS NOT NULL;
