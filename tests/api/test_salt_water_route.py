"""POST /estimator/salt-water — the check that ticks the Coastal package.

Coordinates are exercised for real against the shipped layer (no geocoding involved), because the
number this returns decides both a price and what a customer is told about their warranty. The
geocoding branch is stubbed: Google's API is not under test here.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

import api.routes.estimator as est  # noqa: E402
from api.auth import set_verifier  # noqa: E402

LONE_PINE = {"latitude": 26.8560414, "longitude": -80.0764616}   # Tim's client — 77 ft
GOLDEN_GATE = {"latitude": 26.1876, "longitude": -81.6431}       # inland Naples


def _client(role="admin"):
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    app = FastAPI()
    app.include_router(est.router)
    return TestClient(app)


def _post(body, role="admin"):
    return _client(role).post("/estimator/salt-water", json=body,
                              headers={"Authorization": "Bearer tok"})


def test_a_waterfront_address_reports_the_distance_and_ticks_coastal():
    r = _post(LONE_PINE)
    assert r.status_code == 200
    d = r.json()
    assert d["waterfront"] is True
    assert d["distance_ft"] < 500, d["distance_ft"]
    assert d["materials"], "the per-manufacturer verdicts are the point"


def test_an_inland_address_does_not_tick_coastal():
    """Ticking it here would silently add the Coastal package to every inland Naples quote."""
    d = _post(GOLDEN_GATE).json()
    assert d["waterfront"] is False
    assert d["distance_ft"] > 2640


def test_painted_steel_is_void_on_the_water():
    d = _post(LONE_PINE).json()
    steel = next(m for m in d["materials"] if "Kynar/PVDF-painted steel" in m["name"])
    assert steel["state"] == "void"


def test_the_warranty_terms_ride_along_for_the_proposal():
    d = _post(LONE_PINE).json()
    issuers = {t["issuer"] for t in d["warranty_terms"]}
    assert "Metal Alliance" in issuers


def test_neither_coordinates_nor_address_is_a_422():
    assert _post({}).status_code == 422


def test_an_address_is_geocoded(monkeypatch):
    monkeypatch.setattr("api.routes.squares._api_key", lambda: "test-key")
    monkeypatch.setattr("api.routes.squares._geocode",
                        lambda a, k: (26.8560414, -80.0764616, "188 Lone Pine Dr, FL"))
    d = _post({"address": "188 Lone Pine Dr, Palm Beach Gardens, FL"}).json()
    assert d["waterfront"] is True
    assert d["address"] == "188 Lone Pine Dr, FL"


def test_coordinates_win_over_an_address(monkeypatch):
    """No geocoding call should happen when coordinates are supplied — cheaper and exact."""
    def _boom(*a, **k):
        raise AssertionError("geocoded despite being given coordinates")
    monkeypatch.setattr("api.routes.squares._geocode", _boom)
    assert _post({**GOLDEN_GATE, "address": "somewhere else"}).json()["waterfront"] is False


@pytest.mark.parametrize("role,expect", [("sales", 200), ("admin", 200)])
def test_sales_can_read_it(role, expect):
    """estimating_view, not manage: a salesperson building a quote needs this answer."""
    assert _post(LONE_PINE, role=role).status_code == expect


def test_a_city_centroid_is_refused_rather_than_priced(monkeypatch):
    """Google answers HTTP 200 / status OK with an APPROXIMATE centroid for an address it cannot
    place — a new-construction lot, a rural route. The estimate form ticks the Coastal package
    from these coordinates, so a confident-but-wrong answer silently adds or omits cost.
    """
    from unittest.mock import MagicMock

    import api.routes.squares as sq

    def _resp(payload):
        m = MagicMock()
        m.json.return_value = payload
        m.raise_for_status.return_value = None
        return m

    centroid = {"status": "OK", "results": [{
        "geometry": {"location": {"lat": 25.77, "lng": -80.19}, "location_type": "APPROXIMATE"},
        "formatted_address": "Miami, FL, USA"}]}
    monkeypatch.setattr(sq.http_requests, "get", lambda *a, **k: _resp(centroid))
    monkeypatch.setattr(sq, "_api_key", lambda: "test-key")

    r = _post({"address": "123 Nonexistent Way, Miami, FL"})
    assert r.status_code == 404
    assert "specific property" in r.json()["detail"]


def test_a_rooftop_match_is_accepted(monkeypatch):
    from unittest.mock import MagicMock

    import api.routes.squares as sq

    def _resp(payload):
        m = MagicMock()
        m.json.return_value = payload
        m.raise_for_status.return_value = None
        return m

    rooftop = {"status": "OK", "results": [{
        "geometry": {"location": {"lat": 26.8560414, "lng": -80.0764616},
                     "location_type": "ROOFTOP"},
        "formatted_address": "188 Lone Pine Dr, Palm Beach Gardens, FL"}]}
    monkeypatch.setattr(sq.http_requests, "get", lambda *a, **k: _resp(rooftop))
    monkeypatch.setattr(sq, "_api_key", lambda: "test-key")

    d = _post({"address": "188 Lone Pine Dr, Palm Beach Gardens, FL"}).json()
    assert d["waterfront"] is True
