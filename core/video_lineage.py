"""Join chopped YouTube clips back to the long original they came from.

Sliced uploads look like new catalogue videos. Without a parent link they are
ingested, mined for topics/FAQs, and generate duplicate articles. Store the
clip URLs on the long video when we mark it chopped; when those ids appear
(or already exist), they inherit parent_video_id and drop out of generation.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_FROM_URL = re.compile(
    r"(?:youtu\.be/|v=|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})"
)


def youtube_id_from_url(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if _ID.fullmatch(raw):
        return raw
    match = _FROM_URL.search(raw)
    return match.group(1) if match else None


def ids_from_urls(urls: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in urls or []:
        vid = youtube_id_from_url(item)
        if vid and vid not in seen:
            seen.add(vid)
            out.append(vid)
    return out


def derived_video_ids(videos: Iterable[Any]) -> set[str]:
    """Every id that is a slice of a longer original (parent set or listed URL)."""
    out: set[str] = set()
    for video in videos:
        parent = getattr(video, "parent_video_id", None)
        if parent:
            out.add(video.id)
        for vid in ids_from_urls(getattr(video, "derived_urls", None) or []):
            out.add(vid)
    return out


def derived_ids_from_db(db) -> set[str]:
    from app.models import Video  # noqa: PLC0415
    rows = db.query(Video.id, Video.parent_video_id, Video.derived_urls).all()
    class _Row:
        def __init__(self, id, parent_video_id, derived_urls):
            self.id = id
            self.parent_video_id = parent_video_id
            self.derived_urls = derived_urls
    return derived_video_ids(_Row(*r) for r in rows)


def parent_index_from_db(db) -> dict[str, str]:
    """child youtube id → long-form parent id, from derived_urls on parents."""
    from app.models import Video  # noqa: PLC0415
    index: dict[str, str] = {}
    for parent_id, urls in db.query(Video.id, Video.derived_urls).filter(
        Video.derived_urls.isnot(None)
    ).all():
        for child in ids_from_urls(urls or []):
            if child != parent_id:
                index[child] = parent_id
    return index


def stamp_longform_source(video) -> bool:
    """Drop a >=15min source from the chop queue once we have an in-app cut.

    Clip Studio clips live on the same YouTube id — there is no new upload to
    join. Pasting child URLs is only for slices uploaded as new YouTube videos.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    from core.edit_plan import LONG_SECS  # noqa: PLC0415

    if video is None:
        return False
    if float(video.duration or 0) < LONG_SECS:
        return False
    if getattr(video, "longform_reprocessed_at", None):
        return False
    video.longform_reprocessed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if not getattr(video, "longform_note", None):
        video.longform_note = "clip_studio"
    return True


def attach_derived_urls(parent, urls: list[str], db) -> list[str]:
    """Record clip URLs on the long video and stamp any already-catalogued children."""
    from app.models import Video  # noqa: PLC0415

    existing = list(parent.derived_urls or [])
    seen = set(ids_from_urls(existing))
    merged = list(existing)
    for raw in urls:
        text = (raw or "").strip()
        vid = youtube_id_from_url(text)
        if not vid or vid == parent.id or vid in seen:
            continue
        seen.add(vid)
        merged.append(text)
    parent.derived_urls = merged
    attached: list[str] = []
    for child_id in ids_from_urls(merged):
        child = db.get(Video, child_id)
        if child is None:
            continue
        child.parent_video_id = parent.id
        attached.append(child_id)
    return attached
