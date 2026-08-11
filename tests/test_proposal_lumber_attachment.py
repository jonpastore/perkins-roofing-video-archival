"""Behavioral test for the optional Lumber Schedule PDF attachment.

api/routes/proposals.py is I/O (coverage-omitted per ENGINEERING_RULES R1), so this
validates the new include_lumber_chart behavior directly: render_and_cache_proposal_pdf
must pass the bundled Lumber Schedule PDF bytes to Gotenberg's attachment_pdf_bytes
param when quote_snapshot["include_lumber_chart"] is True, and omit it otherwise.
"""
from __future__ import annotations

import uuid
from io import BytesIO

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import adapters.gotenberg as gotenberg_adapter
from api.routes.proposals import _lumber_schedule_pdf_bytes, render_and_cache_proposal_pdf
from app.models import Base, Proposal


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    s = factory()
    s.info["tenant_id"] = 1
    return s


def _proposal(session, quote_snapshot: dict) -> Proposal:
    row = Proposal(
        customer_id=1,
        property_id=1,
        title="Test Proposal",
        accept_token=uuid.uuid4().hex[:86],
        created_by="test",
        status="draft",
        quote_snapshot=quote_snapshot,
    )
    session.add(row)
    session.flush()
    return row


def _patch_gotenberg(monkeypatch):
    captured = {}

    def fake_html_to_pdf(html, attachment_pdf_bytes=None):
        captured["attachment_pdf_bytes"] = attachment_pdf_bytes
        return b"%PDF-fake"

    monkeypatch.setattr(gotenberg_adapter, "html_to_pdf", fake_html_to_pdf)
    return captured


def test_lumber_schedule_pdf_bytes_reads_bundled_asset():
    data = _lumber_schedule_pdf_bytes()
    assert data is not None
    assert data.startswith(b"%PDF")


def test_include_lumber_chart_true_attaches_pdf(monkeypatch):
    captured = _patch_gotenberg(monkeypatch)
    s = _session()
    row = _proposal(s, {"total": 10000, "include_lumber_chart": True})

    render_and_cache_proposal_pdf(s, row)

    assert captured["attachment_pdf_bytes"] is not None
    assert captured["attachment_pdf_bytes"].startswith(b"%PDF")


def test_include_lumber_chart_false_omits_pdf(monkeypatch):
    captured = _patch_gotenberg(monkeypatch)
    s = _session()
    row = _proposal(s, {"total": 10000, "include_lumber_chart": False})

    render_and_cache_proposal_pdf(s, row)

    assert captured["attachment_pdf_bytes"] is None


def test_include_lumber_chart_absent_defaults_to_omitted(monkeypatch):
    captured = _patch_gotenberg(monkeypatch)
    s = _session()
    row = _proposal(s, {"total": 10000})  # flag not set at all

    render_and_cache_proposal_pdf(s, row)

    assert captured["attachment_pdf_bytes"] is None


def test_the_bundled_asset_is_tims_lumber_schedule():
    """Not just "a PDF" — the right one.

    Verified 2026-08-11 against the source: Tim Kanak, subject "Lumber Chart", 2026-07-20
    17:43:06Z, attachment `Lumber Schedule.pdf`, md5 68156a2ebfca1dcd0f3b3dec22c4e3e5 —
    byte-identical to the copy in assets/. It is the ONLY lumber schedule in the mailbox, so
    there is no newer revision to prefer.

    This goes on every proposal by default now, so a wrong or truncated file is a wrong document
    in a customer's hands. `_lumber_schedule_pdf_bytes` returns None and only logs when the file
    is missing, which means the proposal would simply ship without it and nobody would notice.
    """
    import pypdf

    data = _lumber_schedule_pdf_bytes()
    text = "\n".join(
        (page.extract_text() or "") for page in pypdf.PdfReader(BytesIO(data)).pages
    )
    collapsed = " ".join(text.split())
    assert "LUMBER SCHEDULE" in collapsed
    # The pricing basis, which is what makes the sheet meaningful rather than decorative.
    assert "1-story" in collapsed and "6/12" in collapsed
    assert "2-Story" in collapsed
