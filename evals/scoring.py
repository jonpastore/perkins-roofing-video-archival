"""Pure scoring for the offline eval suites. No DB, no network, no LLM, no clock.

Every number here is produced by replaying a FROZEN dataset (evals/datasets/) through the
SAME functions production uses — `core.retrieval.rank` and `core.grounding.unsourced_terms`.
Nothing is re-implemented for the eval; a metric that scores a copy of the logic measures the
copy.

WHAT THESE NUMBERS PROVE, AND WHAT THEY DO NOT — stated up front, because the failure mode of
an eval harness is a confident number nobody can act on.

  retrieval: the candidate pool (vector hits + their cosine similarities, the lexical matches,
    the Content-Graph video ids) was captured from the live corpus at refresh time and is
    committed. Replay therefore measures the FUSION AND RANKING (`core.retrieval.rank`) exactly,
    and CANNOT see a change in the embedding model, the chunking, or the corpus itself — those
    move only when `evals/refresh.py` is re-run. `pool_recall` is reported alongside to make
    that ceiling visible: it is the fraction of queries whose gold video was in the frozen pool
    at all, i.e. the best recall@k any ranker could reach on this snapshot.

  grounding: `unsourced_terms` is pure string logic, so its replay is total — this suite sees
    every change to the guard. What it cannot see is whether a term the guard accepts is
    actually SUPPORTED: token presence is not claim support (memory `grounding-vs-vocabulary`),
    and "Tim recommends replacing shingles every 10 years" uses only Tim's words and is still
    invented. Groundedness here means "names nothing Tim never named", not "is true".

  Neither suite uses an LLM judge. Deliberate: a pinned judge needs an API key in CI, costs
  money per run, and is non-deterministic — and a local model asked to judge a diff produced
  6 findings of which 3 were provably false and 0 were real (docs/2026-08-01-local-model-review-
  postmortem.md). A deterministic metric that measures less is worth more than a stochastic one
  that measures nothing reproducibly.

The gold labels are SYNTHETIC and corpus-derived: each retrieval query is a `content_graph`
claim — an LLM-extracted paraphrase of something Tim said in one specific video — and the gold
answer is that video. This is known-item retrieval. It is honest because the claim is a
paraphrase rather than a verbatim span (so the lexical path cannot trivially win), and because
the source node is excluded from the graph signal at refresh time (otherwise the query would
match its own node and hand the gold video a free boost).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

DATASETS = Path(__file__).parent / "datasets"

# Higher is better for every metric listed here; these are the ones `--check` gates on.
# Metrics absent from this set are reported but never gated (they are diagnostics, and some,
# like unsourced-terms-per-article, are lower-is-better).
GATED = ("recall@1", "recall@4", "recall@8", "precision@8", "mrr", "groundedness")


def load(name: str) -> list[dict]:
    """Read a frozen dataset. Gzipped because the grounding suite carries real article bodies
    and real transcripts, and truncating either one manufactures unsourced terms that do not
    exist in production."""
    with gzip.open(DATASETS / f"{name}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


class _Chunk:
    """Stand-in for app.models.Chunk. `rank()` reads `.id` and `.video_id` and nothing else,
    so the frozen pool does not have to carry chunk text it will never use."""

    __slots__ = ("id", "video_id")

    def __init__(self, chunk_id: int, video_id: str) -> None:
        self.id, self.video_id = chunk_id, video_id


# ── retrieval ────────────────────────────────────────────────────────────────────────────────

def replay(case: dict, k: int) -> list[str]:
    """Re-run production ranking over a frozen candidate pool. Returns the ranked video ids.

    `sim is None` marks a candidate that only the lexical query found — it never entered the
    vector list, which is exactly how `hybrid_search` hands it to `rank()` (seeded at 0.5).
    """
    from core.retrieval import rank

    vec = [(_Chunk(c["chunk_id"], c["video_id"]), c["sim"])
           for c in case["candidates"] if c["sim"] is not None]
    lex = [_Chunk(c["chunk_id"], c["video_id"]) for c in case["candidates"] if c["lexical"]]
    return [ch.video_id for ch, _ in rank(vec, lex, set(case["graph_video_ids"]), k)]


def recall_at_k(ranked: list[str], gold: str, k: int) -> float:
    """Known-item recall: there is exactly one right video, so this is 1.0 or 0.0 per query
    and the mean over the suite is the hit rate."""
    return 1.0 if gold in ranked[:k] else 0.0


def precision_at_k(ranked: list[str], gold: str, k: int) -> float:
    """Fraction of the top k that came from the gold video. Divided by k, not by len(ranked):
    returning three results instead of eight is not a precision win."""
    return sum(1 for v in ranked[:k] if v == gold) / k


def reciprocal_rank(ranked: list[str], gold: str) -> float:
    for i, v in enumerate(ranked, 1):
        if v == gold:
            return 1.0 / i
    return 0.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def score_retrieval(cases: list[dict], ks: tuple[int, ...] = (1, 4, 8)) -> dict:
    top_k = max(ks)
    rows = [(replay(c, top_k), c["gold_video"]) for c in cases]
    out: dict[str, float] = {"n": float(len(rows))}
    for k in ks:
        out[f"recall@{k}"] = _mean([recall_at_k(r, g, k) for r, g in rows])
        out[f"precision@{k}"] = _mean([precision_at_k(r, g, k) for r, g in rows])
    out["mrr"] = _mean([reciprocal_rank(r, g) for r, g in rows])
    # The ceiling: no ranker can retrieve what the frozen pool does not contain. A recall@8
    # equal to pool_recall means ranking is not the bottleneck — the retrieval upstream is.
    out["pool_recall"] = _mean(
        [1.0 if c["gold_video"] in {x["video_id"] for x in c["candidates"]} else 0.0
         for c in cases])
    # COVERAGE, not quality. How many cases actually reach the lexical and Content-Graph legs of
    # rank(). Reported because a suite where these are 0 gates the vector leg ALONE while
    # looking like it gates hybrid retrieval — on the `retrieval` (question-shaped) set they are
    # 0/60 and 1/60, so every fusion change scores identically there. The `retrieval_keyword`
    # set exists to cover them (19/60 and 15/60). Never gated: a change that legitimately
    # narrows the lexical filter would fail a floor for being correct.
    #
    # ⚠️ DO NOT "FIX" THE 0/60 BY TERM-MATCHING THE ILIKE. Measured 2026-08-04 over these exact
    # queries: matching graph nodes and chunks on the query's distinctive words (len>=5, OR, top
    # 5) takes graph coverage from 0/60 to 60/60 and makes retrieval MUCH WORSE —
    # recall@1 0.4000 -> 0.1667, mrr 0.5104 -> 0.3035. An OR over distinctive terms matches so
    # many videos that the +0.1 boost lands on wrong ones and displaces the right answer. Low
    # coverage here is not a bug to close; it is what keeps the boost precise. The graph leg
    # earns its place on KEYWORD-shaped queries (the article path), which is what
    # `retrieval_keyword` measures.
    out["graph_signal_cases"] = float(sum(1 for c in cases if c["graph_video_ids"]))
    out["lexical_cases"] = float(
        sum(1 for c in cases if any(x["lexical"] for x in c["candidates"])))
    return out


# ── grounding ────────────────────────────────────────────────────────────────────────────────

def groundedness(content: str, transcript: str, ignore: object = ()) -> tuple[float, int, int]:
    """(score, unsourced, candidates) for one article.

    score = the share of the proper nouns an article asserts that Tim actually said. 1.0 when
    the article names nothing outside his vocabulary. An article that names nothing at all
    scores 1.0 by definition — it asserts no product, brand or code, so it fabricates none.
    """
    from core.grounding import candidate_terms, unsourced_terms

    total = len(candidate_terms(content))
    if not total:
        return 1.0, 0, 0
    missing = len(unsourced_terms(content, transcript, ignore=ignore))
    return 1.0 - missing / total, missing, total


def score_grounding(cases: list[dict]) -> dict:
    scored = []
    for c in cases:
        score, missing, total = groundedness(
            c["content"], c["transcript"], ignore=c.get("focus_keyword") or ())
        scored.append((score, missing, total, c["slug"]))
    worst = min(scored, default=(1.0, 0, 0, ""))
    return {
        "n": float(len(scored)),
        "groundedness": _mean([s for s, _, _, _ in scored]),
        "unsourced_per_article": _mean([float(m) for _, m, _, _ in scored]),
        "worst_groundedness": worst[0],
        "worst_slug": worst[3],
    }


SUITES = {
    # Question-shaped queries (~58 chars) — what `/ask` sends. Gates the vector leg.
    "retrieval": (lambda: score_retrieval(load("retrieval"))),
    # Keyword-shaped queries (~28 chars) — what `source_transcripts()` sends when an article is
    # generated. Short enough for the ILIKE legs to match, so this is the suite that gates the
    # lexical + Content-Graph fusion in `rank()`. Its recall is deliberately pessimistic: see
    # evals/refresh.py on why the source node is excluded.
    "retrieval_keyword": (lambda: score_retrieval(load("retrieval_keyword"))),
    "grounding": (lambda: score_grounding(load("grounding"))),
}
