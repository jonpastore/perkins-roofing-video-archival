"""Daily portfolio scan — find projects that are READY TO BUILD, and say what is blocking the rest.

Jon, 2026-08-13: "we should also be looking for projects we can build and publish daily."

⚠️ THIS JOB DELIBERATELY DOES NOT PUBLISH, and that is not an oversight or a phase-two deferral.
A portfolio page cannot be published without two things a cron is incapable of supplying:

  1. **Recorded client permission.** api/routes/portfolio._permissions reads permission_property,
     permission_photos and permission_video off the PortfolioCuration row and every one of them
     defaults to FALSE when no row exists. These are client CONSENT flags for publishing photos of
     someone's home. A job that set them would be manufacturing consent, which is the one thing
     no amount of test coverage makes acceptable.
  2. **Curated media.** publish_portfolio_project builds the gallery from row.selections — photos
     a human chose. There is no defensible automatic selection: the mirror holds ~156k photos of
     customers' houses, CompanyCam burns GPS coordinates into the pixels (core/photo_privacy),
     and the publish gate exists precisely because an address can hide in an image alt or a
     customer name in a title.

So the automatable half is the LOOKING, and that is what this does: every day, work out which
projects could be built, which are one step away, and exactly what that step is — so the work
waiting for a person is visible instead of being discovered by remembering to check.

The publish click stays human. That is the correct boundary, not a limitation to remove later.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Advisory-lock key — distinct from ingest/knowify/companycam/render/daily-article.
_LOCK_KEY = 8274128

#: Report the top N ready candidates in the log line. The full set is in the returned dict.
_REPORT_LIMIT = int(os.getenv("PORTFOLIO_SCAN_REPORT_LIMIT", "10"))


def _readiness(candidate: dict, curation) -> dict:
    """What stands between this project and a publishable page.

    Returns {"slug", "name", "ready", "blockers": [...]}. `ready` means a human could open the
    curation view and publish today — NOT that anything should publish automatically.
    """
    blockers: list[str] = []

    if curation is None:
        blockers.append("no curation row — nobody has opened this project yet")
    else:
        missing_perms = [
            label for label, granted in (
                ("property", curation.permission_property),
                ("photos", curation.permission_photos),
                ("video", curation.permission_video),
            ) if not granted
        ]
        if missing_perms:
            # Not a defect and not a to-do the system can close: these are the client's answers.
            blockers.append(f"client permission not recorded: {', '.join(missing_perms)}")
        if not (curation.selections or []):
            blockers.append("no photos selected — the gallery would be empty")

    if not (candidate.get("companycam_url") or "").strip():
        blockers.append("no CompanyCam project linked — there is no media to draw from")
    if not (candidate.get("city") or "").strip():
        blockers.append("no city — the page has no location context")

    return {
        "slug": candidate.get("slug"),
        "name": candidate.get("name"),
        "ready": not blockers,
        "blockers": blockers,
    }


def _run_for_tenant(db, tenant_id: int) -> dict:
    from app.models import PortfolioCuration  # noqa: PLC0415

    try:
        from api.routes.portfolio import _projects  # noqa: PLC0415
        candidates = [p.as_record() for p in _projects(db)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("portfolio_scan: could not list projects for tenant %s: %s", tenant_id, exc)
        return {"tenant_id": tenant_id, "error": str(exc)[:200]}

    curation = {r.slug: r for r in db.query(PortfolioCuration).all()}
    rows = [_readiness(c, curation.get(c.get("slug"))) for c in candidates]

    ready = [r for r in rows if r["ready"]]
    blocked = [r for r in rows if not r["ready"]]

    if ready:
        logger.info(
            "portfolio_scan: tenant %s — %d project(s) READY TO PUBLISH (a person still has to "
            "press publish): %s",
            tenant_id, len(ready), ", ".join(r["slug"] or "?" for r in ready[:_REPORT_LIMIT]),
        )
    else:
        logger.info("portfolio_scan: tenant %s — nothing ready today (%d candidate(s) blocked)",
                    tenant_id, len(blocked))

    # Group the blockers so the log answers "what is actually stopping us" rather than listing
    # every project every day. Consent gaps and un-curated projects need different people.
    tally: dict[str, int] = {}
    for r in blocked:
        for b in r["blockers"]:
            tally[b.split(":")[0]] = tally.get(b.split(":")[0], 0) + 1
    for reason, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        logger.info("portfolio_scan:   %3d x %s", n, reason)

    return {"tenant_id": tenant_id, "total": len(rows),
            "ready": ready, "blocked_count": len(blocked), "blockers": tally}


def run() -> dict:
    """Cron entrypoint. Read-only: this job publishes nothing and writes nothing."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.single_flight import single_flight  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    with single_flight(SessionLocal, _LOCK_KEY) as ok:
        if not ok:
            logger.warning("portfolio_scan: another run holds the lock — skipping")
            return {"skipped": "already running"}

        results: list[dict] = []

        def _fn(db, tenant_id: int) -> None:
            results.append(_run_for_tenant(db, tenant_id))

        for_each_tenant(SessionLocal, _fn)
        return {"tenants": results}


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run(), indent=2, default=str))
