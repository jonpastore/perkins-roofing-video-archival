"""Pure video-redaction filter builder — no I/O, deterministic.

Pixelates operator-marked regions for a time range, so a street number, a house
number or signage can be removed from a clip before it is published.

WHY THIS EXISTS. OpusClip and the rest of the short-form tools do not redact PII at
all (checked 2026-08-12). Tim films clients' houses, and a street number identifies
a property as precisely as the GPS fix CompanyCam already burns into photo pixels
(see core/photo_privacy.py). The privacy policy for this platform is that city and
neighbourhood are fine and anything narrowing to a property is not.

TWO DELIBERATE CHOICES, both arguable, both made for a reason:

1. PIXELATE, NOT INPAINT. Generative inpainting (ProPainter, LaMa) can make the
   number vanish convincingly. It also costs GPU-minutes per video-minute, leaves
   artefacts under motion, and — the deciding reason — it ALTERS THE FOOTAGE. A
   visible mosaic says "this was redacted". A clean inpaint says "this is what the
   house looked like", which is a worse thing to hand a client or a court.

2. OPERATOR-MARKED REGIONS, NOT OCR. core/photo_privacy.py already sets the
   doctrine here: "A blur is a guess about how much entropy is left in the pixels;
   a crop removes them." An OCR box is a guess about where the number is. An
   operator-confirmed box is not. Auto-detection can come later as a SUGGESTION
   feeding this same filter — it must not become the thing that decides.

Pure: builds filter strings only. Execution lives in adapters/ (render_job uses
adapters.ffmpeg.run_ffmpeg_cmd), matching core/audio_enhance.py.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

_FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")

#: Pixel block size. Big enough that the digits are unrecoverable, small enough
#: that the redaction reads as deliberate rather than as a compression fault.
DEFAULT_BLOCK: int = 16

#: Smallest region we will accept. Below this the mosaic is not clearly a mosaic,
#: and a too-small box usually means the caller mis-derived the coordinates.
MIN_DIMENSION: int = 8


class RedactionError(ValueError):
    """A redaction region is unusable. Raised rather than silently dropped.

    A dropped region means unredacted PII ships while the render reports success —
    the exact shape of failure this module exists to prevent, so every problem is
    loud.
    """


def _region(r: Any, key: str) -> Any:
    return r[key] if isinstance(r, dict) else getattr(r, key)


def validate_regions(regions: Iterable[Any], *,
                     frame_w: int | None = None,
                     frame_h: int | None = None,
                     clip_duration: float | None = None) -> list[dict]:
    """Normalise and check regions, raising RedactionError on anything unusable.

    ⚠️ TWO CONTRACTS THAT FAIL SILENTLY IF YOU GUESS THEM WRONG:

    * ``t0``/``t1`` are **CLIP-LOCAL seconds**, not source-absolute. The clip has
      already been cut by the time redaction runs, so a timestamp scrubbed from the
      full source video lands outside the window, ffmpeg exits 0, and the render
      logs "pii redaction applied" having redacted nothing. Pass *clip_duration*
      and that becomes an error instead of a leak. (core/censor.py shifts spans for
      exactly this reason — see render_job's "Word starts are source-relative".)
    * ``x``/``y``/``w``/``h`` are **source-frame pixels**. Marking against a
      differently-sized preview misplaces every box, and ffmpeg's crop clamps
      rather than complaining. Pass *frame_w*/*frame_h* so that is caught.

    Args:
        regions:  iterable of {x, y, w, h, t0, t1} dicts or objects. Pixel
                  coordinates from the top-left; t0/t1 in CLIP-LOCAL seconds.
        frame_w:  frame width, when known — a region outside it is rejected.
        frame_h:  frame height, when known.
        clip_duration: clip length in seconds, when known — a time window that
                  does not intersect [0, clip_duration) is rejected.

    Returns:
        A list of plain dicts, in input order.

    Raises:
        RedactionError: on a non-positive size, an inverted or empty time range,
                        a negative origin, or a region outside a known frame.
    """
    out: list[dict] = []
    for i, r in enumerate(regions):
        try:
            x, y = int(_region(r, "x")), int(_region(r, "y"))
            w, h = int(_region(r, "w")), int(_region(r, "h"))
            t0, t1 = float(_region(r, "t0")), float(_region(r, "t1"))
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            raise RedactionError(
                f"region {i}: needs x, y, w, h, t0, t1 — got {r!r}") from exc

        if w < MIN_DIMENSION or h < MIN_DIMENSION:
            raise RedactionError(
                f"region {i}: {w}x{h} is below the {MIN_DIMENSION}px minimum — "
                "a box this small is usually a coordinate error, and it would not "
                "read as a deliberate redaction")
        if x < 0 or y < 0:
            raise RedactionError(f"region {i}: origin ({x},{y}) is negative")
        if t1 <= t0:
            raise RedactionError(
                f"region {i}: t1 ({t1}) must be after t0 ({t0}) — an empty or "
                "inverted range redacts nothing")
        if t0 < 0:
            raise RedactionError(f"region {i}: t0 ({t0}) is negative")
        if frame_w is not None and x + w > frame_w:
            raise RedactionError(
                f"region {i}: extends to x={x + w}, past the {frame_w}px frame")
        if frame_h is not None and y + h > frame_h:
            raise RedactionError(
                f"region {i}: extends to y={y + h}, past the {frame_h}px frame")
        if clip_duration is not None and t0 >= clip_duration:
            raise RedactionError(
                f"region {i}: t0={t0:g}s is at or after the clip end "
                f"({clip_duration:g}s), so this region would redact NOTHING while "
                "the render reported success. t0/t1 are CLIP-LOCAL seconds — "
                "source-absolute timestamps do not work here.")

        out.append({"x": x, "y": y, "w": w, "h": h, "t0": t0, "t1": t1})
    return out


def build_redact_filter(regions: Iterable[Any], *,
                        block: int = DEFAULT_BLOCK,
                        frame_w: int | None = None,
                        frame_h: int | None = None,
                        clip_duration: float | None = None) -> str:
    """Return an ffmpeg ``-filter_complex`` graph pixelating each region over its range.

    NOT usable as ``-vf`` — the graph carries [labels] and must be passed to
    ``-filter_complex`` with an explicit ``-map`` of the final label.

    Implemented per region as crop -> scale down -> scale up (nearest) -> overlay,
    gated by ``enable='between(t,t0,t1)'``. That mosaics only the box and only
    while it is on screen; every other pixel and every other frame is untouched.

    Returns "" for an empty region list, so a caller can pass the result straight
    through without branching.

    Raises:
        RedactionError: propagated from validate_regions.
    """
    regs = validate_regions(regions, frame_w=frame_w, frame_h=frame_h,
                            clip_duration=clip_duration)
    if not regs:
        return ""
    if block < 2:
        raise RedactionError(f"block must be >= 2, got {block}")

    parts: list[str] = []
    src = "0:v"
    for i, r in enumerate(regs):
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        # Downscale to at least 1px so a small box still collapses to blocks.
        dw, dh = max(1, w // block), max(1, h // block)
        enable = f"between(t\\,{r['t0']:g}\\,{r['t1']:g})"
        tap, base, nxt = f"s{i}a", f"s{i}b", f"v{i}"
        # SPLIT before reusing the label. An ffmpeg INTERNAL link feeds exactly one
        # input pad, so a label cannot be both the crop source and the overlay base.
        # `[0:v]` gets away with it because an input-stream specifier may be
        # duplicated — which is why region 0 worked and every N>=2 graph was
        # rejected with "Stream specifier 'v0' ... matches no streams".
        parts.append(
            f"[{src}]split[{tap}][{base}];"
            f"[{tap}]crop={w}:{h}:{x}:{y},"
            f"scale={dw}:{dh},scale={w}:{h}:flags=neighbor[px{i}];"
            f"[{base}][px{i}]overlay={x}:{y}:enable='{enable}'[{nxt}]"
        )
        src = nxt
    return ";".join(parts)


def build_redact_cmd(in_path: str, out_path: str, regions: Iterable[Any], *,
                     block: int = DEFAULT_BLOCK,
                     frame_w: int | None = None,
                     frame_h: int | None = None,
                     clip_duration: float | None = None) -> list[str]:
    """Full ffmpeg arg list applying the redaction. Audio is copied unchanged.

    Raises:
        RedactionError: when there is nothing to redact, or a region is unusable.
                        Refusing an empty list is deliberate: a caller asking to
                        redact and getting a silent copy would believe PII was
                        removed when it was not.
    """
    fc = build_redact_filter(regions, block=block, frame_w=frame_w,
                            frame_h=frame_h, clip_duration=clip_duration)
    if not fc:
        raise RedactionError(
            "no regions to redact — refusing to emit a passthrough command that "
            "would look like a successful redaction")
    last = fc.rsplit("[", 1)[-1].rstrip("]")
    return [
        _FFMPEG, "-y",
        "-i", in_path,
        "-filter_complex", fc,
        "-map", f"[{last}]",
        "-map", "0:a?",     # keep audio if present; tolerate silent clips
        "-c:a", "copy",
        out_path,
    ]
