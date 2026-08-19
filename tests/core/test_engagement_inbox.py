"""Tim inbox: YouTube comments + PAA + film questions. No bot."""
from __future__ import annotations

from core.engagement_inbox import inbox_items, paa_draft_key


def test_inbox_ranks_youtube_replies_first_then_paa_then_film():
    rows = inbox_items(
        comments=[
            {"comment_id": "c1", "comment_text": "Does insurance cover this?",
             "video_id": "v1", "needs_reply": True},
            {"comment_id": "skip", "comment_text": "nice", "needs_reply": False},
        ],
        paa=["What is a secondary water barrier?"],
        film_questions=["Film a hurricane leak walkthrough"],
        limit=10,
    )
    kinds = [r["kind"] for r in rows]
    assert kinds[0] == "youtube_comment"
    assert "paa" in kinds
    assert "film" in kinds
    assert rows[0]["action"] == "reply"
    assert all(r["kind"] != "youtube_comment" or r["text"] != "nice" for r in rows)


def test_inbox_skips_blank_and_duplicate_questions():
    rows = inbox_items(
        comments=[{"comment_id": "c1", "comment_text": "   ", "needs_reply": True}],
        paa=["", "What is a secondary water barrier?", "What is a secondary water barrier?"],
        film_questions=["", "What is a secondary water barrier?", "Film a hurricane leak"],
        limit=10,
    )
    texts = [r["text"] for r in rows]
    assert "What is a secondary water barrier?" in texts
    assert texts.count("What is a secondary water barrier?") == 1
    assert any("hurricane" in t.lower() for t in texts)


def test_paa_draft_key_is_stable():
    assert paa_draft_key("What is a secondary water barrier?") == paa_draft_key(
        "what is a secondary water barrier?"
    )
    assert paa_draft_key("What is a secondary water barrier?")[:3] != ""
