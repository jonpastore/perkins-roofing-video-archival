from pathlib import Path


def test_imported_invoice_labels_do_not_show_knowify_prefix():
    for path in [
        Path("web/src/pages/Payments.tsx"),
        Path("web/src/pages/Invoices.tsx"),
        Path("web/src/pages/Status.tsx"),
    ]:
        source = path.read_text()
        assert "Knowify #" not in source
