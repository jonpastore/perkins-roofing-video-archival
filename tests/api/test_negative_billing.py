"""Negative-path tests for billing/quoting API routes.

Covers, for each POST/PUT/PATCH/DELETE endpoint in customers.py, contract_faq.py,
invoices.py, price_book.py, proposals.py, payments.py, quotes.py, pricing_configs.py:
  1. missing required field -> 422
  2. wrong type for a field -> 422
  3. nonexistent resource id -> 404 (authed, valid body)
  4. unauthenticated -> 401
  5. insufficient role -> 403

Only gaps not already exercised by test_f3_customers.py, test_f3_proposals.py,
test_contract_faq.py, test_sales_console.py, test_estimator_f2.py, and
test_negative_maxlength.py are added here (see each file for existing coverage).
payments.py and quotes.py are read-only (GET only) and have no mutating endpoints,
so neither contributes cases.

All routers are already mounted on api.app by app.py; no manual include_router needed.
FastAPI resolves auth dependencies before body validation, so 401/403 cases below use
a `{}` body regardless of the endpoint's real schema (see test_f3_proposals.py
test_unauthenticated_proposals_401 for the same pattern).
"""
import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import init_db

AUTH = {"Authorization": "Bearer x"}


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


def _client(role, email):
    set_verifier(lambda t: {"uid": email, "email": email, "role": role, "email_verified": True})
    return TestClient(appmod.app)


@pytest.fixture()
def admin_client():
    return _client("admin", "admin@perkins.com")


@pytest.fixture()
def sales_client():
    return _client("sales", "sales@perkins.com")


@pytest.fixture()
def noperm_client():
    """A role absent from core.authz._MATRIX -- denied every action (empty grant set)."""
    return _client("no_perms", "noperm@perkins.com")


def _call(client, method, path, body):
    if method == "delete":
        return client.delete(path, headers=AUTH)
    return getattr(client, method)(path, json=body, headers=AUTH)


# ---------------------------------------------------------------------------
# 401 unauthenticated -- gaps not covered by existing per-domain test files
# ---------------------------------------------------------------------------

UNAUTH_CASES = [
    ("put", "/quoting/customers/1"),
    ("patch", "/quoting/customers/1/deactivate"),
    ("post", "/quoting/customers/1/contacts"),
    ("put", "/quoting/contacts/1"),
    ("post", "/quoting/customers/1/properties"),
    ("put", "/quoting/properties/1"),
    ("delete", "/quoting/properties/1"),
    ("post", "/contract-faq/ai-prompts"),
    ("post", "/contract-faq/tc-version"),
    ("put", "/contract-faq/1"),
    ("delete", "/contract-faq/1"),
    ("post", "/invoices"),
    ("post", "/invoices/1/payments"),
    ("post", "/price-book/items"),
    ("put", "/price-book/items/1"),
    ("post", "/price-book/versions"),
    ("post", "/estimator/configs/1/activate"),
    ("post", "/quoting/proposals/from-quote/X"),
    ("put", "/quoting/proposals/1"),
    ("post", "/quoting/proposals/1/send"),
    ("post", "/quoting/proposals/1/revise"),
    ("post", "/quoting/templates"),
    ("put", "/quoting/templates/1"),
    ("delete", "/quoting/templates/1"),
    ("post", "/quoting/templates/1/preview"),
    ("put", "/quoting/settings"),
]


@pytest.mark.parametrize("method,path", UNAUTH_CASES, ids=[f"{m}:{p}" for m, p in UNAUTH_CASES])
def test_unauthenticated_returns_401(method, path):
    set_verifier(None)
    client = TestClient(appmod.app)
    if method == "delete":
        r = client.delete(path)
    else:
        r = getattr(client, method)(path, json={})
    assert r.status_code == 401, f"{method} {path}: expected 401, got {r.status_code}: {r.text}"


def test_extract_pdf_unauthenticated_401():
    set_verifier(None)
    client = TestClient(appmod.app)
    r = client.post("/contract-faq/extract-pdf",
                    files={"file": ("c.pdf", b"%PDF fake", "application/pdf")})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 403 insufficient role -- quoting_create/quoting_send/quoting_view gated
# endpoints, where sales AND web_admin both hold the permission. no_perms
# (a role absent from core.authz._MATRIX) is the only role that must be denied.
# ---------------------------------------------------------------------------

NOPERM_403_CASES = [
    ("post", "/quoting/customers"),
    ("put", "/quoting/customers/1"),
    ("patch", "/quoting/customers/1/deactivate"),
    ("post", "/quoting/customers/1/contacts"),
    ("put", "/quoting/contacts/1"),
    ("post", "/quoting/customers/1/properties"),
    ("put", "/quoting/properties/1"),
    ("delete", "/quoting/properties/1"),
    ("post", "/quoting/proposals"),
    ("post", "/quoting/proposals/from-quote/X"),
    ("put", "/quoting/proposals/1"),
    ("post", "/quoting/proposals/1/send"),
    ("post", "/quoting/proposals/1/revise"),
    ("post", "/quoting/templates/1/preview"),
]


