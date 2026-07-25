"""
WHY: RoofR PDFs were re-parsed on every run of fit_days_from_roofr.py
and tim_quote_breakdown.py. The existing measurements table already has
every field the parse produces, so this needed no migration.
Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_tim_measurements.py [--dry-run]
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from sqlalchemy import select

from app.models import Measurement, SessionLocal


def _load_fitter():
    spec = importlib.util.spec_from_file_location(
        'fitmod',
        Path(__file__).with_name('fit_days_from_roofr.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    homes = _load_fitter().load()
    s = SessionLocal()
    s.info['tenant_id'] = 1
    created = updated = 0

    for home in homes:
        addr = home['address']
        existing_row = s.scalar(
            select(Measurement).where(
                Measurement.tenant_id == 1,
                Measurement.provider == 'roofr',
                Measurement.address == addr,
            )
        )

        raw = {
            'tim_days': {
                'demo': home['demo'],
                'shingle': home['shingle'],
                'tile': home['tile'],
                'metal': home['metal'],
            },
            'existing': home['existing'],
            'area_sqft': home['area_sqft'],
            'facets': home['facets'],
            'two_story_sq': home['two_story_sq'],
            'pdf': home['pdf'],
        }

        if existing_row:
            existing_row.total_sq = home['squares']
            existing_row.hips_lf = home['hips']
            existing_row.ridges_lf = home['ridges']
            existing_row.valleys_lf = home['valleys']
            existing_row.rakes_lf = home['rakes']
            existing_row.eaves_lf = home['eaves']
            existing_row.wall_flashings_lf = home['wall_flash']
            existing_row.pitch_primary = home['pitch']
            existing_row.raw_payload = raw
            updated += 1
            print("UPDATED: {}, {}".format(addr, home['squares']))
        else:
            new_row = Measurement(
                tenant_id=1,
                provider='roofr',
                status='complete',
                address=addr,
                total_sq=home['squares'],
                hips_lf=home['hips'],
                ridges_lf=home['ridges'],
                valleys_lf=home['valleys'],
                rakes_lf=home['rakes'],
                eaves_lf=home['eaves'],
                wall_flashings_lf=home['wall_flash'],
                pitch_primary=home['pitch'],
                created_by='seed_tim_measurements.py',
                provenance_note=(
                    'Tim TIME LEARNING sheet + RoofR report, '
                    'emailed 2026-07-24'
                ),
                raw_payload=raw,
            )
            s.add(new_row)
            created += 1
            print("CREATED: {}, {}".format(addr, home['squares']))

    if args.dry_run:
        # The loop stages inserts and mutates loaded rows, and the select() on the next
        # iteration would autoflush them. close() alone rolls back, but say so explicitly —
        # a "dry run" that can touch the database is not one.
        s.rollback()
    else:
        s.commit()
    s.close()

    print("Created: {}, Updated: {}".format(created, updated))


if __name__ == '__main__':
    main()
