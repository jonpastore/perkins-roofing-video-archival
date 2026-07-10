from core.graph import build_extract_prompt, parse_nodes, secs


def test_secs_parses_mmss():
    assert secs("02:30") == 150
    assert secs("0:5") == 5


def test_secs_malformed_returns_none():
    # Bad/missing timecodes now return None so callers can distinguish from a real start=0
    assert secs("garbage") is None
    assert secs("") is None


def test_build_extract_prompt_formats_timecodes_and_truncates():
    segs = [{"text": "intro", "start": 5}, {"text": "later", "start": 125}]
    p = build_extract_prompt(segs)
    assert "[00:05] intro" in p
    assert "[02:05] later" in p
    assert "TRANSCRIPT:" in p


def test_build_extract_prompt_caps_transcript_at_9000_chars():
    segs = [{"text": "x" * 20000, "start": 0}]
    p = build_extract_prompt(segs)
    # the transcript body is capped; total prompt = header + <=9000 body chars
    assert "x" * 9001 not in p


def test_parse_nodes_all_kinds():
    g = {
        "topics": [{"label": "flashing", "ts": "01:00"}],
        "claims": [{"detail": "replace it", "ts": "01:10"}],
        "objections": [{"detail": "too costly", "ts": "02:00"}],
        "ctas": [{"detail": "call us", "ts": "03:00"}],
    }
    rows = parse_nodes(g, "v1")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"topics", "claims", "objections", "ctas"}
    topic = next(r for r in rows if r["kind"] == "topics")
    assert topic["label"] == "flashing" and topic["start"] == 60 and topic["version"] == "v1"


def test_parse_nodes_handles_missing_and_none_lists():
    g = {"topics": None}  # None list and absent kinds
    assert parse_nodes(g, "v1") == []


def test_parse_nodes_defaults_missing_fields():
    # A missing/malformed ts now produces start=None (not 0), letting link() omit ?t=
    rows = parse_nodes({"claims": [{}]}, "v2")
    assert rows[0] == {"kind": "claims", "label": "", "detail": "", "start": None, "version": "v2"}
