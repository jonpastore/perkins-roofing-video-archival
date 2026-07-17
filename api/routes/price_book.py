"""Material price-book API (JB1 / backlog #12).

Editable material items + immutable, hash-pinned versions — the same versioning
model as pricing_configs. Editing an item mutates the LIVE working set
(price_book_id IS NULL); "save as version" freezes the live items into an immutable
PriceBook snapshot (config_hash) and activates it. Issued estimates pin the version
hash so a later price edit never retro-changes a prior estimate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import PriceBook, PriceBookItem
from core.price_book import freeze_items, next_version, price_per_square

router = APIRouter(prefix="/price-book", tags=["price-book"])
_ROLE = "estimating_manage"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _item_dict(it: PriceBookItem) -> dict:
    pps = price_per_square(it.unit_price, it.tax_rate or Decimal("0"),
                           it.waste_rate or Decimal("0"), it.unit_coverage)
    return {
        "id": it.id, "sku": it.sku, "name": it.name, "unit": it.unit,
        "unit_coverage": str(it.unit_coverage) if it.unit_coverage is not None else None,
        "unit_price": str(it.unit_price) if it.unit_price is not None else None,
        "tax_rate": str(it.tax_rate) if it.tax_rate is not None else None,
        "waste_rate": str(it.waste_rate) if it.waste_rate is not None else None,
        "supplier": it.supplier, "item_type": it.item_type,
        "knowify_item_id": it.knowify_item_id,
        "price_per_square": str(pps) if pps is not None else None,  # None = not-stocked / no coverage
    }


class ItemUpsert(BaseModel):
    name: str = Field(max_length=255)
    unit: str | None = Field(default=None, max_length=50)
    unit_coverage: str | None = None
    unit_price: str | None = None            # NULL = not stocked (never 0)
    tax_rate: str = "0.07"
    waste_rate: str = "0.10"
    supplier: str | None = Field(default=None, max_length=100)
    item_type: str | None = Field(default="material", max_length=30)
    sku: str | None = Field(default=None, max_length=100)
    knowify_item_id: str | None = Field(default=None, max_length=100)


@router.get("/items")
def list_items(claims=Depends(require_role(_ROLE)), db: Session = Depends(get_db_session)):
    """List the LIVE editable price-book items (not yet frozen into a version)."""
    rows = db.execute(
        select(PriceBookItem).where(PriceBookItem.price_book_id.is_(None)).order_by(PriceBookItem.name)
    ).scalars().all()
    return [_item_dict(it) for it in rows]


@router.post("/items")
def create_item(body: ItemUpsert, claims=Depends(require_role(_ROLE)), db: Session = Depends(get_db_session)):
    it = PriceBookItem(
        name=body.name, unit=body.unit,
        unit_coverage=body.unit_coverage, unit_price=body.unit_price,
        tax_rate=body.tax_rate, waste_rate=body.waste_rate, supplier=body.supplier,
        item_type=body.item_type, sku=body.sku, knowify_item_id=body.knowify_item_id,
        roof_system_ids=[],
    )
    db.add(it)
    db.flush()
    return _item_dict(it)


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpsert, claims=Depends(require_role(_ROLE)),
                db: Session = Depends(get_db_session)):
    """Edit a LIVE item (e.g. update unit price → price/sq recomputes). Frozen items
    (price_book_id set) are immutable and cannot be edited here."""
    it = db.get(PriceBookItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    if it.price_book_id is not None:
        raise HTTPException(409, "item belongs to a frozen version and is immutable")
    for f in ("name", "unit", "unit_coverage", "unit_price", "tax_rate", "waste_rate",
              "supplier", "item_type", "sku", "knowify_item_id"):
        setattr(it, f, getattr(body, f))
    db.flush()
    return _item_dict(it)


@router.get("/versions")
def list_versions(claims=Depends(require_role(_ROLE)), db: Session = Depends(get_db_session)):
    rows = db.execute(select(PriceBook).order_by(PriceBook.version_number.desc())).scalars().all()
    return [{"id": v.id, "supplier": v.supplier, "version_number": v.version_number,
             "label": v.label, "config_hash": v.config_hash, "is_active": v.is_active,
             "created_at": v.created_at.isoformat() if v.created_at else None} for v in rows]


class VersionCreate(BaseModel):
    supplier: str = Field(default="DEFAULT", max_length=100)
    label: str | None = None
    activate: bool = True


@router.post("/versions")
def create_version(body: VersionCreate, claims=Depends(require_role(_ROLE)),
                   db: Session = Depends(get_db_session)):
    """Freeze the current LIVE items into a new immutable, hash-pinned version.

    Snapshot + config_hash agree at freeze (belt-and-suspenders dual representation),
    and activation is atomic: deactivate the current active version, then activate the
    new one, in one transaction.
    """
    tenant_id = db.info["tenant_id"]
    live = db.execute(
        select(PriceBookItem).where(PriceBookItem.price_book_id.is_(None)).order_by(PriceBookItem.name)
    ).scalars().all()
    if not live:
        raise HTTPException(400, "no live price-book items to freeze")

    item_dicts = [{"sku": it.sku, "name": it.name, "unit": it.unit,
                   "unit_coverage": str(it.unit_coverage) if it.unit_coverage is not None else None,
                   "unit_price": str(it.unit_price) if it.unit_price is not None else None,
                   "tax_rate": str(it.tax_rate) if it.tax_rate is not None else None,
                   "waste_rate": str(it.waste_rate) if it.waste_rate is not None else None,
                   "supplier": it.supplier, "item_type": it.item_type,
                   "knowify_item_id": it.knowify_item_id} for it in live]
    snapshot, config_hash = freeze_items(item_dicts)

    max_ver = db.execute(
        select(func.max(PriceBook.version_number)).where(
            PriceBook.tenant_id == tenant_id, PriceBook.supplier == body.supplier)
    ).scalar()
    version = next_version([max_ver] if max_ver else [])

    book = PriceBook(
        supplier=body.supplier, version_number=version, label=body.label,
        items_snapshot=snapshot, config_hash=config_hash, is_active=False,
        created_by=claims.get("email") or "unknown",
    )
    db.add(book)
    db.flush()
    if body.activate:
        db.execute(update(PriceBook).where(
            PriceBook.tenant_id == tenant_id, PriceBook.supplier == body.supplier,
            PriceBook.is_active.is_(True)).values(is_active=False))
        book.is_active = True
        db.flush()
    return {"id": book.id, "supplier": book.supplier, "version_number": book.version_number,
            "config_hash": book.config_hash, "is_active": book.is_active, "item_count": len(snapshot)}
