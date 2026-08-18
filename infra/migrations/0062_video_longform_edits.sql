-- Track long-form YouTube videos that have already been chopped / re-uploaded
-- so the >10min work list does not offer the same source twice.

ALTER TABLE videos ADD COLUMN IF NOT EXISTS longform_reprocessed_at TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS longform_note TEXT;
