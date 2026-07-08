"""Behavioral validation for core.caption_output — parse + flag-gate for social captions."""
from core.caption_output import (
    BLOCKED,
    OK,
    REVIEW,
    gate_caption_flags,
    parse_caption_output,
)

_RAW = """FLAGS: NO_TECH_FACT, MISSING_LICENSE
CAPTION:
Your roof doesn't fail all at once.
It fails at the fasteners first.
305 MIA ROOF — Miami / Broward
HASHTAGS: #southfloridaroofing #tileroof #roofrepair"""


def test_parse_full_output():
    p = parse_caption_output(_RAW)
    assert p.flags == ["NO_TECH_FACT", "MISSING_LICENSE"]
    assert p.caption.startswith("Your roof doesn't fail all at once.")
    assert "305 MIA ROOF" in p.caption
    assert p.hashtags == "#southfloridaroofing #tileroof #roofrepair"


def test_parse_none_flags():
    p = parse_caption_output("FLAGS: NONE\nCAPTION:\nClean caption.\nHASHTAGS: #roof")
    assert p.flags == []
    assert p.caption == "Clean caption."
    assert p.hashtags == "#roof"


def test_parse_bracketed_and_lowercase_flags():
    p = parse_caption_output("flags: [NO_BRIDGE]\ncaption:\nBody\nhashtags: #x")
    assert p.flags == ["NO_BRIDGE"]
    assert p.caption == "Body"


def test_parse_missing_blocks_failsafe():
    p = parse_caption_output("just some stray text")
    assert p.flags == [] and p.caption == "" and p.hashtags == ""


def test_parse_empty_and_none():
    for raw in ("", None):
        p = parse_caption_output(raw)
        assert p.flags == [] and p.caption == "" and p.hashtags == ""


def test_gate_blocks_missing_license_when_required():
    decision, reason = gate_caption_flags(["MISSING_LICENSE"], require_license=True)
    assert decision == BLOCKED and "license" in reason


def test_gate_missing_license_ignored_when_not_required():
    decision, _ = gate_caption_flags(["MISSING_LICENSE"], require_license=False)
    assert decision == OK


def test_gate_review_on_no_tech_fact():
    decision, reason = gate_caption_flags(["NO_TECH_FACT"])
    assert decision == REVIEW and "review" in reason.lower()


def test_gate_ok_when_clean():
    assert gate_caption_flags([]) == (OK, "")


def test_gate_block_takes_precedence_over_review():
    # both flags present + license required → BLOCKED wins
    decision, _ = gate_caption_flags(["NO_TECH_FACT", "MISSING_LICENSE"], require_license=True)
    assert decision == BLOCKED
