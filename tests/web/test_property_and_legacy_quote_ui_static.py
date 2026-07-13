from pathlib import Path

CUSTOMERS = Path("web/src/pages/Customers.tsx")
PROPOSALS = Path("web/src/pages/Proposals.tsx")
API = Path("web/src/api.ts")


def test_customer_properties_can_be_edited_and_removed_in_modal():
    source = CUSTOMERS.read_text()
    api = API.read_text()

    assert "EditPropertyForm" in source
    assert "updateProperty" in source
    assert "deleteProperty" in source
    assert "Remove this property" in source
    assert "Properties linked to measurements/proposals will be blocked" in source
    assert 'method: "DELETE"' in api
    assert "/quoting/properties/${propertyId}" in api


def test_legacy_quote_import_is_native_migration_with_auto_match():
    source = PROPOSALS.read_text()
    api = API.read_text()

    assert "Migrate → Native" in source
    assert "Migrate to native proposal" in source
    assert "auto-matched from the Knowify ClientId" in source
    assert "customer_id?: number | null" in api
