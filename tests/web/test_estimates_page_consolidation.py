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
