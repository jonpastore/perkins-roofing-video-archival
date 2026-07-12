"""Behavioral tests for api/routes/contract_faq.py."""
import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.contract_faq import router
from app.models import ContractFaqEntry, SessionLocal, TcVersion, init_db


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(_make_app())


def _sales_client():
    set_verifier(lambda token: {"uid": "u2", "email": "sales@x.com", "role": "sales"})
    return TestClient(_make_app())


AUTH = {"Authorization": "Bearer tok"}

TC_TEXT = (
    "Payment is due within 30 days of invoice date. "
    "All roofing work is warranted for one year from the date of completion. "
    "The homeowner must provide clear and unobstructed access to the property at all times. "
    "Any changes to the scope of work must be approved in writing by both parties. "
    "Perkins Roofing is not responsible for pre-existing structural damage discovered during work. "
    "A deposit of 30 percent is required before work commences. "
    "Final payment is due upon project completion and inspection. "
    "The contractor reserves the right to stop work if payment is not received as agreed."
)

_CANNED_ITEMS = [
    {
        "q": "When is payment due?",
        "a": "Payment is due within 30 days of the invoice date.",
        "quote": "Payment is due within 30 days of invoice date",
    },
    {
        "q": "Is the work warranted?",
        "a": "Yes, roofing work is covered for one year.",
        "quote": "warranted for one year from the date of completion",
    },
]
_CANNED_JSON = json.dumps(_CANNED_ITEMS)

_HALLUCINATED_ITEM = {
    "q": "Does Perkins offer a lifetime guarantee?",
    "a": "Yes, all work is guaranteed for life.",
    "quote": "all work is guaranteed for the lifetime of the homeowner",
}

_DENYLIST_ITEM = {
    "q": "Is the work bullshit?",
    "a": "No it is not.",
    "quote": "Payment is due within 30 days of invoice date",
}


def setup_module(module):
    init_db()
    with SessionLocal() as db:
        db.query(ContractFaqEntry).delete()
        db.query(TcVersion).delete()
        db.commit()


def teardown_module(module):
    with SessionLocal() as db:
        db.query(ContractFaqEntry).delete()
        db.query(TcVersion).delete()
        db.commit()


@pytest.fixture(autouse=True)
def _clean_entries():
    with SessionLocal() as db:
        db.query(ContractFaqEntry).delete()
        db.query(TcVersion).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ContractFaqEntry).delete()
        db.query(TcVersion).delete()
        db.commit()


# POST /contract-faq/generate

def test_generate_happy_path(monkeypatch):
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat", lambda prompt, **kw: _CANNED_JSON)
    r = _admin_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT, "count": 2}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["generated"] == 2 and data["rejected_grounding"] == 0 and data["rejected_safety"] == 0


def test_generate_stores_question_answer_quote(monkeypatch):
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat", lambda prompt, **kw: _CANNED_JSON)
    _admin_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT}, headers=AUTH)
    with SessionLocal() as db:
        entries = db.query(ContractFaqEntry).order_by(ContractFaqEntry.id).all()
    assert entries[0].question == "When is payment due?"
    assert entries[0].quote == "Payment is due within 30 days of invoice date"


def test_generate_grounding_rejection(monkeypatch):
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat", lambda prompt, **kw: json.dumps(_CANNED_ITEMS + [_HALLUCINATED_ITEM]))
    r = _admin_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["generated"] == 2 and r.json()["rejected_grounding"] == 1


def test_generate_denylist_rejection(monkeypatch):
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat", lambda prompt, **kw: json.dumps(_CANNED_ITEMS + [_DENYLIST_ITEM]))
    r = _admin_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["rejected_safety"] == 1 and r.json()["generated"] == 2


def test_generate_rejects_empty_tc_text():
    assert _admin_client().post("/contract-faq/generate", json={"tc_text": ""}, headers=AUTH).status_code == 422


def test_generate_rejects_short_tc_text():
    r = _admin_client().post("/contract-faq/generate", json={"tc_text": "Too short."}, headers=AUTH)
    assert r.status_code == 422


def test_generate_caps_count_at_20(monkeypatch):
    import app.llm as llm_mod
    captured = {}
    def fake_chat(prompt, **kw):
        captured["prompt"] = prompt
        return _CANNED_JSON
    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    r = _admin_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT, "count": 999}, headers=AUTH)
    assert r.status_code == 200 and "20" in captured["prompt"] and "999" not in captured["prompt"]


def test_generate_count_min_1(monkeypatch):
    import app.llm as llm_mod
    captured = {}
    def fake_chat(prompt, **kw):
        captured["prompt"] = prompt
        return _CANNED_JSON
    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    r = _admin_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT, "count": 0}, headers=AUTH)
    assert r.status_code == 200 and "1" in captured["prompt"]


def test_generate_requires_manage_articles():
    assert _sales_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT}, headers=AUTH).status_code == 403


