"""The prompt slice in scripts/seed_video_description_prompt.py.

The source file in docs/ is Josh's verbatim EMAIL. What gets seeded is model instructions, so
the greeting, the signature block and the confidentiality notice must not survive the slice —
a prompt ending in "please notify the sender immediately" would eventually be written into a
caption. These assertions are against the real file, so an edit to it that breaks the boundaries
fails here rather than in production captions.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from seed_video_description_prompt import SOURCE, extract_prompt  # noqa: E402


def test_extracts_only_the_prompt_body():
    body = extract_prompt(SOURCE.read_text(encoding="utf-8"))
    assert body.startswith("# MASTER PROMPT")
    assert body.endswith("let the quality of the content do the selling.**")
    for leak in ("Hello Jon", "Best regards", "josh@perkinsroofing.net",
                 "confidential", "Sales Manager"):
        assert leak not in body, f"email wrapper leaked into the prompt: {leak!r}"


def test_all_eighteen_sections_survive():
    """Section count is the cheap proof the slice took the whole prompt, not a prefix."""
    body = extract_prompt(SOURCE.read_text(encoding="utf-8"))
    assert body.count("\n# ") + body.count("\n## ") == 18
    assert "# 17. OUTPUT RULE" in body
    assert "# FINAL STRUCTURE" in body


def test_hashtag_limit_is_strict_not_approximate():
    """Jon, 2026-08-11: a strict 5. 'approximately 5' is not a limit a model treats as one."""
    body = extract_prompt(SOURCE.read_text(encoding="utf-8"))
    assert "approximately 5 relevant hashtags" not in body
    assert "EXACTLY 5 relevant hashtags" in body
    assert "Never more than 5." in body


def test_refuses_rather_than_seeding_a_whole_email():
    """No silent fallback: a source that lost its markers must stop the seed, not seed the email."""
    with pytest.raises(ValueError):
        extract_prompt("Hello Jon,\n\nno markers here.\n\nBest regards,\nJosh")
    with pytest.raises(ValueError):
        extract_prompt("# MASTER PROMPT — too short\n\nBest regards,")
