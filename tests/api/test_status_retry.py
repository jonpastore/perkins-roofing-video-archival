"""Behavioral tests for POST /status/retry in api/app.py."""
import pytest
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.app import app
from app.models import IngestionRun, SessionLocal, init_db


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(app)


def _sales_client():
    set_verifier(lambda token: {"uid": "u2", "email": "sales@x.com", "role": "sales"})
    return TestClient(app)


AUTH = {"Authorization": "Bearer tok"}


def setup_module(module):
    init_db()


def _seed_error_run(video_id: str, stage: str, error: str = "something broke") -> int:
    with SessionLocal() as db:
        run = IngestionRun(
            video_id=video_id,
            stage=stage,
            status="error",
            last_error=error,
            attempts=1,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# POST /status/retry
# ---------------------------------------------------------------------------

def test_retry_resets_to_pending():
    """A failed IngestionRun should flip to pending and clear last_error."""
    run_id = _seed_error_run("vid_retry_1", "transcript")

    c = _admin_client()
    r = c.post("/status/retry", json={"video_id": "vid_retry_1", "stage": "transcript"}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["reset"] >= 1

    with SessionLocal() as db:
        row = db.query(IngestionRun).filter(IngestionRun.id == run_id).one()
        assert row.status == "pending"
        assert row.last_error is None


def test_retry_returns_404_when_no_error_row():
    """404 when there is no error row for the given video_id + stage."""
    c = _admin_client()
    r = c.post("/status/retry", json={"video_id": "no_such_vid", "stage": "embed"}, headers=AUTH)
    assert r.status_code == 404, r.text


def test_retry_does_not_reset_non_error_rows():
    """Rows with status != 'error' must not be touched."""
    with SessionLocal() as db:
        run = IngestionRun(
            video_id="vid_retry_2",
            stage="graph",
            status="done",
            last_error=None,
            attempts=1,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

    c = _admin_client()
    r = c.post("/status/retry", json={"video_id": "vid_retry_2", "stage": "graph"}, headers=AUTH)
    assert r.status_code == 404, r.text

    with SessionLocal() as db:
        row = db.query(IngestionRun).filter(IngestionRun.id == run_id).one()
        assert row.status == "done"


def test_retry_resets_multiple_error_rows():
    """All matching error rows for the same video_id+stage are reset."""
    ids = [_seed_error_run("vid_retry_3", "embed") for _ in range(2)]

    c = _admin_client()
    r = c.post("/status/retry", json={"video_id": "vid_retry_3", "stage": "embed"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["reset"] == 2

    with SessionLocal() as db:
        for rid in ids:
            row = db.query(IngestionRun).filter(IngestionRun.id == rid).one()
            assert row.status == "pending"
            assert row.last_error is None


def test_retry_requires_admin_role():
    """sales role does not have view_status — must get 403."""
    _seed_error_run("vid_retry_4", "transcript")
    c = _sales_client()
    r = c.post("/status/retry", json={"video_id": "vid_retry_4", "stage": "transcript"}, headers=AUTH)
    assert r.status_code == 403, r.text


def test_retry_401_without_token():
    c = _admin_client()
    r = c.post("/status/retry", json={"video_id": "vid_retry_1", "stage": "transcript"})
    assert r.status_code == 401, r.text
