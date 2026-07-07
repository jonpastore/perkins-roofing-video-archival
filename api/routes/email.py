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
from pydantic import BaseModel, EmailStr

import adapters.resend as resend_adapter
from api.auth import require_role
from app.config import settings
from app.llm import chat
from app.models import EmailTemplate, PlatformConfig, SessionLocal
from core.email_proof import build_proof_prompt, diff_suggestions

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
def list_templates(claims=Depends(require_role("email_compose"))):
    with SessionLocal() as db:
        rows = db.query(EmailTemplate).all()
        return [
            {"id": r.id, "name": r.name, "subject": r.subject, "body": r.body,
             "created_by": r.created_by}
            for r in rows
        ]


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, claims=Depends(require_role("manage_templates"))):
    with SessionLocal() as db:
        tmpl = EmailTemplate(
            name=body.name,
            subject=body.subject,
            body=body.body,
            created_by=claims.get("email", ""),
        )
        db.add(tmpl)
        db.commit()
        db.refresh(tmpl)
        return {"id": tmpl.id, "name": tmpl.name, "subject": tmpl.subject,
                "body": tmpl.body, "created_by": tmpl.created_by}


@router.put("/templates/{template_id}")
def update_template(template_id: int, body: TemplateIn,
                    claims=Depends(require_role("manage_templates"))):
    from fastapi import HTTPException
    with SessionLocal() as db:
        tmpl = db.get(EmailTemplate, template_id)
        if tmpl is None:
            raise HTTPException(status_code=404, detail="template not found")
        tmpl.name = body.name
        tmpl.subject = body.subject
        tmpl.body = body.body
        db.commit()
        return {"id": tmpl.id, "name": tmpl.name, "subject": tmpl.subject,
                "body": tmpl.body, "created_by": tmpl.created_by}


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int, claims=Depends(require_role("manage_templates"))):
    from fastapi import HTTPException
    with SessionLocal() as db:
        tmpl = db.get(EmailTemplate, template_id)
        if tmpl is None:
            raise HTTPException(status_code=404, detail="template not found")
        db.delete(tmpl)
        db.commit()


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
    with SessionLocal() as db:
        row = db.get(PlatformConfig, "EMAIL_HTML_HEADER")
    if row is not None:
        return row.value or ""
    return settings.EMAIL_HTML_HEADER or ""


@router.post("/send")
def send_email(req: SendRequest, claims=Depends(require_role("email_send"))):
    sender_email = claims.get("email", "")
    # Strip CRLF from subject to prevent header injection
    safe_subject = req.subject.replace("\r", "").replace("\n", "")
    header_html = _get_email_html_header()
    html_body = (header_html + req.html) if header_html else req.html
    msg_id = resend_adapter.send(
        from_name="Perkins Roofing",
        reply_to=sender_email,
        to=str(req.to),
        subject=safe_subject,
        html=html_body,
    )
    return {"id": msg_id}


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
