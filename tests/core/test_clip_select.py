"""Tests for core/clip_select.py — 100% line coverage required."""
import json

from core.clip_select import (
    build_title_prompt,
    build_viral_prompt,
    generate_titles,
    parse_title_output,
    parse_viral,
    rank_moments,
    score_segments,
)

# ---------------------------------------------------------------------------
# build_viral_prompt
# ---------------------------------------------------------------------------


def test_build_viral_prompt_empty_segments():
    prompt = build_viral_prompt([])
    assert "[]" in prompt
    assert "Hook" in prompt


def test_build_viral_prompt_includes_segment_text():
    segs = [{"start": 0.0, "end": 30.0, "text": "Metal roofs last 50 years"}]
    prompt = build_viral_prompt(segs)
    assert "Metal roofs last 50 years" in prompt
    assert "0.00s" in prompt
    assert "30.00s" in prompt


def test_build_viral_prompt_multiple_segments():
    segs = [
        {"start": 0.0, "end": 20.0, "text": "Citizens Insurance renewal"},
        {"start": 20.0, "end": 45.0, "text": "Wind mitigation discount"},
    ]
    prompt = build_viral_prompt(segs)
    assert "[0]" in prompt
    assert "[1]" in prompt
    assert "Citizens Insurance renewal" in prompt
    assert "Wind mitigation discount" in prompt


def test_build_viral_prompt_rubric_present():
    prompt = build_viral_prompt([{"start": 0.0, "end": 10.0, "text": "test"}])
    for dimension in ("Hook", "Flow", "Value", "Trend"):
        assert dimension in prompt


def test_build_viral_prompt_missing_text_key():
    segs = [{"start": 5.0, "end": 35.0}]
    prompt = build_viral_prompt(segs)
    # Should not raise; text defaults to empty string
    assert "5.00s" in prompt


# ---------------------------------------------------------------------------
# parse_viral — valid JSON
# ---------------------------------------------------------------------------


def test_parse_viral_valid():
    raw = json.dumps([
        {"start": 0.0, "end": 30.0, "score": 85, "reason": "Strong hook"},
        {"start": 30.0, "end": 60.0, "score": 70, "reason": "Good value"},
    ])
    result = parse_viral(raw)
    assert len(result) == 2
    assert result[0]["score"] == 85
    assert result[1]["reason"] == "Good value"


def test_parse_viral_fenced_json():
    raw = '```json\n[{"start": 10.0, "end": 40.0, "score": 90, "reason": "Top hook"}]\n```'
    result = parse_viral(raw)
    assert len(result) == 1
    assert result[0]["score"] == 90


def test_parse_viral_score_clamped_to_99():
    raw = json.dumps([{"start": 0.0, "end": 10.0, "score": 120, "reason": "Over"}])
    result = parse_viral(raw)
    assert result[0]["score"] == 99


def test_parse_viral_score_clamped_to_0():
    raw = json.dumps([{"start": 0.0, "end": 10.0, "score": -5, "reason": "Under"}])
    result = parse_viral(raw)
    assert result[0]["score"] == 0


def test_parse_viral_drops_end_lte_start():
    raw = json.dumps([
        {"start": 10.0, "end": 5.0, "score": 80, "reason": "backwards"},
        {"start": 5.0, "end": 5.0, "score": 80, "reason": "zero-length"},
        {"start": 0.0, "end": 30.0, "score": 70, "reason": "valid"},
    ])
    result = parse_viral(raw)
    assert len(result) == 1
    assert result[0]["reason"] == "valid"


def test_parse_viral_drops_malformed_items():
    raw = json.dumps([
        "not a dict",
        {"start": "bad", "end": "also bad", "score": "X", "reason": ""},
        {"start": 0.0, "end": 20.0, "score": 55, "reason": "ok"},
    ])
    result = parse_viral(raw)
    assert len(result) == 1
    assert result[0]["score"] == 55


# ---------------------------------------------------------------------------
# parse_viral — garbage / edge cases
# ---------------------------------------------------------------------------


def test_parse_viral_empty_string():
    assert parse_viral("") == []


def test_parse_viral_none():
    assert parse_viral(None) == []


def test_parse_viral_garbage_text():
    assert parse_viral("This is definitely not JSON at all!!!") == []


def test_parse_viral_empty_array():
    assert parse_viral("[]") == []


def test_parse_viral_dict_with_moments_wrapper():
    raw = json.dumps({"moments": [{"start": 0.0, "end": 20.0, "score": 77, "reason": "ok"}]})
    result = parse_viral(raw)
    assert len(result) == 1
    assert result[0]["score"] == 77


def test_parse_viral_dict_with_clips_wrapper():
    raw = json.dumps({"clips": [{"start": 5.0, "end": 25.0, "score": 60, "reason": "clips"}]})
    result = parse_viral(raw)
    assert result[0]["score"] == 60


def test_parse_viral_dict_no_known_wrapper():
    raw = json.dumps({"unknown_key": "nothing useful"})
    assert parse_viral(raw) == []


def test_parse_viral_bare_string_value():
    # parse_model_json on a bare JSON string (e.g. '"hello"') returns {} because
    # it finds no { or [ — but if it somehow yields a non-dict non-list (e.g. int),
    # the not-isinstance-list guard fires.  Patch parse_model_json to return an int.
    from unittest.mock import patch

    import core.clip_select as cs
    with patch.object(cs, "parse_model_json", return_value=42):
        assert cs.parse_viral("irrelevant") == []


def test_parse_viral_trailing_comma():
    # parse_model_json already handles trailing commas
    raw = '[{"start": 0.0, "end": 30.0, "score": 50, "reason": "ok"},]'
    result = parse_viral(raw)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# rank_moments
# ---------------------------------------------------------------------------


