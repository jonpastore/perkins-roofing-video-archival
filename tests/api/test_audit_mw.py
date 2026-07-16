"""Behavioral validation for audit coverage — the end-to-end claim, not the unit.

The unit tests in tests/core/test_audit.py prove naming and redaction. These prove the thing
that actually matters: a real request through the real app produces a real row, naming a real
actor. The first version of this middleware read claims from request.state, which nothing set
— so it would have recorded every request as actor=None with no tenant, written nothing, and
looked exactly like an empty audit log.
"""

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from api.audit_mw import AuditMiddleware


@pytest.fixture(autouse=True)
def _audit_on(monkeypatch):
    """This file tests the audit machinery, so it opts back in (conftest disables it)."""
    monkeypatch.setenv("AUDIT_ENABLED", "1")
    from app.config import settings
    monkeypatch.setattr(settings, "AUDIT_ENABLED", True, raising=False)


@pytest.fixture()
def captured(monkeypatch):
    """Capture audit writes instead of hitting the DB."""
    rows = []
    import api.audit_mw as mw
    monkeypatch.setattr(mw, "write", lambda **kw: rows.append(kw) or True)
    return rows


def _app(claims: dict | None, *, boom: bool = False, status: int = 200):
    """A minimal app wired exactly like api/app.py: AuditMiddleware + a claims dependency."""
    app = FastAPI()
    app.add_middleware(AuditMiddleware)

    # `request: Request` must be ANNOTATED or FastAPI treats it as a query param and never
    # injects it — which is exactly how api.auth._stash would silently stash nothing.
    def dep(request: Request = None):
        if claims is not None and request is not None:
            request.state.claims = claims        # mirrors api.auth._stash
        return claims

    @app.post("/articles/{slug}/fix-seo")
    def fix_seo(slug: str, c=Depends(dep)):
        if boom:
            raise RuntimeError("handler exploded")
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True}, status_code=status)

    @app.get("/articles/{slug}")
    def read(slug: str, c=Depends(dep)):
        return {"ok": True}

    return app


CLAIMS = {"tenant_id": 1, "email": "tim@perkinsroofing.net", "role": "admin"}


def test_a_mutating_request_is_audited_with_the_real_actor(captured):
    client = TestClient(_app(CLAIMS))
    assert client.post("/articles/wall-flashings/fix-seo").status_code == 200
    assert len(captured) == 1
    row = captured[0]
    assert row["action"] == "article.fix-seo"
    assert row["actor_email"] == "tim@perkinsroofing.net"
    assert row["actor_role"] == "admin"
    assert row["tenant_id"] == 1
    assert row["entity_type"] == "article" and row["entity_id"] == "wall-flashings"
    assert row["status_code"] == 200
    assert row["method"] == "POST"
    assert row["request_id"]


def test_reads_are_not_audited(captured):
    client = TestClient(_app(CLAIMS))
    client.get("/articles/wall-flashings")
    assert captured == [], "GETs would drown the log without adding accountability"


def test_a_failed_request_is_still_audited(captured):
    # An unexplainable 403/500 is the main thing this exists for, so the row must survive the
    # handler blowing up and the request transaction rolling back.
    client = TestClient(_app(CLAIMS, boom=True))
    with pytest.raises(RuntimeError):
        client.post("/articles/wall-flashings/fix-seo")
    assert len(captured) == 1
    assert captured[0]["status_code"] == 500
    assert captured[0]["actor_email"] == "tim@perkinsroofing.net"


def test_a_rejected_request_records_who_was_rejected(captured):
    client = TestClient(_app(CLAIMS, status=403))
    assert client.post("/articles/wall-flashings/fix-seo").status_code == 403
    assert captured[0]["status_code"] == 403
    assert captured[0]["actor_email"] == "tim@perkinsroofing.net"


