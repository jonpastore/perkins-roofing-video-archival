"""Tests for core.video_availability — pure availability detector.

Three branches:
  - "unknown"     → stats_map is falsy/empty (whole-batch API failure)
  - "available"   → batch succeeded AND video_id is in stats_map
  - "unavailable" → batch succeeded AND video_id is NOT in stats_map
"""
import pytest

from core.video_availability import availability_from_batch


def test_unknown_when_stats_map_is_none():
    assert availability_from_batch("abc123", None) == "unknown"  # type: ignore[arg-type]


def test_unknown_when_stats_map_is_empty_dict():
    assert availability_from_batch("abc123", {}) == "unknown"


def test_available_when_video_id_in_stats_map():
    stats_map = {"abc123": {"views": 100, "likes": 10, "comments": 5}}
    assert availability_from_batch("abc123", stats_map) == "available"


def test_unavailable_when_video_id_missing_from_non_empty_stats_map():
    stats_map = {"other_video": {"views": 50, "likes": 2, "comments": 0}}
    assert availability_from_batch("abc123", stats_map) == "unavailable"


def test_available_does_not_depend_on_other_ids():
    stats_map = {"abc123": {"views": 1}, "xyz": {"views": 2}}
    assert availability_from_batch("abc123", stats_map) == "available"
    assert availability_from_batch("xyz", stats_map) == "available"


def test_unavailable_when_only_other_ids_present():
    stats_map = {"xyz": {"views": 99}}
    assert availability_from_batch("abc123", stats_map) == "unavailable"
