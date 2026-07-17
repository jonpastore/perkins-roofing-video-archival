-- 0040_comment_platform.sql
-- Generalize comment_drafts to carry a platform, ahead of Phase 3 (Meta comments).
-- Idempotent: safe to re-run. Applied by scripts/apply_migrations.sh (git -> apply, R3).

-- Backfills existing rows to 'youtube' (Postgres populates existing rows from DEFAULT
-- when adding a NOT NULL column in one statement).
ALTER TABLE comment_drafts ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT 'youtube';

-- Drop the REAL prod unique constraint: the inline UNIQUE(comment_id) from
-- 0007_comment_drafts.sql:16, auto-named by Postgres as comment_drafts_comment_id_key
-- (NOT the ORM name uq_comment_drafts_comment_id, which never existed in prod).
-- Both names dropped IF EXISTS — belt+suspenders for ORM-created test DBs.
ALTER TABLE comment_drafts DROP CONSTRAINT IF EXISTS comment_drafts_comment_id_key;
ALTER TABLE comment_drafts DROP CONSTRAINT IF EXISTS uq_comment_drafts_comment_id;

-- Tenant-scoped per convention: fixes the RLS silent-drop path (crawl_comments.py's
-- upsert existence check filtered on comment_id alone, ignoring tenant/RLS boundary).
ALTER TABLE comment_drafts ADD CONSTRAINT uq_comment_drafts_tenant_platform_comment
    UNIQUE (tenant_id, platform, comment_id);
