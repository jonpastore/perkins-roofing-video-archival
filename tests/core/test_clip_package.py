"""Aastro packaging gate and score-band display (canonical numbers stay raw)."""
from __future__ import annotations

from core.clip_package import (
    CLIP_MAX_SECS,
    CLIP_MIN_SECS,
    SCORE_HELP,
    missing_package_fields,
    score_band,
)


def _ready(**overrides) -> dict:
    clip = {
        "town": "Boca Raton",
        "problem": "tile leak",
        "title": "Boca Raton tile leak: the flashing mistake we found",
        "hook": "Boca Raton tile leak — we found the flashing mistake",
        "audience": "homeowner",
        "phone_cta": "Call the office",
        "start": 12.0,
        "end": 38.0,
    }
    clip.update(overrides)
    return clip


def test_ready_package_has_no_gaps():
    assert missing_package_fields(_ready()) == []


def test_length_must_be_fifteen_to_forty_seconds():
    assert CLIP_MIN_SECS == 15 and CLIP_MAX_SECS == 40
    assert "length" in missing_package_fields(_ready(end=12.0 + 10))
    assert "length" in missing_package_fields(_ready(end=12.0 + 50))
    assert "length" not in missing_package_fields(_ready(end=12.0 + 20))


def test_missing_town_problem_audience_hook_cta():
    gaps = missing_package_fields(_ready(
        town="", problem="", audience="both", hook="", phone_cta="",
    ))
    for field in ("town", "problem", "audience", "hook", "phone_cta"):
        assert field in gaps


def test_roofer_audience_is_valid():
    assert missing_package_fields(_ready(audience="roofer")) == []


def test_score_help_explains_why_we_chose_each():
    assert "uniqueness" in SCORE_HELP["opportunity"].lower()
    assert "comments" in SCORE_HELP["heat"].lower()
    assert "page" in SCORE_HELP["coverage"].lower()


def test_score_band_uses_peers_never_a_fake_hundred():
    peers = [1.0, 2.0, 20.0]
    assert score_band(0.0, peers) == "low"
    assert score_band(1.0, peers) == "low"
    assert score_band(20.0, peers) == "high"
    assert score_band(8.0, [1.0, 8.0, 20.0]) == "medium"


def test_score_band_without_enough_peers_uses_fixed_thresholds():
    assert score_band(6.0, [1.0]) == "high"
    assert score_band(2.0, []) == "medium"
    assert score_band(0.4, [None]) == "low"  # type: ignore[list-item]
