"""100% line-coverage tests for core/publish_dispatch.py.

Covers:
  - All valid state transitions
  - All invalid state transitions (reject with ValueError)
  - should_retry: boundary conditions + invalid max_attempts
  - backoff_seconds: growth, cap, invalid attempt
  - render_caption: happy path, missing var (preserved), empty vars, empty template
  - transcode_spec: all 7 platforms, unknown platform raises KeyError
"""
import pytest

from core.publish_dispatch import (
    TranscodeSpec,
    backoff_seconds,
    next_status,
    render_caption,
    should_retry,
    transcode_spec,
)

# ---------------------------------------------------------------------------
# next_status — state machine
# ---------------------------------------------------------------------------

class TestNextStatus:
    def test_pending_start_gives_in_flight(self):
        assert next_status("PENDING", "start") == "IN_FLIGHT"

    def test_in_flight_success_gives_published(self):
        assert next_status("IN_FLIGHT", "success") == "PUBLISHED"

    def test_in_flight_fail_gives_failed(self):
        assert next_status("IN_FLIGHT", "fail") == "FAILED"

    def test_invalid_pending_success_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("PENDING", "success")

    def test_invalid_pending_fail_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("PENDING", "fail")

    def test_invalid_published_start_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("PUBLISHED", "start")

    def test_invalid_published_success_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("PUBLISHED", "success")

    def test_invalid_published_fail_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("PUBLISHED", "fail")

    def test_invalid_failed_start_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("FAILED", "start")

    def test_invalid_failed_success_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("FAILED", "success")

    def test_invalid_failed_fail_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("FAILED", "fail")

    def test_invalid_in_flight_start_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            next_status("IN_FLIGHT", "start")

    def test_error_message_includes_status_and_event(self):
        with pytest.raises(ValueError, match="status='PUBLISHED'"):
            next_status("PUBLISHED", "start")


# ---------------------------------------------------------------------------
# should_retry
# ---------------------------------------------------------------------------

class TestShouldRetry:
    def test_attempt_0_of_3_should_retry(self):
        assert should_retry(0, 3) is True

    def test_attempt_1_of_3_should_retry(self):
        assert should_retry(1, 3) is True

    def test_attempt_2_of_3_no_retry(self):
        # attempt 2 is the 3rd (last) attempt
        assert should_retry(2, 3) is False

    def test_attempt_0_of_1_no_retry(self):
        assert should_retry(0, 1) is False

    def test_max_attempts_zero_raises(self):
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            should_retry(0, 0)

    def test_max_attempts_negative_raises(self):
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            should_retry(0, -1)

    def test_large_attempt_below_max(self):
        assert should_retry(98, 100) is True

    def test_large_attempt_at_max(self):
        assert should_retry(99, 100) is False


# ---------------------------------------------------------------------------
# backoff_seconds
# ---------------------------------------------------------------------------

class TestBackoffSeconds:
    def test_attempt_0_is_one_second(self):
        assert backoff_seconds(0) == 1.0

    def test_attempt_1_is_two_seconds(self):
        assert backoff_seconds(1) == 2.0

    def test_attempt_2_is_four_seconds(self):
        assert backoff_seconds(2) == 4.0

    def test_attempt_3_is_eight_seconds(self):
        assert backoff_seconds(3) == 8.0

    def test_attempt_4_is_sixteen_seconds(self):
        assert backoff_seconds(4) == 16.0

    def test_large_attempt_capped_at_300(self):
        assert backoff_seconds(20) == 300.0

    def test_attempt_8_hits_cap(self):
        # 2^8 = 256 < 300, 2^9 = 512 > 300
        assert backoff_seconds(8) == 256.0
        assert backoff_seconds(9) == 300.0

    def test_negative_attempt_raises(self):
        with pytest.raises(ValueError, match="attempt must be >= 0"):
            backoff_seconds(-1)


# ---------------------------------------------------------------------------
# render_caption
# ---------------------------------------------------------------------------

class TestRenderCaption:
    def test_all_vars_substituted(self):
        tmpl = "Roofing in {location} by {crew} — {product}!"
        result = render_caption(tmpl, {"location": "Palm Beach", "crew": "Team Perkins", "product": "metal"})
        assert result == "Roofing in Palm Beach by Team Perkins — metal!"

    def test_missing_var_preserved_as_placeholder(self):
        tmpl = "Expert {product} in {location}"
        result = render_caption(tmpl, {"product": "roofing"})
        assert result == "Expert roofing in {location}"

    def test_empty_vars_returns_template_unchanged(self):
        tmpl = "Call {crew} today!"
        result = render_caption(tmpl, {})
        assert result == "Call {crew} today!"

    def test_empty_template_returns_empty(self):
        assert render_caption("", {"location": "FL"}) == ""

    def test_no_placeholders_passthrough(self):
        tmpl = "Perkins Roofing — Florida's best."
        assert render_caption(tmpl, {"location": "FL"}) == tmpl

    def test_extra_vars_ignored(self):
        tmpl = "Roofing by {crew}"
        result = render_caption(tmpl, {"crew": "us", "location": "FL", "extra": "ignored"})
        assert result == "Roofing by us"

    def test_multiple_same_var(self):
        tmpl = "{location} roofing in {location}"
        result = render_caption(tmpl, {"location": "Miami"})
        assert result == "Miami roofing in Miami"

    def test_partial_missing_preserves_all_missing(self):
        tmpl = "{a} and {b} and {c}"
        result = render_caption(tmpl, {"b": "B"})
        assert result == "{a} and B and {c}"


# ---------------------------------------------------------------------------
# transcode_spec
# ---------------------------------------------------------------------------

class TestTranscodeSpec:
    PLATFORMS = ["tiktok", "instagram", "youtube_shorts", "facebook", "linkedin", "x", "pinterest"]

    def test_all_platforms_return_transcode_spec(self):
        for p in self.PLATFORMS:
            spec = transcode_spec(p)
            assert isinstance(spec, TranscodeSpec)
            assert spec.platform == p

    def test_all_platforms_have_9_16_aspect(self):
        for p in self.PLATFORMS:
            assert transcode_spec(p).aspect_ratio == "9:16"

    def test_all_platforms_use_h264(self):
        for p in self.PLATFORMS:
            assert transcode_spec(p).codec_video == "h264"

    def test_all_platforms_use_aac(self):
        for p in self.PLATFORMS:
            assert transcode_spec(p).codec_audio == "aac"

    def test_tiktok_max_length(self):
        assert transcode_spec("tiktok").max_length_seconds == 600

    def test_instagram_max_length(self):
        assert transcode_spec("instagram").max_length_seconds == 90

    def test_youtube_shorts_max_length(self):
        assert transcode_spec("youtube_shorts").max_length_seconds == 60

    def test_facebook_max_length(self):
        assert transcode_spec("facebook").max_length_seconds == 90

    def test_linkedin_max_length(self):
        assert transcode_spec("linkedin").max_length_seconds == 600

    def test_x_max_length(self):
        assert transcode_spec("x").max_length_seconds == 140

    def test_pinterest_max_length(self):
        assert transcode_spec("pinterest").max_length_seconds == 900

    def test_unknown_platform_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown platform"):
            transcode_spec("snapchat")

    def test_spec_is_frozen(self):
        spec = transcode_spec("tiktok")
        with pytest.raises((AttributeError, TypeError)):
            spec.platform = "changed"  # type: ignore[misc]

    def test_notes_field_populated(self):
        for p in self.PLATFORMS:
            assert transcode_spec(p).notes  # non-empty
