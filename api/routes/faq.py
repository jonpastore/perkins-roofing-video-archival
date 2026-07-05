"""FAQ routes — persistent FAQ system backed by faq_entries table.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - article_read    → sales or admin  (GET /faq, GET /faq/coverage)
  - manage_articles → admin only      (POST /faq/mine, POST /faq/{id}/answer,
                                       POST /faq/answer-batch)
"""
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import require_role
from app.models import FaqEntry, GraphNode, SessionLocal, Video

router = APIRouter(prefix="/faq", tags=["faq"])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yt_link(video_id: str, t: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(t)}"


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
        from app.llm import chat
        raw = chat(prompt, want_json=False)
    except Exception as exc:
        log.warning("LLM rephrase failed: %s", exc)
        return []

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


def _to_question_heuristic(label: str, detail: str) -> str:
    text = (label or "").strip() or (detail or "").strip()
    if not text:
        return ""
    if text.endswith("?"):
        return text
    return text[0].upper() + text[1:] + "?"


def _entry_to_dict(entry: FaqEntry, video_title: Optional[str] = None) -> dict:
    return {
        "id": entry.id,
        "question": entry.question,
        "answer": entry.answer,
        "status": entry.status,
        "source_kind": entry.source_kind,
        "video_id": entry.video_id,
        "video_title": video_title or entry.video_id,
        "url": _yt_link(entry.video_id, entry.start),
        "start": entry.start,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


# ---------------------------------------------------------------------------
# POST /faq/mine
# ---------------------------------------------------------------------------

class MineRequest(BaseModel):
    limit: int = 200


@router.post("/mine")
def mine_faq(body: MineRequest = MineRequest(), claims=Depends(require_role("manage_articles"))):
    """Find content_graph claims+objections not yet in faq_entries, rephrase into questions,
    and INSERT FaqEntry rows (status='mined'). Idempotent — a node is mined at most once.
    Returns {mined: N, remaining_uncovered: M}.
    """
    limit = max(1, min(body.limit, 2000))

    with SessionLocal() as db:
        # Find node IDs already covered
        covered_ids = {row[0] for row in db.query(FaqEntry.source_node_id).all()}

        # Query uncovered claim/objection nodes with a timestamp
        candidates = (
            db.query(GraphNode)
            .filter(
                GraphNode.kind.in_(("claims", "objections")),
                GraphNode.start.isnot(None),
                ~GraphNode.id.in_(covered_ids) if covered_ids else True,
            )
            .order_by(GraphNode.video_id, GraphNode.start)
            .limit(limit)
            .all()
        )

        if not candidates:
            # Count remaining
            total_uncovered = (
                db.query(GraphNode)
                .filter(
                    GraphNode.kind.in_(("claims", "objections")),
                    GraphNode.start.isnot(None),
                    ~GraphNode.id.in_(covered_ids) if covered_ids else True,
                )
                .count()
            )
            return {"mined": 0, "remaining_uncovered": total_uncovered}

        # Rephrase via LLM
        raw_statements = [
            (row.label or "").strip() or (row.detail or "").strip()
            for row in candidates
        ]
        rephrased = _rephrase_via_llm(raw_statements)
        use_llm = len(rephrased) == len(candidates)

        now = datetime.utcnow()
        inserted = 0
        for i, node in enumerate(candidates):
            if use_llm and rephrased[i]:
                question = rephrased[i]
                if not question.endswith("?"):
                    question += "?"
            else:
                question = _to_question_heuristic(node.label or "", node.detail or "")
            if not question:
                continue
            # Guard against duplicates (race condition / re-run safety)
            exists = db.query(FaqEntry).filter(FaqEntry.source_node_id == node.id).first()
            if exists:
                continue
            entry = FaqEntry(
                question=question,
                answer=None,
                source_kind="claim" if node.kind == "claims" else "objection",
                source_node_id=node.id,
                video_id=node.video_id,
                start=node.start,
                status="mined",
                created_at=now,
            )
            db.add(entry)
            inserted += 1

        db.commit()

        # Count remaining after this batch
        covered_ids_after = {row[0] for row in db.query(FaqEntry.source_node_id).all()}
        remaining = (
            db.query(GraphNode)
            .filter(
                GraphNode.kind.in_(("claims", "objections")),
                GraphNode.start.isnot(None),
                ~GraphNode.id.in_(covered_ids_after) if covered_ids_after else True,
            )
            .count()
        )

    return {"mined": inserted, "remaining_uncovered": remaining}


# ---------------------------------------------------------------------------
# GET /faq
# ---------------------------------------------------------------------------

@router.get("")
def list_faq(
    answered: str = Query("all", description="all | yes | no"),
    q: Optional[str] = Query(None, description="Substring search on question text"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    claims=Depends(require_role("article_read")),
):
    """Paginated list of FAQ entries. Joins Video for title.
    Returns {total, items: [{id, question, answer, status, video_id, video_title, url, start}]}.
    """
    with SessionLocal() as db:
        query = db.query(FaqEntry)

        if answered == "yes":
            query = query.filter(FaqEntry.status == "answered")
        elif answered == "no":
            query = query.filter(FaqEntry.status == "mined")

        if q:
            query = query.filter(FaqEntry.question.ilike(f"%{q}%"))

        total = query.count()
        entries = (
            query.order_by(FaqEntry.id)
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Batch-load video titles
        video_ids = {e.video_id for e in entries}
        titles = {}
        if video_ids:
            rows = db.query(Video.id, Video.title).filter(Video.id.in_(video_ids)).all()
            titles = {r.id: r.title for r in rows}

    items = [_entry_to_dict(e, titles.get(e.video_id)) for e in entries]
    return {"total": total, "items": items}


# ---------------------------------------------------------------------------
# POST /faq/{id}/answer
# ---------------------------------------------------------------------------

@router.post("/{entry_id}/answer")
def answer_one(entry_id: int, claims=Depends(require_role("manage_articles"))):
    """Generate + store a grounded answer for a single FAQ entry."""
    from app.answer import ask

    with SessionLocal() as db:
        entry = db.query(FaqEntry).filter(FaqEntry.id == entry_id).first()
        if not entry:
            raise HTTPException(status_code=404, detail="FAQ entry not found")

        result = ask(entry.question)
        entry.answer = result.get("answer", "")
        entry.status = "answered"
        db.commit()
        db.refresh(entry)

        video_ids = {entry.video_id}
        rows = db.query(Video.id, Video.title).filter(Video.id.in_(video_ids)).all()
        titles = {r.id: r.title for r in rows}

    return _entry_to_dict(entry, titles.get(entry.video_id))


# ---------------------------------------------------------------------------
# POST /faq/answer-batch
# ---------------------------------------------------------------------------

class AnswerBatchRequest(BaseModel):
    limit: int = 25


@router.post("/answer-batch")
def answer_batch(body: AnswerBatchRequest = AnswerBatchRequest(), claims=Depends(require_role("manage_articles"))):
    """Generate + store answers for up to `limit` unanswered entries.
    Returns {answered: N, remaining: M}.
    """
    from app.answer import ask

    limit = max(1, min(body.limit, 200))

    with SessionLocal() as db:
        entries = (
            db.query(FaqEntry)
            .filter(FaqEntry.status == "mined")
            .order_by(FaqEntry.id)
            .limit(limit)
            .all()
        )

        answered = 0
        for entry in entries:
            try:
                result = ask(entry.question)
                entry.answer = result.get("answer", "")
                entry.status = "answered"
                answered += 1
            except Exception as exc:
                log.warning("answer-batch: failed for entry %d: %s", entry.id, exc)

        db.commit()

        remaining = db.query(FaqEntry).filter(FaqEntry.status == "mined").count()

    return {"answered": answered, "remaining": remaining}


# ---------------------------------------------------------------------------
# GET /faq/coverage
# ---------------------------------------------------------------------------

@router.get("/coverage")
def coverage(claims=Depends(require_role("article_read"))):
    """Return coverage stats: mined, answered, uncovered_nodes."""
    with SessionLocal() as db:
        mined_count = db.query(FaqEntry).count()
        answered_count = db.query(FaqEntry).filter(FaqEntry.status == "answered").count()

        covered_ids = {row[0] for row in db.query(FaqEntry.source_node_id).all()}
        uncovered_nodes = (
            db.query(GraphNode)
            .filter(
                GraphNode.kind.in_(("claims", "objections")),
                GraphNode.start.isnot(None),
                ~GraphNode.id.in_(covered_ids) if covered_ids else True,
            )
            .count()
        )

    return {
        "mined": mined_count,
        "answered": answered_count,
        "uncovered_nodes": uncovered_nodes,
    }
