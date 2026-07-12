#!/usr/bin/env python3
"""Append-only topic re-mining for under-covered long-form videos.

The original Content Graph prompt capped long videos to the first ~9k chars and max 8 topics.
This script DOES NOT delete/rebuild graph nodes and DOES NOT reset ingest stages. It only:
  1. selects videos matching the user-approved heuristic:
       video.duration_seconds > SUM(existing topic start seconds)
  2. re-runs the topic extractor against the cached transcript segments,
  3. appends only new topic labels that do not already exist for that video.

Dry-run by default. Use --apply to write. This avoids orphaning/churning existing article/social/FAQ
relationships, which are video/slug based and should remain stable.

Usage:
    PYTHONPATH=. python scripts/append_undercovered_topics.py --limit 10
    PYTHONPATH=. python scripts/append_undercovered_topics.py --video-id <id> --apply
    PYTHONPATH=. python scripts/append_undercovered_topics.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess

from sqlalchemy import and_, create_engine, func
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.llm import chat
from app.models import GraphNode, Segment, Video
from core import graph as core_graph


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()


def _candidates(session, *, limit: int | None = None, video_id: str | None = None):
    topic_sum = func.coalesce(func.sum(GraphNode.start), 0)
    q = (
        session.query(
            Video.id,
            Video.title,
            Video.duration,
            func.count(GraphNode.id).label("topic_count"),
            topic_sum.label("topic_time_sum"),
            func.max(GraphNode.start).label("last_topic_at"),
        )
        .outerjoin(GraphNode, and_(GraphNode.video_id == Video.id, GraphNode.kind == "topics"))
        .filter(Video.duration.isnot(None), Video.duration > 0)
        .group_by(Video.id, Video.title, Video.duration)
        .having(Video.duration > topic_sum)
        .order_by(Video.duration.desc())
    )
    if video_id:
        q = q.filter(Video.id == video_id)
    if limit:
        q = q.limit(limit)
    return q.all()


def _segment_windows(segs: list[dict], *, char_budget: int) -> list[list[dict]]:
    windows: list[list[dict]] = []
    current: list[dict] = []
    chars = 0
    for seg in segs:
        add = len(seg.get("text") or "") + 16
        if current and chars + add > char_budget:
            windows.append(current)
            current = []
            chars = 0
        current.append(seg)
        chars += add
    if current:
        windows.append(current)
    return windows


def _extract_topics_windowed(seg_dicts: list[dict], *, char_budget: int) -> list[dict]:
    rows: list[dict] = []
    for window in _segment_windows(seg_dicts, char_budget=char_budget):
        prompt = core_graph.build_extract_prompt(window)
        data = chat(prompt, want_json=True)
        rows.extend(
            r for r in core_graph.parse_nodes(data, settings.GRAPH_VERSION)
            if r.get("kind") == "topics" and r.get("label")
        )
    return rows


def _append_topics_for_video(
    session,
    video_id: str,
    *,
    apply: bool,
    start_after: float | None,
    char_budget: int,
) -> tuple[int, int, int]:
    q = (
        session.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.start)
    )
    if start_after is not None:
        q = q.filter(Segment.start > start_after)
    segs = q.all()
    if not segs:
        return 0, 0, 0
    seg_dicts = [{"text": s.text or "", "start": float(s.start or 0)} for s in segs]

    existing = {
        _norm(label)
        for (label,) in session.query(GraphNode.label)
        .filter(GraphNode.video_id == video_id, GraphNode.kind == "topics")
        .all()
        if label
    }

    extracted = _extract_topics_windowed(seg_dicts, char_budget=char_budget)
    new_rows = []
    seen = set(existing)
    for row in extracted:
        label = str(row.get("label") or "").strip()
        key = _norm(label)
        if not key or key in seen:
            continue
        seen.add(key)
        new_rows.append(row)

    if apply:
        for row in new_rows:
            session.add(GraphNode(video_id=video_id, **row))
        session.flush()
    return len(_segment_windows(seg_dicts, char_budget=char_budget)), len(extracted), len(new_rows)


def _session_factory(*, cloud_sql: bool):
    if not cloud_sql:
        from app.models import SessionLocal  # noqa: PLC0415
        return SessionLocal, None

    from google.cloud.sql.connector import Connector  # noqa: PLC0415

    from core.tenant import register_tenant_session_events  # noqa: PLC0415

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen")
    region = os.environ.get("GCP_REGION", "us-central1")
    instance = os.environ.get("CLOUDSQL_INSTANCE", f"{project}-pg")
    conn_name = f"{project}:{region}:{instance}"
    password = subprocess.check_output([
        "gcloud", "secrets", "versions", "access", "latest",
        "--secret=db-password", "--project", project,
    ]).decode().strip()
    connector = Connector()

    def getconn():
        return connector.connect(conn_name, "pg8000", user="app", password=password, db="perkins")

    engine = create_engine("postgresql+pg8000://", creator=getconn, future=True)
    factory = sessionmaker(bind=engine, future=True)
    register_tenant_session_events(factory, strict=True)
    return factory, connector


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write missing topic rows (default is dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="cap candidate videos processed")
    ap.add_argument("--video-id", default=None, help="process one video id only")
    ap.add_argument("--tenant-id", type=int, default=1)
    ap.add_argument("--cloud-sql", action="store_true", help="connect to prod Cloud SQL via Python Connector")
    ap.add_argument("--char-budget", type=int, default=12000, help="transcript chars per LLM window")
    args = ap.parse_args()

    SessionFactory, connector = _session_factory(cloud_sql=args.cloud_sql)
    session = SessionFactory()
    session.info["tenant_id"] = args.tenant_id
    try:
        rows = _candidates(session, limit=args.limit or None, video_id=args.video_id)
        print(f"undercovered candidates: {len(rows)}  mode={'APPLY' if args.apply else 'DRY-RUN'}", flush=True)
        total_new = 0
        for video_id, title, duration, topic_count, topic_sum, last_topic_at in rows:
            try:
                windows, extracted, new_count = _append_topics_for_video(
                    session,
                    video_id,
                    apply=args.apply,
                    start_after=float(last_topic_at) if last_topic_at is not None else None,
                    char_budget=args.char_budget,
                )
                if args.apply:
                    session.commit()
                else:
                    session.rollback()
                total_new += new_count
                print(
                    f"{video_id} topics={topic_count} duration={float(duration):.0f}s "
                    f"sum_topic_time={float(topic_sum or 0):.0f}s last_topic={float(last_topic_at or 0):.0f}s "
                    f"windows={windows} extracted_topics={extracted} new_topics={new_count} title={title!r}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                print(f"ERROR {video_id}: {type(exc).__name__}: {str(exc)[:180]}", flush=True)
        if args.apply:
            print(f"appended new topics: {total_new}", flush=True)
        else:
            print(f"dry-run new topics that would be appended: {total_new}", flush=True)
        return 0
    finally:
        session.close()
        if connector is not None:
            connector.close()


if __name__ == "__main__":
    raise SystemExit(main())
