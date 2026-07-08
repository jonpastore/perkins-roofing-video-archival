"""Pure viral-moment selector — no I/O, no LLM calls.

Track A1: score candidate transcript segments for clip virality on a 0-99 rubric
(Hook / Flow / Value / Trend), roofing-tuned.  LLM calls are injected by callers;
this module only builds prompts, parses responses, and ranks results.
"""
from __future__ import annotations

from core.json_repair import parse_model_json

# ---------------------------------------------------------------------------
# Prompt builder (A1)
# ---------------------------------------------------------------------------

_RUBRIC = """\
Score each candidate segment on four roofing-content dimensions (0-99 total):

  Hook  (0-25): Does the opening grab a homeowner/insurer facing a Florida roof problem?
  Flow  (0-25): Is the segment self-contained — a complete thought without dangling context?
  Value (0-25): Does it deliver actionable roofing/insurance advice or a surprising fact?
  Trend (0-24): Does it touch a trending FL topic (Citizens Insurance, wind-mit, storm damage,
                HB 1611, 25-rule, HVHZ, material cost)?

Return ONLY a JSON array — one object per segment, in the same order as input:

[
  {"start": <float>, "end": <float>, "score": <int 0-99>, "reason": "<one sentence>"},
  ...
]

No markdown fences, no extra keys, no commentary outside the JSON.
"""


def build_viral_prompt(segments: list[dict]) -> str:
    """Build the LLM scoring prompt for a list of candidate segments.

    Each segment dict must carry at least ``start`` (float) and ``end`` (float),
    plus ``text`` (the transcript text for that window).  Extra keys are ignored.

    Returns a self-contained prompt string ready to pass to an LLM's ``chat()``
    with ``want_json=True``.
    """
    if not segments:
        return _RUBRIC + "\nSegments:\n[]"

    lines: list[str] = []
    for i, seg in enumerate(segments):
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or 0.0)
        text = str(seg.get("text") or "").strip()
        lines.append(f"[{i}] {start:.2f}s–{end:.2f}s: {text}")

    return _RUBRIC + "\nSegments:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parser (A1)
# ---------------------------------------------------------------------------


def parse_viral(raw: str | None) -> list[dict]:
    """Robustly parse an LLM viral-scoring response into a list of moment dicts.

    Accepts the model's raw text (may be fenced, have trailing commas, etc.).
    Each returned dict contains ``start`` (float), ``end`` (float), ``score`` (int),
    and ``reason`` (str).  Malformed or missing entries are silently dropped.
    Returns ``[]`` on any unrecoverable parse failure — never raises.
    """
    if not raw:
        return []

    parsed = parse_model_json(raw)

    # parse_model_json returns {} for non-array top-level responses — handle both
    # the list case (normal) and the dict case (model wrapped in an object).
    if isinstance(parsed, dict):
        # Try common wrapper keys: {"moments": [...], "clips": [...], "results": [...]}
        for key in ("moments", "clips", "results", "data", "segments"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            return []

    if not isinstance(parsed, list):
        return []

    moments: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start") or 0.0)
            end = float(item.get("end") or 0.0)
            score = int(item.get("score") or 0)
            reason = str(item.get("reason") or "")
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        score = max(0, min(99, score))
        moments.append({"start": start, "end": end, "score": score, "reason": reason})

    return moments


# ---------------------------------------------------------------------------
# Ranker (A1)
# ---------------------------------------------------------------------------


def rank_moments(moments: list[dict], top_n: int = 5, min_score: int = 0) -> list[dict]:
    """Filter moments below ``min_score``, then return the ``top_n`` highest-scoring ones.

    Input list is not mutated.  Returns a new list sorted by score descending.
    ``top_n`` and ``min_score`` are both inclusive bounds (``score >= min_score``).
    """
    filtered = [m for m in moments if m.get("score", 0) >= min_score]
    filtered.sort(key=lambda m: m.get("score", 0), reverse=True)
    return filtered[:max(0, top_n)]


# ---------------------------------------------------------------------------
# Orchestrator (A1)
# ---------------------------------------------------------------------------


def score_segments(
    segments: list[dict],
    score_fn: object = None,  # callable[[str], str] | None
) -> list[dict]:
    """Orchestrate prompt-build → score_fn call → parse → rank for a set of segments.

    ``score_fn`` must be an injected callable that accepts a prompt string and returns
    the raw LLM response string (e.g. ``lambda p: llm.chat(p, want_json=True)``).

    If ``score_fn`` is ``None``, returns ``[]`` (no LLM — pure/testable default).
    This function itself never calls the LLM directly; all I/O stays at the boundary.

    Returns a ranked list of moment dicts (see ``parse_viral`` + ``rank_moments``).
    """
    if score_fn is None:
        return []

    prompt = build_viral_prompt(segments)
    raw = score_fn(prompt)
    moments = parse_viral(raw)
    return rank_moments(moments)


# ---------------------------------------------------------------------------
# A4 stub (blocked on Josh's prompts)
# ---------------------------------------------------------------------------


def generate_titles(clip: dict, prompts: dict | None = None) -> list[str]:
    """Generate per-platform titles/hashtags for a clip.

    NOT IMPLEMENTED — blocked on Josh supplying explicit per-platform prompts.
    See spec §2 A4 and docs/BACKLOG.md.

    Raises:
        NotImplementedError: always; this feature is pending external input.
    """
    raise NotImplementedError("A4 blocked on Josh's prompts")
