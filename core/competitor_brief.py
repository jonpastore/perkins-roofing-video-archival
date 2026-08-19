"""Competitor / SERP gaps vs our catalogue. Pure.

A short, Florida-local watchlist — not a crawl of every roofer. Callers fetch
SERPs (Serper) and pass them in. We only decide what *they* rank for that we
do not already cover.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from core.topic_graph import article_covered, slugify


@dataclass(frozen=True)
class WatchQuery:
    genre_id: str
    query: str
    why: str


WATCHLIST: tuple[WatchQuery, ...] = (
    WatchQuery("code", "HOA metal roof Florida 2026",
               "Law/HOA already gets comments on Tim's channel."),
    WatchQuery("weather", "hurricane roof insurance claim Florida",
               "Empty/thin genre; storm season demand."),
    WatchQuery("underlayment", "secondary water barrier Florida HVHZ",
               "Named entity AIO cites; we have tape."),
    WatchQuery("metal", "standing seam metal roof salt air Florida",
               "Coastal install questions competitors rank for."),
    WatchQuery("windows", "impact windows roof leak Florida",
               "Adjacent to roof; we almost wrote a duplicate pillar."),
)

_OUR_HOSTS = ("perkinsroofing.com", "perkinsroofing.net", "myftpupload.com")


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _ours(url: str) -> bool:
    host = _host(url)
    return any(h in host for h in _OUR_HOSTS)


def gap_from_serp(
    *,
    query: str,
    genre_id: str,
    serp: dict,
    our_keywords: set[str],
) -> dict:
    organic = list(serp.get("organic") or [])
    paa = [
        (item.get("question") or "").strip()
        for item in (serp.get("peopleAlsoAsk") or [])
        if (item.get("question") or "").strip()
    ]
    we_rank = any(_ours(str(item.get("link") or "")) for item in organic[:10])
    competitor_hosts = []
    for item in organic[:8]:
        host = _host(str(item.get("link") or ""))
        if host and not _ours(host) and host not in competitor_hosts:
            competitor_hosts.append(host)
    cov = {
        "slugs": {slugify(k) for k in our_keywords},
        "pillars": set(),
        "titles": {k.strip().lower() for k in our_keywords},
        "keywords": {k.strip().lower() for k in our_keywords},
    }
    unanswered = [q for q in paa if not article_covered(q, cov)]
    action = "hold" if we_rank and not unanswered else "film" if not we_rank else "write"
    return {
        "genre_id": genre_id,
        "query": query,
        "we_rank": we_rank,
        "unanswered_paa": unanswered[:5],
        "competitor_hosts": competitor_hosts[:5],
        "action": action,
    }


def summarize_scan(rows: list[dict]) -> list[dict]:
    order = {"film": 0, "write": 1, "hold": 2}
    return sorted(rows, key=lambda r: (order.get(r.get("action") or "hold", 9), -len(r.get("unanswered_paa") or [])))
