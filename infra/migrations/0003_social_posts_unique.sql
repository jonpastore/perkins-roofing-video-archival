-- Migration 0003: unique index backing the per-platform idempotency guard
-- Prevents double-posting when a worker crashes mid-loop and retries.
-- SQLAlchemy UniqueConstraint("series_id","part","platform") on SocialPost maps
-- to this index; CREATE TABLE IF NOT EXISTS (via create_all) picks it up on fresh
-- databases. Run this on existing prod schemas that pre-date the constraint.

CREATE UNIQUE INDEX IF NOT EXISTS uq_social_series_part_platform
    ON social_posts (series_id, part, platform);
