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


def test_payments_detail_uses_right_side_modal_drawer():
    source = Path("web/src/pages/Payments.tsx").read_text()

    assert 'role="dialog"' in source
    assert 'aria-label="Payment detail"' in source
    assert 'justifyContent: "flex-end"' in source
    assert "height: \"100vh\"" in source


def test_estimates_customer_detail_can_add_contacts_and_set_primary():
    source = Path("web/src/pages/Quoting.tsx").read_text()

    assert "ContactForm" in source
    assert "+ Add contact" in source
    assert "Set as primary contact" in source
    assert "handleSetPrimaryContact" in source
    assert "Set primary" in source


def test_estimates_show_non_blocking_warnings():
    source = Path("web/src/pages/Quoting.tsx").read_text()

    assert "warnings?: string[]" in source
    assert "Non-blocking estimate warning" in source
    assert "quoteResult.warnings.map" in source


def test_estimates_customer_search_uses_server_side_search():
    source = Path("web/src/pages/Quoting.tsx").read_text()

    assert 'new URLSearchParams({ limit: "50" })' in source
    assert 'params.set("search", q)' in source
    assert 'apiFetch(`/quoting/customers?${params.toString()}`)' in source
    assert "Searching all customers" in source


def test_estimates_expose_pricing_drivers_discounts_and_estimate_linkage():
    source = Path("web/src/pages/Quoting.tsx").read_text()

    assert "Recommended tier" in source
    assert "EstimateCheckbox" in source
    assert "Demo / tear-off" in source
    assert "Discounts affect total and margin" in source
    assert "estimate_id: quoteResult.estimate_id" in source
    assert "recommended_tier: recommendedTier" in source
    assert "tierTotalsForQuote" in source
    assert "Bridge tier math to Perkins package adders" in source
