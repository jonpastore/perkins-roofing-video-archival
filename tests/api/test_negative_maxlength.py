"""Endpoint-level oversized-field regression tests (422, never a prod-Postgres 500).

Companion to tests/api/test_schema_maxlength.py (which proves every bounded DB
column has a matching Pydantic max_length). These exercise the real endpoints:
oversized input must be rejected at validation (422) — which fires before the
handler runs, so no fixture rows are needed.
"""
import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import init_db

_MOUNTED = set(getattr(r, "prefix", None) for r in appmod.app.routes)
if "/quoting/customers" not in _MOUNTED:
    from api.routes.customers import router as customers_router
    appmod.app.include_router(customers_router)

AUTH = {"Authorization": "Bearer x"}


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                            "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


LONG = "x" * 1001  # longer than every bound in play

OVERSIZED = [
    # (id, method, path, payload-with-one-oversized-field)
    ("customer_display_name", "post", "/quoting/customers", {"display_name": "x" * 256}),
    ("customer_phone", "post", "/quoting/customers", {"display_name": "A", "phone": "1" * 51}),
    ("contact_role", "post", "/quoting/customers/1/contacts",
     {"name": "A", "role": "x" * 101}),
    ("payment_method", "post", "/invoices/1/payments",
     {"amount": "10.00", "idempotency_key": "abcdefgh", "method": "toolong"}),
    ("payment_reference", "post", "/invoices/1/payments",
     {"amount": "10.00", "idempotency_key": "abcdefgh", "reference": "x" * 256}),
    ("price_book_item_type", "post", "/price-book/items",
     {"name": "Shingle", "item_type": "x" * 31}),
    ("price_book_name", "post", "/price-book/items", {"name": "x" * 256}),
    ("proposal_title", "post", "/quoting/proposals",
     {"customer_id": 1, "property_id": 1, "title": "x" * 501, "quote_snapshot": {}}),
    ("template_primary_color", "post", "/quoting/templates",
     {"name": "T", "html_body": "<p/>", "primary_color": "#1234567"}),
    ("template_logo_url", "post", "/quoting/templates",
     {"name": "T", "html_body": "<p/>", "logo_url": LONG}),
    ("contract_faq_status", "put", "/contract-faq/1", {"status": "x" * 21}),
    ("tc_version_tag", "post", "/contract-faq/tc-version",
     {"tc_text": "terms", "version_tag": "x" * 51}),
]


@pytest.mark.parametrize("case,method,path,payload", OVERSIZED, ids=[c[0] for c in OVERSIZED])
def test_oversized_field_returns_422(admin_client, case, method, path, payload):
    r = getattr(admin_client, method)(path, json=payload, headers=AUTH)
    assert r.status_code == 422, f"{case}: expected 422, got {r.status_code}: {r.text}"


def test_valid_payload_passes_validation(admin_client):
    # positive control: a short, valid create is not caught by the new bounds
    r = admin_client.post("/price-book/items",
                          json={"name": "Ridge cap", "item_type": "material"}, headers=AUTH)
    assert r.status_code == 200, r.text
