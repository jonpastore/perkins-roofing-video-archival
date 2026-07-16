#!/usr/bin/env python3
"""Measure the claim-grounding checker BEFORE it is allowed to gate anything.

This script is the gate on the gate. The predecessor guard was tuned until flags hit zero on
3 hand-picked articles, then enforced as a `blocker` across 28 nobody had measured; it stripped
legitimate words and made articles worse while every check reported success. The lesson is not
"tune harder", it is: **the evaluation target was wrong**. "Flags == 0" is not the goal.
Precision, recall, and harmful-edit rate are.

Three passes:

  --adversarial   (free, no LLM)  Seeded cases whose correct verdict is known. These are the
                  ones GPT-5 and Grok produced to kill the v1 design — real spans that support
                  nothing. Measures RECALL on the failure modes we know about.

  --extract       (free, no LLM)  Runs candidate extraction over all 31 real articles and
                  reports counts by type + samples. Extraction precision is the ceiling on
                  everything downstream: if this over-fires, so does every verdict.

  --verify N      (costs LLM)     Full verification of N articles against the corpus. Prints a
                  hand-labelling worksheet — precision is a human judgement, and pretending
                  otherwise is how the last one shipped.

Usage:
    .venv/bin/python scripts/eval_claims.py --adversarial
    .venv/bin/python scripts/eval_claims.py --extract
    LLM_BACKEND=vertex .venv/bin/python scripts/eval_claims.py --verify 3
"""
import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.claims import Claim, ClaimType, Verdict, compare, extract_candidates  # noqa: E402

