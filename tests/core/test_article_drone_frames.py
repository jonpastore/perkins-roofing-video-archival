"""#445 — the article image gallery could not contain a drone shot.

Tim, 2026-07-28: the picks "look identical" — near-duplicate garage stills, when "every video
opens and closes with ~30s of drone footage."

The cause was structural, not a bad model choice. YouTube auto-extracts exactly three frames per
video, at ~25/50/75% of its run time, and those were the only candidates. All three are mid-video
by construction, so no amount of prompting could surface an aerial: the opening and closing drone
shots were never in the candidate set at all.

`drone_timecodes` names the timecodes worth pulling from the archived source instead.
"""
from __future__ import annotations

from core.article_images import (
    DRONE_HEAD_S,
    MIN_DURATION_FOR_TAIL_S,
    drone_timecodes,
    frame_candidates,
)


def test_youtube_frames_are_all_mid_video_which_is_the_whole_problem():
    """Pin the premise: every hosted candidate sits between 25% and 75% of the video."""
    cands = [c for c in frame_candidates("abcdefghijk", duration=600.0)
             if not c["is_title_card"]]
    assert [c["timecode"] for c in cands] == [150, 300, 450]
    assert all(0.2 * 600 < c["timecode"] < 0.8 * 600 for c in cands), (
        "if this ever stops holding, drone_timecodes may be redundant"
    )


def test_drone_timecodes_hit_both_the_opening_and_closing_aerial():
    tcs = drone_timecodes(600.0)
    assert any(t <= max(DRONE_HEAD_S) for t in tcs), "no opening aerial suggested"
    assert any(t >= 600 - 35 for t in tcs), "no closing aerial suggested"
    assert tcs == sorted(set(tcs)), "must be sorted and deduplicated"


def test_no_suggestion_lands_past_the_end_of_the_video():
    """A timecode past the end makes ffmpeg seek off the tail and the extract 502s."""
    for d in (30.0, 45.0, 90.0, 100.0, 3600.0):
        assert all(0 <= t < d for t in drone_timecodes(d)), d


def test_a_short_video_gets_no_tail_window():
    """Below the threshold the head and tail overlap and would suggest duplicate frames."""
    short = drone_timecodes(MIN_DURATION_FOR_TAIL_S - 10)
    assert short, "a short video should still get opening-aerial suggestions"
    assert all(t <= max(DRONE_HEAD_S) for t in short)


def test_unknown_duration_suggests_nothing_rather_than_guessing():
    """Without an end, a tail offset is a guess that seeks past it."""
    assert drone_timecodes(None) == []
    assert drone_timecodes(0) == []
    assert drone_timecodes(-5) == []


def test_suggestions_do_not_duplicate_the_hosted_frames():
    """The gallery filters these against existing candidates; they should rarely collide anyway."""
    duration = 600.0
    hosted = {c["timecode"] for c in frame_candidates("abcdefghijk", duration)
              if c["timecode"] is not None}
    assert not (set(drone_timecodes(duration)) & hosted)
