"""Quoting — Customers, Contacts, Properties CRUD.

Endpoints:
  GET    /quoting/customers               list customers (tenant-scoped, paginated, search/filter/sort)
  POST   /quoting/customers               create customer
  GET    /quoting/customers/{id}          get customer + contacts + properties
  PUT    /quoting/customers/{id}          update customer
  PATCH  /quoting/customers/{id}/deactivate  soft-deactivate (is_active=False)
  POST   /quoting/customers/{id}/contacts add contact
  POST   /quoting/customers/{id}/properties add property
  PUT    /quoting/properties/{id}         update property

Authz:
  quoting_view   → GET endpoints + deactivate
  quoting_create → POST / PUT
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Contact, Customer, Measurement, Property

router = APIRouter(prefix="/quoting", tags=["quoting_customers"])


def _tenant_id(db: Session) -> int:
    """Resolved (verified) tenant for this request — stamped onto the session by
    get_db_session from the caller's verified claims. Never a hardcoded literal."""
    return db.info["tenant_id"]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CustomerCreate(BaseModel):
    display_name: str
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    knowify_customer_id: Optional[str] = None
    notes: Optional[str] = None


class CustomerUpdate(BaseModel):
    display_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class ContactCreate(BaseModel):
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_primary: bool = False


class PropertyCreate(BaseModel):
    street: str
    city: str
    state: str = "FL"
    zip: Optional[str] = None
    county: Optional[str] = None
    code_zone: str = "FBC"
    notes: Optional[str] = None


class PropertyUpdate(BaseModel):
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    county: Optional[str] = None
    code_zone: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _customer_row(
    row: Customer,
    *,
    property_count: int | None = None,
    measurement_count: int | None = None,
) -> dict:
    data = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "display_name": row.display_name,
        "company_name": row.company_name,
        "email": row.email,
        "phone": row.phone,
        "knowify_customer_id": row.knowify_customer_id,
        "is_active": row.is_active,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if property_count is not None:
        data["property_count"] = property_count
        data["has_properties"] = property_count > 0
    if measurement_count is not None:
        data["measurement_count"] = measurement_count
        data["has_measurements"] = measurement_count > 0
    return data


def _contact_row(row: Contact) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "customer_id": row.customer_id,
        "name": row.name,
        "role": row.role,
        "email": row.email,
        "phone": row.phone,
        "is_primary": row.is_primary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _property_row(
    row: Property,
    *,
    measurement_count: int | None = None,
    latest_measurement_total_sq: float | None = None,
) -> dict:
    data = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "customer_id": row.customer_id,
        "street": row.street,
        "city": row.city,
        "state": row.state,
        "zip": row.zip,
        "county": row.county,
        "code_zone": row.code_zone,
        "notes": row.notes,
        "gcs_pdf_prefix": row.gcs_pdf_prefix,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if measurement_count is not None:
        data["measurement_count"] = measurement_count
        data["has_measurements"] = measurement_count > 0
        data["latest_measurement_total_sq"] = latest_measurement_total_sq
    return data


def _property_measurement_summary(
    db: Session, tenant_id: int, property_ids: list[int]
) -> dict[int, dict]:
    """Per-property measurement rollup: count + latest total_sq.

    Measurements link to properties via Measurement.property_id. Returns a map of
    property_id -> {"measurement_count", "latest_measurement_total_sq"} for the
    supplied ids (only ids with >=1 measurement appear). "latest" is by id desc
    (measurement ids are monotonic per the autoincrement PK)."""
    if not property_ids:
        return {}
    rows = db.execute(
        select(
            Measurement.property_id,
            func.count(Measurement.id),
            func.max(Measurement.id),
        )
        .where(
            Measurement.tenant_id == tenant_id,
            Measurement.property_id.in_(property_ids),
        )
        .group_by(Measurement.property_id)
    ).all()
    summary: dict[int, dict] = {}
    latest_ids: dict[int, int] = {}
    for prop_id, count, max_id in rows:
        summary[prop_id] = {"measurement_count": int(count)}
        if max_id is not None:
            latest_ids[prop_id] = max_id
    if latest_ids:
        totals = dict(
            db.execute(
                select(Measurement.id, Measurement.total_sq).where(
                    Measurement.tenant_id == tenant_id,
                    Measurement.id.in_(list(latest_ids.values()))
                )
            ).all()
        )
        for prop_id, mid in latest_ids.items():
            summary[prop_id]["latest_measurement_total_sq"] = totals.get(mid)
    return summary


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------

# Sortable columns whitelist for customers list
_CUSTOMER_SORT_COLS = {
    "display_name": Customer.display_name,
    "company_name": Customer.company_name,
    "email": Customer.email,
    "created_at": Customer.created_at,
    "updated_at": Customer.updated_at,
}


