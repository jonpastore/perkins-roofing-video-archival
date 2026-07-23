"""Curated article images from in-video frames (pure logic).

Buildout item 12: the article image must be a real frame FROM the video, not the
uploaded title-card thumbnail (hqdefault/maxresdefault — those are what YouTube
shows as the "title screen"). YouTube already hosts three auto-extracted frames
per video at ~25/50/75% of its duration (hq1/2/3.jpg, and maxres1/2/3.jpg when
the source is HD), so candidates need no video download and no image hosting.

Pure: candidate construction and img-src swapping only. Availability checks and
the vision pick (both I/O) live in adapters.frame_pick.
"""

import re

FRAME_POSITIONS = (1, 2, 3)  # YouTube thumb N sits at ~N/4 of the video

# The first <img> whose src is a YouTube thumbnail (either host) OR an extracted
# wp-content frame (frame-<videoid>-<t>s.jpg, uploaded by the extract-frame route).
_YT_IMG_SRC_RE = re.compile(
    r'(<img\b[^>]*\bsrc=")'
    r'(https?://(?:img\.youtube\.com|i\.ytimg\.com)/vi/[^/"]+/[^"]+'
    r'|(?:https?://[^/"]+)?/wp-content/uploads/[^"]*frame-[A-Za-z0-9_-]{11}-\d+s[^"]*\.(?:jpe?g|webp|png))'
    r'(")',
    re.IGNORECASE,
)

# An extracted-frame URL: wp-content upload whose basename ties it to a video id.
_WP_FRAME_RE = re.compile(
    r"^(?:https?://[^/]+)?/wp-content/uploads/.*frame-([A-Za-z0-9_-]{11})-\d+s[^/]*\.(?:jpe?g|webp|png)$",
    re.IGNORECASE,
)

# Any YouTube reference (watch/embed/youtu.be/thumbnail hosts) with a real 11-char id.
_YT_REF_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/|img\.youtube\.com/vi/|i\.ytimg\.com/vi/)"
    r"([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)

# A selectable candidate URL: one of the known variants for a given video id.
_VARIANT_RE = re.compile(
    r"^https://(?:img\.youtube\.com|i\.ytimg\.com)/vi/([A-Za-z0-9_-]{11})/"
    r"(hqdefault|maxresdefault|(?:hq|sd|maxres)[123])\.jpg$"
)


def frame_candidates(video_id: str, duration: float | None = None) -> list[dict]:
    """Candidate images for *video_id*: three in-video frames, then the title card.

    Each frame entry carries both quality tiers (maxres may 404 — callers resolve
    availability) and a watch_url deep-linked to the frame's timecode so a gallery
    can show the frame in its video context (buildout item 12).
    """
    out = []
    for n in FRAME_POSITIONS:
        tc = int(duration * n / 4) if duration else None
        out.append({
            "position": n,
            "url": f"https://i.ytimg.com/vi/{video_id}/maxres{n}.jpg",
            "fallback_url": f"https://i.ytimg.com/vi/{video_id}/hq{n}.jpg",
            "timecode": tc,
            "watch_url": (f"https://www.youtube.com/watch?v={video_id}"
                          + (f"&t={tc}s" if tc else "")),
            "is_title_card": False,
        })
    out.append({
        "position": 0,
        "url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        "fallback_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "timecode": None,
        "watch_url": f"https://www.youtube.com/watch?v={video_id}",
        "is_title_card": True,
    })
    return out


def embedded_video_ids(content: str) -> list[str]:
    """Distinct video ids referenced in *content*, in first-seen order."""
    return list(dict.fromkeys(_YT_REF_RE.findall(content or "")))


def valid_candidate_url(url: str, allowed_video_ids: set[str]) -> bool:
    """True when *url* is a known thumbnail variant OR an extracted wp-content
    frame of an allowed video — the image must stay honest to the article's video."""
    m = _VARIANT_RE.match(url or "")
    if m:
        return m.group(1) in allowed_video_ids
    f = _WP_FRAME_RE.match(url or "")
    return bool(f and f.group(1) in allowed_video_ids)


def frame_filename(video_id: str, timecode: int) -> str:
    """Canonical extracted-frame filename — _WP_FRAME_RE ties it back to its video."""
    return f"frame-{video_id}-{int(timecode)}s.jpg"


def current_image_src(content: str) -> str | None:
    """src of the first YouTube-thumbnail <img> in *content*, or None."""
    m = _YT_IMG_SRC_RE.search(content or "")
    return m.group(2) if m else None


def swap_image_src(content: str, new_url: str) -> str:
    """Replace the first YouTube-thumbnail <img> src with *new_url* (no-op if absent)."""
    return _YT_IMG_SRC_RE.sub(rf"\g<1>{new_url}\g<3>", content or "", count=1)
