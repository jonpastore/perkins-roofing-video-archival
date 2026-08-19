"""Shorts/reels packaging gate. Length and required fields follow Aastro's unit of work.

Canonical scores stay raw (opportunity / heat / coverage). Color bands use corpus
percentiles so we never invent a 0-100 score.
"""
from __future__ import annotations

CLIP_MIN_SECS = 15
CLIP_MAX_SECS = 40
AUDIENCES = frozenset({"homeowner", "roofer"})

SCORE_HELP = {
    "opportunity": (
        "Opportunity ranks an uncovered topic using uniqueness, demand, grounding, "
        "named-entity value, and genre diversity; existing pages score zero."
    ),
    "heat": (
        "Heat measures demonstrated audience response, weighting comments more than "
        "likes and likes more than views."
    ),
    "coverage": (
        "Coverage is the share of qualified topics in this subject or genre that already "
        "have a page; high coverage means look elsewhere unless engagement supports "
        "repackaging."
    ),
}


def clip_length_secs(clip: dict) -> float:
    return float(clip.get("end") or 0) - float(clip.get("start") or 0)


def missing_package_fields(clip: dict) -> list[str]:
    missing: list[str] = []
    if not str(clip.get("town") or "").strip():
        missing.append("town")
    if not str(clip.get("problem") or "").strip():
        missing.append("problem")
    if not str(clip.get("hook") or "").strip():
        missing.append("hook")
    if str(clip.get("audience") or "").strip().lower() not in AUDIENCES:
        missing.append("audience")
    if not str(clip.get("phone_cta") or "").strip():
        missing.append("phone_cta")
    length = clip_length_secs(clip)
    if length < CLIP_MIN_SECS or length > CLIP_MAX_SECS:
        missing.append("length")
    return missing


def score_band(value: float, peers: list[float]) -> str:
    """Low / medium / high from corpus terciles. Zero is always low."""
    v = float(value or 0)
    if v <= 0:
        return "low"
    sample = [float(p) for p in peers if p is not None]
    if len(sample) < 3:
        if v >= 5:
            return "high"
        if v >= 1:
            return "medium"
        return "low"
    ordered = sorted(sample)
    p33 = ordered[(len(ordered) * 33) // 100]
    p66 = ordered[(len(ordered) * 66) // 100]
    if v <= p33:
        return "low"
    if v <= p66:
        return "medium"
    return "high"
