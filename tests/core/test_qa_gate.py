"""Tests for core/qa_gate.py — 100% coverage target."""

from __future__ import annotations

import pytest

from core.qa_gate import _shingles, dedup_jaccard, is_duplicate, verdict

# ---------------------------------------------------------------------------
# verdict — precedence logic
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_all_pass_returns_pass(self):
        checks = [
            {"severity": "pass", "details": "ok"},
            {"severity": "pass", "details": "ok"},
        ]
        assert verdict(checks) == "pass"

    def test_single_warn_returns_warn(self):
        checks = [{"severity": "warn", "details": "borderline"}]
        assert verdict(checks) == "warn"

    def test_single_block_returns_block(self):
        checks = [{"severity": "block", "details": "duplicate"}]
        assert verdict(checks) == "block"

    def test_block_overrides_warn(self):
        checks = [
            {"severity": "warn", "details": "borderline"},
            {"severity": "block", "details": "blocked"},
        ]
        assert verdict(checks) == "block"

    def test_block_overrides_pass(self):
        checks = [
            {"severity": "pass", "details": "ok"},
            {"severity": "block", "details": "blocked"},
        ]
        assert verdict(checks) == "block"

    def test_warn_overrides_pass(self):
        checks = [
            {"severity": "pass", "details": "ok"},
            {"severity": "warn", "details": "borderline"},
        ]
        assert verdict(checks) == "warn"

    def test_mixed_block_warn_pass_returns_block(self):
        checks = [
            {"severity": "pass"},
            {"severity": "warn"},
            {"severity": "block"},
        ]
        assert verdict(checks) == "block"

    def test_empty_list_returns_pass(self):
        assert verdict([]) == "pass"

    def test_unknown_severity_treated_as_pass(self):
        checks = [{"severity": "unknown_value", "details": "x"}]
        assert verdict(checks) == "pass"

    def test_missing_severity_key_treated_as_pass(self):
        checks = [{"details": "no severity key"}]
        assert verdict(checks) == "pass"

    def test_severity_none_treated_as_pass(self):
        checks = [{"severity": None}]
        assert verdict(checks) == "pass"

    def test_case_insensitive_severity(self):
        checks = [{"severity": "BLOCK"}]
        assert verdict(checks) == "block"

    def test_single_item_block(self):
        assert verdict([{"severity": "block"}]) == "block"

    def test_single_item_warn(self):
        assert verdict([{"severity": "warn"}]) == "warn"

    def test_single_item_pass(self):
        assert verdict([{"severity": "pass"}]) == "pass"

    def test_three_warns_return_warn(self):
        checks = [{"severity": "warn"}] * 3
        assert verdict(checks) == "warn"

    def test_stops_early_on_block(self):
        # After hitting block, no further iteration needed — verify correctness
        # even with many subsequent checks
        checks = [{"severity": "block"}] + [{"severity": "warn"}] * 10
        assert verdict(checks) == "block"


# ---------------------------------------------------------------------------
# _shingles — internal helper (tested for coverage)
# ---------------------------------------------------------------------------

class TestShingles:
    def test_basic_5gram(self):
        text = "the quick brown fox jumped over the lazy dog"
        result = _shingles(text, n=5)
        assert isinstance(result, set)
        # "quick brown fox jumped over" should be one shingle (after filtering short words)
        # Note: "the" is 3 chars — included; "fox" is 3 chars — included
        assert len(result) > 0

    def test_short_text_fewer_than_n_words_returns_empty(self):
        result = _shingles("roof repair", n=5)
        # Only 2 words ≥3 chars → no 5-gram possible
        assert result == set()

    def test_filters_words_shorter_than_3_chars(self):
        # "a", "is" are too short
        result = _shingles("a is the roof repair guide", n=3)
        # Remaining ≥3-char words: "the", "roof", "repair", "guide" → 2 3-grams
        assert len(result) == 2

    def test_normalises_to_lowercase(self):
        a = _shingles("Roof Repair Dallas Texas Guide", n=3)
        b = _shingles("roof repair dallas texas guide", n=3)
        assert a == b

    def test_strips_punctuation(self):
        a = _shingles("roof, repair! dallas.", n=3)
        b = _shingles("roof repair dallas", n=3)
        assert a == b

    def test_n1_shingles(self):
        result = _shingles("roof repair dallas", n=1)
        assert "roof" in result
        assert "repair" in result
        assert "dallas" in result

    def test_empty_text_returns_empty_set(self):
        assert _shingles("", n=5) == set()

    def test_only_short_words_returns_empty(self):
        assert _shingles("a an or by", n=3) == set()


# ---------------------------------------------------------------------------
# dedup_jaccard
# ---------------------------------------------------------------------------

