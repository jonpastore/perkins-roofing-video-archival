"""Pure mini-series planner — Content-Graph ranked candidate selection and part segmentation.
No I/O; all functions are deterministic."""


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
