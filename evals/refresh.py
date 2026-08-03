"""Rebuild evals/datasets/ from the LIVE corpus. NOT run in CI — needs the prod DB and Vertex.

    scripts/run_cloudsql_job.sh evals.refresh

Re-run this when the embedding model, the chunker, the corpus or the article set changes.
Everything the eval replays offline is captured here, so a stale snapshot is a stale ceiling:
`pool_recall` in the scorecard is the number to watch — it can only move when this runs.

Sampling is seeded and ordered, so a refresh against an unchanged corpus produces an unchanged
dataset and the diff is empty. That matters: a dataset that churns on every refresh makes the
baseline meaningless.
"""
from __future__ import annotations

import gzip
import json
import logging
import random
from pathlib import Path

DATASETS = Path(__file__).parent / "datasets"

SEED = 20260803
N_QUERIES = 60          # one per video, so no single talkative video dominates the score
N_ARTICLES = 20
POOL_K = 8              # mirrors hybrid_search's default k (vector pool is k*2, lex/graph k)
MAX_WORDS = 24000       # jobs.article_job.SOURCE_MAX_WORDS — the budget prod actually grounds on
MAX_VIDEOS = 14         # jobs.article_job.SOURCE_MAX_SLICES; one article cites up to 74 videos,
                        # and freezing every transcript of all of them is 300 KB for one case

logger = logging.getLogger(__name__)


def _retrieval(db, kind: str, lo: int, hi: int) -> list[dict]:
    """Known-item queries from `content_graph`: an LLM-extracted statement about ONE video, so
    that video is the gold answer and the wording is not a verbatim span of the transcript.

    TWO query shapes, because production has two and they do not exercise the same code:

      kind='claims'  — a full sentence (~58 chars), the shape a user asks `/ask`.
      kind='topics'  — a short label (~28 chars), the shape `source_transcripts(keyword)` sends
                       when an article is generated.

    Length is the whole reason both exist. `hybrid_search`'s lexical and Content-Graph legs are
    `ILIKE '%<the entire query>%'`, which a full sentence matches nowhere but its own row. On the
    claims set that is measured at 0/60 graph hits and 1/60 lexical hits — so "hybrid" retrieval
    is a plain vector search for question-shaped queries, and an eval built only on those cannot
    see a fusion regression at all (deleting the graph boost outright moved no metric).

    The source node is dropped from the graph signal in both. Without that the query — which IS
    that node's text — matches its own node and the gold video collects a +0.1 boost the ranker
    did not earn: the difference between measuring retrieval and measuring an identity lookup.
    On the topics set this makes recall PESSIMISTIC (another video covering the same topic is
    scored as a miss). That is fine for a regression gate — the baseline absorbs the absolute
    level, and what has to move when `rank()` changes still moves.
    """
    from app.models import Chunk, GraphNode
    from app.store import vector_search

    by_video: dict[str, list] = {}
    for n in db.query(GraphNode).filter(GraphNode.kind == kind).order_by(GraphNode.id).all():
        text = (n.detail or n.label or "").strip()
        if lo <= len(text) <= hi and n.video_id:
            by_video.setdefault(n.video_id, []).append((n.id, text))

    videos = sorted(by_video)
    random.Random(SEED).shuffle(videos)

    cases = []
    for video_id in videos[:N_QUERIES]:
        node_id, query = by_video[video_id][0]      # lowest node id — deterministic
        like = "%" + query.lower() + "%"
        # order_by(id) on the lexical/graph legs: prod leaves these unordered, which makes the
        # snapshot irreproducible for no benefit. The ordering only decides WHICH ties are
        # frozen, never how rank() scores them.
        lex = (db.query(Chunk).filter(Chunk.text.ilike(like))
               .order_by(Chunk.id).limit(POOL_K).all())
        gnodes = (db.query(GraphNode)
                  .filter((GraphNode.label.ilike(like)) | (GraphNode.detail.ilike(like)))
                  .order_by(GraphNode.id).limit(POOL_K).all())

        lex_ids = {c.id for c in lex}
        candidates = [{"chunk_id": c.id, "video_id": c.video_id, "sim": round(float(s), 6)}
                      for c, s in vector_search(query, k=POOL_K * 2, db=db)]
        seen = {c["chunk_id"] for c in candidates}
        for c in lex:                               # lexical-only hits enter rank() seeded at 0.5
            if c.id not in seen:
                candidates.append({"chunk_id": c.id, "video_id": c.video_id, "sim": None})
        for c in candidates:
            c["lexical"] = c["chunk_id"] in lex_ids

        cases.append({
            "query": query,
            "gold_video": video_id,
            "source_node_id": node_id,
            "candidates": candidates,
            "graph_video_ids": sorted({g.video_id for g in gnodes if g.id != node_id}),
        })
        logger.info("retrieval case %d/%d %s", len(cases), N_QUERIES, video_id)
    return cases


def _grounding(db) -> list[dict]:
    """Published articles paired with the transcripts of the videos they were written from.

    The transcript is the whole of each source video rather than prod's topic slices — slices
    are transient (`_source_transcript` is never persisted), and a full video is a SUPERSET of
    the slice taken from it. So this scores no worse than prod did; a term unsourced here was
    unsourced there too.
    """
    from app.models import Article, Chunk

    articles = (db.query(Article)
                .filter(Article.status == "published", Article.content_md.isnot(None))
                .order_by(Article.slug).all())
    # Seeded shuffle, not the first 20 by slug: alphabetical order picks a block of articles
    # whose slugs start with a digit or 'a', which is a naming artefact, not a sample.
    random.Random(SEED).shuffle(articles)

    cases = []
    for a in articles:
        video_ids = a.source_video_ids or []
        if not isinstance(video_ids, list) or not video_ids:
            continue
        rows = (db.query(Chunk).filter(Chunk.video_id.in_(video_ids[:MAX_VIDEOS]))
                .order_by(Chunk.video_id, Chunk.start).all())
        transcript = " ".join(r.text or "" for r in rows)
        if not transcript.strip():
            continue
        cases.append({
            "slug": a.slug,
            "focus_keyword": a.focus_keyword or "",
            "content": a.content_md,
            "transcript": " ".join(transcript.split()[:MAX_WORDS]),
        })
        logger.info("grounding case %d/%d %s", len(cases), N_ARTICLES, a.slug)
        if len(cases) >= N_ARTICLES:
            break
    return cases


def _write(name: str, cases: list[dict]) -> None:
    DATASETS.mkdir(exist_ok=True)
    path = DATASETS / f"{name}.json.gz"
    # mtime=0: gzip stamps the current time into the header by default, so an unchanged corpus
    # would still produce a changed file and every refresh would look like a data change.
    with gzip.GzipFile(path, "wb", mtime=0) as fh:
        fh.write(json.dumps(cases, indent=1, sort_keys=True).encode())
    print(f"{path}  {len(cases)} cases  {path.stat().st_size / 1024:.0f} KB")


def run() -> None:
    from jobs.article_job import _stamped_session

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with _stamped_session(1) as db:
        _write("retrieval", _retrieval(db, "claims", 40, 220))
        _write("retrieval_keyword", _retrieval(db, "topics", 12, 60))
        _write("grounding", _grounding(db))
    print("\nRefreshed. Re-run `python -m evals run --all` and update evals/baseline.json.")


if __name__ == "__main__":
    run()
