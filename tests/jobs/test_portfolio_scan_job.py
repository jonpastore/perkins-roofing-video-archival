"""The daily portfolio scan finds work — and must never publish it.

Jon asked for projects "we can build and publish daily". The finding is automatable; the
publishing is not, and this pins that boundary so it is not quietly removed later.
"""
from __future__ import annotations

from types import SimpleNamespace

import jobs.portfolio_scan_job as PS


def _cur(prop=True, photos=True, video=True, selections=(1,)):
    return SimpleNamespace(permission_property=prop, permission_photos=photos,
                           permission_video=video, selections=list(selections))


def _cand(**over):
    base = {"slug": "evergrene", "name": "Evergrene", "city": "Palm Beach Gardens",
            "companycam_url": "https://app.companycam.com/projects/123"}
    base.update(over)
    return base


def test_a_fully_permissioned_curated_project_is_ready():
    r = PS._readiness(_cand(), _cur())
    assert r["ready"] and r["blockers"] == []


def test_missing_client_permission_blocks_and_NAMES_which_one():
    """These are the client's answers about photographing their home, not a system to-do."""
    r = PS._readiness(_cand(), _cur(photos=False))
    assert not r["ready"]
    assert any("photos" in b and "permission" in b for b in r["blockers"]), r["blockers"]


def test_no_curation_row_blocks():
    r = PS._readiness(_cand(), None)
    assert not r["ready"]
    assert any("nobody has opened" in b for b in r["blockers"])


def test_no_selected_photos_blocks_because_the_gallery_would_be_empty():
    r = PS._readiness(_cand(), _cur(selections=()))
    assert not r["ready"]
    assert any("no photos selected" in b for b in r["blockers"])


def test_missing_companycam_link_or_city_blocks():
    assert not PS._readiness(_cand(companycam_url=""), _cur())["ready"]
    assert not PS._readiness(_cand(city=""), _cur())["ready"]


def test_the_scan_NEVER_publishes_and_never_writes():
    """THE BOUNDARY. A page needs recorded client consent and human-chosen photos of someone's
    house; CompanyCam burns GPS into the pixels and the mirror holds ~156k of them. A cron
    cannot supply consent, so this module must contain no publish call and no write.

    Asserted against the SOURCE so that adding one is a deliberate act that fails this test.
    """
    import ast
    from pathlib import Path

    # AST, not grep. A name scan matches this module's own DOCSTRING — which exists precisely to
    # explain why publishing is excluded — so it would fail on the explanation rather than on any
    # behaviour. (Same lesson as the redact_regions grep test earlier the same day.) Only actual
    # CALLS count.
    tree = ast.parse(Path("jobs/portfolio_scan_job.py").read_text())
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                called.add(f.id)
            elif isinstance(f, ast.Attribute):
                called.add(f.attr)

    for forbidden in ("publish_portfolio_post", "publish_portfolio_project", "commit", "add"):
        assert forbidden not in called, (
            f"portfolio_scan_job now CALLS {forbidden!r} — this job is read-only by design. "
            "Publishing a customer's project page requires recorded client permission and "
            "human-selected photos; a cron can supply neither."
        )


def test_overlapping_runs_are_refused(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _denied(_f, _k):
        yield False

    monkeypatch.setattr("core.single_flight.single_flight", _denied)
    assert PS.run()["skipped"] == "already running"


def test_the_jobs_output_can_actually_REACH_cloud_logging():
    """A daily scan whose findings are discarded has run and told nobody.

    Verified in prod 2026-08-13: the API service has no basicConfig, so the root logger sits at
    WARNING and logger.info is dropped — a logger.warning from jobs/social_job appears in Cloud
    Logging, a logger.info does not. These jobs run inside that service via /internal/*, and their
    output IS the product, so the module logger pins its own level.
    """
    import logging

    import jobs.daily_content_job as DC
    import jobs.portfolio_scan_job as PS

    for mod in (PS, DC):
        assert mod.logger.getEffectiveLevel() <= logging.INFO, (
            f"{mod.__name__} would emit nothing in prod — the API service's root logger is at "
            "WARNING and this module's findings are its entire purpose"
        )
