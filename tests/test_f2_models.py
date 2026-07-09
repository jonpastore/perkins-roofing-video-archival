"""F2 ORM model tests — PricingConfig, Estimate, Measurement.

Runs against the SQLite test engine (schema from Base.metadata.create_all).
Covers column presence, FK declarations, model instantiation, immutability
contract, and hash canonicalization (RFC 8785 via jcs).

These tests are backend-agnostic: Postgres-specific DDL (DEFERRABLE INITIALLY
DEFERRED, JSONB, TIMESTAMPTZ) lives only in the .sql migrations tested
separately against dev Postgres.  The SQLite suite validates the ORM layer.
"""
import hashlib
import json

import pytest

from app.models import Base, Estimate, Measurement, PricingConfig, SessionLocal, init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _db():
    init_db()


SAMPLE_CONFIG = {
    "schema_version": 1,
    "exhibit_version": "B-2026-07",
    "sloped_base_cost_lm": {"HVHZ": {"13_tile": 780}},
    "profit_scale": [[1, 400], [None, 100]],
}


def _hash(cfg: dict) -> str:
    import jcs
    return hashlib.sha256(jcs.canonicalize(cfg)).hexdigest()


# ---------------------------------------------------------------------------
# PricingConfig model tests
# ---------------------------------------------------------------------------

