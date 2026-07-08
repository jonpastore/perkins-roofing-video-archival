"""Content safety / professionalism gate — pure logic, no I/O.

Two-layer gate:
  1. Fast denylist/regex pass — catches crude/off-brand terms immediately.
  2. LLM-judge pass (injected callable) — rubric-scores professional/on-brand/safe.

The LLM callable is dependency-injected so this module stays pure and 100% testable
without mocking network calls.

Public API
----------
denylist_hits(text)              -> list[str]
build_judge_prompt(text, kind)   -> str
parse_verdict(raw)               -> Verdict
gate(text, kind, judge_fn=None)  -> GateResult
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Denylist — crude / off-brand terms (roofing company context)
# ---------------------------------------------------------------------------

# Exact word-boundary terms (case-insensitive)
_DENY_WORDS: list[str] = [
    "pee",
    "piss",
    "pissed",
    "crap",
    "shit",
    "shitty",
    "ass",
    "asshole",
    "damn",
    "hell",
    "bastard",
    "bitch",
    "dick",
    "fuck",
    "fucking",
    "bullshit",
    "cunt",
    "wtf",
    "omg",
    "sucks",
    "crappy",
    "dumbass",
]

# Regex patterns (compiled once) that need more nuance than whole-word match
_DENY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bsh[i!1]t\b", re.IGNORECASE),        # "sh!t" / "sh1t"
    re.compile(r"\bf+u+c+k+\b", re.IGNORECASE),        # elongated forms
]

# Compile word-list into a single alternation pattern for efficiency
_WORD_DENY_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _DENY_WORDS) + r")\b",
    re.IGNORECASE,
)


def denylist_hits(text: str) -> list[str]:
    """Return all crude/off-brand terms found in *text*.

    Case-insensitive, word-boundary aware. Returns a deduplicated list of
    matched terms; order is match order in the text. Empty list = clean.

    Args:
        text: The content to check.

    Returns:
        List of matched terms (lowercased). Empty if nothing matched.
    """
    found: list[str] = []
    seen: set[str] = set()

    for m in _WORD_DENY_RE.finditer(text):
        term = m.group(0).lower()
        if term not in seen:
            found.append(term)
            seen.add(term)

    for pat in _DENY_PATTERNS:
        for m in pat.finditer(text):
            term = m.group(0).lower()
            if term not in seen:
                found.append(term)
                seen.add(term)

    return found


# ---------------------------------------------------------------------------
# LLM-judge prompt builder
# ---------------------------------------------------------------------------

_KIND_LABEL: dict[str, str] = {
    "article": "blog article",
    "faq": "FAQ answer",
    "caption": "clip caption",
    "social": "social media copy",
    "avatar_script": "AI avatar script",
}


def build_judge_prompt(text: str, kind: str) -> str:
    """Build a rubric prompt asking the LLM to judge content professionalism.

    The prompt instructs the model to return a JSON object with keys:
        pass  (bool)   — True when content is professional / on-brand / safe
        reason (str)   — Short human-readable explanation
        score  (float) — Confidence 0.0–1.0 (1.0 = fully professional)

    Args:
        text: The content artifact to evaluate.
        kind: Artifact type key — one of 'article', 'faq', 'caption',
              'social', 'avatar_script'. Unknown kinds fall back to 'content'.

    Returns:
        Prompt string ready to pass to an LLM chat call with want_json=True.
    """
    kind_label = _KIND_LABEL.get(kind, kind or "content")
    return (
        f"You are a professional-content reviewer for Perkins Roofing, a Florida residential "
        f"roofing company. Evaluate the following {kind_label} for professionalism, "
        f"on-brand tone, and safety for public publishing.\n\n"
        f"Scoring rubric:\n"
        f"  - Professional: written for a roofing business audience, no crude/vulgar language, "
        f"no slang or off-brand humour.\n"
        f"  - On-brand: relevant to roofing, home improvement, or Florida homeowner topics; "
        f"does not damage the Perkins Roofing brand.\n"
        f"  - Safe: no harmful, offensive, discriminatory, or legally risky content.\n\n"
        f"Return ONLY a JSON object — no explanation outside the JSON — with exactly these keys:\n"
        f'  {{"pass": <true|false>, "reason": "<one sentence>", "score": <0.0-1.0>}}\n\n'
        f"Set pass=true only when the content satisfies ALL three criteria above. "
        f"Score 1.0 = fully professional, 0.0 = completely unprofessional. "
        f"If uncertain, err on the side of caution (pass=false).\n\n"
        f"Content to evaluate:\n"
        f"---\n"
        f"{text}\n"
        f"---"
    )


# ---------------------------------------------------------------------------
# Verdict / GateResult dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    """Parsed result from the LLM judge."""
    passed: bool
    reason: str
    score: float


@dataclass
class GateResult:
    """Result of the full content safety gate."""
    passed: bool
    reason: str
    layer: str                    # 'denylist' | 'judge' | 'clean'
    score: Optional[float] = field(default=None)


# ---------------------------------------------------------------------------
# Verdict parser — robust, fail-closed
# ---------------------------------------------------------------------------

def parse_verdict(raw) -> Verdict:
    """Parse an LLM judge response into a Verdict. Fail-closed on any error.

    Accepts:
      - A dict (already parsed JSON)
      - A str (JSON or fenced JSON; tolerates trailing commas + control chars)

    On any parse failure or missing/bad ``pass`` key, returns a FAIL verdict
    so content is never silently published on a broken judge response.

    Args:
        raw: LLM response — dict or str.

    Returns:
        Verdict dataclass.
    """
    _FAIL = Verdict(passed=False, reason="verdict unparseable — defaulting to FAIL", score=0.0)

    if raw is None:
        return _FAIL

    # If already a dict, skip JSON parsing
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        from core.json_repair import parse_model_json  # noqa: PLC0415
        data = parse_model_json(raw)
        if not data or not isinstance(data, dict):
            return _FAIL
    else:
        return _FAIL

    # Extract 'pass' — must be a real bool (True/False); anything else → FAIL
    passed_val = data.get("pass")
    if not isinstance(passed_val, bool):
        return _FAIL

    reason = str(data.get("reason") or "no reason provided")

    try:
        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        score = 0.0

    return Verdict(passed=passed_val, reason=reason, score=score)


# ---------------------------------------------------------------------------
# Gate orchestrator — pure, fail-closed
# ---------------------------------------------------------------------------

def gate(
    text: str,
    kind: str,
    judge_fn: Optional[Callable[[str], object]] = None,
) -> GateResult:
    """Run the two-layer content safety gate.

    Layer 1 — denylist: if any crude term is found, immediately return FAIL.
               No LLM call is made (fast + no token cost).
    Layer 2 — LLM judge: if judge_fn is provided, build the rubric prompt,
               call judge_fn(prompt), parse the verdict, return the result.
    No judge  — if the denylist is clean AND no judge_fn is provided, FAIL-CLOSED
               (passed=False, layer='clean'): denylist-clean is not sufficient to
               confirm safety, so a mis-wired caller cannot silently pass. Production
               always injects the judge via adapters.safety.run_gate.

    Fail-closed: any exception from judge_fn is caught and treated as FAIL.

    Args:
        text:      Content artifact to evaluate.
        kind:      Artifact type ('article', 'faq', 'caption', 'social',
                   'avatar_script', or any freeform label).
        judge_fn:  Optional callable (prompt: str) -> raw that returns the LLM
                   response (str or dict). The LLM stays out of core — inject
                   it from the adapter layer.

    Returns:
        GateResult with passed, reason, layer, and optional score.
    """
    # --- Layer 1: denylist ---
    hits = denylist_hits(text)
    if hits:
        return GateResult(
            passed=False,
            reason=f"denylist match: {', '.join(hits)}",
            layer="denylist",
            score=0.0,
        )

    # --- Layer 2: LLM judge ---
    if judge_fn is not None:
        prompt = build_judge_prompt(text, kind)
        try:
            raw = judge_fn(prompt)
        except Exception as exc:  # noqa: BLE001
            return GateResult(
                passed=False,
                reason=f"judge call failed: {exc}",
                layer="judge",
                score=0.0,
            )
        verdict = parse_verdict(raw)
        return GateResult(
            passed=verdict.passed,
            reason=verdict.reason,
            layer="judge",
            score=verdict.score,
        )

    # --- No judge wired: FAIL-CLOSED ---
    # Denylist-clean is NOT sufficient to confirm safety — the LLM judge is the real gate.
    # A mis-wired caller that forgets to inject judge_fn must NOT silently pass unsafe content.
    # Production always injects the judge via adapters.safety.run_gate.
    return GateResult(
        passed=False,
        reason="denylist clean but no judge configured — cannot confirm safe (fail-closed)",
        layer="clean",
        score=None,
    )
