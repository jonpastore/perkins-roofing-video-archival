#!/usr/bin/env python3
"""Self-check for the invoicing API's atomic invoice-number issuance (R2 C2).

Exercises `_issue_number` against a real DB: single-statement UPDATE ... RETURNING
increments atomically and returns the NEW value; a tenant with no counter starts at
1; and the UNIQUE(tenant_id, invoice_number) constraint is the collision safety net
(so even a hypothetical race becomes a loud abort, not a duplicate).

    PYTHONPATH=. python scripts/validate_invoice_api.py
"""
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from api.routes.invoices import _issue_number
from app.models import Base, Customer, Invoice, Job, Tenant, TenantInvoiceCounter

engine = create_engine("sqlite:///:memory:", future=True)
Base.metadata.create_all(engine)  # after_create hook seeds tenant 1
Session = sessionmaker(bind=engine, future=True)


def main() -> None:
    db = Session()
    # Perkins (tenant 1) seeded at the live Knowify max.
    db.add(TenantInvoiceCounter(tenant_id=1, last_number=18732))
    db.commit()

    # Atomic increment returns the NEW value, monotonic.
    assert _issue_number(db, 1) == 18733, "first issued must be 18733"
    assert _issue_number(db, 1) == 18734, "monotonic +1"
    db.commit()

    # A new tenant with no counter row starts its sequence at 1 (ensure-then-increment).
    db.add(Tenant(id=2, name="T2", slug="t2"))
    db.commit()
    assert _issue_number(db, 2) == 1, "new tenant starts at 1"
    assert _issue_number(db, 1) == 18735, "tenant 1 unaffected by tenant 2"
    db.commit()

    # Collision safety net: two invoices with the same (tenant, number) is rejected.
    cust = Customer(display_name="X")
    job = Job(status="in_progress")
    db.add_all([cust, job])
    db.flush()

    def _inv(num):
        return Invoice(invoice_number=num, job_id=job.id, customer_id=cust.id, status="sent",
                       subtotal=0, tax_amount=0, credit_amount=0, total=0, created_by="t")

    db.add(_inv(18733))
    db.commit()
    db.add(_inv(18733))  # duplicate number for tenant 1
    try:
        db.commit()
        raise AssertionError("duplicate invoice_number should violate UNIQUE(tenant,number)")
    except IntegrityError:
        db.rollback()

    print("OK — atomic numbering: 18732 -> 18733/18734/18735 (tenant 1), new tenant -> 1, "
          "UPDATE...RETURNING is single-statement; UNIQUE(tenant,number) blocks collisions.")


if __name__ == "__main__":
    main()
