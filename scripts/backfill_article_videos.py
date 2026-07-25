"""Backfill articles.source_video_ids from aggregated_topics by keyword — the video<->article
side of the content-hub linkage. Re-runnable: run after every generation batch to link the new
articles. Only fills rows that are still NULL (idempotent), matching an article's focus_keyword
to a harvested topic's canonical_label (case-insensitive).

An SEO focus_keyword ("the proven guide to metal roofs on the coast best choices") is rarely a
verbatim topic label, so ~50 articles never link on the exact-match pass. --retrieval clears
those by asking `source_transcripts()` — the SAME grounded retrieval the generator was given —
which videos the article was actually written from. That is the real linkage; string similarity
between an SEO headline and a topic label is not.

    python -m scripts.backfill_article_videos              # report + exact-label fill
    python -m scripts.backfill_article_videos --dry        # report only
    python -m scripts.backfill_article_videos --retrieval  # + retrieval pass for the leftovers

Env: DB_URL (Cloud SQL proxy on 127.0.0.1:5432); --retrieval also needs the embedding backend
(EMBED_BACKEND=vertex + creds), since it runs the same hybrid search as generation.
"""
import argparse
import json
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from jobs.article_job import _stamped_session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--retrieval", action="store_true",
                    help="second pass: link leftovers via the generator's own grounded retrieval")
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
        if args.retrieval:
            from jobs.article_job import source_transcripts  # noqa: PLC0415
            leftovers = db.execute(text(
                "SELECT slug, focus_keyword FROM articles WHERE source_video_ids IS NULL "
                "AND focus_keyword IS NOT NULL ORDER BY slug")).fetchall()
            for slug, kw in leftovers:
                try:
                    vids = list(dict.fromkeys(
                        s["video_id"] for s in source_transcripts(kw, db=db) if s.get("video_id")))
                except Exception as exc:  # noqa: BLE001
                    print(f"  retrieval failed for {kw!r}: {exc}", file=sys.stderr)
                    continue
                print(f"  {'DRY: ' if args.dry else ''}{kw!r} -> {vids or 'no hits'}")
                if vids and not args.dry:
                    db.execute(
                        text("UPDATE articles SET source_video_ids = CAST(:v AS json) "
                             "WHERE slug = :s AND source_video_ids IS NULL"),
                        {"v": json.dumps(vids), "s": slug})
            if not args.dry:
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