@router.get("/customers")
def list_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    page: Optional[int] = Query(None, ge=1),
    search: Optional[str] = Query(None, description="Case-insensitive match on display_name/company_name/email/phone"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    sort: str = Query("display_name", description="Column to sort by"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    """List customers with optional search, is_active filter, sort, and pagination.

    Returns {items: [...], total: N} for pagination support.
    The search param does a case-insensitive substring match across display_name,
    company_name, email, and phone using func.lower() so it works on both SQLite and PG.
    """
    tenant_id = _tenant_id(db)
    offset = (page - 1) * limit if page is not None else skip

    sort_col = _CUSTOMER_SORT_COLS.get(sort, Customer.display_name)
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()

    filters = [Customer.tenant_id == tenant_id]

    if is_active is not None:
        filters.append(Customer.is_active == is_active)

    if search:
        term = search.lower()
        filters.append(
            func.lower(Customer.display_name).contains(term)
            | func.lower(Customer.company_name).contains(term)
            | func.lower(Customer.email).contains(term)
            | func.lower(Customer.phone).contains(term)
        )

    property_counts = (
        select(
            Property.customer_id.label("customer_id"),
            func.count(Property.id).label("property_count"),
        )
        .where(Property.tenant_id == tenant_id)
        .group_by(Property.customer_id)
        .subquery()
    )
    measurement_counts = (
        select(
            Property.customer_id.label("customer_id"),
            func.count(Measurement.id).label("measurement_count"),
        )
        .join(Measurement, Measurement.property_id == Property.id)
        .where(Property.tenant_id == tenant_id, Measurement.tenant_id == tenant_id)
        .group_by(Property.customer_id)
        .subquery()
    )

    total = db.execute(select(func.count()).select_from(Customer).where(*filters)).scalar_one()
    rows = db.execute(
        select(
            Customer,
            func.coalesce(property_counts.c.property_count, 0),
            func.coalesce(measurement_counts.c.measurement_count, 0),
        )
        .outerjoin(property_counts, property_counts.c.customer_id == Customer.id)
        .outerjoin(measurement_counts, measurement_counts.c.customer_id == Customer.id)
        .where(*filters)
        .order_by(sort_expr)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [
            _customer_row(
                customer,
                property_count=int(property_count),
                measurement_count=int(measurement_count),
            )
            for customer, property_count, measurement_count in rows
        ],
        "total": total,
    }


@router.post("/customers")
def create_customer(
    body: CustomerCreate,
    _claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    row = Customer(
        tenant_id=tenant_id,
        display_name=body.display_name,
        company_name=body.company_name,
        email=body.email,
        phone=body.phone,
        knowify_customer_id=body.knowify_customer_id,
        notes=body.notes,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    result = _customer_row(row)
    return result


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: int,
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Customer {customer_id} not found")

    contacts = db.execute(
        select(Contact).where(Contact.customer_id == customer_id)
    ).scalars().all()
    properties = db.execute(
        select(Property).where(Property.customer_id == customer_id)
    ).scalars().all()
    measurement_summary = _property_measurement_summary(
        db, tenant_id, [p.id for p in properties]
    )
    total_measurements = sum(
        int(s.get("measurement_count", 0)) for s in measurement_summary.values()
    )

    result = _customer_row(
        row,
        property_count=len(properties),
        measurement_count=total_measurements,
    )
    result["contacts"] = [_contact_row(c) for c in contacts]
    result["properties"] = [
        _property_row(
            p,
            measurement_count=int(
                measurement_summary.get(p.id, {}).get("measurement_count", 0)
            ),
            latest_measurement_total_sq=measurement_summary.get(p.id, {}).get(
                "latest_measurement_total_sq"
            ),
        )
        for p in properties
    ]
    return result


@router.put("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    _claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Customer {customer_id} not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.flush()
    db.refresh(row)
    return _customer_row(row)


@router.patch("/customers/{customer_id}/deactivate")
def deactivate_customer(
    customer_id: int,
    _claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    """Soft-deactivate a customer (is_active=False). NOT a hard delete.
    Invoices/history for this customer remain intact."""
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    row.is_active = False
    db.flush()
    db.refresh(row)
    return _customer_row(row)


# ---------------------------------------------------------------------------
# Contact endpoints
# ---------------------------------------------------------------------------

@router.post("/customers/{customer_id}/contacts")
def add_contact(
    customer_id: int,
    body: ContactCreate,
    _claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    cust = db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if cust is None:
        raise HTTPException(404, f"Customer {customer_id} not found")

    row = Contact(
        tenant_id=tenant_id,
        customer_id=customer_id,
        name=body.name,
        role=body.role,
        email=body.email,
        phone=body.phone,
        is_primary=body.is_primary,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return _contact_row(row)


# ---------------------------------------------------------------------------
# Property endpoints
# ---------------------------------------------------------------------------

@router.post("/customers/{customer_id}/properties")
def add_property(
    customer_id: int,
    body: PropertyCreate,
    _claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    cust = db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if cust is None:
        raise HTTPException(404, f"Customer {customer_id} not found")

    row = Property(
        tenant_id=tenant_id,
        customer_id=customer_id,
        street=body.street,
        city=body.city,
        state=body.state,
        zip=body.zip,
        county=body.county,
        code_zone=body.code_zone,
        notes=body.notes,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return _property_row(row)


@router.put("/properties/{property_id}")
def update_property(
    property_id: int,
    body: PropertyUpdate,
    _claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Property).where(
            Property.id == property_id,
            Property.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Property {property_id} not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.flush()
    db.refresh(row)
    return _property_row(row)
