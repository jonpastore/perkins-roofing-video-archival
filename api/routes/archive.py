"""Archive routes — browse and download archived source videos.

Export ``router`` only; mounted onto the main app in api/app.py.

Role requirements (core.authz):
  - search → admin (via "*") + sales
"""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_role
from app.models import SessionLocal, Video, GraphNode, Article, MiniSeries, SocialPost
from core.retrieval import link

router = APIRouter(prefix="/archive", tags=["archive"])


def _video_to_dict(v: Video) -> dict:
    return {
        "id": v.id,
        "title": v.title,
        "duration": v.duration,
        "upload_date": v.upload_date,
        "archived": bool(v.archive_uri),
        "youtube_url": v.url,
    }


@router.get("/videos")
def list_videos(
    q: str | None = None,
    archived_only: bool = False,
    _claims=Depends(require_role("search")),
):
    """Return all Video rows ordered by upload_date desc.

    Optional filters:
      ?q=<title substring>        case-insensitive title search
      ?archived_only=true         only rows with a non-null archive_uri
    """
    with SessionLocal() as db:
        query = db.query(Video)
        if archived_only:
            query = query.filter(Video.archive_uri.isnot(None))
        if q:
            query = query.filter(Video.title.ilike(f"%{q}%"))
        rows = query.order_by(Video.upload_date.desc()).all()
        return [_video_to_dict(v) for v in rows]


@router.get("/{video_id}/download")
def download_video(
    video_id: str,
    _claims=Depends(require_role("search")),
):
    """Return a short-lived signed GCS download URL for an archived video.

    Parses bucket + key from the gs:// archive_uri. Returns 404 if the video
    has no archive_uri. ``adapters.storage`` is imported lazily so tests can
    monkeypatch it without triggering real GCP initialisation.
    """
    with SessionLocal() as db:
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
    import re  # noqa: PLC0415
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
):
    """Return per-video detail: topics with timecoded deep links, article usage, and social posts.

    - topics:       content_graph rows (kind='topics') for this video, ordered by start.
    - articles:     articles whose content_md contains the video_id string (usage detection).
    - social_posts: social posts linked via mini_series.video_id → social_posts.series_id.

    Returns 404 if the video does not exist.

    TODO (B2): add unanswered_comments count once the comments table is built.
    """
    with SessionLocal() as db:
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
