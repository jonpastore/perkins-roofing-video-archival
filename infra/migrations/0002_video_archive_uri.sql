-- Wave 3: add the source-video archival URI column to the existing videos table.
-- create_all() only creates missing tables, not columns on existing ones, so an
-- established DB needs this ALTER. Idempotent.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS archive_uri VARCHAR;
