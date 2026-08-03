"""Tests for the offline eval harness (#342).

Two layers, and they fail for different reasons on purpose:

  * the metric functions are pure arithmetic — tested against hand-worked cases, because a
    recall that silently counts wrong turns the whole harness into a confident wrong number;
  * the committed datasets are loaded and scored end to end, and `--check` is run against a
    DELIBERATELY RAISED baseline to prove the gate actually exits non-zero. An eval that cannot
    be shown to fail is indistinguishable from one that always passes — which is exactly how
    #333 (`app/eval.py`) sat in the tree for a year proving nothing.
"""
from __future__ import annotations

import json

import pytest

from evals import scoring
from evals.__main__ import main

RANKED = ["a", "b", "a", "c", "d", "e", "f", "g"]


def test_recall_at_k_is_hit_or_miss():
    assert scoring.recall_at_k(RANKED, "a", 1) == 1.0
    assert scoring.recall_at_k(RANKED, "c", 1) == 0.0
    assert scoring.recall_at_k(RANKED, "c", 4) == 1.0
    assert scoring.recall_at_k(["a"], "z", 8) == 0.0


def test_precision_at_k_divides_by_k_not_by_length():
    # 2 of the first 4 are gold -> 0.5
    assert scoring.precision_at_k(RANKED, "a", 4) == 0.5
    # A short result list must NOT be rewarded: 1 gold in a 1-item list is 1/8 at k=8.
    assert scoring.precision_at_k(["a"], "a", 8) == pytest.approx(0.125)


def test_reciprocal_rank_uses_first_hit():
    assert scoring.reciprocal_rank(RANKED, "a") == 1.0
    assert scoring.reciprocal_rank(RANKED, "c") == pytest.approx(0.25)
    assert scoring.reciprocal_rank(RANKED, "zz") == 0.0


def test_replay_applies_the_lexical_and_graph_boosts():
    """The frozen pool feeds production's rank() unchanged: a lexical-only candidate enters at
    0.5 and a graph-matched video gets +0.1, which is enough to overtake a weak vector hit."""
    case = {
        "candidates": [
            {"chunk_id": 1, "video_id": "weak", "sim": 0.52, "lexical": False},
            {"chunk_id": 2, "video_id": "lexonly", "sim": None, "lexical": True},
        ],
        "graph_video_ids": ["lexonly"],
    }
    assert scoring.replay(case, 8) == ["lexonly", "weak"]  # 0.5 + 0.1 > 0.52


def test_groundedness_of_a_fully_sourced_article_is_one():
    score, missing, total = scoring.groundedness(
        "We install Polyglass underlayment. The Polyglass sheet is nailed.",
        "we always use polyglass underlayment on every tile roof")
    assert missing == 0
    assert total > 0
    assert score == 1.0


def test_groundedness_falls_when_a_term_is_absent_from_the_transcript():
    score, missing, _ = scoring.groundedness(
        "We install Polyblast Paper on every roof.", "we always use polyglass underlayment")
    assert missing == 1
    assert score < 1.0


def test_an_article_asserting_no_proper_nouns_scores_one():
    score, missing, total = scoring.groundedness("we nail it down and move on", "anything")
    assert (score, missing, total) == (1.0, 0, 0)


def test_committed_datasets_load_and_score():
    """The datasets are real, frozen corpus data — if a refresh writes a broken shape, or the
    files go missing, this fails here rather than in CI's eval step with a stack trace."""
    for name, run in scoring.SUITES.items():
        scores = run()
        assert scores["n"] > 0, name
        for key in scoring.GATED:
            if key in scores:
                assert 0.0 <= scores[key] <= 1.0, (name, key)


def test_pool_recall_bounds_recall_at_k():
    """No ranker can retrieve what the frozen pool does not contain. If recall@8 ever exceeds
    pool_recall the replay is scoring something other than the pool it was given."""
    scores = scoring.score_retrieval(scoring.load("retrieval"))
    assert scores["recall@8"] <= scores["pool_recall"]


def test_check_passes_against_the_committed_baseline():
    assert main(["run", "--all", "--check"]) == 0


def test_check_fails_when_a_metric_regresses(monkeypatch, tmp_path, capsys):
    """The gate has to be shown firing. Raising the floor above the achievable score is the
    same event as a real regression, from the checker's point of view."""
    impossible = tmp_path / "baseline.json"
    impossible.write_text(json.dumps({s: {k: 1.0 for k in scoring.GATED} for s in scoring.SUITES}))
    monkeypatch.setattr("evals.__main__.BASELINE", impossible)
    assert main(["run", "--all", "--check"]) == 1
    assert "EVAL GATE FAILED" in capsys.readouterr().out


def test_a_gated_metric_with_no_recorded_floor_is_a_failure(monkeypatch, tmp_path):
    """An ungated metric reads exactly like a passing one — so a missing floor must be loud."""
    empty = tmp_path / "baseline.json"
    empty.write_text(json.dumps({"retrieval": {}, "grounding": {}}))
    monkeypatch.setattr("evals.__main__.BASELINE", empty)
    assert main(["run", "--all", "--check"]) == 1


def test_written_baseline_is_truncated_so_it_passes_its_own_gate(monkeypatch, tmp_path):
    """round-to-nearest would write a floor ABOVE the score it came from (0.11666 -> 0.1167),
    and with the zero tolerance the gate then fails on the very tree that wrote the baseline.
    Write, then immediately check: the two must agree."""
    written = tmp_path / "baseline.json"
    monkeypatch.setattr("evals.__main__.BASELINE", written)
    assert main(["run", "--all", "--write-baseline"]) == 0
    assert main(["run", "--all", "--check"]) == 0
    recorded = json.loads(written.read_text())
    live = scoring.SUITES["retrieval_keyword"]()
    assert recorded["retrieval_keyword"]["recall@1"] <= live["recall@1"]


def test_the_keyword_suite_reaches_the_fusion_legs():
    """The reason `retrieval_keyword` exists. Question-shaped queries are too long for
    hybrid_search's `ILIKE '%<query>%'` legs to match anything, so on the `retrieval` suite the
    lexical and graph boosts are dead code and every fusion change scores identically. If this
    ever drops to zero the gate has quietly stopped covering `rank()`'s fusion."""
    scores = scoring.score_retrieval(scoring.load("retrieval_keyword"))
    assert scores["graph_signal_cases"] > 0
    assert scores["lexical_cases"] > 0


def test_a_metric_that_vanishes_from_a_suite_fails(monkeypatch, tmp_path, capsys):
    """A baseline floor with nothing to compare against must fail, not pass. Otherwise deleting
    a metric is the cheapest way to make its gate green."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"retrieval": {"recall@1": 0.1, "recall@99": 0.1}}))
    monkeypatch.setattr("evals.__main__.BASELINE", baseline)
    assert main(["run", "retrieval", "--check"]) == 1
    assert "no longer reports this metric" in capsys.readouterr().out


def test_unknown_suite_is_rejected():
    with pytest.raises(SystemExit):
        main(["run", "nosuchsuite"])
