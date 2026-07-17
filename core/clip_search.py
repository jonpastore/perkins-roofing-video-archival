"""Pure prompt-to-clip candidate builder — no I/O, no LLM calls.

Track: prompt-to-clip — natural-language clip search across the whole video corpus
(cross-video answer to ClipAnything). Mirrors core/clip_select.py's style: pure
functions only, LLM calls injected by callers via ``score_fn``.
"""
from __future__ import annotations

from core.clip_select import score_segments

# Clip-length window bounds (seconds) — matches the 20-60s guidance already used
# by clip_select's suggestion prompt.
_MIN_WINDOW = 20.0
_MAX_WINDOW = 60.0

# Safety cap on candidates handed to the (expensive) LLM ranking step.
_TOP_N = 24


def _pad_to_window(start: float, end: float) -> tuple[float, float]:
    """Symmetrically pad a [start, end] window up to at least _MIN_WINDOW seconds."""
    deficit = _MIN_WINDOW - (end - start)
    if deficit <= 0:
        return start, end
    pad = deficit / 2
    new_start = max(0.0, start - pad)
    return new_start, new_start + _MIN_WINDOW


def build_candidates(prompt: str, chunks: list) -> list[dict]:
    """Convert retrieval chunks into deduped, clip-length candidate segments.

    ``chunks`` items are dicts carrying at least ``video_id``, ``start``, ``end``,
    ``text``, and ``score`` (the shape produced by app.retrieval.hybrid_search's
    "chunks" list once normalised to plain dicts by the caller). Extra keys are
    ignored; malformed entries are silently skipped.

    Short windows are padded symmetrically up to _MIN_WINDOW seconds; windows
    longer than _MAX_WINDOW are truncated. Overlapping windows within the same
    video are deduped, keeping the higher-scoring one. Results are capped at the
    top _TOP_N by retrieval score, sorted descending.

    ``prompt`` is accepted for interface symmetry with ``search_to_clips`` /
    future prompt-aware windowing; it does not affect the current windowing logic.

    Never raises. Empty/all-malformed input -> [].
    """
    windows: list[dict] = []
    for ch in chunks:
        try:
            video_id = ch.get("video_id")
            start = float(ch.get("start") or 0.0)
            end = float(ch.get("end") or 0.0)
            text = str(ch.get("text") or "").strip()
            score = float(ch.get("score") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if not video_id or end <= start:
            continue

        start, end = _pad_to_window(start, end)
        if end - start > _MAX_WINDOW:
            end = start + _MAX_WINDOW

        windows.append({
            "video_id": str(video_id),
            "start": start,
            "end": end,
            "text": text,
            "score": score,
        })

    if not windows:
        return []

    # Dedupe overlapping windows per video, keeping the higher-scoring one first.
    windows.sort(key=lambda w: w["score"], reverse=True)
    kept: list[dict] = []
    for w in windows:
        if any(
            k["video_id"] == w["video_id"] and w["start"] < k["end"] and k["start"] < w["end"]
            for k in kept
        ):
            continue
        kept.append(w)

    return kept[:_TOP_N]


def _by_retrieval_score(candidates: list[dict]) -> list[dict]:
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    return [
        {
            "video_id": c["video_id"],
            "start": c["start"],
            "end": c["end"],
            "score": c["score"],
            "reason": "",
            "text": c["text"],
        }
        for c in ranked
    ]


def search_to_clips(prompt: str, chunks: list, score_fn: object = None) -> list[dict]:
    """Pipeline glue: build_candidates -> LLM-rank (via score_fn) or retrieval-rank.

    ``score_fn`` is passed straight through to ``core.clip_select.score_segments``
    (``callable[[str], str] | None``). When given, candidates are re-ranked by
    the LLM's viral-moment rubric; the LLM's ``start``/``end`` are matched back
    (rounded to 2dp, matching the prompt's own formatting) to their source
    candidate to recover ``video_id``/``text``. When ``score_fn`` is ``None``,
    or the LLM ranking raises/returns nothing usable, falls back to ordering by
    retrieval score.

    Each result dict: ``{video_id, start, end, score, reason, text}``.
    Never raises; empty input -> [].
    """
    candidates = build_candidates(prompt, chunks)
    if not candidates:
        return []

    if score_fn is None:
        return _by_retrieval_score(candidates)

    try:
        moments = score_segments(candidates, score_fn)
    except Exception:  # noqa: BLE001 — score_fn is caller-injected I/O; never propagate
        return _by_retrieval_score(candidates)

    if not moments:
        return _by_retrieval_score(candidates)

    # candidates are score-descending; setdefault keeps the HIGHER-scoring one when
    # two windows round to the same (start,end) key (a bare dict comp would keep the last).
    by_window: dict = {}
    for c in candidates:
        by_window.setdefault((round(c["start"], 2), round(c["end"], 2)), c)
    results = []
    for m in moments:
        src = by_window.get((round(m["start"], 2), round(m["end"], 2)))
        if src is None:
            continue
        results.append({
            "video_id": src["video_id"],
            "start": m["start"],
            "end": m["end"],
            "score": m["score"],
            "reason": m["reason"],
            "text": src["text"],
        })
    if not results:
        # LLM mutated every window's times so nothing matched back — retrieval
        # order is still a correct answer; an empty result here would not be.
        return _by_retrieval_score(candidates)
    return results
