"""Cloud Run Job: enumerate the full Perkins channel (videos + shorts + streams) and
upsert Video rows. Idempotent — re-running refreshes titles/urls, adds new videos.

Run: .venv/bin/python -m jobs.enumerate_channel [limit_per_tab]
"""
import sys

from adapters.yt_dlp import list_channel
from app.models import SessionLocal, Video, init_db
from core.enumerate import to_video_rows

CHANNEL_ID = "UChJZpBYXOuR0j1EHJugv5hg"  # Perkins Roofing Corp (tenant-1 fallback)


def _channel_ids_for_tenant(db, tenant_id: int) -> list[str]:
    """Return the list of YouTube channel IDs configured for this tenant.

    Reads kb.channel_sources from tenants.settings via TenantSettings. For tenant 1
    with no channel_sources configured, falls back to the legacy Perkins channel ID.
    Returns an empty list when channel_sources is explicitly set to [] (skip tenant).
    """
    from sqlalchemy import text  # noqa: PLC0415

    from core.tenant_settings import TenantSettings  # noqa: PLC0415

    row = db.execute(
        text("SELECT settings FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    ).fetchone()

    if row is None:
        return []

    raw_settings = row.settings if hasattr(row, "settings") else row[0]
    if not isinstance(raw_settings, dict):
        raw_settings = {}

    ts = TenantSettings.load(raw_settings)
    if ts.kb is not None and ts.kb.channel_sources:
        return list(ts.kb.channel_sources)

    # Tenant 1 fallback: use the hardcoded Perkins channel when no setting is configured.
    if tenant_id == 1:
        return [CHANNEL_ID]

    # Other tenants with no channel_sources configured: skip (return empty list).
    return []


def _run_for_tenant(db, tenant_id: int, channel_id=None, limit=None) -> dict:
    """Per-tenant channel enumeration body. Called by for_each_tenant via run().

    Loads channel_sources from TenantSettings kb. For tenant 1 with no setting,
    falls back to the legacy Perkins channel ID. Tenants with no channel_sources
    are skipped (returns zero-count result).
    """
    channel_ids = _channel_ids_for_tenant(db, tenant_id)
    if not channel_ids:
        return {"enumerated": 0, "shorts": 0, "videos_in_db": 0,
                "failed_tabs": [], "incomplete": False}

    # Use the first channel_id; multi-channel support is a future extension.
    resolved_channel_id = channel_ids[0]
    entries, failed = list_channel(resolved_channel_id, limit=limit)
    rows = to_video_rows(entries)
    for r in rows:
        v = db.get(Video, r["id"]) or Video(id=r["id"])
        v.title = r["title"] or v.title
        if r["duration"] is not None:
            v.duration = r["duration"]
        v.url = r["url"]
        db.add(v)
    db.commit()
    total = db.query(Video).count()
    incomplete = any(t in ("videos", "shorts") for t in failed)
    if failed:
        print(f"[warn] tabs failed during enumeration: {failed} (incomplete={incomplete})")
    return {"enumerated": len(rows),
            "shorts": sum(1 for r in rows if r["is_short"]),
            "videos_in_db": total,
            "failed_tabs": failed,
            "incomplete": incomplete}


def run(channel_id=CHANNEL_ID, limit=None):
    """Iterate active tenants and enumerate the channel for each."""
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    init_db()
    results: list[dict] = []

    def _fn(db, tenant_id: int) -> None:
        results.append(_run_for_tenant(db, tenant_id, channel_id=channel_id, limit=limit))

    for_each_tenant(SessionLocal, _fn)

    if not results:
        return {"enumerated": 0, "shorts": 0, "videos_in_db": 0, "failed_tabs": [], "incomplete": False}
    # Return the last tenant's result (channel enumeration is global; all tenants share the same channel)
    return results[-1]


if __name__ == "__main__":
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = run(limit=_limit)
    print(result)
    sys.exit(1 if result["incomplete"] else 0)  # non-zero exit on partial enumeration
