"""Pexels video adapter (I/O — coverage-omitted).

Item 9: Search Pexels for vertical b-roll clips matching a keyword, download
the top result to a temp file, and return the local path for ffmpeg splicing.

API key: PEXELS_API_KEY env var.  When unset all functions return None + log.
Free tier: 200 req/hr, attribution required (shown in Clip Studio UI).
Docs: https://www.pexels.com/api/documentation/#videos-search

File boundary: this adapter is NEW (not the scaffold in adapters/broll_providers.py
which only does search).  This adapter adds the download step.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"


def _api_key() -> str | None:
    return os.getenv("PEXELS_API_KEY", "").strip() or None


def fetch_broll_clip(
    keyword: str,
    scratch: str,
    *,
    per_page: int = 5,
    min_duration: int = 5,
) -> str | None:
    """Search Pexels for a vertical video matching *keyword* and download it.

    Selects the first HD portrait-orientation result whose duration is at least
    *min_duration* seconds.  Downloads the best-quality ``hd`` or ``sd`` file
    and returns its local path.

    Args:
        keyword:      Search query string (e.g. ``"roof leak repair"``).
        scratch:      Directory in which to write the downloaded file.
        per_page:     Number of Pexels results to fetch (1–80, default 5).
        min_duration: Minimum video duration in seconds (default 5).

    Returns:
        Absolute path to the downloaded MP4, or ``None`` when:
          - ``PEXELS_API_KEY`` is not set.
          - No suitable result is found.
          - Any network or I/O error occurs.
    """
    key = _api_key()
    if not key:
        logger.info(
            "pexels: PEXELS_API_KEY not set — skipping b-roll fetch for %r", keyword
        )
        return None

    try:
        import json  # noqa: PLC0415
        import urllib.parse  # noqa: PLC0415

        params = urllib.parse.urlencode({
            "query": keyword,
            "per_page": per_page,
            "orientation": "portrait",
            "size": "medium",
        })
        url = f"{_PEXELS_VIDEO_SEARCH}?{params}"
        req = urllib.request.Request(  # noqa: S310
            url,
            headers={"Authorization": key},
        )
        logger.info("pexels: searching %s", url)
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())

        videos = data.get("videos") or []
        if not videos:
            logger.info("pexels: no results for keyword=%r", keyword)
            return None

        # Pick the first video that meets min_duration.
        chosen_video = None
        for v in videos:
            if (v.get("duration") or 0) >= min_duration:
                chosen_video = v
                break
        if chosen_video is None:
            chosen_video = videos[0]

        # Pick the best file: prefer hd > sd, portrait aspect if available.
        files = chosen_video.get("video_files") or []
        portrait_files = [
            f for f in files
            if f.get("width", 9999) < f.get("height", 0)  # width < height = portrait
        ]
        candidate_pool = portrait_files if portrait_files else files
        hd_files = [f for f in candidate_pool if f.get("quality") in ("hd", "sd")]
        best_file = hd_files[0] if hd_files else (candidate_pool[0] if candidate_pool else None)

        if best_file is None:
            logger.warning("pexels: no downloadable file for keyword=%r", keyword)
            return None

        download_url = best_file.get("link") or ""
        if not download_url:
            logger.warning("pexels: empty link in best_file for keyword=%r", keyword)
            return None

        # Sanitise keyword for filename (keep alphanumeric + underscore).
        safe_kw = "".join(c if c.isalnum() or c == "_" else "_" for c in keyword)[:40]
        out_path = os.path.join(scratch, f"broll_{safe_kw}.mp4")

        logger.info("pexels: downloading %s -> %s", download_url, out_path)
        urllib.request.urlretrieve(download_url, out_path)  # noqa: S310
        logger.info("pexels: downloaded %d bytes", os.path.getsize(out_path))
        return out_path

    except Exception as exc:  # noqa: BLE001
        logger.warning("pexels: fetch_broll_clip failed (non-fatal): %s", exc)
        return None


def build_broll_overlay_cmd(
    primary_path: str,
    broll_path: str,
    out_path: str,
    *,
    overlay_start: float = 0.0,
    overlay_end: float = 4.0,
) -> list[str]:
    """Build an ffmpeg arg list that overlays *broll_path* onto *primary_path*.

    The b-roll video is scaled to fill the primary frame (scale to primary
    dimensions), trimmed to [0, overlay_end - overlay_start], and overlaid
    from *overlay_start* to *overlay_end* using the ``overlay`` filter with
    ``enable='between(t,...)'``.

    Both inputs must be the same resolution (1080×1920 for 9:16).

    Args:
        primary_path:   Path to the primary (already reframed) video.
        broll_path:     Path to the downloaded b-roll clip.
        out_path:       Destination path for the composited output.
        overlay_start:  Timestamp in *primary_path* where b-roll starts (seconds).
        overlay_end:    Timestamp in *primary_path* where b-roll ends (seconds).

    Returns:
        A ``list[str]`` suitable for ``subprocess.run(..., shell=False)``.
    """
    ffmpeg = os.getenv("FFMPEG_BIN", "ffmpeg")
    duration = max(0.01, overlay_end - overlay_start)

    # filter_complex:
    #   [1:v] scale to primary frame size, trim to overlay duration → [broll_scaled]
    #   [0:v][broll_scaled] overlay with time-enable between overlay_start/end → [vout]
    fc = (
        f"[1:v]scale=iw:ih:force_original_aspect_ratio=increase,"
        f"crop=iw:ih,setpts=PTS-STARTPTS,trim=0:{duration:.6f},setpts=PTS-STARTPTS[broll_t];"
        f"[0:v][broll_t]overlay=0:0:enable='between(t,{overlay_start:.6f},{overlay_end:.6f})'[vout]"
    )

    return [
        ffmpeg, "-y",
        "-i", primary_path,
        "-i", broll_path,
        "-filter_complex", fc,
        "-map", "[vout]",
        "-map", "0:a?",
        "-c:v", "libx264", "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        out_path,
    ]
