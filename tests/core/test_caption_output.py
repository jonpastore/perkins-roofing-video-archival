"""Behavioral validation for core.caption_output — v5 JSON contract + v3 line fallback + gating."""
import json

from core.caption_output import (
    BLOCKED,
    OK,
    REVIEW,
    gate_caption,
    gate_caption_flags,
    parse_caption_output,
)

# --- v5 JSON contract ---------------------------------------------------------------------------
_V5_OK = json.dumps({
    "prompt_version": "perkins-caption-v5.0",
    "status": "ok",
    "flags": ["NO_VOICE_SAMPLES", "NO_TECH_FACT", "ASSUMED_PLATFORM_INSTAGRAM"],
    "platform_used": "instagram",
    "hook_structure": "CONTRA",
    "tone": "CONTRARIAN",
    "caption": "You researched the car. Not the roof.\n\nBody.",
    "hashtags": ["#a", "#b", "#c", "#d", "#e"],
    "word_count": 120,
})
_V5_WITHHELD = json.dumps({
    "prompt_version": "perkins-caption-v5.0", "status": "withheld", "flags": ["MISSING_LICENSE"],
    "platform_used": "instagram", "hook_structure": None, "tone": None,
    "caption": None, "hashtags": None, "word_count": None,
})


def test_parse_v5_ok():
    p = parse_caption_output(_V5_OK)
    assert p.status == "ok" and p.prompt_version == "perkins-caption-v5.0"
    assert p.flags == ["NO_VOICE_SAMPLES", "NO_TECH_FACT", "ASSUMED_PLATFORM_INSTAGRAM"]
    assert p.caption.startswith("You researched the car.")
    assert p.hashtags == ["#a", "#b", "#c", "#d", "#e"]
    assert p.hook_structure == "CONTRA" and p.tone == "CONTRARIAN" and p.word_count == 120


def test_parse_v5_withheld_null_fields():
    p = parse_caption_output(_V5_WITHHELD)
    assert p.status == "withheld" and p.caption == "" and p.hashtags == []
    assert p.hook_structure is None and p.word_count is None


def test_parse_malformed_json_is_parse_error():
    p = parse_caption_output('{"status": "ok", "flags": [oops]}')
    assert p.status == "parse_error" and p.raw_ok is False and p.caption == ""


# --- v3 line-format fallback --------------------------------------------------------------------
def test_parse_v3_line_format_still_works():
    raw = "FLAGS: NO_TECH_FACT\nCAPTION:\nHello.\nWorld.\nHASHTAGS: #roof"
    p = parse_caption_output(raw)
    assert p.flags == ["NO_TECH_FACT"] and p.caption == "Hello.\nWorld." and p.hashtags == "#roof"
    assert p.status == "ok"


def test_parse_v3_none_and_bracketed():
    assert parse_caption_output("FLAGS: NONE\nCAPTION:\nX\nHASHTAGS: #a").flags == []
    assert parse_caption_output("flags: [NO_BRIDGE]\ncaption:\nY\nhashtags: #a").flags == ["NO_BRIDGE"]


def test_parse_empty_none_and_stray():
    for raw in ("", None, "   ", "just stray text"):
        p = parse_caption_output(raw)
        assert p.flags == [] and p.caption == "" and p.status == "ok"


# --- gating -------------------------------------------------------------------------------------
def test_gate_withheld_blocks():
    assert gate_caption_flags(["MISSING_LICENSE"], status="withheld")[0] == BLOCKED


def test_gate_parse_error_blocks():
    assert gate_caption_flags([], status="parse_error")[0] == BLOCKED


def test_gate_block_class_flags():
    assert gate_caption_flags(["SUSPECT_TRANSCRIPT"])[0] == BLOCKED
    assert gate_caption_flags(["UNUSABLE_TRANSCRIPT"])[0] == BLOCKED


def test_gate_missing_license_only_blocks_when_required():
    assert gate_caption_flags(["MISSING_LICENSE"], require_license=True)[0] == BLOCKED
    assert gate_caption_flags(["MISSING_LICENSE"], require_license=False)[0] == OK


def test_gate_review_flags():
    assert gate_caption_flags(["NO_TECH_FACT"])[0] == REVIEW
    assert gate_caption_flags(["INSURANCE_TRIM"])[0] == REVIEW


def test_gate_no_voice_samples_is_not_a_gate():
    # standing defect → OK (dashboard counter, never a gate)
    assert gate_caption_flags(["NO_VOICE_SAMPLES", "ASSUMED_PLATFORM_INSTAGRAM"]) == (OK, "")


def test_gate_clean_ok():
    assert gate_caption_flags([]) == (OK, "")


def test_gate_caption_convenience_passes_status():
    # v5 withheld JSON → BLOCKED via the convenience wrapper (reads status off the parts)
    assert gate_caption(parse_caption_output(_V5_WITHHELD))[0] == BLOCKED
    # v5 ok-with-NO_TECH_FACT → REVIEW
    assert gate_caption(parse_caption_output(_V5_OK))[0] == REVIEW
