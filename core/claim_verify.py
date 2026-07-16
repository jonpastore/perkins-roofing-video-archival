"""Verify a typed claim against Tim's transcripts: retrieve, extract slots, compare in code.

The division of labour is the whole design:

    retrieval  -> finds candidate spans                       (code)
    the model  -> reports WHAT A SPAN STATES, into slots      (model, narrow, no judgement)
    comparison -> decides whether that supports the claim     (code, core.claims.compare)

The model is never asked "does this support the claim?". That question is what the three
critic lenses already answer, and they answer "clean" to everything. It is also what the v1
design asked, dressed up as "quote your evidence and we'll string-match the quote" — GPT-5 and
Grok independently showed that verifies the span EXISTS, not that it SUPPORTS: "Some
contractors recommend X" is a real span that says nothing about what Tim recommends.

Retrieval recall is now load-bearing. Once a verdict can gate, a retrieval miss becomes a
false accusation of invention — so UNVERIFIABLE (found nothing to check against) is a distinct
verdict from UNSUPPORTED (checked, no support). Conflating them makes a gate a randomiser.

See docs/superpowers/specs/claim-grounding.md.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from core.claims import Claim, ClaimType, Verdict, compare

logger = logging.getLogger(__name__)

# One claim -> one span -> one judgement. Batching claims into a single call lets one quote get
# reused across several of them, which is support laundering with a cost saving attached.
MAX_SPANS_PER_CLAIM = 6
WINDOW_SECS = 45.0          # support is usually a sentence away, not in the matched chunk


@dataclass
class ClaimResult:
    claim: Claim
    verdict: Verdict
    span_text: str = ""
    video_id: str = ""
    start: float = 0.0
    note: str = ""

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}?t={int(self.start)}" if self.video_id else ""


_SLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "states_anything": {"type": "boolean"},
        "subject": {"type": "string"},
        "measure": {"type": "string"},
        "value_lo": {"type": "number"},
        "value_hi": {"type": "number"},
        "unit": {"type": "string"},
        "qualifier": {"type": "string"},
        "condition": {"type": "string"},
        "entity": {"type": "string"},
        "speaker": {"type": "string"},
        "stance": {"type": "string",
                   "enum": ["asserts", "rejects", "reports_others", "offers_option", "none"]},
        "force": {"type": "string"},
        "proposition": {"type": "string"},
    },
    "required": ["states_anything"],
}

_EXTRACT_PROMPT = """You are reading ONE span of a transcript from a Florida roofer's video.

Report ONLY what this span itself states. Do NOT judge, agree, or relate it to anything else.
Do NOT infer. If the span does not state a {kind}, set states_anything=false and stop.

Fill these slots from the span, using ITS OWN words:
- subject     : what the statement is ABOUT
- measure     : what is being measured, precisely. "lifespan" and "time_to_failure" are
                DIFFERENT: "lasts 10-15 years" is lifespan; "I've seen some fail in 10-15
                years" is time_to_failure. Report which one the span actually says.
- value_lo/hi : the number or range (same number twice if a point value)
- unit        : years, months, inches, mils, squares, usd, percent, mph ...
- qualifier   : typical / minimum / observed / warranty ... only if the span says so
- condition   : any "in X" / "on Y" / "when Z" the span attaches
- entity      : the exact code, brand, product or place named
- speaker     : WHO is asserting it, in the span's words. "I"/"we" = the roofer speaking.
                If the span says "some contractors" or "they", the speaker is THEM, not him.
- stance      : asserts | rejects | reports_others | offers_option
- force       : the modality AS WRITTEN. "almost never" is NOT "never" — report "almost never".
                Do not strengthen a hedge.
- proposition : one short sentence of what the span asserts

SPAN:
{span}

