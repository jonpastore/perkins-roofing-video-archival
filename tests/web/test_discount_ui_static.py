from pathlib import Path


def test_proposal_builder_supports_percent_discounts_and_presets():
    source = Path("web/src/pages/ProposalBuilder.tsx").read_text()
    assert 'discount_type: "amount" | "percent"' in source
    assert "DISCOUNT_PRESETS_KEY" in source
    assert "Save preset" in source
    assert 'discount_type: d.discount_type' in source
    assert 'd.discount_type === "amount"' in source


def test_invoice_form_supports_percent_discounts_and_presets():
    source = Path("web/src/pages/Invoices.tsx").read_text()
    assert 'discount_type: "amount" | "percent"' in source
    assert "INVOICE_DISCOUNT_PRESETS_KEY" in source
    assert 'discount_type: d.discount_type' in source
    assert 'd.discount_type === "amount"' in source
