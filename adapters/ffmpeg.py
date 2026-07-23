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
    # Card text is partly derived from external YouTube video titles, so it must be safely
    # embedded in ffmpeg's filtergraph. Single-quoting the value makes filtergraph specials
    # (: , ; [ ]) literal; the ONE char that can't appear inside single quotes is the
    # apostrophe, written as the shell-style '\'' sequence (close-quote, literal quote,
    # reopen) — a plain \' would TERMINATE the quote early and garble titles like "Tim's".
    # expansion=none disables drawtext's % / \ expansion so those are literal too.
    escaped = text.replace("'", "'\\''")
    drawtext = (
        f"drawtext=text='{escaped}':expansion=none"
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


def fuse_videos(
    intro_path: str,
    clip_path: str,
    outro_path: str,
    out: str,
) -> str:
    """Concatenate intro + clip + outro into a single 1080×1920 reel MP4.

    All three inputs are normalised to 1080×1920, 30 fps, yuv420p, same SAR,
    and a consistent stereo 48 kHz audio track before concatenation.  The clip
    audio receives EBU R128 loudnorm (-14 LUFS) matching the image-card path.
    Segments without audio get synthesised silence so the concat filter always
    has three consistent v+a stream pairs.

    Args:
        intro_path: Path to the brand intro video file.
        clip_path:  Path to the extracted clip video.
        outro_path: Path to the brand outro video file.
        out:        Destination MP4 path (created/overwritten).

    Returns:
        *out* on success.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
        subprocess.TimeoutExpired: if the call takes too long.
    """
    def _video_norm(input_idx: int, out_label: str) -> str:
        """Return a scale/pad/setsar/fps filter chain for input *input_idx*."""
        return (
            f"[{input_idx}:v]fps=30,"
            f"scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1[{out_label}]"
        )

    def _audio_norm(input_idx: int, out_label: str, *, is_clip: bool, has_aud: bool) -> str:
        """Return an audio normalisation filter for segment *input_idx*.

        When the input has no audio stream a silence source is generated.
        The clip segment additionally receives loudnorm.
        """
        if not has_aud:
            # Probe duration so silence matches the video length; use a generous
            # upper bound — concat will trim at the video stream end anyway.
            return (
                f"aevalsrc=0:channel_layout=stereo:sample_rate=48000[{out_label}]"
            )
        if is_clip:
            return (
                f"[{input_idx}:a]loudnorm=I=-14:LRA=11:TP=-1.5,"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{out_label}]"
            )
        return (
            f"[{input_idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{out_label}]"
        )

    intro_has_audio = has_audio(intro_path)
    clip_has_audio = has_audio(clip_path)
    outro_has_audio = has_audio(outro_path)

    filter_parts = [
        _video_norm(0, "v0"),
        _audio_norm(0, "a0", is_clip=False, has_aud=intro_has_audio),
        _video_norm(1, "v1"),
        _audio_norm(1, "a1", is_clip=True, has_aud=clip_has_audio),
        _video_norm(2, "v2"),
        _audio_norm(2, "a2", is_clip=False, has_aud=outro_has_audio),
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]",
    ]
    filtergraph = ";".join(filter_parts)

    cmd = [
        _FFMPEG, "-y",
        "-i", intro_path,
        "-i", clip_path,
        "-i", outro_path,
        "-filter_complex", filtergraph,
        "-map", "[vout]",
        "-map", "[aout]",
        *output_args(),
        out,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=_ENCODE_TIMEOUT)
    return out


def has_audio(path: str) -> bool:
    """True if *path* contains at least one audio stream.

    Parses ``ffmpeg -i`` stderr (same approach as probe(), so it works with imageio-ffmpeg
    which ships no ffprobe). Used to reject a re-archived MP4 that is still video-only.
    """
    import re  # noqa: PLC0415

    result = subprocess.run(
        [_FFMPEG, "-hide_banner", "-i", path],
        capture_output=True,
        timeout=_PROBE_TIMEOUT,
    )
    text = result.stderr.decode("utf-8", errors="replace")
    return bool(re.search(r"Stream #\d+:\d+.*: Audio:", text))


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


def run_ffmpeg_cmd(cmd: list[str]) -> None:
    """Execute an arbitrary ffmpeg command list, raising on non-zero exit.

    Replaces the first element with the configured FFMPEG_BIN so callers
    that construct commands with a bare ``"ffmpeg"`` work correctly when the
    binary is overridden (e.g. imageio-ffmpeg in tests).

    Args:
        cmd: Full ffmpeg argument list, beginning with ``"ffmpeg"`` or
             the binary path.  The first element is replaced with FFMPEG_BIN.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
        subprocess.TimeoutExpired: if the call exceeds _ENCODE_TIMEOUT.
    """
    if cmd:
        cmd = [_FFMPEG] + cmd[1:]
    subprocess.run(cmd, check=True, capture_output=True, timeout=_ENCODE_TIMEOUT)


def extract_frame(src: str, timecode: float, *, max_width: int = 1600) -> bytes:
    """Extract a single JPEG frame from *src* (path or URL) at *timecode* seconds.

    ``-ss`` before ``-i`` seeks by keyframe index without reading the stream up to
    the target, so extraction from a remote (signed GCS) URL only ranges the bytes
    it needs. Frames wider than *max_width* are scaled down (source videos are up
    to 4K; article images don't need more).

    Returns:
        JPEG bytes.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
        subprocess.TimeoutExpired: if the call exceeds _ENCODE_TIMEOUT.
        ValueError: if ffmpeg produced no frame (timecode past end of video).
    """
    cmd = [
        _FFMPEG, "-ss", str(timecode), "-i", src,
        "-frames:v", "1", "-q:v", "2",
        "-vf", f"scale='min({max_width},iw)':-2",
        "-f", "image2", "pipe:1",
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, timeout=_ENCODE_TIMEOUT)
    if not proc.stdout:
        raise ValueError(f"no frame at t={timecode}s (past end of video?)")
    return proc.stdout
