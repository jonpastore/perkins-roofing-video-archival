"""Pure b-roll cue builder and asset planner — no I/O, deterministic.

Track A7: derives b-roll insertion cues from transcript segments (roofing-tuned
keyword extraction), then maps cues to available assets for compositing.

Compositing specs reuse core.clip_fx.OverlaySpec so the ffmpeg adapter can
consume the plan without re-parsing.

No subprocess calls, no HTTP calls, no file I/O here.  All execution lives in
adapters/ and jobs/.
"""
from __future__ import annotations

import re

from core.clip_fx import OverlaySpec

# ---------------------------------------------------------------------------
# Roofing keyword vocabulary — maps segment text tokens to search keywords.
# Ordered from most-specific to most-general; first match wins.
# ---------------------------------------------------------------------------

_ROOFING_KEYWORD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bhvhz\b", re.IGNORECASE), "hvhz roofing"),
    (re.compile(r"\b25[- ]?rule\b", re.IGNORECASE), "25 percent rule roof"),
    (re.compile(r"\bwind\s*mit(igation)?\b", re.IGNORECASE), "wind mitigation inspection"),
    (re.compile(r"\bcitizens\s*insur\w*\b", re.IGNORECASE), "citizens insurance florida"),
    (re.compile(r"\bstorm\s*(damage|repair)\b", re.IGNORECASE), "storm damage roof repair"),
    (re.compile(r"\bflashing\b", re.IGNORECASE), "roof flashing detail"),
    (re.compile(r"\bgutters?\b", re.IGNORECASE), "roof gutters installation"),
    (re.compile(r"\bshingle\b", re.IGNORECASE), "asphalt shingle roofing"),
    (re.compile(r"\bmetal\s*roof\b", re.IGNORECASE), "metal roof installation"),
    (re.compile(r"\btile\s*roof\b", re.IGNORECASE), "tile roof florida"),
    (re.compile(r"\bleak(ing|s)?\b", re.IGNORECASE), "roof leak repair"),
    (re.compile(r"\binspect(ion|or)?\b", re.IGNORECASE), "roof inspection"),
    (re.compile(r"\binstal(l|lation|ling)?\b", re.IGNORECASE), "roofing installation"),
    (re.compile(r"\brepair\b", re.IGNORECASE), "roof repair"),
    (re.compile(r"\bventil(ation|ator)?\b", re.IGNORECASE), "roof ventilation"),
    (re.compile(r"\bdeck(ing)?\b", re.IGNORECASE), "roof decking"),
    (re.compile(r"\binsur\w*\b", re.IGNORECASE), "homeowner insurance roof"),
    (re.compile(r"\broof\w*\b", re.IGNORECASE), "roofing contractor florida"),
]

_FALLBACK_KEYWORD = "roofing contractor florida"


def _derive_keyword(text: str) -> str:
    """Return the best roofing search keyword for *text*.

    Iterates ``_ROOFING_KEYWORD_RULES`` in order; returns the keyword for the
    first matching rule.  Falls back to ``_FALLBACK_KEYWORD`` when nothing matches.
    """
    for pattern, keyword in _ROOFING_KEYWORD_RULES:
        if pattern.search(text):
            return keyword
    return _FALLBACK_KEYWORD


# ---------------------------------------------------------------------------
# broll_cues
# ---------------------------------------------------------------------------

#: Default overlay duration for a single b-roll cue (seconds).
_DEFAULT_WINDOW_DURATION: float = 4.0


