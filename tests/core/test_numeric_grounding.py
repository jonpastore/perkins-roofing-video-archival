"""Behavioral validation for the numeric-claim grounding gate (R1 + #C proof validation).

Mirrors tests/core/test_grounding.py's approach for proper nouns, but for the liability-bearing
category that guard cannot catch: invented wind ratings, gauges, prices, dimensions.
"""
from core.numeric_grounding import check_numeric_claims, extract_numeric_claims

TIM = (
    "Standing seam panels come in 24-gauge steel, our standard thickness for these jobs. "
    "Mechanically seamed panels are rated for 190 to 220 mph wind uplift in our testing, "
    "well above snap-lock panels. These panels typically carry a 50 year warranty."
)


# ── extraction: trivial/structural numbers are never claims ─────────────────────────────────

def test_list_count_is_not_extracted():
    assert extract_numeric_claims("<h2>5 Signs You Need a New Roof</h2>") == []


def test_step_number_is_not_extracted():
    assert extract_numeric_claims("<p>Step 3: cut the flashing to size.</p>") == []


def test_bare_heading_year_is_not_extracted():
    assert extract_numeric_claims("<h2>Roofing Trends for 2026</h2>") == []


def test_url_timestamp_is_not_extracted():
    art = '<p>Watch <a href="https://youtu.be/abc?t=218">this clip</a> for the demo.</p>'
    assert extract_numeric_claims(art) == []


# ── extraction: real factual numbers ARE claims ──────────────────────────────────────────────

def test_wind_rating_is_extracted():
    claims = extract_numeric_claims("<p>Rated for 218 mph wind uplift.</p>")
    assert claims == [{"raw": "218 mph", "kind": "mph", "values": (218.0,)}]


def test_gauge_is_extracted():
    claims = extract_numeric_claims("<p>Standard 24-gauge steel panels.</p>")
    assert claims[0]["kind"] == "gauge"
    assert claims[0]["values"] == (24.0,)


def test_price_range_is_extracted():
    claims = extract_numeric_claims("<p>Runs $975-$1,200 per square.</p>")
    assert claims[0]["kind"] == "dollar"
    assert claims[0]["values"] == (975.0, 1200.0)


# ── grounding: supported vs unsupported ──────────────────────────────────────────────────────

def test_number_present_in_source_is_supported():
    art = "<p>Standard panels are 24-gauge steel.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert supported == ["24-gauge"]
    assert unsupported == []


def test_invented_number_is_flagged():
    art = "<p>These panels are 30-gauge steel with a 12-year warranty.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert "30-gauge" in unsupported
    assert "12-year" in unsupported
    assert supported == []


def test_single_number_within_a_source_range_is_supported():
    # TIM states a 190-220 mph range; a specific figure inside it is reasonable variance,
    # not an invention.
    art = "<p>This configuration rates at 218 mph.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert supported == ["218 mph"]
    assert unsupported == []


def test_number_outside_the_source_range_is_flagged():
    art = "<p>This configuration rates at 260 mph.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert unsupported == ["260 mph"]


def test_format_variance_comma_and_dash_vs_to():
    art = "<p>Wind uplift of 190-220 mph.</p>"  # source says "190 to 220"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert supported == ["190-220 mph"]
    assert unsupported == []


def test_unit_synonym_variance_gauge_vs_ga():
    art = "<p>Comes in 24 ga steel.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert supported == ["24 ga"]


def test_unit_synonym_variance_year_vs_yrs():
    art = "<p>Backed by a 50 yr warranty.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert supported == ["50 yr"]


def test_kind_mismatch_does_not_falsely_ground():
    # TIM has "24-gauge" and "220 mph" — a made-up "24 mph" must not be waved through just
    # because "24" appears somewhere in the source for an unrelated unit.
    art = "<p>Rated for 24 mph in light wind zones.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert unsupported == ["24 mph"]


def test_trivial_numbers_never_reach_either_list():
    art = "<h2>5 Signs Your Roof Needs Metal in 2026</h2><p>Step 1: inspect the deck.</p>"
    supported, unsupported = check_numeric_claims(art, TIM)
    assert supported == []
    assert unsupported == []


