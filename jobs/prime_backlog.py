"""One-time BACKLOG PRIMING on the local LLM (cerberus Ollama / Qwen3-30B-A3B).

Grinds the expensive one-time work — FAQ questions+answers and article-cluster drafts —
on the free local GPU instead of the client's cloud. The live/incremental path stays on
Vertex. Resumable + idempotent: skips FAQs already answered and topics already turned into
a cluster, so it can be re-run or run in chunks.

Run (from a box with the Cloud SQL proxy up):
  LLM_BACKEND=ollama OLLAMA_URL=http://cerberus-ai:11434 LLM_MODEL=qwen3:30b-a3b \
  EMBED_BACKEND=vertex EMBED_MODEL=gemini-embedding-001 \
  GOOGLE_APPLICATION_CREDENTIALS=$(scripts/fetch_vertex_sa.sh) GOOGLE_CLOUD_PROJECT=... \
  python -m jobs.prime_backlog --faqs 300 --answers 300 --articles 10

EMBED must stay on the cloud gemini model so retrieval matches the stored 3072-dim chunks.
"""
import argparse
import json
import logging

logger = logging.getLogger(__name__)


def _mine_faqs(limit: int, tenant_id: int | None = None) -> int:
    """Turn uncovered content_graph claims/objections into stored FaqEntry questions."""
    from sqlalchemy import select

    from api.routes.faq import _rephrase_via_llm
    from app.models import FaqEntry, GraphNode, SessionLocal

    with SessionLocal() as db:
        if tenant_id is not None:
            db.info["tenant_id"] = tenant_id
        covered = {r[0] for r in db.execute(select(FaqEntry.source_node_id)).all()}
        nodes = [
            n for n in db.query(GraphNode)
            .filter(GraphNode.kind.in_(("claims", "objections")), GraphNode.start.isnot(None))
            .order_by(GraphNode.id)
            .all()
            if n.id not in covered
        ][:limit]
        if not nodes:
            return 0
        made = 0
        # Rephrase in small batches — one giant LLM call would blow the context window.
        for i in range(0, len(nodes), 40):
            chunk = nodes[i:i + 40]
            questions = _rephrase_via_llm([(n.label or n.detail or "").strip() for n in chunk])
            for n, q in zip(chunk, questions):
                if not q:
                    continue
                db.add(FaqEntry(question=q, answer=None, source_kind=n.kind,
                                source_node_id=n.id, video_id=n.video_id, start=n.start or 0.0,
                                status="mined"))
                made += 1
            db.commit()
        return made


def _answer_faqs(limit: int, tenant_id: int | None = None) -> int:
    """Generate + store grounded answers for still-unanswered FaqEntry rows (local LLM)."""
    from app.answer import answer_faq
    from app.models import FaqEntry, SessionLocal

    with SessionLocal() as db:
        if tenant_id is not None:
            db.info["tenant_id"] = tenant_id
        pending = db.query(FaqEntry).filter(FaqEntry.status == "mined").limit(limit).all()
        done = 0
        for e in pending:
            try:
                res = answer_faq(e.question, db=db)
                ans = (res.get("answer") or "").strip()
                if not ans:
                    continue  # abstained — leave as 'mined' rather than store filler
                e.answer = ans
                e.status = "answered"
                db.commit()
                done += 1
            except Exception as ex:  # noqa: BLE001 — keep grinding the backlog
                logger.warning("answer failed for faq %s: %s", e.id, ex)
                db.rollback()
        return done


def _prime_articles(top_n: int, tenant_id: int | None = None) -> int:
    """Generate a cluster draft for the top-N aggregated topics not yet turned into a pillar."""
    from api.routes.topics import GenerateArticleRequest, _slugify, generate_cluster_article
    from app.models import AggregatedTopic, Article, SessionLocal

    with SessionLocal() as db:
        if tenant_id is not None:
            db.info["tenant_id"] = tenant_id
        topics = (db.query(AggregatedTopic)
                  .order_by(AggregatedTopic.num_videos.desc())
                  .limit(top_n * 2).all())
        made = 0
        for t in topics:
            if made >= top_n:
                break
            slug = _slugify(t.canonical_label)
            if db.get(Article, slug) is not None:
                continue  # already primed
            try:
                generate_cluster_article(GenerateArticleRequest(topic=t.canonical_label),
                                         claims={"email": "prime@local", "role": "admin"})
                made += 1
                logger.info("primed cluster for %r", t.canonical_label)
            except Exception as ex:  # noqa: BLE001
                logger.warning("article prime failed for %r: %s", t.canonical_label, ex)
        return made


def _run_for_tenant(db, tenant_id: int, faqs: int = 0, answers: int = 0, articles: int = 0) -> dict:
    """Per-tenant backlog priming body. Called by for_each_tenant via run().

    Note: internal helpers (_mine_faqs, _answer_faqs, _prime_articles) manage
    their own sessions for transaction isolation. tenant_id is threaded into each
    helper and stamped on session.info so the F4 after_begin event issues the
    correct SET LOCAL app.tenant_id on Postgres.
    """
    mined = _mine_faqs(faqs, tenant_id=tenant_id) if faqs else 0
    answered = _answer_faqs(answers, tenant_id=tenant_id) if answers else 0
    primed = _prime_articles(articles, tenant_id=tenant_id) if articles else 0
    return {"faqs_mined": mined, "faqs_answered": answered, "articles_primed": primed}


def run(faqs: int = 0, answers: int = 0, articles: int = 0) -> dict:
    """Iterate active tenants and prime the backlog for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"faqs_mined": 0, "faqs_answered": 0, "articles_primed": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, faqs=faqs, answers=answers, articles=articles)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--faqs", type=int, default=0)
    ap.add_argument("--answers", type=int, default=0)
    ap.add_argument("--articles", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(run(faqs=a.faqs, answers=a.answers, articles=a.articles), indent=2))
