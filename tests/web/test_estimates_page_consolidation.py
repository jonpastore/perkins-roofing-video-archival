from pathlib import Path


def test_quoting_page_is_presented_as_canonical_estimates_workflow():
    source = Path("web/src/pages/Quoting.tsx").read_text()

    assert "<PageTitle" in source
    assert "Estimates" in source
    assert "This is the canonical path for building a customer-linked estimate" in source
    assert '["Customer", "Property", "Measurement", "Estimate", "Proposal"]' in source


def test_estimator_page_is_marked_legacy_unattached_calculator():
    source = Path("web/src/pages/Estimator.tsx").read_text()

    assert "Legacy Quick Estimate Calculator" in source
    assert "Legacy / unattached calculator" in source
    assert "It does not create a customer" in source


def test_estimates_customer_search_is_autocomplete_not_full_list():
    source = Path("web/src/pages/Quoting.tsx").read_text()
    assert "Start typing to find a customer" in source
    assert "filteredCustomers.slice(0, 8)" in source
    assert "No customers matching" in source


def test_estimates_property_measurement_estimate_chain_present():
    source = Path("web/src/pages/Quoting.tsx").read_text()
    assert "PropertyForm" in source
    assert "property_id: selectedPropertyId" in source
    assert "/measurements?property_id=" in source
    assert "/estimator/estimates?measurement_id=" in source
    assert "Estimates for this measurement" in source
