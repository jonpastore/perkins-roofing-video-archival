"""Pure render-spec helpers — no I/O, fully deterministic.

Render target (binding, satisfies IG + TikTok):
  MP4, H.264 high profile, +faststart, 9:16, 1080×1920,
  AAC 128kbps 48kHz, EBU R128 loudnorm (-14 LUFS), ≤300s, ≤300MB.
"""

# Duration in seconds that title and closing cards are held on screen when
# they are produced from static images (passed to build_filtergraph).
_TITLE_DEFAULT_SECS: float = 3.0
_CLOSING_DEFAULT_SECS: float = 3.0

# Target dimensions
_W = 1080
_H = 1920


def _scale_pad_filter(stream_label: str, out_label: str) -> str:
    """Return a scale+pad+setsar filter chain that forces *stream_label* to
    1080×1920 with black bars (letterbox/pillarbox) without cropping.

    force_original_aspect_ratio=decrease shrinks the content to fit inside the
    frame; pad then adds black to reach the exact target dimensions; setsar=1
    ensures square pixels on output so players don't mis-render anamorphic."""
    return (
        f"[{stream_label}]scale={_W}:{_H}:"
        f"force_original_aspect_ratio=decrease,"
        f"pad={_W}:{_H}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1[{out_label}]"
    )


def build_filtergraph(title_secs: float, closing_secs: float) -> str:
    """Build the ffmpeg filter_complex string for a 3-segment reel.

    Layout: title image (held title_secs) → clip → closing image (held closing_secs).

    Inputs assumed by the caller (in order):
      0: title image  (still, looped to title_secs via -loop 1 -t title_secs)
      1: clip video   (the extracted source clip)
      2: closing image (still, looped to closing_secs via -loop 1 -t closing_secs)

    The filter:
      - Scales/pads each video stream to 1080×1920 (force_original_aspect_ratio=decrease + pad + setsar=1)
      - Generates silence for the title/closing image audio streams
      - Applies EBU R128 loudnorm (-14 LUFS) to the clip audio
      - Concatenates all three segments (video + audio) into a single stream

    Returns a string suitable for passing to ffmpeg -filter_complex.
    """
    parts = [
        # --- title image: scale/pad video, generate silence audio ---
        _scale_pad_filter("0:v", "v0"),
        f"aevalsrc=0:channel_layout=stereo:sample_rate=48000:duration={title_secs:.6f}[a0]",

        # --- clip: scale/pad video, loudnorm audio (aformat ensures matching sample
        #     format/rate/layout so the concat filter accepts silence + clip audio) ---
        _scale_pad_filter("1:v", "v1"),
        (
            "[1:a]loudnorm=I=-14:LRA=11:TP=-1.5,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a1]"
        ),

        # --- closing image: scale/pad video, generate silence audio ---
        _scale_pad_filter("2:v", "v2"),
        f"aevalsrc=0:channel_layout=stereo:sample_rate=48000:duration={closing_secs:.6f}[a2]",

        # --- concat all three segments ---
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]",
    ]
    return ";".join(parts)


def output_args() -> list[str]:
    """Return the ffmpeg output encoder arguments for the binding render spec.

    -c:v libx264 -profile:v high  → H.264 high profile
    -movflags +faststart           → moov atom at front for streaming
    -pix_fmt yuv420p               → broadest player compatibility
    -c:a aac -b:a 128k -ar 48000  → AAC 128kbps 48kHz
    """
    return [
        "-c:v", "libx264",
        "-profile:v", "high",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "48000",
    ]
