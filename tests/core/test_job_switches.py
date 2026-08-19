"""Admin job on/off flags."""
from __future__ import annotations

from core.job_switches import (
    CONTENT_GEN,
    KNOWIFY_SYNC,
    PROPOSAL_REMINDERS,
    content_gen_enabled,
    knowify_sync_enabled,
    parse_bool,
    proposal_reminders_enabled,
    read_flag,
)


def test_flags_are_editable_config_keys():
    from api.routes.config import EDITABLE_KEYS
    assert KNOWIFY_SYNC in EDITABLE_KEYS
    assert PROPOSAL_REMINDERS in EDITABLE_KEYS
    assert CONTENT_GEN in EDITABLE_KEYS


def test_parse_bool():
    assert parse_bool("true") is True
    assert parse_bool("ON") is True
    assert parse_bool("1") is True
    assert parse_bool("false") is False
    assert parse_bool("") is False
    assert parse_bool(None, default=True) is True


def test_read_flag_env(monkeypatch):
    monkeypatch.setenv(KNOWIFY_SYNC, "true")
    monkeypatch.setenv(PROPOSAL_REMINDERS, "false")
    assert read_flag(KNOWIFY_SYNC) is True
    assert read_flag(PROPOSAL_REMINDERS) is False
    assert knowify_sync_enabled() is True
    assert proposal_reminders_enabled() is False


def test_read_flag_default_off(monkeypatch):
    monkeypatch.delenv(KNOWIFY_SYNC, raising=False)
    monkeypatch.delenv(PROPOSAL_REMINDERS, raising=False)
    assert knowify_sync_enabled() is False
    assert proposal_reminders_enabled() is False


def test_content_gen_on_only_when_mode_is_dump(monkeypatch):
    monkeypatch.setenv(CONTENT_GEN, "dump")
    assert content_gen_enabled() is True
    monkeypatch.setenv(CONTENT_GEN, "off")
    assert content_gen_enabled() is False
    monkeypatch.delenv(CONTENT_GEN, raising=False)
    assert content_gen_enabled() is False


def test_read_flag_db_wins(monkeypatch):
    monkeypatch.setenv(KNOWIFY_SYNC, "true")

    class _Row:
        value = "false"

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, model, key):
            return _Row() if key == KNOWIFY_SYNC else None

        info: dict = {}

    monkeypatch.setattr("app.models.PlatformSessionLocal", lambda: _Db())
    assert read_flag(KNOWIFY_SYNC) is False
