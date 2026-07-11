"""Tests for core/tc_ai_prompts.py — pure constants + one function. TDD: written before implementation."""
from core.tc_ai_prompts import (
    ATTORNEY_DISCLAIMER,
    COVER_LETTER,
    RECOMMENDED_PROMPTS,
    get_tc_ai_prompts_block,
)


def test_get_block_returns_dict():
    result = get_tc_ai_prompts_block()
    assert isinstance(result, dict)


def test_get_block_has_cover_letter_key():
    assert "cover_letter" in get_tc_ai_prompts_block()


def test_get_block_has_attorney_disclaimer_key():
    assert "attorney_disclaimer" in get_tc_ai_prompts_block()


def test_get_block_has_recommended_prompts_key():
    assert "recommended_prompts" in get_tc_ai_prompts_block()


def test_cover_letter_contains_faq():
    assert "FAQ" in COVER_LETTER


def test_attorney_disclaimer_contains_attorney():
    assert "attorney" in ATTORNEY_DISCLAIMER.lower()


def test_recommended_prompts_is_list():
    assert isinstance(RECOMMENDED_PROMPTS, list)


def test_recommended_prompts_has_at_least_6():
    assert len(RECOMMENDED_PROMPTS) >= 6


def test_each_recommended_prompt_is_nonempty():
    for prompt in RECOMMENDED_PROMPTS:
        assert isinstance(prompt, str) and len(prompt.strip()) > 0


def test_block_cover_letter_matches_constant():
    assert get_tc_ai_prompts_block()["cover_letter"] == COVER_LETTER


def test_block_attorney_disclaimer_matches_constant():
    assert get_tc_ai_prompts_block()["attorney_disclaimer"] == ATTORNEY_DISCLAIMER


def test_block_recommended_prompts_matches_constant():
    assert get_tc_ai_prompts_block()["recommended_prompts"] == RECOMMENDED_PROMPTS