@pytest.mark.parametrize("method,path", NOPERM_403_CASES, ids=[f"{m}:{p}" for m, p in NOPERM_403_CASES])
def test_insufficient_role_returns_403(noperm_client, method, path):
    r = _call(noperm_client, method, path, {})
    assert r.status_code == 403, f"{method} {path}: expected 403, got {r.status_code}: {r.text}"


# sales lacks manage_articles / estimating_manage / quoting_manage_templates.
SALES_403_CASES = [
    ("post", "/contract-faq/tc-version"),
    ("post", "/price-book/items"),
    ("put", "/price-book/items/1"),
    ("post", "/price-book/versions"),
    ("put", "/quoting/templates/1"),
    ("delete", "/quoting/templates/1"),
]


@pytest.mark.parametrize("method,path", SALES_403_CASES, ids=[f"{m}:{p}" for m, p in SALES_403_CASES])
def test_sales_insufficient_role_returns_403(sales_client, method, path):
    r = _call(sales_client, method, path, {})
    assert r.status_code == 403, f"{method} {path}: expected 403, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# 404 nonexistent resource id -- authed (admin), schema-valid body
# ---------------------------------------------------------------------------

def test_update_contact_404_unknown(admin_client):
    r = admin_client.put("/quoting/contacts/999999", json={"name": "X"}, headers=AUTH)
    assert r.status_code == 404


def test_delete_property_404_unknown(admin_client):
    r = admin_client.delete("/quoting/properties/999999", headers=AUTH)
    assert r.status_code == 404


def test_record_payment_404_unknown_invoice(admin_client):
    r = admin_client.post("/invoices/999999/payments",
                          json={"amount": "10.00", "idempotency_key": "abcdefgh"},
                          headers=AUTH)
    assert r.status_code == 404


def test_update_price_book_item_404_unknown(admin_client):
    r = admin_client.put("/price-book/items/999999", json={"name": "X"}, headers=AUTH)
    assert r.status_code == 404


def test_create_proposal_from_quote_404_unknown_contract(admin_client):
    r = admin_client.post("/quoting/proposals/from-quote/NOPE-CONTRACT", json={}, headers=AUTH)
    assert r.status_code == 404


def test_update_proposal_404_unknown(admin_client):
    r = admin_client.put("/quoting/proposals/999999", json={"title": "X"}, headers=AUTH)
    assert r.status_code == 404


def test_send_proposal_404_unknown(admin_client):
    r = admin_client.post("/quoting/proposals/999999/send", json={}, headers=AUTH)
    assert r.status_code == 404


def test_revise_proposal_404_unknown(admin_client):
    r = admin_client.post("/quoting/proposals/999999/revise", json={}, headers=AUTH)
    assert r.status_code == 404


def test_update_template_404_unknown(admin_client):
    r = admin_client.put("/quoting/templates/999999", json={"name": "X"}, headers=AUTH)
    assert r.status_code == 404


def test_delete_template_404_unknown(admin_client):
    r = admin_client.delete("/quoting/templates/999999", headers=AUTH)
    assert r.status_code == 404


def test_preview_template_404_unknown(admin_client):
    r = admin_client.post("/quoting/templates/999999/preview", json={}, headers=AUTH)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 422 missing required field / wrong type -- authed (admin). A path id doesn't
# need to be real: pydantic body validation runs before the handler's own
# lookup, so bad-body cases 422 regardless of what id is in the URL.
# ---------------------------------------------------------------------------

WRONG_TYPE_CASES = [
    ("post", "/quoting/customers", {"display_name": ["not", "a", "string"]}),
    ("post", "/quoting/customers/1/contacts", {"name": ["bad"]}),
    ("put", "/quoting/contacts/1", {"name": ["bad"]}),
    ("post", "/quoting/customers/1/properties", {"street": ["bad"], "city": "Miami"}),
    ("put", "/quoting/properties/1", {"city": ["bad"]}),
    ("post", "/contract-faq/ai-prompts", {"include_existing_faqs": ["bad"]}),
    ("put", "/contract-faq/1", {"question": ["bad"]}),
    ("post", "/quoting/proposals/from-quote/X", {"title": ["bad"]}),
    ("put", "/quoting/proposals/1", {"title": ["bad"]}),
    ("post", "/quoting/proposals/1/revise", {"title": ["bad"]}),
    ("put", "/quoting/templates/1", {"name": ["bad"]}),
    ("post", "/price-book/versions", {"activate": ["bad"]}),
]


