from pathlib import Path


def test_quoting_page_is_presented_as_canonical_estimates_workflow():
    source = Path("web/src/pages/Quoting.tsx").read_text()

    assert "<PageTitle" in source
    assert "Estimates" in source
    assert "This is the canonical path for building a customer-linked estimate" in source
    assert '["Customer", "Property", "Measurement", "Estimate", "Proposal"]' in source


def test_legacy_estimator_page_was_removed_by_consolidation():
    # The consolidation went past "mark it legacy" — the standalone Estimator page was
    # removed entirely, so the only estimate path is the customer-linked Quoting flow.
    assert not Path("web/src/pages/Estimator.tsx").exists()


def test_estimates_customer_search_is_bounded_server_search_not_full_list():
    # Customer selection is a debounced SERVER-side search (bounded result set), not a
    # full client-side list — the same intent, implemented server-side.
    source = Path("web/src/pages/Quoting.tsx").read_text()
    assert 'placeholder="Search customers by name, company, or email' in source
    assert 'params.set("search"' in source          # query carries the search term
    assert 'limit: "50"' in source                  # bounded, not "load them all"


def test_estimates_property_measurement_estimate_chain_present():
    source = Path("web/src/pages/Quoting.tsx").read_text()
    assert "PropertyForm" in source
    assert "property_id: selectedPropertyId" in source
    assert "/measurements?property_id=" in source
    assert "/estimator/estimates?measurement_id=" in source
    assert "Estimates for this measurement" in source
