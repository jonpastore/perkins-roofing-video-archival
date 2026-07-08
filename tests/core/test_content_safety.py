"""Tests for core/content_safety.py — 100% line coverage target.

Covers:
  - denylist_hits: hits (exact, mixed-case, regex patterns), misses
  - build_judge_prompt: structural checks
  - parse_verdict: valid dict, valid JSON str, fenced JSON, invalid/empty/bad type
  - gate: denylist-fail, judge-pass, judge-fail, judge exception, no-judge clean
"""

from __future__ import annotations

import json

import pytest

from core.content_safety import (
    GateResult,
    Verdict,
    build_judge_prompt,
    denylist_hits,
    gate,
    parse_verdict,
)

# ---------------------------------------------------------------------------
# denylist_hits
# ---------------------------------------------------------------------------

class TestDenylistHits:
    def test_clean_text_returns_empty(self):
        assert denylist_hits("Our roofing team delivers top-quality work.") == []

    def test_exact_word_hit(self):
        hits = denylist_hits("where do roofers pee on the job")
        assert "pee" in hits

    def test_case_insensitive(self):
        hits = denylist_hits("That is BULLSHIT workmanship.")
        assert "bullshit" in hits

    def test_mixed_case_hit(self):
        hits = denylist_hits("What a Crap installation.")
        assert "crap" in hits

    def test_word_boundary_no_false_positive(self):
        # "class" contains "ass" but should NOT trigger the word-boundary match
        assert denylist_hits("The class of material matters.") == []

    def test_multiple_hits_deduplicated(self):
        hits = denylist_hits("pee pee pee")
        assert hits.count("pee") == 1

    def test_multiple_distinct_hits(self):
        hits = denylist_hits("pee and crap everywhere")
        assert "pee" in hits
        assert "crap" in hits

    def test_regex_pattern_shit_variant(self):
        hits = denylist_hits("that sh!t is wrong")
        assert len(hits) >= 1

    def test_regex_pattern_elongated_fuck(self):
        hits = denylist_hits("fuuuck this leak")
        assert len(hits) >= 1

    def test_piss_hit(self):
        assert "piss" in denylist_hits("he piss on the roof")

    def test_wtf_hit(self):
        assert "wtf" in denylist_hits("wtf is going on")

    def test_empty_string(self):
        assert denylist_hits("") == []

    def test_sucks_hit(self):
        assert "sucks" in denylist_hits("this contractor sucks")


# ---------------------------------------------------------------------------
# build_judge_prompt
# ---------------------------------------------------------------------------

class TestBuildJudgePrompt:
    def test_returns_string(self):
        prompt = build_judge_prompt("Great roofing work.", "article")
        assert isinstance(prompt, str)

    def test_contains_text(self):
        prompt = build_judge_prompt("Some content here.", "caption")
        assert "Some content here." in prompt

    def test_contains_kind_label(self):
        prompt = build_judge_prompt("x", "article")
        assert "blog article" in prompt

    def test_unknown_kind_uses_kind_itself(self):
        prompt = build_judge_prompt("x", "unknown_type")
        assert "unknown_type" in prompt

    def test_instructs_json_output(self):
        prompt = build_judge_prompt("x", "social")
        assert '"pass"' in prompt
        assert '"reason"' in prompt
        assert '"score"' in prompt

    def test_mentions_perkins_roofing(self):
        prompt = build_judge_prompt("x", "faq")
        assert "Perkins Roofing" in prompt

    def test_social_kind_label(self):
        assert "social media copy" in build_judge_prompt("x", "social")

    def test_avatar_script_kind_label(self):
        assert "AI avatar script" in build_judge_prompt("x", "avatar_script")

    def test_faq_kind_label(self):
        assert "FAQ answer" in build_judge_prompt("x", "faq")

    def test_caption_kind_label(self):
        assert "clip caption" in build_judge_prompt("x", "caption")

    def test_empty_kind_falls_back(self):
        # empty kind should still produce a valid prompt string
        prompt = build_judge_prompt("x", "")
        assert isinstance(prompt, str)
        assert len(prompt) > 50


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------