@pytest.mark.parametrize("method,path,body", WRONG_TYPE_CASES,
                         ids=[f"{m}:{p}" for m, p, _ in WRONG_TYPE_CASES])
def test_wrong_type_returns_422(admin_client, method, path, body):
    r = _call(admin_client, method, path, body)
    assert r.status_code == 422, f"{method} {path}: expected 422, got {r.status_code}: {r.text}"


def test_create_customer_wrong_type_422(admin_client):
    r = admin_client.post("/quoting/customers", json={"display_name": ["bad"]}, headers=AUTH)
    assert r.status_code == 422


def test_generate_missing_tc_text_422(admin_client):
    r = admin_client.post("/contract-faq/generate", json={"count": 2}, headers=AUTH)
    assert r.status_code == 422


def test_generate_wrong_type_count_422(admin_client):
    r = admin_client.post("/contract-faq/generate",
                          json={"tc_text": "x" * 150, "count": ["bad"]}, headers=AUTH)
    assert r.status_code == 422


def test_save_tc_version_missing_tc_text_422(admin_client):
    r = admin_client.post("/contract-faq/tc-version", json={"version_tag": "foo"}, headers=AUTH)
    assert r.status_code == 422


def test_save_tc_version_wrong_type_422(admin_client):
    r = admin_client.post("/contract-faq/tc-version", json={"tc_text": ["bad"]}, headers=AUTH)
    assert r.status_code == 422


def test_extract_pdf_missing_file_422(admin_client):
    r = admin_client.post("/contract-faq/extract-pdf", headers=AUTH)
    assert r.status_code == 422


def test_issue_invoice_missing_required_field_422(admin_client):
    r = admin_client.post("/invoices", json={
        "job_id": 1, "milestone_pct": "0.30",
        "scopes": [{"description": "d", "scope_value": "100.00"}],
    }, headers=AUTH)
    assert r.status_code == 422


def test_issue_invoice_wrong_type_422(admin_client):
    r = admin_client.post("/invoices", json={
        "job_id": ["bad"], "customer_id": 1, "milestone_pct": "0.30",
        "scopes": [{"description": "d", "scope_value": "100.00"}],
    }, headers=AUTH)
    assert r.status_code == 422


def test_record_payment_missing_idempotency_key_422(admin_client):
    r = admin_client.post("/invoices/1/payments", json={"amount": "10.00"}, headers=AUTH)
    assert r.status_code == 422


def test_record_payment_wrong_type_amount_422(admin_client):
    r = admin_client.post("/invoices/1/payments",
                          json={"amount": ["bad"], "idempotency_key": "abcdefgh"}, headers=AUTH)
    assert r.status_code == 422


def test_create_price_book_item_missing_name_422(admin_client):
    r = admin_client.post("/price-book/items", json={"unit": "box"}, headers=AUTH)
    assert r.status_code == 422


def test_create_price_book_item_wrong_type_422(admin_client):
    r = admin_client.post("/price-book/items", json={"name": ["bad"]}, headers=AUTH)
    assert r.status_code == 422


def test_update_price_book_item_missing_name_422(admin_client):
    """name has no default in ItemUpsert, so PUT (which reuses the full create schema)
    still requires it even though only some fields are conceptually being changed."""
    r = admin_client.put("/price-book/items/1", json={"unit": "box"}, headers=AUTH)
    assert r.status_code == 422


def test_create_pricing_config_missing_branch_422(admin_client):
    r = admin_client.post("/estimator/configs", json={"config": {}}, headers=AUTH)
    assert r.status_code == 422


def test_create_pricing_config_wrong_type_config_422(admin_client):
    r = admin_client.post("/estimator/configs",
                          json={"branch": "miami", "config": "notadict"}, headers=AUTH)
    assert r.status_code == 422


def test_create_proposal_missing_quote_snapshot_422(admin_client):
    r = admin_client.post("/quoting/proposals", json={
        "customer_id": 1, "property_id": 1, "title": "T",
    }, headers=AUTH)
    assert r.status_code == 422


def test_create_proposal_wrong_type_customer_id_422(admin_client):
    r = admin_client.post("/quoting/proposals", json={
        "customer_id": "abc", "property_id": 1, "title": "T", "quote_snapshot": {},
    }, headers=AUTH)
    assert r.status_code == 422


def test_create_template_missing_html_body_422(admin_client):
    r = admin_client.post("/quoting/templates", json={"name": "T"}, headers=AUTH)
    assert r.status_code == 422


def test_create_template_wrong_type_422(admin_client):
    r = admin_client.post("/quoting/templates",
                          json={"name": ["bad"], "html_body": "<p/>"}, headers=AUTH)
    assert r.status_code == 422
