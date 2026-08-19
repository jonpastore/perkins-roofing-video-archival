"""Tim's engagement inbox. Enhance replies — do not bot them.

Projects YouTube comments, unanswered People-Also-Ask, and film-next
questions into one ranked list. Persistence is comment_drafts.
"""
from __future__ import annotations

from core.topic_graph import slugify

INBOX_VIDEO = "inbox"


def paa_draft_key(question: str) -> str:
    return slugify(question or "", 80) or "question"


def inbox_items(
    *,
    comments: list[dict],
    paa: list[str],
    film_questions: list[str],
    limit: int = 20,
) -> list[dict]:
    rows: list[dict] = []
    for c in comments:
        if not c.get("needs_reply"):
            continue
        text = (c.get("comment_text") or c.get("text") or "").strip()
        if not text:
            continue
        rows.append({
            "kind": "youtube_comment",
            "id": str(c.get("comment_id") or c.get("id") or ""),
            "text": text,
            "source": c.get("video_id") or "",
            "action": "reply",
            "priority": 0,
        })
    seen = {r["id"] for r in rows}
    for q in paa:
        text = (q or "").strip()
        if not text:
            continue
        key = paa_draft_key(text)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "kind": "paa",
            "id": key,
            "text": text,
            "source": "serp",
            "action": "answer",
            "priority": 1,
        })
    for q in film_questions:
        text = (q or "").strip()
        if not text:
            continue
        key = paa_draft_key(text)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "kind": "film",
            "id": key,
            "text": text,
            "source": "graph",
            "action": "film",
            "priority": 2,
        })
    rows.sort(key=lambda r: (r["priority"], r["text"]))
    return rows[:limit]
