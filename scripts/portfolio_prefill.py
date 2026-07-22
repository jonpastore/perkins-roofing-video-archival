#!/usr/bin/env python3
"""Assemble Avada Portfolio candidate records for the 13 "Possible Project" entries in
Wendy's projects doc (2026-07-22 ask) — match each against Knowify + videos/chunks, generate a
grounded write-up via Cloudflare Workers-AI, and prefill the 30-field questionnaire.

Writes two files to --out-dir:
  portfolio_records.json   — everything (full record + questionnaire + post payload + needs_human)
  wendy_sheet_filled.csv   — one column-block per project: Info Required, response, source-note

Does NOT touch WordPress — see scripts/portfolio_publish.py for that.

Usage:
  .venv/bin/python scripts/portfolio_prefill.py --out-dir <scratch-dir>

Requires DB_URL (Cloud SQL proxy) and CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN in env.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import String, cast, create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from core.portfolio import (  # noqa: E402
    infer_property_type,
    infer_roof_type,
    map_to_post,
    map_to_questionnaire,
    needs_human,
)
from core.tenant import register_tenant_session_events  # noqa: E402

# Transcribed directly from projects_doc.txt "Possible Commercial/Residential Projects"
# sections — 13 candidates. date_start/date_end are the CompanyCam photo date range (or video
# upload date where no CompanyCam range is given) already stated in that doc; NOT invented.
CANDIDATES = [
    {"name": "Fisher Island 7900 Flat Roofs", "city": "Fisher Island", "section": "commercial",
     "search_terms": ["7900"], "youtube_url": "https://www.youtube.com/watch?v=bPyTl6vIjvk",
     "companycam_url": "https://app.companycam.com/projects/60249175/photos",
     "date_start": "20 Feb 2024", "date_end": "21 May 2025",
     "notes": "Also has separate CompanyCam projects per tower: south tower "
              "(57458249), center tower (59760105), north tower (59023123), lobby tower (59411141)."},
    {"name": "Fisher Island Building 77 Soffit Work", "city": "Fisher Island", "section": "commercial",
     "search_terms": ["Building 77"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/79260538/photos",
     "date_start": "11 May 2026", "date_end": "17 Jul 2026", "notes": ""},
    {"name": "Miami Warehouse Polyglass Silicone Restoration", "city": "Miami", "section": "commercial",
     "search_terms": ["warehouse"], "youtube_url": "https://www.youtube.com/watch?v=tNCEbXiR64E",
     "companycam_url": "", "date_start": "", "date_end": "", "notes": "50,000 SF warehouse."},
    {"name": "Miami Isola Roof", "city": "Miami", "section": "commercial",
     "search_terms": ["Isola"], "youtube_url": "https://www.youtube.com/watch?v=515byFUH6Uo",
     "companycam_url": "https://app.companycam.com/projects/64431634/photos",
     "date_start": "21 May 2024", "date_end": "13 Nov 2025", "notes": ""},
    {"name": "Miami Beach Florida Tower", "city": "Miami Beach", "section": "commercial",
     "search_terms": ["Florida Tower"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/59475894/photos",
     "date_start": "30 Jan 2024", "date_end": "2 Mar 2026", "notes": ""},
    {"name": "Jupiter River Place Condos", "city": "Jupiter", "section": "commercial",
     "search_terms": ["River Place"], "youtube_url": "https://www.youtube.com/watch?v=XECfokKx3Hs",
     "companycam_url": "https://app.companycam.com/projects/78679624/photos",
     "date_start": "Mar 2025", "date_end": "Aug 2025",
     "notes": "Additional video: https://www.youtube.com/watch?v=XKt1lnZFG8I"},
    {"name": "Fort Lauderdale Alhambra Coating", "city": "Fort Lauderdale", "section": "commercial",
     "search_terms": ["Alhambra"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/65412482/photos",
     "date_start": "Jun 2024", "date_end": "Jan 2026", "notes": ""},
    {"name": "Sunny Isles Beach The Pinnacle Condo Association", "city": "Sunny Isles Beach", "section": "commercial",
     "search_terms": ["Pinnacle"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/63312314/photos",
     "date_start": "29 Apr 2024", "date_end": "13 Jul 2026", "notes": "May be 2 different jobs — verify with Tim."},
    {"name": "Miami D&L Office Park", "city": "Miami", "section": "commercial",
     "search_terms": ["D&L", "D & L"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/52940807/photos",
     "date_start": "18 Jul 2023", "date_end": "2 Apr 2024", "notes": ""},
    {"name": "Miami Beach Olsen Condo", "city": "Miami Beach", "section": "commercial",
     "search_terms": ["Olsen"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/38781677/photos",
     "date_start": "28 Apr 2022", "date_end": "5 Dec 2024", "notes": ""},
    {"name": "Abacoa Jupiter Tile Tower Roof", "city": "Jupiter", "section": "residential",
     "search_terms": ["Abacoa"], "youtube_url": "https://www.youtube.com/watch?v=FJYcbDGZ8Ik",
     "companycam_url": "", "date_start": "", "date_end": "16 Jul 2025", "notes": ""},
    {"name": "SL Construction Boca Raton Roof Replacement", "city": "Boca Raton", "section": "residential",
     "search_terms": ["SL Construction"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/82079257/photos",
     "date_start": "", "date_end": "Jun 2026", "notes": "Roof replaced."},
    {"name": "Jim Malooly Delray Beach Roof", "city": "Delray Beach", "section": "residential",
     "search_terms": ["Malooly"], "youtube_url": None,
     "companycam_url": "https://app.companycam.com/projects/105307945/photos",
     "date_start": "", "date_end": "", "notes": "In progress — still need final images."},
]


def _video_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    q = parse_qs(urlparse(url).query)
    return q.get("v", [None])[0]


def _make_session(db_url: str, tenant_id: int):
    engine = create_engine(db_url, future=True)
    factory = sessionmaker(bind=engine, future=True)
    register_tenant_session_events(factory, strict=True)
    session = factory()
    session.info["tenant_id"] = tenant_id
    return session, engine


def match_knowify(session, tenant_id: int, terms: list[str]) -> dict:
    """Search projects -> contracts -> clients (in that preference order) for the first
    term that hits. Returns a normalized dict; all keys None/"" when nothing matches."""
    from app.models import KnowifyRawRecord

    for term in terms:
        for entity in ("projects", "contracts", "clients"):
            rows = session.execute(
                select(KnowifyRawRecord.knowify_id, KnowifyRawRecord.payload).where(
                    KnowifyRawRecord.tenant_id == tenant_id,
                    KnowifyRawRecord.entity == entity,
                    KnowifyRawRecord.is_present.is_(True),
                    cast(KnowifyRawRecord.payload, String).ilike(f"%{term}%"),
                )
            ).all()
            if not rows:
                continue
            with_city = [r for r in rows if r.payload.get("City")]
            row = (with_city or rows)[0]
            payload = row.payload
            return {
                "matched": True,
                "entity": entity,
                "knowify_id": row.knowify_id,
                "city": payload.get("City"),
                "contract_type": payload.get("ContractType"),
                "knowify_name": (
                    payload.get("ProjectName") or payload.get("ContractName")
                    or payload.get("ClientName") or payload.get("CompanyName")
                ),
                "start_date": payload.get("StartDate") or payload.get("DateCreated"),
                "end_date": payload.get("ExpirationDate") or payload.get("DueDate"),
            }
    return {"matched": False, "entity": None, "knowify_id": None, "city": None,
            "contract_type": None, "knowify_name": None, "start_date": None, "end_date": None}


def video_context(session, video_id: str | None) -> dict:
    """Video title/upload_date + a short transcript excerpt for write-up grounding."""
    if not video_id:
        return {"title": None, "upload_date": None, "transcript_excerpt": ""}
    from app.models import Chunk, Video

    v = session.get(Video, video_id)
    chunks = session.execute(
        select(Chunk.text).where(Chunk.video_id == video_id).order_by(Chunk.start).limit(20)
    ).scalars().all()
    excerpt = " ".join(chunks)[:800]
    return {
        "title": v.title if v else None,
        "upload_date": v.upload_date if v else None,
        "transcript_excerpt": excerpt,
    }


def build_record(session, tenant_id: int, candidate: dict) -> dict:
    km = match_knowify(session, tenant_id, candidate["search_terms"])
    video_id = _video_id_from_url(candidate["youtube_url"])
    vc = video_context(session, video_id)

    city = candidate["city"] or km["city"] or ""
    completion_date = candidate["date_end"] or km["end_date"] or vc["upload_date"] or ""
    start_date = candidate["date_start"] or km["start_date"] or ""
    property_type = infer_property_type(km["contract_type"], candidate["name"]) or ""
    new_roof_type = infer_roof_type(candidate["name"], vc["title"], vc["transcript_excerpt"])

    return {
        "name": candidate["name"],
        "city": city,
        "section": candidate["section"],
        "companycam_url": candidate["companycam_url"],
        "youtube_url": candidate["youtube_url"] or "",
        "property_type": property_type,
        "completion_date": completion_date,
        "start_date": start_date,
        "original_roof_type": "",  # not derivable from any available source
        "new_roof_type": new_roof_type or "",
        "reason": "",  # not derivable from any available source
        "doc_notes": candidate["notes"],
        "knowify_match": km,
        "video": vc,
    }


WRITEUP_PROMPT = """Write a 300-500 word professional project write-up for a commercial/residential
roofing contractor's portfolio page. Use ONLY the facts given below — do NOT invent square
footage, exact dates, product names, or manufacturers that are not listed. If a detail (like
roof size or specific products used) is not given, write around it in general professional
language instead of guessing a number.

