"""Classify digest/ops problems into actionable issues.

One list feeds the weekly digest (floated to the top) and the on-change
alert email. Keys are stable so we only email when a new key appears.
"""
from __future__ import annotations

import json
from typing import Any

from core.email_template import wrap_email
from core.profit_alerts import PROFIT_FLOOR_NOTIFY

ON_DEMAND_JOBS = frozenset({
    "render", "article", "social", "proposal-pdf-backfill",
})
PAUSED_FIX = (
    "Paused on purpose in Terraform. Leave it until the underlying bug is fixed, "
    "then set paused=false and apply."
)
JOB_FIX = {
    "companycam-sync": (
        "A CompanyCam playback URL exceeded varchar(1000). Code now clips URLs to 1000 chars "
        "and migration 0061 widens url/thumbnail_url to TEXT. Commit/deploy both so the "
        "06:00 ET sync stops dying. Until deploy, the job will keep failing."
    ),
    "knowify-keepwarm": (
        "Token refresh is already wired (02:00 ET keep-warm + refresh-on-use). "
        "If this is red, Log in from Data sources on Legacy Data / Portfolio / "
        "Admin → Marketing, or run "
        "python scripts/knowify/knowify_oauth.py --mcp --bootstrap-secret. "
        "A live token was written 2026-08-17; next keep-warm should go green."
    ),
    "knowify-sync": (
        "Paused on purpose while Knowify REST OAuth 500s. Sync uses MCP after a live token. "
        "Leave paused until --mcp login + keep-warm succeeds, then set paused=false in Terraform."
    ),
    "proposal-reminders-daily": (
        "Paused 2026-07-14 pending review of customer-facing email. Leave paused while "
        "EMAIL_SEND_MODE=test. Set paused=false in Terraform only when you want reminders live."
    ),
    "archive": (
        "Archive failed. Check Cloud Run logs for bot-check / timeout. "
        "If videos are already in GCS, reset stuck transcript rows instead of re-downloading."
    ),
    "enumerate-channel": (
        "Enumerate failed. If videos/shorts tabs failed, YouTube blocked the pull. "
        "streams failing alone is noise."
    ),
    "ingest": (
        "Ingest failed. Transcript needs archive_uri. Reset pending transcript rows "
        "after archive succeeds (Status → retry, or POST /status/retry)."
    ),
    "weekly-digest": (
        "No Cloud Scheduler job in GCP yet. Commit/deploy the weekly-digest resource."
    ),
}