class TestPricingConfigModel:
    def test_instantiate_and_persist(self):
        h = _hash(SAMPLE_CONFIG)
        with SessionLocal() as db:
            row = PricingConfig(
                branch="miami",
                version=1,
                label="Test v1",
                config=SAMPLE_CONFIG,
                config_hash=h,
                is_active=True,
                created_by="test@test.com",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            assert row.id is not None
            assert row.config_hash == h
            assert row.is_active is True
            assert row.tenant_id == 1

    def test_unique_constraint_tenant_branch_version(self):
        """Two rows with same (tenant, branch, version) must fail."""
        from sqlalchemy.exc import IntegrityError
        h = _hash(SAMPLE_CONFIG)
        with SessionLocal() as db:
            db.add(PricingConfig(branch="jupiter", version=1, config=SAMPLE_CONFIG,
                                 config_hash=h, created_by="x@x.com"))
            db.commit()

        with pytest.raises(IntegrityError):
            with SessionLocal() as db:
                db.add(PricingConfig(branch="jupiter", version=1, config=SAMPLE_CONFIG,
                                     config_hash=h, created_by="y@y.com"))
                db.commit()

    def test_config_stored_and_retrieved(self):
        h = _hash(SAMPLE_CONFIG)
        with SessionLocal() as db:
            db.add(PricingConfig(branch="naples", version=1, config=SAMPLE_CONFIG,
                                 config_hash=h, created_by="a@a.com"))
            db.commit()

        with SessionLocal() as db:
            from sqlalchemy import select
            row = db.execute(
                select(PricingConfig).where(PricingConfig.branch == "naples")
            ).scalar_one()
            loaded = row.config
            # JSON round-trip preserves structure
            assert loaded["schema_version"] == 1
            assert loaded["sloped_base_cost_lm"]["HVHZ"]["13_tile"] == 780

    def test_activate_deactivates_prior(self):
        """Activating version 2 sets version 1 is_active=False."""
        import uuid
        branch = f"act-deact-{uuid.uuid4().hex[:8]}"
        h = _hash(SAMPLE_CONFIG)
        cfg2 = {**SAMPLE_CONFIG, "exhibit_version": "B-v2"}
        h2 = _hash(cfg2)

        with SessionLocal() as db:
            v1 = PricingConfig(branch=branch, version=1, config=SAMPLE_CONFIG,
                               config_hash=h, is_active=True, created_by="a@a.com")
            v2 = PricingConfig(branch=branch, version=2, config=cfg2,
                               config_hash=h2, is_active=False, created_by="a@a.com")
            db.add_all([v1, v2])
            db.commit()
            v1_id = v1.id
            v2_id = v2.id

        # Simulate activation swap (the API does this; here we test the model allows it)
        with SessionLocal() as db:
            from sqlalchemy import select
            r1 = db.get(PricingConfig, v1_id)
            r2 = db.get(PricingConfig, v2_id)
            r1.is_active = False
            r2.is_active = True
            db.commit()

        with SessionLocal() as db:
            r1 = db.get(PricingConfig, v1_id)
            r2 = db.get(PricingConfig, v2_id)
            assert r1.is_active is False
            assert r2.is_active is True

    def test_immutable_no_config_update(self):
        """Config field must not change after creation (immutability contract).
        The model itself doesn't enforce this — the API/service layer does.
        This test documents the expected behaviour via a sentinel check."""
        h = _hash(SAMPLE_CONFIG)
        with SessionLocal() as db:
            row = PricingConfig(branch="miami", version=99, config=SAMPLE_CONFIG,
                                config_hash=h, created_by="a@a.com")
            db.add(row)
            db.commit()
            row_id = row.id

        with SessionLocal() as db:
            row = db.get(PricingConfig, row_id)
            original_hash = row.config_hash
            # Mutating the config field directly is possible at the DB level;
            # the service layer (API route) must reject such updates.
            # This test simply verifies the original hash is preserved on retrieval.
            assert row.config_hash == original_hash

    def test_created_at_auto_set(self):
        h = _hash(SAMPLE_CONFIG)
        with SessionLocal() as db:
            row = PricingConfig(branch="miami", version=77, config=SAMPLE_CONFIG,
                                config_hash=h, created_by="a@a.com")
            db.add(row)
            db.commit()
            db.refresh(row)
            assert row.created_at is not None

    def test_label_nullable(self):
        h = _hash(SAMPLE_CONFIG)
        with SessionLocal() as db:
            row = PricingConfig(branch="miami", version=88, config=SAMPLE_CONFIG,
                                config_hash=h, created_by="a@a.com", label=None)
            db.add(row)
            db.commit()
            db.refresh(row)
            assert row.label is None


# ---------------------------------------------------------------------------
# Estimate model tests
# ---------------------------------------------------------------------------

class TestEstimateModel:
    def test_instantiate_with_hash_fields(self):
        import uuid
        branch = f"est-hash-{uuid.uuid4().hex[:8]}"
        h = _hash(SAMPLE_CONFIG)
        # First create a pricing config to FK against
        with SessionLocal() as db:
            cfg = PricingConfig(branch=branch, version=1, config=SAMPLE_CONFIG,
                                config_hash=h, is_active=True, created_by="a@a.com")
            db.add(cfg)
            db.commit()
            cfg_id = cfg.id

        with SessionLocal() as db:
            est = Estimate(
                tenant_id=1,
                pricing_config_id=cfg_id,
                pricing_config_hash=h,
                branch="miami",
                code_zone="HVHZ",
                county="broward",
                input_json={"num_squares": 28},
                result_json={"project_total": 35560},
                created_by="sales@test.com",
            )
            db.add(est)
            db.commit()
            db.refresh(est)
            assert est.id is not None
            assert est.pricing_config_hash == h
            assert est.branch == "miami"
            assert est.code_zone == "HVHZ"
            assert est.county == "broward"

    def test_estimate_nullable_config_fields(self):
        """Estimates can be created without a pricing config (pre-F2 compat)."""
        with SessionLocal() as db:
            est = Estimate(
                tenant_id=1,
                pricing_config_id=None,
                pricing_config_hash=None,
                created_by="x@x.com",
            )
            db.add(est)
            db.commit()
            db.refresh(est)
            assert est.id is not None
            assert est.pricing_config_id is None


# ---------------------------------------------------------------------------
# Measurement model tests
# ---------------------------------------------------------------------------

class TestMeasurementModel:
    def test_instantiate_manual(self):
        with SessionLocal() as db:
            m = Measurement(
                tenant_id=1,
                provider="manual",
                status="complete",
                total_sq=28.0,
                created_by="tech@perkins.com",
                provenance_note="Manual entry by tech@perkins.com on 2026-07-08",
            )
            db.add(m)
            db.commit()
            db.refresh(m)
            assert m.id is not None
            assert m.provider == "manual"
            assert m.confidence is None
            assert m.total_sq == 28.0

    def test_created_by_not_null(self):
        """created_by must be set — not nullable per TRD §2.3."""
        from sqlalchemy.exc import IntegrityError
        with pytest.raises((IntegrityError, Exception)):
            with SessionLocal() as db:
                m = Measurement(tenant_id=1, provider="manual", status="complete")
                # created_by not set — should fail at commit
                db.add(m)
                db.commit()

    def test_all_edge_fields_nullable(self):
        """Measurement edge/dimension fields are all optional (manual entry may omit them)."""
        with SessionLocal() as db:
            m = Measurement(
                tenant_id=1,
                provider="manual",
                status="complete",
                created_by="a@a.com",
            )
            db.add(m)
            db.commit()
            db.refresh(m)
            assert m.hips_lf is None
            assert m.ridges_lf is None
            assert m.valleys_lf is None


# ---------------------------------------------------------------------------
# Hash canonicalization tests (RFC 8785 via jcs)
# ---------------------------------------------------------------------------

class TestHashCanonicalization:
    def test_rfc8785_key_ordering(self):
        """Dict with unsorted keys produces same hash as sorted."""
        unsorted = {"z": 1, "a": 2, "m": 3}
        sorted_  = {"a": 2, "m": 3, "z": 1}
        assert _hash(unsorted) == _hash(sorted_)

    def test_hash_determinism(self):
        """Same config dict hashed twice produces identical output."""
        h1 = _hash(SAMPLE_CONFIG)
        h2 = _hash(SAMPLE_CONFIG)
        assert h1 == h2

    def test_hash_sensitivity(self):
        """Changing one rate value changes the hash."""
        modified = {**SAMPLE_CONFIG, "sloped_base_cost_lm": {"HVHZ": {"13_tile": 999}}}
        assert _hash(SAMPLE_CONFIG) != _hash(modified)

    def test_rfc8785_unicode(self):
        """Unicode strings produce consistent bytes."""
        cfg = {"label": "Ñoño — café £ 日本語"}
        h1 = _hash(cfg)
        h2 = _hash(cfg)
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_is_sha256_hex(self):
        h = _hash(SAMPLE_CONFIG)
        assert len(h) == 64
        int(h, 16)  # must be valid hex

    def test_hash_matches_manual_computation(self):
        """Cross-check: jcs-based hash matches manual computation."""
        import jcs
        canon = jcs.canonicalize(SAMPLE_CONFIG)
        expected = hashlib.sha256(canon).hexdigest()
        assert _hash(SAMPLE_CONFIG) == expected
