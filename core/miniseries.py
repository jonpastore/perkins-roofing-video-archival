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


def _topic_relevance(topic: str, label: str) -> int:
    """Cheap lexical overlap score between a topic and a node label (0 = unrelated)."""
    t_words = {w for w in re.split(r"[^a-z0-9]+", topic.lower()) if len(w) > 3}
    l_norm = label.lower()
    if not t_words:
        return 0
    if topic.lower() in l_norm:
        return 100
    return sum(1 for w in t_words if w in l_norm)


def propose_topic_clips(
    topic: str,
    sources: list[dict],
    *,
    max_clips: int = 5,
    clip_len: float = 40.0,
    min_clip_len: float = 20.0,
    max_clip_len: float = 60.0,
) -> list[dict]:
    """Topic-driven MULTI-source reel: one best clip from each of SEVERAL videos.

    For a single topic, picks the single most on-topic, highest-value Content-Graph
    moment from each source video and assembles them into one series whose parts
    span multiple source videos. Each returned part carries its OWN ``video_id`` (and
    ``video_title``) so the renderer/UI use the correct source per part.

    ``sources``: list of dicts, each ``{video_id, video_title, duration, graph_nodes}``
    where ``graph_nodes`` is ``[{label, start, kind}]`` for that video.

    Returns ``[{video_id, video_title, title, start, end}]`` — real second offsets,
    ranked by (topic relevance, kind priority), best first, capped at ``max_clips``.
    Sources with no usable on-topic anchor are skipped.
    """
    target_len = min(max(float(clip_len), float(min_clip_len)), float(max_clip_len))
    topic_name = clean_title(topic) or topic

    candidates: list[tuple[int, int, dict]] = []  # (relevance desc, kind prio asc, part)
    for src in sources:
        video_id = src.get("video_id")
        if not video_id:
            continue
        duration = max(float(src.get("duration") or 0.0), 0.0)
        vid_name = clean_title(src.get("video_title")) or video_id

        best = None  # (relevance, -kind_prio, start, label)
        for n in src.get("graph_nodes") or []:
            start = float(n.get("start") or 0.0)
            if start < 0 or (duration > 0 and start >= duration):
                continue
            label = (n.get("label") or "").strip()
            rel = _topic_relevance(topic, label)
            if rel <= 0:
                continue
            prio = _KIND_PRIORITY.get(str(n.get("kind") or "topics"), 3)
            key = (rel, -prio, -start)  # prefer relevant, punchy, earlier
            if best is None or key > best[0]:
                best = (key, start, label, rel, prio)
        if best is None:
            continue

        _key, start, label, rel, prio = best
        eff_len = min(target_len, duration) if duration > 0 else target_len
        end = min(start + eff_len, duration) if duration > 0 else start + eff_len
        if end - start < min(min_clip_len, eff_len):
            # Anchor too close to the end — pull the window back.
            start = max(0.0, (duration - eff_len)) if duration > 0 else start
            end = min(start + eff_len, duration) if duration > 0 else start + eff_len
        part = {
            "video_id": video_id,
            "video_title": vid_name,
            "title": _part_title(topic_name, label, 0),  # (Part N) numbered below
            "start": round(start, 3),
            "end": round(end, 3),
        }
        candidates.append((rel, prio, part))

    # Best sources first (relevance desc, kind priority asc), cap, then renumber parts.
    candidates.sort(key=lambda c: (-c[0], c[1]))
    parts: list[dict] = []
    for _rel, _prio, part in candidates[:max_clips]:
        part = dict(part)
        # Rewrite the title with the real part number and the source name for clarity.
        part["title"] = f"{topic_name} — {part['video_title']} (Part {len(parts) + 1})"
        parts.append(part)
    return parts


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
    video_title: str | None = None,
) -> list[dict]:
    """Derive 4-7 sequential parts from Content-Graph node timestamps.

    Each graph_node has {"label": str, "start": float|int}.
    Nodes are sorted by start time; topic boundaries become part cut-points.
    Count is clamped to [min_parts, max_parts].
    If there are fewer than min_parts nodes (or fewer than min_parts usable interior
    boundaries), the duration is split evenly into min_parts.

    ``video_title`` is used to build descriptive part titles via ``_part_title``
    (e.g. "Metal Roof Installation — Fastener Spacing — Part 2"); pass it whenever
    the source video title is available.

    Returns list of {"title": str, "start": float, "end": float}.

    NOTE (future work): topic-driven MULTI-source series — one series pulling the
    best parts across several source videos — would plug in here by accepting a list
    of (video_title, graph_nodes) pairs and merging them before the cut-point logic.
    """
    duration = float(duration)
    name = clean_title(video_title)
    nodes_sorted = sorted(graph_nodes, key=lambda n: float(n["start"]))

    def _even_split() -> list[dict]:
        step = duration / min_parts
        return [
            {
                "title": _part_title(name, "", i + 1),
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
        parts.append({"title": _part_title(name, label, i + 1), "start": start, "end": end})

    return parts
