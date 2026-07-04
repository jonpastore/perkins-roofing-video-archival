"""Email engine routes — templates CRUD, Gemini proofread, and Resend send.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - email_compose / email_proof / email_send  → sales or admin
  - manage_templates (POST/PUT/DELETE templates) → admin only
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

import adapters.resend as resend_adapter
from api.auth import require_role
from app.llm import chat
from app.models import EmailTemplate, SessionLocal
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

@router.post("/send")
def send_email(req: SendRequest, claims=Depends(require_role("email_send"))):
    sender_email = claims.get("email", "")
    # Strip CRLF from subject to prevent header injection
    safe_subject = req.subject.replace("\r", "").replace("\n", "")
    msg_id = resend_adapter.send(
        from_name="Perkins Roofing",
        reply_to=sender_email,
        to=str(req.to),
        subject=safe_subject,
        html=req.html,
    )
    return {"id": msg_id}
