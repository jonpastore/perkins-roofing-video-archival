"""One-shot prime: N new pillars × K supporting articles, persisted as scheduled drafts.

Does not touch WordPress. Used to test consistency, then the daily cron (CONTENT_GEN_MODE)
takes over.

    python -m jobs.prime_content
    CONTENT_DUMP_PER_RUN=10 CONTENT_DUMP_CLUSTERS=2 python -m jobs.prime_content
"""
from __future__ import annotations

import json
import logging
import os

from jobs.daily_content_job import _clusters_for, next_topic

logger = logging.getLogger(__name__)


def run(n_pillars: int | None = None, n_clusters: int | None = None) -> dict:
    from app.models import SessionLocal  # noqa: PLC0415
    from core.content_cadence import cadence  # noqa: PLC0415
    from jobs.batch_article_job import run_batch  # noqa: PLC0415

    cfg = cadence()
    n_pillars = n_pillars if n_pillars is not None else int(cfg["dump_per_run"] or 10)
    n_clusters = n_clusters if n_clusters is not None else int(cfg["dump_clusters"] or 2)
    db = SessionLocal()
    db.info["tenant_id"] = 1
    campaigns = []
    reserved: set[str] = set()
    try:
        for _ in range(n_pillars):
            topic = next_topic(db, extra_done=reserved)
            if topic is None:
                break
            reserved.add(topic["slug"])
            clusters = _clusters_for(topic["label"], db)[:n_clusters]
            campaigns.append({"pillar": topic["label"], "clusters": clusters})
    finally:
        db.close()

    if not campaigns:
        return {"skipped": "no ungenerated topics", "campaigns": []}

    result = run_batch(
        campaigns,
        workers=int(os.getenv("PRIME_WORKERS", "2")),
        critique=True,
        mode="persist",
        status="draft",
        per_day=1,
    )
    return {"campaigns": campaigns, "report": result.get("report"), "records": result.get("records")}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run(), indent=2, default=str)[:8000])
