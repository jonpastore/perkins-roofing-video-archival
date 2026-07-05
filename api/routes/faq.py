"""FAQ extraction routes.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - article_read    → sales or admin  (GET /faq/mined)
  - manage_articles → admin only      (POST /faq/build)
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import require_role
from app.models import GraphNode, SessionLocal

router = APIRouter(prefix="/faq", tags=["faq"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yt_link(video_id: str, t: int) -> str:
    return f"https://youtu.be/{video_id}?t={t}"


def _to_question(label: str, detail: str) -> str:
    """Convert a claim/objection label+detail into a natural question.

    Deterministic and cheap: no LLM involved. If the label already ends with
    '?' it's used as-is. Otherwise we try to make it a question.
    """
    text = (label or "").strip() or (detail or "").strip()
    if not text:
        return ""
    if text.endswith("?"):
        return text
    # Capitalise and append '?'
    return text[0].upper() + text[1:] + "?"


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
    Filter with ?q=<substring>. Deterministic — no LLM.
    """
    with SessionLocal() as db:
        rows = (
            db.query(GraphNode)
            .filter(
                GraphNode.kind.in_(("claims", "objections")),
                GraphNode.start.isnot(None),
            )
            .order_by(GraphNode.video_id, GraphNode.start)
            .all()
        )

    items = []
    for row in rows:
        question = _to_question(row.label or "", row.detail or "")
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
        if len(items) >= limit:
            break

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
