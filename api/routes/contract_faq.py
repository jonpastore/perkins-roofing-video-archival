"""REST endpoints for the Contract FAQ engine (F5 #321)."""
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role

router = APIRouter(prefix='/contract-faq', tags=['contract-faq'])

GENERATE_MAX = 20
GENERATE_MIN = 1
TC_MIN_LEN = 100


class GenerateRequest(BaseModel):
    tc_text: str
    count: int = 10
    tc_version_id: int | None = None


class AiPromptsRequest(BaseModel):
    tc_text: str
    include_existing_faqs: bool = True


class UpdateRequest(BaseModel):
    question: str | None = None
    answer: str | None = None
    status: str | None = None


def _entry_dict(e) -> dict:
    return {
        'id': e.id,
        'question': e.question,
        'answer': e.answer,
        'quote': e.quote,
        'status': e.status,
        'created_at': e.created_at.isoformat() if e.created_at else None,
    }


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from a PDF upload using pypdf (no OCR).

    Fail loud on encrypted/scanned/unreadable PDFs so the UI can tell the user to
    paste text or upload a text-based PDF. This path handles the Knowify proposal
    PDFs we have locally.
    """
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - dependency installed in app/requirements
        raise HTTPException(500, 'PDF extraction dependency pypdf is not installed') from exc

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise HTTPException(422, 'PDF is encrypted; please upload an unlocked PDF or paste text')
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or '')
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f'Could not extract PDF text: {type(exc).__name__}') from exc

    text = '\n\n'.join(p.strip() for p in pages if p.strip()).strip()
    if len(text) < TC_MIN_LEN:
        raise HTTPException(422, 'PDF text extraction returned too little text; it may be scanned/image-only')
    return text


@router.post('/generate')
def generate_contract_faq(
    body: GenerateRequest,
    db: Session = Depends(get_db_session),
    _: dict = Depends(require_role('manage_articles')),
):
    import app.llm as llm_mod  # noqa: PLC0415
    from app.models import ContractFaqEntry  # noqa: PLC0415
    from core.content_safety import denylist_hits  # noqa: PLC0415
    from core.contract_faq import (  # noqa: PLC0415
        build_contract_faq_prompt,
        grounding_gate,
        parse_contract_faq,
    )

    tc_text = body.tc_text or ''
    if len(tc_text) < TC_MIN_LEN:
        raise HTTPException(status_code=422, detail='tc_text too short (min 100 chars)')

    count = max(GENERATE_MIN, min(body.count, GENERATE_MAX))
    prompt = build_contract_faq_prompt(tc_text, count=count)
    raw = llm_mod.chat(prompt)
    items = parse_contract_faq(raw)
    kept, rejected_grounding = grounding_gate(items, tc_text)

    # M1: idempotency — never stack duplicate drafts for a question that already
    # exists for this tenant (normalized compare, same rule as faq.py mining).
    def _norm_q(q):
        import re  # noqa: PLC0415
        return re.sub(r'[^a-z0-9]+', ' ', (q or '').lower()).strip()
    existing = {_norm_q(q) for (q,) in db.query(ContractFaqEntry.question).all()}

    entries = []
    rejected_safety = 0
    skipped_duplicates = 0
    tenant_id = db.info['tenant_id']  # guaranteed by get_db_session (403 without tenant)
    for item in kept:
        if denylist_hits(item['q'] + ' ' + item['a']):
            rejected_safety += 1
            continue
        nq = _norm_q(item['q'])
        if nq in existing:
            skipped_duplicates += 1
            continue
        existing.add(nq)
        e = ContractFaqEntry(
            question=item['q'],
            answer=item['a'],
            quote=item['quote'],
            status='draft',
            tc_version_id=body.tc_version_id,
            tenant_id=tenant_id,
        )
        db.add(e)
        entries.append(item)
    db.flush()

    return {
        'generated': len(entries),
        'rejected_grounding': len(rejected_grounding),
        'rejected_safety': rejected_safety,
        'skipped_duplicates': skipped_duplicates,
        'entries': entries,
    }


@router.post('/extract-pdf')
async def extract_contract_pdf(
    file: UploadFile = File(...),
    _: dict = Depends(require_role('manage_articles')),
):
    """Extract text from an uploaded contract/proposal PDF for FAQ generation."""
    if file.content_type not in (None, '', 'application/pdf', 'application/octet-stream'):
        raise HTTPException(422, 'Upload must be a PDF')
    data = await file.read()
    if not data:
        raise HTTPException(422, 'Uploaded PDF is empty')
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, 'PDF is too large (max 15MB)')
    text = _extract_pdf_text(data)
    return {'filename': file.filename, 'chars': len(text), 'text': text}


@router.post('/ai-prompts')
def contract_ai_prompts(
    body: AiPromptsRequest,
    db: Session = Depends(get_db_session),
    _: dict = Depends(require_role('kb_contract_faq_read')),
):
    """Return copy/paste AI prompts for contract explanation + FAQ cross-checking."""
    from app.models import ContractFaqEntry  # noqa: PLC0415
    from core.tc_ai_prompts import build_contract_review_prompt  # noqa: PLC0415

    tc_text = body.tc_text or ''
    if len(tc_text) < TC_MIN_LEN:
        raise HTTPException(status_code=422, detail='tc_text too short (min 100 chars)')

    faq_items = []
    if body.include_existing_faqs:
        rows = db.query(ContractFaqEntry).order_by(ContractFaqEntry.id).all()
        faq_items = [{'question': r.question, 'answer': r.answer} for r in rows]
    return build_contract_review_prompt(tc_text, faq_items)


@router.get('')
def list_contract_faq(
    status: str | None = None,
    db: Session = Depends(get_db_session),
    _: dict = Depends(require_role('kb_contract_faq_read')),
):
    from app.models import ContractFaqEntry  # noqa: PLC0415

    q = db.query(ContractFaqEntry).order_by(ContractFaqEntry.id)
    if status:
        q = q.filter(ContractFaqEntry.status == status)
    return [_entry_dict(e) for e in q.all()]


@router.put('/{entry_id}')
def update_contract_faq(
    entry_id: int,
    body: UpdateRequest,
    db: Session = Depends(get_db_session),
    _: dict = Depends(require_role('manage_articles')),
):
    from app.models import ContractFaqEntry  # noqa: PLC0415

    e = db.query(ContractFaqEntry).filter(ContractFaqEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail='Not found')
    if body.status is not None and body.status not in ('draft', 'approved'):
        raise HTTPException(status_code=422, detail='status must be draft or approved')
    if body.question is not None:
        e.question = body.question
    if body.answer is not None:
        e.answer = body.answer
    if body.status is not None:
        e.status = body.status
    db.flush()
    return _entry_dict(e)


@router.delete('/{entry_id}')
def delete_contract_faq(
    entry_id: int,
    db: Session = Depends(get_db_session),
    _: dict = Depends(require_role('manage_articles')),
):
    from app.models import ContractFaqEntry  # noqa: PLC0415

    e = db.query(ContractFaqEntry).filter(ContractFaqEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail='Not found')
    db.delete(e)
    db.flush()
    return {'deleted': True}


@router.get('/jsonld')
def jsonld_contract_faq(
    db: Session = Depends(get_db_session),
    _: dict = Depends(require_role('kb_contract_faq_read')),
):
    from app.models import ContractFaqEntry  # noqa: PLC0415
    from core.jsonld import build_faq_page  # noqa: PLC0415

    entries = (
        db.query(ContractFaqEntry)
        .filter(ContractFaqEntry.status == 'approved')
        .order_by(ContractFaqEntry.id)
        .all()
    )
    items = [{'q': e.question, 'a': e.answer} for e in entries]
    return build_faq_page(items)
