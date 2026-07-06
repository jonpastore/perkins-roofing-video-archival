"""Content Opportunities / Suggestions route.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements:
  - view_status → admin only  (GET /suggestions, GET /suggestions/counts)

Returns four proactive suggestion buckets derived from current DB state:
  - article_topics  : high-frequency mined topics not yet covered by any article
  - reels           : approved MiniSeries with no ScheduledContent or SocialPost
  - faqs            : mined objections/claims whose video is not referenced by any article
  - unused_videos   : videos with transcripts/topics but not in any article or MiniSeries
"""
from fastapi import APIRouter, Depends

from api.auth import require_role
from app.models import (
    Article,
    GraphNode,
    MiniSeries,
    Segment,
    ScheduledContent,
    SessionLocal,
    SocialPost,
    Video,
)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


def _normalize(label: str) -> str:
    return label.strip().lower()


def _to_question(label: str, detail: str) -> str:
    text = (label or "").strip() or (detail or "").strip()
    if not text:
        return ""
    if text.endswith("?"):
        return text
    return text[0].upper() + text[1:] + "?"


@router.get("/counts")
def get_suggestion_counts(
    claims=Depends(require_role("view_status")),
):
    """Return cheap COUNT-only totals for each opportunity bucket.

    Does NOT run the heavy suggestion computation — uses fast COUNT queries only.
    Intended for sidebar badge display.

    Returns:
      article_topics   - total uncovered topics
      reels            - total approved series with no schedule or social post
      faqs             - total unbuilt FAQ items
      unused_videos    - total unused videos with transcript/topic data
    """
    with SessionLocal() as db:
        # --- article_topics count ---
        topic_rows = (
            db.query(GraphNode)
            .filter(GraphNode.kind == "topics")
            .all()
        )
        articles = db.query(Article).all()
        article_titles_lower = {(a.title or "").strip().lower() for a in articles}

        topic_groups: dict[str, set] = {}
        for row in topic_rows:
            if not row.label:
                continue
            key = _normalize(row.label)
            topic_groups.setdefault(key, set()).add(row.video_id)

        article_topics_count = sum(
            1 for key in topic_groups if key not in article_titles_lower
        )

        # --- reels count ---
        approved_ids = {
            s.id for s in db.query(MiniSeries).filter(MiniSeries.approved == 1).all()
        }
        scheduled_ref_ids = {
            sc.ref_id
            for sc in db.query(ScheduledContent).filter(ScheduledContent.kind == "reel").all()
            if sc.ref_id is not None
        }
        social_series_ids = {
            row.series_id
            for row in db.query(SocialPost.series_id).distinct().all()
            if row.series_id is not None
        }
        reels_count = sum(
            1 for sid in approved_ids
            if str(sid) not in scheduled_ref_ids and sid not in social_series_ids
        )

        # --- faqs count ---
        all_video_ids_in_db: set[str] = {row.id for row in db.query(Video.id).all()}
        article_contents = [a.content_md or "" for a in articles]
        article_video_ids: set[str] = set()
        for vid_id in all_video_ids_in_db:
            if any(vid_id in content for content in article_contents):
                article_video_ids.add(vid_id)

        faq_rows = (
            db.query(GraphNode)
            .filter(
                GraphNode.kind.in_(("objections", "claims")),
                GraphNode.start.isnot(None),
            )
            .all()
        )
        faqs_count = sum(
            1 for row in faq_rows
            if row.video_id not in article_video_ids
            and bool(_to_question(row.label or "", row.detail or ""))
        )

        # --- unused_videos count ---
        series_video_ids: set[str] = {
            s.video_id for s in db.query(MiniSeries).all() if s.video_id
        }
        segment_video_ids: set[str] = {
            row.video_id for row in db.query(Segment.video_id).distinct().all()
        }
        graph_video_ids: set[str] = {
            row.video_id for row in db.query(GraphNode.video_id).distinct().all()
        }
        covered_video_ids = segment_video_ids | graph_video_ids
        all_videos = db.query(Video).all()
        unused_count = sum(
            1 for v in all_videos
            if v.id in covered_video_ids
            and v.id not in article_video_ids
            and v.id not in series_video_ids
        )

    return {
        "article_topics": article_topics_count,
        "reels": reels_count,
        "faqs": faqs_count,
        "unused_videos": unused_count,
    }