class TestParseVerdict:
    def test_valid_dict_pass_true(self):
        v = parse_verdict({"pass": True, "reason": "looks good", "score": 0.95})
        assert v.passed is True
        assert v.reason == "looks good"
        assert v.score == pytest.approx(0.95)

    def test_valid_dict_pass_false(self):
        v = parse_verdict({"pass": False, "reason": "crude language", "score": 0.1})
        assert v.passed is False
        assert v.score == pytest.approx(0.1)

    def test_valid_json_string(self):
        raw = json.dumps({"pass": True, "reason": "ok", "score": 0.8})
        v = parse_verdict(raw)
        assert v.passed is True
        assert v.score == pytest.approx(0.8)

    def test_fenced_json_string(self):
        raw = '```json\n{"pass": false, "reason": "bad", "score": 0.2}\n```'
        v = parse_verdict(raw)
        assert v.passed is False

    def test_empty_string_returns_fail(self):
        v = parse_verdict("")
        assert v.passed is False
        assert "FAIL" in v.reason

    def test_none_returns_fail(self):
        v = parse_verdict(None)
        assert v.passed is False

    def test_garbage_string_returns_fail(self):
        v = parse_verdict("no json here at all")
        assert v.passed is False

    def test_missing_pass_key_returns_fail(self):
        v = parse_verdict({"reason": "ok", "score": 0.9})
        assert v.passed is False

    def test_pass_not_bool_returns_fail(self):
        # pass=1 (int) is not a bool — must fail-closed
        v = parse_verdict({"pass": 1, "reason": "ok", "score": 0.9})
        assert v.passed is False

    def test_pass_string_returns_fail(self):
        v = parse_verdict({"pass": "true", "reason": "ok", "score": 0.9})
        assert v.passed is False

    def test_bad_score_type_defaults_zero(self):
        v = parse_verdict({"pass": True, "reason": "ok", "score": "not-a-number"})
        assert v.passed is True
        assert v.score == pytest.approx(0.0)

    def test_score_clamped_above_one(self):
        v = parse_verdict({"pass": True, "reason": "ok", "score": 99.0})
        assert v.score == pytest.approx(1.0)

    def test_score_clamped_below_zero(self):
        v = parse_verdict({"pass": True, "reason": "ok", "score": -5.0})
        assert v.score == pytest.approx(0.0)

    def test_missing_reason_defaults_string(self):
        v = parse_verdict({"pass": True, "score": 0.7})
        assert isinstance(v.reason, str)

    def test_wrong_type_int_returns_fail(self):
        v = parse_verdict(42)
        assert v.passed is False

    def test_list_raw_returns_fail(self):
        v = parse_verdict([{"pass": True}])
        assert v.passed is False


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

class TestGate:
    # --- Denylist fast-fail ---
    def test_denylist_fail_no_judge_called(self):
        called = []
        def judge(prompt):
            called.append(prompt)
            return {"pass": True, "reason": "ok", "score": 1.0}

        result = gate("where do roofers pee on the job", "article", judge_fn=judge)
        assert result.passed is False
        assert result.layer == "denylist"
        assert "pee" in result.reason
        assert called == []  # judge must NOT be called

    def test_denylist_fail_score_is_zero(self):
        result = gate("this is crap work", "caption")
        assert result.passed is False
        assert result.score == 0.0

    # --- Judge pass ---
    def test_judge_pass(self):
        def judge(prompt):
            return json.dumps({"pass": True, "reason": "professional", "score": 0.92})

        result = gate("Our team installs roofs professionally.", "article", judge_fn=judge)
        assert result.passed is True
        assert result.layer == "judge"
        assert result.score == pytest.approx(0.92)
        assert result.reason == "professional"

    # --- Judge fail ---
    def test_judge_fail(self):
        def judge(prompt):
            return json.dumps({"pass": False, "reason": "off-brand", "score": 0.3})

        result = gate("This content is off-brand.", "social", judge_fn=judge)
        assert result.passed is False
        assert result.layer == "judge"
        assert result.score == pytest.approx(0.3)

    # --- Judge exception → fail-closed ---
    def test_judge_exception_returns_fail(self):
        def judge(prompt):
            raise RuntimeError("network error")

        result = gate("Good roofing content.", "faq", judge_fn=judge)
        assert result.passed is False
        assert result.layer == "judge"
        assert "network error" in result.reason

    # --- No judge, denylist clean ---
    def test_no_judge_clean_fails_closed(self):
        # Denylist-clean but no judge wired → FAIL-CLOSED (cannot confirm safe without the judge).
        result = gate("Quality roofing services in Florida.", "article")
        assert result.passed is False
        assert result.layer == "clean"
        assert result.score is None

    # --- GateResult fields ---
    def test_gate_result_is_dataclass(self):
        result = gate("good content", "caption")
        assert isinstance(result, GateResult)
        assert hasattr(result, "passed")
        assert hasattr(result, "reason")
        assert hasattr(result, "layer")
        assert hasattr(result, "score")

    # --- Judge receives the prompt (integration of build_judge_prompt) ---
    def test_judge_receives_prompt_containing_text(self):
        received = []
        def judge(prompt):
            received.append(prompt)
            return json.dumps({"pass": True, "reason": "ok", "score": 1.0})

        gate("My unique roofing sentence.", "article", judge_fn=judge)
        assert len(received) == 1
        assert "My unique roofing sentence." in received[0]

    # --- Verdict dataclass ---
    def test_verdict_is_dataclass(self):
        v = parse_verdict({"pass": True, "reason": "ok", "score": 0.9})
        assert isinstance(v, Verdict)
