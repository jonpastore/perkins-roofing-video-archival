"""Hook title overlay helpers — pure, no I/O.

Item 5 (Clip Studio v1): burn the clip's ``hook`` text as an on-screen title
band for the first 2.5 s using ffmpeg drawtext.  Designed for 9:16 (1080×1920)
vertical video with platform-safe margins.

Public API
----------
escape_drawtext(text)
    Escape ``text`` for safe embedding in an ffmpeg drawtext value.  Handles
    the four special characters that break drawtext when unescaped inside the
    single-quoted value: ``'``, ``:``, ``\\``, ``%``.

hook_drawtext_filter(hook_text, *, duration, brand_color, fontsize, y_expr)
    Return a complete ``-vf`` drawtext filter string that burns *hook_text*
    as a band overlay for the first *duration* seconds.
"""
from __future__ import annotations

# Brand-red in ffmpeg colour syntax (0xRRGGBB).
_DEFAULT_BRAND_COLOR: str = "0xCC2222"

# Duration the hook title stays on screen (seconds).
_DEFAULT_HOOK_DURATION: float = 2.5

# Font size for the hook title.
_DEFAULT_FONTSIZE: int = 52

# Vertical position: safe-area bottom-third for 9:16 (near top of lower-third).
# 1920 * 0.75 = 1440 → text centre at y=1440 means top-of-text near 1400.
_DEFAULT_Y_EXPR: str = "(h*3/4)-text_h/2"

# Box padding around the text band.
_DEFAULT_BOX_BORDER: int = 16

# Box background: black at 70% opacity.
_DEFAULT_BOX_COLOR: str = "black@0.70"


def escape_drawtext(text: str) -> str:
    """Escape *text* for safe embedding in an ffmpeg drawtext filter value.

    The filter value is single-quoted by the caller (``text='...'``).  The
    following characters require escaping within that single-quoted context:

    - ``'``  — close-quote + literal-quote + reopen-quote sequence (``'\\''``)
    - ``\\`` — doubled to ``\\\\`` so ffmpeg's drawtext parser sees a literal
      backslash rather than an escape sequence.
    - ``%``  — doubled to ``%%`` to prevent strftime/printf expansion even
      when ``expansion=none`` is set (defence-in-depth).
    - ``:``  — escaped to ``\\:`` because ``:`` is the key=value separator in
      the ffmpeg filter option string.

    The order matters: backslashes are replaced first so subsequent
    substitutions do not double-escape already-escaped characters.

    Returns:
        The escaped text string (without surrounding quotes).
    """
    # 1. Backslash first (must be before other replacements that add backslashes).
    text = text.replace("\\", "\\\\")
    # 2. Colon — ffmpeg filter separator.
    text = text.replace(":", "\\:")
    # 3. Percent — prevent strftime expansion.
    text = text.replace("%", "%%")
    # 4. Apostrophe — inside single-quoted value must break/reopen the quote.
    text = text.replace("'", "'\\''")
    return text


def hook_drawtext_filter(
    hook_text: str,
    *,
    duration: float = _DEFAULT_HOOK_DURATION,
    brand_color: str = _DEFAULT_BRAND_COLOR,
    fontsize: int = _DEFAULT_FONTSIZE,
    y_expr: str = _DEFAULT_Y_EXPR,
    box_border: int = _DEFAULT_BOX_BORDER,
    box_color: str = _DEFAULT_BOX_COLOR,
) -> str:
    """Return a ``-vf`` drawtext filter string for a hook title band overlay.

    The text is horizontally centred and positioned at *y_expr* on a
    semi-transparent black box band.  It is displayed only for the first
    *duration* seconds of the clip (``enable='between(t,0,duration)'``).

    The text colour is *brand_color*; the box background is *box_color*.

    Args:
        hook_text:   The hook text to display.  Escaped automatically.
        duration:    How long (seconds) the title stays on screen.
        brand_color: ffmpeg colour string for the text (default brand red).
        fontsize:    Font size in pixels.
        y_expr:      ffmpeg expression for the text's vertical position.
        box_border:  Padding pixels around the text for the background band.
        box_color:   ffmpeg colour string for the background box.

    Returns:
        A ``-vf`` filter string (suitable for passing to ``ffmpeg -vf ...``).

    Raises:
        ValueError: if *hook_text* is empty after stripping.
    """
    stripped = hook_text.strip() if hook_text else ""
    if not stripped:
        raise ValueError("hook_text must not be empty")

    escaped = escape_drawtext(stripped)
    return (
        f"drawtext="
        f"text='{escaped}'"
        f":expansion=none"
        f":fontsize={fontsize}"
        f":fontcolor={brand_color}"
        f":x=(w-text_w)/2"
        f":y={y_expr}"
        f":box=1"
        f":boxcolor={box_color}"
        f":boxborderw={box_border}"
        f":enable='between(t,0,{duration:.6f})'"
    )
