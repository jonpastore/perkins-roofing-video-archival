"""Tests for core/tc_ai_prompts.py — pure constants + one function. TDD: written before implementation."""
from core.tc_ai_prompts import (
    ATTORNEY_DISCLAIMER,
    COVER_LETTER,
    RECOMMENDED_PROMPTS,
    build_contract_review_prompt,
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


def test_get_block_includes_contract_review_prompts():
    block = get_tc_ai_prompts_block()
    assert "contract_review_system_prompt" in block
    assert "contract_review_user_prompts" in block


def test_build_contract_review_prompt_includes_tc_and_faqs():
    result = build_contract_review_prompt(
        "Payment is due at dry-in.",
        [{"question": "When do I pay?", "answer": "At dry-in."}],
    )
    assert "Payment is due at dry-in." in result["user_prompt"]
    assert "When do I pay?" in result["user_prompt"]
    assert "not a lawyer" in result["system_prompt"].lower()


def test_each_recommended_prompt_is_nonempty():
    for prompt in RECOMMENDED_PROMPTS:
        assert isinstance(prompt, str) and len(prompt.strip()) > 0


def test_block_cover_letter_matches_constant():
    assert get_tc_ai_prompts_block()["cover_letter"] == COVER_LETTER


def test_block_attorney_disclaimer_matches_constant():
    assert get_tc_ai_prompts_block()["attorney_disclaimer"] == ATTORNEY_DISCLAIMER


def test_block_recommended_prompts_matches_constant():
    assert get_tc_ai_prompts_block()["recommended_prompts"] == RECOMMENDED_PROMPTS
