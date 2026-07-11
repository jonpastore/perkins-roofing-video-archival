"""Archive routes — browse and download archived source videos.

Export ``router`` only; mounted onto the main app in api/app.py.

Role requirements (core.authz):
  - search → admin (via "*") + sales
  - manage_archive → admin + web_admin
"""
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Article, GraphNode, MiniSeries, SocialPost, Video
from core.ratelimit import SingleFlightGuard
from core.retrieval import link

router = APIRouter(prefix="/archive", tags=["archive"])

# Per-process single-flight guards for expensive YouTube/LLM fan-out endpoints.
# Cloud Run may run multiple instances — these are defense-in-depth per-instance
# guards. Add a platform_config-backed daily counter for a durable cross-instance
# quota budget.
_backfill_guard = SingleFlightGuard(cooldown_seconds=30)
_poll_kpis_guard = SingleFlightGuard(cooldown_seconds=30)
# check-new is read-only (no writes/LLM) — lock only, no cooldown.
_check_new_guard = SingleFlightGuard(cooldown_seconds=0)


def _video_to_dict(
    v: Video,
    topic_count: int = 0,
    article_count: int = 0,
    social_post_count: int = 0,
    clips_generated: bool = False,
    articles_generated: bool = False,
    social_generated: bool = False,
) -> dict:
    return {
        "id": v.id,
        "title": v.title,
        "duration": v.duration,
        "content_length": int(v.duration) if v.duration is not None else None,
        "upload_date": v.upload_date,
        "archived": bool(v.archive_uri),
        "youtube_url": v.url,
        "topic_count": topic_count,
        "article_count": article_count,
        "social_post_count": social_post_count,
        "clips_generated": clips_generated,
        "articles_generated": articles_generated,
        "social_generated": social_generated,
        "clips_generated_at": v.clips_generated_at.isoformat() if v.clips_generated_at else None,
        "views": v.views,
        "likes": v.likes,
        "comment_count": v.comment_count,
        "last_comment_at": v.last_comment_at.isoformat() if v.last_comment_at else None,
        "kpis_polled_at": v.kpis_polled_at.isoformat() if v.kpis_polled_at else None,
        "last_pulled_at": v.last_pulled_at.isoformat() if v.last_pulled_at else None,
        "unavailable_since": v.unavailable_since.isoformat() if v.unavailable_since else None,
        "hidden_at": v.hidden_at.isoformat() if v.hidden_at else None,
    }


