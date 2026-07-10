"""FAQ routes — persistent FAQ system backed by faq_entries table.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - article_read    → sales or admin  (GET /faq, GET /faq/coverage, GET /faq/estimate)
  - manage_articles → admin only      (POST /faq/mine, POST /faq/{id}/answer,
                                       POST /faq/answer-batch)
"""
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import FaqEntry, GraphNode, Video

router = APIRouter(prefix="/faq", tags=["faq"])
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Batch caps — server-side guardrails against runaway LLM spend
# ---------------------------------------------------------------------------

MINE_DEFAULT = 200
MINE_MAX = 500          # hard cap per /faq/mine call

ANSWER_BATCH_DEFAULT = 25
ANSWER_BATCH_MAX = 100  # hard cap per /faq/answer-batch call

# ---------------------------------------------------------------------------
# Cost estimation — token budgets + pricing table
# ---------------------------------------------------------------------------
# Gemini 2.5 Flash pricing (approximate, as of mid-2025).
# Labeled "estimate" everywhere — actual cost depends on prompt length, caching,
# and Google's current rates. Source: https://cloud.google.com/vertex-ai/pricing
#
# Token assumptions per item (conservative/high-side estimates):
#   Mining:   ~400 tokens in (system + batch context per item) + ~30 tokens out
#   Answering: ~1 200 tokens in (retrieval chunks + question) + ~300 tokens out

_PRICING: dict[str, dict] = {
    "gemini-2.5-flash": {
        "input_per_1m":  0.15,   # USD per 1M input tokens
        "output_per_1m": 0.60,   # USD per 1M output tokens
    },
    # Fallback for unknown models — conservative placeholder
    "_default": {
        "input_per_1m":  0.50,
        "output_per_1m": 1.50,
    },
}

_MINE_TOKENS_IN  = 400   # per question (rephrasing prompt share)
_MINE_TOKENS_OUT = 30    # per question (one rephrased question)
_ANS_TOKENS_IN   = 1_200 # per question (RAG context + question)
_ANS_TOKENS_OUT  = 300   # per question (answer paragraph)


