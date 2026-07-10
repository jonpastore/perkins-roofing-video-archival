"""Quoting — Proposals lifecycle + public e-sign accept surface.

Authenticated endpoints (prefix /quoting):
  GET    /quoting/proposals               list proposals (tenant-scoped)
  POST   /quoting/proposals               create draft proposal
  GET    /quoting/proposals/{id}          get proposal + events
  PUT    /quoting/proposals/{id}          update draft proposal
  POST   /quoting/proposals/{id}/send     freeze snapshot → status=sent + sent event
  POST   /quoting/proposals/{id}/revise   new version via core.proposal chain rules
  GET    /quoting/proposals/{id}/chain    full version chain (root_id query)

  GET    /quoting/templates               list templates
  POST   /quoting/templates               create template (quoting_manage_templates)
  PUT    /quoting/templates/{id}          update template (quoting_manage_templates)

  GET    /quoting/settings                get tenant quoting settings
  PUT    /quoting/settings                update quoting settings (quoting_manage_settings)

Public accept-page endpoints (no auth — token-gated):
  GET    /p/{token}    render accept page; 200 terminal for superseded/accepted; 404 for unknown
  POST   /p/{token}/accept      single-tx accept; 422 without consent/name; 404 on re-accept
  POST   /p/{token}/decline     status→declined + event
  POST   /p/{token}/revision    status→revision_requested + event

Domain logic (tokens, transitions, version chain, snapshot validation, selection capture)
is owned by core.proposal — routes delegate to it and map ValueError subclasses → 4xx.

Rate-limit note: Token strength (512-bit entropy) is the primary protection against
brute-force. The single-tx UPDATE WHERE status IN ('sent','viewed') handles concurrent
double-submit. Cloudflare WAF rate limiting (F6) is required before public go-live.

Authz:
  quoting_view             → GET endpoints
  quoting_create           → POST/PUT proposals
  quoting_send             → send / revise
  quoting_manage_templates → template write operations
  quoting_manage_settings  → settings write
"""
import logging
import os
from contextlib import contextmanager
from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import (
    Customer,
    Job,
    PlatformSessionLocal,
    Property,
    Proposal,
    ProposalEvent,
    ProposalTemplate,
    SessionLocal,
    Tenant,
)
from core.proposal import (
    InvalidTransitionError,
    SnapshotError,
    capture_selection,
    generate_accept_token,
    new_version,
    supersede,
    transition,
    validate_snapshot,
)
from core.proposal_render import (
    DEFAULT_TEMPLATE_HTML,
    ProposalRenderContext,
    render_proposal_html,
)

_log = logging.getLogger(__name__)

router = APIRouter(tags=["quoting_proposals"])

# Re-export for tests that import from this module
_new_accept_token = generate_accept_token


def _tenant_id(db: Session) -> int:
    """Resolved (verified) tenant for this request — stamped onto the session by
    get_db_session from the caller's verified claims. Never a hardcoded literal."""
    return db.info["tenant_id"]


@contextmanager
def _token_scoped_session(token: str):
    """Yield a tenant-scoped session for a PUBLIC (token-gated) proposal request.

    Public accept-page endpoints have no bearer token, so tenant cannot come from
    verified claims. Instead we resolve the owning tenant from the accept_token via
    a platform-scoped lookup (RLS-exempt), then stamp a tenant-scoped session with
    that tenant so RLS applies to all subsequent statements. Yields (db, proposal_id)
    or (None, None) if the token is unknown — callers 404 on None.
    """
    plat = PlatformSessionLocal()
    plat.info["platform_scope"] = True
    try:
        # Set the transaction-local app.accept_token GUC so the proposals RLS policy
        # (migration 0022) grants exactly this token's row — the only way to read the
        # RLS-FORCED proposals table without a resolved tenant context. Never sourced
        # from anything but the URL token; is_local=true dies with the transaction.
        # PostgreSQL-only: set_config is a PG function; SQLite (dev/test) has no RLS,
        # so the plain SELECT below already returns the row.
        if plat.bind.dialect.name == "postgresql":
            plat.execute(text("SELECT set_config('app.accept_token', :tok, true)"), {"tok": token})
        row = plat.execute(
            select(Proposal.id, Proposal.tenant_id).where(Proposal.accept_token == token)
        ).first()
    finally:
        plat.close()

    if row is None:
        yield None, None
        return

    proposal_id, tenant_id = row
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    try:
        yield db, proposal_id
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _utcnow():
    from datetime import datetime
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _proposal_as_dict(row: Proposal) -> dict:
    """Convert ORM row → plain dict for core.proposal domain calls."""
    return {
        "id": row.id,
        "root_id": row.root_id,
        "parent_id": row.parent_id,
        "version_number": row.version_number,
        "status": row.status,
        "quote_snapshot": row.quote_snapshot or {},
    }


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ProposalCreate(BaseModel):
    customer_id: int
    property_id: int
    title: str
    quote_snapshot: dict
    template_id: Optional[int] = None