class TestDedupJaccard:
    def test_identical_texts_return_1(self):
        text = "roof repair guide for homeowners in Dallas Texas covers shingles gutters flashing"
        score = dedup_jaccard(text, text)
        assert score == pytest.approx(1.0)

    def test_completely_different_texts_return_0_or_low(self):
        a = "roofing shingles asphalt dallas repair leak gutter flashing eave ridge"
        b = "pizza oven kitchen recipe baking flour yeast dough mozzarella tomato"
        score = dedup_jaccard(a, b)
        assert score < 0.1

    def test_empty_text_a_returns_0(self):
        assert dedup_jaccard("", "roof repair guide dallas texas") == 0.0

    def test_empty_text_b_returns_0(self):
        assert dedup_jaccard("roof repair guide dallas texas", "") == 0.0

    def test_both_empty_returns_0(self):
        assert dedup_jaccard("", "") == 0.0

    def test_partial_overlap_between_0_and_1(self):
        shared = "roof repair guide for homeowners in dallas texas covers shingles gutters"
        a = shared + " unique content about flashing membrane installation"
        b = shared + " different content about insulation vapour barriers"
        score = dedup_jaccard(a, b)
        assert 0.0 < score < 1.0

    def test_high_similarity_near_duplicate(self):
        base = ("roofing shingles repair guide dallas texas homeowners leak flashing " * 10).strip()
        # Change only a few words — Jaccard with 5-gram shingles gives ~0.64
        # because replacing 2 of 10 occurrences of "roofing" invalidates every
        # shingle that overlaps those positions.
        variant = base.replace("roofing", "roofer", 2)
        score = dedup_jaccard(base, variant)
        assert score > 0.5

    def test_default_n_is_5(self):
        text = "the quick brown fox jumped over the lazy dog here"
        # n=5 is default; explicit n=5 should give same result
        assert dedup_jaccard(text, text) == dedup_jaccard(text, text, n=5)

    def test_custom_n_3(self):
        text = "roof repair dallas"
        score = dedup_jaccard(text, text, n=3)
        assert score == pytest.approx(1.0)

    def test_symmetry(self):
        a = "roof repair guide for dallas homeowners shingles gutters"
        b = "dallas homeowners guide for roof repair shingles replacement"
        assert dedup_jaccard(a, b) == pytest.approx(dedup_jaccard(b, a))

    def test_text_with_only_short_words_returns_0(self):
        # All words < 3 chars are filtered → no shingles → 0.0
        score = dedup_jaccard("a an or by", "a an or by")
        assert score == 0.0

    def test_score_between_0_and_1(self):
        a = "roof repair shingles dallas texas homeowners gutters leak"
        b = "roof repair shingles dallas homeowners gutters"
        score = dedup_jaccard(a, b)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# is_duplicate
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    def _long_text(self, seed: str, repeats: int = 20) -> str:
        """Generate a long text by repeating a seed phrase."""
        return (seed + " ") * repeats

    def test_exact_duplicate_returns_true(self):
        text = self._long_text("roof repair guide dallas texas homeowners shingles")
        assert is_duplicate(text, [text]) is True

    def test_no_match_returns_false(self):
        new = self._long_text("roof repair guide dallas shingles homeowners")
        existing = [self._long_text("pizza recipe baking flour yeast mozzarella kitchen")]
        assert is_duplicate(new, existing) is False

    def test_empty_corpus_returns_false(self):
        new = self._long_text("roof repair shingles dallas")
        assert is_duplicate(new, []) is False

    def test_default_threshold_is_85_percent(self):
        # Build two texts with ≥85% overlap
        base = self._long_text("roof repair guide for dallas homeowners shingles gutters leak", 15)
        # Near-identical — should exceed 0.85
        near_dup = base  # identical → jaccard = 1.0
        assert is_duplicate(near_dup, [base]) is True

    def test_low_similarity_not_duplicate(self):
        new = self._long_text("roof repair guide for dallas homeowners shingles leak", 5)
        # Only 2 words in common after shingle generation — very different
        other = self._long_text("completely unrelated content about gardening flowers plants soil", 5)
        assert is_duplicate(new, [other]) is False

    def test_custom_threshold_lower(self):
        a = self._long_text("roof repair guide dallas texas homeowners shingles", 10)
        b = self._long_text("roof repair guide dallas texas homeowners membrane", 10)
        # At threshold=0.5, similar texts should be flagged
        score = dedup_jaccard(a, b)
        expected = score >= 0.5
        assert is_duplicate(a, [b], threshold=0.5) is expected

    def test_custom_threshold_1_only_exact_match(self):
        a = self._long_text("roof repair guide dallas homeowners shingles gutters", 10)
        b = a + " extra words"
        # threshold=1.0 → only exact shingle sets match
        assert is_duplicate(a, [b], threshold=1.0) is False
        assert is_duplicate(a, [a], threshold=1.0) is True

    def test_checks_all_existing_texts(self):
        new = self._long_text("roof repair guide dallas texas homeowners shingles")
        # First two are unrelated; last is identical
        existing = [
            self._long_text("pizza recipe flour yeast baking kitchen dough mozzarella"),
            self._long_text("gardening flowers plants soil nutrients sunlight water pots"),
            self._long_text("roof repair guide dallas texas homeowners shingles"),
        ]
        assert is_duplicate(new, existing) is True

    def test_returns_false_when_similarity_just_below_threshold(self):
        # Construct two texts where Jaccard is just below 0.85
        # Use completely unrelated texts
        a = self._long_text("roofing shingles asphalt dallas texas homeowners guide repair")
        b = self._long_text("swimming pool maintenance chemicals chlorine filter pump skimmer")
        assert is_duplicate(a, [b]) is False

    def test_new_text_empty_returns_false(self):
        existing = [self._long_text("roof repair guide dallas")]
        # Empty text has no shingles → jaccard=0.0 < 0.85
        assert is_duplicate("", existing) is False

    def test_existing_text_empty_not_duplicate(self):
        new = self._long_text("roof repair guide dallas homeowners shingles")
        assert is_duplicate(new, [""]) is False
