"""core.article_images — curated in-video frame candidates + img swapping (pure)."""

from core.article_images import (
    current_image_src,
    embedded_video_ids,
    frame_candidates,
    swap_image_src,
    valid_candidate_url,
)

VID = "gtbkLgg_G9o"
IMG = (f'<img src="https://img.youtube.com/vi/{VID}/hqdefault.jpg" '
       f'alt="Roof — Perkins Roofing" loading="lazy" />')
BODY = f"<p>intro</p>\n{IMG}\n<p>rest https://youtu.be/{VID}</p>"


def test_frame_candidates_three_frames_then_title_card():
    c = frame_candidates(VID, duration=400)
    assert [x["position"] for x in c] == [1, 2, 3, 0]
    assert [x["is_title_card"] for x in c] == [False, False, False, True]
    # ~25/50/75% timecodes, each deep-linked for gallery context
    assert [x["timecode"] for x in c[:3]] == [100, 200, 300]
    assert c[1]["watch_url"] == f"https://www.youtube.com/watch?v={VID}&t=200s"
    assert c[0]["url"].endswith("/maxres1.jpg")
    assert c[0]["fallback_url"].endswith("/hq1.jpg")


def test_frame_candidates_without_duration_has_no_timecodes():
    c = frame_candidates(VID)
    assert all(x["timecode"] is None for x in c)
    assert c[0]["watch_url"] == f"https://www.youtube.com/watch?v={VID}"


def test_embedded_video_ids_dedupes_across_reference_shapes():
    content = (f"https://www.youtube.com/watch?v={VID} "
               f'<img src="https://i.ytimg.com/vi/{VID}/hq2.jpg"> '
               "https://youtu.be/BnsaVtCb0GU")
    assert embedded_video_ids(content) == [VID, "BnsaVtCb0GU"]


def test_valid_candidate_url_accepts_only_known_variants_of_allowed_videos():
    ok = f"https://i.ytimg.com/vi/{VID}/maxres2.jpg"
    assert valid_candidate_url(ok, {VID})
    assert not valid_candidate_url(ok, {"BnsaVtCb0GU"})  # not this article's video
    assert not valid_candidate_url(f"https://i.ytimg.com/vi/{VID}/evil.jpg", {VID})
    assert not valid_candidate_url(f"https://example.com/vi/{VID}/hq2.jpg", {VID})
    assert not valid_candidate_url("", {VID})


def test_swap_image_src_replaces_only_the_thumbnail_img():
    new = f"https://i.ytimg.com/vi/{VID}/maxres3.jpg"
    out = swap_image_src(BODY, new)
    assert f'src="{new}"' in out
    assert "hqdefault" not in out
    assert 'alt="Roof — Perkins Roofing"' in out  # rest of the tag untouched
    assert f"https://youtu.be/{VID}" in out  # watch link untouched
    assert current_image_src(out) == new


def test_swap_image_src_noop_without_a_thumbnail():
    assert swap_image_src("<p>plain</p>", "x") == "<p>plain</p>"
    assert current_image_src("<p>plain</p>") is None
