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
from app.models import Contact, Customer, Property

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

def _customer_row(row: Customer) -> dict:
    return {
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


def _property_row(row: Property) -> dict:
    return {
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

    base = select(Customer).where(Customer.tenant_id == tenant_id)

    if is_active is not None:
        base = base.where(Customer.is_active == is_active)

    if search:
        term = search.lower()
        base = base.where(
            func.lower(Customer.display_name).contains(term)
            | func.lower(Customer.company_name).contains(term)
            | func.lower(Customer.email).contains(term)
            | func.lower(Customer.phone).contains(term)
        )

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(sort_expr).offset(offset).limit(limit)).scalars().all()
    return {"items": [_customer_row(r) for r in rows], "total": total}


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

    result = _customer_row(row)
    result["contacts"] = [_contact_row(c) for c in contacts]
    result["properties"] = [_property_row(p) for p in properties]
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