@router.get("/videos")
def list_videos(
    q: str | None = None,
    archived_only: bool = False,
    include_hidden: bool = False,
    min_length: int | None = None,
    max_length: int | None = None,
    uploaded_after: str | None = None,
    uploaded_before: str | None = None,
    clips: str = "all",
    articles: str = "all",
    social: str = "all",
    _claims=Depends(require_role("search")),
    db: Session = Depends(get_db_session),
):
    """Return all Video rows ordered by upload_date desc.

    Optional filters:
      ?q=<title substring>        case-insensitive title search
      ?archived_only=true         only rows with a non-null archive_uri
      ?include_hidden=true        include rows where hidden_at IS NOT NULL
                                  (default: hidden rows are excluded)
      ?min_length=<seconds>       minimum duration (inclusive)
      ?max_length=<seconds>       maximum duration (inclusive)
      ?uploaded_after=<ISO date>  upload_date >= date (YYYY-MM-DD)
      ?uploaded_before=<ISO date> upload_date <= date (YYYY-MM-DD)
      ?clips=all|yes|no           filter by whether MiniSeries rows exist
      ?articles=all|yes|no        filter by whether articles reference this video
      ?social=all|yes|no          filter by whether SocialPost rows exist

    Each row includes usage counts and KPI fields:
      topic_count, article_count, social_post_count
      clips_generated, articles_generated, social_generated
      clips_generated_at, views, likes, comment_count,
      last_comment_at, kpis_polled_at, last_pulled_at
      content_length (= duration as int seconds)
      unavailable_since, hidden_at
    """
    query = db.query(Video)
    if not include_hidden:
        query = query.filter(Video.hidden_at.is_(None))
    if archived_only:
        query = query.filter(Video.archive_uri.isnot(None))
    if q:
        query = query.filter(Video.title.ilike(f"%{q}%"))
    if min_length is not None:
        query = query.filter(Video.duration >= min_length)
    if max_length is not None:
        query = query.filter(Video.duration <= max_length)
    if uploaded_after:
        query = query.filter(Video.upload_date >= uploaded_after)
    if uploaded_before:
        query = query.filter(Video.upload_date <= uploaded_before)

    rows = query.order_by(Video.upload_date.desc()).all()

    if not rows:
        return []

    video_ids = [v.id for v in rows]

    # topic counts: one query, group by video_id
    topic_counts: dict[str, int] = dict(
        db.query(GraphNode.video_id, func.count(GraphNode.id))
        .filter(GraphNode.video_id.in_(video_ids), GraphNode.kind == "topics")
        .group_by(GraphNode.video_id)
        .all()
    )

    # article counts: per video_id, count articles whose content_md contains it
    article_counts: dict[str, int] = {}
    for vid in video_ids:
        article_counts[vid] = (
            db.query(func.count(Article.slug))
            .filter(Article.content_md.contains(vid))
            .scalar() or 0
        )

    # social post counts + presence: mini_series.video_id → social_posts.series_id
    series_map: dict[str, list[int]] = {}  # video_id -> [series_id]
    for s in db.query(MiniSeries.id, MiniSeries.video_id).filter(MiniSeries.video_id.in_(video_ids)).all():
        series_map.setdefault(s.video_id, []).append(s.id)
    all_series_ids = [sid for sids in series_map.values() for sid in sids]
    post_counts_by_series: dict[int, int] = {}
    if all_series_ids:
        post_counts_by_series = dict(
            db.query(SocialPost.series_id, func.count(SocialPost.id))
            .filter(SocialPost.series_id.in_(all_series_ids))
            .group_by(SocialPost.series_id)
            .all()
        )
    social_post_counts: dict[str, int] = {
        vid: sum(post_counts_by_series.get(sid, 0) for sid in sids)
        for vid, sids in series_map.items()
    }

    # Derived booleans
    clips_generated_map: dict[str, bool] = {
        vid: bool(sids) for vid, sids in series_map.items()
    }
    articles_generated_map: dict[str, bool] = {
        vid: cnt > 0 for vid, cnt in article_counts.items()
    }
    social_generated_map: dict[str, bool] = {
        vid: cnt > 0 for vid, cnt in social_post_counts.items()
    }

    # Apply boolean filters (post-query, derived from join results)
    def _bool_filter(vid: str, param: str, generated_map: dict[str, bool]) -> bool:
        if param == "all":
            return True
        val = generated_map.get(vid, False)
        return val if param == "yes" else not val

    result = []
    for v in rows:
        if not _bool_filter(v.id, clips, clips_generated_map):
            continue
        if not _bool_filter(v.id, articles, articles_generated_map):
            continue
        if not _bool_filter(v.id, social, social_generated_map):
            continue
        result.append(
            _video_to_dict(
                v,
                topic_count=topic_counts.get(v.id, 0),
                article_count=article_counts.get(v.id, 0),
                social_post_count=social_post_counts.get(v.id, 0),
                clips_generated=clips_generated_map.get(v.id, False),
                articles_generated=articles_generated_map.get(v.id, False),
                social_generated=social_generated_map.get(v.id, False),
            )
        )
    return result


@router.get("/{video_id}/download")
def download_video(
    video_id: str,
    _claims=Depends(require_role("search")),
    db: Session = Depends(get_db_session),
):
    """Return a short-lived signed GCS download URL for an archived video.

    Parses bucket + key from the gs:// archive_uri. Returns 404 if the video
    has no archive_uri. ``adapters.storage`` is imported lazily so tests can
    monkeypatch it without triggering real GCP initialisation.
    """
    video = db.get(Video, video_id)

    if video is None:
        raise HTTPException(status_code=404, detail="video not found")
    if not video.archive_uri:
        raise HTTPException(status_code=404, detail="video not yet archived")

    # Parse  gs://<bucket>/<key>
    # archive_uri is expected to be  gs://<GOOGLE_CLOUD_PROJECT>-media/videos/<video_id>.mp4
    uri = video.archive_uri
    if not uri.startswith("gs://"):
        raise HTTPException(status_code=500, detail="invalid archive_uri scheme")
    path = uri[5:]  # strip "gs://"
    bucket, _, key = path.partition("/")

    # Sanitize the title before it goes into the Content-Disposition filename (it comes from
    # YouTube — avoid quotes/CRLF producing a malformed disposition header).
    safe_name = re.sub(r'[^\w\-. ]', "_", (video.title or video_id)).strip() or video_id

    import adapters.storage as _storage  # lazy — monkeypatchable in tests
    try:
        download_url = _storage.signed_download_url(
            bucket,
            key,
            filename=f"{safe_name}.mp4",
        )
    except Exception:  # noqa: BLE001 — signing needs SignBlob; degrade without leaking a traceback
        raise HTTPException(status_code=503, detail="download temporarily unavailable")
    return {"download_url": download_url}


