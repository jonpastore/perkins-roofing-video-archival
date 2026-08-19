from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "web" / "src"


def test_data_sources_panel_has_login_buttons():
    src = (ROOT / "components" / "DataSources.tsx").read_text()
    assert "Knowify" in src
    assert "CompanyCam" in src
    assert "YouTube" in src
    assert "Log in" in src
    assert "startOAuth" in src
    assert "needsLogin" in src
    assert "aria-expanded" in src
    assert 'setOpen(true)' in src
    assert "visibilitychange" in src


def test_dashboard_has_one_readiness_surface():
    status = (ROOT / "pages" / "Status.tsx").read_text()
    assert "Go-Live Checklist" not in status
    assert "GoLiveChecklistBanner" not in status
    assert "ProductionReadinessBanner" in status
    assert "Search-engine indexing is IndexNow" in status
    assert "Tim pricing" in status
    assert status.count("<ProductionReadinessBanner") == 1


def test_data_sources_only_on_dashboard():
    status = (ROOT / "pages" / "Status.tsx").read_text()
    assert "DataSources" in status
    assert status.find("<DataSources") < status.find("<ProductionReadinessBanner")
    for name in ("Knowify.tsx", "Portfolio.tsx", "MarketingConfig.tsx", "Articles.tsx", "Scheduling.tsx"):
        src = (ROOT / "pages" / name).read_text()
        assert "DataSources" not in src, f"{name} must not mount Data sources"


def test_job_switches_and_reminder_notice_mounted():
    switches = (ROOT / "components" / "JobSwitches.tsx").read_text()
    assert "KNOWIFY_SYNC_ENABLED" in switches
    assert "PROPOSAL_REMINDERS_ENABLED" in switches
    assert "CONTENT_GEN_MODE" in switches
    assert "Daily articles" in switches
    assert "JobSwitches" in (ROOT / "pages" / "Settings.tsx").read_text()
    assert "JobSwitches" in (ROOT / "pages" / "MarketingConfig.tsx").read_text()
    notice = (ROOT / "components" / "RemindersPausedNotice.tsx").read_text()
    assert "proposal reminders are off" in notice.lower()
    assert "RemindersPausedNotice" in (ROOT / "pages" / "Proposals.tsx").read_text()
    assert "RemindersPausedNotice" in (ROOT / "pages" / "Quoting.tsx").read_text()
