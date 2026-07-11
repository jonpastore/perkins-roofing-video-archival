"""Tests for core/tc_summary.py — pure functions, no I/O. TDD: written before implementation."""
import json

from core.tc_summary import build_tc_summary_prompt, parse_tc_summary

TC_TEXT = (
    "Payment is due within 30 days of invoice. "
    "All work is warranted for one year from the date of completion. "
    "The homeowner must provide clear access to the property. "
    "Any changes to the scope of work must be approved in writing by both parties."
)


# ---------------------------------------------------------------------------
# build_tc_summary_prompt
# ---------------------------------------------------------------------------

def test_prompt_contains_tc_text():
    assert TC_TEXT in build_tc_summary_prompt(TC_TEXT)


def test_prompt_mentions_max_bullets():
    prompt = build_tc_summary_prompt(TC_TEXT, max_bullets=5)
    assert "5" in prompt


def test_prompt_requests_json_array():
    prompt = build_tc_summary_prompt(TC_TEXT)
    assert "JSON" in prompt or "json" in prompt
    assert "array" in prompt.lower() or "[" in prompt


def test_prompt_default_max_bullets_is_8():
    assert "8" in build_tc_summary_prompt(TC_TEXT)


def test_prompt_requires_wording_from_contract():
    prompt = build_tc_summary_prompt(TC_TEXT)
    # Must instruct model to reference real clauses / use contract wording
    assert "contract" in prompt.lower() or "clause" in prompt.lower() or "wording" in prompt.lower()


def test_max_bullets_clamped_low():
    # 0 → 1
    prompt = build_tc_summary_prompt(TC_TEXT, max_bullets=0)
    assert "1" in prompt
    assert "0" not in prompt.split("1")[0]  # the clamped value 1 appears


def test_max_bullets_clamped_high():
    # 16 → 15
    prompt = build_tc_summary_prompt(TC_TEXT, max_bullets=16)
    assert "15" in prompt


def test_max_bullets_at_boundary_1():
    prompt = build_tc_summary_prompt(TC_TEXT, max_bullets=1)
    assert "1" in prompt


def test_max_bullets_at_boundary_15():
    prompt = build_tc_summary_prompt(TC_TEXT, max_bullets=15)
    assert "15" in prompt


# ---------------------------------------------------------------------------
# parse_tc_summary
# ---------------------------------------------------------------------------

def test_parse_clean_json_array():
    raw = json.dumps(["Bullet one.", "Bullet two.", "Bullet three."])
    result = parse_tc_summary(raw)
    assert result == ["Bullet one.", "Bullet two.", "Bullet three."]


def test_parse_fenced_json():
    raw = "```json\n" + json.dumps(["Bullet one.", "Bullet two."]) + "\n```"
    result = parse_tc_summary(raw)
    assert result == ["Bullet one.", "Bullet two."]


def test_parse_numbered_list_fallback():
    raw = "1. Bullet one\n2. Bullet two\n3. Bullet three"
    result = parse_tc_summary(raw)
    assert result == ["Bullet one", "Bullet two", "Bullet three"]


def test_parse_bulleted_list_fallback_dash():
    raw = "- Bullet one\n- Bullet two"
    result = parse_tc_summary(raw)
    assert result == ["Bullet one", "Bullet two"]


def test_parse_bulleted_list_fallback_bullet_char():
    raw = "• Bullet one\n• Bullet two"
    result = parse_tc_summary(raw)
    assert result == ["Bullet one", "Bullet two"]


def test_parse_mixed_valid_invalid_json_skips_non_strings():
    raw = json.dumps(["Valid string", 42, None, "Another valid", True])
    result = parse_tc_summary(raw)
    assert result == ["Valid string", "Another valid"]


def test_parse_non_list_json_returns_empty():
    raw = json.dumps({"bullet": "Not a list"})
    result = parse_tc_summary(raw)
    assert result == []


def test_parse_empty_string_returns_empty():
    assert parse_tc_summary("") == []


def test_parse_garbage_returns_empty():
    assert parse_tc_summary("not json at all!!!") == []


def test_parse_strips_whitespace():
    raw = json.dumps(["  Bullet one  ", "  Bullet two  "])
    result = parse_tc_summary(raw)
    assert result == ["Bullet one", "Bullet two"]


def test_parse_empty_json_array_returns_empty():
    assert parse_tc_summary("[]") == []


def test_parse_non_string_items_in_json_skipped():
    raw = json.dumps([{"nested": "object"}, "Valid bullet", 123])
    result = parse_tc_summary(raw)
    assert result == ["Valid bullet"]
