#!/usr/bin/env python3
"""Record Tim's blanket client-permission grant on every portfolio project.

WHY THIS IS DATA AND NOT A DEFAULT. core.portfolio_criteria treats naming a property and
using its photos/video as three separate ``blocker`` criteria, and api.routes.portfolio
._permissions defaults all three to False when no curation row exists. That deny-by-default is
correct and must stay: a project created tomorrow has no clearance until someone says so.
This script writes the clearance we DO have as a row per project, with its provenance, rather
than flipping the default and silently clearing every future project too.

PROVENANCE. Tim Kanak (President, Perkins Roofing), by email 2026-07-30 11:35 UTC, on the
thread "Project pages — where should they live, and what are the requirements?", answering
Jon's question "we need to know which projects have client permission to name the property and
use the photos and video":

    "Hey Jon, Every project has client permission, it's one of our contract terms."

So the grant is blanket and covers all three permissions for every project. It is recorded in
``updated_by`` because portfolio_curation has no notes column — the point is that an auditor
reading the row can see the clearance came from the client, not from an engineer.

This unblocks CURATION, not publishing. Permission is upstream of everything else because
api.routes.portfolio._available_media filters the mirror through
core.portfolio_media.publishable_media, so with permission_photos false a project shows zero
photos available and a gallery can never be built. Publishing still has to pass no_pii,
title_not_a_person, media_sanitized (the burned-in GPS stamp) and the quality majors, none of
which this touches.

⚠️ THE GRANT IS FROZEN IN TIME, AND THAT IS THE WHOLE POINT.

Tim's statement was made on 2026-07-30 and covers the projects that existed when he made it. A
project added in September is not covered by a sentence written in July. So this only touches
projects created at or before :data:`GRANT_CUTOFF`, and skips archived ones.

Without that bound, "idempotent, safe to re-run" — true of the row writes — would silently mean
"re-run it and every project added since inherits a clearance nobody gave", stamped with Tim's
name as provenance. An auditor reading such a row would be told the client cleared it. Re-running
is safe ONLY for the frozen set; that is what makes the idempotency claim honest.

Usage:
  DB_URL=postgresql+psycopg://app:...@127.0.0.1:5432/perkins \
    .venv/bin/python scripts/portfolio_grant_permissions.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GRANTED_BY = "tim@perkinsroofing.net (email 2026-07-30, contract term)"
#: When Tim sent it (UTC). Projects created after this are OUTSIDE the grant — a later clearance
#: needs its own evidence, not a re-run of this script.
GRANT_CUTOFF = datetime(2026, 7, 30, 11, 35, 29)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from app.models import PortfolioCuration, PortfolioProject, SessionLocal

    db = SessionLocal()
    db.info["tenant_id"] = 1

    projects = (
        db.query(PortfolioProject)
        .filter(PortfolioProject.created_at <= GRANT_CUTOFF,
                PortfolioProject.archived_at.is_(None))
        .order_by(PortfolioProject.slug)
        .all()
    )
    outside = (
        db.query(PortfolioProject)
        .filter(PortfolioProject.created_at > GRANT_CUTOFF)
        .count()
    )
    if outside:
        # Named, not silently skipped: a project outside the grant is a project someone still has
        # to get clearance for, and a count of 0 published here is what says the grant is complete.
        print(f"  ! {outside} project(s) created after {GRANT_CUTOFF:%Y-%m-%d} are OUTSIDE this "
              f"grant and were left untouched — they need their own clearance.")

    existing = {r.slug: r for r in db.query(PortfolioCuration).all()}

    changed = 0
    for project in projects:
        row = existing.get(project.slug)
        if row is None:
            row = PortfolioCuration(tenant_id=1, slug=project.slug, selections=[])
            db.add(row)
            action = "created"
        elif all((row.permission_property, row.permission_photos, row.permission_video)):
            print(f"  unchanged  {project.slug}")
            continue
        else:
            action = "updated"

        row.permission_property = True
        row.permission_photos = True
        row.permission_video = True
        row.updated_by = GRANTED_BY
        changed += 1
        print(f"  {action:10s} {project.slug}")

    if args.dry_run:
        db.rollback()
        print(f"\ndry-run: {changed} row(s) would change, nothing written")
        return 0

    db.commit()
    print(f"\n{changed} row(s) written, {len(projects)} project(s) total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
