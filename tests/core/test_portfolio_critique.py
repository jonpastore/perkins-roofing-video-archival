"""The adversarial critics for a project page.

Pure prompt/parse logic, so the tests assert the CONTRACT (lenses exist, inputs reach the
prompt, malformed critics fail closed) rather than an LLM's judgement.
"""
import pytest

from core.portfolio_critique import CRITICS, blocking, critique_prompt, merge, parse_findings

PAGE = {
    "title": "Miami Beach Olsen Condo",
    "city": "Miami Beach",
    "meta": "A commercial roofing project in Miami Beach, Florida.",
    "content_html": "<p>Perkins Roofing completed a tile re-roof.</p>",
    "scope_lines": ['13" Concrete Tile Re-Roof', "Sika RoofPro System"],
    "alt_texts": ["Olsen Condo roof, view 1"],
}


def test_the_three_lenses_are_distinct_and_privacy_leads():
    assert set(CRITICS) == {"privacy", "grounding", "reader"}
    assert list(CRITICS)[0] == "privacy", "privacy is the highest-stakes review"
    # Each lens must own different failure modes, or they are redundant skeptics.
    assert "street address" in CRITICS["privacy"]
    assert "street address" not in CRITICS["grounding"]
    assert "not supported" in CRITICS["grounding"] or "not in the record" in CRITICS["grounding"]


def test_an_unknown_lens_is_rejected_loudly():
    with pytest.raises(ValueError, match="unknown critic lens"):
        critique_prompt("seo", PAGE)


@pytest.mark.parametrize("lens", sorted(CRITICS))
def test_every_lens_receives_the_scope_and_the_alt_text(lens):
    """Alt text is passed separately because it publishes and a reader never sees it — it is
    where an address or unit number hides from everyone but a crawler."""
    prompt = critique_prompt(lens, PAGE)
    assert '13" Concrete Tile Re-Roof' in prompt
    assert "Olsen Condo roof, view 1" in prompt
    assert "Miami Beach" in prompt
    assert '{"findings"' in prompt


def test_missing_scope_is_stated_not_omitted():
    """A grounding critic must know the scope was EMPTY, not just not see one."""
    prompt = critique_prompt("grounding", {**PAGE, "scope_lines": []})
    assert "(none matched)" in prompt


def test_privacy_lens_names_indirect_identifiers():
    """The deterministic gate catches "1424 Willow Rd"; only a reader catches "the corner unit
    above the tennis courts"."""
    assert "corner unit" in CRITICS["privacy"]
    assert "INDIRECT" in CRITICS["privacy"]


def test_privacy_lens_explicitly_allows_city_and_building_names():
    """Without this the critic would flag every legitimate page."""
    text = CRITICS["privacy"]
    assert "Do NOT flag" in text
    assert "neighbourhood" in text and "condo/association/building name" in text


def test_malformed_critic_output_fails_closed():
    assert parse_findings(None) == []
    assert parse_findings({"findings": ["nope", {"severity": "huge", "issue": "x"}]}) == []
    assert parse_findings({"findings": [{"severity": "blocker", "issue": ""}]}) == []


def test_valid_findings_survive_parsing():
    out = parse_findings({"findings": [
        {"severity": "blocker", "issue": "unit number in alt", "fix": "remove it"},
        {"severity": "minor", "issue": "repetitive", "fix": "trim"},
    ]})
    assert [f["severity"] for f in out] == ["blocker", "minor"]
    assert blocking(out) == [out[0]]


def test_merge_puts_blockers_first_and_tags_the_lens():
    merged = merge({
        "reader": [{"severity": "minor", "issue": "filler"}],
        "privacy": [{"severity": "blocker", "issue": "street address in caption"}],
        "grounding": [{"severity": "major", "issue": "invented square footage"}],
    })
    assert [f["severity"] for f in merged] == ["blocker", "major", "minor"]
    assert merged[0]["lens"] == "privacy"


def test_merge_of_nothing_is_empty():
    assert merge({}) == []
