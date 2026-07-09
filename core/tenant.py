"""Tenant isolation primitives.

TenantMixin — attach to every new ORM model to get tenant_id + the F4 seam.
TenantSession — thin wrapper that will issue SET LOCAL in F4; in F0 it is a
                no-op so the existing SessionLocal continues to work unchanged.
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import Session


class TenantMixin:
    """Mixin that adds tenant_id to a SQLAlchemy model.

    Usage (new tables, F2+):
        class MyModel(Base, TenantMixin):
            __tablename__ = "my_table"
            ...

    Existing tables are backfilled via migration 0013; their model classes
    gain the column declaration below without needing this mixin (the mixin
    is for NEW tables going forward).  Existing models will be updated to
    inherit TenantMixin in a follow-up cleanup so the column is declared in
    one place.
    """
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id"),
        nullable=False,
        default=1,
        index=False,
    )


def set_tenant_context(session: Session, tenant_id: int) -> None:
    """Seam for F4's RLS session pattern.

    In F0 this is a documented no-op. Per the F0 R2 contract amendment
    (TRD-F0 §10.2), F4 plumbs the single call site in the shared session
    dependency as its first step, together with filling in this body.

    F4 implementation (do NOT implement here):
        session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id})
    """
    pass


class TenantQueryMixin:
    """ORM query helper — belt (complements F4's RLS suspenders).

    Usage in service layer:
        rows = session.query(Article).filter(
            *TenantQueryMixin.tenant_filter(Article, tenant_id)
        ).all()

    F4 will additionally rely on RLS; this filter stays as defense-in-depth.
    """
    @staticmethod
    def tenant_filter(model_cls, tenant_id: int):
        return (model_cls.tenant_id == tenant_id,)
