"""100% coverage tests for core/ask_cache.py.

All functions are pure (no I/O) — no mocks needed.
"""
from datetime import datetime, timedelta, timezone

import pytest

from core.ask_cache import (
    build_cache_entry,
    is_stale,
    normalize_question,
    should_serve,
    should_suggest,
)


# ---------------------------------------------------------------------------
# normalize_question
# ---------------------------------------------------------------------------

class TestNormalizeQuestion:
    def test_lowercases(self):
        assert normalize_question("How MUCH Does It Cost?") == "how much does it cost"

    def test_strips_punctuation(self):
        assert normalize_question("What's the best roof?") == "what s the best roof"

    def test_collapses_whitespace(self):
        assert normalize_question("  too   many   spaces  ") == "too many spaces"

    def test_strips_accents(self):
        # é -> e after NFD decomposition
        result = normalize_question("résumé")
        assert result == "resume"

    def test_empty_string(self):
        assert normalize_question("") == ""

    def test_only_punctuation(self):
        assert normalize_question("!!! ???") == ""

    def test_mixed_case_and_punctuation(self):
        result = normalize_question("Do I need TWO layers? (Yes!)")
        assert result == "do i need two layers yes"

    def test_already_normalized(self):
        q = "how long does a roof last"
        assert normalize_question(q) == q

    def test_numbers_preserved(self):
        result = normalize_question("3-tab shingles cost $500")
        assert "3" in result
        assert "500" in result

    def test_unicode_dash(self):
        result = normalize_question("GAF—Timberline")
        assert result == "gaf timberline"


# ---------------------------------------------------------------------------
# should_serve
# ---------------------------------------------------------------------------

class TestShouldServe:
    def test_at_threshold_returns_true(self):
        assert should_serve(0.95) is True

    def test_above_threshold_returns_true(self):
        assert should_serve(0.99) is True
        assert should_serve(1.0) is True

    def test_below_threshold_returns_false(self):
        assert should_serve(0.94) is False
        assert should_serve(0.0) is False

    def test_custom_threshold(self):
        assert should_serve(0.80, threshold=0.80) is True
        assert should_serve(0.79, threshold=0.80) is False

    def test_exact_one(self):
        assert should_serve(1.0, threshold=0.95) is True


# ---------------------------------------------------------------------------
# should_suggest
# ---------------------------------------------------------------------------

class TestShouldSuggest:
    def test_in_band_returns_true(self):
        assert should_suggest(0.85) is True
        assert should_suggest(0.90) is True
        assert should_suggest(0.9499) is True

    def test_at_low_boundary(self):
        assert should_suggest(0.85) is True

    def test_below_low_boundary(self):
        assert should_suggest(0.84) is False
        assert should_suggest(0.0) is False

    def test_at_high_boundary_excluded(self):
        # high=0.95 is exclusive (< not <=)
        assert should_suggest(0.95) is False

    def test_above_high_boundary(self):
        assert should_suggest(0.99) is False

    def test_custom_thresholds(self):
        assert should_suggest(0.70, low=0.70, high=0.80) is True
        assert should_suggest(0.80, low=0.70, high=0.80) is False
        assert should_suggest(0.69, low=0.70, high=0.80) is False


# ---------------------------------------------------------------------------
# build_cache_entry
# ---------------------------------------------------------------------------

class TestBuildCacheEntry:
    def test_basic_shape(self):
        entry = build_cache_entry("How long does a roof last?", {"answer": "20 years"}, "v1")
        assert entry["question"] == "How long does a roof last?"
        assert entry["question_norm"] == "how long does a roof last"
        assert entry["answer_json"] == {"answer": "20 years"}
        assert entry["pipeline_version"] == "v1"
        assert entry["hit_count"] == 0
        assert entry["embedding"] is None

    def test_embedding_placeholder(self):
        entry = build_cache_entry("q", {}, "v2")
        assert entry["embedding"] is None

    def test_normalisation_matches_standalone(self):
        q = "What's the BEST metal roof?!"
        entry = build_cache_entry(q, {}, "v1")
        assert entry["question_norm"] == normalize_question(q)

    def test_empty_answer_dict(self):
        entry = build_cache_entry("q?", {}, "v1")
        assert entry["answer_json"] == {}

    def test_complex_answer_dict_preserved(self):
        ans = {"answer": "text", "abstained": False, "confidence": 0.9,
               "citations": ["https://youtu.be/abc?t=10"], "sources": []}
        entry = build_cache_entry("q", ans, "v1")
        assert entry["answer_json"] == ans


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------

class TestIsStale:
    _NOW = datetime(2026, 7, 10, 12, 0, 0)  # tz-naive UTC

    def test_same_version_within_ttl_not_stale(self):
        created = self._NOW - timedelta(days=5)
        assert is_stale(created, "v1", "v1", now=self._NOW) is False

    def test_version_mismatch_is_stale(self):
        created = self._NOW - timedelta(days=1)
        assert is_stale(created, "v1", "v2", now=self._NOW) is True

    def test_expired_ttl_is_stale(self):
        created = self._NOW - timedelta(days=31)
        assert is_stale(created, "v1", "v1", now=self._NOW) is True

    def test_exactly_at_ttl_boundary_is_stale(self):
        # age_days == ttl_days: > is False, so NOT stale
        created = self._NOW - timedelta(days=30)
        assert is_stale(created, "v1", "v1", now=self._NOW) is False

    def test_one_second_past_ttl_is_stale(self):
        created = self._NOW - timedelta(days=30, seconds=1)
        assert is_stale(created, "v1", "v1", now=self._NOW) is True

    def test_custom_ttl(self):
        created = self._NOW - timedelta(days=8)
        assert is_stale(created, "v1", "v1", now=self._NOW, ttl_days=7) is True
        assert is_stale(created, "v1", "v1", now=self._NOW, ttl_days=9) is False

    def test_now_defaults_to_utcnow(self):
        created = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        assert is_stale(created, "v1", "v1") is False

    def test_tz_aware_created_at_handled(self):
        created_tz = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
        assert is_stale(created_tz, "v1", "v1", now=self._NOW) is False

    def test_both_conditions_trigger_stale(self):
        created = self._NOW - timedelta(days=40)
        assert is_stale(created, "v1", "v2", now=self._NOW) is True

    def test_version_empty_string_mismatch(self):
        created = self._NOW - timedelta(days=1)
        assert is_stale(created, "", "v1", now=self._NOW) is True

    def test_version_same_empty_string(self):
        created = self._NOW - timedelta(days=1)
        assert is_stale(created, "", "", now=self._NOW) is False
