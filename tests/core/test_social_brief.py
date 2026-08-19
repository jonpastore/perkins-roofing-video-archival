"""Social release + film-next ranking from footage heat and genre gaps."""
from __future__ import annotations

from core.social_brief import rank_cut_for_social, rank_film_next, social_action


def test_already_posted_is_not_a_cut_candidate():
    assert social_action(duration=90, has_clips=True, has_social=True) is None


def test_short_unused_clip_is_post_ready():
    assert social_action(duration=75, has_clips=False, has_social=False) == "post_short"


def test_18_minute_talk_is_tighten_or_split():
    assert social_action(duration=18 * 60, has_clips=False, has_social=False) == "tighten_or_split"


def test_40_minute_talk_is_chop():
    assert social_action(duration=40 * 60, has_clips=True, has_social=False) == "chop"


def test_rank_cut_prefers_comments_over_raw_views():
    rows = rank_cut_for_social([
        {"id": "viral", "title": "Protect Your Home", "duration": 600,
         "views": 958_000, "likes": 18, "comments": 0, "has_clips": False, "has_social": False},
        {"id": "howto", "title": "How To Install Roof Tiles", "duration": 900,
         "views": 157_000, "likes": 1566, "comments": 337, "has_clips": False, "has_social": False},
    ], limit=5)
    assert rows[0]["id"] == "howto"
    assert rows[0]["action"] == "tighten_or_split"


def test_rank_cut_skips_posted_and_tiny_clips():
    rows = rank_cut_for_social([
        {"id": "posted", "title": "Reel", "duration": 60, "views": 9, "likes": 9, "comments": 9,
         "has_clips": True, "has_social": True},
        {"id": "tiny", "title": "ASMR", "duration": 12, "views": 30_000, "likes": 90, "comments": 4,
         "has_clips": False, "has_social": False},
    ])
    assert rows == []


def test_zero_heat_long_talk_is_skipped_unless_already_short():
    rows = rank_cut_for_social([
        {"id": "dead", "title": "Long dead talk", "duration": 400, "views": 0, "likes": 0,
         "comments": 0, "has_clips": False, "has_social": False},
        {"id": "short", "title": "Short unused", "duration": 70, "views": 0, "likes": 0,
         "comments": 0, "has_clips": False, "has_social": False},
    ])
    assert [r["id"] for r in rows] == ["short"]


def test_chop_why_and_blank_or_internal_comments():
    rows = rank_cut_for_social([{
        "id": "long", "title": "All day job site", "duration": 40 * 60,
        "views": 100, "likes": 10, "comments": 5, "has_clips": False, "has_social": False,
    }])
    assert rows and rows[0]["action"] == "chop"
    assert "chop" in rows[0]["why"].lower()
    film = rank_film_next(
        genres=[{
            "id": "weather", "label": "Weather", "publishable": True, "density": "empty",
            "n_unpublished": 3, "grounding_seconds": 0, "opportunity": 10,
        }],
        comments=[
            {"text": "   ", "video_id": "v"},
            {"text": "How do I start a roofing franchise?", "video_id": "v"},
        ],
    )
    assert film and film[0]["questions"] == []


def test_film_next_prefers_empty_under_served_genres():
    rows = rank_film_next(
        genres=[
            {"id": "tile", "label": "Tile", "publishable": True, "density": "over_served",
             "n_unpublished": 10, "grounding_seconds": 50_000, "opportunity": 5},
            {"id": "weather", "label": "Weather / insurance", "publishable": True, "density": "empty",
             "n_unpublished": 20, "grounding_seconds": 200, "opportunity": 28},
            {"id": "internal", "label": "Internal", "publishable": False, "density": "internal",
             "n_unpublished": 80, "grounding_seconds": 9_000, "opportunity": 0},
        ],
        comments=[
            {"text": "Does insurance cover a hurricane leak?", "video_id": "v1"},
            {"text": "nice video", "video_id": "v2"},
        ],
        limit=5,
    )
    assert rows[0]["id"] == "weather"
    assert any("insurance" in (q.lower()) for q in rows[0]["questions"])
    assert all(r["id"] != "internal" for r in rows)


def test_film_next_skips_balanced_genre_with_no_questions():
    rows = rank_film_next(
        genres=[{
            "id": "cost", "label": "Cost", "publishable": True, "density": "balanced",
            "n_unpublished": 1, "grounding_seconds": 120, "opportunity": 2,
        }],
        comments=[{"text": "nice video", "video_id": "v"}],
    )
    assert rows == []


def test_film_next_keeps_balanced_genre_when_audience_asks():
    rows = rank_film_next(
        genres=[{
            "id": "cost", "label": "Cost", "publishable": True, "density": "balanced",
            "n_unpublished": 1, "grounding_seconds": 120, "opportunity": 2,
        }],
        comments=[{"text": "How much does a roof warranty cost?", "video_id": "v"}],
    )
    assert rows and rows[0]["id"] == "cost"
    assert "asking" in rows[0]["why"].lower()
