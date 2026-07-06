"""Tests for GET /config, PUT /config, GET /config/secrets, PUT /config/secrets.

All admin-gated (manage_config). Sales role must get 403 everywhere.
Secret Manager calls are monkeypatched — no live GCP needed.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.config import router as config_router, EDITABLE_KEYS, ALLOWED_SECRET_IDS
from app.models import init_db, SecretAudit, SessionLocal

# Mount the config router onto the shared app once (idempotent).
if not any(getattr(r, "path", None) == "/config" for r in appmod.app.routes):
    appmod.app.include_router(config_router)


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@test.com", "role": "admin"})
    return TestClient(appmod.app)


@pytest.fixture()
def sales_client():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@test.com", "role": "sales"})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------------

def test_get_config_admin_ok(admin_client):
    r = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert "settings" in body
    assert "known_models" in body
    assert "default_admins" in body
    assert "default_admins_note" in body
    # known_models has llm + embed lists
    assert "llm" in body["known_models"]
    assert "embed" in body["known_models"]
    assert isinstance(body["known_models"]["llm"], list)
    assert len(body["known_models"]["llm"]) > 0
    assert len(body["known_models"]["embed"]) > 0


def test_get_config_returns_settings_list(admin_client):
    r = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    settings_list = r.json()["settings"]
    assert isinstance(settings_list, list)
    keys = [s["key"] for s in settings_list]
    # All EDITABLE_KEYS must appear
    for k in EDITABLE_KEYS:
        assert k in keys
    # Each entry has required fields
    for entry in settings_list:
        assert "key" in entry
        assert "label" in entry
        assert "value" in entry
        assert entry["editable"] is True
        assert entry["source"] in ("db", "env")


def test_get_config_db_override_shows_source(admin_client):
    # Seed a db override
    admin_client.put(
        "/config",
        json={"key": "WP_URL", "value": "https://perkins.example.com"},
        headers={"Authorization": "Bearer x"},
    )
    r = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    body = r.json()
    wp = next(s for s in body["settings"] if s["key"] == "WP_URL")
    assert wp["source"] == "db"
    assert wp["value"] == "https://perkins.example.com"
    assert wp["updated_by"] == "admin@test.com"
    assert wp["updated_at"] is not None


def test_get_config_default_admins_note(admin_client):
    r = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    note = r.json()["default_admins_note"]
    assert "Users page" in note


def test_get_config_sales_forbidden(sales_client):
    r = sales_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


def test_get_config_unauthenticated():
    client = TestClient(appmod.app)
    r = client.get("/config")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /config
# ---------------------------------------------------------------------------

def test_put_config_upsert(admin_client):
    r = admin_client.put(
        "/config",
        json={"key": "WP_URL", "value": "https://perkins.example.com"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "WP_URL"
    assert body["value"] == "https://perkins.example.com"
    assert body["updated_by"] == "admin@test.com"
    assert body["updated_at"] is not None


def test_put_config_update_existing(admin_client):
    admin_client.put(
        "/config",
        json={"key": "MAX_VIDEOS_PER_RUN", "value": "100"},
        headers={"Authorization": "Bearer x"},
    )
    r = admin_client.put(
        "/config",
        json={"key": "MAX_VIDEOS_PER_RUN", "value": "250"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert r.json()["value"] == "250"

    r2 = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    entry = next(s for s in r2.json()["settings"] if s["key"] == "MAX_VIDEOS_PER_RUN")
    assert entry["value"] == "250"
    assert entry["source"] == "db"


def test_put_config_records_updated_by(admin_client):
    r = admin_client.put(
        "/config",
        json={"key": "ABSTAIN_THRESHOLD", "value": "0.85"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.json()["updated_by"] == "admin@test.com"


def test_put_config_rejects_unknown_key(admin_client):
    r = admin_client.put(
        "/config",
        json={"key": "SECRET_THING", "value": "bad"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422


def test_put_config_sales_forbidden(sales_client):
    r = sales_client.put(
        "/config",
        json={"key": "WP_URL", "value": "y"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403


def test_put_config_unauthenticated():
    client = TestClient(appmod.app)
    r = client.put("/config", json={"key": "WP_URL", "value": "x"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /config/secrets
# ---------------------------------------------------------------------------

def _mock_sm_client(create_time_iso="2026-07-01T12:00:00+00:00"):
    """Build a mock Secret Manager client that returns a single version."""
    from datetime import timezone
    from unittest.mock import MagicMock

    version = MagicMock()
    # create_time.timestamp() must return a float
    ts = 1751371200.0  # 2026-07-01T12:00:00Z
    version.create_time.timestamp.return_value = ts

    client = MagicMock()
    client.list_secret_versions.return_value = [version]
    return client


def test_get_secrets_admin_ok(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert "secrets" in body
    secret_keys = {s["key"] for s in body["secrets"]}
    # All allowed secrets are listed
    assert ALLOWED_SECRET_IDS == secret_keys


def test_get_secrets_never_returns_value(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    for s in r.json()["secrets"]:
        assert "value" not in s
        assert "secret_data" not in s


def test_get_secrets_metadata_fields(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    for s in r.json()["secrets"]:
        assert "key" in s
        assert "last_set" in s
        assert "last_set_by" in s
        assert "ui_updated_at" in s


def test_get_secrets_no_gcp_graceful(admin_client):
    """When GCP is unavailable, last_set is None but endpoint still returns 200."""
    with patch("api.routes.config._secret_manager_client", side_effect=Exception("no gcp")):
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    for s in r.json()["secrets"]:
        assert s["last_set"] is None


def test_get_secrets_sales_forbidden(sales_client):
    r = sales_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


def test_get_secrets_unauthenticated():
    client = TestClient(appmod.app)
    r = client.get("/config/secrets")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /config/secrets
# ---------------------------------------------------------------------------

def test_put_secrets_admin_ok(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.put(
            "/config/secrets",
            json={"key": "youtube-api-key", "value": "AIza_test_key"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "youtube-api-key"
    assert body["last_set_by"] == "admin@test.com"
    # value must never appear in response
    assert "value" not in body
    assert "secret_data" not in body


def test_put_secrets_never_returns_value(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.put(
            "/config/secrets",
            json={"key": "serper-api-key", "value": "super_secret_value"},
            headers={"Authorization": "Bearer x"},
        )
    resp_str = r.text
    # The submitted value must never appear anywhere in the response
    assert "super_secret_value" not in resp_str


def test_put_secrets_records_audit(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        admin_client.put(
            "/config/secrets",
            json={"key": "resend-api-key", "value": "re_test123"},
            headers={"Authorization": "Bearer x"},
        )
    with SessionLocal() as db:
        audit = db.get(SecretAudit, "resend-api-key")
    assert audit is not None
    assert audit.updated_by == "admin@test.com"
    assert audit.updated_at is not None


def test_put_secrets_audit_shows_in_get(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        admin_client.put(
            "/config/secrets",
            json={"key": "wp-app-password", "value": "pw"},
            headers={"Authorization": "Bearer x"},
        ) if "wp-app-password" in ALLOWED_SECRET_IDS else None

        admin_client.put(
            "/config/secrets",
            json={"key": "wordpress-app-password", "value": "pw_test"},
            headers={"Authorization": "Bearer x"},
        )
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})

    secrets = {s["key"]: s for s in r.json()["secrets"]}
    wap = secrets.get("wordpress-app-password")
    assert wap is not None
    assert wap["last_set_by"] == "admin@test.com"
    assert wap["ui_updated_at"] is not None


def test_put_secrets_rejects_unknown_key(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.put(
            "/config/secrets",
            json={"key": "not-a-real-secret", "value": "val"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 422


def test_put_secrets_rejects_empty_value(admin_client):
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.put(
            "/config/secrets",
            json={"key": "youtube-api-key", "value": ""},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 422


def test_put_secrets_gcp_error_returns_502(admin_client):
    broken_client = MagicMock()
    broken_client.add_secret_version.side_effect = Exception("GCP unavailable")
    with patch("api.routes.config._secret_manager_client", return_value=broken_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.put(
            "/config/secrets",
            json={"key": "youtube-api-key", "value": "somekey"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 502


def test_put_secrets_sales_forbidden(sales_client):
    r = sales_client.put(
        "/config/secrets",
        json={"key": "youtube-api-key", "value": "val"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403


def test_put_secrets_unauthenticated():
    client = TestClient(appmod.app)
    r = client.put("/config/secrets", json={"key": "youtube-api-key", "value": "val"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /config/secrets — provisioned flag
# ---------------------------------------------------------------------------

def test_get_secrets_provisioned_flag(admin_client):
    """Provisioned secrets have provisioned=True; social/unprovisioned have False."""
    from api.routes.config import _PROVISIONED_SECRET_IDS
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    secrets_map = {s["key"]: s for s in r.json()["secrets"]}
    for key, meta in secrets_map.items():
        assert "provisioned" in meta
        assert meta["provisioned"] == (key in _PROVISIONED_SECRET_IDS)


def test_get_secrets_unprovisioned_last_set_is_none(admin_client):
    """Unprovisioned secrets must have last_set=None even if GCP is available."""
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    for s in r.json()["secrets"]:
        if not s["provisioned"]:
            assert s["last_set"] is None, f"{s['key']} should have last_set=None"


def test_get_secrets_includes_whisper_token(admin_client):
    """whisper-token must appear in the secrets list."""
    mock_client = _mock_sm_client()
    with patch("api.routes.config._secret_manager_client", return_value=mock_client), \
         patch("api.routes.config._gcp_project", return_value="test-project"):
        r = admin_client.get("/config/secrets", headers={"Authorization": "Bearer x"})
    keys = {s["key"] for s in r.json()["secrets"]}
    assert "whisper-token" in keys


# ---------------------------------------------------------------------------
# PUT /config — PROD_DOMAIN editable key
# ---------------------------------------------------------------------------

def test_put_config_prod_domain(admin_client):
    """PROD_DOMAIN is in the editable keys and can be persisted."""
    r = admin_client.put(
        "/config",
        json={"key": "PROD_DOMAIN", "value": "perkins.degenito.ai"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert r.json()["value"] == "perkins.degenito.ai"


def test_get_config_includes_prod_domain(admin_client):
    """GET /config must include PROD_DOMAIN in the settings list."""
    r = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    keys = [s["key"] for s in r.json()["settings"]]
    assert "PROD_DOMAIN" in keys


# ---------------------------------------------------------------------------
# GET /config/health-checks
# ---------------------------------------------------------------------------

def test_health_checks_admin_ok(admin_client):
    """Health checks endpoint returns 200 with a results list."""
    with patch("api.routes.config._check_vertex", return_value=(True, "ADC valid")), \
         patch("api.routes.config._check_db", return_value=(True, "ok")), \
         patch("api.routes.config._check_wordpress", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_resend", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_youtube", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_serper", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_oauth", return_value=(True, "client_id configured")):
        r = admin_client.get("/config/health-checks", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert isinstance(body["results"], list)
    assert len(body["results"]) == 7


def test_health_checks_result_shape(admin_client):
    """Each result has name, ok, detail fields."""
    with patch("api.routes.config._check_vertex", return_value=(True, "ADC valid")), \
         patch("api.routes.config._check_db", return_value=(True, "ok")), \
         patch("api.routes.config._check_wordpress", return_value=(False, "WP_URL not configured")), \
         patch("api.routes.config._check_resend", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_youtube", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_serper", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_oauth", return_value=(True, "client_id configured")):
        r = admin_client.get("/config/health-checks", headers={"Authorization": "Bearer x"})
    for result in r.json()["results"]:
        assert "name" in result
        assert "ok" in result
        assert "detail" in result
        assert isinstance(result["ok"], bool)


def test_health_checks_partial_failure(admin_client):
    """A failing probe does not prevent other probes from running."""
    with patch("api.routes.config._check_vertex", return_value=(False, "no ADC")), \
         patch("api.routes.config._check_db", return_value=(True, "ok")), \
         patch("api.routes.config._check_wordpress", return_value=(False, "timeout")), \
         patch("api.routes.config._check_resend", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_youtube", return_value=(False, "403 Forbidden")), \
         patch("api.routes.config._check_serper", return_value=(True, "HTTP 200")), \
         patch("api.routes.config._check_oauth", return_value=(True, "client_id configured")):
        r = admin_client.get("/config/health-checks", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    results = {item["name"]: item for item in r.json()["results"]}
    assert results["Vertex / GCP"]["ok"] is False
    assert results["Database"]["ok"] is True
    assert results["YouTube API"]["ok"] is False
    assert results["Serper"]["ok"] is True


def test_health_checks_sales_forbidden(sales_client):
    r = sales_client.get("/config/health-checks", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


def test_health_checks_unauthenticated():
    client = TestClient(appmod.app)
    r = client.get("/config/health-checks")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# _check_resend unit tests
# ---------------------------------------------------------------------------

def test_check_resend_no_key():
    from api.routes.config import _check_resend
    ok, detail = _check_resend("")
    assert ok is False
    assert "not configured" in detail


def test_check_resend_success():
    import urllib.error
    from unittest.mock import MagicMock, patch
    from api.routes.config import _check_resend

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        ok, detail = _check_resend("re_validkey")
    assert ok is True
    assert "200" in detail


def test_check_resend_restricted_key_ok():
    """A send-only (restricted) key returns 401 with name=restricted_api_key — treat as ok=True."""
    import json
    import urllib.error
    from unittest.mock import patch, MagicMock
    from api.routes.config import _check_resend

    body = json.dumps({"statusCode": 401, "name": "restricted_api_key",
                       "message": "restricted to only send emails"}).encode()
    http_err = urllib.error.HTTPError(
        url="https://api.resend.com/domains", code=401, msg="Unauthorized",
        hdrs=MagicMock(), fp=MagicMock(read=MagicMock(return_value=body)),
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        ok, detail = _check_resend("re_sendonly")
    assert ok is True
    assert "send-only" in detail


def test_check_resend_bad_key_401():
    """A genuinely invalid key returns 401 without restricted_api_key name — ok=False."""
    import json
    import urllib.error
    from unittest.mock import patch, MagicMock
    from api.routes.config import _check_resend

    body = json.dumps({"statusCode": 401, "name": "invalid_api_key",
                       "message": "Invalid API key"}).encode()
    http_err = urllib.error.HTTPError(
        url="https://api.resend.com/domains", code=401, msg="Unauthorized",
        hdrs=MagicMock(), fp=MagicMock(read=MagicMock(return_value=body)),
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        ok, detail = _check_resend("re_badkey")
    assert ok is False
    assert "401" in detail


def test_check_resend_network_error():
    from unittest.mock import patch
    from api.routes.config import _check_resend

    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        ok, detail = _check_resend("re_somekey")
    assert ok is False
    assert "connection refused" in detail


# ---------------------------------------------------------------------------
# _check_oauth unit tests
# ---------------------------------------------------------------------------

def test_check_oauth_no_key():
    from api.routes.config import _check_oauth
    ok, detail = _check_oauth("")
    assert ok is False
    assert "not configured" in detail


def test_check_oauth_valid():
    from api.routes.config import _check_oauth
    client_id = "123456789.apps.googleusercontent.com"
    ok, detail = _check_oauth(client_id)
    assert ok is True
    assert "configured" in detail


def test_check_oauth_malformed():
    from api.routes.config import _check_oauth
    ok, detail = _check_oauth("not-a-real-client-id")
    assert ok is False
    assert "does not look like" in detail


def test_health_checks_includes_oauth(admin_client):
    """GET /config/health-checks result list includes a Google OAuth entry."""
    with patch("api.routes.config._check_vertex", return_value=(True, "ok")), \
         patch("api.routes.config._check_db", return_value=(True, "ok")), \
         patch("api.routes.config._check_wordpress", return_value=(True, "ok")), \
         patch("api.routes.config._check_resend", return_value=(True, "ok")), \
         patch("api.routes.config._check_youtube", return_value=(True, "ok")), \
         patch("api.routes.config._check_serper", return_value=(True, "ok")), \
         patch("api.routes.config._check_oauth", return_value=(True, "client_id configured")):
        r = admin_client.get("/config/health-checks", headers={"Authorization": "Bearer x"})
    names = [item["name"] for item in r.json()["results"]]
    assert "Google OAuth" in names
