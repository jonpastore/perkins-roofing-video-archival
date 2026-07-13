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
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from api.routes.quotes import (
    _CONTRACT_FIELDS,
    _DELIVERABLE_FIELDS,
    _PROJECT_ADDRESS_FIELDS,
    _pick,
)
from app.models import (
    Customer,
    Job,
    KnowifyRawRecord,
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


@lru_cache(maxsize=8)
def _tc_summary_bullets(tc_text: str):
    """Return summary bullets generated from saved T&C text.

    Cached per distinct version text so proposal rendering does not call the LLM
    repeatedly. FAQ rows come from contract_faq_entries instead of ad-hoc render-time
    generation so proposal PDFs use reviewed/approved database content.
    """
    import app.llm as llm_mod  # noqa: PLC0415
    from core.tc_summary import build_tc_summary_prompt, parse_tc_summary  # noqa: PLC0415

    return parse_tc_summary(llm_mod.chat(build_tc_summary_prompt(tc_text))) or None


def _load_tc_context(db: Session) -> dict:
    """Load versioned T&C text, approved FAQ rows, and static AI prompts for proposals."""
    from api.routes.contract_faq import _load_tc_text_for_version  # noqa: PLC0415
    from app.models import ContractFaqEntry, TcVersion  # noqa: PLC0415
    from core.tc_ai_prompts import get_tc_ai_prompts_block  # noqa: PLC0415

    latest = (
        db.query(TcVersion)
        .order_by(TcVersion.effective_at.desc(), TcVersion.id.desc())
        .first()
    )
    tc_text = _load_tc_text_for_version(latest) if latest is not None else ""
    rows = (
        db.query(ContractFaqEntry)
        .filter(ContractFaqEntry.status == "approved")
        .order_by(ContractFaqEntry.id)
        .all()
    )
    prompt_block = get_tc_ai_prompts_block()
    return {
        "tc_text": tc_text or None,
        "tc_summary_bullets": _tc_summary_bullets(tc_text) if tc_text else None,
        "tc_faq_items": [
            {"q": r.question, "a": r.answer or "", "quote": r.quote or ""}
            for r in rows
        ] or None,
        "tc_review_prompts": prompt_block["recommended_prompts"],
        "tc_ai_disclaimer": prompt_block["attorney_disclaimer"],
        "tc_cover_letter": prompt_block["cover_letter"],
    }

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


def _media_bucket() -> str:
    project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
        or "video-archival-and-content-gen"
    )
    return f"{project}-media"


def _proposal_pdf_key(row: Proposal) -> str:
    stamp = (row.updated_at or row.created_at or _utcnow()).strftime("%Y%m%d%H%M%S")
    return f"tenants/{row.tenant_id}/proposals/{row.id}/rendered-v{row.version_number}-{stamp}.pdf"


def _split_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError("not a gs:// URI")
    bucket_key = uri[5:]
    bucket, _, key = bucket_key.partition("/")
    if not bucket or not key:
        raise ValueError("invalid gs:// URI")
    return bucket, key


def _download_gcs_bytes(uri: str) -> bytes:
    from google.cloud import storage  # noqa: PLC0415

    bucket, key = _split_gs_uri(uri)
    return storage.Client().bucket(bucket).blob(key).download_as_bytes()


def _upload_gcs_bytes(uri: str, data: bytes, content_type: str) -> None:
    from google.cloud import storage  # noqa: PLC0415

    bucket, key = _split_gs_uri(uri)
    storage.Client().bucket(bucket).blob(key).upload_from_string(data, content_type=content_type)


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


class ProposalFromQuoteCreate(BaseModel):
    customer_id: Optional[int] = None
    property_id: Optional[int] = None
    title: Optional[str] = None


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