def test_audit_failure_never_breaks_the_request(monkeypatch):
    import api.audit_mw as mw

    def _explode(**kw):
        raise RuntimeError("audit db down")

    monkeypatch.setattr(mw, "write", _explode)
    client = TestClient(_app(CLAIMS))
    assert client.post("/articles/wall-flashings/fix-seo").status_code == 200


def test_health_checks_are_skipped(captured):
    app = FastAPI()
    app.add_middleware(AuditMiddleware)

    @app.post("/healthz")
    def hz():
        return {"ok": True}

    TestClient(app).post("/healthz")
    assert captured == []


def test_query_params_are_recorded_but_redacted(captured):
    client = TestClient(_app(CLAIMS))
    client.post("/articles/wall-flashings/fix-seo?status=draft&token=sekrit")
    detail = captured[0]["detail"]["query"]
    assert detail["status"] == "draft"
    assert detail["token"] == "sekrit", "middleware passes raw; write() redacts"


def test_before_after_changes_survive_the_write_redactor(monkeypatch):
    """diff() has already redacted `changes`; redact() must not run over it again.

    redact() is deny-by-default for untrusted payloads — it would replace the whole
    before/after tree with "[omitted]" (content_md is not on SAFE_KEYS) and silently turn a
    revert-capable trail into a decorative one.
    """
    captured = {}

    class _S:
        def __init__(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        info = {}
        def add(self, row): captured["row"] = row
        def commit(self): pass

    import api.audit_mw as mw
    monkeypatch.setattr(mw, "redact", lambda d: {"_redacted": True})

    class _AuditLog:
        def __init__(self, **kw): captured.update(kw)

    import app.models as models
    monkeypatch.setattr(models, "AuditLog", _AuditLog, raising=False)
    monkeypatch.setattr(models, "SessionLocal", lambda: _S(), raising=False)

    changes = {"content_md": {"from": "old body", "to": "new body"}}
    assert mw.write(tenant_id=1, action="article.update", detail={"changes": changes})
    assert captured["detail"]["changes"] == changes, "before/after was destroyed by redact()"


def test_platform_actions_go_to_the_platform_trail_not_the_tenant_one(monkeypatch):
    """A platform admin acting with no tenant context must still be audited.

    audit_log is RLS tenant-scoped with tenant_id NOT NULL, so these have nowhere to go there —
    and giving it a nullable tenant_id would mean guarding the schema's most sensitive rows
    (who was granted platform_admin, which tenant was provisioned) with a GUC the app sets on
    itself, inside the table every tenant queries. Separate table; merged at the read layer.
    """
    tenant_rows, platform_rows = [], []
    import api.audit_mw as mw
    monkeypatch.setattr(mw, "write", lambda **kw: tenant_rows.append(kw) or True)
    monkeypatch.setattr(mw, "write_platform", lambda **kw: platform_rows.append(kw) or True)

    # platform_admin without impersonation: tenant_id is None
    client = TestClient(_app({"tenant_id": None, "email": "jon@degenito.ai",
                              "role": "platform_admin"}))
    client.post("/articles/wall-flashings/fix-seo")

    assert tenant_rows == [], "a no-tenant action must not be forced into the tenant trail"
    assert len(platform_rows) == 1
    assert platform_rows[0]["actor_email"] == "jon@degenito.ai"
    assert platform_rows[0]["action"] == "article.fix-seo"
    assert platform_rows[0]["request_id"], "request_id is the join key across both trails"


def test_impersonation_target_is_recorded_on_the_platform_row(monkeypatch):
    platform_rows = []
    import api.audit_mw as mw
    monkeypatch.setattr(mw, "write_platform", lambda **kw: platform_rows.append(kw) or True)
    client = TestClient(_app({"tenant_id": None, "email": "jon@degenito.ai",
                              "role": "platform_admin", "impersonating_as": 7}))
    client.post("/articles/wall-flashings/fix-seo")
    assert platform_rows[0]["target_tenant_id"] == 7
