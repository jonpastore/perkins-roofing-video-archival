"""Tests for Item 11: virality score parsing + new render_spec fields.

Covers:
- _parse_virality: all inputs, clamping, total recomputation, rationale truncation.
- ClipRenderSpec: speaker_tracking + audio_enhance new fields.
- SuggestResponse / ClipSuggestion: virality field present and validated.
- RenderSpecRequest: new fields accepted.
"""
from __future__ import annotations

import os
import tempfile

import pytest

# Isolate SQLite DB before importing app.models
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from api.routes.clips import (  # noqa: E402
    ClipSuggestion,
    RenderSpecRequest,
    ViralityScore,
    _parse_virality,
)
from core.render_spec import ClipRenderSpec  # noqa: E402


# ---------------------------------------------------------------------------
# _parse_virality
# ---------------------------------------------------------------------------


class TestParseVirality:
    def test_none_returns_all_zeros(self) -> None:
        v = _parse_virality(None)
        assert v["total"] == 0
        assert v["hook_strength"] == 0
        assert v["emotion"] == 0
        assert v["pacing"] == 0
        assert v["value"] == 0
        assert v["rationale"] == ""

    def test_non_dict_returns_defaults(self) -> None:
        assert _parse_virality("bad") == _parse_virality(None)
        assert _parse_virality(42) == _parse_virality(None)
        assert _parse_virality([]) == _parse_virality(None)

    def test_valid_dict_parsed(self) -> None:
        raw = {"hook_strength": 20, "emotion": 15, "pacing": 18, "value": 22,
               "total": 99, "rationale": "great hook"}
        v = _parse_virality(raw)
        assert v["hook_strength"] == 20
        assert v["emotion"] == 15
        assert v["pacing"] == 18
        assert v["value"] == 22
        assert v["rationale"] == "great hook"

    def test_total_recomputed_from_parts(self) -> None:
        raw = {"hook_strength": 20, "emotion": 15, "pacing": 18, "value": 22,
               "total": 999}  # LLM gave wrong total
        v = _parse_virality(raw)
        assert v["total"] == 20 + 15 + 18 + 22

    def test_dimension_clamped_max_25(self) -> None:
        raw = {"hook_strength": 99, "emotion": 25, "pacing": 25, "value": 25, "total": 0}
        v = _parse_virality(raw)
        assert v["hook_strength"] == 25

    def test_dimension_clamped_min_0(self) -> None:
        raw = {"hook_strength": -10, "emotion": 10, "pacing": 10, "value": 10, "total": 0}
        v = _parse_virality(raw)
        assert v["hook_strength"] == 0

    def test_non_numeric_dimension_becomes_0(self) -> None:
        raw = {"hook_strength": "strong", "emotion": 10, "pacing": 10, "value": 10, "total": 0}
        v = _parse_virality(raw)
        assert v["hook_strength"] == 0

    def test_missing_dimension_defaults_to_0(self) -> None:
        raw = {"emotion": 10, "pacing": 10, "value": 10, "total": 0}
        v = _parse_virality(raw)
        assert v["hook_strength"] == 0

    def test_rationale_truncated_at_300(self) -> None:
        raw = {"rationale": "x" * 500}
        v = _parse_virality(raw)
        assert len(v["rationale"]) == 300

    def test_rationale_none_becomes_empty_string(self) -> None:
        raw = {"rationale": None}
        v = _parse_virality(raw)
        assert v["rationale"] == ""

    def test_all_zero_total_is_0(self) -> None:
        raw = {"hook_strength": 0, "emotion": 0, "pacing": 0, "value": 0, "total": 0}
        v = _parse_virality(raw)
        assert v["total"] == 0

    def test_max_total_is_100(self) -> None:
        raw = {"hook_strength": 25, "emotion": 25, "pacing": 25, "value": 25, "total": 999}
        v = _parse_virality(raw)
        assert v["total"] == 100

    def test_float_dimension_rounded_to_int(self) -> None:
        raw = {"hook_strength": 12.9, "emotion": 0, "pacing": 0, "value": 0, "total": 0}
        v = _parse_virality(raw)
        assert isinstance(v["hook_strength"], int)
        assert v["hook_strength"] == 12


