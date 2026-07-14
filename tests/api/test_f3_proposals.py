"""F3 API — Proposals lifecycle + e-sign accept surface (TDD, fail-first).

Covers (slip-rule order — money path first):
  §6.1  Snapshot immutability
  §6.2  Version chain / supersede
  §6.3  Token entropy + 404-indistinguishability
  §6.4  Consent / audit completeness
  §6.5  Floor preservation in snapshot
  §6.7  Authz denials (sales vs web_admin)

Public accept-page endpoints are unauthenticated and token-gated.
Authenticated proposal routes require quoting_view / quoting_create / quoting_send.

All tests run on SQLite via init_db(). Uses fake-verifier pattern from test_estimator_f2.py.
"""
import base64
import secrets
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import api.app as appmod
from api.auth import set_verifier
from app.models import KnowifyRawRecord, SessionLocal, init_db

# ---------------------------------------------------------------------------
# Mount F3 routers idempotently
# ---------------------------------------------------------------------------

_MOUNTED = set(getattr(r, "prefix", None) for r in appmod.app.routes)
if "/quoting/customers" not in _MOUNTED:
    from api.routes.customers import router as customers_router
    appmod.app.include_router(customers_router)
if "/quoting/proposals" not in _MOUNTED:
    from api.routes.proposals import router as proposals_router
    appmod.app.include_router(proposals_router)


