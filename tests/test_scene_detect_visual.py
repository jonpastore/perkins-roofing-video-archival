"""parse_scene_timestamps + build_scene_detect_cmd (pure; runner is integration-only)."""
from core.scene_detect_visual import build_scene_detect_cmd, parse_scene_timestamps


def test_parse_pts_time_collapses_near_duplicates():
    out = "frame:0 pts_time:2.0\nlavfi.scene_score=0.5\nframe:1 pts_time:2.05\nframe:2 pts_time:9.0"
    assert parse_scene_timestamps(out, min_gap=1.0) == [2.0, 9.0]


def test_parse_scd_time_form():
    assert parse_scene_timestamps("lavfi.scd.time=12.345\nlavfi.scd.score=0.5") == [12.345]


def test_parse_empty_or_garbage():
    assert parse_scene_timestamps("") == []
    assert parse_scene_timestamps("no timestamps here") == []


def test_build_cmd_contains_filter_and_range():
    cmd = build_scene_detect_cmd("/tmp/v.mp4", 0.4, start=5.0, end=20.0)
    assert "/tmp/v.mp4" in cmd
    assert any("select='gt(scene,0.4)'" in x for x in cmd)
    assert cmd.count("-f") == 1 and "null" in cmd
    assert "-ss" in cmd and "-to" in cmd
