"""Archive routes — browse and download archived source videos.

Export ``router`` only; mounted onto the main app in api/app.py.

Role requirements (core.authz):
  - search → admin (via "*") + sales
"""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_role
from app.models import SessionLocal, Video

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
