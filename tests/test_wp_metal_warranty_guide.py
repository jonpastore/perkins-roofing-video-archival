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
    for row in GUIDE["panel_types"]:
        for key in row:
            assert f"$t['{key}']" in src, f"guide.json panel_types.{key} is never read by the renderer"


def test_every_field_the_renderer_reads_is_provided(src):
    """Reverse direction: the renderer asking for a key the data does not have. PHP's `??` and
    array access yield null, which prints as an empty cell — a blank column, not an error."""
    import re
    for key in set(re.findall(r"\$u\['(\w+)'\]", src)):
        assert all(key in row for row in GUIDE["uplift"]), f"renderer reads uplift.{key}; some rows lack it"
    for key in set(re.findall(r"\$t\['(\w+)'\]", src)):
        assert all(key in row for row in GUIDE["panel_types"]), \
            f"renderer reads panel_types.{key}; some rows lack it"
    for key in set(re.findall(r"\$c\['(\w+)'\]", src)):
        assert all(key in row for row in GUIDE["clip_spacing"]), \
            f"renderer reads clip_spacing.{key}; some rows lack it"
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
    licensed roofer's site is the liability `core.grounding` exists to prevent.

    Attribution must NOT name a person or an internal document: `_sources.uplift` renders verbatim
    on the public page (perkins-metal-warranty.php:256). It briefly carried a staff member's name,
    the title and date of an internal proposal, and Perkins' per-square upgrade price.
    """
    src = GUIDE["_sources"]["uplift"]
    assert "MANUFACTURER" in src
    assert "reference sheet" in src.lower()
    assert "corroborated" in src.lower()
    assert "670QE0CZQGE" in GUIDE["_sources"]["panel_types"]
    for row in GUIDE["uplift"]:
        assert row["psf"] > 0
    for row in GUIDE["panel_types"]:
        assert row["psf"] > 0 and row["mph"] > 0


def test_no_internal_pricing_or_named_documents_reach_the_public_page():
    """Everything in guide.json that the shortcode renders is customer-facing by definition.

    Guards the leak directly: an internal per-square upcharge and a pointer to one identifiable
    customer's proposal shipped to a marketing page as part of a provenance note.
    """
    import json as _json
    rendered = _json.dumps({k: v for k, v in GUIDE.items() if not k.startswith("_note")})
    for leak in ("per SQ", "Kanak", "Metal and Flat Re-Roof", "$45"):
        assert leak not in rendered, f"internal detail on a public page: {leak!r}"


def test_snap_lock_is_the_weakest_row():
    """The point of the table. If an edit ever makes snap lock the strongest panel, the page is
    telling homeowners the opposite of what Tim demonstrates on camera."""
    snap = [r for r in GUIDE["panel_types"] if "snap lock" in r["panel"].lower()]
    seamed = [r for r in GUIDE["panel_types"] if "seamed" in r["panel"].lower()]
    assert snap and seamed
    assert max(r["psf"] for r in snap) < min(r["psf"] for r in seamed)


def test_the_most_clips_is_not_the_highest_rating():
    """The page's whole claim (Josh's sheet): strength is the tested assembly, not the clip count.

    If an edit ever leaves the densest clip pattern also holding the highest tested pressure, the
    page argues against itself while every table still renders.
    """
    rows = [r for r in GUIDE["uplift"] if r.get("clips_per_20ft")]
    assert len(rows) >= 2, "need at least two clip-count rows to make the comparison"
    most_clips = max(rows, key=lambda r: r["clips_per_20ft"])
    strongest = max(GUIDE["uplift"], key=lambda r: r["psf"])
    assert most_clips is not strongest, (
        "the assembly with the most clips is also the strongest — that is the opposite of the "
        "thesis this section states")
    assert strongest.get("specified"), "Perkins should specify the highest tested assembly"


def test_clip_spacing_arithmetic_holds():
    """20 ft of panel at N inches on centre. A transcription slip here is a number a customer can
    check with a tape measure."""
    for row in GUIDE["clip_spacing"]:
        inches = float(row["spacing"].split()[0])
        assert row["clips_per_20ft"] == round(240 / inches), row
    # And the per-system rows must agree with that same table, not carry a second set of numbers.
    by_spacing = {r["spacing"]: r["clips_per_20ft"] for r in GUIDE["clip_spacing"]}
    for u in GUIDE["uplift"]:
        if u.get("clips_per_20ft"):
            key = u["attachment"].replace(" clips", "")
            assert by_spacing.get(key) == u["clips_per_20ft"], \
                f"{u['manufacturer']} says {u['clips_per_20ft']} clips at {key}; the table disagrees"


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


def test_day_cells_invalidate_the_quote_when_edited():
    """A day-cell edit must mark the quote stale. Source-level check, in pytest for the same
    reason the PHP brace check above is: the SPA has no DOM harness (no jsdom, no
    testing-library) and adding one for a two-line invariant is not worth a dependency.

    `quoteBodyKey` deliberately excludes `daily_series` so the day-suggestion pre-fill cannot
    mark its OWN fresh quote stale. That removed the only path by which typing in a day cell
    reached `setInputsDirty` — so an operator could type 6 days over a suggested 3, press
    "Create proposal" (which snapshots the previous response rather than re-quoting) and ship a
    document priced at 3. The edit is the entire feature Tim asked for; it has to invalidate.
    """
    src = (PLUGIN_DIR.parent.parent / "web" / "src" / "pages" / "Quoting.tsx").read_text()
    for setter in ("setQuoteDemoDays", "setQuoteInstallDays"):
        handler = next((ln for ln in src.splitlines()
                        if "onChange={(e) =>" in ln and f"{setter}(e.target.value)" in ln), None)
        assert handler, f"no onChange handler found for {setter}"
        assert "setInputsDirty(true)" in handler, f"{setter} edit does not mark the quote dirty"


def test_the_plugin_declares_one_version_twice_and_they_agree(src):
    """The header `Version:` and PERKINS_MWC_VERSION are two literals for one fact.

    WordPress reads the HEADER (it parses the file as text, so the constant is invisible to it)
    for the plugin list and update checks, while the CONSTANT is what `?ver=` cache-busts the
    assets with. Bumping only the constant ships new geometry that browsers do fetch — the
    cache-bust works — under a plugin row still reporting the old version, so the admin screen
    says the deploy did not happen while the site behaves as though it did.

    Caught on 2026-08-07 verifying the NHD deploy: assets served `?ver=1.6.0` against a plugin
    list showing 1.5.1. Nothing was broken; nothing agreed either.
    """
    import re

    header = re.search(r"^ \* Version:\s+([0-9.]+)", src, re.MULTILINE)
    const = re.search(r"define\(\s*'PERKINS_MWC_VERSION',\s*'([0-9.]+)'\s*\)", src)
    assert header, "no `Version:` line in the plugin header — WordPress needs it"
    assert const, "no PERKINS_MWC_VERSION define — the asset cache-bust needs it"
    assert header.group(1) == const.group(1), (
        f"plugin header says {header.group(1)}, PERKINS_MWC_VERSION says {const.group(1)} — "
        f"bump both or the admin screen and the served assets disagree")