# ---------------------------------------------------------------------------
# Video naming — rename, re-parse from YouTube, suggest from transcript
# ---------------------------------------------------------------------------

class RenameRequest(BaseModel):
    title: str


@router.post("/{video_id}/rename")
def rename_video(
    video_id: str,
    body: RenameRequest,
    _claims=Depends(require_role("manage_archive")),
    db: Session = Depends(get_db_session),
):
    """Set the stored display title for a video. Returns {id, title}. 404 if missing."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")
    v = db.get(Video, video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="video not found")
    v.title = title
    db.flush()
    db.refresh(v)
    return {"id": v.id, "title": v.title}


@router.get("/{video_id}/youtube-name")
def youtube_name(video_id: str, _claims=Depends(require_role("manage_archive"))):
    """Fetch the current title from YouTube (Data API snippet) to re-parse a better name."""
    from adapters.youtube_stats import fetch_titles
    try:
        titles = fetch_titles([video_id])
    except Exception as exc:  # noqa: BLE001 — surface as 502, don't leak a traceback
        raise HTTPException(status_code=502, detail="YouTube title lookup failed") from exc
    title = titles.get(video_id)
    if not title:
        raise HTTPException(status_code=404, detail="no YouTube title found (deleted/private?)")
    return {"video_id": video_id, "youtube_title": title}


@router.post("/{video_id}/suggest-name")
def suggest_name(
    video_id: str,
    _claims=Depends(require_role("manage_archive")),
    db: Session = Depends(get_db_session),
):
    """Suggest a concise, descriptive title from the video transcript via the LLM."""
    from app.llm import chat
    from app.models import Segment

    v = db.get(Video, video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="video not found")
    segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.start)
        .limit(40)
        .all()
    )
    context = " ".join(s.text for s in segments if s.text)[:2000]
    if not context.strip():
        raise HTTPException(status_code=400, detail="no transcript available to suggest a name")

    prompt = (
        "You are titling a Perkins Roofing video. From the transcript excerpt below, write ONE "
        "concise, descriptive, engaging title (max 70 characters, no quotes, no emojis) that "
        "accurately reflects the content.\n\nTranscript excerpt:\n"
        f"{context}\n\nTitle only — no preamble."
    )
    try:
        title = chat(prompt, want_json=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="name suggestion failed") from exc
    if not title or not title.strip():
        raise HTTPException(status_code=502, detail="LLM returned an empty title")
    return {"video_id": video_id, "suggested_title": title.strip().strip('"')[:100]}


# ---------------------------------------------------------------------------
# Platform URL helpers for social posts
# ---------------------------------------------------------------------------

_PLATFORM_URL_TEMPLATES = {
    "instagram": "https://www.instagram.com/p/{external_id}/",
    "tiktok": "https://www.tiktok.com/@perkins/video/{external_id}",
}


def _social_post_url(post: SocialPost) -> str | None:
    """Derive a public URL from the post's platform + external_id, else fall back to gcs_url."""
    if post.external_id and post.platform in _PLATFORM_URL_TEMPLATES:
        return _PLATFORM_URL_TEMPLATES[post.platform].format(external_id=post.external_id)
    return post.gcs_url or None