class ProposalUpdate(BaseModel):
    title: Optional[str] = None
    quote_snapshot: Optional[dict] = None
    template_id: Optional[int] = None


class SendRequest(BaseModel):
    pass


class ReviseRequest(BaseModel):
    title: Optional[str] = None
    quote_snapshot: Optional[dict] = None
    template_id: Optional[int] = None


class AcceptRequest(BaseModel):
    selected_tier: str
    selected_options: Optional[list] = None
    consent_electronic: bool
    signed_name: str

    @field_validator("consent_electronic")
    @classmethod
    def consent_must_be_true(cls, v):
        if not v:
            raise ValueError("consent_electronic must be True to accept the proposal")
        return v

    @field_validator("signed_name")
    @classmethod
    def name_must_not_be_blank(cls, v):
        if not v or not v.strip():
            raise ValueError("signed_name must not be blank")
        return v.strip()


class DeclineRequest(BaseModel):
    note: Optional[str] = None


class RevisionRequest(BaseModel):
    note: Optional[str] = None


class TemplateCreate(BaseModel):
    name: str
    html_body: str
    is_default: bool = False
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    footer_text: Optional[str] = None
    tc_attachment_gcs: Optional[str] = None
    cover_page_html: Optional[str] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    html_body: Optional[str] = None
    is_default: Optional[bool] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    footer_text: Optional[str] = None
    cover_page_html: Optional[str] = None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _event_row(ev: ProposalEvent) -> dict:
    return {
        "id": ev.id,
        "proposal_id": ev.proposal_id,
        "event_type": ev.event_type,
        "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
        "actor_email": ev.actor_email,
        "metadata": ev.event_metadata,
    }


def _proposal_row(row: Proposal, events: list | None = None) -> dict:
    d = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "customer_id": row.customer_id,
        "property_id": row.property_id,
        "template_id": row.template_id,
        "root_id": row.root_id,
        "parent_id": row.parent_id,
        "version_number": row.version_number,
        "title": row.title,
        "quote_snapshot": row.quote_snapshot,
        "selected_tier": row.selected_tier,
        "selected_options": row.selected_options,
        "status": row.status,
        "accept_token": row.accept_token,
        "accepted_by_name": row.accepted_by_name,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "consent_electronic": row.consent_electronic,
        "signed_pdf_gcs": row.signed_pdf_gcs,
        "created_by": row.created_by,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if events is not None:
        d["events"] = [_event_row(e) for e in events]
    return d


def _template_row(row: ProposalTemplate) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "is_default": row.is_default,
        "logo_url": row.logo_url,
        "primary_color": row.primary_color,
        "accent_color": row.accent_color,
        "footer_text": row.footer_text,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Proposal endpoints
# ---------------------------------------------------------------------------

