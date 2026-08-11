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
