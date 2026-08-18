"""The daily article cron: topic selection and the boundaries around it.

Nothing in this system created content before 2026-08-13 — the fourteen schedulers only MOVED
content that already existed, which is why the catalogue sat at 473 articles with nothing new.
"""
from __future__ import annotations

from types import SimpleNamespace

import jobs.daily_content_job as DC


class _Q:
    def __init__(self, rows): self._rows = rows
    def filter(self, *a, **k): return self
    def all(self): return self._rows


class _DB:
    """Answers query(GraphNode), query(Video), and query(Article.slug, Article.pillar_slug)."""
    def __init__(self, nodes, videos, articles):
        self._n, self._v, self._a = nodes, videos, articles

    def query(self, *cols):
        first = getattr(cols[0], "__name__", "")
        if first == "GraphNode":
            return _Q(self._n)
        if first == "Video":
            return _Q(self._v)
        return _Q(self._a)


def _node(label, video_id):
    return SimpleNamespace(kind="topics", label=label, video_id=video_id)


def _video(vid, duration):
    return SimpleNamespace(id=vid, duration=duration)


def _graph(label, seconds, n_videos=3):
    """One topic mentioned on n_videos, each lasting seconds/n_videos so the TOTAL is seconds."""
    per = seconds / n_videos
    nodes, videos = [], []
    for i in range(n_videos):
        vid = f"{label}-{i}"
        nodes.append(_node(label, vid))
        videos.append(_video(vid, per))
    return nodes, videos


def test_picks_the_best_GROUNDED_topic_not_the_most_mentioned():
    """Ranked by total_seconds, not num_videos. This pipeline's characteristic failure is
    INVENTION (core/article_grounding exists because articles were once ~90% invented), and the
    gate rejects what it cannot ground — so depth of source beats breadth of mention."""
    shallow_n, shallow_v = _graph("Shallow but everywhere", 60.0, n_videos=40)
    deep_n, deep_v = _graph("Deeply covered", 900.0, n_videos=3)
    db = _DB(shallow_n + deep_n, shallow_v + deep_v, [])
    assert DC.next_topic(db)["label"] == "Deeply covered"


def test_reads_content_graph_not_the_stale_aggregate(monkeypatch):
    """aggregated_topics is a snapshot nothing refreshes. If this job ranks from it,
    a morning ingest never changes what tomorrow's cron picks."""
    import inspect
    assert "AggregatedTopic" not in inspect.getsource(DC.next_topic)


def test_skips_topics_that_already_have_an_article():
    nodes, videos = _graph("Tile underlayment", 900.0)
    db = _DB(nodes, videos, [("tile-underlayment", None)])
    assert DC.next_topic(db) is None


def test_skips_a_topic_that_exists_only_as_a_CLUSTER_parent():
    """_generated_slugs collects pillar_slug too — a topic with clusters under it is generated
    even if no article carries its own slug."""
    nodes, videos = _graph("Metal roofing", 900.0)
    db = _DB(nodes, videos, [("some-cluster", "metal-roofing")])
    assert DC.next_topic(db) is None


def test_sliced_clips_are_not_new_source_material():
    """A clip cut from a long original must not invent a second article topic."""
    nodes = [_node("Same speech", "LONGVIDEO01"), _node("Same speech", "CLIPVIDEO01")]
    videos = [
        SimpleNamespace(id="LONGVIDEO01", duration=900.0, parent_video_id=None,
                        derived_urls=["https://youtu.be/CLIPVIDEO01"]),
        SimpleNamespace(id="CLIPVIDEO01", duration=180.0, parent_video_id="LONGVIDEO01",
                        derived_urls=[]),
    ]
    picked = DC.next_topic(_DB(nodes, videos, []))
    assert picked["label"] == "Same speech"
    assert picked["num_videos"] == 1
    assert picked["total_seconds"] == 900.0


def test_a_topic_that_only_exists_on_sliced_clips_is_skipped():
    nodes = [_node("Only the cut", "CLIPVIDEO01")]
    videos = [
        SimpleNamespace(id="CLIPVIDEO01", duration=180.0, parent_video_id="LONGVIDEO01",
                        derived_urls=[]),
    ]
    assert DC.next_topic(_DB(nodes, videos, [])) is None


def test_exhausted_catalogue_returns_None_rather_than_inventing_a_topic():
    assert DC.next_topic(_DB([], [], [])) is None
    assert DC.next_topic(_DB([_node("   ", "v1")], [_video("v1", 900.0)], [])) is None


def test_extra_done_skips_an_otherwise_winning_topic():
    nodes, videos = _graph("Already picked", 900.0)
    assert DC.next_topic(_DB(nodes, videos, []), extra_done={"already-picked"}) is None


def test_off_mode_does_not_generate(monkeypatch):
    monkeypatch.setattr("core.content_cadence.cadence", lambda: {"mode": "off"})
    assert DC._run_for_tenant(_DB([], [], []), 1)["skipped"] == "content gen off"


def test_a_tenant_with_nothing_left_is_skipped_not_failed(monkeypatch):
    monkeypatch.setattr("core.content_cadence.cadence", lambda: {
        "mode": "dump", "dump_clusters": 2, "freshness_budget": 10,
    })
    monkeypatch.setattr(DC, "next_topic", lambda db: None)
    assert DC._run_for_tenant(_DB([], [], []), 1)["skipped"] == "no ungenerated topics"


def test_subtopic_failure_degrades_to_pillar_only_instead_of_losing_the_day(monkeypatch):
    """Subtopic derivation is LLM-backed. A failure there must cost clusters, not the article."""
    import api.routes.topics as T

    def _boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(T, "_derive_subtopics", _boom)
    assert DC._clusters_for("Tile underlayment", _DB([], [], [])) == []


def test_it_generates_GATED_and_as_a_DRAFT(monkeypatch):
    """The two settings that keep this safe: critique=True runs the compliance gate (never
    generate ungated), and status='draft' means the EXISTING promote cron does the releasing —
    one publish path, not two."""
    seen = {}
    monkeypatch.setattr("core.content_cadence.cadence", lambda: {
        "mode": "dump", "dump_clusters": 2, "freshness_budget": 10,
    })
    monkeypatch.setattr(DC, "next_topic", lambda db: {"label": "Tile underlayment", "slug": "t",
                                                      "num_videos": 3, "total_seconds": 900.0})
    monkeypatch.setattr(DC, "_clusters_for", lambda *a, **k: ["hip and ridge"])

    import jobs.batch_article_job as B

    def _fake(campaigns, **kw):
        seen.update(campaigns=campaigns, **kw)
        return {"report": {}}

    monkeypatch.setattr(B, "run_batch", _fake)
    DC._run_for_tenant(_DB([], [], []), 1)

    assert seen["mode"] == "persist"
    assert seen["status"] == "draft", "persist writes drafts only; it must not schedule promote"
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