def collect_issues(payload: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    issues.extend(_youtube_issues(payload.get("youtube") or {}))
    issues.extend(_job_issues(payload.get("scheduled_jobs") or {}))
    issues.extend(_spend_issues(payload.get("cloud_spend") or {}))
    issues.extend(_profit_issues(payload.get("profit_below_minimum") or []))
    issues.extend(_scan_issues(payload))
    rank = {"error": 0, "warning": 1}
    return sorted(issues, key=lambda i: (rank.get(i["severity"], 9), i["title"]))


def issue_keys(issues: list[dict[str, str]]) -> list[str]:
    return [i["key"] for i in issues]


def new_issue_keys(current: list[dict[str, str]], previous: list[str] | set[str]) -> list[str]:
    prev = set(previous)
    return [i["key"] for i in current if i["key"] not in prev]


def _issue(key: str, severity: str, title: str, detail: str, fix: str) -> dict[str, str]:
    return {
        "key": key,
        "severity": severity,
        "title": title,
        "detail": detail,
        "fix": fix,
    }


def _youtube_issues(yt: dict[str, Any]) -> list[dict[str, str]]:
    if not yt:
        return []
    out: list[dict[str, str]] = []
    if yt.get("blocked"):
        out.append(_issue(
            "youtube.blocked", "error",
            "YouTube pull is BLOCKED",
            "yt-dlp hit the bot wall and we still cannot download.",
            "Check WireGuard configs (secret wireguard-configs). "
            "Archive job rotates egress; if all exits are blocked, refresh the VPN peers.",
        ))
    elif yt.get("incomplete"):
        out.append(_issue(
            "youtube.incomplete", "error",
            "Enumerate incomplete",
            f"Failed tabs: {', '.join(yt.get('failed_tabs') or []) or 'unknown'}.",
            "videos/shorts failing means the catalog is wrong. Re-run enumerate-channel. "
            "streams alone can be ignored.",
        ))
    elif yt.get("failed_tabs"):
        out.append(_issue(
            "youtube.tab:" + ",".join(yt["failed_tabs"]), "warning",
            "Enumerate tab failed: " + ", ".join(yt["failed_tabs"]),
            "Non-critical if only streams. videos/shorts is a real miss.",
            "Ignore streams. If videos or shorts appear here, re-run enumerate-channel.",
        ))
    waiting = set(yt.get("unarchived_ids") or [])
    if waiting and not yt.get("blocked"):
        out.append(_issue(
            "youtube.unarchived", "error",
            f"{len(waiting)} video(s) still unarchived",
            "Ids: " + ", ".join(list(waiting)[:12]),
            "Run the archive Cloud Run job. If it bot-blocks, refresh wireguard-configs.",
        ))
    for err in yt.get("ingest_errors") or []:
        vid = err.get("video_id") or "?"
        raw = err.get("error") or ""
        if "no archive_uri" in raw and vid not in waiting:
            out.append(_issue(
                f"ingest.stale:{vid}", "warning",
                f"Transcript stuck for {vid}",
                "Ingest tried STT before the MP4 landed. The file is in GCS now.",
                "POST /status/retry {video_id, stage: transcript} then let run-ingest pick it up "
                "(09:00–18:00 ET), or gcloud run jobs execute ingest.",
            ))
        elif "no archive_uri" in raw:
            out.append(_issue(
                f"ingest.no_archive:{vid}", "error",
                f"Transcript blocked — {vid} has no MP4",
                raw,
                "Archive that video first, then retry the transcript stage.",
            ))
    return out


def _job_issues(blob: dict[str, Any]) -> list[dict[str, str]]:
    if not blob.get("ok"):
        return [_issue(
            "jobs.unavailable", "warning",
            "Could not read scheduled jobs",
            blob.get("error") or "unavailable",
            blob.get("hint") or "Grant cloudscheduler.viewer and run.viewer to the API SA.",
        )]
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for job in list(blob.get("schedulers") or []) + list(blob.get("run_jobs") or []):
        name = job.get("name") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        attention = job.get("attention") or ""
        if attention == "ok":
            continue
        detail = job.get("message") or job.get("last_execution") or job.get("last_attempt") or ""
        if attention == "paused":
            out.append(_issue(
                f"job.paused:{name}", "warning",
                f"{name} is paused",
                detail or "Cloud Scheduler state=PAUSED.",
                JOB_FIX.get(name, PAUSED_FIX),
            ))
            continue
        if name in ON_DEMAND_JOBS:
            out.append(_issue(
                f"job.on_demand:{name}", "warning",
                f"{name} last on-demand run failed",
                detail,
                "Not a cron. Re-run from the UI if you still need that render/article.",
            ))
            continue
        out.append(_issue(
            f"job.{attention}:{name}", "error",
            f"{name} {attention}",
            detail,
            JOB_FIX.get(name, "Open Cloud Run / Cloud Scheduler logs for this job and re-run it."),
        ))
    return out


def _spend_issues(spend: dict[str, Any]) -> list[dict[str, str]]:
    if spend.get("ok"):
        return []
    return [_issue(
        "spend.unavailable", "warning",
        "Cloud spend unavailable",
        spend.get("error") or "unknown",
        "Grant billing.budgets.viewer on billing account 01549D-4220C6-D775AD to "
        "api-run-sa. That is a billing-account IAM grant, not a project role — "
        "a billing admin must do it. The digest still sends without a number.",
    )]


def _profit_issues(below: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not below:
        return []
    ids = ", ".join(f"#{b.get('id')}" for b in below[:8])
    return [_issue(
        "profit.below", "warning",
        f"{len(below)} quote(s) under $2,500 profit",
        ids,
        "Advisory only — the quote was not blocked. Review in Quoting.",
    )]


def _scan_issues(payload: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for s in payload.get("scans_latest") or payload.get("scans") or []:
        if s.get("error"):
            kind = s.get("scan_type") or "scan"
            out.append(_issue(
                f"scan.error:{kind}", "error",
                f"{kind} scan failed",
                str(s["error"]),
                "Re-run the daily portfolio scan. If the table is missing, apply migration 0060.",
            ))
    return out


def persist_and_diff(db, issues: list[dict[str, str]]) -> list[dict[str, str]]:
    """Store current keys on the ops_alerts status row. Return newly appeared issues."""
    from datetime import datetime, timezone  # noqa: PLC0415

    from app.models import IntegrationStatus  # noqa: PLC0415

    row = (
        db.query(IntegrationStatus)
        .filter(IntegrationStatus.tenant_id.is_(None),
                IntegrationStatus.integration == "ops_alerts")
        .first()
    )
    if row is None:
        row = IntegrationStatus(
            tenant_id=None, integration="ops_alerts",
            status="unconfigured", consecutive_failures=0,
        )
        db.add(row)
        db.flush()
    try:
        prev = set(json.loads(row.last_error or "[]"))
    except (TypeError, ValueError):
        prev = set()
    current = issue_keys(issues)
    fresh_keys = set(current) - prev
    row.last_error = json.dumps(sorted(current))
    row.last_checked = datetime.now(timezone.utc).replace(tzinfo=None)
    row.status = "broken" if any(i["severity"] == "error" for i in issues) else "healthy"
    db.add(row)
    return [i for i in issues if i["key"] in fresh_keys]


def render_ops_html(issues: list[dict[str, str]], *, intro: str) -> str:
    from core.weekly_digest import LOGO_URL, _esc, _section, _status_cell  # noqa: PLC0415

    if not issues:
        rows = [[_esc("None"), _esc("—"), _esc("No errors or warnings right now.")]]
    else:
        rows = [
            [
                _status_cell(i["severity"], "failed" if i["severity"] == "error" else "warn"),
                _esc(f"{i['title']}. {i['detail']}".strip()),
                _esc(i["fix"]),
            ]
            for i in issues
        ]
    body = (
        f'<p style="margin:0 0 16px; font-size:14px;">{_esc(intro)}</p>'
        + _section(
            "Needs action",
            "Errors first, then warnings. Fix column is the next step.",
            ["Severity", "Issue", "How to fix"],
            rows,
        )
    )
    header = (
        f'<img src="{_esc(LOGO_URL)}" alt="Perkins Roofing" width="180" '
        'style="display:block; border:0; max-width:180px; height:auto;">'
    )
    return wrap_email(
        body_html=body,
        header_html=header,
        company_name="Perkins Roofing",
        header_bg="#ffffff",
    )


def send_ops_alert(issues: list[dict[str, str]], *, tenant_id: int | None = None) -> list[str]:
    if not issues:
        return []
    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    subject = f"Perkins ops: {errors} error(s), {warnings} warning(s)"
    html = render_ops_html(
        issues,
        intro="New error or warning since the last check. Address the How to fix column.",
    )
    try:
        from core.email_gate import decide  # noqa: PLC0415
        import adapters.resend as resend  # noqa: PLC0415
    except Exception:
        return []
    ids: list[str] = []
    for to in PROFIT_FLOOR_NOTIFY:
        if not decide(to).allowed:
            continue
        ids.append(resend.send(
            reply_to=to,
            to=to,
            subject=subject,
            html=html,
            tenant_id=tenant_id,
            send_type="ops_alert",
            metadata={"issue_keys": issue_keys(issues), "errors": errors, "warnings": warnings},
        ))
    return ids
