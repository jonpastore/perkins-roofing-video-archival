"""Regression tests for probe_companycam (integration health).

Guards the signature mismatch a review caught: the probe called list_projects(per_page=1) after
list_projects() was changed to take no args (pagination refactor) — a TypeError that would fire the
instant the CompanyCam PAT is issued. These exercise the REAL ping() path (only _get is mocked), so a
signature drift between the probe and the adapter fails here instead of at activation.
"""
import adapters.companycam as companycam
from adapters.integration_probes import probe_companycam


def test_probe_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("COMPANYCAM_PAT", raising=False)
    assert probe_companycam() is None


def test_probe_ok_when_ping_succeeds(monkeypatch):
    monkeypatch.setenv("COMPANYCAM_PAT", "tok")
    monkeypatch.setattr(companycam, "_get", lambda url, params=None: [])  # no network
    result = probe_companycam()
    assert result is not None and result.ok is True


def test_probe_hard_auth_failure_on_401(monkeypatch):
    monkeypatch.setenv("COMPANYCAM_PAT", "tok")

    def _boom(url, params=None):
        raise RuntimeError("CompanyCam API error 401: invalid token")

    monkeypatch.setattr(companycam, "_get", _boom)
    result = probe_companycam()
    assert result is not None and result.ok is False and result.hard_auth_failure is True
