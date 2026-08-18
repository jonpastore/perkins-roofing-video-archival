from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "web" / "src"


def test_data_sources_panel_has_login_buttons():
    src = (ROOT / "components" / "DataSources.tsx").read_text()
    assert "Knowify" in src
    assert "CompanyCam" in src
    assert "Log in" in src
    assert "startOAuth" in src


def test_knowify_and_portfolio_mount_data_sources():
    assert "DataSources" in (ROOT / "pages" / "Knowify.tsx").read_text()
    assert "DataSources" in (ROOT / "pages" / "Portfolio.tsx").read_text()
    assert "DataSources" in (ROOT / "pages" / "MarketingConfig.tsx").read_text()
