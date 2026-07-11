"""Read-only Quotes / Legacy-Contracts API (Wave 3).

Surfaces Knowify contract data from KnowifyRawRecord (entity='contracts') with
associated line-items (entity='deliverables') and project address (entity='projects').

NOTE on "measurements": Knowify has NO roof measurements for Perkins (Roofs table
is empty). "Measurements" in the UI context = deliverable line-items (scope/work
items) + project address. That is what /quotes/{id} returns.

Role gate: billing_view (sales, web_admin, admin). Read-only; no writes here.
Money fields are DOLLARS (not cents) — stored as-is from Knowify payload.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import KnowifyRawRecord

router = APIRouter(prefix="/quotes", tags=["quotes"])

_READ_ROLE = "billing_view"

# Whitelist for sort column to prevent injection via the JSON path strings.
_SORT_COLS = {"Id", "DateCreated", "OriginalContractSum", "BusinessState"}

# Contract payload fields returned on list and detail.
_CONTRACT_FIELDS = (
    "ContractType",
    "BusinessState",
    "ContractName",
    "OriginalContractSum",
    "CurrentContractSum",
    "AdditionalContractSum",
    "DepositAmount",
    "ClientId",
    "ProjectId",
    "DateCreated",
    "ExpirationDate",
    "IsSigned",
    "PONumber",
    "ContactName",
)

# Deliverable payload fields returned on detail.
_DELIVERABLE_FIELDS = (
    "Id",
    "ContractId",
    "Description",
    "Quantity",
    "UnitPrice",
    "Price",
    "PriceBilled",
    "CostLabor",
    "CostMaterials",
    "ObjectState",
)

# Project address fields.
_PROJECT_ADDRESS_FIELDS = (
    "Id",
    "Address1",
    "City",
    "StateProvince",
    "Zip",
)


def _pick(payload: dict, fields: tuple) -> dict:
    return {f: payload.get(f) for f in fields}


@router.get("")
def list_quotes(
    search: Optional[str] = Query(default=None, description="Substring match on ContractName, ContactName, PONumber"),
    business_state: Optional[str] = Query(default=None),
    client_id: Optional[str] = Query(default=None),
    sort: str = Query(default="DateCreated"),
    order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    claims=Depends(require_role(_READ_ROLE)),
    db: Session = Depends(get_db_session),
):
    """List live contracts from the Knowify mirror.

    Filters (applied in Python after a bounded DB fetch — SQLite-compatible):
    - search: substring match on ContractName, ContactName, PONumber
    - business_state: exact match on BusinessState
    - client_id: exact match on ClientId

    Sort whitelist: Id, DateCreated, OriginalContractSum, BusinessState.
    Pagination: page/limit; returns total (pre-filter count is bounded, post-filter
    total is exact).
    """
    if sort not in _SORT_COLS:
        raise HTTPException(422, f"sort must be one of {sorted(_SORT_COLS)}")
    if order not in ("asc", "desc"):
        raise HTTPException(422, "order must be 'asc' or 'desc'")

    # Fetch all live contract rows for this tenant (RLS ensures tenant scope).
    stmt = (
        select(KnowifyRawRecord)
        .where(
            KnowifyRawRecord.entity == "contracts",
            KnowifyRawRecord.is_present == True,  # noqa: E712 — SQLAlchemy requires ==
        )
    )
    rows = db.execute(stmt).scalars().all()

    # Python-side filter (keeps logic SQLite-compatible; contract volume is bounded).
    results = []
    for r in rows:
        p = r.payload or {}
        if business_state and p.get("BusinessState") != business_state:
            continue
        if client_id and str(p.get("ClientId", "")) != str(client_id):
            continue
        if search:
            needle = search.lower()
            haystack = " ".join(
                str(p.get(f, "") or "") for f in ("ContractName", "ContactName", "PONumber")
            ).lower()
            if needle not in haystack:
                continue
        results.append((r.knowify_id, p))

    total = len(results)

    # Sort — numeric columns coerced to float so "32000" > "9000" (not lexicographic).
    # Stable tiebreak on knowify_id keeps pagination boundaries deterministic.
    _NUMERIC_COLS = {"OriginalContractSum"}
    reverse = order == "desc"
    if sort in _NUMERIC_COLS:
        results.sort(
            key=lambda x: (float(x[1].get(sort) or 0), x[0]),
            reverse=reverse,
        )
    else:
        results.sort(
            key=lambda x: (x[1].get(sort) or "", x[0]),
            reverse=reverse,
        )

    # Paginate.
    skip = (page - 1) * limit
    page_items = results[skip: skip + limit]

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {"contract_id": cid, **_pick(p, _CONTRACT_FIELDS)}
            for cid, p in page_items
        ],
    }


@router.get("/{contract_id}")
def get_quote(
    contract_id: str,
    claims=Depends(require_role(_READ_ROLE)),
    db: Session = Depends(get_db_session),
):
    """One contract's full detail: fields + deliverable line-items + project address.

    NOTE: Knowify has NO roof measurements for Perkins (Roofs table empty).
    'measurements' here = deliverable line-items (scope/work items) + project address.
    """
    # Contract row.
    contract_row = db.execute(
        select(KnowifyRawRecord).where(
            KnowifyRawRecord.entity == "contracts",
            KnowifyRawRecord.knowify_id == contract_id,
            KnowifyRawRecord.is_present == True,  # noqa: E712
        )
    ).scalar_one_or_none()

    if contract_row is None:
        raise HTTPException(404, "contract not found")

    cp = contract_row.payload or {}
    project_id = str(cp.get("ProjectId") or "")

    # Deliverable line-items for this contract.
    deliverable_rows = db.execute(
        select(KnowifyRawRecord).where(
            KnowifyRawRecord.entity == "deliverables",
            KnowifyRawRecord.is_present == True,  # noqa: E712
        )
    ).scalars().all()
    line_items = [
        _pick(r.payload or {}, _DELIVERABLE_FIELDS)
        for r in deliverable_rows
        if str((r.payload or {}).get("ContractId") or "") == contract_id
    ]

    # Project address (first match on ProjectId).
    project_address = None
    if project_id:
        project_rows = db.execute(
            select(KnowifyRawRecord).where(
                KnowifyRawRecord.entity == "projects",
                KnowifyRawRecord.is_present == True,  # noqa: E712
            )
        ).scalars().all()
        for r in project_rows:
            pp = r.payload or {}
            if str(pp.get("Id") or "") == project_id:
                project_address = _pick(pp, _PROJECT_ADDRESS_FIELDS)
                break

    return {
        "contract_id": contract_id,
        **_pick(cp, _CONTRACT_FIELDS),
        "line_items": line_items,
        "project_address": project_address,
        # Document the measurements gap explicitly.
        "_note": (
            "Knowify Roofs table is empty for this tenant; "
            "roof measurements are not available. "
            "Scope is captured via deliverable line_items above."
        ),
    }
