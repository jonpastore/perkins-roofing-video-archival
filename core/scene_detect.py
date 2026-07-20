"""Scene-boundary detection from transcript word timings.

For talking-head content the natural "scenes" are speech runs separated by pauses.
This finds those boundaries from the Word timestamps already stored in the DB — no
video download or ffmpeg pass needed — so the Clip Studio editor can suggest cut
points. Pure logic; the caller supplies the words.

# ponytail: speech-gap boundaries, not visual scene-cut. Add an ffmpeg `scdet`/`select
# gt(scene)` pass for true visual cuts (camera/B-roll changes) when a render-time video
# is already local — a heavier, async follow-on.
"""
from __future__ import annotations


def _attr(item, key):
    return item[key] if isinstance(item, dict) else getattr(item, key)


def scene_boundaries(
    words,
    gap_threshold: float = 1.2,
    min_scene: float = 2.5,
) -> list[float]:
    """Return sorted scene-start timestamps (the first word's start is always one).

    A boundary is placed at a word whose start follows the previous word's start by
    more than *gap_threshold* seconds (a pause). Boundaries closer than *min_scene*
    seconds to the previous one are dropped so scenes aren't trivially short.

    Args:
        words: iterable of {word, start} (dicts or ORM Word rows), any order.
        gap_threshold: seconds of silence that starts a new scene.
        min_scene: minimum seconds between kept boundaries.
    """
    starts = sorted(float(_attr(w, "start")) for w in words)
    if not starts:
        return []
    boundaries = [starts[0]]
    for prev, cur in zip(starts, starts[1:]):
        if cur - prev > gap_threshold and cur - boundaries[-1] >= min_scene:
            boundaries.append(cur)
    return boundaries
