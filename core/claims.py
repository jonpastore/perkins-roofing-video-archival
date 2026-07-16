"""Atomic, typed claims — extraction and MECHANICAL comparison. Pure: no LLM, no I/O.

The load-bearing idea, and the one that killed the previous two attempts if you get it wrong:

    NEVER ask a model "does this span support this claim?"

That is a judgement, and a model judging a model is exactly what the three critic lenses
already do — they answer "clean" to everything. The predecessor asked a model to quote its
evidence and verified the quote existed verbatim, reasoning that it therefore could not bluff.
Both GPT-5 and Grok found the same hole independently: a verbatim quote proves the span EXISTS,
not that it SUPPORTS the claim. All of these pass a string match:

    claim "Tim recommends X"        <- span "Some contractors recommend X"      (attribution)
    claim "lasts 10-15 years"       <- span "I've seen some fail in 10 to 15 years"  (force)
    claim "never use Y"             <- span "I'd almost never use Y in this case"    (modality)
    claim "ASTM D226 required here" <- one span has the code, another has HVHZ  (stitched)

So the model is asked ONLY to extract what a span states, into the same slots. The comparison
happens here, in code, where it can be tested and cannot be talked out of it.

Claims are ATOMIC. A sentence bundling three assertions launders two of them on the support of
one, which is how "sentence + anchor token" (the v1 shape) fails.

See docs/superpowers/specs/claim-grounding.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ClaimType(str, Enum):
    NUMBER = "number"            # "lasts 10-15 years", "$450 a square"
    CODE = "code"                # "ASTM D226", "HVHZ requires" — highest liability
    PRODUCT = "product"          # "Polyflash 1C", "PB77"
    PLACE = "place"              # "Miami-Dade requires"
    ATTRIBUTION = "attribution"  # "Tim recommends", "we always"
    MODAL = "modal"              # "must", "never", "always"


class Verdict(str, Enum):
    """Not binary. v1's binary verdict conflated three different diagnoses with three
    different remedies, and made a retrieval failure indistinguishable from an invention."""
    SUPPORTED = "supported"
    PARTIAL = "partial"              # subject/measure match; qualifier or condition missing
    INFLATED = "inflated"            # source "sometimes" -> article "always"
    CONTRADICTED = "contradicted"    # corpus says the opposite
    OUT_OF_CORPUS = "out_of_corpus"  # Tim never said it anywhere (Solar Reflectance Index)
    UNSUPPORTED = "unsupported"      # in-corpus words, no supporting span
    UNVERIFIABLE = "unverifiable"    # retrieval found nothing — a RETRIEVAL failure, not an
                                     # invention. Conflating the two makes a gate a randomiser.


# Force ranking for modality/scope. A claim may never exceed its source: a span saying
# "sometimes" cannot support an article saying "always". This is the inflation that LLMs do
# constantly and that a support-judgement never catches.
FORCE = {
    "some": 1, "sometimes": 1, "occasionally": 1, "can": 1, "may": 1, "might": 1,
    "often": 2, "usually": 2, "typically": 2, "generally": 2, "most": 2, "should": 2,
    "always": 3, "never": 3, "must": 3, "all": 3, "every": 3, "required": 3, "no": 3,
}

_UNIT_ALIASES = {
    "yr": "years", "yrs": "years", "year": "years",
    "mo": "months", "month": "months",
    "in": "inches", "inch": "inches", '"': "inches",
    "ft": "feet", "foot": "feet", "'": "feet",
    "lf": "linear_feet", "sq": "squares", "square": "squares",
    "mil": "mils", "mph": "mph", "%": "percent", "$": "usd", "dollars": "usd",
}

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
}


@dataclass
class Claim:
    """One atomic assertion. Slots are type-specific; unset slots are None, not guesses."""
    type: ClaimType
    sentence: str                       # the prose it came from (for reporting)
    section_id: str = ""
    subject: str | None = None
    measure: str | None = None          # lifespan | cost | thickness | time_to_failure ...
    value: tuple[float, float] | None = None   # (lo, hi); a point value is (x, x)
    unit: str | None = None
    qualifier: str | None = None        # typical | minimum | observed ...
    condition: str | None = None        # "in south florida", "on tile roofs"
    entity: str | None = None           # code id, brand, sku, jurisdiction
    speaker: str | None = None          # attribution only
    stance: str | None = None           # asserts | rejects | reports_others | offers_option
    force: str | None = None            # modal/scope only
    proposition: str | None = None

    def key_terms(self) -> list[str]:
        """Terms a retriever should look for. Exact-first lookup beats semantic for codes.

        Falls back to the proposition's content words: attribution and modal claims carry no
        entity/subject/measure (they have speaker/force + proposition), so keying only off
        those three left them with NO search terms — retrieval found nothing and every such
        claim came back UNVERIFIABLE forever. A verifier that silently cannot check a whole
        claim class is the failure this design exists to avoid.
        """
        out = [t for t in (self.entity, self.subject, self.measure) if t]
        if out:
            return out
        # Longest content words first: they are the most selective for an ILIKE lookup.
        words = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", self.proposition or self.sentence or "")
        skip = {"tim", "perkins", "recommend", "recommends", "always", "never", "must",
                "should", "this", "that", "with", "from", "your", "they", "them", "will"}
        picked = sorted({w for w in words if w.lower() not in skip}, key=len, reverse=True)
        return picked[:3]


def normalise_unit(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip().lower().rstrip(".")
    return _UNIT_ALIASES.get(u, u)


def normalise_number(tok: str) -> float | None:
    tok = tok.strip().lower().replace(",", "").lstrip("$")
    if tok in _NUM_WORDS:
        return float(_NUM_WORDS[tok])
    try:
        return float(tok)
    except ValueError:
        return None


def force_of(text: str) -> str | None:
    """Strongest modality/scope word present. 'almost never' is deliberately NOT 'never' —
    the hedge is the whole point, and dropping it is how "I'd almost never" became "never"."""
    t = " " + (text or "").lower() + " "
    if re.search(r"\balmost never\b|\brarely\b|\bhardly ever\b", t):
        return "sometimes"
    best, rank = None, 0
    for word, r in FORCE.items():
        if re.search(rf"\b{re.escape(word)}\b", t) and r > rank:
            best, rank = word, r
    return best


def values_match(a: tuple[float, float] | None, b: tuple[float, float] | None,
                 tol: float = 0.0) -> bool:
    """Ranges match when they overlap. A point inside a range matches it.

    Tolerance is 0 by default: for a code or a price, "close" is wrong. Callers pass a
    tolerance only where the measure is genuinely fuzzy.
    """
    if a is None or b is None:
        return False
    alo, ahi = min(a), max(a)
    blo, bhi = min(b), max(b)
    return (alo - tol) <= bhi and (blo - tol) <= ahi


def compare(claim: Claim, span: Claim) -> Verdict:
    """Compare an article's claim against what a source span ACTUALLY states.

    `span` is the model's structured reading of a transcript span — it reports, it does not
    judge. Everything below is mechanical, which is the entire point: this is the step the
    previous designs handed to a model and got laundering for.
    """
    # Entity claims (code / product / place): the identifier must match exactly. "Close" on a
    # code number is a liability on a licensed roofer's site.
    if claim.type in (ClaimType.CODE, ClaimType.PRODUCT, ClaimType.PLACE):
        if not claim.entity or not span.entity:
            return Verdict.UNSUPPORTED
        if _norm(claim.entity) != _norm(span.entity):
            return Verdict.UNSUPPORTED
        # Right code, but is it being applied to the same thing? "ASTM D226 exists" does not
        # support "ASTM D226 is required in HVHZ".
        if claim.proposition and span.proposition and \
                not _loose_eq(claim.proposition, span.proposition):
            return Verdict.PARTIAL
        return Verdict.SUPPORTED

    if claim.type is ClaimType.ATTRIBUTION:
        # The span must be TIM asserting it. "Some contractors recommend X" is a real span and
        # supports nothing about what Tim recommends.
        if _norm(span.speaker or "") not in ("tim", "we", "perkins", "i"):
            return Verdict.UNSUPPORTED
        if span.stance in ("rejects", "reports_others", "offers_option"):
            return Verdict.CONTRADICTED if span.stance == "rejects" else Verdict.UNSUPPORTED
        if claim.proposition and span.proposition and \
                not _loose_eq(claim.proposition, span.proposition):
            return Verdict.UNSUPPORTED
        return Verdict.SUPPORTED

    if claim.type is ClaimType.MODAL:
        cf, sf = FORCE.get(claim.force or "", 0), FORCE.get(span.force or "", 0)
        if not sf:
            return Verdict.UNSUPPORTED
        if cf > sf:
            return Verdict.INFLATED     # "sometimes" in the source, "always" in the article
        return Verdict.SUPPORTED

    if claim.type is ClaimType.NUMBER:
        # The measure must be the same PROPOSITION, not just the same digits. "lasts 10-15
        # years" and "I've seen some fail in 10 to 15 years" share a number and assert
        # opposite things.
        if claim.measure and span.measure and _norm(claim.measure) != _norm(span.measure):
            return Verdict.UNSUPPORTED
        if claim.subject and span.subject and not _loose_eq(claim.subject, span.subject):
            return Verdict.UNSUPPORTED
        if normalise_unit(claim.unit) != normalise_unit(span.unit):
            return Verdict.UNSUPPORTED
        if not values_match(claim.value, span.value):
            return Verdict.CONTRADICTED if span.value else Verdict.UNSUPPORTED
        if claim.condition and not span.condition:
            return Verdict.PARTIAL      # article adds a condition the source never stated
        return Verdict.SUPPORTED

    return Verdict.UNSUPPORTED


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def _loose_eq(a: str, b: str) -> bool:
    """Same proposition, allowing wording drift — content-word overlap, not string equality.

    Deliberately generous: this is the one place strictness would produce false inventions,
    and a false 'invented' is the failure mode that made the last guard destructive.
    """
    ta = {w for w in _norm(a).split() if len(w) > 3}
    tb = {w for w in _norm(b).split() if len(w) > 3}
    if not ta or not tb:
        return _norm(a) == _norm(b)
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.5


# ── extraction (deterministic candidates only) ───────────────────────────────
# Regex finds CANDIDATES, never the proposition: a number is not a self-identifying fact.
# "10 to 15 years" may be a lifespan, a warranty, an inspection interval, or the age of an
# existing roof. The slots are filled by a structured extraction pass; this only says "there
# is a checkable number here, in this sentence".

_SENT = re.compile(r"(?<=[.!?])\s+")
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</(?:h[1-6]|p|li|div)\s*>", re.IGNORECASE)

_RANGE = re.compile(
    r"\$?\b(\d[\d,]*(?:\.\d+)?|" + "|".join(_NUM_WORDS) + r")\s*(?:-|–|to)\s*"
    r"\$?(\d[\d,]*(?:\.\d+)?|" + "|".join(_NUM_WORDS) + r")\s*"
    r"(years?|yrs?|months?|inches|inch|in\b|feet|ft\b|mils?|squares?|sq\b|lf\b|mph|%|percent)",
    re.IGNORECASE)
_POINT = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d+)?)|"
    r"\b(\d[\d,]*(?:\.\d+)?)\s*(years?|yrs?|months?|inches|inch|feet|ft\b|mils?|squares?|"
    r"sq\b|lf\b|mph|%|percent)\b", re.IGNORECASE)
_CODE = re.compile(r"\b(ASTM\s?[A-Z]?\s?\d{2,4}|FBC\s?\d*|HVHZ|NOA\s?\d+|TAS\s?\d+|"
                   r"Miami-?Dade\s+(?:County\s+)?approv\w+)\b", re.IGNORECASE)
_ATTRIB = re.compile(r"\b(Tim|Perkins|we)\s+(recommend\w*|say\w*|explain\w*|use\w*|"
                     r"always|never|prefer\w*|suggest\w*)\b", re.IGNORECASE)
_MODAL = re.compile(r"\b(always|never|must|required|every|all)\b", re.IGNORECASE)


def sentences(content: str) -> list[str]:
    """Prose sentences. Block tags become boundaries so a heading cannot weld onto the
    paragraph beneath it — that welding is what produced phantom terms last time."""
    text = _TAG.sub(" ", _BLOCK.sub(". ", content or ""))
    return [s.strip() for s in _SENT.split(re.sub(r"\s+", " ", text)) if s.strip()]


def extract_candidates(content: str, section_id: str = "") -> list[Claim]:
    """Sentences carrying something checkable, typed. Slots are filled downstream.

    Returns CANDIDATES. Precision of this step is measured before anything gates
    (scripts/eval_claims.py) — the previous guard was tuned on 3 articles and enforced on 28.
    """
    out: list[Claim] = []
    for sent in sentences(content):
        if _CODE.search(sent):
            for m in _CODE.finditer(sent):
                out.append(Claim(type=ClaimType.CODE, sentence=sent, section_id=section_id,
                                 entity=m.group(1), proposition=sent))
        if _ATTRIB.search(sent):
            m = _ATTRIB.search(sent)
            out.append(Claim(type=ClaimType.ATTRIBUTION, sentence=sent, section_id=section_id,
                             speaker=m.group(1), proposition=sent))
        rng = _RANGE.search(sent)
        if rng:
            lo, hi = normalise_number(rng.group(1)), normalise_number(rng.group(2))
            if lo is not None and hi is not None:
                out.append(Claim(type=ClaimType.NUMBER, sentence=sent, section_id=section_id,
                                 value=(lo, hi), unit=normalise_unit(rng.group(3)),
                                 proposition=sent))
        elif _POINT.search(sent):
            m = _POINT.search(sent)
            raw = m.group(1) or m.group(2)
            v = normalise_number(raw) if raw else None
            if v is not None:
                unit = "usd" if m.group(1) else normalise_unit(m.group(3))
                out.append(Claim(type=ClaimType.NUMBER, sentence=sent, section_id=section_id,
                                 value=(v, v), unit=unit, proposition=sent))
        if _MODAL.search(sent) and not _ATTRIB.search(sent):
            out.append(Claim(type=ClaimType.MODAL, sentence=sent, section_id=section_id,
                             force=force_of(sent), proposition=sent))
    return out
