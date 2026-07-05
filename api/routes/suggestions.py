"""Content Opportunities / Suggestions route.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements:
  - view_status → admin only  (GET /suggestions)

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


@router.get("")
def get_suggestions(claims=Depends(require_role("view_status"))):
    """Compute proactive content opportunities from current DB state.

    Returns:
      article_topics  - up to 12 high-frequency topics not yet in any article
      reels           - approved MiniSeries with no ScheduledContent (kind=reel) or SocialPost
      faqs            - up to 12 objection/claim questions whose video has no article
      unused_videos   - up to 12 videos with transcripts/topics not used in articles or MiniSeries
    """
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
        # Group by normalized label, count distinct videos
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

        # Filter out topics already covered by an article (title match)
        article_topics = []
        for key, g in sorted(
            topic_groups.items(),
            key=lambda kv: len(kv[1]["video_ids"]),
            reverse=True,
        ):
            if key in article_titles_lower:
                continue
            article_topics.append({
                "label": g["label"],
                "count": len(g["video_ids"]),
                "sample": g["sample"],
            })
            if len(article_topics) >= 12:
                break

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
        faqs = []
        for row in faq_rows:
            if row.video_id in article_video_ids:
                continue
            question = _to_question(row.label or "", row.detail or "")
            if not question:
                continue
            faqs.append({
                "question": question,
                "video_id": row.video_id,
                "t": int(row.start),
            })
            if len(faqs) >= 12:
                break

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
        unused_videos = []
        for v in all_videos:
            if v.id not in covered_video_ids:
                continue
            if v.id in article_video_ids:
                continue
            if v.id in series_video_ids:
                continue
            unused_videos.append({"video_id": v.id, "title": v.title})
            if len(unused_videos) >= 12:
                break

    return {
        "article_topics": article_topics,
        "reels": reels,
        "faqs": faqs,
        "unused_videos": unused_videos,
    }
