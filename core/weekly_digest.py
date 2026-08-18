"""Weekly digest: badges, pipeline, comments, spend, scans, profit floor.

Scans = persisted cron outcomes (today: portfolio readiness). Those rows live
in scan_reports. That table and the persist call are not in prod yet, so the
section is empty until that ships. The daily job still runs; it only logs.
"""
from __future__ import annotations

import html as _html
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from core.cloud_spend import fetch_cloud_spend
from core.email_template import wrap_email
from core.ops_issues import collect_issues
from core.profit_alerts import PROFIT_FLOOR_NOTIFY, WARNING_PREFIX, has_profit_below_minimum
from core.scheduled_jobs import fetch_scheduled_jobs
from core.suggestion_counts import compute_suggestion_counts
from core.youtube_health import (
    YOUTUBE_SCAN_TYPES,
    apply_block_logs,
    apply_job_runs,
    collect_youtube_health,
    fetch_bot_block_logs,
)

DIGEST_LOOKBACK_DAYS = 7
LOGO_URL = "https://app.perkinsroofing.net/perkins-logo.png"
_NAVY = "#1b2a52"
_LINE = "#edf0f3"
_MUTED = "#667085"


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.replace(tzinfo=None)


def proposal_total(snap: dict | None) -> float:
    if not snap:
        return 0.0
    totals = snap.get("project_totals") or {}
    for key in ("project_total", "total", "grand_total"):
        raw = totals.get(key)
        if raw is None:
            raw = snap.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _collect_audit(db, since: datetime) -> dict[str, Any]:
    from app.models import AuditLog  # noqa: PLC0415

    rows = db.query(AuditLog).filter(AuditLog.occurred_at >= since).all()
    by_action: Counter[str] = Counter()
    by_actor: Counter[str] = Counter()
    for row in rows:
        by_action[row.action or "(none)"] += 1
        by_actor[row.actor_email or "(system)"] += 1
    return {
        "audit_count": len(rows),
        "by_action": dict(by_action.most_common(20)),
        "by_actor": dict(by_actor.most_common(20)),
    }


def _collect_quotes(db, since: datetime) -> dict[str, Any]:
    from app.models import Estimate  # noqa: PLC0415

    estimates = db.query(Estimate).filter(Estimate.created_at >= since).all()
    below: list[dict[str, Any]] = []
    quote_value = 0.0
    for est in estimates:
        result = dict(est.result_json or {})
        total = float(result.get("project_total") or 0)
        quote_value += total
        profit = float(result.get("profit_dollars") or 0)
        flagged = has_profit_below_minimum(result) or any(
            str(w).startswith(WARNING_PREFIX) for w in (result.get("warnings") or [])
        )
        if flagged or profit + 1e-6 < 2500:
            below.append({
                "id": est.id,
                "created_by": est.created_by,
                "branch": est.branch,
                "profit": profit,
                "total": total,
                "roof_type": result.get("roof_type"),
            })
    return {
        "estimates": len(estimates),
        "quote_value": quote_value,
        "profit_below_minimum": below,
    }


def _collect_customers(db, since: datetime) -> dict[str, Any]:
    from app.models import Customer  # noqa: PLC0415

    rows = db.query(Customer).filter(Customer.created_at >= since).all()
    return {
        "customers_new": len(rows),
        "customer_names": [r.display_name for r in rows[:20] if r.display_name],
    }


def _collect_proposals(db, since: datetime) -> dict[str, Any]:
    from app.models import Proposal  # noqa: PLC0415

    created = db.query(Proposal).filter(Proposal.created_at >= since).all()
    signed = (
        db.query(Proposal)
        .filter(Proposal.status == "accepted", Proposal.accepted_at >= since)
        .all()
    )
    signed_value = sum(proposal_total(p.quote_snapshot) for p in signed)
    return {
        "proposals_created": len(created),
        "proposals_signed": len(signed),
        "signed_value": signed_value,
        "signed_titles": [p.title for p in signed[:15] if p.title],
    }


