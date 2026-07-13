from pathlib import Path


APP = Path("web/src/App.tsx")
STATUS = Path("web/src/pages/Status.tsx")


def test_sidebar_and_hamburger_stay_above_page_modals():
    source = APP.read_text()

    assert "zIndex: 1500" in source  # hamburger remains available over page overlays
    assert "zIndex: 1400" in source  # desktop sidebar remains navigable over page overlays
    assert "zIndex: 1350" in source  # mobile nav backdrop sits between modal and drawer


def test_aging_modal_close_clears_loading_and_ignores_stale_responses():
    source = STATUS.read_text()

    assert "const agingRequestId = useRef(0);" in source
    assert "function closeAgingBucket()" in source
    assert "setAgingLoading(false);" in source
    assert "if (agingRequestId.current === requestId) setAgingDetail(detail);" in source
    assert "if (agingRequestId.current === requestId) setAgingError" in source
    assert "onClick={closeAgingBucket}" in source
    assert "onClick={(e) => e.stopPropagation()}" in source
