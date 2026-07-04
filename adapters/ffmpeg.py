"""ffmpeg / ffprobe adapter (I/O — coverage-omitted).

All subprocess calls use check=True + an explicit timeout.
FFMPEG_BIN env-var overrides the binary path (used by the validate script to
point at the imageio-ffmpeg bundled binary without a system install).
"""

from __future__ import annotations

import os
import subprocess

from core.render_spec import build_filtergraph, output_args

_FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")

# Hard timeout (seconds) for any single ffmpeg/ffprobe call.
# A 300s reel encode could take minutes on slow hardware; give it room.
_ENCODE_TIMEOUT = 1200
_PROBE_TIMEOUT = 30


def make_card(text: str, out: str, *, seconds: float = 3, bg: str = "black", fg: str = "white") -> str:
    """Render a 1080×1920 title/closing card with *text* centred via ffmpeg lavfi.

    Uses the ``color`` source for the background and ``drawtext`` for the
    text overlay.  Long text is word-wrapped at ~40 characters per line.
    Font size is fixed at 72px (readable on mobile).

    Args:
        text:    The text to display on the card.
        out:     Destination image path (PNG recommended).
        seconds: Duration of the generated video card in seconds.
        bg:      Background colour (any ffmpeg colour string, e.g. ``"black"``).
        fg:      Foreground/text colour.

    Returns:
        *out* on success.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
        subprocess.TimeoutExpired: if the call takes too long.
    """
    # Escape special characters that ffmpeg drawtext would misinterpret.
    escaped = text.replace("'", "\\'").replace(":", "\\:")
    drawtext = (
        f"drawtext=text='{escaped}'"
        f":fontcolor={fg}:fontsize=72"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":line_spacing=10"
    )
    cmd = [
        _FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"color=c={bg}:size=1080x1920:rate=30:duration={seconds}",
        "-vf", drawtext,
        "-vframes", str(int(seconds * 30)),
        "-c:v", "png",
        out,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=_ENCODE_TIMEOUT)
    return out


def clip(src: str, start: float, end: float, out: str) -> str:
    """Extract a time-range from *src* into *out* using stream-copy.

    Args:
        src:   Path to the source video file.
        start: Clip start time in seconds.
        end:   Clip end time in seconds.
        out:   Destination MP4 path (created/overwritten).

    Returns:
        *out* on success.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
        subprocess.TimeoutExpired: if the call takes too long.
    """
    duration = end - start
    cmd = [
        _FFMPEG, "-y",
        "-ss", str(start),
        "-i", src,
        "-t", str(duration),
        "-c", "copy",
        out,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=_ENCODE_TIMEOUT)
    return out


def fuse(
    clip_path: str,
    title_img: str,
    closing_img: str,
    out: str,
    *,
    title_secs: float = 3.0,
    closing_secs: float = 3.0,
) -> str:
    """Fuse title image + clip + closing image into a single 1080×1920 reel MP4.

    The title and closing card images are held for *title_secs* / *closing_secs*
    respectively. The clip is loudnorm-normalised to -14 LUFS.

    Args:
        clip_path:    Path to the extracted clip video.
        title_img:    Path to the title card image (PNG/JPG).
        closing_img:  Path to the closing card image (PNG/JPG).
        out:          Destination MP4 path.
        title_secs:   Seconds to hold the title card (default 3).
        closing_secs: Seconds to hold the closing card (default 3).

    Returns:
        *out* on success.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
        subprocess.TimeoutExpired: if the call takes too long.
    """
    filtergraph = build_filtergraph(title_secs, closing_secs)

    cmd = [
        _FFMPEG, "-y",
        # input 0: title image (looped to title_secs)
        "-loop", "1", "-t", str(title_secs), "-i", title_img,
        # input 1: clip video
        "-i", clip_path,
        # input 2: closing image (looped to closing_secs)
        "-loop", "1", "-t", str(closing_secs), "-i", closing_img,
        "-filter_complex", filtergraph,
        "-map", "[vout]",
        "-map", "[aout]",
        *output_args(),
        out,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=_ENCODE_TIMEOUT)
    return out


def probe(path: str) -> dict:
    """Return video metadata by parsing ffmpeg -i stderr output.

    Uses the ffmpeg binary (FFMPEG_BIN) rather than a separate ffprobe binary
    so the adapter works with imageio-ffmpeg (which ships only ffmpeg) and any
    environment where only ffmpeg is installed.

    Returns a dict::

        {
            "width":    int,
            "height":   int,
            "duration": float,   # seconds
        }

    Raises:
        subprocess.TimeoutExpired: if the call takes too long.
        ValueError: if width/height/duration cannot be parsed from the output.
    """
    import re  # noqa: PLC0415

    # ``ffmpeg -hide_banner -i <path>`` always exits 1 (no output specified) but
    # writes stream info to stderr — we capture that and ignore the exit code.
    # -hide_banner suppresses the lengthy build/version header so the relevant
    # Duration/Stream lines are in the captured output without being buried.
    result = subprocess.run(
        [_FFMPEG, "-hide_banner", "-i", path],
        capture_output=True,
        timeout=_PROBE_TIMEOUT,
    )
    text = result.stderr.decode("utf-8", errors="replace")

    # Parse the video resolution — match ", NNNxNNNN" (comma-prefixed) to avoid
    # accidentally capturing hex values like "0x31637661" in codec strings.
    width = height = 0
    m = re.search(r",\s*(\d{3,5})x(\d{3,5})\b", text)
    if m:
        width = int(m.group(1))
        height = int(m.group(2))

    # Parse: "Duration: HH:MM:SS.ff"
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        duration = h * 3600 + mn * 60 + s

    if width == 0 or height == 0 or duration == 0.0:
        raise ValueError(
            f"probe: could not parse video info from ffmpeg output for {path!r}.\n"
            f"ffmpeg stderr:\n{text[:800]}"
        )

    return {"width": width, "height": height, "duration": duration}
