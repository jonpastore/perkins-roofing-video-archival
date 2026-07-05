"""Pure mini-series planner — Content-Graph ranked candidate selection and part segmentation.
No I/O; all functions are deterministic."""

import re

# --- title cleaning -------------------------------------------------------
# Unicode emoji blocks + variation selectors (mirrors api/routes/video.clean_label).
_EMOJI_RE = re.compile(
    "[\U00002600-\U000027BF"   # misc symbols
    "\U0001F300-\U0001FAFF"    # emoji / pictographs
    "\U0000FE00-\U0000FE0F"    # variation selectors
    "\U00002190-\U000021FF"    # arrows
    "\U00002B00-\U00002BFF"    # misc symbols and arrows
    "]+",
    flags=re.UNICODE,
)
# Hashtag tokens anywhere (e.g. "#roofing") and leading junk symbols.
_HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
_LEADING_JUNK_RE = re.compile(r"^[\s#@*•\-–—|]+")
_TRAILING_JUNK_RE = re.compile(r"[\s#@*•\-–—|]+$")


def clean_title(text: str | None) -> str:
    """Strip emojis and hashtags from a raw source-video title; collapse whitespace.

    Returns a clean, human-readable name suitable for MiniSeries.title and part
    titles. Empty/None input yields ''.
    """
    if not text:
        return ""
    cleaned = _EMOJI_RE.sub("", text)
    cleaned = _HASHTAG_RE.sub(" ", cleaned)
    cleaned = _LEADING_JUNK_RE.sub("", cleaned)
    cleaned = _TRAILING_JUNK_RE.sub("", cleaned)
    return " ".join(cleaned.split())


# Content-graph kinds ranked by clip value (CTAs and claims make the punchiest
# standalone reels; topics are the fallback structure).
_KIND_PRIORITY = {"ctas": 0, "claims": 1, "objections": 2, "topics": 3}


def propose_clips(
    video_title: str | None,
    duration: float,
    graph_nodes: list[dict],
    *,
    max_clips: int = 5,
    clip_len: float = 40.0,
    min_clip_len: float = 20.0,
    max_clip_len: float = 60.0,
) -> list[dict]:
    """Content-driven clip selection with REAL second offsets (deterministic fallback).

    Picks the highest-value Content-Graph moments (by kind priority, then time) and
    turns each into a standalone clip window anchored at the node's real ``start``
    second. Windows are:
      * real second offsets into the source video (never fractions),
      * clamped to ``[0, duration]``,
      * ``clip_len`` seconds long (bounded by ``min_clip_len``/``max_clip_len`` and duration),
      * de-overlapped and returned in chronological order.

    Each node dict may carry ``label``, ``start``, and optionally ``kind``.
    Titles are ``"<clean video name> — <topic> (Part N)"``.

    When there are no usable nodes, falls back to evenly-spaced clips across the
    video so callers always get real-second windows (never the degenerate 0/.25/.5).

    NOTE (future work): full topic-driven MULTI-source mini-series — one series
    pulling the best clips across SEVERAL source videos — is a larger step. This
    function only builds correct single-source clips. See jobs/propose_series_job.py.
    """
    duration = max(float(duration or 0.0), 0.0)
    name = clean_title(video_title)

    # Effective clip length, bounded and never larger than the video itself.
    target_len = min(max(float(clip_len), float(min_clip_len)), float(max_clip_len))
    if duration > 0:
        target_len = min(target_len, duration)

    # Candidate anchors: nodes with a real, in-bounds start second.
    anchors: list[tuple[int, float, str]] = []
    for n in graph_nodes:
        start = float(n.get("start") or 0.0)
        if duration > 0 and start >= duration:
            continue
        if start < 0:
            continue
        prio = _KIND_PRIORITY.get(str(n.get("kind") or "topics"), 3)
        label = (n.get("label") or "").strip()
        anchors.append((prio, start, label))

    if not anchors or duration <= 0:
        return _even_clips(name, duration, target_len, max_clips)

    # Rank by kind priority then chronological, take the best, then re-sort by time.
    anchors.sort(key=lambda a: (a[0], a[1]))
    chosen = anchors[:max_clips]
    chosen.sort(key=lambda a: a[1])

    clips: list[dict] = []
    prev_end = 0.0
    for _prio, start, label in chosen:
        s = max(start, prev_end)
        if duration > 0 and s >= duration:
            break
        e = min(s + target_len, duration) if duration > 0 else s + target_len
        if e - s < min(min_clip_len, target_len):
            # Window collapsed against the end of the video; stop.
            continue
        clips.append({
            "title": _part_title(name, label, len(clips) + 1),
            "start": round(s, 3),
            "end": round(e, 3),
        })
        prev_end = e

    if not clips:
        return _even_clips(name, duration, target_len, max_clips)
    return clips


