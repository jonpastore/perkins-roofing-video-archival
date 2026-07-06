"""Unit + integration tests for POST /email/draft and the _html_compliant validator.

Validator tests are pure (no I/O). Endpoint tests mock app.llm.chat.
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.email import router as email_router, _html_compliant
from app.models import init_db


# Mount router idempotently
if not any(getattr(r, "path", None) == "/email/templates" for r in appmod.app.routes):
    appmod.app.include_router(email_router)


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def sales_client():
    set_verifier(lambda t: {"uid": "u1", "email": "sales@test.com", "role": "sales"})
    return TestClient(appmod.app)


@pytest.fixture()
def anon_client():
    set_verifier(lambda t: {})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# _html_compliant — pure validator unit tests
# ---------------------------------------------------------------------------

CLEAN_HTML = (
    "<p>Hi,</p>"
    "<ul><li><strong>Roof repair</strong><br>Great clip.<br>"
    '<a href="https://example.com/v/1">Watch the clip</a></li></ul>'
    "<p>Best,<br>Tim Perkins Roofing</p>"
)


class TestHtmlCompliant:
    def test_clean_html_passes(self):
        assert _html_compliant(CLEAN_HTML) is True

    def test_missing_href_fails(self):
        html = "<p>Hi,</p><ul><li>No link here</li></ul><p>Best,</p>"
        assert _html_compliant(html) is False

    def test_markdown_link_syntax_fails(self):
        html = '<p>Check [this](https://example.com) out</p><a href="x">link</a>'
        assert _html_compliant(html) is False

    def test_markdown_asterisk_bullet_fails(self):
        html = '<p>Items:</p>\n* first item\n<a href="x">link</a>'
        assert _html_compliant(html) is False

    def test_markdown_dash_bullet_fails(self):
        html = '<p>Items:</p>\n- first item\n<a href="x">link</a>'
        assert _html_compliant(html) is False

    def test_markdown_bullet_unicode_fails(self):
        html = '<p>Items:</p>\n• first item\n<a href="x">link</a>'
        assert _html_compliant(html) is False

    def test_bare_url_fails(self):
        html = '<p>Visit https://example.com for more</p><a href="x">link</a>'
        assert _html_compliant(html) is False

    def test_url_inside_href_is_not_bare(self):
        # URL only inside href — should not be flagged as bare
        html = '<p>Hi</p><a href="https://example.com">Watch</a><p>Best,</p>'
        assert _html_compliant(html) is True

    def test_multiple_links_pass(self):
        html = (
            '<p>Hi</p><ul>'
            '<li><a href="https://a.com">A</a></li>'
            '<li><a href="https://b.com">B</a></li>'
            '</ul><p>Best,<br>Tim</p>'
        )
        assert _html_compliant(html) is True


# ---------------------------------------------------------------------------
# POST /email/draft — endpoint integration tests
# ---------------------------------------------------------------------------

SOURCES_PAYLOAD = {
    "sources": [
        {"title": "Roof Repair 101", "snippet": "Fix leaks fast.", "url": "https://example.com/v/1"},
        {"title": "Storm Prep", "snippet": "Protect your home.", "url": "https://example.com/v/2"},
    ]
}


def test_draft_returns_html_on_first_attempt(sales_client):
    with patch("api.routes.email.chat", return_value=CLEAN_HTML) as mock_chat:
        r = sales_client.post("/email/draft", json=SOURCES_PAYLOAD,
                              headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["html"] == CLEAN_HTML
    assert mock_chat.call_count == 1


def test_draft_retries_on_noncompliant_then_succeeds(sales_client):
    bad = "<p>Check [this](https://example.com) out</p>"
    responses = [bad, bad, CLEAN_HTML]
    with patch("api.routes.email.chat", side_effect=responses) as mock_chat:
        r = sales_client.post("/email/draft", json=SOURCES_PAYLOAD,
                              headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["html"] == CLEAN_HTML
    assert mock_chat.call_count == 3


def test_draft_returns_502_after_3_failures(sales_client):
    bad = "<p>No links here, just * markdown - bullets.</p>"
    with patch("api.routes.email.chat", return_value=bad) as mock_chat:
        r = sales_client.post("/email/draft", json=SOURCES_PAYLOAD,
                              headers={"Authorization": "Bearer x"})
    assert r.status_code == 502
    assert mock_chat.call_count == 3


def test_draft_rejects_empty_sources(sales_client):
    r = sales_client.post("/email/draft", json={"sources": []},
                          headers={"Authorization": "Bearer x"})
    assert r.status_code == 422


def test_draft_requires_auth(anon_client):
    r = anon_client.post("/email/draft", json=SOURCES_PAYLOAD,
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


def test_draft_with_intro(sales_client):
    with patch("api.routes.email.chat", return_value=CLEAN_HTML):
        r = sales_client.post(
            "/email/draft",
            json={**SOURCES_PAYLOAD, "intro": "I wanted to share some helpful clips."},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    assert "html" in r.json()
