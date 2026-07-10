"""Cloud Run Job: answer all FAQ entries that are still in 'mined' status.

Calls the same answer_faq pipeline used by POST /faq/answer-batch, but without
the HTTP API layer — designed to be run as a Cloud Run Job (or locally) to do a
full back-fill in one shot.

Usage:
    python -m jobs.answer_pending_faqs [--batch-size N] [--limit N]

    --batch-size  How many entries to process per inner loop iteration (default 50).
                  Kept low so a crash/restart only repeats the last batch.
    --limit       Hard cap on total entries answered this run (default: all pending).

Idempotent: entries with status != 'mined' are skipped. Safe to re-run; already-
answered entries are never touched.

Cloud Run invocation (once deployed):
    gcloud run jobs execute answer-pending-faqs --region us-central1
Or via the /faq/answer-batch endpoint (up to 100 per call):
    curl -X POST https://<api>/faq/answer-batch \\
         -H "Authorization: Bearer <token>" \\
         -H "Content-Type: application/json" \\
         -d '{"limit": 100}'
"""
import argparse
import logging
import sys

from app.models import FaqEntry, SessionLocal, init_db

log = logging.getLogger(__name__)


def run(batch_size: int = 50, limit: int | None = None, tenant_id: int = 1) -> dict:
    """Answer all pending (status='mined') FAQ entries.

    Args:
        batch_size: entries processed per loop iteration.
        limit: total cap; None means process everything.

    Returns:
        {"answered": int, "failed": int, "remaining": int}
    """
    init_db()

    # Deferred import — keeps startup fast and avoids importing LLM deps at module load.
    from app.answer import answer_faq

    answered = 0
    failed = 0
    processed = 0

    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id  # strict-safe: stamp before first query
        while True:
            fetch_n = batch_size
            if limit is not None:
                remaining_budget = limit - processed
                if remaining_budget <= 0:
                    break
                fetch_n = min(batch_size, remaining_budget)

            batch = (
                db.query(FaqEntry)
                .filter(FaqEntry.status == "mined")
                .order_by(FaqEntry.id)
                .limit(fetch_n)
                .all()
            )
            if not batch:
                break

            for entry in batch:
                processed += 1
                try:
                    res = answer_faq(entry.question, db=db)
                    ans = (res.get("answer") or "").strip()
                    if ans:
                        entry.answer = ans
                        entry.status = "answered"
                        db.commit()
                        answered += 1
                        log.info("answered faq entry %d", entry.id)
                    else:
                        log.warning("answer_faq returned empty for entry %d", entry.id)
                        failed += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning("answer failed for entry %d: %s", entry.id, exc)
                    db.rollback()
                    failed += 1

        remaining = db.query(FaqEntry).filter(FaqEntry.status == "mined").count()

    return {"answered": answered, "failed": failed, "remaining": remaining}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Answer all pending FAQ entries")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--tenant", type=int, default=1)
    args = parser.parse_args()
    result = run(batch_size=args.batch_size, limit=args.limit, tenant_id=args.tenant)
    print(result)
    sys.exit(0 if result["remaining"] == 0 else 1)