# ── the adversarial set ──────────────────────────────────────────────────────
# Each case: (name, article_claim, what_the_span_actually_states, expected_verdict)
# Seeded tests flatter a system because they match the author's imagination of failure, so
# these are drawn from what the REVIEWERS found, not from what I expected to catch.
ADVERSARIAL = [
    ("attribution inversion",
     Claim(type=ClaimType.ATTRIBUTION, sentence="Tim recommends peel and stick.",
           speaker="Tim", proposition="recommends peel and stick underlayment"),
     Claim(type=ClaimType.ATTRIBUTION, sentence="some contractors recommend peel and stick",
           speaker="some contractors", stance="reports_others",
           proposition="recommends peel and stick underlayment"),
     Verdict.UNSUPPORTED),

    ("force reversal (lifespan vs time-to-failure)",
     Claim(type=ClaimType.NUMBER, sentence="Acrylic coating lasts 10-15 years.",
           subject="acrylic coating", measure="lifespan", value=(10, 15), unit="years"),
     Claim(type=ClaimType.NUMBER, sentence="I've seen some fail in 10 to 15 years",
           subject="acrylic coating", measure="time_to_failure", value=(10, 15), unit="years"),
     Verdict.UNSUPPORTED),

    ("hedge dropped (almost never -> never)",
     Claim(type=ClaimType.MODAL, sentence="Never use organic felt.", force="never"),
     Claim(type=ClaimType.MODAL, sentence="I'd almost never use organic felt here",
           force="sometimes"),
     Verdict.INFLATED),

    ("scope inflation (some -> all)",
     Claim(type=ClaimType.MODAL, sentence="All tile roofs need a secondary barrier.",
           force="all"),
     Claim(type=ClaimType.MODAL, sentence="some of these need a secondary barrier",
           force="some"),
     Verdict.INFLATED),

    ("code present but wrong applicability",
     Claim(type=ClaimType.CODE, sentence="ASTM D226 is required in HVHZ zones.",
           entity="ASTM D226", proposition="astm d226 is required in hvhz zones"),
     Claim(type=ClaimType.CODE, sentence="that underlayment is an ASTM D226 felt",
           entity="ASTM D226", proposition="that underlayment is an astm d226 felt"),
     Verdict.PARTIAL),

    ("number attached to the wrong subject",
     Claim(type=ClaimType.NUMBER, sentence="The underlayment lasts 10-15 years.",
           subject="underlayment", measure="lifespan", value=(10, 15), unit="years"),
     Claim(type=ClaimType.NUMBER, sentence="that roof is already 10 to 15 years old",
           subject="the existing roof", measure="age", value=(10, 15), unit="years"),
     Verdict.UNSUPPORTED),

    ("speaker rejects what the article asserts",
     Claim(type=ClaimType.ATTRIBUTION, sentence="Tim uses foam adhesive on tile.",
           speaker="Tim", proposition="uses foam adhesive on tile"),
     Claim(type=ClaimType.ATTRIBUTION, sentence="I would never use foam adhesive on tile",
           speaker="I", stance="rejects", proposition="uses foam adhesive on tile"),
     Verdict.CONTRADICTED),

    ("contradicting number",
     Claim(type=ClaimType.NUMBER, sentence="A tile roof lasts 30 years.", subject="tile roof",
           measure="lifespan", value=(30, 30), unit="years"),
     Claim(type=ClaimType.NUMBER, sentence="you get 15 to 20 out of it", subject="tile roof",
           measure="lifespan", value=(15, 20), unit="years"),
     Verdict.CONTRADICTED),

    ("unit swapped",
     Claim(type=ClaimType.NUMBER, sentence="It is 40 mils thick.", subject="membrane",
           measure="thickness", value=(40, 40), unit="mils"),
     Claim(type=ClaimType.NUMBER, sentence="forty inches across", subject="membrane",
           measure="thickness", value=(40, 40), unit="inches"),
     Verdict.UNSUPPORTED),

    ("article invents a condition the source never stated",
     Claim(type=ClaimType.NUMBER, sentence="In South Florida the coating lasts 10 years.",
           subject="coating", measure="lifespan", value=(10, 10), unit="years",
           condition="in south florida"),
     Claim(type=ClaimType.NUMBER, sentence="the coating gives you ten years",
           subject="coating", measure="lifespan", value=(10, 10), unit="years"),
     Verdict.PARTIAL),

    # CONTROLS — these must NOT be flagged. A checker that catches everything catches nothing,
    # and false accusations are what made the predecessor destructive.
    ("control: genuinely supported number",
     Claim(type=ClaimType.NUMBER, sentence="Caulk fails in 10-15 years.", subject="caulk",
           measure="time_to_failure", value=(10, 15), unit="years"),
     Claim(type=ClaimType.NUMBER, sentence="it fails 10 15 years down the road",
           subject="caulk", measure="time_to_failure", value=(10, 15), unit="yrs"),
     Verdict.SUPPORTED),

    ("control: genuinely supported attribution",
     Claim(type=ClaimType.ATTRIBUTION, sentence="Tim cuts the stucco back.", speaker="Tim",
           proposition="cut the stucco back into the block"),
     Claim(type=ClaimType.ATTRIBUTION, sentence="you cut the stucco and put it into the block",
           speaker="I", stance="asserts", proposition="cut the stucco back into the block"),
     Verdict.SUPPORTED),

    ("control: matching code and assertion",
     Claim(type=ClaimType.CODE, sentence="Polyflash 1C comes from Polyblast.",
           entity="Polyblast", proposition="polyflash 1c comes from polyblast"),
     Claim(type=ClaimType.CODE, sentence="recourse polyflash 1C from Polyblast",
           entity="Polyblast", proposition="polyflash 1c from polyblast"),
     Verdict.SUPPORTED),
]


def run_adversarial() -> int:
    print("=" * 78)
    print("ADVERSARIAL SET — recall on known failure modes (no LLM, deterministic)")
    print("=" * 78)
    bad = 0
    for name, claim, span, expected in ADVERSARIAL:
        got = compare(claim, span)
        ok = got is expected
        bad += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<48} expected={expected.value:<14} got={got.value}")
    print(f"\n  {len(ADVERSARIAL) - bad}/{len(ADVERSARIAL)} correct")
    if bad:
        print("  !! a failure here means the checker would ship a hallucination it was built to catch")
    return bad


def run_extract() -> None:
    """Extraction precision is the ceiling on every verdict downstream. Measure it on real
    articles, not on the three you tuned against."""
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    from app.models import Article, SessionLocal

    print("=" * 78)
    print("EXTRACTION — candidates per article, over ALL articles (no LLM)")
    print("=" * 78)
    totals: Counter = Counter()
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        rows = db.query(Article).order_by(Article.slug).all()
        for a in rows:
            cands = extract_candidates(a.content_md or "", section_id=a.slug)
            per = Counter(c.type.value for c in cands)
            totals.update(per)
            print(f"  {a.slug[:44]:<45} {len(cands):>3}  {dict(per)}")
    print(f"\n  articles: {len(rows)}   candidates: {sum(totals.values())}   by type: {dict(totals)}")
    print(f"  mean per article: {sum(totals.values()) / max(1, len(rows)):.1f}")
    print("\n  NOTE: these are CANDIDATES, not findings. Precision is judged after verification,")
    print("  by a human reading the worksheet from --verify. Do not read a count as a problem.")


