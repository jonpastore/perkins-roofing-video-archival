

def test_build_suggest_prompt_tolerates_null_timestamps():
    """Regression: a segment/node with a null start/end must not 500 the suggest
    endpoint (f"{None:.1f}" TypeError raised before the try/except)."""
    from types import SimpleNamespace

    from api.routes.clips import _build_suggest_prompt

    segs = [SimpleNamespace(start=None, end=None, text="null ts"),
            SimpleNamespace(start=0.0, end=9.0, text="ok")]
    nodes = [SimpleNamespace(start=None, kind="topic", label="x")]
    prompt = _build_suggest_prompt("Title", segs, nodes, 4)
    assert "0.0s" in prompt and "null ts" in prompt
