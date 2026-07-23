"""Pick the best in-video frame for an article image (I/O side of core.article_images).

Availability: maxres frame variants 404 on SD-source videos — resolve each candidate
to its best live URL with a HEAD check. Pick: Gemini vision (always Vertex — the
validation lane per the standing model-routing rule, independent of LLM_BACKEND)
chooses the most usable frame; any failure falls back to the mid-video frame, and
never to the title card.
"""

import json
import logging
import os

import requests

from core.article_images import frame_candidates

logger = logging.getLogger(__name__)

_TIMEOUT = 15


def _alive(url: str) -> bool:
    try:
        r = requests.head(url, timeout=_TIMEOUT, allow_redirects=True)
        # ytimg serves a 120x90 grey placeholder for some missing variants at 200;
        # those are ~1kB, real frames are >5kB.
        return r.status_code == 200 and int(r.headers.get("content-length") or 0) > 5000
    except requests.RequestException:
        return False


def resolve_candidates(video_id: str, duration: float | None = None) -> list[dict]:
    """frame_candidates with each entry's url resolved to the best live variant."""
    out = []
    for c in frame_candidates(video_id, duration):
        if not _alive(c["url"]):
            c = {**c, "url": c["fallback_url"]}
        out.append(c)
    return out


def _vision_pick(images: list[bytes], keyword: str) -> int:
    """Index of the best frame per Gemini vision. Raises on any failure."""
    import vertexai
    from vertexai.generative_models import GenerationConfig, GenerativeModel, Part

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT unset")
    vertexai.init(project=project, location=os.getenv("GCP_REGION", "us-central1"))
    model = GenerativeModel(os.getenv("LLM_MODEL", "gemini-2.5-flash"))
    parts = [
        f"These are {len(images)} frames from a roofing video about "
        f"{keyword or 'roofing'}. Pick the single best one to use as the article's "
        "hero image: sharp, well-composed, shows the subject (roof work, materials, "
        "or the speaker mid-demonstration), no motion blur, no mid-blink faces, no "
        "text overlays. Reply with JSON: "
        '{"index": <0-based index of the best frame>, "reason": "<one sentence>"}',
    ]
    for img in images:
        parts.append(Part.from_data(img, mime_type="image/jpeg"))
    resp = model.generate_content(
        parts, generation_config=GenerationConfig(response_mime_type="application/json"))
    idx = int(json.loads(resp.text)["index"])
    if not 0 <= idx < len(images):
        raise ValueError(f"vision pick out of range: {idx}")
    return idx


def pick_best_frame(video_id: str, duration: float | None = None,
                    keyword: str = "") -> dict:
    """Best in-video frame candidate for *video_id* (never the title card).

    Returns a resolved candidate dict (see core.article_images.frame_candidates).
    Vision failure degrades to the mid-video frame — a real frame beats an error.
    """
    frames = [c for c in resolve_candidates(video_id, duration) if not c["is_title_card"]]
    try:
        images = []
        for c in frames:
            r = requests.get(c["url"], timeout=_TIMEOUT)
            r.raise_for_status()
            images.append(r.content)
        return frames[_vision_pick(images, keyword)]
    except Exception as exc:  # noqa: BLE001 — degrade, never block article generation
        logger.warning("frame vision pick failed for %s (falling back to mid frame): %s",
                       video_id, exc)
        return frames[1]  # position 2 = ~50% of the video
