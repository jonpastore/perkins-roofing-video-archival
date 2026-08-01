"""Remove CompanyCam's burned-in capture stamp from a photo before it can be published.

CompanyCam renders the capture time AND the GPS fix into the image pixels at capture time —
e.g. ``Sep 1, 2023 at 12:12:36 PM / 25.858694° N 80.120019° W``, six decimals, roughly 0.1 m.
Measured 2026-07-30 on the Olsen project: of 16 photos sampled across 802, every one from the
2023 capture window carried it.

``core/pii.py`` cannot see this. It reads text surfaces — body, meta, title, image alt, JSON-LD
captions, scope lines — all of which were clean, so ``no_pii`` returned ok while the gallery
would have shipped the property's coordinates. Privacy policy is that city and neighbourhood
are fine and anything narrowing to a property is not; a GPS fix is the narrowest thing there is.

The stamp is CUT, not blurred. A blur is a guess about how much entropy is left in the pixels;
a crop removes them. Band measured, not assumed: the stamp sat inside the bottom ~14% of every
sampled photo, and cutting 20% left no trace in any of the 16.

The gate that actually protects the page is NOT a detector — detection would have to be right
every time on an adversarial input. It is :func:`unsanitized_media`, which requires every
published file — image OR video, including a video's poster frame — to be WP-hosted, i.e. to
have come through this module. Fail closed: media that was never sanitized cannot reach a page,
whether or not anything recognised a stamp in it.
"""

from __future__ import annotations

import re

# Fraction of image height removed from the bottom. Raising this is safe; LOWERING it needs a
# re-check against real captures — see the module docstring for how the 20% was arrived at.
STAMP_BAND = 0.20

# WordPress serves library uploads from this path. An image whose src does not contain it never
# went through upload_media, so it is still a third-party URL with whatever is burned into it.
_WP_UPLOADS = "/wp-content/uploads/"

# Both tags matter. gallery_html renders a selected video as
# <video poster="<cdn thumbnail>" src="<cdn video>">, and build_project_jsonld copies the same
# urls into VideoObject.contentUrl/thumbnailUrl. Checking <img> alone let a video publish
# CompanyCam-hosted frames carrying the same capture stamp the crop exists to remove.
_MEDIA_TAG_RE = re.compile(r"<(?:img|video)\b[^>]*>", re.IGNORECASE)
# Double-quoted, single-quoted AND bare. Matching only ``src="..."`` made this gate depend on how
# the emitter happened to quote, and gallery_html interpolated editor-supplied alt text
# unescaped — so an alt ending in `" /><img src='<cdn url>` produced a SINGLE-quoted tag that
# this regex could not see, and a raw CompanyCam file published with media_sanitized green.
# The emitter now escapes (core.portfolio_media.gallery_html), but a gate that is only correct
# because of what its caller does is not a gate: both halves are fixed on purpose.
# The bare branch must not start with `&`: once the emitter escapes alt text, a hostile alt
# renders as `... src=&#x27;https://cdn/...` INSIDE the alt attribute, and a greedy bare match
# read that as a real unsanitized src — refusing to publish a page whose only sin was the words
# "src=" in a caption. Fail-closed is right; fail-closed on correct input is a different bug.
_MEDIA_URL_ATTR_RE = re.compile(
    r"""\b(?:src|poster)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>'"&][^\s>'"]*))""", re.IGNORECASE)


def strip_stamp(data: bytes) -> bytes:
    """Return ``data`` with the bottom :data:`STAMP_BAND` of the image removed.

    Raises ValueError on anything that does not decode as an image, so a failed download or an
    HTML error page cannot pass through as "sanitized".

    ⚠️ THIS ALSO STRIPS EXIF, INCLUDING EXIF GPS — and that is load-bearing, not incidental.
    The burned-in pixel stamp is only half the exposure; a CompanyCam JPEG can carry the same
    fix in its metadata, which no crop would touch. It works because the round trip is
    decode-to-pixels then re-encode, and OpenCV writes a bare JPEG with no metadata. Verified by
    round-tripping an image with an injected GPS payload (see the test alongside this module).
    Anything that makes this a lossless/metadata-preserving crop — a PIL rewrite, a
    "don't re-encode if the band is zero" fast path — silently republishes coordinates.
    """
    import cv2  # noqa: PLC0415 — heavy import, only needed when a photo is actually published
    import numpy as np  # noqa: PLC0415

    try:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:  # empty buffer asserts inside OpenCV rather than returning None
        raise ValueError("not a decodable image") from exc
    if img is None:
        raise ValueError("not a decodable image")
    keep = int(img.shape[0] * (1.0 - STAMP_BAND))
    if keep < 1:
        raise ValueError(f"image too short to crop: {img.shape[0]}px")
    ok, buf = cv2.imencode(".jpg", img[:keep], [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError("re-encode failed")
    return buf.tobytes()


def stamp_free_filename(kind: str, media_id: str) -> str:
    """Stable name for the sanitized copy, so re-publishing reuses it instead of re-uploading.

    The band is IN the name (``-b20``) on purpose. adapters.wordpress.sanitize_photo_to_media
    reuses an existing attachment with this filename without re-cropping, so if STAMP_BAND is
    ever raised — the exact thing you would do on finding a stamp outside the current band —
    every photo already uploaded would keep its old, insufficient crop and nothing would say so.
    Encoding the band means a change to it changes every filename, forcing a re-crop.
    """
    return f"perkins-{kind}-{media_id}-b{int(round(STAMP_BAND * 100))}.jpg"


def unsanitized_media(content_html: str) -> list[str]:
    """Gallery image/video urls that are NOT WordPress-hosted — never passed the sanitizer.

    This is the fail-closed half of the privacy gate. It asks "did this come through the
    sanitizer", not "can I see a stamp in it", because only the first question has an answer
    that is reliable on media nobody has looked at.

    There is no video sanitizer yet — cropping a video means a full re-encode — so in practice
    this BLOCKS publishing a selected video. That is the intended outcome, not an oversight: a
    CompanyCam video's frames and its poster thumbnail carry the same burned-in stamp as its
    photos, and shipping them while claiming the page is sanitized would be the worse failure.
    """
    urls: list[str] = []
    for tag in _MEDIA_TAG_RE.findall(content_html or ""):
        for groups in _MEDIA_URL_ATTR_RE.findall(tag):
            # One alternation per quoting style, so exactly one group is non-empty per match.
            url = next((g for g in groups if g), "")
            if url and _WP_UPLOADS not in url:
                urls.append(url)
    return urls
