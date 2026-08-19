"""Edit / chop plan from a transcript. Pure — no I/O.

Long-form queue is videos over LONG_SECS (15 min). Under EVAL_MAX_SECS (30 min)
we choose split vs tighten from topic blocks and fluff density. Over 30 min
the default is chop into pieces; fluff cuts still show what to drop.
"""
from __future__ import annotations

import re

LONG_SECS = 900.0
EVAL_MAX_SECS = 1800.0
MIN_PIECE_SECS = 90.0
MIN_KEEP_SECS = 6.0

_FLUFF = re.compile(
    r"\b("
    r"um+|uh+|er+|ah+|hmm+|you know|i mean|kind of|sort of|like i said|"
    r"anyway|so yeah|yeah so|right\?|let me see|hold on|where was i|"
    r"as i was saying|thanks for watching|smash (that |the )?like|"
    r"hit subscribe|don't forget to like|comment below|see you (next|in the)|"
    r"what's up guys|hey guys"
    r")\b",
    re.I,
)
_CONTENT = re.compile(r"[a-z0-9]{3,}", re.I)
_STOP = frozenset({
    "the", "and", "for", "you", "that", "this", "with", "have", "from",
    "they", "was", "are", "but", "not", "all", "can", "just", "about",
})


def _tokens(text: str) -> list[str]:
    return [w for w in _CONTENT.findall((text or "").lower()) if w not in _STOP]


def _fluff_ratio(text: str) -> float:
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words:
        return 0.0
    hits = len(_FLUFF.findall(text or ""))
    return min(1.0, hits / max(1, len(words)))


def _is_fluff(text: str, duration: float) -> bool:
    if duration <= 0:
        return True
    ratio = _fluff_ratio(text)
    toks = _tokens(text)
    if ratio >= 0.18:
        return True
    if len(toks) < 4 and duration >= 8:
        return True
    return False


def _merge_ranges(ranges: list[dict], gap: float = 4.0) -> list[dict]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: r["start"])
    out = [dict(ordered[0])]
    for r in ordered[1:]:
        if r["start"] <= out[-1]["end"] + gap:
            out[-1]["end"] = max(out[-1]["end"], r["end"])
        else:
            out.append(dict(r))
    return [r for r in out if r["end"] - r["start"] >= MIN_KEEP_SECS]


def keep_ranges(segments: list[dict]) -> list[dict]:
    keep = []
    for s in segments:
        text = (s.get("text") or "").strip()
        start = float(s.get("start") or 0)
        end = float(s.get("end") or start)
        if end <= start:
            continue
        if _is_fluff(text, end - start):
            continue
        keep.append({"start": start, "end": end, "label": text[:80]})
    return _merge_ranges(keep)


def topic_blocks(topics: list[dict], duration: float) -> list[dict]:
    stamped = []
    for t in topics:
        label = (t.get("label") or "").strip()
        if not label:
            continue
        stamped.append({"label": label, "start": float(t.get("start") or 0)})
    if not stamped:
        return [{"label": "", "start": 0.0, "end": duration}]
    stamped.sort(key=lambda t: t["start"])
    blocks = []
    for i, t in enumerate(stamped):
        end = stamped[i + 1]["start"] if i + 1 < len(stamped) else duration
        if end - t["start"] < MIN_PIECE_SECS:
            if blocks:
                blocks[-1]["end"] = end
            continue
        blocks.append({"label": t["label"], "start": t["start"], "end": end})
    if not blocks:
        return [{"label": stamped[0]["label"], "start": 0.0, "end": duration}]
    blocks[0]["start"] = 0.0
    blocks[-1]["end"] = duration
    return blocks


def recommend(*, duration: float, keep_seconds: float, fluff_ratio: float, n_pieces: int) -> str:
    if duration >= EVAL_MAX_SECS:
        return "chop"
    if n_pieces >= 2:
        return "split"
    if keep_seconds + 1 < duration and fluff_ratio >= 0.08:
        return "tighten"
    if duration >= LONG_SECS:
        return "chop"
    return "tighten"


def plan(
    *,
    duration: float,
    segments: list[dict],
    topics: list[dict] | None = None,
) -> dict:
    duration = float(duration or 0)
    segs = list(segments or [])
    keep = keep_ranges(segs)
    keep_seconds = sum(k["end"] - k["start"] for k in keep)
    cut_seconds = max(0.0, duration - keep_seconds)
    fluff_ratio = cut_seconds / duration if duration else 0.0

    blocks = topic_blocks(topics or [], duration)
    pieces = [b for b in blocks if b["end"] - b["start"] >= MIN_PIECE_SECS]
    if len(pieces) < 2:
        pieces = [{"label": (blocks[0]["label"] if blocks else ""), "start": 0.0, "end": duration}]

    action = recommend(
        duration=duration,
        keep_seconds=keep_seconds,
        fluff_ratio=fluff_ratio,
        n_pieces=len(pieces) if len(pieces) > 1 else 1,
    )
    if not segs:
        action = "chop" if duration >= LONG_SECS else "unknown"
        keep = []
        keep_seconds = 0.0
        cut_seconds = 0.0
        fluff_ratio = 0.0

    if action == "tighten":
        why = (
            f"One topic under 30 min. Cut ~{int(cut_seconds)}s of fluff and "
            f"release a {int(keep_seconds)}s cut."
        )
    elif action == "split":
        why = f"{len(pieces)} distinct sections — chop at the topic changes."
    elif action == "chop":
        why = "Over 30 min (or no clean tighten). Slice into standalone clips."
    else:
        why = "No transcript to score."

    return {
        "duration": duration,
        "action": action,
        "reason": why,
        "target_seconds": round(keep_seconds if action == "tighten" else duration, 1),
        "cut_seconds": round(cut_seconds, 1),
        "fluff_ratio": round(fluff_ratio, 3),
        "keep": [{"start": round(k["start"], 1), "end": round(k["end"], 1),
                  "label": k.get("label") or ""} for k in keep],
        "pieces": [{"start": round(p["start"], 1), "end": round(p["end"], 1),
                    "label": p.get("label") or ""} for p in pieces],
    }
