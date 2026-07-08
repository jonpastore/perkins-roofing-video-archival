"""Tests for core/avatar_script.py — 100% line coverage target.

Covers:
  - build_script_prompt: structure, topic injection, snippet formatting, empty snippets
  - parse_script: valid JSON str, valid dict, fenced JSON, empty/garbage/None input,
                  est_seconds from LLM vs computed, short-text parse_ok=False
  - script_gate_input: full dict, title-only, body-only, empty dict
  - avatar_job (light mocked-job test): gate BLOCKS an unprofessional script
"""

from __future__ import annotations

import json

import pytest

from core.avatar_script import (
    _WPM,
    build_script_prompt,
    parse_script,
    script_gate_input,
)


# ---------------------------------------------------------------------------
# build_script_prompt
# ---------------------------------------------------------------------------

class TestBuildScriptPrompt:
    def test_topic_in_prompt(self):
        prompt = build_script_prompt("roof-age insurance", [])
        assert "roof-age insurance" in prompt

    def test_json_instruction_present(self):
        prompt = build_script_prompt("any topic", [])
        assert "script_text" in prompt
        assert "est_seconds" in prompt
        assert "title" in prompt

    def test_no_snippets_omits_source_block(self):
        prompt = build_script_prompt("topic", [])
        assert "SOURCE CLIPS" not in prompt

    def test_snippets_included(self):
        snippets = [
            {"text": "Tim explains shingles last 25 years", "link": "https://youtu.be/abc?t=10"},
            {"text": "Wind mitigation discounts up to 40%"},
        ]
        prompt = build_script_prompt("wind mitigation", snippets)
        assert "SOURCE CLIPS" in prompt
        assert "Tim explains shingles last 25 years" in prompt
        assert "https://youtu.be/abc?t=10" in prompt
        assert "Wind mitigation discounts up to 40%" in prompt

    def test_snippet_without_link_no_empty_parens(self):
        snippets = [{"text": "Some fact about roofing."}]
        prompt = build_script_prompt("topic", snippets)
        # Should not contain empty parentheses "()" for the missing link
        assert "()" not in prompt

    def test_snippet_numbering(self):
        snippets = [{"text": "First fact"}, {"text": "Second fact"}]
        prompt = build_script_prompt("topic", snippets)
        assert "1. First fact" in prompt
        assert "2. Second fact" in prompt

    def test_returns_string(self):
        assert isinstance(build_script_prompt("topic", []), str)

    def test_professional_tone_instructions_present(self):
        prompt = build_script_prompt("topic", [])
        assert "Perkins Roofing" in prompt
        assert "call-to-action" in prompt


# ---------------------------------------------------------------------------
# parse_script
# ---------------------------------------------------------------------------

class TestParseScript:
    def _valid_payload(self, title="How to Survive a Roof Inspection",
                       script_text=None, est_seconds=75):
        if script_text is None:
            # 30-word script so parse_ok is True
            script_text = (
                "If your insurer is threatening nonrenewal because of your roof age, "
                "here is what you need to know right now as a South Florida homeowner."
            )
        return {"title": title, "script_text": script_text, "est_seconds": est_seconds}

    # --- valid JSON string ---

    def test_valid_json_string(self):
        payload = self._valid_payload()
        raw = json.dumps(payload)
        result = parse_script(raw)
        assert result["title"] == payload["title"]
        assert result["script_text"] == payload["script_text"]
        assert result["est_seconds"] == 75
        assert result["parse_ok"] is True

    def test_fenced_json_string(self):
        payload = self._valid_payload()
        raw = f"```json\n{json.dumps(payload)}\n```"
        result = parse_script(raw)
        assert result["title"] == payload["title"]
        assert result["parse_ok"] is True

    # --- valid dict ---

    def test_valid_dict_input(self):
        payload = self._valid_payload()
        result = parse_script(payload)
        assert result["title"] == payload["title"]
        assert result["parse_ok"] is True

    # --- est_seconds computation ---

    def test_est_seconds_from_llm_when_positive(self):
        payload = self._valid_payload(est_seconds=90)
        result = parse_script(payload)
        assert result["est_seconds"] == 90

    def test_est_seconds_computed_when_zero(self):
        payload = self._valid_payload(est_seconds=0)
        # 30-word script at _WPM wpm
        result = parse_script(payload)
        word_count = len(payload["script_text"].split())
        expected = max(1, round(word_count / _WPM * 60))
        assert result["est_seconds"] == expected

    def test_est_seconds_computed_when_negative(self):
        payload = self._valid_payload(est_seconds=-5)
        result = parse_script(payload)
        assert result["est_seconds"] > 0

    def test_est_seconds_computed_when_missing(self):
        payload = self._valid_payload()
        del payload["est_seconds"]
        result = parse_script(payload)
        assert result["est_seconds"] > 0

    def test_est_seconds_computed_when_non_numeric(self):
        payload = self._valid_payload()
        payload["est_seconds"] = "not-a-number"
        result = parse_script(payload)
        assert result["est_seconds"] > 0

    # --- parse_ok flag ---

    def test_parse_ok_false_for_short_script(self):
        payload = self._valid_payload(script_text="Too short.")
        result = parse_script(payload)
        assert result["parse_ok"] is False

    def test_parse_ok_true_for_sufficient_words(self):
        long_text = "word " * 25  # 25 words — above _MIN_WORDS (20)
        payload = self._valid_payload(script_text=long_text.strip())
        result = parse_script(payload)
        assert result["parse_ok"] is True

    # --- failure / garbage input ---

    def test_none_returns_fallback(self):
        result = parse_script(None)
        assert result["parse_ok"] is False
        assert result["script_text"] == ""
        assert result["title"] == ""
        assert result["est_seconds"] == 0

    def test_empty_string_returns_fallback(self):
        result = parse_script("")
        assert result["parse_ok"] is False

    def test_garbage_string_returns_fallback(self):
        result = parse_script("this is not json at all !!")
        assert result["parse_ok"] is False

    def test_wrong_type_returns_fallback(self):
        result = parse_script(42)
        assert result["parse_ok"] is False

    def test_empty_dict_returns_parse_ok_false(self):
        result = parse_script({})
        assert result["parse_ok"] is False
        assert result["title"] == ""
        assert result["script_text"] == ""

    def test_missing_title_key_uses_empty_string(self):
        payload = self._valid_payload()
        del payload["title"]
        result = parse_script(payload)
        assert result["title"] == ""
        assert result["parse_ok"] is True

    def test_strips_whitespace_from_fields(self):
        payload = self._valid_payload(title="  My Title  ",
                                      script_text="  " + "word " * 25)
        result = parse_script(payload)
        assert result["title"] == "My Title"
        assert not result["script_text"].startswith(" ")

    def test_est_seconds_at_least_one_for_non_empty_script(self):
        # Single word — still at least 1 second (but parse_ok=False)
        payload = {"title": "T", "script_text": "Hello", "est_seconds": 0}
        result = parse_script(payload)
        assert result["est_seconds"] >= 1


