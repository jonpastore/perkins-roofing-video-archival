"""Pure publish-pipeline planning functions — no I/O, fully deterministic.

All functions operate over plain dicts or dataclasses so they are trivially testable
and 100% coverable without any database/network setup.

Article dict shape (relevant keys):
    slug        str
    role        str   -- 'pillar' | 'support'
    priority    int   -- lower value = higher priority
    cluster_id  int | None
    status      str   -- 'draft' | 'scheduled' | 'published' | 'blocked' | 'ready'
    scheduled_at datetime | None

Cluster dict shape:
    id       int
    status   str  -- 'pending' | 'active' | 'complete'
    position int  -- activation order (ascending)
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# select_seed
# ---------------------------------------------------------------------------

def select_seed(items: list[dict[str, Any]], pct: float = 0.55) -> list[dict[str, Any]]:
    """Return the top *pct* fraction of items ranked by ascending priority.

    Items with a lower priority value rank higher (priority=1 before priority=10).
    Items without a priority value sort last (treated as +inf).
    The count is computed as ``ceil(len(items) * pct)`` so that even a single-item
    list with pct > 0 returns that one item, and an empty list returns [].

    Args:
        items: List of article dicts; must each have a 'priority' key (int | None).
        pct:   Fraction of items to seed immediately.  0 < pct <= 1.0.

    Returns:
        Ordered list (highest-priority first) of items to publish immediately.
    """
    if not items:
        return []
    import math
    count = math.ceil(len(items) * pct)
    count = max(0, min(count, len(items)))
    sorted_items = sorted(items, key=lambda a: (a.get("priority") is None, a.get("priority") or 0))
    return sorted_items[:count]


# ---------------------------------------------------------------------------
# publish_order
# ---------------------------------------------------------------------------

def publish_order(cluster_articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return cluster articles sorted pillar-first, then supports by ascending priority.

    Within each role tier, items with no priority sort last.

    Args:
        cluster_articles: Article dicts belonging to a single cluster.

    Returns:
        Ordered list — pillar(s) first, then supports, each sub-group by priority asc.
    """
    def _sort_key(a: dict[str, Any]) -> tuple[int, bool, int]:
        role_order = 0 if a.get("role") == "pillar" else 1
        pri = a.get("priority")
        return (role_order, pri is None, pri or 0)

    return sorted(cluster_articles, key=_sort_key)


# ---------------------------------------------------------------------------
# next_cluster
# ---------------------------------------------------------------------------

def next_cluster(clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the lowest-position 'pending' cluster, or None if none exist.

    Args:
        clusters: All cluster dicts (any status).

    Returns:
        The pending cluster with the smallest position value, or None.
    """
    pending = [c for c in clusters if c.get("status") == "pending"]
    if not pending:
        return None
    return min(pending, key=lambda c: c.get("position") or 0)


# ---------------------------------------------------------------------------
# to_dispatch
# ---------------------------------------------------------------------------

def to_dispatch(
    in_flight: list[dict[str, Any]],
    target: int,
    ready: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return items from *ready* needed to fill the pipeline to *target* in-flight.

    The pipeline is "always full": if fewer than *target* articles are currently
    in flight, pull from the front of the *ready* queue (already ordered by
    publish_order or equivalent) until the target is met or ready is exhausted.

    Args:
        in_flight: Articles currently being published (any status that counts as active).
        target:    Desired number of concurrent in-flight articles.
        ready:     Queue of articles ready to dispatch, in desired dispatch order.

    Returns:
        Slice of *ready* to start (may be empty if already at or above target).
    """
    slots = max(0, target - len(in_flight))
    return ready[:slots]