def _collect_comments(db, since: datetime) -> dict[str, Any]:
    from app.models import CommentDraft  # noqa: PLC0415

    new_rows = db.query(CommentDraft).filter(CommentDraft.created_at >= since).all()
    return {
        "comments_new": len(new_rows),
        "comments_need_reply": sum(
            1 for r in new_rows
            if r.needs_reply and (r.status or "") in ("pending", "drafted")
        ),
    }


def _collect_scans(db, since: datetime) -> dict[str, Any]:
    from app.models import ScanReport  # noqa: PLC0415

    try:
        scan_rows = db.query(ScanReport).filter(ScanReport.ran_at >= since).all()
    except Exception:
        db.rollback()
        scan_rows = []
    scans: list[dict[str, Any]] = []
    latest_by_type: dict[str, Any] = {}
    for row in scan_rows:
        payload = dict(row.payload or {})
        item = {
            "id": row.id,
            "scan_type": row.scan_type,
            "ran_at": row.ran_at.isoformat(timespec="seconds") if row.ran_at else None,
            "tenant_id": row.tenant_id,
            **payload,
        }
        scans.append(item)
        key = f"{row.scan_type}:{row.tenant_id}"
        prev = latest_by_type.get(key)
        if prev is None or (row.ran_at and row.ran_at >= prev["_ran"]):
            latest_by_type[key] = {**item, "_ran": row.ran_at}
    return {
        "scans": scans,
        "scans_latest": [{k: v for k, v in item.items() if k != "_ran"}
                         for item in latest_by_type.values()],
        "scan_runs": len(scan_rows),
    }


def collect_digest(db, *, now: datetime | None = None, lookback_days: int = DIGEST_LOOKBACK_DAYS) -> dict[str, Any]:
    now = _aware(now or datetime.utcnow())
    since = now - timedelta(days=lookback_days)
    payload: dict[str, Any] = {
        "since": since.isoformat(timespec="seconds"),
        "until": now.isoformat(timespec="seconds"),
    }
    payload.update(_collect_audit(db, since))
    payload.update(_collect_quotes(db, since))
    payload.update(_collect_customers(db, since))
    payload.update(_collect_proposals(db, since))
    payload.update(_collect_comments(db, since))
    payload.update(_collect_scans(db, since))
    try:
        payload["queues"] = compute_suggestion_counts(db)
    except Exception:
        payload["queues"] = {}
    try:
        yt = collect_youtube_health(db, since, now=now)
    except Exception:
        db.rollback()
        yt = {"blocked": False, "pull_ok": False, "reasons": ["catalog query failed"]}
    payload["cloud_spend"] = fetch_cloud_spend()
    jobs = fetch_scheduled_jobs()
    payload["scheduled_jobs"] = jobs
    payload["youtube"] = apply_block_logs(apply_job_runs(yt, jobs), fetch_bot_block_logs())
    payload["issues"] = collect_issues(payload)
    return payload


def _money(n: Any) -> str:
    try:
        return f"${float(n):,.0f}"
    except (TypeError, ValueError):
        return "$0"


def _esc(value: Any) -> str:
    return _html.escape("" if value is None else str(value))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(
        f'<th style="text-align:left; padding:8px 10px; font-size:12px; '
        f'letter-spacing:0.02em; text-transform:uppercase; color:{_MUTED}; '
        f'border-bottom:2px solid {_NAVY};">{_esc(h)}</th>'
        for h in headers
    )
    body = []
    for i, row in enumerate(rows):
        bg = "#f7f8fa" if i % 2 else "#ffffff"
        tds = "".join(
            f'<td style="padding:8px 10px; font-size:13px; color:#1a202c; '
            f'vertical-align:top; border-bottom:1px solid {_LINE};">{cell}</td>'
            for cell in row
        )
        body.append(f'<tr style="background-color:{bg};">{tds}</tr>')
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse; margin:0 0 22px;">'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _section(title: str, note: str, headers: list[str], rows: list[list[str]]) -> str:
    return (
        f'<h3 style="margin:0 0 6px; font-size:16px; color:{_NAVY};">{_esc(title)}</h3>'
        f'<p style="margin:0 0 10px; font-size:13px; color:{_MUTED};">{_esc(note)}</p>'
        f"{_table(headers, rows)}"
    )