# ---------------------------------------------------------------------------
# ViralityScore pydantic model
# ---------------------------------------------------------------------------


class TestViralityScore:
    def test_defaults_all_zero(self) -> None:
        vs = ViralityScore()
        assert vs.total == 0
        assert vs.hook_strength == 0
        assert vs.rationale == ""

    def test_from_parsed_dict(self) -> None:
        raw = {"hook_strength": 20, "emotion": 15, "pacing": 18, "value": 22,
               "total": 75, "rationale": "solid"}
        vs = ViralityScore(**raw)
        assert vs.total == 75
        assert vs.rationale == "solid"


# ---------------------------------------------------------------------------
# ClipSuggestion — virality field
# ---------------------------------------------------------------------------


class TestClipSuggestionVirality:
    def test_virality_defaults_to_empty(self) -> None:
        cs = ClipSuggestion(start=0.0, end=30.0, title="T", caption="C", hook="H", reason="R")
        assert cs.virality.total == 0

    def test_virality_field_accepted(self) -> None:
        vs = ViralityScore(hook_strength=20, emotion=15, pacing=18, value=22,
                          total=75, rationale="great")
        cs = ClipSuggestion(start=0.0, end=30.0, title="T", caption="C",
                           hook="H", reason="R", virality=vs)
        assert cs.virality.total == 75


# ---------------------------------------------------------------------------
# ClipRenderSpec — new fields
# ---------------------------------------------------------------------------


class TestClipRenderSpecNewFields:
    def test_speaker_tracking_defaults_false(self) -> None:
        spec = ClipRenderSpec()
        assert spec.speaker_tracking is False

    def test_audio_enhance_defaults_false(self) -> None:
        spec = ClipRenderSpec()
        assert spec.audio_enhance is False

    def test_speaker_tracking_set_true(self) -> None:
        spec = ClipRenderSpec(speaker_tracking=True)
        assert spec.speaker_tracking is True

    def test_audio_enhance_set_true(self) -> None:
        spec = ClipRenderSpec(audio_enhance=True)
        assert spec.audio_enhance is True

    def test_to_dict_includes_speaker_tracking(self) -> None:
        spec = ClipRenderSpec(speaker_tracking=True)
        d = spec.to_dict()
        assert "speaker_tracking" in d
        assert d["speaker_tracking"] is True

    def test_to_dict_includes_audio_enhance(self) -> None:
        spec = ClipRenderSpec(audio_enhance=True)
        d = spec.to_dict()
        assert "audio_enhance" in d
        assert d["audio_enhance"] is True

    def test_from_dict_round_trips_speaker_tracking(self) -> None:
        spec = ClipRenderSpec.from_dict({"speaker_tracking": True})
        assert spec.speaker_tracking is True

    def test_from_dict_round_trips_audio_enhance(self) -> None:
        spec = ClipRenderSpec.from_dict({"audio_enhance": True})
        assert spec.audio_enhance is True

    def test_backward_compatible_absent_fields(self) -> None:
        spec = ClipRenderSpec.from_dict({})
        assert spec.speaker_tracking is False
        assert spec.audio_enhance is False


# ---------------------------------------------------------------------------
# RenderSpecRequest — new fields
# ---------------------------------------------------------------------------


class TestRenderSpecRequestNewFields:
    def test_speaker_tracking_defaults_false(self) -> None:
        req = RenderSpecRequest()
        assert req.speaker_tracking is False

    def test_audio_enhance_defaults_false(self) -> None:
        req = RenderSpecRequest()
        assert req.audio_enhance is False

    def test_speaker_tracking_accepted(self) -> None:
        req = RenderSpecRequest(speaker_tracking=True)
        assert req.speaker_tracking is True

    def test_audio_enhance_accepted(self) -> None:
        req = RenderSpecRequest(audio_enhance=True)
        assert req.audio_enhance is True
