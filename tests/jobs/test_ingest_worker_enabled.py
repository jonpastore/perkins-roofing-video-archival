"""kb.ingest_enabled must actually stop ingest — the KB screen promises it does.

Found by the architect audit, 2026-08-13. The setting was declared (core/tenant_settings),
seeded (core/provision) and written by the UI (KbConfig.tsx), and NOTHING read it. The screen
says "No new videos will be fetched until re-enabled"; unticking it did nothing.
"""
from __future__ import annotations

import jobs.ingest_worker as IW


class _Row:
    def __init__(self, settings):
        self.settings = settings


class _DB:
    def __init__(self, settings):
        self._settings = settings
        self.queried = False

    def execute(self, *a, **k):
        self.queried = True
        return self

    def fetchone(self):
        return _Row(self._settings)


def test_disabled_tenant_is_skipped_without_touching_the_queue(monkeypatch):
    called = []
    monkeypatch.setattr(IW, "_pending_video_ids", lambda *a, **k: called.append(1) or [])

    out = IW._run_for_tenant(_DB({"kb": {"ingest_enabled": False}}), 1)

    assert out["skipped"] == "ingest_enabled=false"
    assert out["ingested"] == 0
    assert called == [], "a disabled tenant must not even enumerate pending videos"


def test_enabled_tenant_still_ingests(monkeypatch):
    monkeypatch.setattr(IW, "_pending_video_ids", lambda *a, **k: [])
    out = IW._run_for_tenant(_DB({"kb": {"ingest_enabled": True}}), 1)
    assert "skipped" not in out


def test_absent_setting_defaults_to_enabled(monkeypatch):
    """Every existing tenant predates this reader. None of them may go dark."""
    monkeypatch.setattr(IW, "_pending_video_ids", lambda *a, **k: [])
    for raw in ({}, {"kb": {}}, {"marketing": {}}):
        assert "skipped" not in IW._run_for_tenant(_DB(raw), 1), raw


def test_a_broken_settings_blob_fails_OPEN(monkeypatch):
    """Ingest feeds everything downstream. A malformed blob must not silently halt the
    catalogue — only an explicit False may stop it."""
    monkeypatch.setattr(IW, "_pending_video_ids", lambda *a, **k: [])

    class _Boom(_DB):
        def fetchone(self):
            raise RuntimeError("settings column unreadable")

    assert "skipped" not in IW._run_for_tenant(_Boom({}), 1)
    assert IW._ingest_enabled(_DB("not-a-dict"), 1) is True
