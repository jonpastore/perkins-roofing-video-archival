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
    """The module must emit to STDOUT on its own, with nothing else configured.

    This is a subprocess with the root handlers stripped, because that is prod: the API service
    calls no basicConfig, so the root logger has NO handlers and records fall to
    logging.lastResort, which is WARNING-only.

    ⚠️ IT IS A SUBPROCESS FOR A REASON. The first version of this test added its OWN capture
    handler and therefore PASSED against the broken first fix — which set the logger level but
    attached no handler, and produced literally nothing when triggered in prod. A test that
    supplies the very thing under test proves nothing. The level decides whether a record is
    CREATED; a handler decides whether anything is EMITTED, and only the second is visible to a
    human.
    """
    import subprocess
    import sys

    for module in ("jobs.portfolio_scan_job", "jobs.daily_content_job"):
        code = (
            "import logging\n"
            "root = logging.getLogger()\n"
            "[root.removeHandler(h) for h in list(root.handlers)]\n"
            f"import {module} as M\n"
            "M.logger.info('CANARY-VISIBLE')\n"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert "CANARY-VISIBLE" in r.stdout, (
            f"{module} emits NOTHING to stdout with an empty root handler chain — which is "
            f"exactly the API service. Its findings are its entire product.\n"
            f"stdout={r.stdout!r}\nstderr={r.stderr[-400:]!r}"
        )