@router.get("/quoting/proposals")
def list_proposals(
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    page: Optional[int] = Query(None, ge=1),
    skip: int = 0,
    limit: int = 50,
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    offset = (page - 1) * limit if page is not None else skip
    stmt = (
        select(Proposal, Customer.display_name, Property.street, Property.city, Property.state)
        .join(Customer, Proposal.customer_id == Customer.id)
        .join(Property, Proposal.property_id == Property.id)
        .where(Proposal.tenant_id == tenant_id)
    )
    if status:
        stmt = stmt.where(Proposal.status == status)
    if customer_id:
        stmt = stmt.where(Proposal.customer_id == customer_id)
    stmt = stmt.order_by(Proposal.created_at.desc()).offset(offset).limit(limit)
    results = db.execute(stmt).all()

    out = []
    for row, cname, street, city, state in results:
        d = _proposal_row(row)
        d["customer_name"] = cname
        d["property_address"] = f"{street}, {city} {state}" if street else None
        out.append(d)
    return out


@router.post("/quoting/proposals")
def create_proposal(
    body: ProposalCreate,
    claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    email = claims.get("email") or "unknown"
    row = Proposal(
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        property_id=body.property_id,
        template_id=body.template_id,
        title=body.title,
        quote_snapshot=body.quote_snapshot,
        status="draft",
        accept_token=generate_accept_token(),
        created_by=email,
        version_number=1,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return _proposal_row(row)


@router.get("/quoting/proposals/{proposal_id}")
def get_proposal(
    proposal_id: int,
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    events = db.execute(
        select(ProposalEvent)
        .where(ProposalEvent.proposal_id == proposal_id)
        .order_by(ProposalEvent.occurred_at)
    ).scalars().all()
    return _proposal_row(row, events=events)


@router.put("/quoting/proposals/{proposal_id}")
def update_proposal(
    proposal_id: int,
    body: ProposalUpdate,
    _claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    if row.status != "draft":
        raise HTTPException(
            409,
            f"Proposal {proposal_id} is not a draft (status={row.status!r});"
            " use /revise to create a new version",
        )
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.flush()
    db.refresh(row)
    return _proposal_row(row)


@router.post("/quoting/proposals/{proposal_id}/send")
def send_proposal(
    proposal_id: int,
    body: SendRequest,
    claims=Depends(require_role("quoting_send")),
    db: Session = Depends(get_db_session),
):
    """Freeze snapshot → status=sent via core.proposal.transition(); insert sent event.

    Validates snapshot before freezing (422 on SnapshotError). Stamps sent_at_iso into
    the snapshot. Sends accept-link email to customer; if customer has no email, the send
    still succeeds and the response includes email_sent=false.
    """
    tenant_id = _tenant_id(db)
    email = claims.get("email") or "unknown"
    now = _utcnow()
    row = db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")

    try:
        transition(_proposal_as_dict(row), "sent")
    except InvalidTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc

    # Stamp sent_at_iso into snapshot before freezing, then validate
    snapshot = dict(row.quote_snapshot or {})
    snapshot["sent_at_iso"] = now.isoformat() + "Z"
    try:
        validate_snapshot(snapshot)
    except SnapshotError as exc:
        raise HTTPException(422, str(exc)) from exc
    row.quote_snapshot = snapshot

    row.status = "sent"
    row.sent_at = now
    db.flush()
    if row.root_id is None:
        row.root_id = row.id

    # Fetch customer email for accept-link email
    customer = db.get(Customer, row.customer_id)
    tenant_row = db.get(Tenant, row.tenant_id)
    customer_email = customer.email if customer else None
    tenant_name = tenant_row.name if tenant_row else "Your roofing contractor"
    accept_token = row.accept_token
    proposal_title = row.title

    from core.tenant_settings import TenantSettings  # noqa: PLC0415
    _ts = TenantSettings.load(dict(tenant_row.settings or {}) if tenant_row else {})
    _reply_to = _ts.get_workspace_admin_subject() or "info@perkinsroofing.net"

    db.add(ProposalEvent(
        tenant_id=tenant_id,
        proposal_id=row.id,
        event_type="sent",
        occurred_at=now,
        actor_email=email,
    ))
    db.flush()
    db.refresh(row)

    # Send accept-link email (I/O, degrades gracefully). Runs before the
    # dependency's commit; reads only captured locals, so ordering is safe.
    if customer_email:
        email_sent = _send_accept_link_email(
            to_email=customer_email,
            accept_token=accept_token,
            tenant_name=tenant_name,
            proposal_title=proposal_title,
            reply_to=_reply_to,
        )
    else:
        email_sent = False
        _log.warning("send_proposal: customer has no email for proposal %s", proposal_id)

    result = _proposal_row(row)
    if not email_sent:
        result["email_sent"] = False
    return result


@router.post("/quoting/proposals/{proposal_id}/revise")
def revise_proposal(
    proposal_id: int,
    body: ReviseRequest,
    claims=Depends(require_role("quoting_send")),
    db: Session = Depends(get_db_session),
):
    """Create new version via core.proposal.new_version(); supersede old via supersede().

    Version chain rules (TRD §3.4):
      core.proposal.new_version() computes root_id, parent_id, version_number, token.
      core.proposal.supersede() returns the status update dict for the old row.
      New row is sent immediately (status=sent), not left as draft — deliberate: the
      revised proposal replaces the old one in the customer's inbox without a second send action.
    """
    tenant_id = _tenant_id(db)
    email = claims.get("email") or "unknown"
    now = _utcnow()
    prev = db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if prev is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")

    prev_dict = _proposal_as_dict(prev)
    try:
        new_fields = new_version(prev_dict, created_by=email)
    except InvalidTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc

    new_row = Proposal(
        tenant_id=tenant_id,
        customer_id=prev.customer_id,
        property_id=prev.property_id,
        template_id=body.template_id if body.template_id is not None else prev.template_id,
        root_id=new_fields["root_id"],
        parent_id=new_fields["parent_id"],
        version_number=new_fields["version_number"],
        title=body.title if body.title is not None else prev.title,
        quote_snapshot=(body.quote_snapshot if body.quote_snapshot is not None
                        else prev.quote_snapshot),
        status="sent",
        accept_token=new_fields["accept_token"],
        sent_at=now,
        created_by=email,
    )
    db.add(new_row)

    # supersede() validates the transition and returns {"status": "superseded"}
    supersede_fields = supersede(prev_dict)
    prev.status = supersede_fields["status"]

    db.flush()

    # Fetch customer info for email (while session is open)
    customer = db.get(Customer, prev.customer_id)
    tenant_row = db.get(Tenant, tenant_id)
    customer_email = customer.email if customer else None
    tenant_name = tenant_row.name if tenant_row else "Your roofing contractor"

    from core.tenant_settings import TenantSettings  # noqa: PLC0415
    _ts2 = TenantSettings.load(dict(tenant_row.settings or {}) if tenant_row else {})
    _reply_to2 = _ts2.get_workspace_admin_subject() or "info@perkinsroofing.net"

    db.add(ProposalEvent(
        tenant_id=tenant_id,
        proposal_id=new_row.id,
        event_type="sent",
        occurred_at=now,
        actor_email=email,
    ))
    db.flush()
    db.refresh(new_row)
    new_accept_token = new_row.accept_token
    new_title = new_row.title
    new_proposal_id = new_row.id
    result = _proposal_row(new_row)

    # Send updated accept-link email (degrades gracefully)
    if customer_email:
        _send_accept_link_email(
            to_email=customer_email,
            accept_token=new_accept_token,
            tenant_name=tenant_name,
            proposal_title=new_title,
            reply_to=_reply_to2,
        )
    else:
        _log.warning("revise_proposal: customer has no email for proposal %s", new_proposal_id)

    return result


@router.get("/quoting/proposals/{proposal_id}/chain")
def get_proposal_chain(
    proposal_id: int,
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    """Return all versions sharing the same root_id, ordered by version_number."""
    tenant_id = _tenant_id(db)
    anchor = db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if anchor is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")

    root_id = anchor.root_id if anchor.root_id is not None else anchor.id
    rows = db.execute(
        select(Proposal)
        .where(
            Proposal.tenant_id == tenant_id,
            Proposal.root_id == root_id,
        )
        .order_by(Proposal.version_number)
    ).scalars().all()
    if not rows:
        rows = [anchor]
    return [_proposal_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------

@router.get("/quoting/templates")
def list_templates(
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    rows = db.execute(
        select(ProposalTemplate)
        .where(ProposalTemplate.tenant_id == tenant_id)
        .order_by(ProposalTemplate.name)
    ).scalars().all()
    return [_template_row(r) for r in rows]


@router.post("/quoting/templates")
def create_template(
    body: TemplateCreate,
    claims=Depends(require_role("quoting_manage_templates")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    email = claims.get("email") or "unknown"
    row = ProposalTemplate(
        tenant_id=tenant_id,
        name=body.name,
        is_default=body.is_default,
        html_body=body.html_body,
        logo_url=body.logo_url,
        primary_color=body.primary_color,
        accent_color=body.accent_color,
        footer_text=body.footer_text,
        tc_attachment_gcs=body.tc_attachment_gcs,
        cover_page_html=body.cover_page_html,
        created_by=email,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return _template_row(row)


@router.put("/quoting/templates/{template_id}")
def update_template(
    template_id: int,
    body: TemplateUpdate,
    _claims=Depends(require_role("quoting_manage_templates")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(ProposalTemplate).where(
            ProposalTemplate.id == template_id,
            ProposalTemplate.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Template {template_id} not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.flush()
    db.refresh(row)
    return _template_row(row)


@router.delete("/quoting/templates/{template_id}")
def delete_template(
    template_id: int,
    _claims=Depends(require_role("quoting_manage_templates")),
    db: Session = Depends(get_db_session),
):
    """Delete a template. Returns 409 if any non-draft proposal references it."""
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(ProposalTemplate).where(
            ProposalTemplate.id == template_id,
            ProposalTemplate.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Template {template_id} not found")

    blocking = db.execute(
        select(Proposal).where(
            Proposal.template_id == template_id,
            Proposal.status != "draft",
        ).limit(1)
    ).scalar_one_or_none()
    if blocking is not None:
        raise HTTPException(
            409,
            f"Template {template_id} is referenced by non-draft proposal {blocking.id}"
        )

    db.delete(row)
    db.flush()
    return {"ok": True}


@router.get("/quoting/proposals/{proposal_id}/pdf")
def get_proposal_pdf(
    proposal_id: int,
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    """Render the current proposal as PDF via Gotenberg and stream it.

    Returns 503 if GOTENBERG_URL is not configured.
    """
    gotenberg_url = os.environ.get("GOTENBERG_URL", "")
    if not gotenberg_url:
        raise HTTPException(503, "PDF rendering unavailable: GOTENBERG_URL is not configured")

    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    customer = db.get(Customer, row.customer_id)
    prop = db.get(Property, row.property_id)
    tenant_row = db.get(Tenant, row.tenant_id)

    snap = row.quote_snapshot or {}
    tiers = snap.get("tiers") or {}
    dp = snap.get("deposit_policy") or {}
    address = (
        f"{prop.street}, {prop.city} {prop.state}" if prop and prop.street else ""
    )

    ctx = ProposalRenderContext(
        proposal_title=row.title,
        proposal_date=row.sent_at.strftime("%Y-%m-%d") if row.sent_at else "",
        proposal_version=row.version_number,
        customer_name=customer.display_name if customer else "",
        customer_company=None,
        property_address=address,
        property_county=prop.county if prop else None,
        property_code_zone=prop.code_zone if prop else "",
        quote_roof_type=snap.get("roof_type", ""),
        quote_num_squares=float(snap.get("num_squares", 0)),
        quote_good_price=str(tiers.get("good", {}).get("total", "")),
        quote_better_price=str(tiers.get("better", {}).get("total", "")),
        quote_best_price=str(tiers.get("best", {}).get("total", "")),
        quote_line_items=[],
        deposit_amount=str(dp.get("amount", "")),
        deposit_instructions=dp.get("instructions", ""),
        tenant_name=tenant_row.name if tenant_row else "",
        tenant_license=None,
        accept_url="",
    )

    # Use default template if no template attached
    template_html = None
    if row.template_id:
        tpl = db.get(ProposalTemplate, row.template_id)
        template_html = tpl.html_body if tpl else None
    if template_html is None:
        template_html = DEFAULT_TEMPLATE_HTML

    try:
        html = render_proposal_html(template_html, ctx)
    except Exception as exc:
        raise HTTPException(500, f"Render error: {exc}") from exc

    try:
        import adapters.gotenberg as gotenberg_adapter  # noqa: PLC0415
        pdf_bytes = gotenberg_adapter.html_to_pdf(html)
    except Exception as exc:
        raise HTTPException(503, f"PDF generation failed: {exc}") from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="proposal-{proposal_id}.pdf"'},
    )


@router.post("/quoting/templates/{template_id}/preview")
def preview_template(
    template_id: int,
    body: dict,
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    """Render a template with sample context and return HTML.

    Returns rendered HTML as text/html. Does not require Gotenberg.
    """
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(ProposalTemplate).where(
            ProposalTemplate.id == template_id,
            ProposalTemplate.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Template {template_id} not found")
    template_html = row.html_body

    ctx = ProposalRenderContext(
        proposal_title=body.get("title", "Sample Proposal"),
        proposal_date="2026-07-09",
        proposal_version=1,
        customer_name=body.get("customer_name", "Sample Customer"),
        customer_company=None,
        property_address="123 Main St, Miami FL",
        property_county=None,
        property_code_zone="FBC",
        quote_roof_type="dimensional_shingle",
        quote_num_squares=28.0,
        quote_good_price="18,400.00",
        quote_better_price="21,200.00",
        quote_best_price="24,800.00",
        quote_line_items=[],
        deposit_amount="9,200.00",
        deposit_instructions="Check payable to Perkins Roofing",
        tenant_name="Perkins Roofing",
        tenant_license=None,
        accept_url="#preview",
    )

    try:
        html = render_proposal_html(template_html, ctx)
    except Exception as exc:
        raise HTTPException(500, f"Render error: {exc}") from exc

    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

@router.get("/quoting/settings")
def get_settings(
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return {}
    settings = tenant.settings or {}
    return {
        "deposit": settings.get("deposit", {}),
        "reminder_cadence_days": settings.get("reminder_cadence_days", [3, 7, 14]),
        "license_number": settings.get("license_number"),
    }


@router.put("/quoting/settings")
def update_settings(
    body: dict,
    _claims=Depends(require_role("quoting_manage_settings")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")
    existing = dict(tenant.settings or {})
    existing.update(body)
    tenant.settings = existing
    db.flush()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Public accept-page endpoints — NO AUTH MIDDLEWARE (token-gated)
# ---------------------------------------------------------------------------

_PUBLIC_APP_URL = os.environ.get(
    "PUBLIC_APP_URL", "https://video-archival-and-content-gen.web.app"
)


def _send_accept_link_email(
    *,
    to_email: str,
    accept_token: str,
    tenant_name: str,
    proposal_title: str,
    reply_to: str = "info@perkinsroofing.net",
) -> bool:
    """Send the accept-link email via Resend. Returns True on success, False if email absent.

    reply_to should be the tenant's workspace_admin_subject from Tenant.settings.integrations
    (W0: retired WORKSPACE_ADMIN_SUBJECT env var — now read from per-tenant settings at the
    call site and passed in explicitly).

    Degrades gracefully — logs warning and returns False instead of raising if Resend is
    unavailable (missing API key) or to_email is blank.
    """
    if not to_email:
        return False

    public_url = os.environ.get("PUBLIC_APP_URL", _PUBLIC_APP_URL)
    accept_url = f"{public_url}/p/{accept_token}"

    html = f"""
<html><body>
<p>Hello,</p>
<p>Your proposal from <strong>{tenant_name}</strong> is ready for review.</p>
<h3 style="color:#333">{proposal_title}</h3>
<p><a href="{accept_url}" style="background:#C0392B;color:#fff;padding:12px 24px;
text-decoration:none;border-radius:4px;display:inline-block;">
Review &amp; Accept Proposal</a></p>
<p>Or copy this link: {accept_url}</p>
<p>Best regards,<br>{tenant_name}</p>
</body></html>
"""
    try:
        import adapters.resend as resend_adapter  # noqa: PLC0415
        resend_adapter.send(
            from_name=tenant_name,
            reply_to=reply_to,
            to=to_email,
            subject=f"Your proposal from {tenant_name} is ready",
            html=html,
        )
        return True
    except Exception as exc:
        _log.warning("accept-link email failed for token %s: %s", accept_token, exc)
        return False


def _lookup_proposal_by_token(db, token: str) -> Proposal | None:
    return db.execute(
        select(Proposal).where(Proposal.accept_token == token)
    ).scalar_one_or_none()


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


def _public_snapshot_projection(snapshot: dict) -> dict:
    """Return a client-safe subset of a frozen quote_snapshot.

    Strips internal pricing fields (floors, pricing_config_hash, region,
    branch, code_zone, estimator_version, line_items inside tiers).
    Exposes only what the accept-page UI needs to render.
    """
    raw_tiers = snapshot.get("tiers") or {}
    safe_tiers = {}
    for tier_key, tier_val in raw_tiers.items():
        safe_tiers[tier_key] = {
            k: v for k, v in tier_val.items()
            if k in ("label", "description", "total")
        }

    raw_opts = snapshot.get("optional_items") or []
    safe_opts = [
        {k: v for k, v in item.items() if k in ("id", "label", "unit_price", "qty")}
        for item in raw_opts
    ]

    dp = snapshot.get("deposit_policy") or {}
    safe_deposit = {k: v for k, v in dp.items()
                    if k in ("amount", "instructions", "mode", "value")}

    return {
        "tiers": safe_tiers,
        "optional_items": safe_opts,
        "deposit_policy": safe_deposit,
    }


@router.get("/p/{token}")
def accept_page_get(token: str, request: Request):
    """Return a client-safe proposal payload for the public accept page.

    Token lookup:
      Unknown token           → 404
      draft / revision_requested → 404 (indistinguishable from unknown)
      sent / viewed (active)  → 200 with full client-safe payload; records 'viewed' event once
      accepted / declined / superseded (terminal) → 200 with ONLY {status, title}
    """
    now = _utcnow()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    with _token_scoped_session(token) as (db, _pid):
        if db is None:
            raise HTTPException(404, "Not found")
        row = _lookup_proposal_by_token(db, token)

        # Unknown token or states that must look like 404
        if row is None or row.status in ("draft", "revision_requested"):
            raise HTTPException(404, "Not found")

        if row.status not in ("sent", "viewed", "accepted", "declined", "superseded"):
            raise HTTPException(404, "Not found")

        # Terminal states — return minimal payload, no snapshot
        if row.status in ("accepted", "declined", "superseded"):
            return {"status": row.status, "title": row.title}

        # Active states (sent / viewed) — record viewed event once
        if row.status == "sent":
            row.status = "viewed"
            existing_viewed = db.execute(
                select(ProposalEvent).where(
                    ProposalEvent.proposal_id == row.id,
                    ProposalEvent.event_type == "viewed",
                )
            ).scalar_one_or_none()
            if existing_viewed is None:
                db.add(ProposalEvent(
                    tenant_id=row.tenant_id,
                    proposal_id=row.id,
                    event_type="viewed",
                    occurred_at=now,
                    ip_address=ip,
                    user_agent=ua,
                ))
            db.flush()
            db.refresh(row)

        # Denormalize customer + property for the SPA
        customer = db.get(Customer, row.customer_id)
        prop = db.get(Property, row.property_id)
        tenant = db.get(Tenant, row.tenant_id)

        customer_name = customer.display_name if customer else None
        property_address = (
            f"{prop.street}, {prop.city} {prop.state}"
            if prop and prop.street else None
        )
        payload = {
            "status": row.status,
            "title": row.title,
            "customer_name": customer_name,
            "property_address": property_address,
            "quote_snapshot": _public_snapshot_projection(row.quote_snapshot or {}),
            "tenant_name": tenant.name if tenant else None,
        }
    return payload


@router.post("/p/{token}/accept")
def accept_proposal(token: str, body: AcceptRequest, request: Request):
    """Submit acceptance.

    Consent and name validation are enforced by Pydantic validators (→ 422).
    Token not found or not in (sent, viewed) → 404.
    core.proposal.capture_selection() validates tier choice (→ 422 on bad tier).
    core.proposal.transition() validates the accepted state machine edge.
    Single transaction: all field updates + event + job stub.
    Re-accept → 404 (status is already 'accepted', not in sent/viewed).
    """
    now = _utcnow()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    with _token_scoped_session(token) as (db, _pid):
        if db is None:
            raise HTTPException(404, "Not found")
        row = _lookup_proposal_by_token(db, token)
        if row is None or row.status not in ("sent", "viewed"):
            raise HTTPException(404, "Not found")

        row_dict = _proposal_as_dict(row)
        try:
            selection = capture_selection(
                row_dict, body.selected_tier, body.selected_options
            )
            transition(row_dict, "accepted")
        except InvalidTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        row.status = "accepted"
        row.accepted_by_name = body.signed_name
        row.accepted_at = now
        row.accepted_ip = ip
        row.accepted_ua = ua
        row.consent_electronic = True
        row.selected_tier = selection["selected_tier"]
        row.selected_options = selection["selected_options"]

        db.add(ProposalEvent(
            tenant_id=row.tenant_id,
            proposal_id=row.id,
            event_type="accepted",
            occurred_at=now,
            ip_address=ip,
            user_agent=ua,
        ))
        db.add(Job(tenant_id=row.tenant_id, proposal_id=row.id, status="pending"))
        db.flush()

    return {"ok": True, "status": "accepted"}


@router.post("/p/{token}/decline")
def decline_proposal(token: str, body: DeclineRequest, request: Request):
    """Submit decline — status→declined via core.proposal.transition(); insert event."""
    now = _utcnow()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    with _token_scoped_session(token) as (db, _pid):
        if db is None:
            raise HTTPException(404, "Not found")
        row = _lookup_proposal_by_token(db, token)
        if row is None or row.status not in ("sent", "viewed"):
            raise HTTPException(404, "Not found")

        try:
            transition(_proposal_as_dict(row), "declined")
        except InvalidTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc

        row.status = "declined"
        db.add(ProposalEvent(
            tenant_id=row.tenant_id,
            proposal_id=row.id,
            event_type="declined",
            occurred_at=now,
            ip_address=ip,
            user_agent=ua,
            event_metadata={"note": body.note} if body.note else None,
        ))
        db.flush()

    return {"ok": True, "status": "declined"}


@router.post("/p/{token}/revision")
def request_revision(token: str, body: RevisionRequest, request: Request):
    """Submit revision request — status→revision_requested; insert event."""
    now = _utcnow()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    with _token_scoped_session(token) as (db, _pid):
        if db is None:
            raise HTTPException(404, "Not found")
        row = _lookup_proposal_by_token(db, token)
        if row is None or row.status not in ("sent", "viewed"):
            raise HTTPException(404, "Not found")

        try:
            transition(_proposal_as_dict(row), "revision_requested")
        except InvalidTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc

        row.status = "revision_requested"
        db.add(ProposalEvent(
            tenant_id=row.tenant_id,
            proposal_id=row.id,
            event_type="revision_requested",
            occurred_at=now,
            ip_address=ip,
            user_agent=ua,
            event_metadata={"revision_note": body.note} if body.note else None,
        ))
        db.flush()

    return {"ok": True, "status": "revision_requested"}