def _money(payload: dict, field: str) -> float:
    value = payload.get(field)
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _knowify_qty(row: dict) -> float:
    """Knowify deliverable Quantity is scaled by 100 in the MCP/API layer.

    Example observed live: a line named "(Qty.: 29 Squares)" has Quantity=2900.
    Convert to human units before using it as proposal-facing measurements.
    """
    try:
        return float(row.get("Quantity") or 0) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _knowify_legacy_measurements(line_items: list[dict]) -> dict:
    """Derive quote-facing legacy measurements from Knowify deliverables.

    These are not Roofr roof-plane measurements. They are the quantity/unit values
    Knowify used to price the quote, which is enough to make imported proposals
    native while preserving source provenance.
    """
    total_squares = 0.0
    unit_breakdown: dict[str, float] = {}
    square_items = []
    for item in line_items:
        qty = _knowify_qty(item)
        if qty <= 0:
            continue
        unit = str(item.get("UnitName") or "").strip()
        if unit:
            unit_breakdown[unit] = unit_breakdown.get(unit, 0.0) + qty
        if unit.lower() in {"square", "squares", "sq", "sq."}:
            total_squares += qty
            square_items.append({
                "description": item.get("Description"),
                "quantity": qty,
                "unit": unit,
            })
    return {
        "source": "knowify_deliverables",
        "note": (
            "Knowify did not expose Roofr roof-plane measurements through the MCP/API. "
            "These values are legacy quote deliverable quantities used for pricing."
        ),
        "total_squares": total_squares,
        "unit_breakdown": unit_breakdown,
        "square_items": square_items,
    }


def _norm_addr(value) -> str:
    return str(value or "").strip().lower()


def _parse_knowify_dt(raw):
    """Parse a Knowify ISO datetime to a naive-UTC datetime (matches our columns)."""
    from datetime import datetime, timezone

    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


_STALE_SENT_DAYS = 90


def knowify_proposal_state(contract: dict) -> dict:
    """Map Knowify business/sign state to native proposal lifecycle."""
    from datetime import datetime, timedelta, timezone

    business_state = str(contract.get("BusinessState") or "").strip()
    signed = bool(contract.get("IsSigned"))
    created = _parse_knowify_dt(contract.get("DateCreated"))

    status = "draft"
    sent_at = None
    accepted_at = None

    if signed or business_state in ("Open", "Closed", "Completed"):
        status = "accepted"
        sent_at = created
        accepted_at = created
    elif business_state == "OutForSigning":
        status = "sent"
        sent_at = created
    elif business_state in ("Lost", "Cancelled", "Declined"):
        status = "declined"
        sent_at = created

    if status == "sent" and created is not None:
        age = datetime.now(timezone.utc).replace(tzinfo=None) - created
        if age > timedelta(days=_STALE_SENT_DAYS):
            status = "declined"

    return {"status": status, "created_at": created, "sent_at": sent_at, "accepted_at": accepted_at}


