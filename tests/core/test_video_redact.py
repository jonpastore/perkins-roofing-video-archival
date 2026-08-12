"""Behavioral validation for video PII redaction.

This is a privacy path, so the tests are written to fail LOUDLY rather than to
confirm the happy path: a silently-dropped region means unredacted PII ships while
the render reports success.

The last test actually runs ffmpeg and inspects pixels, because a filter string
that looks right and mosaics nothing is exactly the failure a string assertion
cannot see.
"""
import re
import shutil
import subprocess

import pytest

from core.video_redact import (
    DEFAULT_BLOCK,
    RedactionError,
    build_redact_cmd,
    build_redact_filter,
    validate_regions,
)

R = {"x": 100, "y": 200, "w": 160, "h": 80, "t0": 1.0, "t1": 4.5}


# --- validation: every rejection is a real failure mode ---------------------

def test_a_valid_region_normalises_to_a_plain_dict():
    assert validate_regions([R]) == [R]


def test_object_regions_work_too():
    class Reg:
        x, y, w, h, t0, t1 = 10, 20, 30, 40, 0.0, 1.0
    assert validate_regions([Reg()])[0]["w"] == 30


@pytest.mark.parametrize("bad,why", [
    ({**R, "w": 0}, "zero width mosaics nothing"),
    ({**R, "h": 4}, "below the 8px minimum"),
    ({**R, "x": -5}, "negative origin"),
    ({**R, "t1": 1.0}, "empty range (t1 == t0)"),
    ({**R, "t1": 0.5}, "inverted range"),
    ({**R, "t0": -1.0}, "negative start"),
])
def test_unusable_regions_raise_rather_than_being_skipped(bad, why):
    """A dropped region is unredacted PII on a green render."""
    with pytest.raises(RedactionError):
        validate_regions([bad])


def test_a_region_outside_the_frame_is_rejected():
    with pytest.raises(RedactionError, match="past the"):
        validate_regions([R], frame_w=200, frame_h=1080)
    with pytest.raises(RedactionError, match="past the"):
        validate_regions([R], frame_w=1920, frame_h=250)


def test_a_region_missing_a_key_names_the_problem():
    with pytest.raises(RedactionError, match="needs x, y, w, h"):
        validate_regions([{"x": 1, "y": 2, "w": 30, "h": 40}])


# --- filter construction ----------------------------------------------------

def test_filter_gates_on_the_time_range():
    """Only while the number is on screen — the rest of the clip is untouched."""
    f = build_redact_filter([R])
    assert "enable='between(t\\,1\\,4.5)'" in f


def test_filter_crops_and_overlays_at_the_region_origin():
    f = build_redact_filter([R])
    assert "crop=160:80:100:200" in f
    assert "overlay=100:200" in f


def test_pixelation_uses_nearest_neighbour_not_a_smooth_blur():
    """A soft blur can leave recoverable structure; hard blocks do not, and they
    read unambiguously as a deliberate redaction."""
    f = build_redact_filter([R])
    assert "flags=neighbor" in f
    assert f"scale={160 // DEFAULT_BLOCK}:{80 // DEFAULT_BLOCK}" in f


def test_a_tiny_region_still_collapses_to_at_least_one_block():
    """max(1, w//block) — a 10px box must not scale to 0 and crash ffmpeg."""
    f = build_redact_filter([{**R, "w": 10, "h": 10}])
    assert "scale=1:1," in f


def test_multiple_regions_chain_so_all_of_them_apply():
    """Two addresses in one shot must BOTH be redacted, not just the last.

    ⚠️ These are SUBSTRING assertions and they passed against a graph ffmpeg
    rejected outright — an internal label was consumed twice, so every N>=2 render
    died with "Stream specifier 'v0' matches no streams". The real check is
    test_two_regions_both_mosaic_through_real_ffmpeg below; this one only pins the
    coordinates."""
    f = build_redact_filter([R, {**R, "x": 500, "y": 600}])
    assert "crop=160:80:100:200" in f and "crop=160:80:500:600" in f
    assert f.count("overlay=") == 2


def test_each_reused_label_is_split_before_being_consumed_twice():
    """An ffmpeg INTERNAL link feeds exactly one input pad. [0:v] may be duplicated
    because it is an input-stream specifier; [v0] may not."""
    f = build_redact_filter([R, {**R, "x": 500, "y": 600}])
    assert f.count("split") == 2, f


def test_no_regions_yields_an_empty_filter():
    assert build_redact_filter([]) == ""


def test_block_size_must_be_sane():
    with pytest.raises(RedactionError):
        build_redact_filter([R], block=1)


# --- command ----------------------------------------------------------------

def test_cmd_maps_the_last_filter_output_and_copies_audio():
    cmd = build_redact_cmd("in.mp4", "out.mp4", [R])
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "0:a?" in cmd, "optional audio — a silent clip must not fail"
    last = cmd[cmd.index("-map") + 1]
    assert last.startswith("[v") and last.endswith("]")


