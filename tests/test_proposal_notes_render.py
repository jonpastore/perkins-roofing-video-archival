"""#387 — a per-job note must reach the CUSTOMER'S document, not just the AI reviewer.

`quote_snapshot["notes"]` was read in exactly one place: `_assemble_review_text`, which flattens a
proposal for `core.proposal_review` (the pre-send fairness/security check). None of the four
document renderers touched it. So an estimator's note was read by the reviewer and never printed
on the thing the customer signs.

api/routes/proposals.py is I/O and coverage-omitted per ENGINEERING_RULES R1, so this drives
`render_and_cache_proposal_pdf` directly — the same approach as
tests/test_proposal_lumber_attachment.py — and asserts on the HTML actually handed to Gotenberg.
That is the seam the defect lived in: the renderer supported nothing, and the route passed nothing.
"""
from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import adapters.gotenberg as gotenberg_adapter
from api.routes.proposals import render_and_cache_proposal_pdf
from app.models import Base, Proposal


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.info["tenant_id"] = 1
    return s


def _proposal(session, quote_snapshot: dict) -> Proposal:
    row = Proposal(
        customer_id=1, property_id=1, title="Test Proposal",
        accept_token=uuid.uuid4().hex[:86], created_by="test", status="draft",
        quote_snapshot=quote_snapshot,
    )
    session.add(row)
    session.flush()
    return row


def _capture_html(monkeypatch) -> dict:
    """Capture the HTML handed to Gotenberg — the document the customer receives."""
    captured = {}

    def fake_html_to_pdf(html, attachment_pdf_bytes=None):
        captured["html"] = html
        return b"%PDF-fake"

    monkeypatch.setattr(gotenberg_adapter, "html_to_pdf", fake_html_to_pdf)
    return captured


def test_notes_reach_the_rendered_document(monkeypatch):
    cap = _capture_html(monkeypatch)
    s = _session()
    render_and_cache_proposal_pdf(s, _proposal(s, {"total": 10000, "notes": "Gate code 4417"}))
    assert "Gate code 4417" in cap["html"]
    assert "Notes for This Job" in cap["html"]


def test_customer_notes_spelling_also_reaches_the_document(monkeypatch):
    """_assemble_review_text has accepted both spellings since it was written. If the document
    honoured only one, a note would reach the reviewer and vanish from the contract — which is
    the exact failure this task closes, reintroduced through the other key."""
    cap = _capture_html(monkeypatch)
    s = _session()
    render_and_cache_proposal_pdf(
        s, _proposal(s, {"total": 10000, "customer_notes": "Dumpster on the north side"}))
    assert "Dumpster on the north side" in cap["html"]


def test_notes_wins_over_customer_notes(monkeypatch):
    """Same precedence as _assemble_review_text (`notes or customer_notes`), so the reviewer and
    the document can never be shown different text for the same proposal."""
    cap = _capture_html(monkeypatch)
    s = _session()
    render_and_cache_proposal_pdf(s, _proposal(s, {
        "total": 10000, "notes": "PRIMARY", "customer_notes": "SECONDARY"}))
    assert "PRIMARY" in cap["html"]
    assert "SECONDARY" not in cap["html"]


def test_a_proposal_without_notes_renders_no_notes_block(monkeypatch):
    """Every proposal written before #387 has no `notes` key, and an empty 'Notes for This Job'
    heading on a signed contract reads as something omitted."""
    cap = _capture_html(monkeypatch)
    s = _session()
    render_and_cache_proposal_pdf(s, _proposal(s, {"total": 10000}))
    assert "Notes for This Job" not in cap["html"]


def test_notes_are_escaped_in_the_rendered_document(monkeypatch):
    """Operator-supplied text reaching customer-facing HTML, asserted end-to-end through the
    route rather than only at the pure-render layer."""
    cap = _capture_html(monkeypatch)
    s = _session()
    render_and_cache_proposal_pdf(
        s, _proposal(s, {"total": 10000, "notes": "<script>alert(1)</script>"}))
    assert "<script>alert(1)</script>" not in cap["html"]
    assert "&lt;script&gt;" in cap["html"]
