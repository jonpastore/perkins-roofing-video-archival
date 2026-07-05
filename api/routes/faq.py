"""FAQ extraction routes.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - article_read    → sales or admin  (GET /faq/mined)
  - manage_articles → admin only      (POST /faq/build)
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import require_role
from app.models import GraphNode, SessionLocal

router = APIRouter(prefix="/faq", tags=["faq"])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yt_link(video_id: str, t: int) -> str:
    return f"https://youtu.be/{video_id}?t={t}"


def _to_question_heuristic(label: str, detail: str) -> str:
    """Fallback: capitalise and append '?' if not already a question."""
    text = (label or "").strip() or (detail or "").strip()
    if not text:
        return ""
    if text.endswith("?"):
        return text
    return text[0].upper() + text[1:] + "?"


def _rephrase_via_llm(statements: list[str]) -> list[str]:
    """Batch-rephrase raw claim/objection statements into natural homeowner questions.

    Sends one prompt to the LLM with all statements numbered; parses the numbered
    list back. Returns a list the same length as ``statements``. On any failure
    returns an empty list so the caller falls back to the heuristic.
    """
    from app.llm import chat

    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(statements))
    prompt = (
        "You are helping a roofing company build an FAQ for homeowners.\n"
        "Rephrase each of the following statements into a natural question a homeowner might ask.\n"
        "Return ONLY a numbered list in the exact same order, one question per line, "
        "ending each with a question mark. No extra text.\n\n"
        f"{numbered}"
    )
    try:
        raw = chat(prompt, want_json=False)
    except Exception as exc:
        log.warning("LLM rephrase failed: %s", exc)
        return []

    # Parse "1. Question text?" lines
    questions: list[str] = []
    for line in raw.splitlines():
        m = re.match(r"^\s*\d+\.\s*(.+)", line)
        if m:
            q = m.group(1).strip()
            if q and not q.endswith("?"):
                q += "?"
            questions.append(q)

    if len(questions) != len(statements):
        log.warning("LLM rephrase count mismatch (%d vs %d)", len(questions), len(statements))
        return []

    return questions


# ---------------------------------------------------------------------------
# GET /faq/mined
# ---------------------------------------------------------------------------

@router.get("/mined")
def list_mined(
    q: Optional[str] = Query(None, description="Substring filter on question text"),
    limit: int = Query(20, ge=1, le=200),
    claims=Depends(require_role("article_read")),
):
    """Return candidate FAQ items derived from content_graph objections + claims.

    Each item has: question, video_id, t (seconds), url (deep-link).
    Statements are rephrased into natural homeowner questions via the LLM
    (one batch call). Falls back to a heuristic if the LLM call fails.
    Filter with ?q=<substring>.
    """
    with SessionLocal() as db:
        rows = (
            db.query(GraphNode)
            .filter(
                GraphNode.kind.in_(("claims", "objections")),
                GraphNode.start.isnot(None),
            )
            .order_by(GraphNode.video_id, GraphNode.start)
            .limit(limit)
            .all()
        )

    if not rows:
        return []

    # Build raw statement list for the LLM batch call
    raw_statements = [
        (row.label or "").strip() or (row.detail or "").strip()
        for row in rows
    ]

    rephrased = _rephrase_via_llm(raw_statements)
    use_llm = len(rephrased) == len(rows)

    items = []
    for i, row in enumerate(rows):
        if use_llm:
            question = rephrased[i] if rephrased[i] else _to_question_heuristic(row.label or "", row.detail or "")
        else:
            question = _to_question_heuristic(row.label or "", row.detail or "")
        if not question:
            continue
        if q and q.lower() not in question.lower():
            continue
        t = int(row.start)
        items.append({
            "question": question,
            "video_id": row.video_id,
            "t": t,
            "url": _yt_link(row.video_id, t),
        })

    return items


# ---------------------------------------------------------------------------
# POST /faq/build
# ---------------------------------------------------------------------------

class BuildRequest(BaseModel):
    questions: list[str]
    video_ids: Optional[list[str]] = None


@router.post("/build")
def build_faq(body: BuildRequest, claims=Depends(require_role("manage_articles"))):
    """Generate grounded Q&A pairs for the given questions.

    Calls app.answer.ask() per question to produce a grounded answer with
    citations. Returns {faq: [{question, answer, citations}]}.
    """
    from app.answer import ask

    faq = []
    for question in body.questions:
        if not question.strip():
            continue
        result = ask(question)
        faq.append({
            "question": question,
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
        })

    return {"faq": faq}
