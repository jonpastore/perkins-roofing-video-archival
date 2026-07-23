"""Backfill curated article images: replace title-card thumbnails with AI-picked frames.

Every published article currently shows hqdefault.jpg — the video's uploaded title
card, i.e. the same image as the YouTube title screen. This swaps each one for a
Gemini-vision-picked real in-video frame (adapters.frame_pick), updating both the
DB row and the WordPress post. Idempotent: articles whose image is already a
non-title-card variant are skipped.

Run (against the real DB via the Cloud SQL proxy — see prompt.txt FIRST STEPS):
    DB_URL=... .venv/bin/python scripts/curate_article_images.py [--dry-run] [--slug SLUG]
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from app.models import Article, Video  # noqa: E402
from core.article_images import current_image_src, swap_image_src  # noqa: E402
from jobs.article_job import _stamped_session  # noqa: E402

WP_THROTTLE_S = 1.5  # staging WP 429s under fast writes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slug", help="only this article")
    args = ap.parse_args()

    from adapters.frame_pick import pick_best_frame  # deferred: needs GCP creds

    with _stamped_session(1) as db:
        _run(db, pick_best_frame, args)
    return 0


def _run(db, pick_best_frame, args) -> None:
    q = db.query(Article).filter(Article.status == "published")
    if args.slug:
        q = db.query(Article).filter(Article.slug == args.slug)
    changed = skipped = 0
    for a in q.all():
        src = current_image_src(a.content_md or "")
        if not src:
            print(f"-- {a.slug}: no YouTube image, skip")
            skipped += 1
            continue
        if "default.jpg" not in src:
            print(f"-- {a.slug}: already curated ({src.rsplit('/', 1)[-1]}), skip")
            skipped += 1
            continue
        vid = src.split("/vi/")[1].split("/")[0]
        v = db.get(Video, vid)
        pick = pick_best_frame(vid, v.duration if v else None, a.focus_keyword or "")
        print(f"** {a.slug}: {src.rsplit('/', 1)[-1]} -> {pick['url'].rsplit('/vi/')[-1]}"
              f" (t={pick['timecode']}s)")
        if args.dry_run:
            changed += 1
            continue
        a.content_md = swap_image_src(a.content_md, pick["url"])
        db.commit()
        if a.wp_post_id:
            from adapters.wordpress import update
            from jobs.article_job import _markdown_to_html
            update(
                post_id=a.wp_post_id,
                title=a.title or "",
                html=_markdown_to_html(a.content_md or ""),
                meta_description=a.meta or "",
                jsonld=list(a.jsonld_json) if a.jsonld_json else [],
                status="publish",
                focus_keyword=a.focus_keyword,
            )
            time.sleep(WP_THROTTLE_S)
        changed += 1
    print(f"\n{changed} curated, {skipped} skipped{' (dry run)' if args.dry_run else ''}")


if __name__ == "__main__":
    raise SystemExit(main())
