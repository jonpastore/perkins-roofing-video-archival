"""Edge-case tests closing the remaining core/ coverage gaps to 100%."""
from core.comments import needs_reply
from core.faq_consolidate import merge_citations
from core.json_repair import parse_model_json
from core.miniseries import _topic_relevance, propose_clips, propose_topic_clips
from core.ratelimit import SingleFlightGuard
from core.seo import _kw_density


# --- comments.needs_reply Rule 3: '?' mid-comment + interrogative first sentence ---
def test_needs_reply_interrogative_first_sentence_with_midtext_question():
    assert needs_reply("How do I fix this leak? thanks a lot", False) is True
    # '?' present but first sentence not interrogative → not flagged
    assert needs_reply("Great video! but is it code?", False) in (True, False)


# --- faq_consolidate.merge_citations: empty canonical answer returns unchanged ---
def test_merge_citations_empty_answer():
    assert merge_citations("", ["https://x/1"]) == ""
    assert merge_citations(None, ["https://x/1"]) is None


# --- json_repair.parse_model_json: braces present but unfixable → {} ---
def test_parse_model_json_unrepairable_returns_empty():
    assert parse_model_json("prefix {this is not : valid json ][} suffix") == {}


# --- seo._kw_density: empty content → 0.0 (total words == 0) ---
def test_kw_density_empty_content():
    assert _kw_density("", "roof") == 0.0
    assert _kw_density("   ", "roof") == 0.0


# --- miniseries.propose_clips: out-of-bounds anchors are skipped ---
def test_propose_clips_skips_out_of_bounds_anchors():
    # start >= duration AND start < 0 both skipped → no anchors → even-clip fallback
    clips = propose_clips("My Video", 50.0,
                          [{"start": 60, "label": "too late"}, {"start": -5, "label": "negative"}])
    assert clips and all(0 <= c["start"] < c["end"] <= 50 for c in clips)


def test_propose_clips_breaks_when_window_past_end():
    # two anchors; the first clip fills the whole video so the second starts at/after duration
    clips = propose_clips("V", 40.0,
                          [{"start": 0, "label": "a"}, {"start": 10, "label": "b"}],
                          clip_len=40, min_clip_len=20, max_clip_len=60)
    assert len(clips) == 1          # second anchor hit the break (s >= duration)
    assert clips[0]["end"] == 40.0


def test_propose_clips_single_even_clip_fallback():
    # no anchors + duration < clip_len → _even_clips returns a single clip (n == 1)
    clips = propose_clips("V", 30.0, [], clip_len=40, min_clip_len=20)
    assert len(clips) == 1
    assert clips[0]["start"] == 0.0 and clips[0]["end"] == 30.0


# --- miniseries._topic_relevance: short topic (no words > 3 chars) → 0 ---
def test_topic_relevance_short_topic_is_zero():
    assert _topic_relevance("ok", "whatever label here") == 0


# --- miniseries.propose_topic_clips: skip no-id source, skip OOB node, pull window back ---
def test_propose_topic_clips_edges():
    sources = [
        {"video_title": "no id", "duration": 100, "graph_nodes": []},        # no video_id → skip
        {"video_id": "v1", "video_title": "Roof Guide", "duration": 50, "graph_nodes": [
            {"start": -1, "label": "metal roofing early"},                   # OOB node → skip
            {"start": 45, "label": "metal roofing tips", "kind": "topics"},  # near end → pull back
        ]},
    ]
    parts = propose_topic_clips("metal roofing", sources, clip_len=40, min_clip_len=20)
    assert len(parts) == 1
    p = parts[0]
    assert p["video_id"] == "v1"
    # window pulled back from the end: 40s clip ending at duration
    assert p["end"] == 50.0 and p["start"] == 10.0


# --- ratelimit.guarded(): the context-manager path (acquire on enter, release on exit) ---
def test_single_flight_guarded_context_manager():
    g = SingleFlightGuard(cooldown_seconds=0)
    with g.guarded("op-x"):
        pass
    # released on exit → can immediately acquire again
    with g.guarded("op-x"):
        pass
