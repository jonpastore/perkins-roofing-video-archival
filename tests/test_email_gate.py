import json

import pytest

from adapters import resend
from app.models import Base, EmailLog, SessionLocal, engine
from core.email_gate import decide


@pytest.fixture(autouse=True)
def _email_log_schema():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        db.query(EmailLog).delete()
        db.commit()


def test_email_gate_defaults_to_test_mode_and_blocks_clients(monkeypatch):
    monkeypatch.delenv("EMAIL_SEND_MODE", raising=False)
    monkeypatch.delenv("EMAIL_TEST_RECIPIENT_ALLOWLIST", raising=False)

    assert decide("client@example.com").allowed is False
    assert decide("jon@degenito.ai").allowed is True


def test_email_gate_does_not_treat_bare_domain_as_allowlist(monkeypatch):
    monkeypatch.setenv("EMAIL_SEND_MODE", "test")
    monkeypatch.setenv("EMAIL_TEST_RECIPIENT_ALLOWLIST", "degenito.ai")

    assert decide("someone@degenito.ai").allowed is False


def test_resend_blocks_non_allowlisted_recipient_before_api_key(monkeypatch):
    monkeypatch.delenv("EMAIL_SEND_MODE", raising=False)
    monkeypatch.delenv("EMAIL_TEST_RECIPIENT_ALLOWLIST", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    msg_id = resend.send(
        reply_to="sales@perkinsroofing.net",
        to="client@example.com",
        subject="Test",
        html="<p>body</p>",
        tenant_id=1,
        send_type="test_case",
    )

    assert resend.is_blocked_message_id(msg_id)
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        rows = db.query(EmailLog).all()
    assert len(rows) == 1
    assert rows[0].status == "blocked"
    assert rows[0].to_email == "client@example.com"
    assert rows[0].error == "not_test_allowlisted"


class _FakeResendResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"id": "email_real_123"}).encode()


def test_resend_allows_jons_test_address_and_logs_sent(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req, timeout))
        return _FakeResendResponse()

    monkeypatch.delenv("EMAIL_SEND_MODE", raising=False)
    monkeypatch.delenv("EMAIL_TEST_RECIPIENT_ALLOWLIST", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "test_key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    msg_id = resend.send(
        reply_to="sales@perkinsroofing.net",
        to="jon@degenito.ai",
        subject="Test",
        html="<p>body</p>",
        tenant_id=1,
        send_type="test_case",
    )

    assert msg_id == "email_real_123"
    assert len(calls) == 1
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        rows = db.query(EmailLog).all()
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert rows[0].provider_message_id == "email_real_123"
