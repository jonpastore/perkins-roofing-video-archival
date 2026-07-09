"""TDD tests for F3 ORM models in app/models.py.

Verifies the 9 new tables (customers, contacts, properties, proposal_templates,
proposals, proposal_events, leads, jobs, catalog_items, tc_versions) exist in the
schema with the correct columns, constraints, and FKs.  Runs on SQLite via the
conftest.py temp-DB fixture.
"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models import (
    Base,
    CatalogItem,
    Contact,
    Customer,
    Job,
    Lead,
    Proposal,
    ProposalEvent,
    ProposalTemplate,
    Property,
    SessionLocal,
    TcVersion,
    Tenant,
    engine,
)


# ---------------------------------------------------------------------------
# Schema introspection helpers
# ---------------------------------------------------------------------------

def _columns(table_name: str) -> set[str]:
    insp = inspect(engine)
    return {c["name"] for c in insp.get_columns(table_name)}


def _table_names() -> set[str]:
    insp = inspect(engine)
    return set(insp.get_table_names())


# ---------------------------------------------------------------------------
# Fixture: ensure schema created once for this module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _create_schema():
    Base.metadata.create_all(engine)
    yield


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------

class TestTableExistence:
    def test_customers_table_exists(self):
        assert "customers" in _table_names()

    def test_contacts_table_exists(self):
        assert "contacts" in _table_names()

    def test_properties_table_exists(self):
        assert "properties" in _table_names()

    def test_proposal_templates_table_exists(self):
        assert "proposal_templates" in _table_names()

    def test_proposals_table_exists(self):
        assert "proposals" in _table_names()

    def test_proposal_events_table_exists(self):
        assert "proposal_events" in _table_names()

    def test_leads_table_exists(self):
        assert "leads" in _table_names()

    def test_jobs_table_exists(self):
        assert "jobs" in _table_names()

    def test_catalog_items_table_exists(self):
        assert "catalog_items" in _table_names()

    def test_tc_versions_table_exists(self):
        assert "tc_versions" in _table_names()


# ---------------------------------------------------------------------------
# Column sets
# ---------------------------------------------------------------------------

class TestCustomerColumns:
    def test_required_columns(self):
        cols = _columns("customers")
        for col in ("id", "tenant_id", "display_name", "company_name", "email",
                    "phone", "knowify_customer_id", "notes", "created_at", "updated_at"):
            assert col in cols, f"Missing column: {col}"


class TestContactColumns:
    def test_required_columns(self):
        cols = _columns("contacts")
        for col in ("id", "tenant_id", "customer_id", "name", "role",
                    "email", "phone", "is_primary", "created_at"):
            assert col in cols, f"Missing column: {col}"


class TestPropertyColumns:
    def test_required_columns(self):
        cols = _columns("properties")
        for col in ("id", "tenant_id", "customer_id", "street", "city", "state",
                    "zip", "county", "code_zone", "knowify_customer_id",
                    "gcs_pdf_prefix", "notes", "created_at", "updated_at"):
            assert col in cols, f"Missing column: {col}"


class TestProposalTemplateColumns:
    def test_required_columns(self):
        cols = _columns("proposal_templates")
        for col in ("id", "tenant_id", "name", "is_default", "html_body",
                    "logo_url", "primary_color", "accent_color", "footer_text",
                    "tc_attachment_gcs", "cover_page_html", "created_by",
                    "updated_at", "created_at"):
            assert col in cols, f"Missing column: {col}"


class TestProposalColumns:
    def test_required_columns(self):
        cols = _columns("proposals")
        for col in ("id", "tenant_id", "customer_id", "property_id", "template_id",
                    "root_id", "parent_id", "version_number", "title",
                    "quote_snapshot", "selected_tier", "selected_options",
                    "status", "accept_token", "accepted_by_name", "accepted_at",
                    "accepted_ip", "accepted_ua", "consent_electronic",
                    "signed_pdf_gcs", "signed_pdf_emailed_at",
                    "created_by", "sent_at", "created_at", "updated_at"):
            assert col in cols, f"Missing column: {col}"


class TestProposalEventColumns:
    def test_required_columns(self):
        cols = _columns("proposal_events")
        for col in ("id", "tenant_id", "proposal_id", "event_type",
                    "occurred_at", "ip_address", "user_agent",
                    "actor_email", "metadata"):
            assert col in cols, f"Missing column: {col}"


class TestLeadColumns:
    def test_required_columns(self):
        cols = _columns("leads")
        for col in ("id", "tenant_id", "name", "email", "phone",
                    "source", "notes", "status", "converted_customer_id",
                    "created_at", "updated_at"):
            assert col in cols, f"Missing column: {col}"


class TestJobColumns:
    def test_required_columns(self):
        cols = _columns("jobs")
        for col in ("id", "tenant_id", "proposal_id", "status", "created_at"):
            assert col in cols, f"Missing column: {col}"


class TestCatalogItemColumns:
    def test_required_columns(self):
        cols = _columns("catalog_items")
        for col in ("id", "tenant_id", "name", "unit", "unit_price",
                    "knowify_item_id", "created_at"):
            assert col in cols, f"Missing column: {col}"


class TestTcVersionColumns:
    def test_required_columns(self):
        cols = _columns("tc_versions")
        for col in ("id", "tenant_id", "version_tag", "content_gcs",
                    "effective_at", "created_at"):
            assert col in cols, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# ORM round-trip: insert and read back
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def tenant_id(db):
    """Ensure Perkins tenant row exists (seeded by after_create hook or insert here)."""
    from sqlalchemy import text as sa_text
    result = db.execute(sa_text("SELECT id FROM tenants WHERE id = 1")).fetchone()
    if not result:
        t = Tenant(id=1, name="Perkins Roofing", slug="perkins", status="active", settings={})
        db.add(t)
        db.commit()
    return 1


class TestCustomerRoundTrip:
    def test_insert_and_read(self, db, tenant_id):
        c = Customer(
            tenant_id=tenant_id,
            display_name="Tim Perkins",
            company_name="Perkins Roofing",
            email="tim@perkins.com",
            phone="555-1234",
        )
        db.add(c)
        db.flush()
        assert c.id is not None
        fetched = db.query(Customer).filter_by(id=c.id).one()
        assert fetched.display_name == "Tim Perkins"
        assert fetched.tenant_id == tenant_id

    def test_knowify_customer_id_nullable(self, db, tenant_id):
        c = Customer(tenant_id=tenant_id, display_name="No Knowify")
        db.add(c)
        db.flush()
        assert c.knowify_customer_id is None


class TestContactRoundTrip:
    def test_insert_contact(self, db, tenant_id):
        cust = Customer(tenant_id=tenant_id, display_name="Contact Owner")
        db.add(cust)
        db.flush()
        ct = Contact(
            tenant_id=tenant_id,
            customer_id=cust.id,
            name="Jane Doe",
            role="Project Manager",
            email="jane@example.com",
            is_primary=True,
        )
        db.add(ct)
        db.flush()
        assert ct.id is not None
        assert ct.is_primary is True


class TestPropertyRoundTrip:
    def test_insert_property(self, db, tenant_id):
        cust = Customer(tenant_id=tenant_id, display_name="Property Owner")
        db.add(cust)
        db.flush()
        prop = Property(
            tenant_id=tenant_id,
            customer_id=cust.id,
            street="123 Main St",
            city="Miami",
            state="FL",
            code_zone="HVHZ",
        )
        db.add(prop)
        db.flush()
        assert prop.id is not None
        assert prop.code_zone == "HVHZ"

    def test_default_state_fl(self, db, tenant_id):
        cust = Customer(tenant_id=tenant_id, display_name="State Default Owner")
        db.add(cust)
        db.flush()
        prop = Property(
            tenant_id=tenant_id,
            customer_id=cust.id,
            street="456 Oak Ave",
            city="Jupiter",
            code_zone="FBC",
        )
        db.add(prop)
        db.flush()
        assert prop.state == "FL"


class TestProposalTemplateRoundTrip:
    def test_insert_template(self, db, tenant_id):
        tmpl = ProposalTemplate(
            tenant_id=tenant_id,
            name="Default Template",
            is_default=True,
            html_body="<h1>{{ proposal.title }}</h1>",
            created_by="admin@example.com",
        )
        db.add(tmpl)
        db.flush()
        assert tmpl.id is not None
        assert tmpl.is_default is True


class TestProposalRoundTrip:
    def _setup(self, db, tenant_id):
        cust = Customer(tenant_id=tenant_id, display_name="Proposal Customer")
        db.add(cust)
        db.flush()
        prop = Property(
            tenant_id=tenant_id, customer_id=cust.id,
            street="1 Test St", city="Miami", code_zone="HVHZ",
        )
        db.add(prop)
        db.flush()
        return cust, prop

    def test_insert_proposal(self, db, tenant_id):
        from core.proposal import generate_accept_token
        cust, prop = self._setup(db, tenant_id)
        token = generate_accept_token()
        p = Proposal(
            tenant_id=tenant_id,
            customer_id=cust.id,
            property_id=prop.id,
            title="Roof Replacement — 123 Main St",
            quote_snapshot={"pricing_config_hash": "abc", "tiers": {}},
            accept_token=token,
            status="draft",
            version_number=1,
            created_by="staff@example.com",
        )
        db.add(p)
        db.flush()
        assert p.id is not None
        assert p.status == "draft"
        assert p.version_number == 1

    def test_accept_token_unique_constraint(self, db, tenant_id):
        from sqlalchemy.exc import IntegrityError
        from core.proposal import generate_accept_token
        cust, prop = self._setup(db, tenant_id)
        token = generate_accept_token()
        p1 = Proposal(
            tenant_id=tenant_id, customer_id=cust.id, property_id=prop.id,
            title="P1", quote_snapshot={}, accept_token=token,
            status="draft", version_number=1, created_by="staff@example.com",
        )
        p2 = Proposal(
            tenant_id=tenant_id, customer_id=cust.id, property_id=prop.id,
            title="P2", quote_snapshot={}, accept_token=token,
            status="draft", version_number=1, created_by="staff@example.com",
        )
        db.add(p1)
        db.flush()
        db.add(p2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_status_default_is_draft(self, db, tenant_id):
        from core.proposal import generate_accept_token
        cust, prop = self._setup(db, tenant_id)
        p = Proposal(
            tenant_id=tenant_id, customer_id=cust.id, property_id=prop.id,
            title="Draft Test", quote_snapshot={},
            accept_token=generate_accept_token(),
            version_number=1, created_by="staff@example.com",
        )
        db.add(p)
        db.flush()
        assert p.status == "draft"

    def test_version_number_default_is_1(self, db, tenant_id):
        from core.proposal import generate_accept_token
        cust, prop = self._setup(db, tenant_id)
        p = Proposal(
            tenant_id=tenant_id, customer_id=cust.id, property_id=prop.id,
            title="Version Default Test", quote_snapshot={},
            accept_token=generate_accept_token(),
            created_by="staff@example.com",
        )
        db.add(p)
        db.flush()
        assert p.version_number == 1


class TestProposalEventRoundTrip:
    def test_insert_event(self, db, tenant_id):
        cust = Customer(tenant_id=tenant_id, display_name="Event Cust")
        db.add(cust)
        db.flush()
        prop = Property(
            tenant_id=tenant_id, customer_id=cust.id,
            street="1 Event St", city="Miami", code_zone="HVHZ",
        )
        db.add(prop)
        db.flush()
        from core.proposal import generate_accept_token
        proposal = Proposal(
            tenant_id=tenant_id, customer_id=cust.id, property_id=prop.id,
            title="Event Proposal", quote_snapshot={},
            accept_token=generate_accept_token(),
            status="sent", version_number=1, created_by="staff@example.com",
        )
        db.add(proposal)
        db.flush()
        evt = ProposalEvent(
            tenant_id=tenant_id,
            proposal_id=proposal.id,
            event_type="sent",
            actor_email="staff@example.com",
        )
        db.add(evt)
        db.flush()
        assert evt.id is not None
        assert evt.event_type == "sent"


class TestLeadRoundTrip:
    def test_insert_lead(self, db, tenant_id):
        lead = Lead(
            tenant_id=tenant_id,
            name="Prospect Pete",
            email="pete@example.com",
            source="web_form",
        )
        db.add(lead)
        db.flush()
        assert lead.id is not None
        assert lead.status == "new"

    def test_status_default_new(self, db, tenant_id):
        lead = Lead(tenant_id=tenant_id, name="Default Status")
        db.add(lead)
        db.flush()
        assert lead.status == "new"


class TestJobRoundTrip:
    def test_insert_job(self, db, tenant_id):
        cust = Customer(tenant_id=tenant_id, display_name="Job Cust")
        db.add(cust)
        db.flush()
        prop = Property(
            tenant_id=tenant_id, customer_id=cust.id,
            street="1 Job St", city="Miami", code_zone="FBC",
        )
        db.add(prop)
        db.flush()
        from core.proposal import generate_accept_token
        proposal = Proposal(
            tenant_id=tenant_id, customer_id=cust.id, property_id=prop.id,
            title="Job Proposal", quote_snapshot={},
            accept_token=generate_accept_token(),
            status="accepted", version_number=1, created_by="staff@example.com",
        )
        db.add(proposal)
        db.flush()
        job = Job(
            tenant_id=tenant_id,
            proposal_id=proposal.id,
            status="pending",
        )
        db.add(job)
        db.flush()
        assert job.id is not None
        assert job.status == "pending"

    def test_job_status_default_pending(self, db, tenant_id):
        job = Job(tenant_id=tenant_id)
        db.add(job)
        db.flush()
        assert job.status == "pending"


class TestCatalogItemRoundTrip:
    def test_insert_catalog_item(self, db, tenant_id):
        item = CatalogItem(
            tenant_id=tenant_id,
            name="Ridge Vent",
            unit="LF",
            unit_price=8.50,
            knowify_item_id="KW-001",
        )
        db.add(item)
        db.flush()
        assert item.id is not None
        assert item.unit_price == 8.50


class TestTcVersionRoundTrip:
    def test_insert_tc_version(self, db, tenant_id):
        tc = TcVersion(
            tenant_id=tenant_id,
            version_tag="v1.0",
            content_gcs="gs://bucket/tc/v1.pdf",
        )
        db.add(tc)
        db.flush()
        assert tc.id is not None
        assert tc.version_tag == "v1.0"


# ---------------------------------------------------------------------------
# TenantMixin verification
# ---------------------------------------------------------------------------

class TestTenantMixin:
    """Verify all F3 models use TenantMixin (have tenant_id from the mixin)."""

    def test_all_f3_models_have_tenant_id(self):
        from core.tenant import TenantMixin
        f3_models = [
            Customer, Contact, Property, ProposalTemplate, Proposal,
            ProposalEvent, Lead, Job, CatalogItem, TcVersion,
        ]
        for model in f3_models:
            assert issubclass(model, TenantMixin), (
                f"{model.__name__} must inherit TenantMixin"
            )