def test_rank_moments_sorts_by_score_desc():
    moments = [
        {"start": 0.0, "end": 10.0, "score": 40, "reason": "low"},
        {"start": 10.0, "end": 20.0, "score": 90, "reason": "high"},
        {"start": 20.0, "end": 30.0, "score": 65, "reason": "mid"},
    ]
    result = rank_moments(moments, top_n=3)
    assert [m["score"] for m in result] == [90, 65, 40]


def test_rank_moments_top_n():
    moments = [{"start": float(i), "end": float(i + 10), "score": i, "reason": ""} for i in range(10)]
    result = rank_moments(moments, top_n=3)
    assert len(result) == 3
    assert result[0]["score"] == 9


def test_rank_moments_min_score_filter():
    moments = [
        {"start": 0.0, "end": 10.0, "score": 30, "reason": ""},
        {"start": 10.0, "end": 20.0, "score": 70, "reason": ""},
    ]
    result = rank_moments(moments, top_n=5, min_score=50)
    assert len(result) == 1
    assert result[0]["score"] == 70


def test_rank_moments_all_below_min_score():
    moments = [{"start": 0.0, "end": 10.0, "score": 20, "reason": ""}]
    assert rank_moments(moments, top_n=5, min_score=50) == []


def test_rank_moments_empty():
    assert rank_moments([], top_n=5) == []


def test_rank_moments_top_n_zero():
    moments = [{"start": 0.0, "end": 10.0, "score": 80, "reason": ""}]
    assert rank_moments(moments, top_n=0) == []


def test_rank_moments_does_not_mutate_input():
    moments = [
        {"start": 0.0, "end": 10.0, "score": 50, "reason": ""},
        {"start": 10.0, "end": 20.0, "score": 80, "reason": ""},
    ]
    original_order = [m["score"] for m in moments]
    rank_moments(moments, top_n=2)
    assert [m["score"] for m in moments] == original_order


# ---------------------------------------------------------------------------
# score_segments
# ---------------------------------------------------------------------------


def test_score_segments_no_score_fn_returns_empty():
    segs = [{"start": 0.0, "end": 30.0, "text": "test"}]
    result = score_segments(segs)
    assert result == []


def test_score_segments_calls_score_fn_with_prompt():
    captured = {}

    def fake_score_fn(prompt):
        captured["prompt"] = prompt
        return json.dumps([{"start": 0.0, "end": 30.0, "score": 80, "reason": "good"}])

    segs = [{"start": 0.0, "end": 30.0, "text": "Florida roofing tip"}]
    result = score_segments(segs, score_fn=fake_score_fn)
    assert len(result) == 1
    assert result[0]["score"] == 80
    assert "Florida roofing tip" in captured["prompt"]


def test_score_segments_returns_ranked():
    def fake_score_fn(prompt):
        return json.dumps([
            {"start": 0.0, "end": 30.0, "score": 40, "reason": "low"},
            {"start": 30.0, "end": 60.0, "score": 90, "reason": "high"},
        ])

    result = score_segments([], score_fn=fake_score_fn)
    assert result[0]["score"] == 90


def test_score_segments_score_fn_returns_garbage():
    result = score_segments(
        [{"start": 0.0, "end": 10.0, "text": "test"}],
        score_fn=lambda p: "not json",
    )
    assert result == []


# ---------------------------------------------------------------------------
# generate_titles — A4 stub
# ---------------------------------------------------------------------------


def test_generate_titles_no_gen_fn_returns_empty():
    # Pure/testable default, same contract as score_segments(score_fn=None).
    assert generate_titles({"title": "Valley Repair"}) == {}


def test_generate_titles_parses_all_platforms():
    raw = ('{"title": "Roof Valley Done Right", "hashtags": ["MiamiRoofing", "#Tile"],'
           ' "description": "How we hem valley metal."}')
    out = generate_titles({"title": "Valley", "text": "hem the valley metal"}, gen_fn=lambda p: raw)
    assert set(out) == {"youtube", "tiktok", "instagram"}
    yt = out["youtube"]
    assert yt["title"] == "Roof Valley Done Right"
    # Bare tags get a leading '#'; existing '#' preserved.
    assert yt["hashtags"] == ["#MiamiRoofing", "#Tile"]
    assert yt["description"] == "How we hem valley metal."


def test_generate_titles_omits_unparseable_platform():
    responses = iter(['{"title": "Good", "hashtags": [], "description": ""}', "garbage", '{"title": ""}'])
    out = generate_titles({"title": "x"}, gen_fn=lambda p: next(responses))
    assert list(out) == ["youtube"]  # tiktok garbage + instagram empty-title both dropped


def test_build_title_prompt_uses_josh_override():
    prompt = build_title_prompt(
        {"title": "Valley", "text": "transcript here"},
        "tiktok",
        prompts={"tiktok": "JOSH SAYS: {title} // {text}"},
    )
    assert prompt == "JOSH SAYS: Valley // transcript here"


def test_build_title_prompt_default_mentions_platform_and_core_tags():
    prompt = build_title_prompt({"title": "Valley", "text": "t"}, "instagram")
    assert "instagram" in prompt
    assert "#PerkinsRoofing" in prompt


def test_parse_title_output_handles_fenced_json_and_str_hashtags():
    raw = '```json\n{"title": "T", "hashtags": "#a #b", "description": "d"}\n```'
    parsed = parse_title_output(raw)
    assert parsed == {"title": "T", "hashtags": ["#a", "#b"], "description": "d"}


def test_parse_title_output_rejects_junk():
    assert parse_title_output(None) is None
    assert parse_title_output("not json at all") is None
    assert parse_title_output('["a", "list"]') is None  # non-dict top level
    assert parse_title_output('{"hashtags": ["#x"]}') is None  # no title
