"""Clip / video UI feature delivery.

Pins every control ClipStudioHelp documents, plus Archive and Video Approval
surfaces, against the source. A missing string here means the screen stopped
shipping a feature the help (or the wave-3 video spec) still promises.
"""
from pathlib import Path

CLIP = Path("web/src/pages/ClipStudio.tsx").read_text()
HELP = Path("web/src/components/ClipStudioHelp.tsx").read_text()
ARCHIVE = Path("web/src/pages/Archive.tsx").read_text()
APPROVAL = Path("web/src/pages/VideoApproval.tsx").read_text()
SCHED = Path("web/src/pages/Scheduling.tsx").read_text()
APP = Path("web/src/App.tsx").read_text()
PLAT = Path("web/src/components/PlatformCheckboxes.tsx").read_text()


def test_nav_exposes_the_three_video_surfaces():
    for tab, label in (
        ("archive", "Video Archive"),
        ("clip-studio", "Clip Studio"),
        ("video-approval", "Video Approval"),
    ):
        assert f'["{tab}", "{label}"]' in APP
    assert "<ClipStudio />" in APP
    assert "<VideoApproval />" in APP
    assert "<Archive />" in APP


def test_clip_studio_help_titles_all_have_a_writer_on_the_screen():
    """Help is the operator contract. Every titled control must exist in ClipStudio.tsx."""
    writers = {
        "Platform presets": ["General", "Instagram", "TikTok", "YouTube Shorts", "Facebook",
                             "Suggest clips"],
        "Scene detection": ["Detect scenes", "visual", "/clips/scenes"],
        "Platform fit check": ["Fits", "/clips/preview/preflight"],
        "Reframe (9:16)": ["Reframe 9:16", "spec.reframe"],
        "Speaker tracking": ["Speaker tracking", "spec.speaker_tracking"],
        "Focal point": ["Focal point", "focus_x"],
        "Captions": ["Bold yellow", "TikTok Pop", "Reels Clean", "Shorts Editorial"],
        "Emoji highlights": ["Emoji highlights", "emoji_highlights"],
        "Speech cleanup": ["Speech cleanup", "speech_cleanup"],
        "Audio enhance": ["Audio enhance", "audio_enhance"],
        "Background music": ["Background music", "pixabay", "fma"],
        "Export aspects": ["9:16 (always)", "1:1 square", "16:9 wide"],
        "Publish targets": ["Publish to", "instagram", "tiktok"],
        "Auto-censor": [],  # automatic — no toggle; help says so
    }
    for title, needles in writers.items():
        assert f'title: "{title}"' in HELP, f"help dropped {title}"
        for n in needles:
            assert n in CLIP, f"{title}: {n!r} missing from ClipStudio.tsx"


def test_clip_studio_flow_steps_are_wired():
    for needle in (
        "Step 1 — Pick a source video",
        "Step 2 — AI clip suggestions",
        "Step 2 — Review suggested clips",
        "Step 3 — Save as clip series",
        'apiFetch("/clips/suggest"',
        'apiFetch("/clips/save"',
        'apiFetch("/clips/renderable"',
        'apiFetch(`/clips/${s.id}/render`',
        'apiFetch(`/clips/${seriesId}/render_spec`',
        "Render options ▼",
        "Render now",
        "Play preview",
        "Ready to Render",
        "Save as clip series",
        "Hide videos with clips already",
        "Re-generate →",
        "? Help — features",
    ):
        assert needle in CLIP, needle


def test_clip_card_curation_controls():
    for needle in (
        "Preview on YouTube",
        "Show transcript",
        "Detect scenes",
        'detectScenes("speech")',
        'detectScenes("visual")',
        "cut @",
        "clip.included",
        "clip.hook",
        "clip.caption",
        "ViralityBadge",
    ):
        assert needle in CLIP, needle


def test_render_options_gate_save_until_spec_loaded():
    """A save before GET lands would PUT DEFAULT_SPEC and wipe stored keys."""
    assert "specLoaded" in CLIP
    assert "disabled={saving || !specLoaded}" in CLIP
    assert "focus_x" in CLIP
    assert "platforms" in CLIP


def test_reframe_hides_focal_point_when_speaker_tracking_is_on():
    assert "spec.reframe &&" in CLIP
    assert "!spec.speaker_tracking" in CLIP
    assert "focus_x" in CLIP


def test_brand_intro_outro_upload_exists():
    assert "upload-brand-video" in CLIP
    assert "intro" in CLIP.lower()
    assert "outro" in CLIP.lower()


def test_scheduling_uses_platform_checkboxes_not_a_select():
    assert "PlatformCheckboxes" in SCHED
    assert "PUBLISHABLE" in PLAT
    assert '"instagram"' in PLAT and '"tiktok"' in PLAT


def test_archive_detail_and_actions():
    for needle in (
        "/archive/${video.id}/detail",
        "Used in Articles",
        "Used in Social Posts",
        "Topics (",
        "navigate(\"clip-studio\", { video: v.id })",
        "navigate(\"video-approval\", { series: v.id })",
        "/archive/${video.id}/download",
        "/archive/${video.id}/hide",
        "/archive/${v.id}/rename",
        "Open in Clip Studio",
        "Review reel →",
        "include_hidden",
    ):
        assert needle in ARCHIVE, needle


def test_video_approval_review_loop():
    for needle in (
        "/video/proposals",
        "/video/${proposal.id}/approve",
        "/video/${proposal.id}/repropose",
        "/video/${proposal.video_id}/description",
        "Approve",
        "Re-propose",
        "hh:mm:ss",
        "fmtHMS",
        "parseHMS",
        "ytLink",
        "Download source video",
        "Generate description",
        "beforeunload",
    ):
        assert needle in APPROVAL, needle


def test_help_does_not_advertise_redact_regions():
    """Decided unreachable — the frame an operator would draw on does not exist."""
    assert "redact" not in HELP.lower()
    assert "redact_regions:" not in CLIP
    assert "Redact" not in CLIP