Return JSON only."""


def _exact_hits(term: str, db, limit: int = 8) -> list:
    """Exact lookup before semantic search. For a code or a brand, ILIKE is both cheaper and
    strictly better than an embedding — 'ASTM D226' either appears or it does not."""
    from app.models import Chunk  # noqa: PLC0415

    t = (term or "").strip()
    if len(t) < 3:
        return []
    return db.query(Chunk).filter(Chunk.text.ilike(f"%{t}%")).limit(limit).all()


def _window(chunk, db) -> str:
    """The matched chunk plus its neighbours — support is often one sentence either side, and
    a chunk boundary is an artefact of ingestion, not of meaning."""
    from app.models import Chunk  # noqa: PLC0415

    rows = (db.query(Chunk)
            .filter(Chunk.video_id == chunk.video_id,
                    Chunk.start >= (chunk.start or 0) - WINDOW_SECS,
                    Chunk.start <= (chunk.start or 0) + WINDOW_SECS)
            .order_by(Chunk.start).all())
    return " ".join((c.text or "").strip() for c in rows) or (chunk.text or "")


def candidate_spans(claim: Claim, db, source_chunks: list | None = None) -> list:
    """Spans worth checking this claim against, exact-match first.

    `source_chunks` is the article's own evidence when available; the corpus is the fallback,
    because a claim may cite something Tim said in a video this article didn't draw from —
    that is 'reached outside its evidence', which is different from 'invented'.
    """
    seen: dict = {}
    for term in claim.key_terms():
        for c in _exact_hits(term, db):
            seen.setdefault((c.video_id, c.start), c)
        if len(seen) >= MAX_SPANS_PER_CLAIM:
            break
    if not seen and source_chunks:
        for c in source_chunks[:MAX_SPANS_PER_CLAIM]:
            seen.setdefault((c.video_id, c.start), c)
    return list(seen.values())[:MAX_SPANS_PER_CLAIM]


def read_span(span_text: str, claim_type: ClaimType, *, llm) -> Claim | None:
    """Ask the model to REPORT what a span states. It never judges support."""
    from core.json_repair import parse_model_json  # noqa: PLC0415

    kind = {ClaimType.NUMBER: "number or measurement",
            ClaimType.CODE: "code or standard",
            ClaimType.PRODUCT: "product or brand",
            ClaimType.PLACE: "place or jurisdiction",
            ClaimType.ATTRIBUTION: "statement by a person",
            ClaimType.MODAL: "rule or absolute"}.get(claim_type, "statement")
    prompt = _EXTRACT_PROMPT.format(kind=kind, span=span_text[:4000])
    try:
        try:
            raw = llm.chat(prompt, want_json=True, response_schema=_SLOT_SCHEMA)
        except TypeError:
            raw = llm.chat(prompt, want_json=True)
        d = parse_model_json(raw) if isinstance(raw, str) else raw
    except Exception as exc:  # noqa: BLE001
        logger.warning("span read failed: %s", exc)
        return None
    if not isinstance(d, dict) or not d.get("states_anything"):
        return None
    lo, hi = d.get("value_lo"), d.get("value_hi")
    value = (float(lo), float(hi)) if lo is not None and hi is not None else None
    return Claim(
        type=claim_type, sentence=span_text[:400],
        subject=d.get("subject") or None, measure=d.get("measure") or None,
        value=value, unit=d.get("unit") or None, qualifier=d.get("qualifier") or None,
        condition=d.get("condition") or None, entity=d.get("entity") or None,
        speaker=d.get("speaker") or None,
        stance=(d.get("stance") if d.get("stance") != "none" else None),
        force=d.get("force") or None, proposition=d.get("proposition") or None,
    )


def _in_corpus(claim: Claim, vocab: frozenset[str]) -> bool:
    """Has Tim ever said the claim's distinctive terms, anywhere in 801 videos?

    Separates OUT_OF_CORPUS ("Solar Reflectance Index": 0 hits in 14,592 chunks — the article
    imported an ASTM standard from the model's own knowledge) from UNSUPPORTED (his words, but
    this article's sources don't back this assertion). Different diagnoses, different remedies.
    """
    if not vocab:
        return True     # no vocabulary loaded: never accuse on missing evidence
    terms = " ".join(t for t in claim.key_terms() if t)
    words = [w for w in re.findall(r"[a-z0-9]+", terms.lower()) if len(w) > 3]
    return all(w in vocab for w in words) if words else True


def verify_claim(claim: Claim, db, *, llm, vocab: frozenset[str] = frozenset(),
                 source_chunks: list | None = None) -> ClaimResult:
    """One claim, verified. Report-only — this returns a verdict, it never edits anything."""
    spans = candidate_spans(claim, db, source_chunks)
    if not spans:
        if not _in_corpus(claim, vocab):
            return ClaimResult(claim, Verdict.OUT_OF_CORPUS,
                               note="no chunk in 801 videos contains these terms")
        # Nothing retrieved is a RETRIEVAL failure. Calling it an invention is how a gate
        # becomes a randomiser.
        return ClaimResult(claim, Verdict.UNVERIFIABLE, note="retrieval found no candidates")

    best: ClaimResult | None = None
    rank = {Verdict.SUPPORTED: 6, Verdict.PARTIAL: 5, Verdict.INFLATED: 4,
            Verdict.CONTRADICTED: 3, Verdict.UNSUPPORTED: 2, Verdict.UNVERIFIABLE: 1,
            Verdict.OUT_OF_CORPUS: 0}
    for chunk in spans:
        text = _window(chunk, db)
        span_claim = read_span(text, claim.type, llm=llm)
        if span_claim is None:
            continue
        v = compare(claim, span_claim)
        r = ClaimResult(claim, v, span_text=text[:600], video_id=chunk.video_id,
                        start=chunk.start or 0.0)
        if best is None or rank[v] > rank[best.verdict]:
            best = r
        if v is Verdict.SUPPORTED:
            return r        # a verified span is the answer; stop paying for more
    if best is None:
        return ClaimResult(claim, Verdict.UNVERIFIABLE, note="no span could be read")
    return best
