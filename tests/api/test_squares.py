"""tests/api/test_squares.py — behavioral tests for POST /squares/measure and
GET /squares/measurements.

All HTTP calls to Google APIs are mocked — no real network traffic.
Uses the same fake-verifier + SQLite pattern as the rest of the test suite.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from api.routes.squares import router as squares_router
from app.models import init_db

# Mount router idempotently
_MOUNTED = {getattr(r, "prefix", None) for r in appmod.app.routes}
if "/squares" not in _MOUNTED:
    appmod.app.include_router(squares_router)

AUTH = {"Authorization": "Bearer x"}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                             "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


@pytest.fixture()
def sales_client():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@perkins.com",
                             "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# Sample Solar API response (7-segment Miami building)
# ---------------------------------------------------------------------------

SOLAR_RAW = {
    "name": "buildings/ChIJabc123",
    "center": {"latitude": 25.7617, "longitude": -80.1918},
    "solarPotential": {
        "imageryDate": {"year": 2024, "month": 3, "day": 15},
        "imageryQuality": "HIGH",
        "wholeRoofStats": {"groundAreaMeters2": 180.5},
        "roofSegmentStats": [
            {"stats": {"areaMeters2": 40.0}, "pitchDegrees": 18.0, "azimuthDegrees": 180.0},
            {"stats": {"areaMeters2": 35.0}, "pitchDegrees": 20.0, "azimuthDegrees": 0.0},
            {"stats": {"areaMeters2": 30.0}, "pitchDegrees": 22.0, "azimuthDegrees": 90.0},
            {"stats": {"areaMeters2": 28.0}, "pitchDegrees": 18.0, "azimuthDegrees": 270.0},
            {"stats": {"areaMeters2": 32.0}, "pitchDegrees": 16.0, "azimuthDegrees": 135.0},
            {"stats": {"areaMeters2": 27.0}, "pitchDegrees": 24.0, "azimuthDegrees": 315.0},
            {"stats": {"areaMeters2": 25.9}, "pitchDegrees": 20.0, "azimuthDegrees": 225.0},
        ],
    },
}

GEOCODE_RESP = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "123 Main St, Miami, FL 33101, USA",
            "geometry": {"location": {"lat": 25.7617, "lng": -80.1918}},
        }
    ],
}


def _mock_get(url, *args, **kwargs):
    mock = MagicMock()
    mock.status_code = 200
    if "geocode" in url:
        mock.json.return_value = GEOCODE_RAW if hasattr(_mock_get, "_geocode_raw") else GEOCODE_RESP
        mock.raise_for_status.return_value = None
    else:
        mock.json.return_value = SOLAR_RAW
        mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# POST /squares/measure — happy path (address)
# ---------------------------------------------------------------------------

class TestMeasureAddress:
    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_measure_by_address_returns_squares(self, mock_get, admin_client):
        r = admin_client.post(
            "/squares/measure",
            json={"address": "123 Main St, Miami, FL"},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_sq"] > 0
        assert body["measurement_id"] is not None
        assert body["provider"] == "google_solar"
        assert body["status"] == "complete"
        assert "staleness_warning" in body
        assert isinstance(body["per_segment"], list)
        assert len(body["per_segment"]) == 7

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_measure_by_address_persists_row(self, mock_get, admin_client):
        r = admin_client.post(
            "/squares/measure",
            json={"address": "123 Main St, Miami, FL"},
            headers=AUTH,
        )
        assert r.status_code == 200
        body = r.json()
        # Fetch the persisted row
        from app.models import Measurement, SessionLocal
        with SessionLocal() as db:
            row = db.get(Measurement, body["measurement_id"])
        assert row is not None
        assert row.provider == "google_solar"
        assert row.total_sq == body["total_sq"]
        assert row.imagery_date == "2024-03-15"
        assert row.imagery_quality == "HIGH"


# ---------------------------------------------------------------------------
# POST /squares/measure — happy path (lat/lng direct)
# ---------------------------------------------------------------------------

class TestMeasureLatLng:
    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_measure_by_latlng_skips_geocode(self, mock_get, admin_client):
        r = admin_client.post(
            "/squares/measure",
            json={"latitude": 25.7617, "longitude": -80.1918},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_sq"] > 0
        # Geocoding should NOT have been called (only 1 GET: the Solar call)
        solar_calls = [c for c in mock_get.call_args_list if "solar" in str(c)]
        geocode_calls = [c for c in mock_get.call_args_list if "geocode" in str(c)]
        assert len(solar_calls) == 1
        assert len(geocode_calls) == 0


# ---------------------------------------------------------------------------
# POST /squares/measure — error cases
# ---------------------------------------------------------------------------

class TestMeasureErrors:
    def test_no_api_key_returns_503(self, admin_client):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SQUARES_API_KEY", None)
            r = admin_client.post(
                "/squares/measure",
                json={"address": "anywhere"},
                headers=AUTH,
            )
        assert r.status_code == 503
        assert "SQUARES_API_KEY" in r.json()["detail"]

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    def test_no_address_or_latlng_returns_422(self, admin_client):
        r = admin_client.post("/squares/measure", json={}, headers=AUTH)
        assert r.status_code == 422

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    def test_address_only_partial_latlng_geocodes(self, admin_client):
        # body.latitude present but longitude absent → should geocode
        geocode_called = []

        def mock_get(url, *args, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.raise_for_status.return_value = None
            if "geocode" in url:
                geocode_called.append(True)
                m.json.return_value = GEOCODE_RESP
            else:
                m.json.return_value = SOLAR_RAW
            return m

        with patch("api.routes.squares.http_requests.get", side_effect=mock_get):
            r = admin_client.post(
                "/squares/measure",
                json={"address": "123 Main St", "latitude": 25.0},
                headers=AUTH,
            )
        assert r.status_code == 200
        assert geocode_called, "Should have called geocode when longitude absent"

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    def test_geocode_zero_results_returns_404(self, admin_client):
        def mock_get(url, *args, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.raise_for_status.return_value = None
            m.json.return_value = {"status": "ZERO_RESULTS", "results": []}
            return m

        with patch("api.routes.squares.http_requests.get", side_effect=mock_get):
            r = admin_client.post(
                "/squares/measure",
                json={"address": "zzznowhere"},
                headers=AUTH,
            )
        assert r.status_code == 404

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    def test_solar_404_returns_404_with_detail(self, admin_client):
        def mock_get(url, *args, **kwargs):
            m = MagicMock()
            if "geocode" in url:
                m.status_code = 200
                m.raise_for_status.return_value = None
                m.json.return_value = GEOCODE_RESP
            else:
                m.status_code = 404
                from requests import HTTPError
                m.raise_for_status.side_effect = HTTPError("404")
            return m

        with patch("api.routes.squares.http_requests.get", side_effect=mock_get):
            r = admin_client.post(
                "/squares/measure",
                json={"address": "123 Main St"},
                headers=AUTH,
            )
        assert r.status_code == 404
        assert "manual entry" in r.json()["detail"].lower()

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    def test_solar_502_on_upstream_http_error(self, admin_client):
        from requests.exceptions import RequestException

        def mock_get(url, *args, **kwargs):
            m = MagicMock()
            if "geocode" in url:
                m.status_code = 200
                m.raise_for_status.return_value = None
                m.json.return_value = GEOCODE_RESP
            else:
                raise RequestException("connection refused")
            return m

        with patch("api.routes.squares.http_requests.get", side_effect=mock_get):
            r = admin_client.post(
                "/squares/measure",
                json={"address": "123 Main St"},
                headers=AUTH,
            )
        assert r.status_code == 502

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    def test_geocode_timeout_returns_502(self, admin_client):
        from requests.exceptions import Timeout

        def mock_get(url, *args, **kwargs):
            raise Timeout("timed out")

        with patch("api.routes.squares.http_requests.get", side_effect=mock_get):
            r = admin_client.post(
                "/squares/measure",
                json={"address": "123 Main St"},
                headers=AUTH,
            )
        assert r.status_code == 502

    def test_unauthenticated_returns_401(self):
        client = TestClient(appmod.app)
        r = client.post("/squares/measure", json={"address": "anywhere"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Staleness warning flag
# ---------------------------------------------------------------------------

class TestStalenessFlag:
    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get")
    def test_old_imagery_sets_warning_true(self, mock_get, admin_client):
        old_raw = json.loads(json.dumps(SOLAR_RAW))
        old_raw["solarPotential"]["imageryDate"] = {"year": 2020, "month": 1, "day": 1}
        old_raw["solarPotential"]["imageryQuality"] = "HIGH"

        def side(url, *args, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.raise_for_status.return_value = None
            m.json.return_value = GEOCODE_RESP if "geocode" in url else old_raw
            return m

        mock_get.side_effect = side
        r = admin_client.post(
            "/squares/measure",
            json={"address": "123 Main St"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["staleness_warning"] is True

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get")
    def test_medium_quality_sets_warning_true(self, mock_get, admin_client):
        med_raw = json.loads(json.dumps(SOLAR_RAW))
        med_raw["solarPotential"]["imageryQuality"] = "MEDIUM"

        def side(url, *args, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.raise_for_status.return_value = None
            m.json.return_value = GEOCODE_RESP if "geocode" in url else med_raw
            return m

        mock_get.side_effect = side
        r = admin_client.post(
            "/squares/measure",
            json={"address": "123 Main St"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["staleness_warning"] is True

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_fresh_high_quality_warning_false(self, mock_get, admin_client):
        # SOLAR_RAW has imageryDate 2024-03-15 + quality HIGH — recent enough
        r = admin_client.post(
            "/squares/measure",
            json={"address": "123 Main St"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["staleness_warning"] is False


# ---------------------------------------------------------------------------
# GET /squares/measurements
# ---------------------------------------------------------------------------

class TestListMeasurements:
    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_list_returns_solar_measurements(self, mock_get, admin_client):
        # Create a measurement first
        admin_client.post(
            "/squares/measure",
            json={"address": "123 Main St"},
            headers=AUTH,
        )
        r = admin_client.get("/squares/measurements", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["provider"] == "google_solar"

    def test_list_unauthenticated_returns_401(self):
        client = TestClient(appmod.app)
        r = client.get("/squares/measurements")
        assert r.status_code == 401

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_list_newest_first(self, mock_get, admin_client):
        # Two measurements
        for _ in range(2):
            admin_client.post(
                "/squares/measure",
                json={"address": "123 Main St"},
                headers=AUTH,
            )
        r = admin_client.get("/squares/measurements", headers=AUTH)
        data = r.json()
        assert len(data) >= 2
        ids = [d["id"] for d in data]
        assert ids == sorted(ids, reverse=True)

    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_list_sales_role_allowed(self, mock_get, sales_client):
        r = sales_client.get("/squares/measurements", headers=AUTH)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Authz
# ---------------------------------------------------------------------------

class TestAuthz:
    @patch.dict("os.environ", {"SQUARES_API_KEY": "test-key"})
    @patch("api.routes.squares.http_requests.get", side_effect=_mock_get)
    def test_sales_can_measure(self, mock_get, sales_client):
        r = sales_client.post(
            "/squares/measure",
            json={"address": "123 Main St"},
            headers=AUTH,
        )
        assert r.status_code == 200
