"""Competitor SERP gaps vs our coverage — no live Serper."""
from __future__ import annotations

from core.competitor_brief import WATCHLIST, _host, gap_from_serp, summarize_scan


def test_watchlist_is_small_and_florida_local():
    assert 3 <= len(WATCHLIST) <= 6
    assert all("florida" in q.query.lower() or "hvhz" in q.query.lower() for q in WATCHLIST)


def test_gap_flags_paa_we_do_not_cover_and_whether_we_rank():
    serp = {
        "organic": [
            {"title": "GAF Metal Roof Guide", "link": "https://www.gaf.com/metal"},
            {"title": "Perkins Roofing HOA Metal", "link": "https://perkinsroofing.com/hoa-metal"},
        ],
        "peopleAlsoAsk": [
            {"question": "Can an HOA ban a metal roof in Florida?"},
            {"question": "What is a secondary water barrier?"},
        ],
    }
    gap = gap_from_serp(
        query="HOA metal roof Florida",
        genre_id="code",
        serp=serp,
        our_keywords={"hoa metal roof", "standing seam"},
    )
    assert gap["we_rank"] is True
    assert any("secondary water" in q.lower() for q in gap["unanswered_paa"])
    assert any("gaf.com" in h for h in gap["competitor_hosts"])


def test_host_returns_empty_on_unparseable():
    assert _host(123) == ""  # type: ignore[arg-type]


def test_summarize_prefers_gaps_we_do_not_rank_on():
    rows = [
        {"genre_id": "weather", "query": "hurricane roof insurance Florida",
         "we_rank": False, "unanswered_paa": ["Does insurance cover a hurricane leak?"],
         "competitor_hosts": ["thisoldhouse.com"], "action": "film"},
        {"genre_id": "tile", "query": "tile foam Florida",
         "we_rank": True, "unanswered_paa": [],
         "competitor_hosts": [], "action": "hold"},
    ]
    out = summarize_scan(rows)
    assert out[0]["genre_id"] == "weather"
    assert out[0]["action"] == "film"
