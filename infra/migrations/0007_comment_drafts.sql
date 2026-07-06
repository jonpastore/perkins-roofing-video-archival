-- Wave: YouTube comment reply assistant — comment_drafts table.
-- Idempotent: safe to re-run. Applied by scripts/apply_migrations.sh (git -> apply, R3).

CREATE TABLE IF NOT EXISTS comment_drafts (
    id           SERIAL NOT NULL,
    video_id     VARCHAR NOT NULL,
    comment_id   VARCHAR NOT NULL,
    author       VARCHAR,
    comment_text TEXT NOT NULL,
    published_at TIMESTAMP WITHOUT TIME ZONE,
    needs_reply  BOOLEAN NOT NULL DEFAULT FALSE,
    draft_reply  TEXT,
    status       VARCHAR NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    UNIQUE (comment_id)
);
CREATE INDEX IF NOT EXISTS ix_comment_drafts_video_id ON comment_drafts (video_id);
CREATE INDEX IF NOT EXISTS ix_comment_drafts_status   ON comment_drafts (status);