class _SpanReadFailures(logging.Handler):
    """Count swallowed span-read failures.

    A malformed response_schema once made every span read raise inside the SDK; read_span's
    broad `except Exception` turned that into 80 unreadable spans, and this harness printed a
    worksheet and exited 0. Verdicts computed against zero evidence are not data — they are the
    predecessor's bug wearing the evaluator's clothes. Count them, and refuse to report.
    """

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "span read failed" in record.getMessage():
            self.count += 1


def run_verify(n: int) -> int:
    """Full verification. Prints a hand-labelling worksheet — precision is a human call."""
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    from adapters.llm import get_default
    from app.models import Article, SessionLocal
    from core.claim_verify import verify_claim
    from jobs.article_job import _corpus_vocabulary

    failures = _SpanReadFailures()
    logging.getLogger("core.claim_verify").addHandler(failures)
    llm = get_default()
    print("=" * 78)
    print(f"VERIFY — {n} article(s), full pipeline (COSTS LLM CALLS)")
    print("=" * 78)
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        vocab = _corpus_vocabulary()
        print(f"  corpus vocabulary: {len(vocab)} tokens\n")
        # _corpus_vocabulary swallows DB errors and returns empty. An empty vocabulary makes
        # _in_corpus() answer True for everything ("never accuse on missing evidence"), which
        # silently disables OUT_OF_CORPUS — the verdict that catches the Solar Reflectance Index
        # case this whole checker exists for. Observed for real: a dead cloud-sql-proxy printed
        # "0 tokens" and the run carried on emitting confident-looking verdicts.
        if not vocab:
            print("  !! corpus vocabulary is EMPTY — OUT_OF_CORPUS cannot fire, so every")
            print("     'in Tim's words' judgement below is vacuous. Fix the DB, re-run.")
            return 1
        rows = db.query(Article).order_by(Article.slug).limit(n).all()
        tally: Counter = Counter()
        for a in rows:
            cands = extract_candidates(a.content_md or "", section_id=a.slug)
            print(f"\n--- {a.slug}  ({len(cands)} candidates)")
            for c in cands:
                r = verify_claim(c, db, llm=llm, vocab=vocab)
                tally[r.verdict.value] += 1
                flag = "" if r.verdict is Verdict.SUPPORTED else "   <-- REVIEW"
                print(f"  [{r.verdict.value:<14}] {c.type.value:<12}{flag}")
                # A verdict is not labellable without BOTH sides of the comparison. Printing the
                # claim truncated to 64 chars and a YouTube link means the labeller has to open
                # 20+ tabs to judge one article — so nobody labels, and the number never exists.
                # Print what was compared, in full, next to each other.
                print(f"       claim: {c.sentence.strip()[:300]}")
                if r.span_text:
                    print(f"       span : {' '.join(r.span_text.split())[:300]}")
                if r.url:
                    print(f"       source: {r.url}")
                if r.note:
                    print(f"       note: {r.note}")
        print(f"\n  verdicts: {dict(tally)}")
        if failures.count:
            print(f"\n  !! {failures.count} span read(s) FAILED — the model was never asked, or")
            print("     never answered. Every verdict above that rests on a failed read is an")
            print("     artefact of the failure, not a measurement of the article.")
            print("     DO NOT hand-label this run. Fix the reads, re-run.")
            return 1
        print("\n  HAND-LABEL each non-SUPPORTED line: is it a REAL problem or a false alarm?")
        print("  precision = real / (real + false). Nothing gates until that number is known.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--adversarial", action="store_true")
    p.add_argument("--extract", action="store_true")
    p.add_argument("--verify", type=int, default=0, metavar="N")
    args = p.parse_args()
    if not (args.adversarial or args.extract or args.verify):
        p.error("pick at least one of --adversarial / --extract / --verify N")
    rc = 0
    if args.adversarial:
        rc = run_adversarial()
    if args.extract:
        run_extract()
    if args.verify:
        rc += run_verify(args.verify)
    sys.exit(1 if rc else 0)
