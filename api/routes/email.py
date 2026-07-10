"""Email engine routes — templates CRUD, Gemini proofread, Resend send, and AI draft.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - email_compose / email_proof / email_send  → sales or admin
  - manage_templates (POST/PUT/DELETE templates) → admin only
"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

import adapters.resend as resend_adapter
from api.auth import get_db_session, require_role
from app.config import settings
from app.llm import chat
from app.models import EmailTemplate, PlatformConfig, PlatformSessionLocal
from core.email_proof import build_proof_prompt, diff_suggestions
from core.email_template import wrap_email

router = APIRouter(prefix="/email", tags=["email"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class TemplateIn(BaseModel):
    name: str
    subject: str
    body: str


class ProofRequest(BaseModel):
    draft: str


class SendRequest(BaseModel):
    to: EmailStr
    subject: str
    html: str


class DraftSource(BaseModel):
    title: str
    snippet: str
    url: str


class DraftRequest(BaseModel):
    sources: list[DraftSource]
    intro: Optional[str] = None


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------

@router.get("/templates")
def list_templates(
    claims=Depends(require_role("email_compose")),
    db: Session = Depends(get_db_session),
):
    rows = db.query(EmailTemplate).all()
    return [
        {"id": r.id, "name": r.name, "subject": r.subject, "body": r.body,
         "created_by": r.created_by}
        for r in rows
    ]


@router.post("/templates", status_code=201)
def create_template(
    body: TemplateIn,
    claims=Depends(require_role("manage_templates")),
    db: Session = Depends(get_db_session),
):
    tmpl = EmailTemplate(
        tenant_id=db.info["tenant_id"],
        name=body.name,
        subject=body.subject,
        body=body.body,
        created_by=claims.get("email", ""),
    )
    db.add(tmpl)
    db.flush()
    db.refresh(tmpl)
    return {"id": tmpl.id, "name": tmpl.name, "subject": tmpl.subject,
            "body": tmpl.body, "created_by": tmpl.created_by}


@router.put("/templates/{template_id}")
def update_template(
    template_id: int,
    body: TemplateIn,
    claims=Depends(require_role("manage_templates")),
    db: Session = Depends(get_db_session),
):
    tmpl = db.get(EmailTemplate, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    tmpl.name = body.name
    tmpl.subject = body.subject
    tmpl.body = body.body
    db.flush()
    return {"id": tmpl.id, "name": tmpl.name, "subject": tmpl.subject,
            "body": tmpl.body, "created_by": tmpl.created_by}


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    claims=Depends(require_role("manage_templates")),
    db: Session = Depends(get_db_session),
):
    tmpl = db.get(EmailTemplate, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    db.delete(tmpl)
    db.flush()


# ---------------------------------------------------------------------------
# Proofread
# ---------------------------------------------------------------------------

@router.post("/proof")
def proof_email(req: ProofRequest, claims=Depends(require_role("email_proof"))):
    prompt = build_proof_prompt(req.draft)
    proofed = chat(prompt)
    suggestions = diff_suggestions(req.draft, proofed)
    return {"proofed": proofed, "suggestions": suggestions}


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def _get_email_html_header() -> str:
    """Return the configured global email header HTML (db override takes precedence over env)."""
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        row = db.get(PlatformConfig, "EMAIL_HTML_HEADER")
    if row is not None:
        return row.value or ""
    return settings.EMAIL_HTML_HEADER or ""


def _claims_display_name(claims: dict) -> str:
    """Derive a display name from verified token claims.

    Tries ``name`` claim first; falls back to title-casing the local-part of
    the email address (e.g. "jane.smith@..." → "Jane Smith").
    """
    name = claims.get("name", "")
    if name:
        return name
    email = claims.get("email", "")
    local = email.split("@")[0] if "@" in email else email
    return local.replace(".", " ").replace("_", " ").title() or "Perkins Roofing"


def _sender_from_address(sender_email: str) -> str:
    """Return a perkinsroofing.net From address for the authenticated user.

    Users sign in with Google (any domain). We always send from the verified
    perkinsroofing.net domain; the user's address goes in reply-to so replies
    land in their inbox.
    """
    if not sender_email:
        return resend_adapter._DEFAULT_FROM_EMAIL
    local = sender_email.split("@")[0]
    # Sanitise: strip characters that are not safe in an email local-part
    safe_local = re.sub(r"[^a-zA-Z0-9.+_-]", "", local) or "noreply"
    return f"{safe_local}@perkinsroofing.net"


@router.post("/send")
def send_email(req: SendRequest, claims=Depends(require_role("email_send"))):
    sender_email = claims.get("email", "")
    # Strip CRLF from subject to prevent header injection
    safe_subject = req.subject.replace("\r", "").replace("\n", "")
    header_html = _get_email_html_header()
    wrapped_html = wrap_email(body_html=req.html, header_html=header_html)
    display_name = _claims_display_name(claims)
    from_address = _sender_from_address(sender_email)
    msg_id = resend_adapter.send(
        from_name=display_name,
        from_email=from_address,
        reply_to=sender_email or resend_adapter._DEFAULT_FROM_EMAIL,
        to=str(req.to),
        subject=safe_subject,
        html=wrapped_html,
    )
    return {"id": msg_id}


@router.post("/preview", response_class=HTMLResponse)
def preview_email(req: SendRequest, claims=Depends(require_role("email_compose"))):
    """Return the branded HTML wrapper for a given body — used by the compose UI
    to render a live preview in an iframe without duplicating the wrap logic."""
    header_html = _get_email_html_header()
    return HTMLResponse(content=wrap_email(body_html=req.html, header_html=header_html))


# ---------------------------------------------------------------------------
# AI draft generation
# ---------------------------------------------------------------------------

# Markdown artifact patterns that must NOT appear in the final HTML output.
_MD_BULLET = re.compile(r"(^|\n)[\*\-\•] ")          # leading bullet chars
_MD_LINK = re.compile(r"\]\(")                         # markdown link syntax  ](
_BARE_URL = re.compile(r"(?<![\"'])https?://\S+")      # bare http(s) not inside an href


def _html_compliant(html: str) -> bool:
    """Return True only if html is clean structured HTML, False if any compliance rule fails.

    Rules:
    1. Must contain at least one real hyperlink: <a href=
    2. Must NOT contain markdown link syntax: ](
    3. Must NOT contain markdown bullet leaders: line-starting * / - / bullet
    4. Must NOT contain bare URLs outside href attributes
    """
    if "<a href" not in html:
        return False
    if _MD_LINK.search(html):
        return False
    if _MD_BULLET.search(html):
        return False
    # Strip href="..." values before checking for bare URLs so legitimate links don't fail
    stripped = re.sub(r'href="[^"]*"', 'href=""', html)
    if _BARE_URL.search(stripped):
        return False
    return True


def _build_draft_prompt(sources: list[DraftSource], intro: Optional[str]) -> str:
    items = "\n".join(
        f'- Title: {s.title}\n  Snippet: {s.snippet}\n  URL: {s.url}'
        for s in sources
    )
    intro_line = f"\nUse this intro as the opening paragraph:\n{intro}\n" if intro else ""
    return f"""Write a polished, friendly HTML email from Tim Perkins Roofing to a prospective client.
{intro_line}
Include each of the following sources as a proper HTML hyperlink (<a href="URL">descriptive text</a>).
Structure the email with <p> paragraphs and a <ul><li> list for the sources.
Start with a warm greeting and end with:
<p>Best,<br>Tim Perkins Roofing</p>

Sources:
{items}

IMPORTANT RULES:
- Output ONLY valid HTML. No markdown. No ``` fences. No plain text.
- Every URL must appear inside an href attribute, never as bare text.
- Use <ul><li> for the source list, NOT markdown bullets (*, -, •).
- Do NOT use markdown link syntax like [text](url).
"""


@router.post("/draft")
def draft_email(req: DraftRequest, claims=Depends(require_role("email_compose"))):
    """Generate a polished HTML email body from sources, retrying up to 3 times until compliant."""
    if not req.sources:
        raise HTTPException(status_code=422, detail="sources must not be empty")

    prompt = _build_draft_prompt(req.sources, req.intro)
    html = ""
    for _ in range(3):
        html = chat(prompt)
        if _html_compliant(html):
            return {"html": html}
        # Feed the failure back into the next attempt
        prompt = _build_draft_prompt(req.sources, req.intro) + (
            "\n\nPrevious attempt was rejected. Fix ALL of these issues:\n"
            "- Every URL must be inside href=\"...\", not bare text.\n"
            "- No markdown bullets (*, -, •) at line start.\n"
            "- No markdown link syntax ](\n"
            "- Must include at least one <a href= tag.\n"
        )

    raise HTTPException(status_code=502, detail="AI draft did not produce compliant HTML after 3 attempts")
