"""The daily article cron: topic selection and the boundaries around it.

Nothing in this system created content before 2026-08-13 — the fourteen schedulers only MOVED
content that already existed, which is why the catalogue sat at 473 articles with nothing new.
"""
from __future__ import annotations

from types import SimpleNamespace

import jobs.daily_content_job as DC


class _Q:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _DB:
    """Answers query(AggregatedTopic) and query(Article.slug, Article.pillar_slug)."""
    def __init__(self, topics, articles): self._t, self._a = topics, articles

    def query(self, *cols):
        first = getattr(cols[0], "__name__", "")
        return _Q(self._t if first == "AggregatedTopic" else self._a)


def _topic(label, seconds, videos=3):
    return SimpleNamespace(canonical_label=label, total_seconds=seconds, num_videos=videos)


def test_picks_the_best_GROUNDED_topic_not_the_most_mentioned():
    """Ranked by total_seconds, not num_videos. This pipeline's characteristic failure is
    INVENTION (core/article_grounding exists because articles were once ~90% invented), and the
    gate rejects what it cannot ground — so depth of source beats breadth of mention."""
    db = _DB([_topic("Shallow but everywhere", 60.0, videos=40),
              _topic("Deeply covered", 900.0, videos=3)], [])
    assert DC.next_topic(db)["label"] == "Deeply covered"


def test_skips_topics_that_already_have_an_article():
    db = _DB([_topic("Tile underlayment", 900.0)], [("tile-underlayment", None)])
    assert DC.next_topic(db) is None


def test_skips_a_topic_that_exists_only_as_a_CLUSTER_parent():
    """_generated_slugs collects pillar_slug too — a topic with clusters under it is generated
    even if no article carries its own slug."""
    db = _DB([_topic("Metal roofing", 900.0)], [("some-cluster", "metal-roofing")])
    assert DC.next_topic(db) is None


def test_exhausted_catalogue_returns_None_rather_than_inventing_a_topic():
    assert DC.next_topic(_DB([], [])) is None
    assert DC.next_topic(_DB([_topic("   ", 900.0)], [])) is None


def test_a_tenant_with_nothing_left_is_skipped_not_failed(monkeypatch):
    monkeypatch.setattr(DC, "next_topic", lambda db: None)
    assert DC._run_for_tenant(_DB([], []), 1)["skipped"] == "no ungenerated topics"


def test_subtopic_failure_degrades_to_pillar_only_instead_of_losing_the_day(monkeypatch):
    """Subtopic derivation is LLM-backed. A failure there must cost clusters, not the article."""
    import api.routes.topics as T

    def _boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(T, "_derive_subtopics", _boom)
    assert DC._clusters_for("Tile underlayment", _DB([], [])) == []


def test_it_generates_GATED_and_as_a_DRAFT(monkeypatch):
    """The two settings that keep this safe: critique=True runs the compliance gate (never
    generate ungated), and status='draft' means the EXISTING promote cron does the releasing —
    one publish path, not two."""
    seen = {}
    monkeypatch.setattr(DC, "next_topic", lambda db: {"label": "Tile underlayment", "slug": "t",
                                                      "num_videos": 3, "total_seconds": 900.0})
    monkeypatch.setattr(DC, "_clusters_for", lambda *a, **k: ["hip and ridge"])

    import jobs.batch_article_job as B

    def _fake(campaigns, **kw):
        seen.update(campaigns=campaigns, **kw)
        return {"report": {}}

    monkeypatch.setattr(B, "run_batch", _fake)
    DC._run_for_tenant(_DB([], []), 1)

    assert seen["mode"] == "publish"
    assert seen["status"] == "draft", "must not bypass ScheduledContent and publish live"
    assert seen["critique"] is True, "generating without the compliance gate is never acceptable"
    assert seen["campaigns"] == [{"pillar": "Tile underlayment", "clusters": ["hip and ridge"]}]


def test_overlapping_runs_are_refused(monkeypatch):
    """Generation loops against the gate and can outlast an hour. Two runs would pick the SAME
    topic — nothing is written until an article persists — and generate it twice."""
    from contextlib import contextmanager

    @contextmanager
    def _denied(_f, _k):
        yield False

    monkeypatch.setattr("core.single_flight.single_flight", _denied)
    assert DC.run()["skipped"] == "already running"