def broll_cues(
    segments: list[dict],
    *,
    max_cues: int = 5,
    min_gap: float = 8.0,
) -> list[dict]:
    """Derive b-roll insertion cues from transcript segments.

    Each cue identifies a moment in the timeline where b-roll footage should
    appear, together with a search keyword tuned for roofing content.

    Selection strategy: iterate segments in order; emit a cue at the midpoint
    of each segment that is at least *min_gap* seconds after the previous cue.
    Stop after *max_cues* cues.

    Args:
        segments:   Transcript segments.  Each must carry ``start`` (float),
                    ``end`` (float), and ``text`` (str).  Extra keys are ignored.
        max_cues:   Maximum number of cues to return (must be > 0).
        min_gap:    Minimum gap in seconds between consecutive cue timestamps
                    (must be ≥ 0).

    Returns:
        List of cue dicts::

            {
                "time":    float,  # insertion timestamp (midpoint of segment)
                "keyword": str,    # roofing-tuned search keyword
                "segment_start": float,
                "segment_end":   float,
            }

        Returns ``[]`` for empty input or when *max_cues* is 0.

    Raises:
        ValueError: if *max_cues* < 1 or *min_gap* < 0.
    """
    if max_cues < 1:
        raise ValueError(f"max_cues must be ≥ 1, got {max_cues}")
    if min_gap < 0:
        raise ValueError(f"min_gap must be ≥ 0, got {min_gap}")
    if not segments:
        return []

    cues: list[dict] = []
    last_time: float | None = None

    for seg in segments:
        if len(cues) >= max_cues:
            break

        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)
        text = str(seg.get("text") or "")

        midpoint = (start + end) / 2.0

        if last_time is not None and (midpoint - last_time) < min_gap:
            continue

        keyword = _derive_keyword(text)
        cues.append({
            "time": midpoint,
            "keyword": keyword,
            "segment_start": start,
            "segment_end": end,
        })
        last_time = midpoint

    return cues


# ---------------------------------------------------------------------------
# plan_broll
# ---------------------------------------------------------------------------


def plan_broll(
    cues: list[dict],
    assets: list[dict],
    *,
    window_duration: float = _DEFAULT_WINDOW_DURATION,
) -> list[dict]:
    """Map b-roll cues to available assets and produce compositing specs.

    Each cue is matched to the best available asset by keyword similarity
    (exact substring match first, then any available asset as fallback).
    Unmatched cues with no fallback asset are included with ``asset=None``
    so callers can decide whether to skip them or generate AI images.

    Compositing spec reuses :class:`core.clip_fx.OverlaySpec` — the ``x``/``y``
    positions default to full-frame (``"0"``) so the b-roll fills the frame when
    composited at 1:1 scale.  Callers may override x/y/size as needed.

    Args:
        cues:            Output of :func:`broll_cues`.  Each must carry ``time``
                         (float), ``keyword`` (str), ``segment_start`` (float),
                         ``segment_end`` (float).
        assets:          Available stock/AI assets.  Each must carry ``url`` (str)
                         and ``keyword`` (str — the search term used to fetch it).
                         Extra keys (``id``, ``thumb``, etc.) are passed through
                         in the plan entry.
        window_duration: Duration of the b-roll overlay window in seconds.

    Returns:
        List of plan dicts, one per cue::

            {
                "time":             float,       # insertion timestamp
                "keyword":          str,          # cue keyword
                "asset":            dict | None,  # matched asset dict (or None)
                "overlay_start":    float,        # = time
                "overlay_end":      float,        # = time + window_duration
                "overlay_spec":     OverlaySpec | None,
            }

        ``overlay_spec`` is ``None`` when no asset is available for the cue.

    Raises:
        ValueError: if *window_duration* ≤ 0.
    """
    if window_duration <= 0:
        raise ValueError(f"window_duration must be > 0, got {window_duration}")

    def _best_asset(keyword: str) -> dict | None:
        # Exact substring match (case-insensitive) first.
        kw_lower = keyword.lower()
        for asset in assets:
            asset_kw = str(asset.get("keyword") or "").lower()
            if kw_lower in asset_kw or asset_kw in kw_lower:
                return asset
        # Fallback: any asset.
        return assets[0] if assets else None

    plan: list[dict] = []
    for cue in cues:
        t = float(cue.get("time") or 0.0)
        keyword = str(cue.get("keyword") or "")
        overlay_start = t
        overlay_end = t + window_duration

        asset = _best_asset(keyword)

        if asset is not None:
            image_path = str(asset.get("url") or "")
            spec: OverlaySpec | None = OverlaySpec(
                image_path=image_path,
                x="0",
                y="0",
                start=overlay_start,
                end=overlay_end,
            )
        else:
            spec = None

        plan.append({
            "time": t,
            "keyword": keyword,
            "asset": asset,
            "overlay_start": overlay_start,
            "overlay_end": overlay_end,
            "overlay_spec": spec,
        })

    return plan
