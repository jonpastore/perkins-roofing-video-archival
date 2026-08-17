"""Archive list helpers — counts, filters, pagination, short TTL cache.

list_videos used to COUNT articles with content_md.contains(video_id) once per
row. That is one full-text scan per video and is why the Archive tab took
1–2 minutes. Counts go through this module in one pass instead.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Iterable, Mapping, Sequence


def _as_id_list(source_ids: Any) -> list[str] | None:
    if source_ids is None:
        return None
    if isinstance(source_ids, str):
        return [source_ids] if source_ids else None
    if isinstance(source_ids, (list, tuple)):
        out = [str(v) for v in source_ids if v]
        return out or None
    return None


def article_refers_to_video(source_ids: Any, content_md: str | None, video_id: str) -> bool:
    """Same membership rule as article_counts_for / the detail panel."""
    linked = _as_id_list(source_ids)
    if linked is not None:
        return video_id in linked
    return bool(content_md) and video_id in content_md


def article_counts_for(
    video_ids: Sequence[str],
    articles: Iterable[tuple[Any, str | None]],
) -> dict[str, int]:
    """Count articles that reference each video.

    Prefer Article.source_video_ids. If that field is empty, fall back to a
    substring match in content_md so older rows (and the hermetic fixtures)
    still count.
    """
    counts = {vid: 0 for vid in video_ids}
    if not counts:
        return counts
    id_set = set(counts)
    for source_ids, content_md in articles:
        linked = _as_id_list(source_ids)
        if linked is not None:
            for vid in set(linked):
                if vid in counts:
                    counts[vid] += 1
            continue
        if not content_md:
            continue
        for vid in id_set:
            if vid in content_md:
                counts[vid] += 1
    return counts


def list_cache_key(tenant_id: int | None, parts: Mapping[str, Any]) -> str:
    return f"{tenant_id}|{filter_key(parts)}"


def keep_generated(param: str, generated: bool) -> bool:
    """clips/articles/social tri-state: all | yes | no."""
    if param == "all":
        return True
    return generated if param == "yes" else not generated


def page_slice(items: Sequence[Any], limit: int | None, offset: int) -> tuple[list[Any], int]:
    """Return (page, total). limit=None means the rest of the list after offset."""
    total = len(items)
    start = max(offset, 0)
    if limit is None:
        return list(items[start:]), total
    size = max(limit, 0)
    return list(items[start:start + size]), total


class TtlCache:
    """Process-local TTL map. Fine on Cloud Run: 30s of stale catalog is OK."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            ts, val = hit
            if now - ts > self.ttl:
                del self._store[key]
                return None
            if isinstance(val, list):
                return list(val)
            return val

    def set(self, key: str, val: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), val)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


def filter_key(parts: Mapping[str, Any]) -> str:
    """Stable cache key from the list-videos query params."""
    return "|".join(f"{k}={parts[k]}" for k in sorted(parts))
