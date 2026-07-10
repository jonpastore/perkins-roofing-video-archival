"""Tests for core/contract_faq.py — pure functions, no I/O."""
import json

from core.contract_faq import (
    build_contract_faq_prompt,
    grounding_gate,
    parse_contract_faq,
)

TC_TEXT = (
    "Payment is due within 30 days of invoice. "
    "All work is warranted for one year from the date of completion. "
    "The homeowner must provide clear access to the property. "
    "Any changes to the scope of work must be approved in writing by both parties. "
    "Perkins Roofing is not responsible for pre-existing structural damage."
)


def _raw(items):
    return json.dumps(items)


def test_prompt_contains_tc_text():
    assert TC_TEXT in build_contract_faq_prompt(TC_TEXT, count=5)


def test_prompt_contains_count():
    assert "7" in build_contract_faq_prompt(TC_TEXT, count=7)


def test_prompt_requests_json():
    p = build_contract_faq_prompt(TC_TEXT)
    assert "JSON" in p or "json" in p


def test_prompt_requires_quote():
    assert "quote" in build_contract_faq_prompt(TC_TEXT).lower()


def test_prompt_default_count_is_10():
    assert "10" in build_contract_faq_prompt(TC_TEXT)


def test_prompt_grounding_instruction():
    assert "contract" in build_contract_faq_prompt(TC_TEXT).lower()


def test_prompt_json_structure_hint():
    p = build_contract_faq_prompt(TC_TEXT)
    assert '"q"' in p and '"a"' in p and '"quote"' in p


def test_parse_clean_json():
    items = [
        {"q": "When is payment due?", "a": "Within 30 days.", "quote": "Payment is due within 30 days"},
        {"q": "Is work warranted?", "a": "Yes, one year.", "quote": "warranted for one year"},
    ]
    result = parse_contract_faq(_raw(items))
    assert len(result) == 2
    assert result[0]["q"] == "When is payment due?"
    assert result[0]["quote"] == "Payment is due within 30 days"


def test_parse_key_variant_question_answer():
    items = [{"question": "How long is warranty?", "answer": "One year.", "quote": "one year"}]
    result = parse_contract_faq(_raw(items))
    assert len(result) == 1 and result[0]["q"] == "How long is warranty?"


def test_parse_drops_missing_q():
    assert parse_contract_faq(_raw([{"a": "Some answer.", "quote": "q"}])) == []


def test_parse_drops_missing_a():
    assert parse_contract_faq(_raw([{"q": "Some question?", "quote": "q"}])) == []


def test_parse_empty_string():
    assert parse_contract_faq("") == []


def test_parse_garbage_input():
    assert parse_contract_faq("not json at all!!!") == []


def test_parse_fenced_json():
    items = [{"q": "Q?", "a": "A.", "quote": "x"}]
    raw = "```json\n" + json.dumps(items) + "\n```"
    assert len(parse_contract_faq(raw)) == 1


def test_parse_strips_whitespace():
    items = [{"q": "  Question?  ", "a": "  Answer.  ", "quote": "  quote  "}]
    result = parse_contract_faq(_raw(items))
    assert result[0]["q"] == "Question?" and result[0]["a"] == "Answer." and result[0]["quote"] == "quote"


def test_parse_non_list_returns_empty():
    assert parse_contract_faq('{"q": "Q?", "a": "A."}') == []


def test_parse_mixed_valid_invalid():
    items = [
        {"q": "Valid?", "a": "Yes.", "quote": "q"},
        {"a": "No question here.", "quote": "q"},
        {"q": "Also valid?", "a": "Indeed.", "quote": "q2"},
    ]
    result = parse_contract_faq(_raw(items))
    assert len(result) == 2 and result[0]["q"] == "Valid?"


def test_parse_missing_quote_key_still_parses():
    items = [{"q": "No quote?", "a": "Still valid."}]
    result = parse_contract_faq(_raw(items))
    assert len(result) == 1 and result[0]["quote"] == ""


def test_parse_empty_list():
    assert parse_contract_faq("[]") == []


def test_grounding_keeps_verbatim_match():
    items = [{"q": "Q?", "a": "A.", "quote": "warranted for one year from the date"}]
    kept, rejected = grounding_gate(items, TC_TEXT)
    assert len(kept) == 1 and rejected == []


def test_grounding_case_insensitive():
    items = [{"q": "Q?", "a": "A.", "quote": "WARRANTED FOR ONE YEAR FROM THE DATE"}]
    kept, _ = grounding_gate(items, TC_TEXT)
    assert len(kept) == 1


def test_grounding_rejects_fabricated_quote():
    items = [{"q": "Q?", "a": "A.", "quote": "this quote was completely made up by the model"}]
    kept, rejected = grounding_gate(items, TC_TEXT)
    assert kept == [] and len(rejected) == 1


def test_grounding_rejects_missing_quote():
    items = [{"q": "Q?", "a": "A.", "quote": ""}]
    kept, rejected = grounding_gate(items, TC_TEXT)
    assert kept == [] and len(rejected) == 1


def test_grounding_rejects_none_quote():
    items = [{"q": "Q?", "a": "A.", "quote": None}]
    kept, rejected = grounding_gate(items, TC_TEXT)
    assert kept == [] and len(rejected) == 1


def test_grounding_normalizes_whitespace():
    items = [{"q": "Q?", "a": "A.", "quote": "warranted  for   one year   from the  date"}]
    kept, _ = grounding_gate(items, TC_TEXT)
    assert len(kept) == 1


def test_grounding_partitions_correctly():
    items = [
        {"q": "Real?", "a": "A.", "quote": "Payment is due within 30 days of invoice"},
        {"q": "Fake?", "a": "B.", "quote": "hallucinated content not in the contract"},
        {"q": "Also real?", "a": "C.", "quote": "All work is warranted for one year"},
    ]
    kept, rejected = grounding_gate(items, TC_TEXT)
    assert len(kept) == 2 and len(rejected) == 1 and rejected[0]["q"] == "Fake?"


def test_grounding_empty_items():
    kept, rejected = grounding_gate([], TC_TEXT)
    assert kept == [] and rejected == []


def test_grounding_empty_tc_text():
    items = [{"q": "Q?", "a": "A.", "quote": "any quote"}]
    kept, rejected = grounding_gate(items, "")
    assert kept == [] and len(rejected) == 1


class TestGroundingBypassH1:
    """H1 (R2 review): a trivial common-word 'quote' must NOT pass the gate."""

    def _items(self, quote):
        return [{"q": "Q?", "a": "Fabricated answer.", "quote": quote}]

    def test_single_word_quote_rejected(self):
        from core.contract_faq import grounding_gate
        tc = "Payment is due within 30 days of invoice. Deposits are non-refundable."
        for trivial in ("is", "due", ".", "the", "30 days"):
            kept, rejected = grounding_gate(self._items(trivial), tc)
            assert kept == [], f"trivial quote {trivial!r} passed the gate"
            assert len(rejected) == 1

    def test_real_clause_still_passes(self):
        from core.contract_faq import grounding_gate
        tc = "Payment is due within 30 days of invoice. Deposits are non-refundable."
        kept, rejected = grounding_gate(
            self._items("Payment is due within 30 days of invoice"), tc)
        assert len(kept) == 1 and rejected == []


def test_parse_skips_non_dict_items():
    from core.contract_faq import parse_contract_faq
    raw = '["just a string", {"q": "Q?", "a": "A."}]'
    items = parse_contract_faq(raw)
    assert len(items) == 1 and items[0]["q"] == "Q?"
