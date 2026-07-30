"""The capture-stamp crop and the fail-closed "did it come through the sanitizer" check."""

import cv2
import numpy as np
import pytest

from core.photo_privacy import (
    STAMP_BAND,
    stamp_free_filename,
    strip_stamp,
    unsanitized_media,
)
from core.portfolio_criteria import check_project


def _jpeg(h: int = 400, w: int = 600) -> bytes:
    img = np.full((h, w, 3), 128, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _height(data: bytes) -> int:
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape[0]


def test_crops_the_stamp_band_off_the_bottom():
    assert _height(strip_stamp(_jpeg(400, 600))) == int(400 * (1 - STAMP_BAND))


def test_keeps_the_rest_of_the_image():
    """The crop must remove the band and nothing else — a gallery of slivers is not a fix."""
    out = strip_stamp(_jpeg(1000, 800))
    assert _height(out) == 800
    assert cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR).shape[1] == 800


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"\xff\xd8\xff\xe0trunc"])
def test_undecodable_input_raises(data):
    """A failed download or an HTML error page must not pass through as 'sanitized'."""
    with pytest.raises(ValueError):
        strip_stamp(data)


def test_image_too_short_to_crop_raises():
    """Guards the degenerate case where the crop would leave zero rows."""
    with pytest.raises(ValueError, match="too short"):
        strip_stamp(_jpeg(1, 600))


def test_filename_is_stable_so_republish_reuses_the_upload():
    assert stamp_free_filename("photo", "716040275") == "perkins-photo-716040275-b20.jpg"


def test_filename_encodes_the_band_so_widening_it_forces_a_recrop(monkeypatch):
    """sanitize_photo_to_media reuses an attachment by filename WITHOUT re-cropping. If the band
    were not in the name, raising STAMP_BAND after finding a stamp outside it would leave every
    already-uploaded photo at the old crop, silently."""
    import core.photo_privacy as pp
    before = pp.stamp_free_filename("photo", "1")
    monkeypatch.setattr(pp, "STAMP_BAND", 0.30)
    assert pp.stamp_free_filename("photo", "1") != before
    assert pp.stamp_free_filename("photo", "1").endswith("-b30.jpg")


def test_unsanitized_media_flags_a_cdn_url():
    html = '<img src="https://img.companycam.com/abc123" alt="roof" />'
    assert unsanitized_media(html) == ["https://img.companycam.com/abc123"]


def test_unsanitized_media_accepts_a_wp_upload():
    html = '<img src="https://example.com/wp-content/uploads/2026/07/perkins-photo-1.jpg" alt="a" />'
    assert unsanitized_media(html) == []


def test_unsanitized_media_is_an_allowlist_not_a_cdn_blocklist():
    """Naming known CDNs would pass every host nobody thought of. Only WP uploads are allowed."""
    assert unsanitized_media('<img src="https://cdn.example.net/x.jpg" alt="a" />')


def _project(content_html: str) -> dict:
    criteria = check_project(
        title="Miami Beach Oceanfront Condo", city="Miami Beach", meta="Roof restoration",
        content_html=content_html,
        selections=[{"kind": "photo", "id": "1", "alt": "a"}],
        scope_lines=["Polyglass 2-Ply Built-Up Roofing System"], jsonld=[],
        permissions={"permission_property": True, "permission_photos": True,
                     "permission_video": True},
    )
    return {c.key: c for c in criteria}


def test_gate_blocks_a_gallery_still_on_the_cdn():
    """The defect this whole module exists for: pixels carrying GPS that no text check sees."""
    c = _project('<p>x</p><img src="https://img.companycam.com/abc" alt="roof deck" />')
    assert c["media_sanitized"].ok is False
    assert c["media_sanitized"].severity == "blocker"
    # ...and it is invisible to the text-based check, which is exactly why this one is needed.
    assert c["no_pii"].ok is True


def test_gate_passes_a_sanitized_gallery():
    c = _project('<p>x</p><img src="https://wp.example/wp-content/uploads/a.jpg" alt="deck" />')
    assert c["media_sanitized"].ok is True


# --- video: the same stamp, a different tag ---------------------------------

def test_a_selected_video_is_blocked_while_no_video_sanitizer_exists():
    """gallery_html renders <video poster=... src=...> straight from the CompanyCam CDN, and
    build_project_jsonld copies both into VideoObject. Those frames carry the same capture
    stamp as the photos, so checking <img> alone published exactly what the crop removes."""
    html = ('<video controls preload="none" poster="https://img.companycam.com/thumb" '
            'src="https://video.companycam.com/clip.mp4"></video>')
    assert sorted(unsanitized_media(html)) == [
        "https://img.companycam.com/thumb", "https://video.companycam.com/clip.mp4"]


def test_gate_blocks_a_page_whose_only_cdn_file_is_a_video():
    c = _project('<p>x</p><img src="https://wp.example/wp-content/uploads/a.jpg" alt="deck" />'
                 '<video poster="https://img.companycam.com/t" src="https://cdn/v.mp4"></video>')
    assert c["media_sanitized"].ok is False
    assert c["media_sanitized"].severity == "blocker"


def test_a_wp_hosted_video_passes():
    c = _project('<img src="https://wp.example/wp-content/uploads/a.jpg" alt="deck" />'
                 '<video poster="https://wp.example/wp-content/uploads/t.jpg" '
                 'src="https://wp.example/wp-content/uploads/v.mp4"></video>')
    assert c["media_sanitized"].ok is True


def test_reencode_failure_raises_rather_than_returning_the_original(monkeypatch):
    """If the JPEG re-encode fails we must NOT fall back to the untouched bytes — that would
    return a still-stamped image to a caller that believes it is sanitized."""
    data = _jpeg()  # build the input BEFORE patching — the fixture encodes too
    monkeypatch.setattr(cv2, "imencode", lambda *a, **k: (False, None))
    with pytest.raises(ValueError, match="re-encode failed"):
        strip_stamp(data)


def test_a_caller_cannot_forge_a_sanitized_selection():
    """media_sanitized trusts sel['wp_url'], which the server sets from the real attachment.
    If a client could send it, anyone with curate rights could point the gallery at an
    unsanitized file whose path merely contains /wp-content/uploads/ and publish a stamped
    photo. SelectionItem declares only kind/id/alt, so pydantic drops the rest."""
    from api.routes.portfolio import SelectionItem

    forged = SelectionItem(**{
        "kind": "photo", "id": "1", "alt": "a",
        "wp_url": "https://evil.example/wp-content/uploads/x.jpg", "wp_media_id": 1,
    })
    assert sorted(forged.model_dump()) == ["alt", "id", "kind"]