def _load_knowify_quote(db: Session, contract_id: str) -> dict:
    tenant_id = _tenant_id(db)
    contract_row = db.execute(
        select(KnowifyRawRecord).where(
            KnowifyRawRecord.tenant_id == tenant_id,
            KnowifyRawRecord.entity == "contracts",
            KnowifyRawRecord.knowify_id == contract_id,
            KnowifyRawRecord.is_present == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if contract_row is None:
        raise HTTPException(404, "contract not found")

    contract_payload = contract_row.payload or {}
    project_id = str(contract_payload.get("ProjectId") or "")

    deliverable_rows = db.execute(
        select(KnowifyRawRecord).where(
            KnowifyRawRecord.tenant_id == tenant_id,
            KnowifyRawRecord.entity == "deliverables",
            KnowifyRawRecord.is_present == True,  # noqa: E712
        )
    ).scalars().all()
    line_items = [
        _pick(r.payload or {}, _DELIVERABLE_FIELDS)
        for r in deliverable_rows
        if str((r.payload or {}).get("ContractId") or "") == contract_id
    ]

    project_address = None
    if project_id:
        project_rows = db.execute(
            select(KnowifyRawRecord).where(
                KnowifyRawRecord.tenant_id == tenant_id,
                KnowifyRawRecord.entity == "projects",
                KnowifyRawRecord.is_present == True,  # noqa: E712
            )
        ).scalars().all()
        for r in project_rows:
            project_payload = r.payload or {}
            if str(project_payload.get("Id") or "") == project_id:
                project_address = _pick(project_payload, _PROJECT_ADDRESS_FIELDS)
                break

    return {
        "contract_id": contract_id,
        "contract": _pick(contract_payload, _CONTRACT_FIELDS),
        "line_items": line_items,
        "project_address": project_address,
        "project_id": project_id,
        "content_hash": contract_row.content_hash,
    }


def _existing_knowify_import(db: Session, tenant_id: int, contract_id: str) -> Proposal | None:
    rows = db.execute(
        select(Proposal).where(Proposal.tenant_id == tenant_id)
    ).scalars().all()
    for row in rows:
        snap = row.quote_snapshot or {}
        if (
            snap.get("source") == "knowify_import"
            and str(snap.get("source_ref") or "") == contract_id
        ):
            return row
    return None


def _matching_property_ids_for_project_address(
    db: Session,
    tenant_id: int,
    customer_id: int,
    project_address: dict | None,
) -> set[int]:
    if not project_address:
        return set()

    wanted = (
        _norm_addr(project_address.get("Address1")),
        _norm_addr(project_address.get("City")),
        _norm_addr(project_address.get("StateProvince")),
        _norm_addr(project_address.get("Zip")),
    )
    if not wanted[0] or not wanted[1] or not wanted[2]:
        return set()

    rows = db.execute(
        select(Property).where(
            Property.tenant_id == tenant_id,
            Property.customer_id == customer_id,
        )
    ).scalars().all()
    return {
        row.id for row in rows
        if (
            _norm_addr(row.street),
            _norm_addr(row.city),
            _norm_addr(row.state),
            _norm_addr(row.zip),
        ) == wanted
    }


def _matching_property_ids_for_project_crosswalk(
    db: Session,
    tenant_id: int,
    customer_id: int,
    project_id: str,
) -> set[int]:
    if not project_id:
        return set()

    rows = db.execute(
        select(Proposal.property_id)
        .join(Job, Job.proposal_id == Proposal.id)
        .where(
            Job.tenant_id == tenant_id,
            Job.knowify_job_id == project_id,
            Proposal.tenant_id == tenant_id,
            Proposal.property_id.isnot(None),
        )
    ).all()
    candidate_ids = {pid for (pid,) in rows if pid is not None}
    if not candidate_ids:
        return set()
    valid = db.execute(
        select(Property.id).where(
            Property.id.in_(candidate_ids),
            Property.tenant_id == tenant_id,
            Property.customer_id == customer_id,
        )
    ).all()
    return {pid for (pid,) in valid}


def _resolve_import_property_id(
    db: Session,
    *,
    tenant_id: int,
    customer_id: int,
    property_id: int | None,
    project_id: str,
    project_address: dict | None,
) -> int:
    if property_id is not None:
        row = db.execute(
            select(Property.id).where(
                Property.id == property_id,
                Property.tenant_id == tenant_id,
                Property.customer_id == customer_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(422, "property_id must belong to customer_id for this tenant")
        return row

    matches = (
        _matching_property_ids_for_project_crosswalk(db, tenant_id, customer_id, project_id)
        | _matching_property_ids_for_project_address(
            db, tenant_id, customer_id, project_address
        )
    )
    if len(matches) == 1:
        return next(iter(matches))
    if len(matches) > 1:
        raise HTTPException(422, "property_id is required; Knowify project matched multiple properties")

    # Fallback for older Knowify quotes: many projects have no job-site address, but
    # the customer has exactly one backfilled property from the client billing address.
    # That is safe; multiple properties remains ambiguous and must be chosen manually.
    customer_properties = db.execute(
        select(Property.id).where(
            Property.tenant_id == tenant_id,
            Property.customer_id == customer_id,
        )
    ).all()
    candidate_ids = [pid for (pid,) in customer_properties if pid is not None]
    if len(candidate_ids) == 1:
        return candidate_ids[0]

    raise HTTPException(422, "property_id is required; no safe Knowify project match found")


def _resolve_import_customer_id(
    db: Session,
    *,
    tenant_id: int,
    customer_id: int | None,
    contract: dict,
) -> int:
    if customer_id is not None:
        row = db.execute(
            select(Customer.id).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(422, "customer_id must belong to this tenant")
        return row

    knowify_client_id = contract.get("ClientId")
    if knowify_client_id is None:
        raise HTTPException(422, "customer_id is required; Knowify quote has no ClientId")
    row = db.execute(
        select(Customer.id).where(
            Customer.tenant_id == tenant_id,
            Customer.knowify_customer_id == str(knowify_client_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(422, "customer_id is required; Knowify ClientId is not backfilled")
    return row


def _build_knowify_quote_snapshot(quote: dict) -> dict:
    contract = quote["contract"]
    line_items = quote["line_items"]
    total = _money(contract, "CurrentContractSum") or _money(contract, "OriginalContractSum")
    deposit = _money(contract, "DepositAmount")
    title = contract.get("ContractName") or f"Knowify quote {quote['contract_id']}"
    legacy_measurements = _knowify_legacy_measurements(line_items)

    return {
        "source": "knowify_import",
        "source_ref": quote["contract_id"],
        "contract": contract,
        "line_items": line_items,
        "total": total,
        "deposit": deposit,
        "project_address": quote["project_address"],
        "legacy_measurements": legacy_measurements,
        # Compatibility fields expected by existing proposal rendering/send paths.
        "pricing_config_hash": quote.get("content_hash") or f"knowify_import:{quote['contract_id']}",
        "sent_at_iso": None,
        "roof_type": "legacy_knowify_quote",
        "num_squares": legacy_measurements["total_squares"],
        "tiers": {
            "legacy": {
                "label": "Knowify Quote",
                "description": title,
                "total": total,
                "line_items": line_items,
            }
        },
        "optional_items": [],
        "deposit_policy": {
            "mode": "fixed" if deposit else "none",
            "value": deposit,
            "amount": deposit,
            "instructions": "Imported from Knowify DepositAmount",
        },
        "floors": {
            "min_profit_pct": 0,
            "min_profit_plus_oh_pct": 0,
        },
        "estimator_version": "knowify_import",
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
    limit: int = Query(50, ge=1, le=200),
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    tenant_id = _tenant_id(db)
    offset = (page - 1) * limit if page is not None else skip
    base = (
        select(Proposal, Customer.display_name, Property.street, Property.city, Property.state)
        .join(Customer, Proposal.customer_id == Customer.id)
        .join(Property, Proposal.property_id == Property.id)
        .where(Proposal.tenant_id == tenant_id)
    )
    if status:
        base = base.where(Proposal.status == status)
    if customer_id:
        base = base.where(Proposal.customer_id == customer_id)

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    status_rows = db.execute(
        select(Proposal.status, func.count())
        .where(Proposal.tenant_id == tenant_id)
        .group_by(Proposal.status)
    ).all()
    status_counts = {str(st): int(count) for st, count in status_rows}
    stmt = base.order_by(Proposal.created_at.desc()).offset(offset).limit(limit)
    results = db.execute(stmt).all()

    out = []
    for row, cname, street, city, state in results:
        d = _proposal_row(row)
        d["customer_name"] = cname
        d["property_address"] = f"{street}, {city} {state}" if street else None
        snap = row.quote_snapshot or {}
        tiers = snap.get("tiers") or {}
        legacy = tiers.get("legacy") or {}
        d["amount"] = snap.get("total") or legacy.get("total") or 0
        out.append(d)
    return {"items": out, "total": total, "status_counts": status_counts}


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


@router.post("/quoting/proposals/from-quote/{contract_id}")
def create_proposal_from_quote(
    contract_id: str,
    body: ProposalFromQuoteCreate,
    claims=Depends(require_role("quoting_create")),
    db: Session = Depends(get_db_session),
):
    """Create a native draft proposal from a mirrored Knowify quote/contract.

    Idempotency is keyed by quote_snapshot.source/source_ref for the resolved tenant:
    retrying the same contract import returns the existing proposal row instead of
    creating a duplicate.
    """
    tenant_id = _tenant_id(db)
    email = claims.get("email") or "unknown"

    quote = _load_knowify_quote(db, contract_id)
    existing = _existing_knowify_import(db, tenant_id, contract_id)
    if existing is not None:
        return _proposal_row(existing)

    customer_id = _resolve_import_customer_id(
        db,
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        contract=quote["contract"],
    )

    property_id = _resolve_import_property_id(
        db,
        tenant_id=tenant_id,
        customer_id=customer_id,
        property_id=body.property_id,
        project_id=quote["project_id"],
        project_address=quote["project_address"],
    )
    snapshot = _build_knowify_quote_snapshot(quote)
    title = body.title or quote["contract"].get("ContractName") or f"Knowify quote {contract_id}"
    state = knowify_proposal_state(quote["contract"])

    row = Proposal(
        tenant_id=tenant_id,
        customer_id=customer_id,
        property_id=property_id,
        title=title,
        quote_snapshot=snapshot,
        status=state["status"],
        accept_token=generate_accept_token(),
        accepted_at=state["accepted_at"],
        sent_at=state["sent_at"],
        created_by=email,
        created_at=state["created_at"] or _utcnow(),
        updated_at=state["created_at"] or _utcnow(),
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
      New row is created as a draft so the user can edit/review it before sending.
    """
    tenant_id = _tenant_id(db)
    email = claims.get("email") or "unknown"
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
        status="draft",
        accept_token=new_fields["accept_token"],
        created_by=email,
    )
    db.add(new_row)

    # supersede() validates the transition and returns {"status": "superseded"}
    supersede_fields = supersede(prev_dict)
    prev.status = supersede_fields["status"]

    db.flush()

    db.flush()
    db.refresh(new_row)
    return _proposal_row(new_row)


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



def render_and_cache_proposal_pdf(db: Session, row: Proposal) -> bytes:
    """Render a native proposal PDF, upload it to GCS, stamp quote_snapshot, return bytes."""
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

    try:
        tc_ctx = _load_tc_context(db)
        for key, value in tc_ctx.items():
            setattr(ctx, key, value)
    except Exception as exc:
        _log.warning("tc context loading failed for proposal %s: %s", row.id, exc)

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

    try:
        gcs_uri = f"gs://{_media_bucket()}/{_proposal_pdf_key(row)}"
        _upload_gcs_bytes(gcs_uri, pdf_bytes, "application/pdf")
        row.quote_snapshot = {**snap, "rendered_pdf_gcs": gcs_uri}
        db.flush()
    except Exception as exc:
        _log.warning("proposal pdf GCS upload failed id=%s err=%s", row.id, exc)

    return pdf_bytes


@router.get("/quoting/proposals/{proposal_id}/pdf")
def get_proposal_pdf(
    proposal_id: int,
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    """Render the current proposal as PDF via Gotenberg and stream it.

    Returns 503 if GOTENBERG_URL is not configured.
    """
    tenant_id = _tenant_id(db)
    row = db.execute(
        select(Proposal).where(
            Proposal.id == proposal_id,
            Proposal.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    snap = row.quote_snapshot or {}

    # Prefer original Knowify PDF bytes once archived, then cached rendered bytes.
    for uri in (
        ((snap.get("knowify_pdf") or {}).get("gcs_uri") if isinstance(snap.get("knowify_pdf"), dict) else None),
        snap.get("rendered_pdf_gcs"),
    ):
        if isinstance(uri, str) and uri.startswith("gs://"):
            try:
                return Response(
                    content=_download_gcs_bytes(uri),
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="proposal-{proposal_id}.pdf"'},
                )
            except Exception as exc:
                _log.warning("proposal pdf GCS cache miss/read failed id=%s uri=%s err=%s", proposal_id, uri, exc)

    gotenberg_url = os.environ.get("GOTENBERG_URL", "")
    if not gotenberg_url:
        raise HTTPException(503, "PDF rendering unavailable: GOTENBERG_URL is not configured")

    pdf_bytes = render_and_cache_proposal_pdf(db, row)

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
_SIGN_PUBLIC_URL = os.environ.get("SIGN_PUBLIC_URL", _PUBLIC_APP_URL)


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

    public_url = os.environ.get("SIGN_PUBLIC_URL") or os.environ.get("PUBLIC_APP_URL", _SIGN_PUBLIC_URL)
    accept_url = f"{public_url.rstrip('/')}/p/{accept_token}"

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
