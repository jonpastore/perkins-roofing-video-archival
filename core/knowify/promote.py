"""First-class promotion + ledger synthesis (Wave 3 — MONEY PATH, TRD §2c).

Promotes Knowify raw records into our own tables (Customer, PriceBookItem,
Invoice, Payment) and synthesizes the job_billing_events the derived invoice
status reads. No network here — callers pass already-fetched record dicts and an
already-stamped SQLAlchemy Session (tenant_id in session.info; RLS GUC fires on
Postgres via the after_begin event).

MONEY UNITS: the REST /api/v2 layer returns DOLLARS. Amounts map STRAIGHT to
NUMERIC(12,2) — there is NO ÷100 anywhere in this module. A stray ÷100 would make
every amount 100× too small.

Imports carry source='knowify_import' and invoice_number=NULL; the string
Knowify InvoiceNumber lands in invoices.knowify_invoice_number (TEXT). The
importer NEVER writes tenant_invoice_counters and NEVER touches native
source='api' ledger events.

Ordering precondition: clients must be promoted before invoices (invoices.customer_id
is NOT NULL; _customer_id_for returns None when the client is missing). Use
promote_run which enforces the FK-safe order: clients → items → invoices → payments.

Ledger recovery (only supported repair path for imported events):
    DELETE FROM job_billing_events
    WHERE tenant_id = :t AND idempotency_key LIKE 'knowify:%';
then re-run the sync.
"""
from __future__ import annotations

import logging
from decimal import InvalidOperation
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from core.invoicing import _money, derive_invoice_status

log = logging.getLogger(__name__)

_IMPORT_SOURCE = "knowify_import"
# Sentinel knowify_job_id for invoices that have no Knowify ProjectId.
# Using a fixed string (not NULL) so it is covered by the partial-unique index
# on (tenant_id, knowify_job_id) WHERE knowify_job_id IS NOT NULL.
_PLACEHOLDER_JID = "__knowify_placeholder__"

# Invoice statuses allowed by the CHECK constraint / ORM enum (0030).
# derive_invoice_status may also return 'voided_after_payment' for a voided
# invoice that had payments; we clamp that to 'voided' for the cached column.
_ALLOWED_STATUS = frozenset(
    {"draft", "sent", "viewed", "partially_paid", "paid", "voided"}
)


def _clamp_status(status: str) -> str:
    """Map any derive_invoice_status result to a CHECK-allowed value.

    'voided_after_payment' → 'voided': the ledger + live derive still reflect the
    full picture (paid dollars visible via payment events); only the cached column
    is clamped so the UPDATE never violates the CHECK constraint.
    """
    return status if status in _ALLOWED_STATUS else "voided"


# ---------------------------------------------------------------------------
# Dialect-aware upsert helper for the crosswalk unique indexes.
# ---------------------------------------------------------------------------

