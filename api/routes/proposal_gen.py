"""Proposal generation API (JB3). Compose a proposal from declarative inputs, freeze
its immutable quote_snapshot, persist it, and render the contract PDF.

Separate from api/routes/proposals.py (the F3 accept-token view/accept flow) — this
endpoint is the ENGINE-driven generation surface. The persisted Proposal.quote_snapshot
is the frozen source of truth JB4's milestone schedule reads (HIGH-2).
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from adapters import gotenberg
from api.auth import get_db_session, require_role
from app.models import Proposal
from core.proposal_doc_render import (
    DEFAULT_PROPOSAL_TEMPLATE_HTML,
    proposal_doc_context,
    render_proposal_doc_html,
)
from core.proposal_gen import compose_proposal, freeze_quote_snapshot

router = APIRouter(prefix="/proposal-gen", tags=["proposal-gen"])
_ROLE = "estimating_manage"


class GenerateRequest(BaseModel):
    customer_id: int
    property_id: int
    inputs: dict = Field(..., description="compose_proposal inputs (customer, property, scopes, …)")
    date: str = ""
    tenant_name: str = "Perkins Roofing"
    tenant_license: str | None = None


@router.post("")
def generate(body: GenerateRequest, claims=Depends(require_role(_ROLE)),
             db: Session = Depends(get_db_session)):
    """Compose + freeze + persist a proposal. Returns the composed proposal + snapshot hash."""
    proposal = compose_proposal(body.inputs)
    snapshot, snap_hash = freeze_quote_snapshot(proposal)

    row = Proposal(
        customer_id=body.customer_id, property_id=body.property_id,
        version_number=1,
        title=proposal.get("project_name") or f"Roofing Proposal — {proposal.get('customer', '')}",
        quote_snapshot={**snapshot, "_snapshot_hash": snap_hash},
        status="draft",
        accept_token=secrets.token_urlsafe(64),
        created_by=claims.get("email") or "unknown",
    )
    db.add(row)
    db.flush()
    return {"id": row.id, "snapshot_hash": snap_hash,
            "contract_total": proposal["contract_total"], "expiry_days": proposal["expiry_days"],
            "proposal": proposal}


@router.get("/{proposal_id}/pdf")
def proposal_pdf(proposal_id: int, claims=Depends(require_role(_ROLE)),
                 db: Session = Depends(get_db_session)):
    """Render the persisted proposal's frozen snapshot to a contract PDF."""
    row = db.get(Proposal, proposal_id)
    if row is None:
        raise HTTPException(404, "proposal not found")
    snap = dict(row.quote_snapshot or {})
    snap.pop("_snapshot_hash", None)
    ctx = proposal_doc_context(
        snap, date=snap.get("_date", ""), tenant_name="Perkins Roofing",
        tc_summary_bullets=None, marketing_appendix=None,
    )
    html = render_proposal_doc_html(DEFAULT_PROPOSAL_TEMPLATE_HTML, ctx)
    pdf = gotenberg.html_to_pdf(html)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="proposal-{proposal_id}.pdf"'})
