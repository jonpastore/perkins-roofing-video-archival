"""Pure render-spec helpers — no I/O, fully deterministic.

Render target (binding, satisfies IG + TikTok):
  MP4, H.264 high profile, +faststart, 9:16, 1080×1920,
  AAC 128kbps 48kHz, EBU R128 loudnorm (-14 LUFS), ≤300s, ≤300MB.

ClipRenderSpec
--------------
Pydantic model that captures per-series render options chosen in the Clip Studio
UI.  Stored inside MiniSeries.parts_json as a "render_spec" key (no new DB
column required — parts_json migrates from a bare list to
``{"clips": [...], "render_spec": {...}}``).

Defaults reproduce the current render_job behaviour so a null/absent spec is
fully backward-compatible.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

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


def aspect_export_vf(aspect: str) -> str:
    """Return a scale+pad+setsar filter string for a secondary aspect export.

    Mirrors :func:`_scale_pad_filter`'s letterbox approach (used for the fixed
    9:16 target) but parametrised by the export dimensions for *aspect* — the
    finished 9:16 reel is scaled/padded to "square" (1080x1080) or "wide"
    (1920x1080) with black bars, never cropped.

    Args:
        aspect: One of the keys in ``_ASPECT_EXPORT_DIMENSIONS`` ("square", "wide").

    Returns:
        An ffmpeg ``-vf`` filter string.

    Raises:
        ValueError: if *aspect* is not a supported export aspect.
    """
    if aspect not in _ASPECT_EXPORT_DIMENSIONS:
        raise ValueError(
            f"Unsupported export aspect {aspect!r}. "
            f"Choose from: {sorted(_ASPECT_EXPORT_DIMENSIONS)}"
        )
    w, h = _ASPECT_EXPORT_DIMENSIONS[aspect]
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1"
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


# ---------------------------------------------------------------------------
# ClipRenderSpec — per-series render options (Track A engine wiring)
# ---------------------------------------------------------------------------

_VALID_CAPTION_STYLES: frozenset[str] = frozenset(
    {"default", "bold_yellow", "tiktok_pop", "reels_clean", "shorts_editorial"}
)
# wipe/slide/dissolve removed (#344): those xfade kinds only make sense between
# two clips (see core/clip_fx.py) and are not honestly renderable on a single
# clip. Cut/fade remain — fade is a genuine single-clip fade-in/out.
_VALID_TRANSITIONS: frozenset[str] = frozenset({"cut", "fade"})
_VALID_COLOR_GRADES: frozenset[str] = frozenset({"none", "vivid", "warm", "cool"})
_VALID_BROLL_SOURCES: frozenset[str] = frozenset({"pexels", "none"})
_VALID_MUSIC_CATALOGS: frozenset[str] = frozenset({"pixabay", "ytaudio", "fma", "none"})
_VALID_ASPECTS: frozenset[str] = frozenset({"9:16", "square", "wide"})

# Output dimensions for the secondary aspect exports built from the finished
# 9:16 reel (see aspect_export_vf). "9:16" itself needs no secondary pass —
# it's the render's native output.
_ASPECT_EXPORT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "square": (1080, 1080),
    "wide": (1920, 1080),
}


class CaptionsSpec(BaseModel):
    style: str = "default"
    position: str = "bottom"

    @field_validator("style")
    @classmethod
    def _valid_style(cls, v: str) -> str:
        if v not in _VALID_CAPTION_STYLES:
            raise ValueError(
                f"captions.style must be one of {sorted(_VALID_CAPTION_STYLES)}, got {v!r}"
            )
        return v


class BrollSpec(BaseModel):
    source: str = "none"
    query_auto: bool = True

    @field_validator("source")
    @classmethod
    def _valid_source(cls, v: str) -> str:
        if v not in _VALID_BROLL_SOURCES:
            raise ValueError(f"broll.source must be one of {sorted(_VALID_BROLL_SOURCES)}, got {v!r}")
        return v


class MusicSpec(BaseModel):
    catalog: str = "none"
    track_id: str = ""
    volume_db: float = -18.0

    @field_validator("catalog")
    @classmethod
    def _valid_catalog(cls, v: str) -> str:
        if v not in _VALID_MUSIC_CATALOGS:
            raise ValueError(f"music.catalog must be one of {sorted(_VALID_MUSIC_CATALOGS)}, got {v!r}")
        return v

    @field_validator("volume_db")
    @classmethod
    def _valid_volume(cls, v: float) -> float:
        if not (-60.0 <= v <= 0.0):
            raise ValueError(f"music.volume_db must be between -60 and 0, got {v}")
        return v


class FxSpec(BaseModel):
    transition: str = "cut"
    color_grade: str = "none"
    title_card: bool = True

    @field_validator("transition")
    @classmethod
    def _valid_transition(cls, v: str) -> str:
        if v not in _VALID_TRANSITIONS:
            raise ValueError(f"fx.transition must be one of {sorted(_VALID_TRANSITIONS)}, got {v!r}")
        return v

    @field_validator("color_grade")
    @classmethod
    def _valid_color_grade(cls, v: str) -> str:
        if v not in _VALID_COLOR_GRADES:
            raise ValueError(f"fx.color_grade must be one of {sorted(_VALID_COLOR_GRADES)}, got {v!r}")
        return v


class ClipRenderSpec(BaseModel):
    """Per-series render options chosen in Clip Studio UI.

    All fields default to values that reproduce the current (pre-Track-A)
    render_job behaviour, so an absent spec is fully backward-compatible.

    JSON contract (stored in MiniSeries.parts_json["render_spec"]):
    {
      "reframe":           false,
      "speaker_tracking":  false,
      "captions":          {"style": "default", "position": "bottom"},
      "speech_cleanup":    false,
      "broll":             {"source": "none", "query_auto": true},
      "music":             {"catalog": "none", "track_id": "", "volume_db": -18.0},
      "fx":                {"transition": "cut", "color_grade": "none", "title_card": true},
      "emoji_highlights":  false,
      "aspects":           [],
      "audio_enhance":     false
    }
    """

    reframe: bool = False
    speaker_tracking: bool = False
    focus_x: float = 0.5  # manual horizontal focal point (0=left, 1=right) when not speaker-tracking
    captions: CaptionsSpec = Field(default_factory=CaptionsSpec)
    speech_cleanup: bool = False

    @field_validator("focus_x")
    @classmethod
    def _valid_focus_x(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"focus_x must be in [0, 1], got {v!r}")
        return v
    broll: BrollSpec = Field(default_factory=BrollSpec)
    music: MusicSpec = Field(default_factory=MusicSpec)
    fx: FxSpec = Field(default_factory=FxSpec)
    emoji_highlights: bool = False
    aspects: list[str] = Field(default_factory=list)
    audio_enhance: bool = False
    platforms: list[str] = Field(default_factory=list)  # auto-schedule targets; empty = default

    @field_validator("platforms")
    @classmethod
    def _valid_platforms(cls, v: list[str]) -> list[str]:
        allowed = {"instagram", "tiktok"}  # the platforms social_job can publish today
        for p in v:
            if p not in allowed:
                raise ValueError(f"platforms entries must be in {sorted(allowed)}, got {p!r}")
        return v

    @field_validator("aspects", mode="before")
    @classmethod
    def _valid_aspects(cls, v: Any) -> list[str]:
        if v is None:
            return []
        result = []
        for a in list(v):
            a_str = str(a)
            if a_str not in _VALID_ASPECTS:
                raise ValueError(
                    f"aspects entries must be one of {sorted(_VALID_ASPECTS)}, got {a_str!r}"
                )
            result.append(a_str)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ClipRenderSpec":
        if not data:
            return cls()
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def broll_enabled(self, pexels_key_present: bool = False) -> bool:
        """Return True only when broll is requested AND the provider key is available."""
        return self.broll.source == "pexels" and pexels_key_present

    def music_enabled(self) -> bool:
        return self.music.catalog != "none" and bool(self.music.track_id)


# ---------------------------------------------------------------------------
# parts_json envelope helpers
#
# MiniSeries.parts_json stores either:
#   - Legacy: a bare list  [{title, start, end}, ...]
#   - New:    a dict       {"clips": [...], "render_spec": {...}}
#
# All code should use these helpers rather than accessing parts_json directly.
# ---------------------------------------------------------------------------


def get_clips(parts_json: Any) -> list[dict]:
    """Extract the clips list from parts_json (handles both legacy and envelope form)."""
    if isinstance(parts_json, dict):
        return parts_json.get("clips") or []
    if isinstance(parts_json, list):
        return parts_json
    return []


def get_render_spec(parts_json: Any) -> ClipRenderSpec:
    """Extract the ClipRenderSpec from parts_json; returns defaults if absent."""
    if isinstance(parts_json, dict):
        return ClipRenderSpec.from_dict(parts_json.get("render_spec"))
    return ClipRenderSpec()


def set_render_spec(parts_json: Any, spec: ClipRenderSpec) -> dict:
    """Return a new envelope dict with the render_spec set.

    Upgrades legacy list form to envelope form transparently.
    """
    clips = get_clips(parts_json)
    return {"clips": clips, "render_spec": spec.to_dict()}
