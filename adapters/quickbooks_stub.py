"""QuickBooks sync seam (stubbed, no live credentials).

This module intentionally does NOT talk to QuickBooks. It defines the minimal
contract the billing path needs now so the later live QBO OAuth client can replace
the stub without changing invoice/payment code:

* one QuickBooks Invoice per Perkins Invoice / milestone draw;
* Customer:Job mapping through a stable sub-customer reference;
* idempotent sync keyed on our invoice/payment primary key.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

QBSyncStatus = str  # app.models._QB_SYNC_STATUS values: "pending" | "synced" | "error"
QBPayload = dict[str, str | None]


@dataclass(frozen=True)
class QBSyncResult:
    """Result shape mirrored onto Invoice/Payment qb_* columns."""

    qb_entity_id: str
    status: QBSyncStatus
    error_message: str | None = None
    created: bool = True


class QuickBooksSyncClient(Protocol):
    """Protocol implemented by both the hermetic stub and the future live QBO client."""

    def sync_invoice(self, payload: QBPayload, *, source_invoice_id: int) -> QBSyncResult:
        """Create/replay one QBO Invoice for one Perkins Invoice."""

    def sync_payment(self, payload: QBPayload, *, source_payment_id: int) -> QBSyncResult:
        """Create/replay one QBO Payment linked to a QBO Invoice."""


def _value(obj: Any, attr: str) -> Any:
    return getattr(obj, attr, None)


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


def customer_job_ref(customer_id: int, job_id: int | None) -> str:
    """Stable stand-in for a QuickBooks Customer:Job sub-customer reference."""
    base = f"cust:{customer_id}"
    if job_id is None:
        return base
    return f"{base}:job:{job_id}"


def invoice_sync_payload(invoice: Any, customer: Any) -> QBPayload:
    """Build the real-shaped QBO invoice payload from ORM-like objects."""
    customer_id = int(_value(customer, "id") or _value(invoice, "customer_id"))
    job_id = _value(invoice, "job_id")
    invoice_id = _value(invoice, "id")
    return {
        "source_invoice_id": _str_or_none(invoice_id),
        "customer_ref": f"cust:{customer_id}",
        "customer_job_ref": customer_job_ref(customer_id, int(job_id) if job_id is not None else None),
        "customer_name": _str_or_none(_value(customer, "display_name")),
        "customer_email": _str_or_none(_value(customer, "email")),
        "doc_number": _str_or_none(_value(invoice, "invoice_number")),
        "total": _str_or_none(_value(invoice, "total")),
    }


def payment_sync_payload(payment: Any, qb_invoice_entity_id: str) -> QBPayload:
    """Build the real-shaped QBO payment payload from ORM-like objects."""
    return {
        "source_payment_id": _str_or_none(_value(payment, "id")),
        "source_invoice_id": _str_or_none(_value(payment, "invoice_id")),
        "linked_invoice_ref": qb_invoice_entity_id,
        "amount": _str_or_none(_value(payment, "amount")),
        "method": _str_or_none(_value(payment, "method")),
    }


class StubQuickBooksClient:
    """Hermetic in-memory QuickBooks adapter.

    It records no external side effects and never reads OAuth credentials. Replays
    with the same source id return the existing fake QB id with ``created=False``.
    """

    def __init__(self) -> None:
        self._invoices: dict[int, QBSyncResult] = {}
        self._payments: dict[int, QBSyncResult] = {}

    def sync_invoice(self, payload: QBPayload, *, source_invoice_id: int) -> QBSyncResult:
        existing = self._invoices.get(source_invoice_id)
        if existing is not None:
            return QBSyncResult(existing.qb_entity_id, existing.status, existing.error_message, created=False)
        result = QBSyncResult(qb_entity_id=f"QB-INV-{source_invoice_id}", status="synced")
        self._invoices[source_invoice_id] = result
        return result

    def sync_payment(self, payload: QBPayload, *, source_payment_id: int) -> QBSyncResult:
        existing = self._payments.get(source_payment_id)
        if existing is not None:
            return QBSyncResult(existing.qb_entity_id, existing.status, existing.error_message, created=False)
        result = QBSyncResult(qb_entity_id=f"QB-PAY-{source_payment_id}", status="synced")
        self._payments[source_payment_id] = result
        return result

    def invoice_count(self) -> int:
        return len(self._invoices)

    def payment_count(self) -> int:
        return len(self._payments)
