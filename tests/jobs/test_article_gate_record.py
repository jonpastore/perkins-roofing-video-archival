"""A refused article has to survive as a fixable draft, not just a log line.

Before migration 0051 the compliance verdict for a NON-compliant article went nowhere:
jobs.batch_article_job._publish_fields only runs when compliant, so the draft itself was
discarded and the reasons survived as one logger.error. Nobody could see what to fix, and the
generation loop could not pick the article back up and correct the specific criterion.
"""

import os
import tempfile

import pytest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from app.models import Article, Base, SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)

COMPLIANCE = [
    {"key": "answer_first", "label": "Answer-first lede", "ok": False,
     "severity": "major", "detail": "0/3 sections"},
    {"key": "word_count", "label": "Over 600 words", "ok": True, "severity": "major"},
]
FIELDS = {"slug": "roof-leak-repair", "title": "Roof Leak Repair",
          "meta": "m", "content_md": "# body", "faq_json": None, "jsonld_json": None}
CTX = {"role": "supporting", "pillar_slug": "roofing"}


@pytest.fixture(autouse=True)
def _wipe():
    with SessionLocal() as db:
        db.query(Article).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(Article).delete()
        db.commit()


def _record(compliance):
    from jobs.batch_article_job import _record_gate
    _record_gate(FIELDS, CTX, "roof leak repair", compliance)


def test_a_refused_article_is_saved_as_a_draft_with_its_reasons():
    _record(COMPLIANCE)
    with SessionLocal() as db:
        row = db.get(Article, "roof-leak-repair")
    assert row is not None, "the draft must exist — otherwise there is nothing to correct"
    assert row.status == "draft"
    assert [f["key"] for f in row.gate_failures] == ["answer_first"]
    assert row.gate_checked_at is not None


def test_the_body_is_kept_so_the_draft_can_actually_be_fixed():
    """Recording only the reasons would leave nothing to apply a correction to."""
    _record(COMPLIANCE)
    with SessionLocal() as db:
        row = db.get(Article, "roof-leak-repair")
    assert row.content_md == "# body"
    assert row.focus_keyword == "roof leak repair"


def test_passing_clears_a_stale_failure_from_an_earlier_run():
    """A fixed article must stop appearing on the work list."""
    _record(COMPLIANCE)
    _record([{"key": "answer_first", "label": "Answer-first lede", "ok": True,
              "severity": "major"}])
    with SessionLocal() as db:
        row = db.get(Article, "roof-leak-repair")
    assert row.gate_failures == []
    assert row.gate_checked_at is not None


def test_never_gated_is_not_the_same_as_gated_and_clean():
    """NULL vs [] — an unchecked article must not read as passing."""
    with SessionLocal() as db:
        db.add(Article(slug="untouched", tenant_id=1, title="t", status="draft"))
        db.commit()
        assert db.get(Article, "untouched").gate_failures is None
