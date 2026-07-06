"""Semantic FAQ consolidation (I/O orchestration).

Embeds every FaqEntry question (Vertex), greedily clusters near-duplicates, keeps ONE
canonical entry per cluster (prefer the best answered one), merges the source-video
citations from the whole cluster into the canonical answer, and marks the rest
status='duplicate' (so they drop out of the FAQ page + coverage counts).

Idempotent: already-'duplicate' rows are skipped. Re-run after new mining.

Run (Cloud SQL proxy up, Vertex creds):
  LLM_BACKEND=vertex EMBED_BACKEND=vertex python -m jobs.consolidate_faqs --threshold 0.9
"""
from __future__ import annotations

import argparse
import json
import logging

import core.faq_consolidate as fc

logger = logging.getLogger(__name__)


def _yt(video_id: str, start) -> str:
    return f"https://youtu.be/{video_id}?t={int(start or 0)}"


def _cosine_matrix(vecs):
    import numpy as np  # noqa: PLC0415
    arr = np.asarray(vecs, dtype="float32")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms
    return (arr @ arr.T).tolist()


def run(threshold: float = 0.9, dry_run: bool = False) -> dict:
    from app.llm import embed  # noqa: PLC0415
    from app.models import FaqEntry, SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        rows = (
            db.query(FaqEntry)
            .filter(FaqEntry.status != "duplicate")
            .order_by(FaqEntry.id)
            .all()
        )
        entries = [
            {"id": r.id, "question": r.question or "", "answer": r.answer or "",
             "status": r.status, "video_id": r.video_id, "start": r.start}
            for r in rows
        ]

    if len(entries) < 2:
        return {"total": len(entries), "clusters": 0, "duplicates": 0, "merged": 0}

    logger.info("embedding %d questions…", len(entries))
    vecs = embed([e["question"] for e in entries])
    sim = _cosine_matrix(vecs)
    clusters = fc.greedy_cluster(sim, threshold)

    dupes, merged, multi = [], 0, 0
    updates: dict[int, str] = {}  # canonical id -> new answer
    for members in clusters:
        if len(members) < 2:
            continue
        multi += 1
        group = [entries[m] for m in members]
        ci = fc.choose_canonical(group)
        canonical = group[ci]
        # Gather every source URL across the cluster (from answers + each entry's own clip).
        extra = []
        for e in group:
            extra.extend(fc.links_in(e["answer"]))
            if e["video_id"]:
                extra.append(_yt(e["video_id"], e["start"]))
        new_answer = fc.merge_citations(canonical["answer"], extra)
        if new_answer != canonical["answer"]:
            updates[canonical["id"]] = new_answer
            merged += 1
        for k, e in enumerate(group):
            if k != ci:
                dupes.append(e["id"])

    logger.info("clusters_with_dupes=%d duplicates=%d canonical_citations_merged=%d",
                multi, len(dupes), merged)
    if dry_run:
        return {"total": len(entries), "clusters": multi, "duplicates": len(dupes),
                "merged": merged, "dry_run": True}

    with SessionLocal() as db:
        for cid, ans in updates.items():
            e = db.get(FaqEntry, cid)
            if e:
                e.answer = ans
        for did in dupes:
            e = db.get(FaqEntry, did)
            if e:
                e.status = "duplicate"
        db.commit()

    return {"total": len(entries), "clusters": multi, "duplicates": len(dupes),
            "merged": merged, "remaining": len(entries) - len(dupes)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.9)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(threshold=a.threshold, dry_run=a.dry_run), indent=2))