def test_generate_requires_auth():
    assert _admin_client().post("/contract-faq/generate", json={"tc_text": TC_TEXT}).status_code == 401


# POST /contract-faq/extract-pdf

def test_extract_pdf_upload(monkeypatch):
    import api.routes.contract_faq as mod
    monkeypatch.setattr(mod, "_extract_pdf_text", lambda data: TC_TEXT)
    r = _admin_client().post(
        "/contract-faq/extract-pdf",
        files={"file": ("contract.pdf", b"%PDF fake", "application/pdf")},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == TC_TEXT


def test_extract_pdf_requires_manage_articles():
    r = _sales_client().post(
        "/contract-faq/extract-pdf",
        files={"file": ("contract.pdf", b"%PDF fake", "application/pdf")},
        headers=AUTH,
    )
    assert r.status_code == 403



# T&C version source endpoints

def test_save_tc_version_and_load_latest(monkeypatch):
    import api.routes.contract_faq as mod

    saved = {}
    def fake_save(**kw):
        saved["args"] = kw
        return "gs://bucket/tc.txt", None
    monkeypatch.setattr(mod, "_save_tc_artifacts", fake_save)
    monkeypatch.setattr(mod, "_read_gcs_text", lambda uri: TC_TEXT)

    c = _admin_client()
    r = c.post("/contract-faq/tc-version", json={"tc_text": TC_TEXT, "version_tag": "current terms"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["version_tag"] == "current-terms"
    assert saved["args"]["tc_text"] == TC_TEXT

    latest = c.get("/contract-faq/tc-version/latest", headers=AUTH)
    assert latest.status_code == 200
    assert latest.json()["tc_text"] == TC_TEXT
    assert latest.json()["chars"] == len(TC_TEXT)


def test_extract_pdf_save_creates_tc_version(monkeypatch):
    import api.routes.contract_faq as mod

    monkeypatch.setattr(mod, "_extract_pdf_text", lambda data: TC_TEXT)
    monkeypatch.setattr(mod, "_save_tc_artifacts", lambda **kw: ("gs://bucket/proposal.txt", "gs://bucket/proposal.pdf"))
    r = _admin_client().post(
        "/contract-faq/extract-pdf?save=true&version_tag=josh proposal",
        files={"file": ("contract.pdf", b"%PDF fake", "application/pdf")},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["text"] == TC_TEXT
    assert data["tc_version"]["version_tag"] == "josh-proposal"
    with SessionLocal() as db:
        assert db.query(TcVersion).count() == 1


def test_ai_prompts_falls_back_to_latest_saved_tc(monkeypatch):
    import api.routes.contract_faq as mod

    monkeypatch.setattr(mod, "_read_gcs_text", lambda uri: TC_TEXT)
    with SessionLocal() as db:
        db.add(TcVersion(version_tag="v1", content_gcs="gs://bucket/tc.txt", effective_at=datetime.utcnow()))
        db.commit()
    r = _admin_client().post("/contract-faq/ai-prompts", json={"tc_text": ""}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert TC_TEXT in r.json()["user_prompt"]

# POST /contract-faq/ai-prompts

def test_ai_prompts_include_existing_faq():
    _seed_entries(1)
    r = _admin_client().post("/contract-faq/ai-prompts", json={"tc_text": TC_TEXT}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "system_prompt" in data and "user_prompt" in data
    assert "Question 1?" in data["user_prompt"]


def test_ai_prompts_requires_read_role():
    assert _sales_client().post("/contract-faq/ai-prompts", json={"tc_text": TC_TEXT}, headers=AUTH).status_code == 403


# GET /contract-faq

def _seed_entries(n=2):
    now = datetime.utcnow()
    with SessionLocal() as db:
        for i in range(n):
            db.add(ContractFaqEntry(
                question=f"Question {i+1}?", answer=f"Answer {i+1}.", quote=f"quote {i+1}",
                status="draft" if i % 2 == 0 else "approved", created_at=now,
            ))
        db.commit()


def test_list_returns_entries():
    _seed_entries(3)
    r = _admin_client().get("/contract-faq", headers=AUTH)
    assert r.status_code == 200 and len(r.json()) == 3


def test_list_entry_shape():
    _seed_entries(1)
    item = _admin_client().get("/contract-faq", headers=AUTH).json()[0]
    for key in ("id", "question", "answer", "quote", "status", "created_at"):
        assert key in item


def test_list_status_filter():
    _seed_entries(4)
    items = _admin_client().get("/contract-faq?status=approved", headers=AUTH).json()
    assert all(i["status"] == "approved" for i in items)


def test_list_sales_forbidden():
    """H3: list is gated on kb_contract_faq_read (web_admin/admin) — sales must NOT
    see contract-FAQ entries (drafts are pre-approval legal text)."""
    _seed_entries(1)
    assert _sales_client().get("/contract-faq", headers=AUTH).status_code == 403


def test_list_requires_auth():
    assert _admin_client().get("/contract-faq").status_code == 401


def test_list_empty_when_no_entries():
    r = _admin_client().get("/contract-faq", headers=AUTH)
    assert r.status_code == 200 and r.json() == []


# PUT /contract-faq/{id}

def _seed_one() -> int:
    with SessionLocal() as db:
        e = ContractFaqEntry(
            question="Original question?", answer="Original answer.",
            quote="original quote", status="draft", created_at=datetime.utcnow(),
        )
        db.add(e)
        db.commit()
        return e.id


def test_update_question():
    eid = _seed_one()
    r = _admin_client().put(f"/contract-faq/{eid}", json={"question": "Updated question?"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["question"] == "Updated question?"


def test_update_answer():
    eid = _seed_one()
    r = _admin_client().put(f"/contract-faq/{eid}", json={"answer": "Updated answer."}, headers=AUTH)
    assert r.status_code == 200 and r.json()["answer"] == "Updated answer."


def test_update_approve():
    eid = _seed_one()
    r = _admin_client().put(f"/contract-faq/{eid}", json={"status": "approved"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_update_invalid_status():
    eid = _seed_one()
    assert _admin_client().put(f"/contract-faq/{eid}", json={"status": "published"}, headers=AUTH).status_code == 422


def test_update_404_unknown():
    assert _admin_client().put("/contract-faq/999999", json={"question": "Q?"}, headers=AUTH).status_code == 404


def test_update_requires_manage_articles():
    eid = _seed_one()
    assert _sales_client().put(f"/contract-faq/{eid}", json={"status": "approved"}, headers=AUTH).status_code == 403


# DELETE /contract-faq/{id}

def test_delete_entry():
    eid = _seed_one()
    r = _admin_client().delete(f"/contract-faq/{eid}", headers=AUTH)
    assert r.status_code == 200 and r.json() == {"deleted": True}
    with SessionLocal() as db:
        assert db.query(ContractFaqEntry).filter(ContractFaqEntry.id == eid).first() is None


def test_delete_404_unknown():
    assert _admin_client().delete("/contract-faq/999999", headers=AUTH).status_code == 404


def test_delete_requires_manage_articles():
    eid = _seed_one()
    assert _sales_client().delete(f"/contract-faq/{eid}", headers=AUTH).status_code == 403


# GET /contract-faq/jsonld

def _seed_mixed():
    now = datetime.utcnow()
    with SessionLocal() as db:
        db.add(ContractFaqEntry(question="Approved Q?", answer="Approved A.", quote="q",
                                status="approved", created_at=now))
        db.add(ContractFaqEntry(question="Draft Q?", answer="Draft A.", quote="q", status="draft", created_at=now))
        db.commit()


def test_jsonld_returns_faqpage():
    _seed_mixed()
    r = _admin_client().get("/contract-faq/jsonld", headers=AUTH)
    assert r.status_code == 200 and r.json()["@type"] == "FAQPage" and r.json()["@context"] == "https://schema.org"


def test_jsonld_only_approved():
    _seed_mixed()
    entities = _admin_client().get("/contract-faq/jsonld", headers=AUTH).json()["mainEntity"]
    assert len(entities) == 1 and entities[0]["name"] == "Approved Q?"


def test_jsonld_empty_when_no_approved():
    _seed_one()
    r = _admin_client().get("/contract-faq/jsonld", headers=AUTH)
    assert r.status_code == 200 and r.json()["mainEntity"] == []


def test_jsonld_sales_forbidden():
    """H3: jsonld gated on kb_contract_faq_read — sales must not read it."""
    _seed_mixed()
    assert _sales_client().get("/contract-faq/jsonld", headers=AUTH).status_code == 403


def test_jsonld_requires_auth():
    assert _admin_client().get("/contract-faq/jsonld").status_code == 401


def test_generate_dedupes_existing_questions(monkeypatch):
    """M1: re-running generate must not stack duplicate drafts for the same question."""
    import app.llm as llm_mod
    tc = ("Payment is due within 30 days of invoice. Deposits are non-refundable "
          "to the customer once work has been scheduled and materials ordered.")
    canned = ('[{"q": "When is payment due?", "a": "Within 30 days of invoice.", '
              '"quote": "Payment is due within 30 days of invoice"}]')
    monkeypatch.setattr(llm_mod, "chat", lambda prompt: canned)
    c = _admin_client()
    r1 = c.post("/contract-faq/generate", json={"tc_text": tc}, headers=AUTH)
    assert r1.status_code == 200 and r1.json()["generated"] == 1
    r2 = c.post("/contract-faq/generate", json={"tc_text": tc}, headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["generated"] == 0, "duplicate question was inserted twice"
    assert r2.json().get("skipped_duplicates", 0) == 1
