from pathlib import Path


def test_customers_new_customer_uses_modal_with_property_measurement_fields():
    source = Path("web/src/pages/Customers.tsx").read_text()
    assert "function ModalShell" in source
    assert "Initial property and measurement" in source
    assert "property_id: prop.id" in source
    assert 'apiFetch("/measurements"' in source


def test_customers_selecting_customer_hides_new_modal_and_opens_detail_modal():
    source = Path("web/src/pages/Customers.tsx").read_text()
    assert "setShowNewForm(false); setSelectedId" in source
    assert '<ModalShell title="Customer"' in source
    assert "<DetailPanel" in source
