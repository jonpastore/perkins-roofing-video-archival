-- 0045_article_source_videos.sql
-- Persist which of Tim's videos each article was built from — the video<->article side of the
-- content-hub linkage the DB is meant to be the source of truth for ("what videos and topics are
-- linked to what articles" = our progress and state).
--
-- aggregated_topics already maps each harvested topic -> the video_ids that discuss it, and an
-- article's focus_keyword IS its topic (aggregated_topics.canonical_label, lower-cased). So the
-- linkage is a join we now MATERIALIZE onto the row, so a reader can ask "which videos support
-- this article" straight from articles.* without re-deriving it. topic<->article and pillar<->
-- cluster are already persisted (focus_keyword, role, pillar_slug); this closes the video side.
--
-- Backfill is by case-insensitive keyword match; articles whose keyword isn't a known topic
-- (e.g. a few backfilled originals) are left NULL rather than guessed. Re-run the standalone
-- scripts/backfill_article_videos.py after any generation run to catch new rows.

ALTER TABLE articles ADD COLUMN IF NOT EXISTS source_video_ids JSON;

UPDATE articles a
SET source_video_ids = t.video_ids
FROM aggregated_topics t
WHERE a.source_video_ids IS NULL
  AND a.focus_keyword IS NOT NULL
  AND lower(t.canonical_label) = lower(a.focus_keyword)
  AND t.tenant_id = a.tenant_id;
