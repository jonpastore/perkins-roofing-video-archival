from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "web" / "src"


def test_data_sources_panel_has_login_buttons():
    src = (ROOT / "components" / "DataSources.tsx").read_text()
    assert "Knowify" in src
    assert "CompanyCam" in src
    assert "YouTube" in src
    assert "Log in" in src
    assert "startOAuth" in src


def test_knowify_and_portfolio_mount_data_sources():
    assert "DataSources" in (ROOT / "pages" / "Knowify.tsx").read_text()
    assert "DataSources" in (ROOT / "pages" / "Portfolio.tsx").read_text()
    assert "DataSources" in (ROOT / "pages" / "MarketingConfig.tsx").read_text()
    assert "DataSources" in (ROOT / "pages" / "Status.tsx").read_text()


def test_job_switches_and_reminder_notice_mounted():
    switches = (ROOT / "components" / "JobSwitches.tsx").read_text()
    assert "KNOWIFY_SYNC_ENABLED" in switches
    assert "PROPOSAL_REMINDERS_ENABLED" in switches
    assert "JobSwitches" in (ROOT / "pages" / "Settings.tsx").read_text()
    assert "JobSwitches" in (ROOT / "pages" / "MarketingConfig.tsx").read_text()
    notice = (ROOT / "components" / "RemindersPausedNotice.tsx").read_text()
    assert "proposal reminders are off" in notice.lower()
    assert "RemindersPausedNotice" in (ROOT / "pages" / "Proposals.tsx").read_text()
    assert "RemindersPausedNotice" in (ROOT / "pages" / "Quoting.tsx").read_text()