def _estimate_cost(count: int, model: str) -> dict:
    """Return {mine_cost_usd, answer_cost_usd} for processing `count` items."""
    pricing = _PRICING.get(model) or _PRICING["_default"]
    inp = pricing["input_per_1m"] / 1_000_000
    out = pricing["output_per_1m"] / 1_000_000

    mine_cost   = count * (_MINE_TOKENS_IN * inp + _MINE_TOKENS_OUT * out)
    answer_cost = count * (_ANS_TOKENS_IN  * inp + _ANS_TOKENS_OUT  * out)
    return {
        "mine_cost_usd":   round(mine_cost, 4),
        "answer_cost_usd": round(answer_cost, 4),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yt_link(video_id: str, t) -> str:
    from core.retrieval import link  # noqa: PLC0415
    return link(video_id, t)


def _normalize_question(q: str) -> str:
    """Collapse a question to a dedupe key (lowercased, alphanumerics only)."""
    return re.sub(r"[^a-z0-9]+", " ", (q or "").lower()).strip()


def _answer_entry(entry: FaqEntry, db: Session) -> bool:
    """Generate + store a concise, cited answer for one entry. Returns True if answered.

    Uses answer_faq (professional, 2-4 sentences, numbered ``link n`` citations),
    threading the route's RLS-stamped session so the retrieval chain never opens
    an unstamped one (strict=True). Leaves the entry unanswered when it abstains.
    """
    from app.answer import answer_faq

    res = answer_faq(entry.question, db=db)
    ans = (res.get("answer") or "").strip()
    if not ans:
        return False
    entry.answer = ans
    entry.status = "answered"
    return True


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
    limit: int = MINE_DEFAULT


@router.post("/mine")
def mine_faq(
    body: MineRequest = MineRequest(),
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Find content_graph claims+objections not yet in faq_entries, rephrase into questions,
    and INSERT FaqEntry rows (status='mined'). Idempotent — a node is mined at most once.
    Returns {mined: N, remaining_uncovered: M}.
    Max MINE_MAX items per call (server-enforced).
    """
    limit = max(1, min(body.limit, MINE_MAX))

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

    # Dedupe against existing questions (normalized) so answers aren't repetitive.
    seen_norm = {_normalize_question(row[0]) for row in db.query(FaqEntry.question).all()}

    now = datetime.utcnow()
    new_entries: list[FaqEntry] = []
    for i, node in enumerate(candidates):
        if use_llm and rephrased[i]:
            question = rephrased[i]
            if not question.endswith("?"):
                question += "?"
        else:
            question = _to_question_heuristic(node.label or "", node.detail or "")
        if not question:
            continue
        # Guard against duplicates (same node, or a near-identical question already mined)
        exists = db.query(FaqEntry).filter(FaqEntry.source_node_id == node.id).first()
        if exists:
            continue
        norm = _normalize_question(question)
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
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
        new_entries.append(entry)

    db.flush()
    inserted = len(new_entries)

    # Mining and answering are coupled — answer the freshly-mined questions now so
    # the FAQ is usable in one step (idempotent: abstained questions stay 'mined').
    answered = 0
    for entry in new_entries:
        try:
            if _answer_entry(entry, db):
                answered += 1
                db.flush()
        except Exception as exc:  # noqa: BLE001 — keep going, leave unanswered
            log.warning("mine: answer failed for entry %s: %s", entry.id, exc)

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

    return {"mined": inserted, "answered": answered, "remaining_uncovered": remaining}


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
    db: Session = Depends(get_db_session),
):
    """Paginated list of FAQ entries. Joins Video for title.
    Returns {total, items: [{id, question, answer, status, video_id, video_title, url, start}]}.
    """
    # Consolidated near-duplicates (status='duplicate') are hidden from the builder.
    query = db.query(FaqEntry).filter(FaqEntry.status != "duplicate")

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
def answer_one(
    entry_id: int,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Generate + store a concise, cited answer for a single FAQ entry."""
    entry = db.query(FaqEntry).filter(FaqEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="FAQ entry not found")

    _answer_entry(entry, db)
    db.flush()
    db.refresh(entry)

    video_ids = {entry.video_id}
    rows = db.query(Video.id, Video.title).filter(Video.id.in_(video_ids)).all()
    titles = {r.id: r.title for r in rows}

    return _entry_to_dict(entry, titles.get(entry.video_id))


# ---------------------------------------------------------------------------
# POST /faq/answer-batch
# ---------------------------------------------------------------------------

class AnswerBatchRequest(BaseModel):
    limit: int = ANSWER_BATCH_DEFAULT


@router.post("/answer-batch")
def answer_batch(
    body: AnswerBatchRequest = AnswerBatchRequest(),
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Generate + store answers for up to `limit` unanswered entries.
    Returns {answered: N, remaining: M}.
    Max ANSWER_BATCH_MAX items per call (server-enforced).
    """
    limit = max(1, min(body.limit, ANSWER_BATCH_MAX))

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
            if _answer_entry(entry, db):
                answered += 1
                db.flush()
        except Exception as exc:
            log.warning("answer-batch: failed for entry %d: %s", entry.id, exc)

    remaining = db.query(FaqEntry).filter(FaqEntry.status == "mined").count()

    return {"answered": answered, "remaining": remaining}


# ---------------------------------------------------------------------------
# POST /faq/publish-wordpress
# ---------------------------------------------------------------------------

_FAQ_PAGE_TITLES = ("FAQ", "Frequently Asked Questions")


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _answer_plain(answer: str) -> str:
    """Answer prose without the trailing 'Sources:' citation line (for JSON-LD)."""
    return re.split(r"\n\nSources:", answer or "", maxsplit=1)[0].strip()


def _answer_html(answer: str) -> str:
    """Escape the answer, then render ``[link n](url)`` markdown citations as anchors."""
    esc = _esc(answer).replace("\n", "<br>")
    return _MD_LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{_esc(m.group(1))}</a>',
        esc,
    )


def _build_faq_html(entries: list[FaqEntry]) -> str:
    """Render answered FaqEntry rows as semantic HTML (h3 + p pairs)."""
    parts: list[str] = ["<div class=\"faq-content\">"]
    for e in entries:
        parts.append(f"<h3>{_esc(e.question)}</h3>")
        parts.append(f"<p>{_answer_html(e.answer or '')}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def _build_faqpage_jsonld(entries: list[FaqEntry]) -> dict:
    """Build a FAQPage JSON-LD schema dict from answered entries."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": e.question,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": _answer_plain(e.answer or ""),
                },
            }
            for e in entries
        ],
    }