def _status_cell(label: str, kind: str) -> str:
    colors = {
        "ok": ("#0f7b3a", "#e8f6ee"),
        "failed": ("#b42318", "#fdecea"),
        "blocked": ("#b42318", "#fdecea"),
        "paused": ("#667085", "#f2f4f7"),
        "warn": ("#b54708", "#fff6e5"),
    }
    fg, bg = colors.get(kind, ("#1a202c", "#f2f4f7"))
    return (
        f'<span style="display:inline-block; padding:2px 8px; border-radius:10px; '
        f'font-size:12px; font-weight:600; color:{fg}; background:{bg};">'
        f"{_esc(label)}</span>"
    )


def _queue_rows(payload: dict[str, Any]) -> list[list[str]]:
    q = payload.get("queues") or {}
    new_c = int(payload.get("comments_new") or 0)
    return [
        [_esc("Topics / reels / FAQs / unused videos"),
         _esc(f"{q.get('article_topics', 0)} / {q.get('reels', 0)} / "
              f"{q.get('faqs', 0)} / {q.get('unused_videos', 0)}"),
         _esc("Open content ideas. Unused videos have no article yet.")],
        [_esc("Video approvals waiting"), _esc(q.get("pending_video_approvals", 0)),
         _esc("Clips waiting for a person to approve before publish.")],
        [_esc("Articles scheduled"), _esc(q.get("scheduled_articles", 0)),
         _esc("Articles with a future go-live date.")],
        [_esc("Content queued / scheduled"), _esc(q.get("scheduled_content", 0)),
         _esc("Social or site rows the 15-minute promoter will release.")],
        [_esc("YouTube comments needing a reply"),
         _esc(f"{q.get('comment_drafts', 0)} ({new_c} new this week)"),
         _esc("Draft replies sitting in the comments queue.")],
    ]


def _week_rows(payload: dict[str, Any]) -> list[list[str]]:
    names = ", ".join(payload.get("customer_names") or [])
    cust = str(payload.get("customers_new", 0))
    if names:
        cust = f"{cust} — {names}"
    signed = (
        f"{payload.get('proposals_signed', 0)} · {_money(payload.get('signed_value'))}"
    )
    if payload.get("signed_titles"):
        signed += " — " + ", ".join(payload["signed_titles"])
    return [
        [_esc("New customers"), _esc(cust),
         _esc("Customer records created this week.")],
        [_esc("Quotes"),
         _esc(f"{payload.get('estimates', 0)} · {_money(payload.get('quote_value'))}"),
         _esc("Estimates written, and their combined job total.")],
        [_esc("Proposals created"), _esc(payload.get("proposals_created", 0)),
         _esc("Proposal documents started this week.")],
        [_esc("Proposals signed"), _esc(signed),
         _esc("Accepted this week, and the signed dollar total.")],
    ]


def _spend_rows(spend: dict[str, Any]) -> list[list[str]]:
    if spend.get("ok") and spend.get("amount") is not None:
        value = f"{_money(spend['amount'])} {spend.get('currency') or 'USD'}"
        meaning = f"Current-month budget ({spend.get('display_name') or 'budget'})."
    elif spend.get("ok"):
        value = spend.get("note") or "no amount"
        meaning = "Billing API answered, but no budget amount is configured."
    else:
        value = f"unavailable — {spend.get('error') or 'unknown'}"
        if spend.get("hint"):
            value += f" ({spend['hint']})"
        meaning = "The API service account cannot read Cloud Billing yet."
    return [[_esc("This month"), _esc(value), _esc(meaning)]]


def _profit_rows(below: list[dict[str, Any]]) -> list[list[str]]:
    if not below:
        return [[_esc("(none this week)"), "", _esc("No quote landed under the $2,500 profit floor.")]]
    return [
        [_esc(f"#{b.get('id')} {b.get('created_by') or '?'}"),
         _esc(f"{b.get('roof_type') or '?'} · profit {_money(b.get('profit'))} · "
              f"total {_money(b.get('total'))}"),
         _esc("Profit is under the $2,500 job minimum.")]
        for b in below
    ]


