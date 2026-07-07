"""Regression: make_card must safely embed external (YouTube-title-derived) text in the
ffmpeg drawtext filter — apostrophes must not terminate the quote early, and filtergraph
metacharacters must not inject options. See docs/reviews/2026-07-07-deep-review.md."""
import adapters.ffmpeg as F


def _drawtext(monkeypatch, text):
    captured = {}
    monkeypatch.setattr(F.subprocess, "run", lambda cmd, **kw: captured.setdefault("cmd", cmd))
    F.make_card(text, "/tmp/out.png")
    cmd = captured["cmd"]
    return cmd[cmd.index("-vf") + 1]


def test_apostrophe_uses_shell_escape_sequence(monkeypatch):
    # "Tim's" must become  text='Tim'\''s'  — a plain \' would close the quote early
    vf = _drawtext(monkeypatch, "Tim's Roofing Tips")
    assert "'\\''" in vf
    assert "Tim'\\''s Roofing Tips" in vf
    # options after the text value survive (not swallowed into the string)
    assert ":expansion=none" in vf and ":fontsize=72" in vf


def test_filtergraph_metacharacters_are_contained(monkeypatch):
    # colons/brackets/semicolons/percent are literal inside the single-quoted value,
    # so they can't spawn new drawtext options (injection) or trigger % expansion.
    vf = _drawtext(monkeypatch, "Roof: 50% off [2024]; deal")
    assert vf.startswith("drawtext=text='")
    assert ":expansion=none" in vf   # % expansion disabled
    # the injected ';' / '[' did not create a new filter — value stays single-quoted
    body = vf.split("text='", 1)[1].split("':expansion=none", 1)[0]
    assert "Roof: 50% off [2024]; deal" == body


def test_plain_text_unchanged(monkeypatch):
    vf = _drawtext(monkeypatch, "Metal Roofing")
    assert "text='Metal Roofing':expansion=none" in vf