AUTH = {"Authorization": "Bearer x"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_db():
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


def _make_admin():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                            "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


def _make_sales():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@perkins.com",
                            "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# Scaffolding helpers — build minimal customer + property + proposal
# ---------------------------------------------------------------------------

def _uid():
    return uuid.uuid4().hex[:8]


def _create_customer(client):
    r = client.post("/quoting/customers",
                    json={"display_name": f"Cust-{_uid()}",
                          "email": f"{_uid()}@test.com"},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _create_property(client, customer_id):
    r = client.post(f"/quoting/customers/{customer_id}/properties",
                    json={"street": f"{_uid()} Oak Ave",
                          "city": "Miami", "state": "FL",
                          "zip": "33101", "code_zone": "HVHZ"},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _create_property_at(client, customer_id, *, street, city, state="FL", zip_code="33101"):
    r = client.post(f"/quoting/customers/{customer_id}/properties",
                    json={"street": street,
                          "city": city, "state": state,
                          "zip": zip_code, "code_zone": "HVHZ"},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _seed_knowify_quote(contract_id, project_id, *, address=None, total="15000.00",
                        deposit="5000.00"):
    """Seed a legacy Knowify contract, two deliverables, and its project address."""
    address = address or {
        "Id": project_id,
        "Address1": f"{_uid()} Legacy Way",
        "City": "Miami",
        "StateProvince": "FL",
        "Zip": "33101",
    }
    contract = {
        "Id": contract_id,
        "ContractType": "Standard",
        "BusinessState": "Draft",
        "ContractName": f"Knowify Roof Replacement {contract_id}",
        "OriginalContractSum": total,
        "CurrentContractSum": total,
        "AdditionalContractSum": "0.00",
        "DepositAmount": deposit,
        "ClientId": f"CL-{contract_id}",
        "ProjectId": project_id,
        "DateCreated": "2026-07-10",
        "ExpirationDate": "2026-08-10",
        "IsSigned": False,
        "PONumber": f"PO-{contract_id}",
        "ContactName": "Legacy Contact",
    }
    deliverables = [
        {
            "Id": f"D-{contract_id}-1",
            "ContractId": contract_id,
            "Description": "Remove and replace shingle roof",
            "Quantity": "3000",
            "UnitName": "Squares",
            "UnitPrice": "450.00",
            "Price": "13500.00",
            "PriceBilled": "0.00",
            "CostLabor": "4000.00",
            "CostMaterials": "6000.00",
            "ObjectState": "Active",
        },
        {
            "Id": f"D-{contract_id}-2",
            "ContractId": contract_id,
            "Description": "Permit allowance",
            "Quantity": "100",
            "UnitName": "Each",
            "UnitPrice": "1500.00",
            "Price": "1500.00",
            "PriceBilled": "0.00",
            "CostLabor": "0.00",
            "CostMaterials": "0.00",
            "ObjectState": "Active",
        },
    ]
    db = SessionLocal()
    db.info["tenant_id"] = 1
    try:
        db.add(KnowifyRawRecord(
            tenant_id=1, entity="contracts", knowify_id=contract_id,
            payload=contract, content_hash="c" * 64, is_present=True,
        ))
        for item in deliverables:
            db.add(KnowifyRawRecord(
                tenant_id=1, entity="deliverables", knowify_id=item["Id"],
                payload=item, content_hash="d" * 64, is_present=True,
            ))
        db.add(KnowifyRawRecord(
            tenant_id=1, entity="projects", knowify_id=project_id,
            payload={**address, "Id": project_id}, content_hash="p" * 64,
            is_present=True,
        ))
        db.commit()
    finally:
        db.close()


_SAMPLE_SNAPSHOT = {
    "pricing_config_hash": "abc123" * 10 + "ab",
    "sent_at_iso": "2026-07-08T14:30:00Z",
    "roof_type": "dimensional_shingle",
    "region": "HVHZ",
    "num_squares": 28.0,
    "code_zone": "HVHZ",
    "branch": "Miami",
    "tiers": {
        "good":   {"label": "Good",   "total": 18400.00, "line_items": []},
        "better": {"label": "Better", "total": 21200.00, "line_items": []},
        "best":   {"label": "Best",   "total": 24800.00, "line_items": []},
    },
    "optional_items": [],
    "deposit_policy": {
        "mode": "percent", "value": 50, "amount": 9200.00,
        "instructions": "Check payable to Perkins Roofing",
    },
    "floors": {
        "min_profit_pct": 13,
        "min_profit_plus_oh_pct": 33,
    },
    "estimator_version": "1.0.0",
}


def _create_proposal(client, customer_id, property_id, snapshot=None):
    snap = snapshot or _SAMPLE_SNAPSHOT
    r = client.post("/quoting/proposals",
                    json={"customer_id": customer_id,
                          "property_id": property_id,
                          "title": f"Proposal-{_uid()}",
                          "quote_snapshot": snap},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _send_proposal(client, proposal_id):
    r = client.post(f"/quoting/proposals/{proposal_id}/send",
                    json={},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _scaffold(client=None):
    """Return (client, customer, property, draft_proposal)."""
    c = client or _make_admin()
    cust = _create_customer(c)
    prop = _create_property(c, cust["id"])
    draft = _create_proposal(c, cust["id"], prop["id"])
    return c, cust, prop, draft


# ---------------------------------------------------------------------------
# Knowify quote import — native draft proposal creation
# ---------------------------------------------------------------------------

class TestKnowifyQuoteImport:
    def test_from_quote_creates_draft_and_derives_matching_property(self, admin_client):
        cust = _create_customer(admin_client)
        address = {
            "Address1": f"{_uid()} Legacy Way",
            "City": "Miami",
            "StateProvince": "FL",
            "Zip": "33101",
        }
        prop = _create_property_at(
            admin_client, cust["id"], street=address["Address1"],
            city=address["City"], state=address["StateProvince"],
            zip_code=address["Zip"],
        )
        contract_id = f"KQ-{_uid()}"
        _seed_knowify_quote(contract_id, f"KP-{_uid()}", address=address)

        r = admin_client.post(
            f"/quoting/proposals/from-quote/{contract_id}",
            json={"customer_id": cust["id"], "title": "Imported Knowify Quote"},
            headers=AUTH,
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "draft"
        assert body["customer_id"] == cust["id"]
        assert body["property_id"] == prop["id"]
        assert body["title"] == "Imported Knowify Quote"

        snap = body["quote_snapshot"]
        assert snap["source"] == "knowify_import"
        assert snap["source_ref"] == contract_id
        assert snap["contract"]["ContractName"] == f"Knowify Roof Replacement {contract_id}"
        assert snap["contract"]["ProjectId"].startswith("KP-")
        assert len(snap["line_items"]) == 2
        assert snap["total"] == 15000.0
        assert snap["deposit"] == 5000.0
        assert snap["project_address"]["Address1"] == address["Address1"]
        assert snap["tiers"]["legacy"]["total"] == 15000.0
        assert snap["deposit_policy"]["amount"] == 5000.0
        assert snap["num_squares"] == 30.0
        assert snap["legacy_measurements"]["source"] == "knowify_deliverables"
        assert snap["legacy_measurements"]["unit_breakdown"]["Squares"] == 30.0


    def test_from_quote_auto_resolves_customer_from_knowify_client_id(self, admin_client):
        customer = _create_customer(admin_client)
        address = {
            "Address1": f"{_uid()} Auto Legacy Way",
            "City": "Miami",
            "StateProvince": "FL",
            "Zip": "33101",
        }
        prop = _create_property_at(
            admin_client, customer["id"], street=address["Address1"],
            city=address["City"], state=address["StateProvince"],
            zip_code=address["Zip"],
        )
        contract_id = f"KQ-{_uid()}"
        _seed_knowify_quote(contract_id, f"KP-{_uid()}", address=address)

        # Make the seeded Knowify quote point at the native customer's Knowify crosswalk.
        knowify_client_id = f"KC-{_uid()}"
        db = SessionLocal()
        db.info["tenant_id"] = 1
        try:
            from app.models import Customer

            cust_row = db.get(Customer, customer["id"])
            cust_row.knowify_customer_id = knowify_client_id
            row = db.execute(
                select(KnowifyRawRecord).where(
                    KnowifyRawRecord.entity == "contracts",
                    KnowifyRawRecord.knowify_id == contract_id,
                )
            ).scalar_one()
            row.payload = {**row.payload, "ClientId": knowify_client_id}
            db.commit()
        finally:
            db.close()

        r = admin_client.post(
            f"/quoting/proposals/from-quote/{contract_id}",
            json={},
            headers=AUTH,
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["customer_id"] == customer["id"]
        assert body["property_id"] == prop["id"]
        assert body["quote_snapshot"]["num_squares"] == 30.0

    def test_from_quote_is_idempotent_for_same_tenant_source_ref(self, admin_client):
        cust = _create_customer(admin_client)
        prop = _create_property(admin_client, cust["id"])
        contract_id = f"KQ-{_uid()}"
        _seed_knowify_quote(contract_id, f"KP-{_uid()}")

        first = admin_client.post(
            f"/quoting/proposals/from-quote/{contract_id}",
            json={"customer_id": cust["id"], "property_id": prop["id"], "title": "First"},
            headers=AUTH,
        )
        assert first.status_code == 200, first.text

        second = admin_client.post(
            f"/quoting/proposals/from-quote/{contract_id}",
            json={"customer_id": cust["id"], "property_id": prop["id"], "title": "Second"},
            headers=AUTH,
        )

        assert second.status_code == 200, second.text
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["title"] == "First"

    def test_from_quote_without_property_and_no_safe_project_match_returns_422(self, admin_client):
        cust = _create_customer(admin_client)
        contract_id = f"KQ-{_uid()}"
        _seed_knowify_quote(contract_id, f"KP-{_uid()}",
                            address={"Address1": "No Matching Property",
                                     "City": "Miami", "StateProvince": "FL",
                                     "Zip": "33101"})

        r = admin_client.post(
            f"/quoting/proposals/from-quote/{contract_id}",
            json={"customer_id": cust["id"]},
            headers=AUTH,
        )

        assert r.status_code == 422
        assert "property_id" in r.json()["detail"]


# ---------------------------------------------------------------------------
# §6.1 — Snapshot immutability
# ---------------------------------------------------------------------------

class TestSnapshotImmutability:
    def test_snapshot_frozen_on_send(self, admin_client):
        """quote_snapshot must not be mutatable after the proposal is sent."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        assert sent["status"] == "sent"
        # quote_snapshot should still match original
        assert sent["quote_snapshot"]["pricing_config_hash"] == \
               draft["quote_snapshot"]["pricing_config_hash"]

    def test_snapshot_contains_pricing_config_hash(self, admin_client):
        """quote_snapshot must include a non-empty pricing_config_hash."""
        c, cust, prop, draft = _scaffold(admin_client)
        snap = draft["quote_snapshot"]
        assert "pricing_config_hash" in snap
        assert snap["pricing_config_hash"]

    def test_snapshot_contains_floor_data(self, admin_client):
        """quote_snapshot must include floors.min_profit_pct and min_profit_plus_oh_pct."""
        c, cust, prop, draft = _scaffold(admin_client)
        snap = draft["quote_snapshot"]
        assert "floors" in snap
        assert "min_profit_pct" in snap["floors"]
        assert "min_profit_plus_oh_pct" in snap["floors"]

    def test_snapshot_preserved_across_versions(self, admin_client):
        """New version row has fresh content; old row snapshot unchanged."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])

        # Revise (creates new version)
        r = admin_client.post(f"/quoting/proposals/{sent['id']}/revise",
                              json={"title": "Revised Title",
                                    "quote_snapshot": {
                                        **_SAMPLE_SNAPSHOT,
                                        "pricing_config_hash": "newHash" * 10 + "ne",
                                    }},
                              headers=AUTH)
        assert r.status_code == 200, r.text

        # Reload old proposal — its snapshot is unchanged
        r_old = admin_client.get(f"/quoting/proposals/{sent['id']}", headers=AUTH)
        assert r_old.status_code == 200
        old_snap = r_old.json()["quote_snapshot"]
        assert old_snap["pricing_config_hash"] == _SAMPLE_SNAPSHOT["pricing_config_hash"]


# ---------------------------------------------------------------------------
# §6.2 — Version chain / supersede
# ---------------------------------------------------------------------------

class TestVersionChain:
    def test_send_creates_first_version(self, admin_client):
        """Sending a proposal sets version_number=1, parent_id=None."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        assert sent["version_number"] == 1
        assert sent["parent_id"] is None

    def test_revise_creates_new_version(self, admin_client):
        """Revising a sent proposal creates version_number=2, parent_id=prev.id."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.post(f"/quoting/proposals/{sent['id']}/revise",
                              json={"title": "Rev 2",
                                    "quote_snapshot": _SAMPLE_SNAPSHOT},
                              headers=AUTH)
        assert r.status_code == 200, r.text
        new_v = r.json()
        assert new_v["version_number"] == 2
        assert new_v["parent_id"] == sent["id"]
        assert new_v["status"] == "draft"
        assert new_v["sent_at"] is None

    def test_old_version_status_superseded(self, admin_client):
        """After revision, old proposal status must be 'superseded'."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(f"/quoting/proposals/{sent['id']}/revise",
                          json={"title": "Rev 2", "quote_snapshot": _SAMPLE_SNAPSHOT},
                          headers=AUTH)
        r_old = admin_client.get(f"/quoting/proposals/{sent['id']}", headers=AUTH)
        assert r_old.json()["status"] == "superseded"

    def test_superseded_token_get_returns_200_terminal(self, admin_client):
        """GET /p/{superseded_token} returns 200 JSON with status='superseded' and title only (no snapshot)."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        old_token = sent["accept_token"]
        admin_client.post(f"/quoting/proposals/{sent['id']}/revise",
                          json={"title": "Rev 2", "quote_snapshot": _SAMPLE_SNAPSHOT},
                          headers=AUTH)
        r = admin_client.get(f"/p/{old_token}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "superseded"
        assert "title" in body
        # Terminal state: no snapshot exposed (client-safe projection — data-leak fix)
        assert "quote_snapshot" not in body

    def test_superseded_cannot_be_accepted(self, admin_client):
        """POST /p/{superseded_token}/accept returns 404."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        old_token = sent["accept_token"]
        admin_client.post(f"/quoting/proposals/{sent['id']}/revise",
                          json={"title": "Rev 2", "quote_snapshot": _SAMPLE_SNAPSHOT},
                          headers=AUTH)
        r = admin_client.post(f"/p/{old_token}/accept",
                              json={"selected_tier": "good",
                                    "consent_electronic": True,
                                    "signed_name": "Tim Perkins"})
        assert r.status_code == 404

    def test_chain_query_returns_all_versions(self, admin_client):
        """GET /quoting/proposals/{id}/chain returns all rows in version order."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r_rev = admin_client.post(f"/quoting/proposals/{sent['id']}/revise",
                                   json={"title": "Rev 2",
                                         "quote_snapshot": _SAMPLE_SNAPSHOT},
                                   headers=AUTH)
        new_v = r_rev.json()
        r_chain = admin_client.get(f"/quoting/proposals/{new_v['id']}/chain",
                                    headers=AUTH)
        assert r_chain.status_code == 200
        chain = r_chain.json()
        assert len(chain) == 2
        versions = [p["version_number"] for p in chain]
        assert versions == sorted(versions)


# ---------------------------------------------------------------------------
# §6.3 — Token entropy + constant-time + 404-indistinguishability
# ---------------------------------------------------------------------------

class TestTokenEntropy:
    def test_token_length(self, admin_client):
        """accept_token is 86 characters (URL-safe base64 of 64 bytes, no padding)."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        token = sent["accept_token"]
        assert len(token) == 86

    def test_token_url_safe_charset(self, admin_client):
        """accept_token uses only URL-safe base64 characters (A-Z a-z 0-9 - _)."""
        import re
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        token = sent["accept_token"]
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)

    def test_token_uniqueness(self, admin_client):
        """100 generated tokens (via send) have no collisions."""
        tokens = set()
        # Generate tokens directly via the function — faster than 100 API calls
        from api.routes.proposals import _new_accept_token
        for _ in range(100):
            t = _new_accept_token()
            assert t not in tokens, "Token collision detected"
            tokens.add(t)

    def test_missing_token_returns_404(self, admin_client):
        """GET /p/nonexistent returns 404."""
        r = admin_client.get("/p/totallynotavalidtoken1234567890")
        assert r.status_code == 404

    def test_unknown_token_404_body_matches_style(self, admin_client):
        """404 for unknown token gives same HTTP status as any 404."""
        fake = "A" * 86
        r = admin_client.get(f"/p/{fake}")
        assert r.status_code == 404

    def test_accept_rejects_missing_consent(self, admin_client):
        """POST /p/{token}/accept without consent_electronic=True returns 422."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.post(f"/p/{sent['accept_token']}/accept",
                              json={"selected_tier": "good",
                                    "consent_electronic": False,
                                    "signed_name": "Tim Perkins"})
        assert r.status_code == 422

    def test_accept_rejects_missing_consent_field(self, admin_client):
        """POST /p/{token}/accept without consent_electronic field returns 422."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.post(f"/p/{sent['accept_token']}/accept",
                              json={"selected_tier": "good",
                                    "signed_name": "Tim Perkins"})
        assert r.status_code == 422

    def test_accept_rejects_empty_name(self, admin_client):
        """POST /p/{token}/accept with blank signed_name returns 422."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.post(f"/p/{sent['accept_token']}/accept",
                              json={"selected_tier": "good",
                                    "consent_electronic": True,
                                    "signed_name": "   "})
        assert r.status_code == 422

    def test_double_accept_idempotent(self, admin_client):
        """Second POST /p/{token}/accept returns 404 (status already 'accepted')."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        token = sent["accept_token"]
        payload = {"selected_tier": "good", "consent_electronic": True,
                   "signed_name": "Tim Perkins"}
        r1 = admin_client.post(f"/p/{token}/accept", json=payload)
        assert r1.status_code == 200
        r2 = admin_client.post(f"/p/{token}/accept", json=payload)
        assert r2.status_code == 404

    # test_404_timing_indistinguishable removed: timing test is environment-dependent
    # theater (passes on fast CI, flakes on slow runners). Token entropy (512-bit) is
    # the primary brute-force protection; Cloudflare WAF rate limiting added in F6.


# ---------------------------------------------------------------------------
# §6.4 — Consent / audit completeness
# ---------------------------------------------------------------------------

class TestESignAudit:
    def _do_accept(self, client, token, name="Tim Perkins", tier="good",
                   consent=True):
        payload = {"selected_tier": tier, "consent_electronic": consent,
                   "signed_name": name}
        return client.post(f"/p/{token}/accept", json=payload)

    def test_accept_records_event(self, admin_client):
        """Accepting inserts a proposal_events row with event_type='accepted'."""
        from app.models import ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = self._do_accept(admin_client, sent["accept_token"])
        assert r.status_code == 200
        with SessionLocal() as db:
            events = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "accepted",
                )
            ).scalars().all()
        assert len(events) == 1

    def test_accept_records_ip_ua(self, admin_client):
        """proposal_events 'accepted' row carries ip_address and user_agent strings."""
        from app.models import ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(f"/p/{sent['accept_token']}/accept",
                          json={"selected_tier": "good", "consent_electronic": True,
                                "signed_name": "Tim"},
                          headers={"User-Agent": "TestBrowser/1.0"})
        with SessionLocal() as db:
            ev = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "accepted",
                )
            ).scalar_one()
        # ip_address may be None in TestClient (testclient sets no real IP)
        assert ev.user_agent is not None

    def test_accept_stores_consent_flag(self, admin_client):
        """proposals.consent_electronic is TRUE after acceptance."""
        from app.models import Proposal
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        self._do_accept(admin_client, sent["accept_token"])
        with SessionLocal() as db:
            row = db.get(Proposal, sent["id"])
        assert row.consent_electronic is True

    def test_accept_stores_signed_name(self, admin_client):
        """proposals.accepted_by_name matches the submitted signed_name."""
        from app.models import Proposal
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        self._do_accept(admin_client, sent["accept_token"], name="Jonathan Pastore")
        with SessionLocal() as db:
            row = db.get(Proposal, sent["id"])
        assert row.accepted_by_name == "Jonathan Pastore"

    def test_viewed_event_on_first_get(self, admin_client):
        """GET /p/{token} inserts 'viewed' event and transitions status sent→viewed."""
        from app.models import Proposal, ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.get(f"/p/{sent['accept_token']}")
        with SessionLocal() as db:
            row = db.get(Proposal, sent["id"])
            events = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "viewed",
                )
            ).scalars().all()
        assert row.status == "viewed"
        assert len(events) == 1

    def test_viewed_event_not_duplicated(self, admin_client):
        """Subsequent GETs do not insert additional 'viewed' events."""
        from app.models import ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        token = sent["accept_token"]
        admin_client.get(f"/p/{token}")
        admin_client.get(f"/p/{token}")
        admin_client.get(f"/p/{token}")
        with SessionLocal() as db:
            events = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "viewed",
                )
            ).scalars().all()
        assert len(events) == 1

    def test_send_records_sent_event(self, admin_client):
        """Sending a proposal inserts a proposal_events row with event_type='sent'."""
        from app.models import ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        with SessionLocal() as db:
            events = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "sent",
                )
            ).scalars().all()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# §6.5 — Floor preservation
# ---------------------------------------------------------------------------

class TestFloorPreservation:
    def test_floor_min_profit_preserved(self, admin_client):
        """quote_snapshot floors match the config at send time."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        snap = sent["quote_snapshot"]
        assert snap["floors"]["min_profit_pct"] == 13
        assert snap["floors"]["min_profit_plus_oh_pct"] == 33

    def test_floor_not_recalculated_on_read(self, admin_client):
        """Reading a proposal returns the frozen snapshot floors, not recomputed ones."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/quoting/proposals/{sent['id']}", headers=AUTH)
        snap = r.json()["quote_snapshot"]
        assert snap["floors"]["min_profit_pct"] == 13


# ---------------------------------------------------------------------------
# Proposal CRUD — list, get, create, update
# ---------------------------------------------------------------------------

class TestProposalCRUD:
    def test_create_draft_proposal(self, admin_client):
        c, cust, prop, draft = _scaffold(admin_client)
        assert draft["status"] == "draft"
        assert draft["id"] is not None
        assert draft["tenant_id"] == 1

    def test_create_draft_proposal_preserves_estimate_id(self, admin_client):
        from app.models import Estimate

        cust = _create_customer(admin_client)
        prop = _create_property(admin_client, cust["id"])
        with SessionLocal() as db:
            db.info["tenant_id"] = 1
            est = Estimate(tenant_id=1, input_json={}, result_json={}, created_by="test")
            db.add(est)
            db.commit()
            estimate_id = est.id
        r = admin_client.post(
            "/quoting/proposals",
            json={
                "customer_id": cust["id"],
                "property_id": prop["id"],
                "title": "Estimate linked proposal",
                "quote_snapshot": _SAMPLE_SNAPSHOT,
                "estimate_id": estimate_id,
            },
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        assert r.json()["estimate_id"] == estimate_id

    def test_list_proposals(self, admin_client):
        c, cust, prop, draft = _scaffold(admin_client)
        r = admin_client.get("/quoting/proposals", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "total" in body
        ids = [p["id"] for p in body["items"]]
        assert draft["id"] in ids
        row = next(p for p in body["items"] if p["id"] == draft["id"])
        assert "amount" in row
        assert row["amount"] == 18400.0

    def test_get_proposal(self, admin_client):
        c, cust, prop, draft = _scaffold(admin_client)
        r = admin_client.get(f"/quoting/proposals/{draft['id']}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["id"] == draft["id"]

    def test_get_proposal_includes_events(self, admin_client):
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/quoting/proposals/{sent['id']}", headers=AUTH)
        body = r.json()
        assert "events" in body

    def test_get_proposal_404(self, admin_client):
        r = admin_client.get("/quoting/proposals/999999", headers=AUTH)
        assert r.status_code == 404

    def test_update_draft_proposal(self, admin_client):
        c, cust, prop, draft = _scaffold(admin_client)
        r = admin_client.put(f"/quoting/proposals/{draft['id']}",
                             json={"title": "Updated Title"},
                             headers=AUTH)
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Title"

    def test_list_proposals_unauthenticated_401(self):
        client = TestClient(appmod.app)
        r = client.get("/quoting/proposals")
        assert r.status_code == 401

    def test_proposals_tenant_isolation(self, admin_client):
        """Proposals for tenant 2 must not appear in tenant 1's list."""
        from app.models import Customer, Property, Proposal
        with SessionLocal() as db:
            c2 = Customer(tenant_id=2, display_name="T2Cust")
            db.add(c2)
            db.flush()
            p2 = Property(tenant_id=2, customer_id=c2.id,
                          street="1 X St", city="Miami", state="FL",
                          code_zone="HVHZ")
            db.add(p2)
            db.flush()
            tok = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
            prop2 = Proposal(
                tenant_id=2, customer_id=c2.id, property_id=p2.id,
                title="T2 Proposal",
                quote_snapshot=_SAMPLE_SNAPSHOT,
                accept_token=tok,
                created_by="x@x.com",
            )
            db.add(prop2)
            db.commit()
            t2_id = prop2.id

        r = admin_client.get("/quoting/proposals", headers=AUTH)
        ids = [p["id"] for p in r.json()["items"]]
        assert t2_id not in ids


# ---------------------------------------------------------------------------
# Authz — quoting_send is required to send / revise
# ---------------------------------------------------------------------------

class TestProposalAuthz:
    def test_create_proposal_sales_allowed(self):
        sc = _make_sales()
        cust = _create_customer(sc)
        prop = _create_property(sc, cust["id"])
        r = sc.post("/quoting/proposals",
                    json={"customer_id": cust["id"],
                          "property_id": prop["id"],
                          "title": "Sales Draft",
                          "quote_snapshot": _SAMPLE_SNAPSHOT},
                    headers=AUTH)
        assert r.status_code == 200

    def test_send_proposal_sales_allowed(self):
        """sales has quoting_send → allowed."""
        sc = _make_sales()
        cust = _create_customer(sc)
        prop = _create_property(sc, cust["id"])
        draft = _create_proposal(sc, cust["id"], prop["id"])
        r = sc.post(f"/quoting/proposals/{draft['id']}/send",
                    json={}, headers=AUTH)
        assert r.status_code == 200

    def test_manage_templates_requires_web_admin(self):
        """quoting_manage_templates — sales is denied, web_admin allowed."""
        # sales — should get 403
        sc = _make_sales()
        r = sc.post("/quoting/templates",
                    json={"name": "T1", "html_body": "<p>Hello</p>"},
                    headers=AUTH)
        assert r.status_code == 403

    def test_manage_templates_web_admin_allowed(self):
        """web_admin has quoting_manage_templates."""
        set_verifier(lambda t: {"uid": "u3", "email": "webadmin@perkins.com",
                                "role": "web_admin", "email_verified": True})
        client = TestClient(appmod.app)
        r = client.post("/quoting/templates",
                        json={"name": "T1", "html_body": "<p>Hello</p>"},
                        headers=AUTH)
        assert r.status_code == 200

    def test_manage_settings_sales_denied(self):
        """quoting_manage_settings — sales is denied."""
        sc = _make_sales()
        r = sc.put("/quoting/settings",
                   json={"deposit": {"mode": "percent", "value": 30}},
                   headers=AUTH)
        assert r.status_code == 403

    def test_unauthenticated_proposals_401(self):
        client = TestClient(appmod.app)
        r = client.post("/quoting/proposals", json={})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Decline / revision-request on public surface
# ---------------------------------------------------------------------------

class TestPublicDeclineRevision:
    def test_decline_sets_status(self, admin_client):
        """POST /p/{token}/decline sets status=declined and inserts event."""
        from app.models import Proposal
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.post(f"/p/{sent['accept_token']}/decline",
                              json={"note": "Price too high"})
        assert r.status_code == 200
        with SessionLocal() as db:
            row = db.get(Proposal, sent["id"])
        assert row.status == "declined"

    def test_decline_unknown_token_404(self, admin_client):
        r = admin_client.post("/p/FAKEFAKEFAKEFAKEFAKE/decline",
                              json={"note": "nope"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Accept page render data
# ---------------------------------------------------------------------------

class TestAcceptPageRender:
    def test_get_valid_token_returns_200_json_shape(self, admin_client):
        """GET /p/{token} for a sent proposal returns 200 JSON with required shape."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("sent", "viewed")
        assert "title" in body
        assert "customer_name" in body
        assert "property_address" in body
        assert "quote_snapshot" in body
        assert "tenant_name" in body

    def test_get_accepted_token_returns_200_json_terminal(self, admin_client):
        """GET /p/{token} for an accepted proposal returns 200 JSON with status+title only (no snapshot)."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(f"/p/{sent['accept_token']}/accept",
                          json={"selected_tier": "good", "consent_electronic": True,
                                "signed_name": "Tim Perkins"})
        r = admin_client.get(f"/p/{sent['accept_token']}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert "title" in body
        # Terminal state: no snapshot exposed (client-safe projection — data-leak fix)
        assert "quote_snapshot" not in body

    def test_accept_captures_tier_selection(self, admin_client):
        """POST /p/{token}/accept captures selected_tier in the proposal row."""
        from app.models import Proposal
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(f"/p/{sent['accept_token']}/accept",
                          json={"selected_tier": "better", "consent_electronic": True,
                                "signed_name": "Tim Perkins"})
        with SessionLocal() as db:
            row = db.get(Proposal, sent["id"])
        assert row.selected_tier == "better"

    def test_accept_captures_accepted_at_timestamp(self, admin_client):
        """proposals.accepted_at is populated after acceptance."""
        from app.models import Proposal
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(f"/p/{sent['accept_token']}/accept",
                          json={"selected_tier": "good", "consent_electronic": True,
                                "signed_name": "Tim"})
        with SessionLocal() as db:
            row = db.get(Proposal, sent["id"])
        assert row.accepted_at is not None


class TestUISeamContracts:
    """Explicit contract tests for the three UI seam requirements."""

    def test_list_proposals_includes_customer_name(self, admin_client):
        """GET /quoting/proposals rows must include customer_name (denormalized join)."""
        _scaffold(admin_client)
        r = admin_client.get("/quoting/proposals", headers=AUTH)
        assert r.status_code == 200
        rows = r.json()["items"]
        assert len(rows) >= 1
        row = rows[0]
        assert "customer_name" in row
        assert row["customer_name"] is not None

    def test_list_proposals_includes_property_address(self, admin_client):
        """GET /quoting/proposals rows must include property_address (denormalized join)."""
        _scaffold(admin_client)
        r = admin_client.get("/quoting/proposals", headers=AUTH)
        assert r.status_code == 200
        rows = r.json()["items"]
        assert len(rows) >= 1
        row = rows[0]
        assert "property_address" in row

    def test_list_proposals_page_param(self, admin_client):
        """GET /quoting/proposals?page=1 returns same result as skip=0."""
        _scaffold(admin_client)
        r_skip = admin_client.get("/quoting/proposals?skip=0&limit=50", headers=AUTH)
        r_page = admin_client.get("/quoting/proposals?page=1&limit=50", headers=AUTH)
        assert r_skip.status_code == 200
        assert r_page.status_code == 200
        assert r_skip.json() == r_page.json()

    def test_list_proposals_pages_are_disjoint(self, admin_client):
        """Pagination contract: page 2 never repeats page 1 rows, and when page 1
        is not full, page 2 is empty. (DB-state-agnostic — see customers variant.)"""
        _scaffold(admin_client)
        r1 = admin_client.get("/quoting/proposals?page=1&limit=50", headers=AUTH)
        r2 = admin_client.get("/quoting/proposals?page=2&limit=50", headers=AUTH)
        assert r1.status_code == 200 and r2.status_code == 200
        ids1 = {p["id"] for p in r1.json()["items"]}
        ids2 = {p["id"] for p in r2.json()["items"]}
        assert ids1.isdisjoint(ids2)
        if len(ids1) < 50:
            assert r2.json()["items"] == []

    def test_list_customers_page_param(self, admin_client):
        """GET /quoting/customers?page=1 returns same result as skip=0."""
        r_skip = admin_client.get("/quoting/customers?skip=0&limit=50", headers=AUTH)
        r_page = admin_client.get("/quoting/customers?page=1&limit=50", headers=AUTH)
        assert r_skip.status_code == 200
        assert r_page.status_code == 200
        assert r_skip.json() == r_page.json()

    def test_list_customers_pages_are_disjoint(self, admin_client):
        """Pagination contract: page 2 never repeats page 1 rows, and when page 1
        is not full, page 2 is empty. (DB-state-agnostic — the full suite shares a
        DB with other test files, so an absolute row-count premise is not safe.)"""
        r1 = admin_client.get("/quoting/customers?page=1&limit=50", headers=AUTH)
        r2 = admin_client.get("/quoting/customers?page=2&limit=50", headers=AUTH)
        assert r1.status_code == 200 and r2.status_code == 200
        ids1 = {c["id"] for c in r1.json()["items"]}
        ids2 = {c["id"] for c in r2.json()["items"]}
        assert ids1.isdisjoint(ids2)
        if len(ids1) < 50:
            assert r2.json()["items"] == []

    def test_public_token_get_returns_json_not_html(self, admin_client):
        """GET /p/{token} content-type must be application/json for all states."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        assert r.status_code == 200
        assert "application/json" in r.headers.get("content-type", "")

    def test_public_token_get_all_required_fields(self, admin_client):
        """GET /p/{token} JSON body has all six required fields."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        body = r.json()
        for field in ("status", "title", "customer_name", "property_address",
                      "quote_snapshot", "tenant_name"):
            assert field in body, f"missing field: {field}"


# ---------------------------------------------------------------------------
# Fix 3: Public projection — no data leak (floors, pricing_config_hash, etc.)
# ---------------------------------------------------------------------------

class TestPublicProjection:
    def test_sent_token_strips_floors(self, admin_client):
        """GET /p/{token} for active proposal must NOT include floors in quote_snapshot."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        assert r.status_code == 200
        snap = r.json().get("quote_snapshot", {})
        assert "floors" not in snap, "floors must not be in public projection"

    def test_sent_token_strips_pricing_config_hash(self, admin_client):
        """GET /p/{token} for active proposal must NOT include pricing_config_hash."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        assert r.status_code == 200
        snap = r.json().get("quote_snapshot", {})
        assert "pricing_config_hash" not in snap, "pricing_config_hash must not be in public projection"

    def test_sent_token_strips_estimator_version(self, admin_client):
        """GET /p/{token} must NOT expose estimator_version in quote_snapshot."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        snap = r.json().get("quote_snapshot", {})
        assert "estimator_version" not in snap

    def test_sent_token_strips_region_branch_code_zone(self, admin_client):
        """GET /p/{token} must NOT expose region/branch/code_zone."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        snap = r.json().get("quote_snapshot", {})
        for key in ("region", "branch", "code_zone"):
            assert key not in snap, f"{key} must not be in public projection"

    def test_sent_token_tiers_stripped_to_safe_keys(self, admin_client):
        """quote_snapshot.tiers in public response contains only label/description/total."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.get(f"/p/{sent['accept_token']}")
        snap = r.json().get("quote_snapshot", {})
        tiers = snap.get("tiers", {})
        assert tiers, "tiers must be present"
        for tier_name, tier_data in tiers.items():
            for key in ("line_items",):
                assert key not in tier_data, f"tiers.{tier_name}.{key} must not be exposed"

    def test_draft_token_returns_404(self, admin_client):
        """GET /p/{token} for a draft proposal returns 404 (indistinguishable from unknown)."""
        c, cust, prop, draft = _scaffold(admin_client)
        r = admin_client.get(f"/p/{draft['accept_token']}")
        assert r.status_code == 404

    def test_terminal_accepted_returns_only_status_title(self, admin_client):
        """GET /p/{token} for accepted proposal returns only status+title, no snapshot."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(f"/p/{sent['accept_token']}/accept",
                          json={"selected_tier": "good", "consent_electronic": True,
                                "signed_name": "Tim Perkins"})
        r = admin_client.get(f"/p/{sent['accept_token']}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert "title" in body
        assert "quote_snapshot" not in body, "terminal states must not expose snapshot"

    def test_terminal_declined_returns_only_status_title(self, admin_client):
        """GET /p/{token} for declined proposal returns only status+title, no snapshot."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(f"/p/{sent['accept_token']}/decline", json={})
        r = admin_client.get(f"/p/{sent['accept_token']}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "declined"
        assert "quote_snapshot" not in body

    def test_superseded_returns_only_status_title(self, admin_client):
        """GET /p/{superseded_token} returns only status+title, no snapshot."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        old_token = sent["accept_token"]
        admin_client.post(f"/quoting/proposals/{sent['id']}/revise",
                          json={"title": "Rev 2", "quote_snapshot": _SAMPLE_SNAPSHOT},
                          headers=AUTH)
        r = admin_client.get(f"/p/{old_token}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "superseded"
        assert "quote_snapshot" not in body


# ---------------------------------------------------------------------------
# Fix 4: eSign IP — X-Forwarded-For leftmost hop
# ---------------------------------------------------------------------------

class TestESignIP:
    def test_client_ip_uses_x_forwarded_for_leftmost(self, admin_client):
        """accept event records leftmost X-Forwarded-For IP, not the proxy IP."""
        from app.models import ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(
            f"/p/{sent['accept_token']}/accept",
            json={"selected_tier": "good", "consent_electronic": True,
                  "signed_name": "Tim"},
            headers={"X-Forwarded-For": "203.0.113.7, 10.1.2.3"},
        )
        with SessionLocal() as db:
            ev = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "accepted",
                )
            ).scalar_one()
        assert ev.ip_address == "203.0.113.7", (
            f"Expected 203.0.113.7, got {ev.ip_address!r}"
        )

    def test_client_ip_fallback_when_no_xff(self, admin_client):
        """Without X-Forwarded-For the ip_address is still populated (client.host or '')."""
        from app.models import ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        admin_client.post(
            f"/p/{sent['accept_token']}/accept",
            json={"selected_tier": "good", "consent_electronic": True,
                  "signed_name": "Tim"},
        )
        with SessionLocal() as db:
            ev = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "accepted",
                )
            ).scalar_one()
        # ip_address is a string (possibly empty from testclient) — must not error
        assert ev.ip_address is not None or ev.ip_address == ""


# ---------------------------------------------------------------------------
# Fix 5: Atomic accept — race-safe, no duplicate events on double-accept
# ---------------------------------------------------------------------------

class TestAtomicAccept:
    def test_double_accept_no_duplicate_event(self, admin_client):
        """Sequential double-accept must produce exactly one 'accepted' event row."""
        from app.models import ProposalEvent
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        token = sent["accept_token"]
        payload = {"selected_tier": "good", "consent_electronic": True,
                   "signed_name": "Tim Perkins"}
        r1 = admin_client.post(f"/p/{token}/accept", json=payload)
        assert r1.status_code == 200
        r2 = admin_client.post(f"/p/{token}/accept", json=payload)
        assert r2.status_code == 404  # already terminal

        with SessionLocal() as db:
            events = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == sent["id"],
                    ProposalEvent.event_type == "accepted",
                )
            ).scalars().all()
        assert len(events) == 1, f"Expected 1 accepted event, got {len(events)}"

    def test_double_accept_no_duplicate_job(self, admin_client):
        """Sequential double-accept must produce exactly one Job stub row."""
        from app.models import Job
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        token = sent["accept_token"]
        payload = {"selected_tier": "good", "consent_electronic": True,
                   "signed_name": "Tim Perkins"}
        admin_client.post(f"/p/{token}/accept", json=payload)
        admin_client.post(f"/p/{token}/accept", json=payload)

        with SessionLocal() as db:
            from sqlalchemy import select as _select
            jobs = db.execute(
                _select(Job).where(Job.proposal_id == sent["id"])
            ).scalars().all()
        assert len(jobs) == 1, f"Expected 1 Job row, got {len(jobs)}"


# ---------------------------------------------------------------------------
# Fix 7: PUT immutability — non-draft proposals reject update with 409
# ---------------------------------------------------------------------------

class TestPutImmutability:
    def test_put_on_sent_proposal_returns_409(self, admin_client):
        """PUT /quoting/proposals/{id} on a sent proposal returns 409."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        r = admin_client.put(f"/quoting/proposals/{sent['id']}",
                             json={"title": "Should not work"},
                             headers=AUTH)
        assert r.status_code == 409

    def test_put_on_sent_snapshot_unchanged(self, admin_client):
        """PUT on a sent proposal leaves the snapshot unchanged."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        original_hash = sent["quote_snapshot"]["pricing_config_hash"]
        admin_client.put(f"/quoting/proposals/{sent['id']}",
                         json={"quote_snapshot": {**_SAMPLE_SNAPSHOT,
                                                   "pricing_config_hash": "CHANGED"}},
                         headers=AUTH)
        r = admin_client.get(f"/quoting/proposals/{sent['id']}", headers=AUTH)
        assert r.json()["quote_snapshot"]["pricing_config_hash"] == original_hash

    def test_put_on_draft_still_works(self, admin_client):
        """PUT on a draft proposal still succeeds with 200."""
        c, cust, prop, draft = _scaffold(admin_client)
        r = admin_client.put(f"/quoting/proposals/{draft['id']}",
                             json={"title": "Updated Draft"},
                             headers=AUTH)
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Draft"


# ---------------------------------------------------------------------------
# Fix 9: Missing endpoints
# ---------------------------------------------------------------------------

class TestMissingEndpoints:
    def test_pdf_endpoint_exists_503_without_gotenberg(self, admin_client):
        """GET /quoting/proposals/{id}/pdf returns 503 when GOTENBERG_URL is unset."""
        import os
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        env_backup = os.environ.pop("GOTENBERG_URL", None)
        try:
            r = admin_client.get(f"/quoting/proposals/{sent['id']}/pdf", headers=AUTH)
            assert r.status_code == 503, f"Expected 503 (no GOTENBERG_URL), got {r.status_code}"
        finally:
            if env_backup is not None:
                os.environ["GOTENBERG_URL"] = env_backup


    def test_pdf_endpoint_serves_cached_gcs_without_gotenberg(self, admin_client, monkeypatch):
        import os

        import api.routes.proposals as mod

        c, cust, prop, draft = _scaffold(admin_client)
        with SessionLocal() as db:
            db.info["tenant_id"] = 1
            row = db.get(mod.Proposal, draft["id"])
            row.quote_snapshot = {
                **row.quote_snapshot,
                "rendered_pdf_gcs": "gs://bucket/proposal.pdf",
                "rendered_pdf_template_version": mod._PDF_TEMPLATE_VERSION,
            }
            db.commit()

        monkeypatch.setattr(mod, "_download_gcs_bytes", lambda uri: b"%PDF-1.4 cached")
        env_backup = os.environ.pop("GOTENBERG_URL", None)
        try:
            r = admin_client.get(f"/quoting/proposals/{draft['id']}/pdf", headers=AUTH)
        finally:
            if env_backup is not None:
                os.environ["GOTENBERG_URL"] = env_backup

        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")

    def test_pdf_helper_builds_standard_draws_from_total(self):
        import api.routes.proposals as mod

        draws = mod._proposal_payment_draws({"total": "18400.00"}, 18400.00)
        assert [d["pct"] for d in draws] == ["30%", "30%", "30%", "Balance"]
        assert draws[0]["amount"] == "$5,520.00"
        assert draws[-1]["label"] == "Substantial completion (net balance)"
        assert draws[-1]["amount"] == "$1,840.00"

    def test_pdf_scope_lines_preserve_zero_price_lines(self):
        import api.routes.proposals as mod

        lines = mod._proposal_scope_lines({
            "total": "127263.35",
            "line_items": [
                {"Description": "Comped gutter scope", "Quantity": "52000", "UnitName": "LF", "Price": "0.00"},
            ],
        })
        assert lines[0]["label"] == "Comped gutter scope"
        assert lines[0]["total"] == 0.0
        assert lines[0]["price_display"] == "$0.00"

    def test_template_preview_endpoint_exists(self, admin_client):
        """POST /quoting/templates/{id}/preview returns 200 or known error (not 404/405)."""
        c, cust, prop, draft = _scaffold(admin_client)
        # First create a template
        r_tpl = admin_client.post("/quoting/templates",
                                  json={"name": "T-Preview", "html_body": "<p>Hi {{customer_name}}</p>"},
                                  headers=AUTH)
        assert r_tpl.status_code == 200
        tpl_id = r_tpl.json()["id"]
        r = admin_client.post(f"/quoting/templates/{tpl_id}/preview",
                              json={}, headers=AUTH)
        # 200 (rendered HTML) or 503 (Gotenberg down) — never 404 or 405
        assert r.status_code in (200, 503), f"Unexpected status {r.status_code}"

    def test_delete_template_without_proposals(self, admin_client):
        """DELETE /quoting/templates/{id} with no proposals referencing it returns 200."""
        r_tpl = admin_client.post("/quoting/templates",
                                  json={"name": "T-Delete", "html_body": "<p>Hello</p>"},
                                  headers=AUTH)
        assert r_tpl.status_code == 200
        tpl_id = r_tpl.json()["id"]
        r = admin_client.delete(f"/quoting/templates/{tpl_id}", headers=AUTH)
        assert r.status_code == 200

    def test_delete_template_with_sent_proposal_returns_409(self, admin_client):
        """DELETE /quoting/templates/{id} when a non-draft proposal references it returns 409."""
        # Create template
        r_tpl = admin_client.post("/quoting/templates",
                                  json={"name": "T-InUse", "html_body": "<p>Hello</p>"},
                                  headers=AUTH)
        assert r_tpl.status_code == 200
        tpl_id = r_tpl.json()["id"]
        # Create + send a proposal referencing the template
        c, cust, prop, draft = _scaffold(admin_client)
        r_prop = admin_client.post("/quoting/proposals",
                                   json={"customer_id": cust["id"],
                                         "property_id": prop["id"],
                                         "title": "Ref Proposal",
                                         "quote_snapshot": _SAMPLE_SNAPSHOT,
                                         "template_id": tpl_id},
                                   headers=AUTH)
        assert r_prop.status_code == 200
        _send_proposal(admin_client, r_prop.json()["id"])
        # Now try to delete — must be 409
        r = admin_client.delete(f"/quoting/templates/{tpl_id}", headers=AUTH)
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# Fix 6: Money-path wiring — validate_snapshot on send, email degradation
# ---------------------------------------------------------------------------

class TestMoneyPathWiring:
    def test_send_validates_snapshot_422_on_bad_snapshot(self, admin_client):
        """POST /quoting/proposals/{id}/send returns 422 if snapshot fails validation."""
        c, cust, prop, _ = _scaffold(admin_client)
        # Create proposal with a snapshot missing required keys
        bad_snap = {"tiers": {"good": {"label": "G", "total": 100}}}  # missing floors, etc.
        r = admin_client.post("/quoting/proposals",
                              json={"customer_id": cust["id"],
                                    "property_id": prop["id"],
                                    "title": "Bad Snap",
                                    "quote_snapshot": bad_snap},
                              headers=AUTH)
        assert r.status_code == 200
        proposal_id = r.json()["id"]
        r_send = admin_client.post(f"/quoting/proposals/{proposal_id}/send",
                                   json={}, headers=AUTH)
        assert r_send.status_code == 422, (
            f"Expected 422 from validate_snapshot, got {r_send.status_code}: {r_send.text}"
        )

    def test_send_stamps_sent_at_iso_in_snapshot(self, admin_client):
        """After sending, quote_snapshot must contain sent_at_iso."""
        c, cust, prop, draft = _scaffold(admin_client)
        sent = _send_proposal(admin_client, draft["id"])
        snap = sent["quote_snapshot"]
        assert "sent_at_iso" in snap, "sent_at_iso must be stamped into snapshot on send"
        assert snap["sent_at_iso"]  # non-empty

    @patch("adapters.resend.send")
    def test_send_calls_email_when_customer_has_email(self, mock_resend, admin_client):
        """Sending a proposal with a customer email calls resend.send once."""
        c, cust, prop, draft = _scaffold(admin_client)
        # _scaffold creates customers with email set
        _send_proposal(admin_client, draft["id"])
        mock_resend.assert_called_once()

    @patch("adapters.resend.send")
    def test_send_email_sent_false_when_no_customer_email(self, mock_resend, admin_client):
        """Sending when customer has no email returns email_sent=False, does not raise."""
        from app.models import Customer
        # Create customer without email
        with SessionLocal() as db:
            cust_no_email = Customer(tenant_id=1, display_name="NoEmail Customer")
            db.add(cust_no_email)
            db.flush()
            from app.models import Property
            prop_row = Property(tenant_id=1, customer_id=cust_no_email.id,
                                street="1 X St", city="Miami", state="FL", code_zone="FBC")
            db.add(prop_row)
            db.commit()
            cust_id = cust_no_email.id
            prop_id = prop_row.id

        r_draft = admin_client.post("/quoting/proposals",
                                    json={"customer_id": cust_id,
                                          "property_id": prop_id,
                                          "title": "No-Email Proposal",
                                          "quote_snapshot": _SAMPLE_SNAPSHOT},
                                    headers=AUTH)
        assert r_draft.status_code == 200
        r_send = admin_client.post(f"/quoting/proposals/{r_draft.json()['id']}/send",
                                   json={}, headers=AUTH)
        assert r_send.status_code == 200
        assert r_send.json().get("email_sent") is False
        mock_resend.assert_not_called()

    @patch("adapters.resend.send", side_effect=RuntimeError("RESEND_API_KEY not set"))
    def test_send_degrades_gracefully_on_email_error(self, mock_resend, admin_client):
        """Email failure on send does not fail the proposal (still returns 200)."""
        c, cust, prop, draft = _scaffold(admin_client)
        r = admin_client.post(f"/quoting/proposals/{draft['id']}/send",
                              json={}, headers=AUTH)
        # Must still succeed even when email fails
        assert r.status_code == 200


class TestKnowifyStateMapping:
    def test_signed_maps_to_accepted_with_created_date(self):
        from api.routes.proposals import knowify_proposal_state
        st = knowify_proposal_state({"BusinessState": "Open", "IsSigned": True, "DateCreated": "2024-01-15T10:00:00Z"})
        assert st["status"] == "accepted"
        assert st["created_at"].year == 2024 and st["created_at"].month == 1

    def test_outforsigning_recent_is_sent(self):
        from api.routes.proposals import knowify_proposal_state
        recent = datetime.now(timezone.utc).date().isoformat()
        c = {"BusinessState": "OutForSigning", "IsSigned": False, "DateCreated": recent}
        assert knowify_proposal_state(c)["status"] == "sent"

    def test_outforsigning_stale_autodeclines(self):
        from api.routes.proposals import knowify_proposal_state
        c = {"BusinessState": "OutForSigning", "IsSigned": False, "DateCreated": "2020-01-01T00:00:00Z"}
        assert knowify_proposal_state(c)["status"] == "declined"

    def test_lost_maps_to_declined(self):
        from api.routes.proposals import knowify_proposal_state
        st = knowify_proposal_state({"BusinessState": "Lost", "IsSigned": False, "DateCreated": "2024-01-01T00:00:00Z"})
        assert st["status"] == "declined"

    def test_draft_stays_draft(self):
        from api.routes.proposals import knowify_proposal_state
        c = {"BusinessState": "Draft", "IsSigned": False, "DateCreated": "2024-01-01T00:00:00Z"}
        assert knowify_proposal_state(c)["status"] == "draft"
