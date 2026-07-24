"""Backfill articles.source_video_ids from aggregated_topics by keyword — the video<->article
side of the content-hub linkage. Re-runnable: run after every generation batch to link the new
articles. Only fills rows that are still NULL (idempotent), matching an article's focus_keyword
to a harvested topic's canonical_label (case-insensitive).

    python -m scripts.backfill_article_videos            # report + fill
    python -m scripts.backfill_article_videos --dry      # report only

Env: DB_URL (Cloud SQL proxy on 127.0.0.1:5432).
"""
import argparse
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from jobs.article_job import _stamped_session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    with _stamped_session(1) as db:
        before = db.execute(text(
            "SELECT count(*) FROM articles WHERE source_video_ids IS NOT NULL")).scalar()
        total = db.execute(text("SELECT count(*) FROM articles")).scalar()
        if not args.dry:
            db.execute(text(
                "UPDATE articles a SET source_video_ids = t.video_ids "
                "FROM aggregated_topics t "
                "WHERE a.source_video_ids IS NULL AND a.focus_keyword IS NOT NULL "
                "  AND lower(t.canonical_label) = lower(a.focus_keyword) "
                "  AND t.tenant_id = a.tenant_id"))
            db.commit()
        after = db.execute(text(
            "SELECT count(*) FROM articles WHERE source_video_ids IS NOT NULL")).scalar()
        unlinked = db.execute(text(
            "SELECT focus_keyword FROM articles WHERE source_video_ids IS NULL "
            "ORDER BY generated_at DESC LIMIT 10")).fetchall()
    print(f"{'DRY: ' if args.dry else ''}linked {after}/{total} articles to source videos "
          f"(+{after - before} this run)")
    if unlinked:
        print("still unlinked (focus_keyword not a known topic):",
              [r[0] for r in unlinked])


if __name__ == "__main__":
    main()
