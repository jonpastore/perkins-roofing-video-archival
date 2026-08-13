"""A per-tenant admin must not be able to rotate a DEPLOYMENT-WIDE secret.

Found by the deepsec scan, 2026-08-13. PUT /config/secrets is gated on `manage_config`, which
`admin` satisfies — and `admin` is granted per-tenant from tenant_default_admins. The allowlist
was copied from infra/main.tf's secret_ids, so it included `internal-secret`, `db-password` and
`google-idp-client-secret`.

Concretely: a tenant-2 admin PUTs a new `internal-secret`; every API instance started afterwards
trusts their value for /internal/* cron endpoints while Cloud Scheduler keeps sending the old one.
The same route against `db-password` bricks every new instance.

api/routes/connections.py already refuses exactly this for its own rotation form.
"""
from __future__ import annotations

import pytest

from api.routes.config import ALLOWED_SECRET_IDS, PLATFORM_ONLY_SECRET_IDS


@pytest.mark.parametrize("key", sorted(PLATFORM_ONLY_SECRET_IDS))
def test_platform_secrets_are_still_listable(key):
    """GET /config/secrets iterates ALLOWED_SECRET_IDS — status stays visible, writes do not."""
    assert key in ALLOWED_SECRET_IDS


def test_the_dangerous_three_are_all_covered():
    """Named explicitly: if someone adds one back to the writable path, this is the tripwire."""
    assert PLATFORM_ONLY_SECRET_IDS == {
        "internal-secret", "db-password", "google-idp-client-secret",
    }


@pytest.mark.parametrize("key", sorted(PLATFORM_ONLY_SECRET_IDS))
def test_upsert_refuses_a_deployment_wide_secret(key, monkeypatch):
    """403 before any Secret Manager call — the write must not reach GCP at all."""
    from fastapi import HTTPException

    import api.routes.config as C

    def _boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("reached Secret Manager for a platform-only secret")

    monkeypatch.setattr(C, "_secret_manager_client", _boom)

    with pytest.raises(HTTPException) as ei:
        C.upsert_secret(C.SecretEntry(key=key, value="pwned"), claims={"email": "a@tenant2.test"})
    assert ei.value.status_code == 403
    assert "deployment-wide" in str(ei.value.detail)


def test_an_ordinary_integration_secret_is_still_writable(monkeypatch):
    """The fix must not brick legitimate rotation — this is what the screen is FOR."""
    import api.routes.config as C

    reached = []

    class _Client:
        def add_secret_version(self, request):
            reached.append(request["parent"])

    monkeypatch.setattr(C, "_secret_manager_client", lambda: _Client())
    monkeypatch.setattr(C, "_gcp_project", lambda: "proj")
    monkeypatch.setattr(C, "_secret_latest_create_time", lambda *a, **k: None)
    monkeypatch.setattr(C, "_record_secret_audit", lambda *a, **k: None, raising=False)

    try:
        C.upsert_secret(C.SecretEntry(key="resend-api-key", value="v"),
                        claims={"email": "a@tenant1.test"})
    except Exception:
        pass  # persistence/audit paths need a DB; the GCP call is what matters here

    assert any("resend-api-key" in p for p in reached), (
        "a normal integration secret must still reach Secret Manager"
    )