def _scan_rows(payload: dict[str, Any]) -> tuple[int, list[list[str]]]:
    items = payload.get("scans_latest") or payload.get("scans") or []
    rows: list[list[str]] = []
    n = 0
    for s in items:
        kind = s.get("scan_type") or "scan"
        if kind in YOUTUBE_SCAN_TYPES:
            continue
        n += 1
        if s.get("error"):
            rows.append([_esc(kind), _esc("failed"), _esc(s["error"])])
            continue
        ready = s.get("ready_slugs") or []
        blockers = s.get("blockers") or {}
        block_txt = ", ".join(f"{c}× {reason}" for reason, c in blockers.items()) or "(none)"
        rows.append([
            _esc(f"{kind} {s.get('ran_at') or ''}".strip()),
            _esc(f"{s.get('ready_count', 0)} ready / {s.get('blocked_count', 0)} blocked "
                 f"of {s.get('total', 0)}"),
            _esc(f"Ready: {', '.join(str(x) for x in ready) or '(none)'}. Blockers: {block_txt}."),
        ])
    if not rows:
        rows.append([
            _esc("portfolio"),
            _esc("not persisted yet"),
            _esc("The daily scan still runs. The scan_reports table is not in prod, so there is nothing to list."),
        ])
    return n, rows


def _youtube_verdict(yt: dict[str, Any]) -> tuple[str, str]:
    if yt.get("blocked"):
        return "BLOCKED — cannot pull from YouTube", "blocked"
    if yt.get("pull_ok"):
        return "pulling OK — not blocked", "ok"
    return "not blocked, but pull is not clean", "warn"


def _youtube_rows(yt: dict[str, Any]) -> list[list[str]]:
    if not yt:
        return [[_esc("Status"), _esc("no catalog snapshot"),
                 _esc("Collector did not return a catalog.")]]
    verdict, kind = _youtube_verdict(yt)
    newest = yt.get("newest_title") or yt.get("newest_id") or "(none)"
    when = yt.get("newest_upload_date") or "?"
    if yt.get("newest_age_days") is not None:
        when = f"{when}, {yt['newest_age_days']}d ago"
    new = str(yt.get("new_this_week", 0))
    if yt.get("new_titles"):
        new += " — " + ", ".join(yt["new_titles"])
    rows = [
        [_esc("Status"), _status_cell(verdict, kind),
         _esc("Bot-check only counts as blocked if we still cannot download.")],
        [_esc("Catalog"),
         _esc(f"{yt.get('archived', 0)}/{yt.get('videos', 0)} archived · "
              f"{yt.get('unarchived', 0)} waiting · {yt.get('unavailable', 0)} unavailable"),
         _esc("Archived = MP4 in the media bucket. Waiting = found but not downloaded.")],
        [_esc("Newest video"), _esc(f"{newest} ({when})"),
         _esc("Latest upload_date in the catalog. Stale means enumerate may have stopped.")],
        [_esc("New this week"), _esc(new),
         _esc("Videos whose YouTube date falls in this digest window.")],
    ]
    rows.extend(_youtube_extra_rows(yt))
    return rows


