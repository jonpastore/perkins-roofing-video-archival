"""Pure availability detector for archived YouTube videos.

availability_from_batch(video_id, stats_map) -> str

Decision table:
  stats_map is falsy (None / {})  → "unknown"   (whole-batch API failure; never flag as gone)
  video_id in stats_map           → "available"
  otherwise                       → "unavailable" (batch succeeded but video absent = deleted/private)
"""
from __future__ import annotations


def availability_from_batch(video_id: str, stats_map: dict | None) -> str:
    """Return the YouTube availability status of *video_id* given a batch stats map.

    Args:
        video_id:  The YouTube video ID to check.
        stats_map: The dict returned by yt_stats.fetch_stats() for the batch
                   that contained this video.  None or empty dict means the
                   whole API call failed — treat as transient, do not flag.

    Returns:
        "unknown"     — stats_map was falsy; cannot determine status.
        "available"   — video is in the stats_map; it is live on YouTube.
        "unavailable" — stats_map has entries but this video is absent;
                        it was deleted or made private.
    """
    if not stats_map:
        return "unknown"
    if video_id in stats_map:
        return "available"
    return "unavailable"
