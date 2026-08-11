"""POST /measurements/parse-roofr — the upload path's own logic.

The PDF-to-text step is stubbed: pypdf is not the thing under test, and a fixture PDF would tie
these to ~/perkins-corpus, which is not in the repo. What IS under test is everything the route
decides — that a non-Roofr PDF is refused rather than parsed into a form full of nulls, that the
role gate holds, and that nothing is written to the database.

Verified separately against three real reports from Tim's corpus (10456 159th Ct, 104 Via
Veracruz, 12905 175th Rd): 200 with the full field set, the lumber schedule PDF rejected 422,
a non-PDF rejected 422, and a `sales` token 403.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

import api.routes.measurements as mroute  # noqa: E402
from api.auth import set_verifier  # noqa: E402
from app.models import Base, Measurement, SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)

REPORT_TEXT = """
Roofr area measurement report
Total roof area: 3196 sqft Predominant pitch: 5/12
Pitched roof area: 2774 sqft
Flat roof area: 422 sqft
Ridges: 75ft 7in
Valleys: 72ft
Eaves: 179ft 11in
"""


def _client(role="admin"):
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    app = FastAPI()
    app.include_router(mroute.router)
    return TestClient(app)


@pytest.fixture()
def pdf_text(monkeypatch):
    def _set(text):
        monkeypatch.setattr(mroute, "_extract_pdf_text", lambda _data: text)
    return _set


def _post(client, content=b"%PDF-1.4 fake"):
    return client.post(
        "/measurements/parse-roofr",
        files={"file": ("report.pdf", content, "application/pdf")},
        headers={"Authorization": "Bearer tok"},
    )


def test_returns_the_parsed_fields(pdf_text):
    pdf_text(REPORT_TEXT)
    r = _post(_client())
    assert r.status_code == 200
    m = r.json()["measurement"]
    assert m["total_sq"] == 31.96
    assert m["pitched_sq"] == 27.74
    assert m["flat_sq"] == 4.22
    assert m["pitch_primary"] == 5.0
    assert m["ridges_lf"] == 75.58


def test_it_saves_nothing(pdf_text):
    """Prefill only. Unreviewed numbers must not become a measurement a quote can price."""
    pdf_text(REPORT_TEXT)
    before = SessionLocal().query(Measurement).count()
    assert _post(_client()).status_code == 200
    assert SessionLocal().query(Measurement).count() == before


def test_a_pdf_that_is_not_a_roofr_report_is_refused(pdf_text):
    """It would otherwise parse to all-nulls and prefill an empty form, which reads as a report
    that simply had no measurements in it."""
    pdf_text("INVOICE\nLumber schedule\nAmount due: $4,730")
    r = _post(_client())
    assert r.status_code == 422
    assert "Roofr" in r.json()["detail"]


def test_a_roofr_report_with_no_area_is_refused(pdf_text):
    pdf_text("Roofr area measurement report\nPredominant pitch: 5/12\n")
    r = _post(_client())
    assert r.status_code == 422
    assert "total roof area" in r.json()["detail"].lower()


def test_an_empty_upload_is_refused(pdf_text):
    pdf_text(REPORT_TEXT)
    r = _post(_client(), content=b"")
    assert r.status_code == 422


def test_sales_cannot_upload(pdf_text):
    pdf_text(REPORT_TEXT)
    assert _post(_client("sales")).status_code == 403


def test_no_token_is_401(pdf_text):
    pdf_text(REPORT_TEXT)
    client = _client()
    r = client.post("/measurements/parse-roofr",
                    files={"file": ("report.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 401