def _part_title(name: str, topic: str, n: int) -> str:
    """'<clean video name> — <topic> (Part N)'; degrade gracefully when parts missing."""
    topic = clean_title(topic)
    head = " — ".join(x for x in (name, topic) if x)
    if not head:
        return f"Part {n}"
    return f"{head} (Part {n})"


def _even_clips(name: str, duration: float, clip_len: float, max_clips: int) -> list[dict]:
    """Evenly-spaced real-second clip windows when no content anchors are available."""
    if duration <= 0:
        # No known duration — a single best-effort clip from 0.
        return [{"title": _part_title(name, "", 1), "start": 0.0, "end": round(clip_len, 3)}]

    n = max(1, min(max_clips, int(duration // clip_len) or 1))
    if n == 1:
        return [{"title": _part_title(name, "", 1), "start": 0.0, "end": round(min(clip_len, duration), 3)}]

    # Distribute clip start points evenly across the video, each clip_len long.
    span = duration - clip_len
    step = span / (n - 1) if n > 1 else 0.0
    clips: list[dict] = []
    prev_end = 0.0
    for i in range(n):
        s = max(round(i * step, 3), prev_end)
        e = min(s + clip_len, duration)
        if e - s <= 0:
            break
        clips.append({"title": _part_title(name, "", len(clips) + 1), "start": round(s, 3), "end": round(e, 3)})
        prev_end = e
    return clips


def rank_candidates(videos: list[dict]) -> list[dict]:
    """Rank candidate videos by Content-Graph density (graph_nodes / duration), then by duration.

    Each input dict must have: video_id (str), duration (float|int), graph_nodes (int).
    Returns a new list sorted by (density desc, duration desc), with 'density' added to each dict.
    """
    result = []
    for v in videos:
        duration = max(float(v["duration"]), 1)
        density = v["graph_nodes"] / duration
        result.append({**v, "density": density})
    result.sort(key=lambda v: (v["density"], v["duration"]), reverse=True)
    return result


def propose_parts(
    video_id: str,
    duration: float,
    graph_nodes: list[dict],
    *,
    min_parts: int = 4,
    max_parts: int = 7,
) -> list[dict]:
    """Derive 4-7 sequential parts from Content-Graph node timestamps.

    Each graph_node has {"label": str, "start": float|int}.
    Nodes are sorted by start time; topic boundaries become part cut-points.
    Count is clamped to [min_parts, max_parts].
    If there are fewer than min_parts nodes (or fewer than min_parts usable interior
    boundaries), the duration is split evenly into min_parts.

    Returns list of {"title": str, "start": float, "end": float}.
    """
    duration = float(duration)
    nodes_sorted = sorted(graph_nodes, key=lambda n: float(n["start"]))

    def _even_split() -> list[dict]:
        step = duration / min_parts
        return [
            {
                "title": f"Part {i + 1}",
                "start": round(i * step, 6),
                "end": round(min((i + 1) * step, duration), 6),
            }
            for i in range(min_parts)
        ]

    # Fewer nodes than min_parts → even split
    if len(nodes_sorted) < min_parts:
        return _even_split()

    # Interior cut-points: node starts strictly inside (0, duration)
    interior = sorted({
        float(n["start"])
        for n in nodes_sorted
        if 0.0 < float(n["start"]) < duration
    })

    # Not enough usable interior boundaries → even split
    if len(interior) < min_parts - 1:
        return _even_split()

    # Clamp target part count to [min_parts, max_parts]
    # Max possible parts with available interior cuts is len(interior) + 1
    n_parts = min(len(interior) + 1, max_parts)
    n_parts = max(n_parts, min_parts)
    n_cuts = n_parts - 1

    if n_cuts >= len(interior):
        cuts = interior
    else:
        # Evenly sample n_cuts indices from interior boundaries
        step = (len(interior) - 1) / n_cuts
        cuts = [interior[round(i * step)] for i in range(n_cuts)]
        cuts = sorted(set(cuts))
        # Safety: if rounding collapsed values, pad from interior
        if len(cuts) < n_cuts:  # pragma: no cover
            cuts = interior[:n_cuts]

    # Label lookup: nearest node to a given timestamp
    def nearest_label(t: float) -> str:
        best = min(nodes_sorted, key=lambda n: abs(float(n["start"]) - t))
        return best.get("label") or ""

    # Build parts from [0, cut1, cut2, …, duration]
    endpoints = [0.0] + [float(c) for c in cuts] + [duration]
    parts = []
    for i in range(len(endpoints) - 1):
        start = endpoints[i]
        end = endpoints[i + 1]
        # Title from the cut-point that opens the NEXT segment (topic boundary label)
        if i < len(endpoints) - 2:
            label = nearest_label(endpoints[i + 1])
        else:
            label = nearest_label(start)
        title = label if label else f"Part {i + 1}"
        parts.append({"title": title, "start": start, "end": end})

    return parts
