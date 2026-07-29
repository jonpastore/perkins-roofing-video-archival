"""Scope facts from the Knowify contract record.

Every rule here prevents publishing something false or someone else's on a public page.
"""
from core.portfolio_facts import clean_scope_lines, scope_for_dominant_client, scope_sentence


def _row(desc, client="c1", project="P"):
    return {"client_id": client, "project_name": project, "description": desc}


# --- what may be published -------------------------------------------------

def test_optional_upgrade_lines_are_dropped():
    """Knowify prices upgrades as deliverables on the same contract. They are QUOTES — saying
    a clay tile upgrade was installed when it was only offered is a lie about the property."""
    lines = clean_scope_lines([
        {"description": '13" Concrete Tile Re-Roof'},
        {"description": '(OPTIONAL) Upgrade to Clay Verea "S" Tile (RED)'},
        {"description": "(OPTIONAL) Downgrade to TU Max (60 mil)"},
    ])
    assert lines == ['13" Concrete Tile Re-Roof']


def test_commercial_and_dispute_lines_are_dropped():
    """A public project page must not carry a customer's pricing or delay history."""
    lines = clean_scope_lines([
        {"description": "Sika RoofPro System"},
        {"description": "Group Discount and Cash Discount"},
        {"description": "Material Changes and Additional Costs Due to Delays"},
        {"description": "Sales Tax"},
    ])
    assert lines == ["Sika RoofPro System"]


def test_placeholder_lines_are_dropped():
    assert clean_scope_lines([{"description": "Default_Deliverable"}]) == []


def test_quantities_are_never_published():
    """The unit labels are provably wrong — Olsen's tile re-roof reads "7550 Squares", which
    would be 755,000 sq ft. Descriptions are trustworthy; the numbers are not."""
    lines = clean_scope_lines([
        {"description": "Polyglass MTS Secondary Water Barrier", "quantity": "7550",
         "unit": "Squares"},
    ])
    assert lines == ["Polyglass MTS Secondary Water Barrier"]
    assert "7550" not in " ".join(lines)


def test_template_prefixes_are_stripped_and_duplicates_collapsed():
    lines = clean_scope_lines([
        {"description": "FBC - Tile Roof Underlayment"},
        {"description": "Tile Roof Underlayment"},
    ])
    assert lines == ["Tile Roof Underlayment"]


def test_scope_is_capped():
    lines = clean_scope_lines([{"description": f"Item {i}"} for i in range(30)])
    assert len(lines) == 8


# --- whose scope is it? ----------------------------------------------------

def test_several_projects_for_one_client_are_merged():
    """Olsen Condo legitimately has a tile re-roof, a terrace-deck restoration and a BUR
    contract — same property, so the scope belongs together."""
    rows = [_row('13" Concrete Tile Re-Roof', project="Olsen Tile Re-Roof"),
            _row("Terrace Deck Demo", project="Olsen Condo Terrace Deck Restoration"),
            _row("Polyglass 2-Ply Built-Up Roofing System", project="Olsen Condo - BUR 20 Year")]
    assert len(scope_for_dominant_client(rows)) == 3


def test_a_generic_term_spanning_many_clients_yields_no_scope():
    """"warehouse" matches 9 projects across 7 clients. Publishing that merge would put
    another customer's job on this page, so the page ships without scope instead."""
    rows = [_row(f"Work {i}", client=f"c{i}", project=f"Warehouse {i}") for i in range(7)]
    assert scope_for_dominant_client(rows) == []


def test_a_dominant_client_wins_over_an_incidental_match():
    """Three projects for the condo, one stray for someone else -> use the condo's scope."""
    rows = [_row("Tile Re-Roof", client="condo", project="Alhambra Re-Roof"),
            _row("Pitch Pan Replacement", client="condo", project="Alhambra Pitch Pan"),
            _row("Tile Roof Repair", client="condo", project="Alhambra Repair"),
            _row("Someone else's gutter", client="other", project="Alhambra Street Gutters")]
    lines = scope_for_dominant_client(rows)
    assert "Someone else's gutter" not in lines
    assert len(lines) == 3