@router.post("/publish-wordpress")
def publish_wordpress(
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Collect all ANSWERED FaqEntry rows, build a semantic HTML FAQ page with
    FAQPage JSON-LD, and create-or-update a WordPress PAGE titled 'FAQ'.

    Requires WP_URL / WP_USER / WP_APP_PWD env vars. Returns 503 with a clear
    message when credentials are absent.

    Returns: {page_id, page_url, published, action}  (action: 'created' | 'updated')
    """
    import os

    from adapters import wordpress as wp

    # Guard: WP creds must be present
    missing = [v for v in ("WP_URL", "WP_USER", "WP_APP_PWD") if not os.environ.get(v)]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"WordPress credentials not configured: {', '.join(missing)}",
        )

    entries = (
        db.query(FaqEntry)
        .filter(FaqEntry.status == "answered")
        .order_by(FaqEntry.id)
        .all()
    )

    if not entries:
        raise HTTPException(status_code=422, detail="No answered FAQ entries to publish.")

    html_body = _build_faq_html(entries)
    jsonld = [_build_faqpage_jsonld(entries)]
    meta_desc = f"Frequently asked questions about roofing — {len(entries)} answers from Perkins Roofing."

    # Find existing FAQ page (try both title variants)
    existing_id: int | None = None
    for candidate_title in _FAQ_PAGE_TITLES:
        try:
            existing_id = wp.find_page_by_title(candidate_title)
        except Exception as exc:
            log.warning("WP find_page_by_title failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"WordPress API error: {exc}") from exc
        if existing_id is not None:
            break

    try:
        if existing_id is not None:
            wp.update_page(
                existing_id,
                title="Frequently Asked Questions",
                html=html_body,
                meta_description=meta_desc,
                jsonld=jsonld,
                status="publish",
            )
            page_id = existing_id
            action = "updated"
        else:
            page_id = wp.create_page(
                title="Frequently Asked Questions",
                html=html_body,
                meta_description=meta_desc,
                jsonld=jsonld,
                status="publish",
            )
            action = "created"
    except Exception as exc:
        log.error("WP publish-wordpress failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"WordPress API error: {exc}") from exc

    wp_base = os.environ.get("WP_URL", "").rstrip("/")
    return {
        "page_id": page_id,
        "page_url": f"{wp_base}/?page_id={page_id}",
        "published": len(entries),
        "action": action,
    }


# ---------------------------------------------------------------------------
# GET /faq/estimate
# ---------------------------------------------------------------------------

@router.get("/estimate")
def estimate_cost(
    count: int = Query(..., ge=1, description="Number of questions to estimate"),
    claims=Depends(require_role("article_read")),
):
    """Return an estimated LLM compute cost (USD) for mining and answering `count` questions.

    Uses the configured LLM_MODEL and a conservative token-budget table.
    All figures are labeled 'estimate' — actual cost varies by prompt length,
    model version, caching, and provider pricing changes.

    Returns {count, mine_cost_usd, answer_cost_usd, model, note, caps}.
    """
    from app.config import settings

    model = settings.LLM_MODEL
    costs = _estimate_cost(count, model)
    return {
        "count": count,
        "mine_cost_usd": costs["mine_cost_usd"],
        "answer_cost_usd": costs["answer_cost_usd"],
        "model": model,
        "note": (
            "Estimate only. Token budgets: mining ~400 in / 30 out per question; "
            "answering ~1200 in / 300 out per question. "
            "Actual cost depends on prompt length, caching, and current provider rates."
        ),
        "caps": {
            "mine_max": MINE_MAX,
            "answer_batch_max": ANSWER_BATCH_MAX,
        },
    }


# ---------------------------------------------------------------------------
# GET /faq/coverage
# ---------------------------------------------------------------------------

@router.get("/coverage")
def coverage(
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    """Return coverage stats: mined, answered, uncovered_nodes."""
    # 'mined' total excludes consolidated near-duplicates so the count reflects the
    # curated set the operator actually works with.
    mined_count = db.query(FaqEntry).filter(FaqEntry.status != "duplicate").count()
    answered_count = db.query(FaqEntry).filter(FaqEntry.status == "answered").count()
    duplicate_count = db.query(FaqEntry).filter(FaqEntry.status == "duplicate").count()

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
        "duplicates": duplicate_count,
        "uncovered_nodes": uncovered_nodes,
    }