@router.get("")
def get_suggestions(
    limit: int = 50,
    offset: int = 0,
    bucket: str = "all",
    sort: str = "length",
    claims=Depends(require_role("view_status")),
):
    """Compute proactive content opportunities from current DB state.

    Query params:
      limit  - max items per bucket page (default 50, min 1, max 200)
      offset - skip first N items for faqs and unused_videos buckets (default 0)
      bucket - "all" (default) | "faqs" | "unused" — fetch only one bucket for pagination
      sort   - article_topics sort order: "length" (default, by total_content_length desc)
               or "videos" (by num_videos desc)

    Returns four buckets plus total counts per bucket:
      article_topics        - topics not yet in any article, ranked by content length or video count
      article_topics_total  - total uncovered topics (before limit)
      reels                 - approved MiniSeries with no ScheduledContent (kind=reel) or SocialPost
      faqs                  - objection/claim questions whose video has no article
      faqs_total            - total unbuilt FAQ items (before limit)
      unused_videos         - videos with transcripts/topics not used in articles or MiniSeries
      unused_videos_total   - total unused videos (before limit)

    Each article_topics item includes:
      label                 - topic label (title-cased from first occurrence)
      num_videos            - distinct videos covering this topic
      total_content_length  - sum of segment text length across all videos covering this topic
      count                 - alias for num_videos (backward compat)
      sample                - {video_id, t} for a sample clip

    Each unused_videos item includes:
      video_id, title, duration  (duration in seconds as float)
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    sort = sort if sort in ("length", "videos") else "length"
    with SessionLocal() as db:
        # --- Collect article coverage sets ---
        articles = db.query(Article).all()
        # Set of article titles (lowercased) for topic dedup
        article_titles_lower = {(a.title or "").strip().lower() for a in articles}
        # Set of video_ids referenced in any article's content_md
        # Check each known video_id as a substring of any article content
        all_video_ids_in_db: set[str] = {
            row.id for row in db.query(Video.id).all()
        }
        article_contents = [a.content_md or "" for a in articles]
        article_video_ids: set[str] = set()
        for vid_id in all_video_ids_in_db:
            if any(vid_id in content for content in article_contents):
                article_video_ids.add(vid_id)

        # --- article_topics bucket ---
        topic_rows = (
            db.query(GraphNode)
            .filter(GraphNode.kind == "topics")
            .all()
        )

        # Build per-video segment text length index
        segment_rows = db.query(Segment.video_id, Segment.text).all()
        video_segment_length: dict[str, int] = {}
        for row in segment_rows:
            vid = row.video_id
            txt = row.text or ""
            video_segment_length[vid] = video_segment_length.get(vid, 0) + len(txt)

        # Group by normalized label, track distinct videos + accumulate content length
        topic_groups: dict[str, dict] = {}
        for row in topic_rows:
            if not row.label:
                continue
            key = _normalize(row.label)
            if key not in topic_groups:
                topic_groups[key] = {
                    "label": row.label,
                    "video_ids": set(),
                    "sample": {"video_id": row.video_id, "t": int(row.start or 0)},
                }
            topic_groups[key]["video_ids"].add(row.video_id)

        # Compute total_content_length per topic (sum of segment lengths for its videos)
        for g in topic_groups.values():
            g["total_content_length"] = sum(
                video_segment_length.get(vid, 0) for vid in g["video_ids"]
            )

        # Filter out topics already covered by an article (title match)
        # Sort by selected key
        if sort == "videos":
            sort_key = lambda kv: len(kv[1]["video_ids"])  # noqa: E731
        else:
            sort_key = lambda kv: kv[1]["total_content_length"]  # noqa: E731

        article_topics_all = []
        for key, g in sorted(topic_groups.items(), key=sort_key, reverse=True):
            if key in article_titles_lower:
                continue
            num_videos = len(g["video_ids"])
            article_topics_all.append({
                "label": g["label"],
                "num_videos": num_videos,
                "total_content_length": g["total_content_length"],
                "count": num_videos,  # backward compat
                "sample": g["sample"],
            })
        article_topics_total = len(article_topics_all)
        article_topics = article_topics_all[:limit]

        # --- reels bucket ---
        approved_series = (
            db.query(MiniSeries)
            .filter(MiniSeries.approved == 1)
            .all()
        )
        # Set of series ids that already have a ScheduledContent row (kind=reel)
        scheduled_series_ids: set[str] = set()
        sched_rows = (
            db.query(ScheduledContent)
            .filter(ScheduledContent.kind == "reel")
            .all()
        )
        for sc in sched_rows:
            if sc.ref_id is not None:
                scheduled_series_ids.add(str(sc.ref_id))

        # Set of series ids that already have a SocialPost
        social_series_ids: set[int] = set()
        social_rows = db.query(SocialPost.series_id).distinct().all()
        for row in social_rows:
            if row.series_id is not None:
                social_series_ids.add(row.series_id)

        reels = []
        for s in approved_series:
            already_scheduled = str(s.id) in scheduled_series_ids
            already_posted = s.id in social_series_ids
            if already_scheduled or already_posted:
                continue
            parts_count = len(s.parts_json) if s.parts_json else 0
            reels.append({
                "series_id": s.id,
                "video_id": s.video_id,
                "title": s.title,
                "parts_count": parts_count,
            })

        # --- faqs bucket ---
        faq_rows = (
            db.query(GraphNode)
            .filter(
                GraphNode.kind.in_(("objections", "claims")),
                GraphNode.start.isnot(None),
            )
            .all()
        )
        # Build video title lookup
        video_title_map: dict[str, str] = {
            v.id: (v.title or v.id) for v in db.query(Video).all()
        }
        faqs_all = []
        for row in faq_rows:
            if row.video_id in article_video_ids:
                continue
            question = _to_question(row.label or "", row.detail or "")
            if not question:
                continue
            faqs_all.append({
                "question": question,
                "video_id": row.video_id,
                "title": video_title_map.get(row.video_id, row.video_id),
                "t": int(row.start),
            })
        faqs_total = len(faqs_all)
        faqs = faqs_all[offset: offset + limit]

        # --- unused_videos bucket ---
        # Videos that have at least one Segment (transcript) or GraphNode (topics)
        # but are not referenced in any article and not in any MiniSeries
        series_video_ids: set[str] = set()
        for s in db.query(MiniSeries).all():
            if s.video_id:
                series_video_ids.add(s.video_id)

        # Video IDs that have transcript coverage
        segment_video_ids: set[str] = {
            row.video_id for row in db.query(Segment.video_id).distinct().all()
        }
        # Video IDs that have graph coverage
        graph_video_ids: set[str] = {
            row.video_id for row in db.query(GraphNode.video_id).distinct().all()
        }
        covered_video_ids = segment_video_ids | graph_video_ids

        all_videos = db.query(Video).all()
        unused_videos_all = []
        for v in all_videos:
            if v.id not in covered_video_ids:
                continue
            if v.id in article_video_ids:
                continue
            if v.id in series_video_ids:
                continue
            unused_videos_all.append({
                "video_id": v.id,
                "title": v.title or v.id,
                "duration": v.duration or 0.0,
            })
        unused_videos_total = len(unused_videos_all)
        unused_videos = unused_videos_all[offset: offset + limit]

    return {
        "article_topics": article_topics,
        "article_topics_total": article_topics_total,
        "reels": reels,
        "faqs": faqs,
        "faqs_total": faqs_total,
        "unused_videos": unused_videos,
        "unused_videos_total": unused_videos_total,
    }
