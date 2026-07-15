"""Behavioral validation for ORM before/after capture.

Against a real SQLAlchemy session, because the claim is about SQLAlchemy's behaviour: that the
old values are still readable at before_flush, that a rollback leaves no trail, and that
writing the audit row cannot recurse into auditing itself.
"""
import os

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

import core.audit_orm as audit_orm
from core.audit import current_actor

Base = declarative_base()


class Proposal(Base):           # name must be in AUDITED_MODELS
    __tablename__ = "proposals"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, default=1)
    status = Column(String)
    title = Column(String)
    secret_token = Column(String)


class Chunk(Base):              # deliberately NOT audited
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, default=1)
    text = Column(String)


@pytest.fixture(autouse=True)
def _audit_on(monkeypatch):
    """This file tests the audit machinery, so it opts back in (conftest disables it)."""
    monkeypatch.setenv("AUDIT_ENABLED", "1")
    from app.config import settings
    monkeypatch.setattr(settings, "AUDIT_ENABLED", True, raising=False)


@pytest.fixture()
def session_and_rows(monkeypatch):
    rows = []
    monkeypatch.setattr(audit_orm, "write", lambda **kw: rows.append(kw) or True, raising=False)
    # audit_orm imports write() lazily from api.audit_mw — patch it there too.
    import api.audit_mw as mw
    monkeypatch.setattr(mw, "write", lambda **kw: rows.append(kw) or True)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    audit_orm.register_change_tracking(Session)
    return Session, rows


def test_create_is_captured_with_its_values(session_and_rows):
    Session, rows = session_and_rows
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="draft", title="Roof"))
        s.commit()
    assert len(rows) == 1
    r = rows[0]
    assert r["action"] == "proposal.create"
    assert r["entity_type"] == "Proposal" and r["entity_id"] == "1"
    assert r["detail"]["changes"]["title"] == {"from": None, "to": "Roof"}


def test_update_records_before_and_after_so_it_can_be_reverted(session_and_rows):
    Session, rows = session_and_rows
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="draft", title="Roof"))
        s.commit()
        rows.clear()
        p = s.get(Proposal, 1)
        p.status = "signed"
        s.commit()
    assert len(rows) == 1
    changes = rows[0]["detail"]["changes"]
    assert rows[0]["action"] == "proposal.update"
    assert changes["status"] == {"from": "draft", "to": "signed"}
    assert "title" not in changes, "unchanged fields must not be recorded"


def test_delete_keeps_the_whole_row(session_and_rows):
    # A delete is the change most likely to need undoing, so the full before side is kept.
    Session, rows = session_and_rows
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="draft", title="Roof"))
        s.commit()
        rows.clear()
        s.delete(s.get(Proposal, 1))
        s.commit()
    assert rows[0]["action"] == "proposal.delete"
    assert rows[0]["detail"]["changes"]["title"]["from"] == "Roof"


def test_secret_values_are_never_recorded(session_and_rows):
    Session, rows = session_and_rows
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="d", secret_token="sk-live-abc"))
        s.commit()
    assert "sk-live-abc" not in str(rows)


def test_a_rolled_back_change_leaves_no_trail(session_and_rows):
    # Auditing at before_flush would log a change that never happened.
    Session, rows = session_and_rows
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="draft"))
        s.flush()
        s.rollback()
    assert rows == []


def test_unaudited_models_are_ignored(session_and_rows):
    # Embedding/bookkeeping writes would bury the rows a human actually wants.
    Session, rows = session_and_rows
    with Session() as s:
        s.add(Chunk(id=1, tenant_id=1, text="t"))
        s.commit()
    assert rows == []


def test_the_actor_is_attached_from_the_request_context(session_and_rows):
    Session, rows = session_and_rows
    token = current_actor.set({"email": "tim@perkinsroofing.net", "role": "admin",
                               "request_id": "req123", "source": "api"})
    try:
        with Session() as s:
            s.add(Proposal(id=1, tenant_id=1, status="draft"))
            s.commit()
    finally:
        current_actor.reset(token)
    assert rows[0]["actor_email"] == "tim@perkinsroofing.net"
    assert rows[0]["request_id"] == "req123"


def test_a_job_with_no_request_context_is_still_recorded(session_and_rows):
    Session, rows = session_and_rows
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="draft"))
        s.commit()
    assert rows[0]["actor_email"] is None
    assert rows[0]["source"] == "job", "an unattributed change is still a change"


def test_registration_is_idempotent(session_and_rows):
    Session, rows = session_and_rows
    audit_orm.register_change_tracking(Session)
    audit_orm.register_change_tracking(Session)
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="draft"))
        s.commit()
    assert len(rows) == 1, "double registration would double every audit row"


def test_capture_failure_never_blocks_the_write(session_and_rows, monkeypatch):
    Session, rows = session_and_rows
    monkeypatch.setattr(audit_orm, "_changed_fields",
                        lambda o: (_ for _ in ()).throw(RuntimeError("boom")))
    with Session() as s:
        s.add(Proposal(id=1, tenant_id=1, status="draft"))
        s.commit()
        p = s.get(Proposal, 1)
        p.status = "signed"
        s.commit()                      # must not raise
        assert s.get(Proposal, 1).status == "signed"


def test_a_created_row_records_its_generated_primary_key(session_and_rows):
    """An autoincrement id does not exist at before_flush — it is assigned by the flush.

    Reading entity_id only at capture time recorded None for every create, which makes
    "which proposal was created?" unanswerable.
    """
    Session, rows = session_and_rows
    with Session() as s:
        p = Proposal(tenant_id=1, status="draft", title="Generated PK")   # no explicit id
        s.add(p)
        s.commit()
        real_id = p.id
    assert real_id is not None
    assert rows[0]["entity_id"] == str(real_id)