def test_cmd_refuses_an_empty_region_list():
    """Asking to redact and getting a silent passthrough would let the caller
    believe PII was removed when it was not."""
    with pytest.raises(RedactionError, match="refusing"):
        build_redact_cmd("in.mp4", "out.mp4", [])


# --- the one that actually looks at pixels ----------------------------------

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_pixels_inside_the_region_change_and_pixels_outside_do_not(tmp_path):
    """THE behavioural check. A filter string can be well-formed and mosaic
    nothing; only the frames can say otherwise.

    Measured with PSNR per quadrant rather than byte equality: filter_complex
    re-encodes, so even untouched pixels shift slightly under lossy compression.
    The question is not "did anything change" but "did the region change ENORMOUSLY
    more than the rest of the frame".
    """
    src, out = tmp_path / "src.mp4", tmp_path / "out.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=3",
        "-pix_fmt", "yuv420p", str(src)], check=True)

    region = {"x": 0, "y": 0, "w": 160, "h": 120, "t0": 0.0, "t1": 3.0}
    subprocess.run(
        build_redact_cmd(str(src), str(out), [region], frame_w=320, frame_h=240)
        + ["-hide_banner", "-loglevel", "error"], check=True)

    def psnr(geom: str) -> float:
        """Average PSNR between src and out over one cropped quadrant.
        Lower = more different. inf/None means identical."""
        r = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", str(src), "-i", str(out),
            "-lavfi", f"[0:v]crop={geom}[a];[1:v]crop={geom}[b];[a][b]psnr",
            "-f", "null", "-"], capture_output=True, text=True, check=True)
        m = re.search(r"average:([0-9.]+|inf)", r.stderr)
        assert m, r.stderr[-500:]
        return float("inf") if m.group(1) == "inf" else float(m.group(1))

    inside = psnr("160:120:0:0")        # the redacted quadrant
    outside = psnr("160:120:160:120")   # untouched quadrant

    assert inside < 25, (
        f"region PSNR {inside:.1f} dB — too similar to the source; the redaction "
        "did not actually mosaic anything")
    assert outside > inside + 10, (
        f"outside PSNR {outside:.1f} dB vs inside {inside:.1f} dB — the rest of "
        "the frame changed as much as the region, so this is not a targeted redaction")


# --- the N>=2 path, against real ffmpeg -------------------------------------

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_two_regions_both_mosaic_through_real_ffmpeg(tmp_path):
    """THE regression test for the label-reuse bug. Two regions is the ORDINARY
    case — a house number and a plate, or one number visible in two shots — and it
    failed to render at all while the string-assertion test above stayed green."""
    src, out = tmp_path / "src.mp4", tmp_path / "out.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=3",
        "-pix_fmt", "yuv420p", str(src)], check=True)

    regions = [
        {"x": 0, "y": 0, "w": 160, "h": 120, "t0": 0.0, "t1": 3.0},     # top-left
        {"x": 160, "y": 120, "w": 160, "h": 120, "t0": 0.0, "t1": 3.0},  # bottom-right
    ]
    subprocess.run(
        build_redact_cmd(str(src), str(out), regions, frame_w=320, frame_h=240)
        + ["-hide_banner", "-loglevel", "error"], check=True)

    def psnr(geom):
        r = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", str(src), "-i", str(out),
            "-lavfi", f"[0:v]crop={geom}[a];[1:v]crop={geom}[b];[a][b]psnr",
            "-f", "null", "-"], capture_output=True, text=True, check=True)
        m = re.search(r"average:([0-9.]+|inf)", r.stderr)
        return float("inf") if m.group(1) == "inf" else float(m.group(1))

    tl, br = psnr("160:120:0:0"), psnr("160:120:160:120")
    untouched = psnr("160:120:160:0")   # top-right, not marked
    assert tl < 25, f"first region not mosaiced (PSNR {tl:.1f})"
    assert br < 25, f"SECOND region not mosaiced (PSNR {br:.1f}) — only the last applied"
    assert untouched > max(tl, br) + 10, "an unmarked quadrant was altered"


# --- the silent leak --------------------------------------------------------

def test_a_time_window_past_the_clip_end_is_rejected():
    """ffmpeg exits 0 and redacts NOTHING when the window falls outside the clip,
    and render_job then logs "pii redaction applied". t0/t1 are CLIP-LOCAL; an
    operator scrubbing the full source video produces exactly this."""
    with pytest.raises(RedactionError, match="CLIP-LOCAL"):
        validate_regions([{**R, "t0": 600.0, "t1": 604.0}], clip_duration=4.0)


def test_a_window_inside_the_clip_is_accepted():
    assert validate_regions([{**R, "t0": 1.0, "t1": 3.0}], clip_duration=4.0)


def test_clip_duration_is_optional_so_existing_callers_still_work():
    assert validate_regions([R]) == [R]