Project name: {name}
City: {city}
Property type: {property_type}
Completion date: {completion_date}
Duration/start: {start_date}
Roof type worked: {roof_type}
Notes: {notes}
Site narration excerpt (tone/context only, do not treat as a source of new facts): {transcript}

Return the write-up as HTML paragraphs (<p> tags), no heading, no markdown."""


def generate_writeup(llm, record: dict) -> str:
    prompt = WRITEUP_PROMPT.format(
        name=record["name"], city=record["city"] or "South Florida",
        property_type=record["property_type"] or "not specified",
        completion_date=record["completion_date"] or "recent",
        start_date=record["start_date"] or "not specified",
        roof_type=record["new_roof_type"] or "not specified",
        notes=record["doc_notes"] or "none",
        transcript=record["video"]["transcript_excerpt"] or "none",
    )
    html = llm.chat(prompt)
    if "<p>" not in html:
        html = f"<p>{html}</p>"
    return html


def write_csv(path: Path, records: list[dict]) -> None:
    from core.portfolio import QUESTIONNAIRE_FIELDS

    with path.open("w", newline="") as f:
        w = csv.writer(f)
        for rec in records:
            w.writerow([f"=== {rec['name']} ==="])
            w.writerow(["Info Required", "Perkins response", "source-note"])
            q = rec["questionnaire"]
            for field in QUESTIONNAIRE_FIELDS:
                source = "prefilled" if q[field] else "NEEDS HUMAN"
                w.writerow([field, q[field], source])
            w.writerow([])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=None)
    ap.add_argument("--tenant-id", type=int, default=1)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    import os

    db_url = args.db_url or os.environ["DB_URL"]
    session, engine = _make_session(db_url, args.tenant_id)

    from adapters.llm import CloudflareLLM

    llm = CloudflareLLM()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    matched, unmatched = 0, 0
    try:
        for candidate in CANDIDATES:
            record = build_record(session, args.tenant_id, candidate)
            record["content_html"] = generate_writeup(llm, record)
            record["questionnaire"] = map_to_questionnaire(record)
            record["needs_human"] = needs_human(record["questionnaire"])
            record["post"] = map_to_post(record, content_html=record["content_html"])
            records.append(record)
            if record["knowify_match"]["matched"]:
                matched += 1
            else:
                unmatched += 1
            print(f"  {record['name']}: knowify={'HIT' if record['knowify_match']['matched'] else 'miss'}, "
                  f"needs_human={len(record['needs_human'])}/{len(record['questionnaire'])}")
    finally:
        session.close()
        engine.dispose()

    (out_dir / "portfolio_records.json").write_text(json.dumps(records, indent=2, default=str))
    write_csv(out_dir / "wendy_sheet_filled.csv", records)

    print(f"\n{matched} matched in Knowify, {unmatched} unmatched, out of {len(CANDIDATES)} candidates")
    print(f"Wrote {out_dir / 'portfolio_records.json'}")
    print(f"Wrote {out_dir / 'wendy_sheet_filled.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
