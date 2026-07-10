"""Pixabay Audio API adapter (I/O — coverage-omitted).

Item 8: Resolves a music mood → Pixabay search query → download track to tmp.

API key: PIXABAY_API_KEY env var.  When unset, all functions return None + log.
Free tier: 100 req/hr, no attribution required for non-commercial use.
Docs: https://pixabay.com/api/docs/#api_music

Mood → query mapping mirrors the music.catalog spec field from render_spec.
The spec stores a ``track_id`` that callers set to either:
  - A specific Pixabay track ID (string of digits), OR
  - A mood keyword: ``"upbeat"``, ``"calm"``, ``"dramatic"``, ``"corporate"``
    (any of ``MOOD_QUERY`` keys) → auto-search and return top result.

Returns the local path to a downloaded MP3/WAV, or None on any error.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_API_BASE = "https://pixabay.com/api/music/"

# Mood → Pixabay search query mapping.
MOOD_QUERY: dict[str, str] = {
    "upbeat":     "upbeat corporate",
    "calm":       "calm ambient background",
    "dramatic":   "dramatic cinematic",
    "corporate":  "corporate background motivational",
    "happy":      "happy uplifting",
    "inspiring":  "inspiring motivational",
    "chill":      "chill lofi relaxing",
}


def _api_key() -> str | None:
    return os.getenv("PIXABAY_API_KEY", "").strip() or None


def resolve_track(
    track_id: str,
    scratch: str,
    *,
    mood: str | None = None,
) -> str | None:
    """Resolve a Pixabay track_id or mood keyword to a local audio file.

    Args:
        track_id: Either a numeric Pixabay track ID (e.g. ``"12345"``) or a
                  mood keyword (key in ``MOOD_QUERY``).  When empty and *mood*
                  is set, *mood* is used as the search query.
        scratch:  Directory in which to write the downloaded audio file.
        mood:     Optional mood override; used as a fallback query when
                  *track_id* is not a numeric ID.

    Returns:
        Absolute path to the downloaded audio file, or ``None`` when:
          - ``PIXABAY_API_KEY`` is not set.
          - The API returns no results.
          - Any network or I/O error occurs.
    """
    key = _api_key()
    if not key:
        logger.info(
            "pixabay_audio: PIXABAY_API_KEY not set — skipping music track resolution"
        )
        return None

    try:
        import json  # noqa: PLC0415
        import urllib.parse  # noqa: PLC0415

        # Determine whether track_id is a direct numeric ID or a mood/query.
        if track_id and track_id.strip().isdigit():
            # Direct ID fetch: use the id parameter.
            params = urllib.parse.urlencode({"key": key, "id": track_id.strip()})
            url = f"{_API_BASE}?{params}"
        else:
            # Mood/keyword search.
            query = ""
            if track_id and track_id.strip() in MOOD_QUERY:
                query = MOOD_QUERY[track_id.strip()]
            elif mood and mood.strip() in MOOD_QUERY:
                query = MOOD_QUERY[mood.strip()]
            elif track_id and track_id.strip():
                query = track_id.strip()
            elif mood and mood.strip():
                query = mood.strip()
            else:
                query = "corporate background"

            params = urllib.parse.urlencode({
                "key": key,
                "q": query,
                "per_page": 3,
            })
            url = f"{_API_BASE}?{params}"

        logger.info("pixabay_audio: fetching %s", url)
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())

        hits = data.get("hits") or []
        if not hits:
            logger.info("pixabay_audio: no results for track_id=%r mood=%r", track_id, mood)
            return None

        audio_url = hits[0].get("audio") or hits[0].get("previewURL") or ""
        if not audio_url:
            logger.warning("pixabay_audio: hit has no audio URL: %r", hits[0])
            return None

        # Determine extension from URL.
        ext = ".mp3"
        if ".wav" in audio_url.lower():
            ext = ".wav"

        out_path = os.path.join(scratch, f"pixabay_track_{track_id or mood or 'auto'}{ext}")
        logger.info("pixabay_audio: downloading %s -> %s", audio_url, out_path)
        urllib.request.urlretrieve(audio_url, out_path)  # noqa: S310
        logger.info("pixabay_audio: downloaded %d bytes", os.path.getsize(out_path))
        return out_path

    except Exception as exc:  # noqa: BLE001
        logger.warning("pixabay_audio: resolve_track failed (non-fatal): %s", exc)
        return None