def test_a_dead_heat_yields_no_scope():
    """No clear owner means we cannot attribute the work, so nothing is published."""
    rows = [_row("A", client="c1", project="P1"), _row("B", client="c2", project="P2")]
    assert scope_for_dominant_client(rows) == []


def test_no_rows_is_no_scope():
    assert scope_for_dominant_client([]) == []


# --- prose -----------------------------------------------------------------

def test_scope_sentence_reads_as_english():
    assert scope_sentence(["a"]) == "a"
    assert scope_sentence(["a", "b"]) == "a and b"
    assert scope_sentence(["a", "b", "c"]) == "a, b and c"
    assert scope_sentence([]) == ""


# --- ranking and presentation ----------------------------------------------

def test_roof_work_outranks_administrative_lines():
    """Deliverables are not ordered by importance, so a raw cap of 8 buried
    '13" Concrete Tile Re-Roof' behind "Permit Fees" and a fastener escalation."""
    rows = [{"description": "Permit Fees"},
            {"description": "Permit Fees (to date 5/1/23)"},
            {"description": "Hoist Rental"},
            {"description": '13" Concrete Tile Re-Roof'},
            {"description": "Polyglass 2-Ply Built-Up Roofing System"}]
    lines = clean_scope_lines(rows)
    assert lines[0] == '13" Concrete Tile Re-Roof'
    assert lines[1] == "Polyglass 2-Ply Built-Up Roofing System"
    assert "Permit Fees" in lines, "administrative lines are demoted, not dropped"


def test_the_pricing_sheet_prefix_is_stripped_but_the_work_survives():
    lines = clean_scope_lines([{"description": "LINE ITEM PRICING: REPLACE STEEL DECKING PANEL"}])
    assert lines == ["Replace Steel Decking Panel"]


def test_shouting_lines_are_title_cased_and_brand_spellings_are_not():
    lines = clean_scope_lines([
        {"description": "EXTERIOR CHIMNEY RESTORATION (per structure)"},
        {"description": "Polyglass MTS Secondary Water Barrier"},
        {"description": "Sika RoofPro System"},
    ])
    assert "Exterior Chimney Restoration (per structure)" in lines
    assert "Polyglass MTS Secondary Water Barrier" in lines, "MTS must not become Mts"
    assert "Sika RoofPro System" in lines, "RoofPro must not become Roofpro"


def test_cost_increase_lines_are_dropped():
    assert clean_scope_lines([{"description": "Hoist Increase Since Award"}]) == []


# --- PII ------------------------------------------------------------------

def test_scope_lines_carrying_pii_are_dropped_whole():
    """Real lines from the corpus. 10 of 26,063 carry a street address, 31 a condo unit
    number, 1 a staff email — and scope lines publish verbatim."""
    lines = clean_scope_lines([
        {"description": "Polyglass 2-Ply Built-Up Roofing System"},
        {"description": "Tile Roof Repair   401 80TH ST"},
        {"description": "Flat Roof Maintenance (1460 Palm Ave)"},
        {"description": "Tile Roof Repair (Job Location: 10747 SW 104th St Miami, FL 33176)"},
        {"description": "Fascia Board Replacement - UNIT 114"},
        {"description": "josh@perkinsroofing.net"},
    ])
    assert lines == ["Polyglass 2-Ply Built-Up Roofing System"]


def test_material_specs_that_look_like_unit_numbers_survive():
    """"Double #30" is 30-lb felt, not apartment 30 — 499 lines were wrongly flagged before
    the unit detector required a keyword."""
    lines = clean_scope_lines([
        {"description": "FBC - Gulf Coast .032 Aluminum Versaloc Standing Seam Metal Re-Roof (Double #30)"},
        {"description": "Stainless Steel Scupper Drain (Inc. Wall Chip Out)"},
        {"description": "Seal Under and Inside Scuppers #1 and #2"},
    ])
    assert len(lines) == 3, lines
    assert any("Double #30" in line for line in lines), "30-lb felt is a material, not a unit"