def _upsert_by_crosswalk(
    session: Session,
    model: type,
    xwalk_col: str,
    xwalk_val: str,
    values: dict[str, Any],
) -> None:
    """Atomic insert-or-update keyed by (tenant_id, <xwalk_col>).

    On Postgres: uses pg_insert(...).on_conflict_do_update(...) against the
    partial-unique index so the operation is a single round-trip with no race
    (matches the api/routes/invoices.py:78-84 pattern).
    On SQLite (tests/dev): falls back to read-then-write (no partial-index
    support, but single-process, so no race).
    """
    tenant_id: int = session.info.get("tenant_id", 1)
    dialect = session.bind.dialect.name  # type: ignore[union-attr]

    if dialect == "postgresql":
        from sqlalchemy import literal_column
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(model)
            .values(tenant_id=tenant_id, **{xwalk_col: xwalk_val}, **values)
            .on_conflict_do_update(
                index_elements=["tenant_id", xwalk_col],
                index_where=literal_column(f"{xwalk_col} IS NOT NULL"),
                set_=values,
            )
        )
        session.execute(stmt)
    else:
        # SQLite fallback: read-then-write (single-process, no race).
        row = session.execute(
            select(model).where(
                getattr(model, "tenant_id") == tenant_id,
                getattr(model, xwalk_col) == xwalk_val,
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(model(**{"tenant_id": tenant_id, xwalk_col: xwalk_val, **values}))
        else:
            for k, v in values.items():
                setattr(row, k, v)
    session.flush()


# ---------------------------------------------------------------------------
# clients → Customer
# ---------------------------------------------------------------------------

def promote_clients(session: Session, records: list[dict[str, Any]]) -> int:
    """Upsert Knowify clients into customers, keyed by knowify_customer_id."""
    from app.models import Customer

    n = 0
    for rec in records:
        try:
            kid = str(rec["Id"])
            # Knowify's real field names are ClientName / PhoneNumber (verified against the
            # live schema + REST OpenAPI) — NOT "Name"/"Phone". A client with no CompanyName
            # would otherwise fall through to a "Knowify <id>" placeholder display name.
            display = rec.get("ClientName") or rec.get("CompanyName") or f"Knowify {kid}"
            _upsert_by_crosswalk(session, Customer, "knowify_customer_id", kid, {
                "display_name": display,
                "company_name": rec.get("CompanyName"),
                "email": rec.get("Email"),
                "phone": rec.get("PhoneNumber"),
                # Knowify ObjectState → our is_active (Inactive/Cancelled/Deleted -> False).
                "is_active": rec.get("ObjectState", "Active") == "Active",
            })
            n += 1
            log.debug("knowify promote: client id=%s", kid)
        except Exception as exc:
            kid = str(rec.get("Id", "unknown"))
            log.error("knowify promote: client id=%s error=%s", kid, type(exc).__name__)
    return n


# ---------------------------------------------------------------------------
# clients/contacts/projects → Contact + Property
# ---------------------------------------------------------------------------

def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _clean_str_max(value: Any, max_len: int) -> str | None:
    s = _clean_str(value)
    return s[:max_len] if s else None


def _norm(value: Any) -> str:
    return (_clean_str(value) or "").casefold()


def _state(value: Any) -> str:
    return (_clean_str(value) or "FL").upper()[:2]


def _contact_name(rec: dict[str, Any], fallback: str) -> str:
    return (
        _clean_str(rec.get("ContactName"))
        or _clean_str(rec.get("ClientName"))
        or _clean_str(rec.get("CompanyName"))
        or _clean_str(rec.get("Email"))
        or fallback
    )


def promote_client_contacts(session: Session, records: list[dict[str, Any]]) -> int:
    """Promote the primary contact fields embedded on Knowify Clients.

    Knowify has very few rows in its separate Contacts table for Perkins; most usable
    contact data lives directly on Clients. Synthetic ids are stable and namespaced so
    reruns update in place instead of duplicating contacts.
    """
    from app.models import Contact

    n = 0
    customer_map = _customer_ids_for(session, {str(r["Id"]) for r in records if r.get("Id") is not None})
    source_keys = {f"client:{kid}:primary" for kid in customer_map}
    existing = {
        row.knowify_contact_id: row
        for row in session.execute(
            select(Contact).where(
                Contact.tenant_id == session.info.get("tenant_id", 1),
                Contact.knowify_contact_id.in_(source_keys),
            )
        ).scalars().all()
    } if source_keys else {}
    for rec in records:
        kid = str(rec.get("Id", "unknown"))
        try:
            kid = str(rec["Id"])
            email = _clean_str(rec.get("Email"))
            phone = _clean_str(rec.get("PhoneNumberMobile")) or _clean_str(rec.get("PhoneNumber"))
            name = _contact_name(rec, f"Knowify client {kid}")
            if not (name or email or phone):
                continue
            customer_id = customer_map.get(kid)
            if customer_id is None:
                continue
            xkey = f"client:{kid}:primary"
            row = existing.get(xkey)
            if row is None:
                session.add(Contact(
                    tenant_id=session.info.get("tenant_id", 1),
                    knowify_contact_id=xkey,
                    customer_id=customer_id,
                    name=name,
                    role="Primary",
                    email=email,
                    phone=phone,
                    is_primary=True,
                ))
            else:
                row.customer_id = customer_id
                row.name = name
                row.role = "Primary"
                row.email = email
                row.phone = phone
                row.is_primary = True
            n += 1
            log.debug("knowify promote: client-contact id=%s", kid)
        except Exception as exc:
            log.error("knowify promote: client-contact id=%s error=%s", kid, type(exc).__name__)
    session.flush()
    return n


def promote_contacts(session: Session, records: list[dict[str, Any]]) -> int:
    """Upsert Knowify Contacts into native contacts keyed by knowify_contact_id."""
    from app.models import Contact

    n = 0
    active = [r for r in records if r.get("ObjectState", "Active") == "Active" and r.get("ClientId") is not None]
    customer_map = _customer_ids_for(session, {str(r["ClientId"]) for r in active})
    source_keys = {str(r["Id"]) for r in active if r.get("Id") is not None}
    existing = {
        row.knowify_contact_id: row
        for row in session.execute(
            select(Contact).where(
                Contact.tenant_id == session.info.get("tenant_id", 1),
                Contact.knowify_contact_id.in_(source_keys),
            )
        ).scalars().all()
    } if source_keys else {}
    for rec in records:
        kid = str(rec.get("Id", "unknown"))
        try:
            if rec.get("ObjectState", "Active") != "Active":
                continue
            if rec.get("ClientId") is None:
                continue  # vendor/global contacts are not customer contacts
            kid = str(rec["Id"])
            customer_id = customer_map.get(str(rec["ClientId"]))
            if customer_id is None:
                continue
            name = _contact_name(rec, f"Knowify contact {kid}")
            email = _clean_str(rec.get("Email"))
            phone = _clean_str(rec.get("Phone"))
            row = existing.get(kid)
            if row is None:
                session.add(Contact(
                    tenant_id=session.info.get("tenant_id", 1),
                    knowify_contact_id=kid,
                    customer_id=customer_id,
                    name=name,
                    role=None,
                    email=email,
                    phone=phone,
                    is_primary=False,
                ))
            else:
                row.customer_id = customer_id
                row.name = name
                row.role = None
                row.email = email
                row.phone = phone
                row.is_primary = False
            n += 1
            log.debug("knowify promote: contact id=%s", kid)
        except Exception as exc:
            log.error("knowify promote: contact id=%s error=%s", kid, type(exc).__name__)
    session.flush()
    return n


def _address_values(rec: dict[str, Any]) -> dict[str, str | None] | None:
    street = _clean_str(rec.get("Address1"))
    city = _clean_str(rec.get("City"))
    if not street or not city:
        return None
    return {
        "street": street[:255],
        "city": city[:100],
        "state": _state(rec.get("StateProvince") or rec.get("State")),
        "zip": _clean_str_max(rec.get("Zip"), 10),
    }


def _property_key(customer_id: int, values: dict[str, str | None]) -> tuple[int, str, str, str, str]:
    return (
        customer_id,
        _norm(values["street"]),
        _norm(values["city"]),
        _state(values["state"]),
        _norm(values.get("zip")),
    )


def promote_properties(
    session: Session,
    *,
    projects: list[dict[str, Any]] | None = None,
    clients: list[dict[str, Any]] | None = None,
) -> int:
    """Promote Knowify project/client addresses into native properties.

    Knowify's `Roofs` table is empty for Perkins, so this intentionally creates
    property/address rows only. Measurements remain sourced from Roofr/manual entry.
    """
    from app.models import Property

    tenant_id: int = session.info.get("tenant_id", 1)
    n = 0
    seen: set[tuple[int, str, str, str, str]] = set()
    client_ids = {str(r["Id"]) for r in clients or [] if r.get("Id") is not None}
    client_ids |= {str(r["ClientId"]) for r in projects or [] if r.get("ClientId") is not None}
    customer_map = _customer_ids_for(session, client_ids)

    existing_rows = session.execute(
        select(Property).where(
            Property.tenant_id == tenant_id,
            Property.customer_id.in_(list(customer_map.values()) or [-1]),
        )
    ).scalars().all()
    existing_keys = {
        _property_key(prop.customer_id, {
            "street": prop.street,
            "city": prop.city,
            "state": prop.state,
            "zip": prop.zip,
        })
        for prop in existing_rows
    }

    for rec in projects or []:
        kid = str(rec.get("Id", "unknown"))
        try:
            if rec.get("ClientId") is None:
                continue
            values = _address_values(rec)
            if values is None:
                continue
            knowify_customer_id = str(rec["ClientId"])
            customer_id = customer_map.get(knowify_customer_id)
            if customer_id is None:
                continue
            key = _property_key(customer_id, values)
            if key in seen or key in existing_keys:
                continue
            seen.add(key)
            existing_keys.add(key)
            label = _clean_str(rec.get("ProjectName"))
            note = f"Knowify project {kid}" + (f": {label}" if label else "")
            session.add(Property(
                tenant_id=tenant_id,
                customer_id=customer_id,
                street=values["street"] or "",
                city=values["city"] or "",
                state=values["state"] or "FL",
                zip=values.get("zip"),
                code_zone="FBC",
                knowify_customer_id=knowify_customer_id,
                notes=note,
            ))
            n += 1
            log.debug("knowify promote: project-property id=%s", kid)
        except Exception as exc:
            log.error("knowify promote: project-property id=%s error=%s", kid, type(exc).__name__)

    for rec in clients or []:
        kid = str(rec.get("Id", "unknown"))
        try:
            kid = str(rec["Id"])
            values = _address_values(rec)
            if values is None:
                continue
            customer_id = customer_map.get(kid)
            if customer_id is None:
                continue
            key = _property_key(customer_id, values)
            if key in seen or key in existing_keys:
                continue
            seen.add(key)
            existing_keys.add(key)
            session.add(Property(
                tenant_id=tenant_id,
                customer_id=customer_id,
                street=values["street"] or "",
                city=values["city"] or "",
                state=values["state"] or "FL",
                zip=values.get("zip"),
                code_zone="FBC",
                knowify_customer_id=kid,
                notes=f"Knowify client address {kid}",
            ))
            n += 1
            log.debug("knowify promote: client-property id=%s", kid)
        except Exception as exc:
            log.error("knowify promote: client-property id=%s error=%s", kid, type(exc).__name__)

    session.flush()
    return n


# ---------------------------------------------------------------------------
# items → PriceBookItem (NO stale OurCost — v2 pricing is authoritative)
# ---------------------------------------------------------------------------

def promote_items(session: Session, records: list[dict[str, Any]]) -> int:
    """Upsert Knowify items into price_book_items, keyed by knowify_item_id.

    Input is Knowify's ServiceCatalogItems schema (verified live via MCP):
    Name, ItemNumber, UnitName, Price, OurCost, ...

    Only name/sku/unit/unit_price are mapped. ItemNumber is the SKU/code, UnitName
    is the display unit, and Price is the sell price. Knowify's OurCost is NEVER
    imported (v2 pricing is authoritative — TRD/PRD; Tim's sheet owns costs).
    """
    from app.models import PriceBookItem

    n = 0
    for rec in records:
        try:
            kid = str(rec["Id"])
            up = rec.get("Price")
            _upsert_by_crosswalk(session, PriceBookItem, "knowify_item_id", kid, {
                "name": rec.get("Name") or f"Knowify item {kid}",
                "sku": rec.get("ItemNumber"),
                "unit": rec.get("UnitName"),
                "unit_price": _money(up) if up is not None else None,
            })
            n += 1
            log.debug("knowify promote: item id=%s", kid)
        except Exception as exc:
            kid = str(rec.get("Id", "unknown"))
            log.error("knowify promote: item id=%s error=%s", kid, type(exc).__name__)
    return n


# ---------------------------------------------------------------------------
# invoices → Invoice + ledger synthesis (§2c)
# ---------------------------------------------------------------------------

def _customer_id_for(session: Session, knowify_client_id: str | None) -> int | None:
    """Resolve our customers.id for a Knowify ClientId, creating a minimal placeholder
    customer on first sight if the client wasn't promoted (invoices.customer_id is NOT
    NULL, and Knowify invoices can reference inactive/deleted clients the clients pull
    excluded). The real name backfills on a later clients sync that includes them.
    Returns None only when the invoice truly carries no ClientId."""
    if knowify_client_id is None:
        return None
    from app.models import Customer

    tenant_id: int = session.info.get("tenant_id", 1)
    kid = str(knowify_client_id)
    existing = session.execute(
        select(Customer.id).where(
            Customer.tenant_id == tenant_id,
            Customer.knowify_customer_id == kid,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    # Orphan (client not in the pull — typically inactive/deleted in Knowify): placeholder
    # marked inactive; a later clients sync that includes it backfills the real name/state.
    cust = Customer(tenant_id=tenant_id, knowify_customer_id=kid,
                    display_name=f"Knowify {kid}", is_active=False)
    session.add(cust)
    session.flush()
    return cust.id


def _customer_ids_for(session: Session, knowify_client_ids: set[str]) -> dict[str, int]:
    """Resolve many Knowify ClientIds to customer ids with one query.

    Missing ids are materialized as the same inactive placeholders used by
    _customer_id_for. This avoids thousands of per-row SELECTs during backfills.
    """
    from app.models import Customer

    tenant_id: int = session.info.get("tenant_id", 1)
    ids = {str(i) for i in knowify_client_ids if i is not None}
    if not ids:
        return {}
    rows = session.execute(
        select(Customer.knowify_customer_id, Customer.id).where(
            Customer.tenant_id == tenant_id,
            Customer.knowify_customer_id.in_(ids),
        )
    ).all()
    out = {str(k): int(v) for k, v in rows if k is not None}
    missing = ids - set(out)
    for kid in missing:
        cust = Customer(tenant_id=tenant_id, knowify_customer_id=kid,
                        display_name=f"Knowify {kid}", is_active=False)
        session.add(cust)
        session.flush()
        out[kid] = cust.id
    return out


def _job_id_for(session: Session, knowify_project_id: str | None) -> int:
    """Resolve our jobs.id for a Knowify ProjectId via the knowify_job_id crosswalk,
    creating a minimal stub Job on first sight (invoices.job_id is NOT NULL).

    Project-less invoices get a sentinel Job (knowify_job_id=_PLACEHOLDER_JID) so
    the crosswalk unique index covers the placeholder and re-syncs reuse one row.
    """
    from app.models import Job

    tenant_id: int = session.info.get("tenant_id", 1)
    kjid = str(knowify_project_id) if knowify_project_id is not None else _PLACEHOLDER_JID

    existing = session.execute(
        select(Job.id).where(
            Job.tenant_id == tenant_id,
            Job.knowify_job_id == kjid,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = Job(tenant_id=tenant_id, knowify_job_id=kjid, status="knowify_import")
    session.add(job)
    session.flush()
    return job.id


def _events_for(session: Session, invoice_id: int) -> list[dict]:
    from app.models import JobBillingEvent

    rows = session.execute(
        select(
            JobBillingEvent.event_type,
            JobBillingEvent.payload,
            JobBillingEvent.idempotency_key,
        ).where(JobBillingEvent.invoice_id == invoice_id)
    ).all()
    return [{"event_type": r[0], "payload": r[1] or {}, "idempotency_key": r[2]} for r in rows]


def _delete_import_event(session: Session, tenant_id: int, idempotency_key: str) -> None:
    """Delete one imported ledger event by key (bounded to source='knowify_import').
    Never touches native source='api' events.
    """
    from app.models import JobBillingEvent

    session.execute(
        delete(JobBillingEvent).where(
            JobBillingEvent.tenant_id == tenant_id,
            JobBillingEvent.idempotency_key == idempotency_key,
            JobBillingEvent.source == _IMPORT_SOURCE,
        )
    )


def _sync_import_event(
    session: Session,
    *,
    idempotency_key: str,
    invoice_id: int,
    job_id: int | None,
    event_type: str,
    payload: dict,
    upsert_on_change: bool,
) -> None:
    """Ensure exactly one imported ledger event with this key exists.

    Immutable facts (invoice_issued / invoice_voided) → insert once, else no-op.
    The net payment_recorded → upsert-on-change: delete-then-insert the single
    imported row ONLY when its payload changed (bounded to one row per invoice).

    NEVER touches native source='api' events — every query is scoped to
    source='knowify_import' AND this exact idempotency_key.
    """
    from app.models import JobBillingEvent

    tenant_id: int = session.info.get("tenant_id", 1)
    existing = session.execute(
        select(JobBillingEvent.id, JobBillingEvent.payload).where(
            JobBillingEvent.tenant_id == tenant_id,
            JobBillingEvent.idempotency_key == idempotency_key,
            JobBillingEvent.source == _IMPORT_SOURCE,
        )
    ).fetchone()

    if existing is not None:
        if not upsert_on_change:
            return  # immutable fact — already present, no-op
        if (existing[1] or {}) == payload:
            return  # unchanged — no-op
        # paid changed → replace the single imported row (delete + insert).
        _delete_import_event(session, tenant_id, idempotency_key)

    session.execute(
        insert(JobBillingEvent).values(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            job_id=job_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            source=_IMPORT_SOURCE,
        )
    )
    session.flush()


def promote_invoices(session: Session, records: list[dict[str, Any]]) -> int:
    """Upsert Knowify invoices (regular only) and synthesize their ledger events.

    Money in DOLLARS, no ÷100. String InvoiceNumber → knowify_invoice_number;
    integer invoice_number stays NULL; source='knowify_import'. The counter is
    never written. Status is cached from the synthesized ledger via
    derive_invoice_status; the ledger stays source of truth.

    Precondition: clients must be promoted first (customer_id NOT NULL FK).
    """
    from app.models import Invoice

    tenant_id: int = session.info.get("tenant_id", 1)
    n = 0
    for rec in records:
        kiid = str(rec.get("Id", ""))
        try:
            kiid = str(rec["Id"])
            total = _money(rec["TotalAmount"])
            outstanding = _money(rec["OutstandingAmount"])
            paid = _money(total - outstanding)
            object_state = rec.get("ObjectState", "Active")
            business_state = rec.get("BusinessState", "Draft")
            is_voided = object_state in ("Cancelled", "Deleted")

            job_id = _job_id_for(session, rec.get("ProjectId"))
            _upsert_by_crosswalk(session, Invoice, "knowify_invoice_id", kiid, {
                "knowify_invoice_number": str(rec["InvoiceNumber"]) if rec.get("InvoiceNumber") is not None else None,
                "invoice_number": None,                       # never the integer counter
                "source": _IMPORT_SOURCE,
                "job_id": job_id,
                "customer_id": _customer_id_for(session, rec.get("ClientId")),
                "total": total,
                "subtotal": total,
                "invoice_date": _parse_date(rec.get("InvoiceDate")),
                "due_date": _parse_date(rec.get("DueDate")),
                "created_by": _IMPORT_SOURCE,
            })

            inv = session.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.knowify_invoice_id == kiid,
                )
            ).scalar_one()

            issue_key = f"knowify:issue:{tenant_id}:{kiid}"
            pay_key = f"knowify:payment:{tenant_id}:{kiid}"
            void_key = f"knowify:void:{tenant_id}:{kiid}"

            # invoice_issued — immutable, insert-once.
            if business_state != "Draft":
                _sync_import_event(
                    session,
                    idempotency_key=issue_key,
                    invoice_id=inv.id,
                    job_id=inv.job_id,
                    event_type="invoice_issued",
                    payload={},
                    upsert_on_change=False,
                )

            # ONE net payment_recorded — upsert-on-change.
            # Total==0: treat as fully settled (no payment event needed).
            # paid==0 after a refund/reversal: delete any stale event so status reverts.
            if paid > 0 and total > 0:
                _sync_import_event(
                    session,
                    idempotency_key=pay_key,
                    invoice_id=inv.id,
                    job_id=inv.job_id,
                    event_type="payment_recorded",
                    payload={"amount": str(paid)},
                    upsert_on_change=True,
                )
            else:
                # paid==0 (refund/reversal) or total==0 — remove any stale net event.
                _delete_import_event(session, tenant_id, pay_key)

            # invoice_voided — managed symmetrically:
            # Cancelled/Deleted → insert once (immutable once set).
            # Active (un-void) → delete any stale void event so status recomputes.
            if is_voided:
                _sync_import_event(
                    session,
                    idempotency_key=void_key,
                    invoice_id=inv.id,
                    job_id=inv.job_id,
                    event_type="invoice_voided",
                    payload={},
                    upsert_on_change=False,
                )
            else:
                _delete_import_event(session, tenant_id, void_key)

            # Cache derived status — clamped to the CHECK-allowed set.
            # Special case: Total==0 invoices cannot be expressed as 'paid' via the
            # ledger (derive requires paid>=tot and tot>0), so we infer from BusinessState.
            # 'voided_after_payment' → stored as 'voided' (CHECK constraint clamp).
            if total == 0 and not is_voided:
                cached_status = "paid" if business_state == "Closed" else "sent"
            else:
                raw_status = derive_invoice_status(_events_for(session, inv.id), inv.total)
                cached_status = _clamp_status(raw_status)
            session.execute(
                update(Invoice).where(Invoice.id == inv.id).values(status=cached_status)
            )
            session.flush()
            n += 1
            log.debug("knowify promote: invoice id=%s status=%s", kiid, cached_status)
        except (KeyError, InvalidOperation, Exception) as exc:
            log.error("knowify promote: invoice id=%s error=%s", kiid, type(exc).__name__)
    return n


# ---------------------------------------------------------------------------
# payments → Payment (receivables only)
# ---------------------------------------------------------------------------

def _is_receivable(rec: dict[str, Any]) -> bool:
    """Receivables-only filter (§2f): exclude vendor payables, AIA, voided,
    and non-active payments."""
    if rec.get("PayableId") is not None or rec.get("VendorId") is not None:
        return False
    if rec.get("isAIA") or rec.get("InvoiceAIAId") is not None:
        return False
    if rec.get("Voided"):
        return False
    if rec.get("ObjectState", "Active") != "Active":
        return False
    if rec.get("InvoiceId") is None and rec.get("ReceivableId") is None:
        return False
    return True


def _payment_method(rec: dict[str, Any]) -> str:
    if rec.get("isCreditCard"):
        return "card"
    if rec.get("CheckNumber") or rec.get("QBCheck"):
        return "check"
    return "other"


def promote_payments(session: Session, records: list[dict[str, Any]]) -> int:
    """Upsert receivable Knowify payments into payments, keyed by
    knowify_payment_id. Amount in DOLLARS, no ÷100. Does NOT drive invoice
    status (that is OutstandingAmount-derived on the invoice side)."""
    from app.models import Invoice, Payment

    tenant_id: int = session.info.get("tenant_id", 1)
    n = 0
    for rec in records:
        kid = str(rec.get("Id", "unknown"))
        try:
            if not _is_receivable(rec):
                continue
            kid = str(rec["Id"])
            invoice_id = session.execute(
                select(Invoice.id).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.knowify_invoice_id == str(rec["InvoiceId"]),
                )
            ).scalar_one_or_none()
            if invoice_id is None:
                log.warning("knowify promote: payment id=%s skipped (no mirrored invoice)", kid)
                continue

            pdate = _parse_date(rec.get("PaymentDate"))
            values: dict[str, Any] = {
                "invoice_id": invoice_id,
                "amount": _money(rec["Amount"]),
                "method": _payment_method(rec),
                "reference": rec.get("CheckNumber"),
                "notes": rec.get("Memo"),
            }
            if pdate is not None:
                values["payment_date"] = pdate

            _upsert_by_crosswalk(session, Payment, "knowify_payment_id", kid, values)
            n += 1
            log.debug("knowify promote: payment id=%s", kid)
        except Exception as exc:
            log.error("knowify promote: payment id=%s error=%s", kid, type(exc).__name__)
    return n


def _parse_date(raw: str | None):
    """Parse a Knowify ISO PaymentDate ('YYYY-MM-DD' or full ISO). None/garbage → None."""
    from datetime import datetime

    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "").split("+")[0])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Orchestration — FK-safe order: clients → invoices → payments (§2d)
# ---------------------------------------------------------------------------

def promote_run(
    session: Session,
    *,
    clients: list[dict] | None = None,
    contacts: list[dict] | None = None,
    projects: list[dict] | None = None,
    items: list[dict] | None = None,
    invoices: list[dict] | None = None,
    payments: list[dict] | None = None,
) -> dict[str, int]:
    """Promote a full set in FK-safe order (payments.invoice_id NOT NULL FK).

    Items promote independently (no FK to the above).
    """
    counts = {"clients": 0, "contacts": 0, "properties": 0, "items": 0, "invoices": 0, "payments": 0}
    if clients:
        counts["clients"] = promote_clients(session, clients)
        counts["contacts"] += promote_client_contacts(session, clients)
        counts["properties"] += promote_properties(session, clients=clients)
    if contacts:
        counts["contacts"] += promote_contacts(session, contacts)
    if projects:
        counts["properties"] += promote_properties(session, projects=projects)
    if items:
        counts["items"] = promote_items(session, items)
    if invoices:
        counts["invoices"] = promote_invoices(session, invoices)
    if payments:
        counts["payments"] = promote_payments(session, payments)
    return counts
