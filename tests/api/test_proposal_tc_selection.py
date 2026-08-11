"""Which T&C version a proposal actually prints.

PROD, 2026-08-11: proposals were going out with "Terms and conditions to be attached." instead of
the real terms. Nothing was broken in the obvious places — `include_terms` defaulted true in the
UI, defaulted true in the renderer, and the template had its section. The failure was upstream of
all of it: `_load_tc_context` took the NEWEST TcVersion row, and the newest row (`v0.1-DRAFT`,
effective 2026-08-01) had a NULL content_gcs. It loaded an empty string and everything downstream
faithfully rendered nothing, while the real terms sat on the row underneath.

A contract that ships without its T&C is a contract defect, so "latest" here means the latest
version that actually HAS terms in it.
"""
import os
import tempfile
from datetime import datetime

import pytest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from api.routes.proposals import _load_tc_context  # noqa: E402
from app.models import SessionLocal, TcVersion, init_db  # noqa: E402


def setup_module(module):
    init_db()


@pytest.fixture(autouse=True)
def _clean():
    with SessionLocal() as db:
        db.query(TcVersion).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(TcVersion).delete()
        db.commit()


@pytest.fixture()
def stub_loader(monkeypatch):
    """Stand in for GCS: the URI IS the text, so the test asserts on which ROW was chosen.

    The summary-bullet call is stubbed too — it hits Vertex, and this test is about row
    selection, not about what an LLM makes of the terms.
    """
    import api.routes.contract_faq as cf
    import api.routes.proposals as pr
    monkeypatch.setattr(cf, "_load_tc_text_for_version",
                        lambda v: f"TERMS FROM {v.content_gcs}" if v and v.content_gcs else "")
    monkeypatch.setattr(pr, "_tc_summary_bullets", lambda _text: None)
    monkeypatch.setattr(pr, "get_tc_ai_prompts_block",
                        lambda: {"review_prompts": [], "ai_disclaimer": "", "cover_letter": ""},
                        raising=False)
    return None


def test_an_empty_newer_version_does_not_shadow_the_real_terms(stub_loader):
    """The exact prod shape: a newer draft row with no content, over real terms."""
    with SessionLocal() as db:
        db.add(TcVersion(version_tag="perkins-josh-2026-07-11",
                         content_gcs="gs://bucket/real_terms.pdf",
                         effective_at=datetime(2026, 7, 12)))
        db.add(TcVersion(version_tag="v0.1-DRAFT", content_gcs=None,
                         effective_at=datetime(2026, 8, 1)))
        db.commit()

    with SessionLocal() as db:
        ctx = _load_tc_context(db)

    assert ctx["tc_text"] == "TERMS FROM gs://bucket/real_terms.pdf"


def test_the_newest_version_with_content_still_wins(stub_loader):
    """The fix must not turn into "always use the oldest" — a real newer version supersedes."""
    with SessionLocal() as db:
        db.add(TcVersion(version_tag="old", content_gcs="gs://bucket/old.txt",
                         effective_at=datetime(2026, 1, 1)))
        db.add(TcVersion(version_tag="new", content_gcs="gs://bucket/new.txt",
                         effective_at=datetime(2026, 8, 1)))
        db.commit()

    with SessionLocal() as db:
        ctx = _load_tc_context(db)

    assert ctx["tc_text"] == "TERMS FROM gs://bucket/new.txt"


def test_a_whitespace_only_uri_counts_as_no_content(stub_loader):
    with SessionLocal() as db:
        db.add(TcVersion(version_tag="real", content_gcs="gs://bucket/real.txt",
                         effective_at=datetime(2026, 1, 1)))
        db.add(TcVersion(version_tag="blank", content_gcs="   ",
                         effective_at=datetime(2026, 8, 1)))
        db.commit()

    with SessionLocal() as db:
        ctx = _load_tc_context(db)

    assert ctx["tc_text"] == "TERMS FROM gs://bucket/real.txt"


def test_no_versions_at_all_yields_no_terms_rather_than_raising(stub_loader):
    with SessionLocal() as db:
        ctx = _load_tc_context(db)
    assert ctx["tc_text"] is None
