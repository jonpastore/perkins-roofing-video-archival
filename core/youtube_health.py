"""YouTube catalog + pull-block signals for the weekly digest.

Catalog comes from the videos / ingestion_runs tables. Block detection is
conservative: only bot-check strings count as blocked. Stale newest video or
an unarchived backlog is a pull problem, not proof of a bot-block.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

BOT_MARKERS = (
    "sign in to confirm",
    "not a bot",
    "bot-block",
    "only images are available",
    "confirm you're not a bot",
    "confirm youre not a bot",
)

YOUTUBE_SCAN_TYPES = ("youtube_enumerate", "youtube_archive", "youtube")
CATALOG_TABS = frozenset({"videos", "shorts"})


def parse_upload_date(raw: Any) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def is_bot_block(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in BOT_MARKERS)


def is_absent_optional_tab(tab: str, error: str) -> bool:
    """True when this is 'channel has no Live tab', not a catalog miss.

    Perkins rarely livestreams. YouTube's /streams tab 404s or yt-dlp exits 1
    on that channel every morning. videos/shorts failing, a bot wall, or a
    timeout is a real miss.
    """
    if tab in CATALOG_TABS:
        return False
    if is_bot_block(error):
        return False
    err = (error or "").lower()
    if "timeout" in err or "timed out" in err:
        return False
    return True


def material_failed_tabs(failed_tabs: list[str] | None) -> list[str]:
    return [t for t in (failed_tabs or []) if t in CATALOG_TABS]


def classify_pull(*, newest_age_days: int | None, unarchived: int,
                  bot_hits: int, failed_tabs: list[str], incomplete: bool) -> dict[str, Any]:
    """Return blocked / pull_ok / reasons. Bot-check only sets blocked."""
    reasons: list[str] = []
    blocked = bot_hits > 0
    if blocked:
        reasons.append(f"yt-dlp bot-check in {bot_hits} ingest error(s)")
    material = material_failed_tabs(failed_tabs)
    if material or incomplete:
        reasons.append(
            "enumerate incomplete"
            + (f" (failed tabs: {', '.join(material or failed_tabs)})" if (material or failed_tabs) else "")
        )
    if unarchived:
        reasons.append(f"{unarchived} video(s) still unarchived")
    if newest_age_days is not None and newest_age_days > 14:
        reasons.append(f"newest catalog video is {newest_age_days} days old")
    pull_ok = not blocked and not material and not incomplete and unarchived == 0
    return {"blocked": blocked, "pull_ok": pull_ok, "reasons": reasons}


def _newest(videos: list[Any]) -> Any | None:
    dated = [(parse_upload_date(v.upload_date), v) for v in videos]
    dated = [(d, v) for d, v in dated if d is not None]
    if not dated:
        return videos[0] if videos else None
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return dated[0][1]


def _scan_signals(scans: list[dict[str, Any]]) -> dict[str, Any]:
    failed_tabs: list[str] = []
    incomplete = False
    latest: dict[str, dict[str, Any]] = {}
    for item in scans:
        kind = item.get("scan_type") or ""
        if kind not in YOUTUBE_SCAN_TYPES:
            continue
        prev = latest.get(kind)
        if prev is None or (item.get("ran_at") or "") >= (prev.get("ran_at") or ""):
            latest[kind] = item
        failed_tabs.extend(item.get("failed_tabs") or [])
        if item.get("incomplete"):
            incomplete = True
    # Prefer the newest enumerate row's tabs over a union of the whole week.
    enum = latest.get("youtube_enumerate") or {}
    if enum:
        failed_tabs = list(enum.get("failed_tabs") or [])
        incomplete = bool(enum.get("incomplete"))
    return {"failed_tabs": failed_tabs, "incomplete": incomplete, "latest": latest}


def collect_youtube_health(db, since: datetime, *, now: datetime | None = None) -> dict[str, Any]:
    from app.models import IngestionRun, Video  # noqa: PLC0415

    now = now or datetime.utcnow()
    videos = db.query(Video).all()
    newest = _newest(videos)
    newest_dt = parse_upload_date(getattr(newest, "upload_date", None)) if newest else None
    newest_age = (now.date() - newest_dt.date()).days if newest_dt else None
    since_key = since.strftime("%Y%m%d")
    new_this_week = []
    unarchived = []
    for v in videos:
        if not getattr(v, "archive_uri", None):
            unarchived.append(v)
        ud = (getattr(v, "upload_date", None) or "").replace("-", "")
        if ud >= since_key:
            new_this_week.append(v)

    ingest_rows = db.query(IngestionRun).all()
    ingest_errors = []
    bot_hits = 0
    for row in ingest_rows:
        if (row.status or "") not in ("error", "failed"):
            continue
        err = (row.last_error or "")[:240]
        ingest_errors.append({
            "video_id": row.video_id,
            "stage": row.stage,
            "error": err,
        })
        if is_bot_block(err):
            bot_hits += 1

    from_scans = _scan_signals(_scan_rows(db, since))
    verdict = classify_pull(
        newest_age_days=newest_age,
        unarchived=len(unarchived),
        bot_hits=bot_hits,
        failed_tabs=from_scans["failed_tabs"],
        incomplete=from_scans["incomplete"],
    )
    return {
        "videos": len(videos),
        "archived": len(videos) - len(unarchived),
        "unarchived": len(unarchived),
        "unarchived_ids": [v.id for v in unarchived[:20]],
        "new_this_week": len(new_this_week),
        "new_titles": [v.title for v in new_this_week[:15] if getattr(v, "title", None)],
        "newest_id": getattr(newest, "id", None),
        "newest_title": getattr(newest, "title", None),
        "newest_upload_date": getattr(newest, "upload_date", None) if newest else None,
        "newest_age_days": newest_age,
        "unavailable": sum(1 for v in videos if getattr(v, "unavailable_since", None)),
        "ingest_errors": ingest_errors[:15],
        "ingest_error_count": len(ingest_errors),
        "bot_hits": bot_hits,
        "failed_tabs": from_scans["failed_tabs"],
        "incomplete": from_scans["incomplete"],
        "scans": list(from_scans["latest"].values()),
        **verdict,
    }


def _scan_rows(db, since: datetime) -> list[dict[str, Any]]:
    from app.models import ScanReport  # noqa: PLC0415

    try:
        rows = db.query(ScanReport).filter(ScanReport.ran_at >= since).all()
    except Exception:
        db.rollback()
        return []
    out = []
    for row in rows:
        payload = dict(row.payload or {})
        out.append({
            "scan_type": row.scan_type,
            "ran_at": row.ran_at.isoformat(timespec="seconds") if row.ran_at else None,
            **payload,
        })
    return out


def apply_job_runs(youtube: dict[str, Any], jobs: dict[str, Any]) -> dict[str, Any]:
    """Copy last enumerate/archive/ingest executions onto the YouTube payload."""
    wanted = {"enumerate-channel", "archive", "ingest", "run-ingest"}
    runs = [j for j in (jobs.get("jobs") or []) if j.get("name") in wanted]
    youtube["job_runs"] = runs
    failed = [j["name"] for j in runs if j.get("attention") == "failed"]
    if failed:
        youtube["pull_ok"] = False
        youtube.setdefault("reasons", []).append("job failed: " + ", ".join(failed))
    return youtube


def apply_block_logs(youtube: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    youtube["recent_blocks"] = hits
    if hits:
        youtube.setdefault("reasons", []).append(
            f"{len(hits)} YouTube bot-block log line(s) this week"
        )
        # Historic rotation-recovered blocks do not flip blocked if the catalog is current.
        if youtube.get("unarchived", 0) > 0 or youtube.get("incomplete"):
            youtube["blocked"] = True
            youtube["pull_ok"] = False
    return youtube


def fetch_bot_block_logs(*, hours: int = 24 * 7, limit: int = 15,
                         reader=None) -> list[dict[str, Any]]:
    """Best-effort Cloud Logging scan for yt-dlp bot-check lines. Never raises."""
    try:
        if reader is None:
            from adapters.gcp_logging import recent_errors  # noqa: PLC0415
            reader = recent_errors
        entries = reader(hours=hours, severity="WARNING", limit=80)
    except Exception:
        return []
    hits = []
    for entry in entries:
        msg = entry.get("message") or ""
        if not is_bot_block(msg) and "bot-blocked" not in msg.lower():
            continue
        hits.append({
            "timestamp": entry.get("timestamp"),
            "resource": entry.get("resource"),
            "message": msg[:240],
        })
        if len(hits) >= limit:
            break
    return hits
