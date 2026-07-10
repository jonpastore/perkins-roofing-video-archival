"""Tests for core/hook_overlay.py — 100% coverage required."""
import pytest

from core.hook_overlay import escape_drawtext, hook_drawtext_filter


# ---------------------------------------------------------------------------
# escape_drawtext
# ---------------------------------------------------------------------------

def test_escape_drawtext_plain_text():
    assert escape_drawtext("Hello World") == "Hello World"


def test_escape_drawtext_apostrophe():
    result = escape_drawtext("Tim's Roofing")
    assert "'" not in result.replace("'\\''", "")
    assert "'\\''s" in result


def test_escape_drawtext_colon():
    result = escape_drawtext("Cost: $500")
    assert "\\:" in result


def test_escape_drawtext_percent():
    result = escape_drawtext("Save 20%")
    assert "%%" in result


def test_escape_drawtext_backslash():
    result = escape_drawtext("C:\\path")
    assert "\\\\" in result


def test_escape_drawtext_multiple_specials():
    result = escape_drawtext("Tim's: 50%")
    assert "\\:" in result
    assert "%%" in result
    assert "'\\''s" in result


def test_escape_drawtext_empty_string():
    assert escape_drawtext("") == ""


def test_escape_drawtext_backslash_then_colon():
    # Backslash must be escaped before colon so we don't double-escape
    result = escape_drawtext("a\\:b")
    # The backslash becomes \\ then the colon becomes \:
    assert "\\\\" in result
    assert "\\:" in result


def test_escape_drawtext_no_specials():
    text = "Roof Replacement Services"
    assert escape_drawtext(text) == text


# ---------------------------------------------------------------------------
# hook_drawtext_filter
# ---------------------------------------------------------------------------

def test_hook_filter_contains_drawtext_prefix():
    f = hook_drawtext_filter("Roof leak fixed!")
    assert f.startswith("drawtext=")


def test_hook_filter_contains_text():
    f = hook_drawtext_filter("Hurricane prep tips")
    assert "Hurricane prep tips" in f


def test_hook_filter_contains_enable_expression():
    f = hook_drawtext_filter("test", duration=2.5)
    assert "between(t,0," in f
    assert "2.500000" in f


def test_hook_filter_expansion_none():
    f = hook_drawtext_filter("test")
    assert "expansion=none" in f


def test_hook_filter_centered_horizontally():
    f = hook_drawtext_filter("test")
    assert "x=(w-text_w)/2" in f


def test_hook_filter_box_enabled():
    f = hook_drawtext_filter("test")
    assert "box=1" in f


def test_hook_filter_default_brand_color():
    f = hook_drawtext_filter("test")
    assert "0xCC2222" in f


def test_hook_filter_custom_brand_color():
    f = hook_drawtext_filter("test", brand_color="0x0000FF")
    assert "0x0000FF" in f


def test_hook_filter_custom_duration():
    f = hook_drawtext_filter("test", duration=1.0)
    assert "1.000000" in f


def test_hook_filter_custom_fontsize():
    f = hook_drawtext_filter("test", fontsize=72)
    assert "fontsize=72" in f


def test_hook_filter_custom_y_expr():
    f = hook_drawtext_filter("test", y_expr="h/2")
    assert "y=h/2" in f


def test_hook_filter_custom_box_color():
    f = hook_drawtext_filter("test", box_color="red@0.5")
    assert "red@0.5" in f


def test_hook_filter_custom_box_border():
    f = hook_drawtext_filter("test", box_border=24)
    assert "boxborderw=24" in f


def test_hook_filter_escapes_apostrophe_in_hook_text():
    f = hook_drawtext_filter("Tim's tip")
    assert "'\\''s" in f


def test_hook_filter_escapes_colon_in_hook_text():
    f = hook_drawtext_filter("Step 1: check")
    assert "\\:" in f


def test_hook_filter_raises_on_empty_text():
    with pytest.raises(ValueError, match="hook_text must not be empty"):
        hook_drawtext_filter("")


def test_hook_filter_raises_on_whitespace_only():
    with pytest.raises(ValueError, match="hook_text must not be empty"):
        hook_drawtext_filter("   ")


def test_hook_filter_strips_leading_trailing_whitespace():
    f = hook_drawtext_filter("  test  ")
    assert "test" in f
    # the surrounding spaces should not appear in the text value
    assert "  test  " not in f
