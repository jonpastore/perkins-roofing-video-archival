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


def test_a_text_bomb_is_rejected_rather_than_burning_the_instance(monkeypatch):
    """A ~44 KB crafted PDF extracted 32,000,003 characters and blocked for 40.5 s.

    The endpoint is `async def` (it awaits file.read()), so calling pypdf directly ran that ON the
    event loop — and uvicorn starts without --workers, so it is ONE loop for the whole API with
    max_instance_count 4. A trickle of these wedged the platform for every user. The extraction
    now runs in a threadpool AND is bounded, because off-the-loop alone still burns an instance.
    """
    import zlib

    from api.routes.measurements import _MAX_PAGES, _MAX_TEXT_CHARS, _extract_pdf_text

    chunk = b"BT /F1 8 Tf 10 10 Td (" + b"A" * 4000 + b") Tj ET\n"
    comp = zlib.compress(chunk * 2000, 9)
    n = 2
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: f"<< /Type /Pages /Count {n} /Kids [{' '.join(f'{4+i} 0 R' for i in range(n))}] >>".encode(),
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    for i in range(n):
        objs[4 + i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                       f"<< /Font << /F1 3 0 R >> >> /Contents {4+n+i} 0 R >>").encode()
        objs[4 + n + i] = (f"<< /Length {len(comp)} /Filter /FlateDecode >>\nstream\n".encode()
                           + comp + b"\nendstream")
    out, off = bytearray(b"%PDF-1.4\n"), {}
    for k in sorted(objs):
        off[k] = len(out)
        out += f"{k} 0 obj\n".encode() + objs[k] + b"\nendobj\n"
    x, m = len(out), max(objs) + 1
    out += f"xref\n0 {m}\n0000000000 65535 f \n".encode()
    for k in range(1, m):
        out += f"{off[k]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {m} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()

    assert len(bytes(out)) < 100_000, "the point is that the FILE is small"
    with pytest.raises(Exception) as exc:
        _extract_pdf_text(bytes(out))
    assert getattr(exc.value, "status_code", None) == 422
    assert _MAX_TEXT_CHARS <= 200_000 and _MAX_PAGES <= 60


def test_the_extraction_runs_off_the_event_loop():
    """`async def` + a synchronous pypdf call is what made one upload everyone's outage."""
    import inspect

    import api.routes.measurements as m
    src = inspect.getsource(m.parse_roofr_report)
    assert "run_in_threadpool(_extract_pdf_text" in src, "PDF work must not run on the event loop"
