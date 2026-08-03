"""The [metal_roof_guide] educational page (#382 [51:10]/[53:01]) and its aluminum video (#402).

WHY THESE TESTS AND NOT A SNAPSHOT. CI has no PHP, so nothing here executes the plugin. What it
CAN do is the check that would have caught this repo's recurring defect: data that is correct and
that nothing reads. Four of the five defects on 2026-08-03 were exactly that shape, and one of
them was a config key with the right value and no accessor anywhere.

So these assert the JOIN between the JSON assets and the renderer, in BOTH directions — a field
the renderer never reads, and a field the renderer reads that the data never provides, fail
differently and both are silent in production (PHP renders a missing key as an empty cell).

The rendered output itself was verified by executing the shortcode against WordPress stubs:
    docker run --rm -v "$PWD/wp-plugin/perkins-metal-warranty:/p:ro" \
        -v "$PWD/wp-plugin/perkins-metal-warranty/tests:/h:ro" \
        php:8.3-cli php /h/render.php metal_roof_guide
Every manufacturer, every uplift figure and every video URL appeared in the HTML. That is a manual
step by necessity, not a gate — do not read its absence from CI as it having been skipped.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "wp-plugin" / "perkins-metal-warranty"
PHP = PLUGIN_DIR / "perkins-metal-warranty.php"
ZONES = json.loads((PLUGIN_DIR / "assets" / "zones.json").read_text())
GUIDE = json.loads((PLUGIN_DIR / "assets" / "guide.json").read_text())


@pytest.fixture(scope="module")
def src() -> str:
    return PHP.read_text()


def test_both_shortcodes_are_registered(src):
    """The tool and the educational page. A shortcode that is defined but never registered
    renders as literal text on the page — visibly wrong, but only once someone looks."""
    assert "add_shortcode( 'metal_warranty_checker', 'perkins_mwc_shortcode' );" in src
    assert "add_shortcode( 'metal_roof_guide', 'perkins_mwc_guide_shortcode' );" in src


def test_every_uplift_field_has_a_reader(src):
    """Forward direction: a field present in guide.json that the renderer never reads."""
    for row in GUIDE["uplift"]:
        for key in row:
            assert f"$u['{key}']" in src, f"guide.json uplift.{key} is never read by the renderer"


def test_every_field_the_renderer_reads_is_provided(src):
    """Reverse direction: the renderer asking for a key the data does not have. PHP's `??` and
    array access yield null, which prints as an empty cell — a blank column, not an error."""
    import re
    for key in set(re.findall(r"\$u\['(\w+)'\]", src)):
        assert all(key in row for row in GUIDE["uplift"]), f"renderer reads uplift.{key}; some rows lack it"
    for key in set(re.findall(r"\$p\['(\w+)'\]", src)):
        assert any(key in prov for m in ZONES["materials"] for prov in m["provisions"]), \
            f"renderer reads provision.{key}; zones.json has no such field"
    for key in set(re.findall(r"\$v\['(\w+)'\]", src)):
        assert all(key in v for v in GUIDE["videos"]), f"renderer reads video.{key}; some videos lack it"


def test_the_guide_renders_warranty_data_from_zones_not_a_copy(src):
    """#382's comparison table must come from the SAME asset the checker reads. A second copy of
    the warranty provisions is how the tool and the page start disagreeing about a manufacturer
    without anyone editing either one."""
    assert "perkins_mwc_asset( 'zones.json' )" in src
    assert "$zones['materials']" in src
    # And no prose duplicate crept into guide.json alongside it.
    assert "materials" not in GUIDE, "warranty provisions duplicated into guide.json"


def test_provision_phrase_uses_the_checkers_own_verdict_classes(src):
    """ok/void/cond are the checker's classes, already styled in checker.css. A parallel palette
    is two things to keep in sync and one of them will drift."""
    assert "'void', sprintf" in src
    assert "'cond', sprintf" in src
    assert "return [ 'ok', 'Covered at any distance' ];" in src


def test_402_aluminum_example_video_is_present():
    """#402 verbatim: 'Add a YouTube video link for the aluminum roof example in the
    metal-roofing section.' The section renders only when a video carries section='aluminum',
    so an id with the wrong section is a link that exists and never appears."""
    aluminum = [v for v in GUIDE["videos"] if v["section"] == "aluminum"]
    assert aluminum, "no aluminum-section video — #402 renders nothing"
    assert any("KIE4gR7Bgo4" in v["url"] for v in aluminum), "the aluminum roof EXAMPLE video is missing"
    for v in aluminum:
        assert v["url"].startswith("https://www.youtube.com/"), v["url"]


def test_every_video_section_is_one_the_renderer_emits(src):
    """A video filed under a section the guide never renders is invisible — the exact failure
    mode of a correct thing nothing can reach."""
    emitted = {"aluminum", "uplift"}
    for v in GUIDE["videos"]:
        assert v["section"] in emitted, f"video {v['id']} is in section {v['section']!r}, which nothing renders"
        assert f"$videos['{v['section']}']" in src


def test_uplift_figures_carry_their_source():
    """These are the MANUFACTURER's published approval numbers. Publishing them unattributed on a
    licensed roofer's site is the liability `core.grounding` exists to prevent."""
    assert "670QE0CZQGE" in GUIDE["_sources"]["uplift"]
    assert "Metal Alliance" in GUIDE["_sources"]["uplift"]
    for row in GUIDE["uplift"]:
        assert row["psf"] > 0 and row["mph"] > 0


def test_snap_lock_is_the_weakest_row():
    """The point of the table. If an edit ever makes snap lock the strongest panel, the page is
    telling homeowners the opposite of what Tim demonstrates on camera."""
    snap = [r for r in GUIDE["uplift"] if "snap lock" in r["panel"].lower()]
    seamed = [r for r in GUIDE["uplift"] if "seamed" in r["panel"].lower()]
    assert snap and seamed
    assert max(r["psf"] for r in snap) < min(r["psf"] for r in seamed)


def test_php_braces_balance(src):
    """A parse error is otherwise invisible until WordPress fatals on load — the same cheap guard
    tests/test_wp_plugin_parity.py puts on the JSON-LD plugin."""
    depth = 0
    for i, ch in enumerate(src):
        depth += (ch == "{") - (ch == "}")
        assert depth >= 0, f"unmatched }} on line {src[:i].count(chr(10)) + 1}"
    assert depth == 0, f"{depth} unclosed {{"


def test_version_was_bumped_for_the_new_shortcode(src):
    """WordPress caches plugin CSS/JS by the version string, so a new shortcode shipped under the
    old version serves the old stylesheet and the guide renders unstyled."""
    header = src.split("*/", 1)[0]
    version = [ln for ln in header.splitlines() if "Version:" in ln][0].split(":")[1].strip()
    assert f"define( 'PERKINS_MWC_VERSION', '{version}' );" in src, "header and define disagree"
    assert version >= "1.4.0", "the guide shipped without a version bump"