def _youtube_extra_rows(yt: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    tabs = yt.get("failed_tabs") or []
    if tabs:
        rows.append([_esc("Failed tabs"), _esc(", ".join(tabs)),
                     _esc("Last enumerate failed tabs: " + ", ".join(tabs)
                          + ". streams is noise; videos/shorts is a real miss.")])
    if yt.get("incomplete"):
        rows.append([_esc("Enumerate"), _esc("incomplete"),
                     _esc("Enumerate marked incomplete (videos or shorts tab failed).")])
    if yt.get("unarchived_ids"):
        rows.append([_esc("Unarchived ids"), _esc(", ".join(yt["unarchived_ids"])),
                     _esc("Still waiting on archive_job.")])
    if yt.get("bot_hits"):
        rows.append([_esc("Bot-check hits"), _esc(yt["bot_hits"]),
                     _esc("Ingest errors that look like a YouTube bot wall.")])
    for run in yt.get("job_runs") or []:
        rows.append([
            _esc(run.get("name")),
            _status_cell(run.get("attention") or "?", run.get("attention") or ""),
            _esc(run.get("last_execution") or run.get("last_attempt") or "no execution id"),
        ])
    for hit in (yt.get("recent_blocks") or [])[:6]:
        rows.append([
            _esc(f"Block {hit.get('timestamp') or '?'}"),
            _esc(hit.get("resource") or "yt-dlp"),
            _esc(hit.get("message") or ""),
        ])
    for reason in yt.get("reasons") or []:
        rows.append([_esc("Note"), _esc(reason), _esc("Why pull_ok is false or blocked is set.")])
    waiting = set(yt.get("unarchived_ids") or [])
    for err in (yt.get("ingest_errors") or [])[:5]:
        rows.append([
            _esc(f"Ingest {err.get('stage')}"),
            _esc(err.get("video_id")),
            _esc(_ingest_error_meaning(err, waiting)),
        ])
    return rows


def _ingest_error_meaning(err: dict, waiting: set[str]) -> str:
    raw = err.get("error") or ""
    vid = err.get("video_id") or ""
    if "no archive_uri" in raw:
        if vid in waiting:
            return (
                f"{raw} — STT needs the MP4 in GCS first. This video is still unarchived."
            )
        return (
            f"{raw} — stale. The MP4 is in GCS now. Ingest gives up after 5 failures; "
            "reset this transcript row to pending so the next ingest run transcribes it."
        )
    return raw


def _jobs_rows(blob: dict[str, Any]) -> tuple[str, list[list[str]]]:
    if not blob.get("ok"):
        err = blob.get("error") or "unavailable"
        hint = f" ({blob['hint']})" if blob.get("hint") else ""
        return (
            "Could not read Cloud Scheduler / Cloud Run.",
            [[_esc("GCP"), _esc(f"unavailable — {err}{hint}"),
              _esc("Grant cloudscheduler.viewer and run.viewer to the API SA.")]],
        )
    failed = blob.get("failed") or []
    missing = blob.get("not_running") or []
    paused = blob.get("paused") or []
    bits = []
    if failed:
        bits.append("FAILED: " + ", ".join(failed))
    if missing:
        bits.append("Not running / missed last window: " + ", ".join(missing))
    if paused:
        bits.append("Paused (intentional): " + ", ".join(paused))
    if not failed and not missing:
        bits.append("No failed or missed scheduled jobs")
    rows = []
    for job in blob.get("schedulers") or []:
        last = job.get("last_attempt") or "never"
        detail = f"{job.get('schedule') or ''} {job.get('time_zone') or ''} · last {last}"
        if job.get("message"):
            detail += f" · {job['message']}"
        rows.append([
            _esc(job.get("name")),
            _status_cell(f"{job.get('state')} / {job.get('attention')}", job.get("attention") or ""),
            _esc(detail.strip()),
        ])
    for job in blob.get("run_jobs") or []:
        rows.append([
            _esc(f"Cloud Run {job.get('name')}"),
            _status_cell(job.get("attention") or "?", job.get("attention") or ""),
            _esc(f"last {job.get('last_execution') or 'none'} ({job.get('condition') or '?'})"),
        ])
    if not rows:
        rows.append([_esc("(none)"), "", _esc("No scheduler or Cloud Run jobs returned.")])
    return "; ".join(bits), rows


def _action_rows(payload: dict[str, Any]) -> list[list[str]]:
    actions = payload.get("by_action") or {}
    if not actions:
        return [[_esc("(no audit rows)"), "", _esc("Nobody changed records in this window.")]]
    return [[_esc(k), _esc(v), _esc("Times this action was written to the audit log.")]
            for k, v in actions.items()]


def _who_rows(payload: dict[str, Any]) -> list[list[str]]:
    actors = payload.get("by_actor") or {}
    if not actors:
        return [[_esc("(none)"), "", _esc("No actor emails on audit rows.")]]
    return [[_esc(k), _esc(v), _esc("Audit events attributed to this address.")]
            for k, v in actors.items()]


def _render_issues(issues: list[dict[str, str]]) -> str:
    if not issues:
        rows = [[_esc("None"), _esc("All clear"),
                 _esc("No errors or warnings in this window.")]]
    else:
        rows = [
            [
                _status_cell(i.get("severity") or "info",
                             "failed" if i.get("severity") == "error" else "warn"),
                _esc(f"{i.get('title') or ''}. {i.get('detail') or ''}".strip(". ")),
                _esc(i.get("fix") or ""),
            ]
            for i in issues
        ]
    return _section(
        f"Needs action ({len(issues)})",
        "Errors and warnings first. Use How to fix — do not wait for Monday.",
        ["Severity", "Issue", "How to fix"],
        rows,
    )


def render_html(payload: dict[str, Any], *, logo_url: str = LOGO_URL) -> str:
    below = payload.get("profit_below_minimum") or []
    scan_n, scan_rows = _scan_rows(payload)
    jobs_note, job_rows = _jobs_rows(payload.get("scheduled_jobs") or {})
    issues = payload.get("issues")
    if issues is None:
        issues = collect_issues(payload)
    body = (
        f'<h2 style="margin:0 0 4px; font-size:22px; color:{_NAVY};">Weekly digest</h2>'
        f'<p style="margin:0 0 6px; font-size:13px; color:{_MUTED};">'
        f"{_esc(payload.get('since'))} → {_esc(payload.get('until'))}</p>"
        f'<p style="margin:0 0 22px; font-size:14px; color:#1a202c;">'
        "Snapshot of work waiting in the app, what happened this week, "
        "whether YouTube is still downloading, and whether scheduled jobs ran.</p>"
        + _render_issues(issues)
        + _section(
            "Needs attention",
            "Sidebar badge counts. A non-zero number means someone has work waiting.",
            ["Item", "Value", "What this means"],
            _queue_rows(payload),
        )
        + _section(
            "This week",
            "Customers, quotes, and signed proposals in the last seven days.",
            ["Item", "Value", "What this means"],
            _week_rows(payload),
        )
        + _section(
            "YouTube pull",
            "Channel enumerate + archive. Blocked means yt-dlp hit YouTube's bot wall and we still cannot download.",
            ["Item", "Value", "What this means"],
            _youtube_rows(payload.get("youtube") or {}),
        )
        + _section(
            "Scheduled jobs",
            jobs_note,
            ["Job", "Status", "Schedule / last run"],
            job_rows,
        )
        + _section(
            "Cloud spend",
            "GCP project spend from the billing-budgets API.",
            ["Item", "Value", "What this means"],
            _spend_rows(payload.get("cloud_spend") or {}),
        )
        + _section(
            f"Profit under $2,500 ({len(below)})",
            "Quotes whose estimated profit is under the job minimum.",
            ["Quote", "Detail", "What this means"],
            _profit_rows(below),
        )
        + _section(
            f"Portfolio scans ({scan_n})",
            "Daily readiness scan: which project pages could be built, and what is blocking the rest.",
            ["Scan", "Result", "What this means"],
            scan_rows,
        )
        + _section(
            f"Actions ({payload.get('audit_count') or 0})",
            "What people did in the app this week.",
            ["Action", "Count", "What this means"],
            _action_rows(payload),
        )
        + _section(
            "Who",
            "Who those audit events belong to.",
            ["Person", "Count", "What this means"],
            _who_rows(payload),
        )
    )
    header = (
        f'<img src="{_esc(logo_url)}" alt="Perkins Roofing" width="180" '
        'style="display:block; border:0; max-width:180px; height:auto;">'
    )
    return wrap_email(
        body_html=body,
        header_html=header,
        company_name="Perkins Roofing",
        header_bg="#ffffff",
    )


def send_digest(payload: dict[str, Any], *, tenant_id: int | None = None) -> list[str]:
    import adapters.resend as resend  # noqa: PLC0415

    html = render_html(payload)
    n = len(payload.get("profit_below_minimum") or [])
    signed_n = int(payload.get("proposals_signed") or 0)
    subject = (
        f"Perkins weekly digest — {signed_n} signed · "
        f"{n} quote(s) under $2,500"
    )
    ids: list[str] = []
    for to in PROFIT_FLOOR_NOTIFY:
        ids.append(resend.send(
            reply_to=to,
            to=to,
            subject=subject,
            html=html,
            tenant_id=tenant_id,
            send_type="weekly_digest",
            metadata={"profit_below_count": n, "proposals_signed": signed_n},
        ))
    return ids