@router.get("/{video_id}/detail")
def video_detail(
    video_id: str,
    _claims=Depends(require_role("search")),
    db: Session = Depends(get_db_session),
):
    """Return per-video detail: topics with timecoded deep links, article usage, and social posts.

    - topics:       content_graph rows (kind='topics') for this video, ordered by start.
    - articles:     articles whose content_md contains the video_id string (usage detection).
    - social_posts: social posts linked via mini_series.video_id → social_posts.series_id.

    Returns 404 if the video does not exist.

    TODO (B2): add unanswered_comments count once the comments table is built.
    """
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    # Topics — content_graph rows, kind='topics', ordered by timecode
    topic_rows = (
        db.query(GraphNode)
        .filter(GraphNode.video_id == video_id, GraphNode.kind == "topics")
        .order_by(GraphNode.start)
        .all()
    )
    topics = [
        {
            "label": t.label,
            "t": int(t.start) if t.start is not None else 0,
            "url": link(video_id, t.start if t.start is not None else 0),
        }
        for t in topic_rows
    ]

    # Articles — detect usage by scanning content_md for the video_id string
    article_rows = (
        db.query(Article)
        .filter(Article.content_md.contains(video_id))
        .all()
    )
    articles = [
        {"slug": a.slug, "title": a.title, "status": a.status}
        for a in article_rows
    ]

    # Social posts — join mini_series (video_id) → social_posts (series_id)
    series_rows = (
        db.query(MiniSeries)
        .filter(MiniSeries.video_id == video_id)
        .all()
    )
    series_ids = [s.id for s in series_rows]
    post_rows = (
        db.query(SocialPost)
        .filter(SocialPost.series_id.in_(series_ids))
        .all()
    ) if series_ids else []
    social_posts = [
        {
            "platform": p.platform,
            "status": p.status,
            "url": _social_post_url(p),
        }
        for p in post_rows
    ]

    return {"topics": topics, "articles": articles, "social_posts": social_posts}


# ---------------------------------------------------------------------------
# Backfill + KPI poll endpoints
# ---------------------------------------------------------------------------

@router.post("/backfill")
def backfill(
    _claims=Depends(require_role("manage_archive")),
):
    """Enumerate the YouTube channel and insert missing Video rows.

    Returns {added, checked}.

    Guarded: 409 if already running, 429 if ran < 30s ago.
    """
    _backfill_guard.acquire_or_raise("backfill")
    try:
        import jobs.backfill_archive as _job  # lazy — avoids importing yt-dlp at startup
        result = _job.run()
        return {"added": result["added"], "checked": result["checked"]}
    except HTTPException:
        raise
    finally:
        _backfill_guard.release("backfill")


@router.get("/check-new")
def check_new(
    _claims=Depends(require_role("manage_archive")),
    db: Session = Depends(get_db_session),
):
    """Enumerate the channel and return count of videos not yet in the DB.

    Does not insert anything. Returns {new_count, last_pulled_at}.

    Guarded: 409 if already running (no cooldown — read-only, no LLM).
    """
    _check_new_guard.acquire_or_raise("check-new")
    try:
        import jobs.backfill_archive as _job  # lazy
        return _job.check_new(db=db)
    except HTTPException:
        raise
    finally:
        _check_new_guard.release("check-new")


@router.post("/poll-kpis")
def poll_kpis(
    limit: int | None = Body(default=None, embed=True),
    _claims=Depends(require_role("manage_archive")),
):
    """Fetch YouTube KPIs for archived videos and update the DB.

    Optional body: {"limit": N}
    Returns {polled}.

    Guarded: 409 if already running, 429 if ran < 30s ago.
    """
    _poll_kpis_guard.acquire_or_raise("poll-kpis")
    try:
        import jobs.poll_archive_kpis as _job  # lazy
        return _job.run(limit=limit)
    except HTTPException:
        raise
    finally:
        _poll_kpis_guard.release("poll-kpis")


# ---------------------------------------------------------------------------
# Visibility: hide / unhide
# ---------------------------------------------------------------------------

@router.post("/{video_id}/hide")
def hide_video(
    video_id: str,
    _claims=Depends(require_role("manage_archive")),
    db: Session = Depends(get_db_session),
):
    """Mark a video as hidden so it is excluded from the default archive list.

    The GCS archive copy is never deleted. Returns the updated video dict.
    404 if the video is not found (tenant-scoped).
    """
    from datetime import datetime, timezone  # noqa: PLC0415
    v = db.get(Video, video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="video not found")
    v.hidden_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    db.refresh(v)
    return _video_to_dict(v)


@router.post("/{video_id}/unhide")
def unhide_video(
    video_id: str,
    _claims=Depends(require_role("manage_archive")),
    db: Session = Depends(get_db_session),
):
    """Clear the hidden_at flag so the video reappears in the default archive list.

    Returns the updated video dict. 404 if the video is not found (tenant-scoped).
    """
    v = db.get(Video, video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="video not found")
    v.hidden_at = None
    db.flush()
    db.refresh(v)
    return _video_to_dict(v)
