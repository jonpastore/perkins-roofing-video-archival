"""Cloud Scheduler + Cloud Run Job last-run status for the weekly digest.

Best-effort, same shape as cloud_spend: never raise, return an explicit miss
when ADC or IAM is missing. Viewer roles needed:

  roles/cloudscheduler.viewer
  roles/run.viewer
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen")
REGION = os.getenv("GCP_REGION", "us-central1")

# Daily-ish jobs that should have attempted in the last 2 days (weekends + ET
# business-hours windows). Weekly jobs use WEEKLY_STALE_HOURS.
DAILY_STALE_HOURS = 48
WEEKLY_STALE_HOURS = 9 * 24
FREQUENT_STALE_HOURS = 3

WEEKLY_NAMES = frozenset({"weekly-digest"})
FREQUENT_MARKERS = ("*/15", "*/30", "*/2")


def _adc_token() -> str:
    import google.auth  # noqa: PLC0415
    import google.auth.transport.requests  # noqa: PLC0415

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _get_json(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode())


def _short_name(resource: str) -> str:
    return (resource or "").rsplit("/", 1)[-1]


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def stale_hours_for(name: str, schedule: str) -> int:
    if name in WEEKLY_NAMES or "0 8 * * 1" in (schedule or ""):
        return WEEKLY_STALE_HOURS
    if any(m in (schedule or "") for m in FREQUENT_MARKERS):
        return FREQUENT_STALE_HOURS
    return DAILY_STALE_HOURS


def classify_scheduler(job: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    name = _short_name(job.get("name") or "")
    state = (job.get("state") or "UNKNOWN").upper()
    schedule = job.get("schedule") or ""
    status = job.get("status") or {}
    last_at = _parse_ts(status.get("lastAttemptTime") or job.get("lastAttemptTime"))
    code = status.get("code")
    message = (status.get("message") or "")[:200]
    # Cloud Scheduler often leaves status empty after a success. code=-1 is the
    # paused-job sentinel, not a crash. Only a real rpc code means failed.
    failed = code not in (None, 0, "0", "OK", -1, "-1")
    paused = state in ("PAUSED", "DISABLED")
    hours = stale_hours_for(name, schedule)
    # Empty lastAttemptTime is NOT a miss — the API simply does not keep it.
    missed = (
        (not paused) and last_at is not None
        and last_at < now - timedelta(hours=hours)
    )
    if paused:
        attention = "paused"
    elif failed:
        attention = "failed"
    elif missed:
        attention = "not_running"
    else:
        attention = "ok"
    return {
        "name": name,
        "kind": "scheduler",
        "state": state,
        "schedule": schedule,
        "time_zone": job.get("timeZone") or "",
        "last_attempt": last_at.isoformat(timespec="seconds") if last_at else None,
        "code": code,
        "message": message,
        "attention": attention,
    }


# Jobs a scheduler is supposed to fire. On-demand jobs (render/article/social)
# may sit idle for weeks without that meaning they are broken.
SCHEDULED_RUN_JOBS = frozenset({
    "ingest", "enumerate-channel", "archive", "companycam-sync",
    "knowify-sync", "knowify-keepwarm", "salinity-sweep",
})


def classify_run_job(job: dict[str, Any], execution: dict[str, Any] | None = None,
                     *, now: datetime | None = None) -> dict[str, Any]:
    name = _short_name(job.get("name") or "")
    latest = execution or job.get("latestCreatedExecution") or {}
    conds = latest.get("conditions") or []
    completed = next((c for c in conds if c.get("type") == "Completed"), None) or {}
    cond_state = (completed.get("state") or "").upper()
    succeeded = int(latest.get("succeededCount") or 0)
    failed_n = int(latest.get("failedCount") or 0)
    failed = failed_n > 0 and succeeded == 0
    if cond_state == "CONDITION_FAILED":
        failed = True
    started = _parse_ts(latest.get("createTime") or latest.get("completionTime"))
    stale = (
        name in SCHEDULED_RUN_JOBS
        and started is not None
        and started < (now or datetime.now(timezone.utc)) - timedelta(hours=DAILY_STALE_HOURS)
    )
    if not latest:
        attention = "not_running" if name in SCHEDULED_RUN_JOBS else "ok"
    elif failed:
        attention = "failed"
    elif stale:
        attention = "not_running"
    else:
        attention = "ok"
    return {
        "name": name,
        "kind": "run_job",
        "last_execution": _short_name(latest.get("name") or "") or None,
        "started": latest.get("createTime"),
        "completed": latest.get("completionTime"),
        "succeeded": succeeded,
        "failed_count": failed_n,
        "condition": cond_state or None,
        "message": (completed.get("message") or "")[:200],
        "attention": attention,
    }


def _last_execution(token: str, job_name: str) -> dict[str, Any] | None:
    url = (
        f"https://run.googleapis.com/v2/projects/{PROJECT_ID}/locations/{REGION}"
        f"/jobs/{urllib.parse.quote(job_name)}/executions?pageSize=1"
    )
    body = _get_json(url, token)
    rows = body.get("executions") or []
    return rows[0] if rows else None


_SCHEDULER_RUN_ALIAS = {"run-ingest": "ingest"}


def _overlay_scheduler_from_runs(schedulers: list[dict[str, Any]],
                                 run_jobs: list[dict[str, Any]]) -> None:
    by_name = {j["name"]: j for j in run_jobs}
    paused = {s["name"] for s in schedulers if s["attention"] == "paused"}
    for run in run_jobs:
        if run["name"] in paused and run["attention"] == "not_running":
            run["attention"] = "paused"
    for sched in schedulers:
        src = by_name.get(sched["name"]) or by_name.get(_SCHEDULER_RUN_ALIAS.get(sched["name"], ""))
        if not src:
            continue
        if not sched.get("last_attempt") and src.get("started"):
            sched["last_attempt"] = src["started"]
        if sched["attention"] == "ok" and src["attention"] in ("failed", "not_running"):
            sched["attention"] = src["attention"]
            if src.get("message"):
                sched["message"] = src["message"]


def fetch_scheduled_jobs() -> dict[str, Any]:
    """List Cloud Scheduler jobs + Cloud Run jobs. Never raises."""
    try:
        token = _adc_token()
    except ImportError:
        return {"ok": False, "error": "google-auth not installed", "jobs": []}
    except Exception as exc:  # noqa: BLE001 — digest must still send
        return {"ok": False, "error": f"adc: {exc}", "jobs": []}

    sched_url = (
        f"https://cloudscheduler.googleapis.com/v1/projects/{PROJECT_ID}"
        f"/locations/{REGION}/jobs"
    )
    run_url = (
        f"https://run.googleapis.com/v2/projects/{PROJECT_ID}"
        f"/locations/{REGION}/jobs"
    )
    try:
        sched_body = _get_json(sched_url, token)
        run_body = _get_json(run_url, token)
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "error": f"HTTP {exc.code}",
            "hint": "Grant cloudscheduler.viewer and run.viewer to the API SA",
            "jobs": [],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "jobs": []}

    now = datetime.now(timezone.utc)
    schedulers = [classify_scheduler(j, now=now) for j in (sched_body.get("jobs") or [])]
    run_jobs = []
    for job in (run_body.get("jobs") or []):
        name = _short_name(job.get("name") or "")
        execution = None
        try:
            execution = _last_execution(token, name) if name else None
        except Exception:
            execution = job.get("latestCreatedExecution")
        run_jobs.append(classify_run_job(job, execution, now=now))
    _overlay_scheduler_from_runs(schedulers, run_jobs)
    attention = [j for j in (*schedulers, *run_jobs) if j.get("attention") != "ok"]
    return {
        "ok": True,
        "project": PROJECT_ID,
        "region": REGION,
        "schedulers": schedulers,
        "run_jobs": run_jobs,
        "jobs": schedulers + run_jobs,
        "attention": attention,
        "paused": [j["name"] for j in schedulers if j["attention"] == "paused"],
        "failed": [j["name"] for j in (*schedulers, *run_jobs) if j["attention"] == "failed"],
        "not_running": [j["name"] for j in (*schedulers, *run_jobs) if j["attention"] == "not_running"],
    }