# ---------------------------------------------------------------------------
# script_gate_input
# ---------------------------------------------------------------------------

class TestScriptGateInput:
    def test_full_dict_combines_title_and_body(self):
        script = {"title": "Roof Age and Insurance", "script_text": "Here is what you need to know."}
        out = script_gate_input(script)
        assert "Roof Age and Insurance" in out
        assert "Here is what you need to know." in out
        # Title comes before body
        assert out.index("Roof Age and Insurance") < out.index("Here is what you need to know.")

    def test_title_only(self):
        out = script_gate_input({"title": "My Title", "script_text": ""})
        assert out == "My Title"

    def test_body_only(self):
        out = script_gate_input({"title": "", "script_text": "Body text here."})
        assert out == "Body text here."

    def test_empty_dict_returns_empty_string(self):
        assert script_gate_input({}) == ""

    def test_returns_string(self):
        assert isinstance(script_gate_input({"title": "T", "script_text": "B"}), str)

    def test_separator_is_double_newline(self):
        out = script_gate_input({"title": "T", "script_text": "B"})
        assert "\n\n" in out

    def test_none_values_treated_as_empty(self):
        out = script_gate_input({"title": None, "script_text": None})
        assert out == ""


# ---------------------------------------------------------------------------
# avatar_job — mocked integration: gate BLOCKS unprofessional script
# ---------------------------------------------------------------------------

class TestAvatarJobGateBlocks:
    """Verify that the orchestrator raises when the safety gate fails.

    We mock every I/O boundary (retrieval, LLM, ElevenLabs, HeyGen) and feed
    a script that trips the denylist — the job must raise RuntimeError before
    reaching render.
    """

    def _run_job_with_script(self, script_dict, monkeypatch):
        """Helper: patch all I/O and run avatar_job.run with a fixed LLM response."""
        import jobs.avatar_job as avatar_job  # noqa: PLC0415

        # Stub retrieval
        monkeypatch.setattr(
            "app.retrieval.search",
            lambda topic, k=8: [],
            raising=False,
        )

        # Stub LLM: returns the script dict as JSON
        class FakeLLM:
            def chat(self, prompt, want_json=False, **kw):
                return json.dumps(script_dict)

        # Run — capture any RuntimeError
        return avatar_job.run("test topic", llm=FakeLLM())

    def test_gate_blocks_crude_script(self, monkeypatch):
        """A script containing a denylist word must be blocked before render."""
        import jobs.avatar_job as avatar_job  # noqa: PLC0415

        crude_script = {
            "title": "Roof Repair",
            "script_text": (
                "This crap roof is falling apart. "
                + "word " * 30  # enough words to pass parse_ok
            ),
            "est_seconds": 60,
        }

        monkeypatch.setattr("app.retrieval.search", lambda topic, k=8: [], raising=False)

        class FakeLLM:
            def chat(self, prompt, want_json=False, **kw):
                return json.dumps(crude_script)

        with pytest.raises(RuntimeError, match="content-safety gate BLOCKED"):
            avatar_job.run("test topic", llm=FakeLLM())

    def test_gate_passes_professional_script(self, monkeypatch):
        """A clean script passes the gate and returns render output."""
        import jobs.avatar_job as avatar_job  # noqa: PLC0415

        clean_script = {
            "title": "Roof Age and Insurance in Florida",
            "script_text": (
                "If your insurance company is threatening to drop your policy because of your roof age, "
                "here is what South Florida homeowners need to know right now. "
                "Citizens Insurance requires shingles to be under 25 years old and tile under 50. "
                "Call Perkins Roofing today for a free roof assessment."
            ),
            "est_seconds": 75,
        }

        monkeypatch.setattr("app.retrieval.search", lambda topic, k=8: [], raising=False)

        class FakeLLM:
            def chat(self, prompt, want_json=False, **kw):
                return json.dumps(clean_script)

        # Stub the safety gate to return PASS (avoids live LLM call in unit test)
        from core.content_safety import GateResult  # noqa: PLC0415
        monkeypatch.setattr(
            "adapters.safety.run_gate",
            lambda text, kind: GateResult(passed=True, reason="clean", layer="judge", score=0.95),
        )

        result = avatar_job.run("test topic", llm=FakeLLM())
        assert result["gate_passed"] is True
        assert result["title"] == clean_script["title"]
        assert result["job_id"]  # non-empty mock value
        assert result["url"]     # non-empty mock URL
