"""Behavioral tests for jobs/publish_job.py.

Follows the same pattern as tests/jobs/test_promote_job.py:
- Fresh SQLite DB per test via autouse fixture
- Monkeypatching of external calls (safety gate, wordpress adapter)
- Assertions on DB state after run()

Coverage omitted (jobs/ layer); tests validate behavioral contracts:
  - pillar publishes before its supports
  - gate-blocked article is skipped (status=blocked), not published
  - per-row isolation: one failure doesn't roll back prior successes
  - next-cluster activation when active cluster completes
"""
from datetime import datetime, timedelta, timezone

import pytest

import jobs.publish_job as PJ
from app.models import Article, Base, Cluster, SessionLocal, engine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _past(minutes=5):
    return _now() - timedelta(minutes=minutes)


class _GatePass:
    passed = True
    reason = None


class _GateFail:
    passed = False
    reason = "crude language detected"


def _seed_cluster(s, position=0, status="active"):
    c = Cluster(pillar_topic="Test Pillar", status=status, position=position)
    s.add(c)
    s.flush()
    return c


def _seed_article(s, slug, role="support", priority=1, cluster_id=None,
                  status="ready", wp_post_id=None, scheduled_at=None):
    a = Article(
        slug=slug,
        title=slug,
        content_md=f"content for {slug}",
        role=role,
        priority=priority,
        cluster_id=cluster_id,
        status=status,
        wp_post_id=wp_post_id,
        scheduled_at=scheduled_at or _past(),
    )
    s.add(a)
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pillar_published_before_support(monkeypatch):
    """Pillar article must be published before its support articles."""
    publish_order = []

    def fake_gate(text, kind):
        return _GatePass()

    def fake_wp(post_id, status):
        publish_order.append(post_id)

    monkeypatch.setattr(PJ, "run_gate", fake_gate)
    monkeypatch.setattr(PJ.wordpress, "update_status", fake_wp)

    s = SessionLocal()
    c = _seed_cluster(s)
    _seed_article(s, "support-1", role="support", priority=2,
                  cluster_id=c.id, wp_post_id=201)
    _seed_article(s, "pillar-1", role="pillar", priority=1,
                  cluster_id=c.id, wp_post_id=101)
    _seed_article(s, "support-2", role="support", priority=3,
                  cluster_id=c.id, wp_post_id=301)
    s.commit()
    s.close()

    result = PJ.run(target=10)
    assert result["published"] == 3
    assert result["blocked"] == 0
    assert result["errored"] == 0
    # Pillar (wp_post_id=101) must appear first in WP calls
    assert publish_order[0] == 101


def test_gate_blocked_article_skipped(monkeypatch):
    """An article that fails the content-safety gate must be marked blocked, not published."""
    def fake_gate(text, kind):
        if "bad" in text:
            return _GateFail()
        return _GatePass()

    monkeypatch.setattr(PJ, "run_gate", fake_gate)
    monkeypatch.setattr(PJ.wordpress, "update_status", lambda *a: None)

    s = SessionLocal()
    c = _seed_cluster(s)
    _seed_article(s, "clean", role="support", priority=1, cluster_id=c.id)
    bad = Article(
        slug="bad-article",
        title="bad article",
        content_md="bad language here",
        role="support",
        priority=2,
        cluster_id=c.id,
        status="ready",
        scheduled_at=_past(),
    )
    s.add(bad)
    s.commit()
    s.close()

    result = PJ.run(target=10)
    assert result["published"] == 1
    assert result["blocked"] == 1
    assert result["errored"] == 0

    s = SessionLocal()
    statuses = {a.slug: a.status for a in s.query(Article).all()}
    s.close()
    assert statuses["clean"] == "published"
    assert statuses["bad-article"] == "blocked"


def test_per_row_isolation_failure_does_not_revert_prior(monkeypatch):
    """A WordPress failure on one article must not revert previously published articles."""
    monkeypatch.setattr(PJ, "run_gate", lambda text, kind: _GatePass())

    def fake_wp(post_id, status):
        if post_id == 999:
            raise RuntimeError("WP 500")

    monkeypatch.setattr(PJ.wordpress, "update_status", fake_wp)

    s = SessionLocal()
    c = _seed_cluster(s)
    _seed_article(s, "good", role="support", priority=1,
                  cluster_id=c.id, wp_post_id=111)
    _seed_article(s, "fail-wp", role="support", priority=2,
                  cluster_id=c.id, wp_post_id=999)
    s.commit()
    s.close()

    result = PJ.run(target=10)
    assert result["published"] == 1
    assert result["errored"] == 1

    s = SessionLocal()
    statuses = {a.slug: a.status for a in s.query(Article).all()}
    s.close()
    assert statuses["good"] == "published"
    assert statuses["fail-wp"] == "error"


def test_next_cluster_activated_when_active_completes(monkeypatch):
    """When all articles in the active cluster finish, the next pending cluster is activated."""
    monkeypatch.setattr(PJ, "run_gate", lambda text, kind: _GatePass())
    monkeypatch.setattr(PJ.wordpress, "update_status", lambda *a: None)

    s = SessionLocal()
    # Active cluster with one article
    c1 = _seed_cluster(s, position=0, status="active")
    _seed_article(s, "c1-pillar", role="pillar", priority=1, cluster_id=c1.id)

    # Pending cluster — should be activated after c1 completes
    c2 = _seed_cluster(s, position=1, status="pending")
    _seed_article(s, "c2-pillar", role="pillar", priority=1,
                  cluster_id=c2.id, status="ready", scheduled_at=_past(60))
    s.commit()
    # Capture PKs before closing — ORM objects are detached after close
    c1_id = c1.id
    c2_id = c2.id
    s.close()

    result = PJ.run(target=10)
    assert result["published"] >= 1

    s = SessionLocal()
    c1_row = s.get(Cluster, c1_id)
    c2_row = s.get(Cluster, c2_id)
    s.close()
    assert c1_row.status == "complete"
    assert c2_row.status == "active"


def test_no_articles_due_returns_zeros(monkeypatch):
    """When no articles are due, run() returns all zeros without error."""
    monkeypatch.setattr(PJ, "run_gate", lambda text, kind: _GatePass())
    monkeypatch.setattr(PJ.wordpress, "update_status", lambda *a: None)

    s = SessionLocal()
    # Article with future scheduled_at — should NOT be picked up
    future = _now() + timedelta(hours=2)
    _seed_article(s, "future", status="ready", scheduled_at=future)
    s.commit()
    s.close()

    result = PJ.run(target=5)
    assert result == {"published": 0, "blocked": 0, "errored": 0}


def test_target_in_flight_limits_dispatched(monkeypatch):
    """Only target - in_flight articles are dispatched per run."""
    monkeypatch.setattr(PJ, "run_gate", lambda text, kind: _GatePass())
    monkeypatch.setattr(PJ.wordpress, "update_status", lambda *a: None)

    s = SessionLocal()
    c = _seed_cluster(s)
    for i in range(6):
        _seed_article(s, f"art-{i}", priority=i + 1, cluster_id=c.id)
    s.commit()
    s.close()

    result = PJ.run(target=3)
    assert result["published"] == 3