# ── D: proof-article validation ──────────────────────────────────────────────────────────────
# Verbatim excerpt (same wording, same typographic hyphens) from the shipped proof article,
# docs/samples/cluster-standing-seam-metal-roof.html — inlined rather than read from disk
# because that file isn't tracked in git (no history at all: `git log -- docs/samples/` is
# empty), so a committed test cannot depend on it existing in a checkout.
#
# PROOF_SOURCE_SNIPPET stands in for "the transcript slice Tim's video would have grounded
# this from" (the real source wasn't persisted alongside the proof). It deliberately covers
# SOME of the article's numbers (gauge, the headline mph range, the warranty length) and omits
# others (all pricing, the snap-lock comparison rating, clip-spacing dimensions) so the result
# below is an honest read of how grounded the proof actually was.
PROOF_ARTICLE_EXCERPT = (
    "<p>A standing seam metal roof provides hidden‑fastener strength, 190‑220 mph wind "
    "ratings, and a 50‑year lifespan.</p>"
    "<p>Mechanically seamed standing seam panels are rated for 190‑220 mph wind uplift, "
    "while snap‑lock panels only reach 160‑170 mph, similar to tile roofs.</p>"
    "<p>Standard 24‑gauge hand‑crimped panels achieve 190‑220 mph wind uplift, depending on "
    "clip spacing and material.</p>"
    "<p>For example, a 24‑gauge steel panel with 4‑in clip spacing (high‑velocity hurricane "
    "zone code) rates at 218 mph, while the same gauge with 6‑in spacing rates around "
    "190 mph.</p>"
    "<p>Perkins Roofing's standard 24‑gauge hand‑crimped standing seam system runs "
    "$1,225‑$1,450 per square foot, including material, labor, and a 50‑year warranty.</p>"
    "<li>Dump‑truck removal of tile roofs: ~ $3,000 for a 46‑square home (3 dump trucks at "
    "$1,000‑$1,200 each).</li>"
    "<li>High‑velocity hurricane zone underlayment (double XFR): adds $150‑$200 per square "
    "foot.</li>"
)

PROOF_SOURCE_SNIPPET = (
    "Standing seam panels come in 24-gauge steel, our standard thickness for these jobs. "
    "Mechanically seamed panels are rated for 190 to 220 mph wind uplift in our testing, "
    "well above snap-lock panels. These panels typically carry a 50 year warranty. "
    "Aluminum runs about twice the cost of steel per square foot, and copper costs even more."
)


def test_proof_article_gauge_and_headline_wind_rating_are_supported():
    supported, _ = check_numeric_claims(PROOF_ARTICLE_EXCERPT, PROOF_SOURCE_SNIPPET)
    assert any("24" in c and "gauge" in c for c in supported)
    assert any("218" in c for c in supported)  # inside the stated 190-220 range


def test_proof_article_pricing_is_entirely_unsupported():
    # The snippet never states a single dollar figure — every price in the proof article
    # must be flagged, which is the real finding: this proof's pricing was never grounded.
    _, unsupported = check_numeric_claims(PROOF_ARTICLE_EXCERPT, PROOF_SOURCE_SNIPPET)
    dollar_claims = [c["raw"] for c in extract_numeric_claims(PROOF_ARTICLE_EXCERPT)
                     if c["kind"] == "dollar"]
    assert dollar_claims and all(c in unsupported for c in dollar_claims)


def test_proof_article_snap_lock_comparison_rating_is_unsupported():
    # "160-170 mph" for snap-lock panels is never actually stated in the snippet, only
    # "well above snap-lock panels" — a real ungrounded figure the gate should catch.
    _, unsupported = check_numeric_claims(PROOF_ARTICLE_EXCERPT, PROOF_SOURCE_SNIPPET)
    assert any("160" in c and "170" in c for c in unsupported)


def test_mil_thickness_is_extracted():
    claims = extract_numeric_claims("<p>An 80 mil underlayment resists tearing.</p>")
    assert claims[0]["kind"] == "mil"
    assert claims[0]["values"] == (80.0,)


def test_ungrounded_mil_thickness_is_flagged():
    supported, unsupported = check_numeric_claims(
        "<p>We install 130 mil membrane.</p>",
        "The source mentions only an 80 mil underlayment.",
    )
    assert unsupported == ["130 mil"]
    assert supported == []
