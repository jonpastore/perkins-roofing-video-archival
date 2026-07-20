"""Auto-censor detection: map flagged spoken words to audio-mute spans.

Pure logic — the render pipeline applies the returned spans (ffmpeg volume mute over
[start,end)). Detection reuses the crude denylist in core.content_safety plus the
tenant's configured safety_denylist.
"""
from __future__ import annotations

from core.content_safety import denylist_hits


def _attr(item, key):
    return item[key] if isinstance(item, dict) else getattr(item, key)


def _flagged(token: str, deny: set[str]) -> bool:
    """True when a spoken token hits the tenant denylist or the crude denylist."""
    norm = (token or "").lower().strip(".,!?;:\"'")
    return bool(norm and (norm in deny or denylist_hits(token)))


def mask_word(token: str) -> str:
    """Replace a token with a block mask of similar length (min 2), for captions."""
    core = (token or "").strip()
    return "▇" * max(2, len(core)) if core else token


def mask_caption_words(words, extra_denylist=()) -> list:
    """Return *words* with flagged tokens' text replaced by a block mask (timings and
    all other keys intact), so a censored word is hidden in burned captions too — not
    just muted in the audio track."""
    deny = {t.strip().lower() for t in extra_denylist if t and t.strip()}
    out = []
    for w in words:
        token = _attr(w, "word") or ""
        if _flagged(token, deny):
            masked = dict(w) if isinstance(w, dict) else {"word": token, "start": _attr(w, "start")}
            masked["word"] = mask_word(token)
            out.append(masked)
        else:
            out.append(w)
    return out


def censor_spans(words, extra_denylist=(), tail_pad: float = 0.4) -> list[tuple[float, float]]:
    """Return merged [start, end) audio spans to mute for flagged words.

    Args:
        words: iterable of {word, start} — dicts or ORM Word rows, any order.
        extra_denylist: tenant safety_denylist terms (case-insensitive, exact word).
        tail_pad: seconds to mute past the last word when there is no following word.

    A word is flagged when it exactly matches the tenant denylist or hits the crude
    denylist. Word rows carry only a start, so a word's end is the next word's start
    (tail_pad for the last). A flag right before a long pause thus over-mutes into the
    pause — acceptable for censoring (over-mute beats leaking the term).
    # ponytail: next-word-start end heuristic; persist word end-times if precision matters.
    """
    deny = {t.strip().lower() for t in extra_denylist if t and t.strip()}
    ordered = sorted(
        ({"word": _attr(w, "word"), "start": float(_attr(w, "start"))} for w in words),
        key=lambda w: w["start"],
    )
    spans: list[tuple[float, float]] = []
    for i, w in enumerate(ordered):
        if _flagged(w["word"], deny):
            end = ordered[i + 1]["start"] if i + 1 < len(ordered) else w["start"] + tail_pad
            spans.append((w["start"], end))
    return _merge(spans)


def mute_audio_filter(spans: list[tuple[float, float]]) -> str:
    """Build an ffmpeg ``-af`` value that silences the audio over each span.

    Returns "" when there are no spans (caller should skip the filter entirely).
    ``volume`` is enabled whenever ``t`` falls in any span — the sum of per-span
    ``between()`` terms is >0 inside a span, 0 outside.
    """
    if not spans:
        return ""
    terms = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in spans)
    return f"volume=enable='{terms}':volume=0"


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping/touching spans into a minimal disjoint set."""
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]
