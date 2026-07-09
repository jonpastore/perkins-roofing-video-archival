"""Unit tests for core.email_proof — 100% coverage target.

All tests are pure (no I/O, no mocking required).
"""
from core.email_proof import build_proof_prompt, diff_suggestions

# ---------------------------------------------------------------------------
# build_proof_prompt
# ---------------------------------------------------------------------------

class TestBuildProofPrompt:
    def test_contains_draft(self):
        draft = "Dear client, we wants to offer our servises."
        prompt = build_proof_prompt(draft)
        assert draft in prompt

    def test_contains_proofing_instruction(self):
        prompt = build_proof_prompt("some draft")
        lower = prompt.lower()
        assert "grammar" in lower
        assert "clarity" in lower
        assert "professionalism" in lower

    def test_instructs_return_corrected_only(self):
        prompt = build_proof_prompt("any text")
        lower = prompt.lower()
        # Should instruct to return only corrected text, no commentary
        assert "corrected" in lower or "only" in lower

    def test_returns_string(self):
        result = build_proof_prompt("hello")
        assert isinstance(result, str)

    def test_non_empty_for_empty_draft(self):
        result = build_proof_prompt("")
        assert len(result) > 0

    def test_draft_preserved_verbatim(self):
        draft = "Line one.\nLine two with $pecial ch@rs & <tags>."
        prompt = build_proof_prompt(draft)
        assert draft in prompt

    def test_different_drafts_produce_different_prompts(self):
        p1 = build_proof_prompt("Draft A")
        p2 = build_proof_prompt("Draft B")
        assert p1 != p2


# ---------------------------------------------------------------------------
# diff_suggestions
# ---------------------------------------------------------------------------

class TestDiffSuggestions:
    def test_identical_returns_empty(self):
        text = "Hello.\nHow are you?"
        assert diff_suggestions(text, text) == []

    def test_single_line_change(self):
        original = "We offers the best roofing."
        proofed = "We offer the best roofing."
        result = diff_suggestions(original, proofed)
        assert len(result) == 1
        assert result[0]["original"] == original
        assert result[0]["proofed"] == proofed

    def test_multiline_one_changed(self):
        original = "Dear sir,\nWe wants to help.\nRegards"
        proofed = "Dear sir,\nWe want to help.\nRegards"
        result = diff_suggestions(original, proofed)
        assert len(result) == 1
        assert result[0]["original"] == "We wants to help."
        assert result[0]["proofed"] == "We want to help."

    def test_deletion_sets_proofed_empty(self):
        original = "Line A\nLine B"
        proofed = "Line A"
        result = diff_suggestions(original, proofed)
        assert any(s["original"] == "Line B" and s["proofed"] == "" for s in result)

    def test_insertion_sets_original_empty(self):
        original = "Line A"
        proofed = "Line A\nLine B"
        result = diff_suggestions(original, proofed)
        assert any(s["original"] == "" and s["proofed"] == "Line B" for s in result)

    def test_returns_list_of_dicts(self):
        result = diff_suggestions("old", "new")
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "original" in item
            assert "proofed" in item

    def test_empty_original_and_proofed(self):
        assert diff_suggestions("", "") == []

    def test_empty_original_nonempty_proofed(self):
        result = diff_suggestions("", "Added line")
        assert len(result) == 1
        assert result[0]["original"] == ""
        assert result[0]["proofed"] == "Added line"

    def test_nonempty_original_empty_proofed(self):
        result = diff_suggestions("Removed line", "")
        assert len(result) == 1
        assert result[0]["original"] == "Removed line"
        assert result[0]["proofed"] == ""

    def test_all_lines_changed(self):
        original = "A\nB\nC"
        proofed = "X\nY\nZ"
        result = diff_suggestions(original, proofed)
        assert len(result) == 3
        originals = [s["original"] for s in result]
        proofeds = [s["proofed"] for s in result]
        assert originals == ["A", "B", "C"]
        assert proofeds == ["X", "Y", "Z"]

    def test_deterministic(self):
        original = "Hello world\nThis is a test\nGoodbye"
        proofed = "Hello world\nThis is a Test\nGoodbye"
        r1 = diff_suggestions(original, proofed)
        r2 = diff_suggestions(original, proofed)
        assert r1 == r2
