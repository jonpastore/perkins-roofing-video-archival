"""Behavioral tests for jobs/integration_health_job.py (jobs/ are coverage-omitted).

Probes are faked via monkeypatch — real I/O lives in adapters/integration_probes.py and is
validated separately. These tests exercise: status persistence + transitions, exactly-one
alert email on transition-to-broken, no repeat email while still broken, and the expired-
nonce sweep.
"""
from datetime import datetime, timedelta, timezone

import pytest

import jobs.integration_health_job as J
from app.models import Base, IntegrationStatus, OAuthStateNonce, engine
from core.integration_health import ProbeResult


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _set_probes(monkeypatch, **results):
    """results maps integration name -> ProbeResult|None. Missing integrations probe healthy."""
    def _make(name):
        return lambda: results.get(name, ProbeResult(ok=True))
    monkeypatch.setattr(J, "_PROBES", {name: _make(name) for name in J._PROBES})


def test_hard_auth_failure_persists_broken_and_alerts_once(monkeypatch):
    sent = []
    monkeypatch.setattr(J.resend, "send", lambda **kw: sent.append(kw) or "msg_1")
    _set_probes(monkeypatch, wordpress=ProbeResult(ok=False, hard_auth_failure=True, error="WP 401"))

    result = J.run()

    assert result["statuses"]["wordpress"] == "broken"
    assert len(sent) == len(J.settings.DEFAULT_ADMINS)
    assert all(k["subject"] == "Integration BROKEN: wordpress" for k in sent)

    from app.models import SessionLocal
    s = SessionLocal()
    row = s.query(IntegrationStatus).filter(
        IntegrationStatus.tenant_id.is_(None), IntegrationStatus.integration == "wordpress"
    ).one()
    s.close()
    assert row.status == "broken"
    assert row.last_error == "WP 401"


def test_repeat_broken_cycle_does_not_resend(monkeypatch):
    sent = []
    monkeypatch.setattr(J.resend, "send", lambda **kw: sent.append(kw) or "msg_1")
    _set_probes(monkeypatch, resend=ProbeResult(ok=False, hard_auth_failure=True, error="Resend 401"))

    J.run()
    assert len(sent) == len(J.settings.DEFAULT_ADMINS)
    sent.clear()

    J.run()  # still broken — same hard-auth failure
    assert sent == []


def test_healthy_probe_resets_after_prior_failure(monkeypatch):
    sent = []
    monkeypatch.setattr(J.resend, "send", lambda **kw: sent.append(kw) or "msg_1")
    _set_probes(monkeypatch, knowify=ProbeResult(ok=False, hard_auth_failure=True, error="dead"))
    J.run()
    sent.clear()

    _set_probes(monkeypatch, knowify=ProbeResult(ok=True))
    result = J.run()
    assert result["statuses"]["knowify"] == "healthy"
    assert sent == []


def test_unconfigured_probe_persists_unconfigured(monkeypatch):
    _set_probes(monkeypatch, youtube_reply=None)
    result = J.run()
    assert result["statuses"]["youtube_reply"] == "unconfigured"


def test_nonce_sweep_deletes_only_expired(monkeypatch):
    monkeypatch.setattr(J.resend, "send", lambda **kw: "msg_1")
    from app.models import SessionLocal
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    s = SessionLocal()
    s.add(OAuthStateNonce(nonce="expired", tenant_id=1, platform="wordpress",
                          expires_at=now - timedelta(minutes=5)))
    s.add(OAuthStateNonce(nonce="live", tenant_id=1, platform="wordpress",
                          expires_at=now + timedelta(minutes=5)))
    s.commit()
    s.close()

    result = J.run(now=now)
    assert result["nonces_swept"] == 1

    s = SessionLocal()
    remaining = [n.nonce for n in s.query(OAuthStateNonce).all()]
    s.close()
    assert remaining == ["live"]
