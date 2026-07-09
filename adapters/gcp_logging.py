"""GCP Cloud Logging adapter — read-only query for recent log entries.

Queries Cloud Logging for entries at >= severity from Cloud Run services/jobs
in the last N hours. Only this module touches the Cloud Logging API; all callers
receive plain dicts so tests can mock at the adapter boundary.

Usage::

    from adapters.gcp_logging import recent_errors
    entries = recent_errors(hours=24, severity="ERROR", limit=100)

Raises RuntimeError (turned into 503 by the route) when:
  - google-cloud-logging is not installed, OR
  - Application Default Credentials are not available.
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Structured-logging tenant context (TRD-F4 §5 — tenant_id on every log line)
# ---------------------------------------------------------------------------

# Request-scoped tenant id. get_db_session (api/auth.py) / the token-scoped
# session set this from the VERIFIED tenant so every log record emitted while
# handling a request carries tenant_id, without threading it through call sites.
_tenant_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "tenant_id", default=None
)


def set_log_tenant(tenant_id: int | None) -> "contextvars.Token":
    """Bind tenant_id to the current context for structured logging. Returns a
    reset token; pass it to reset_log_tenant in a finally block."""
    return _tenant_ctx.set(tenant_id)


def reset_log_tenant(token: "contextvars.Token") -> None:
    _tenant_ctx.reset(token)


class TenantLogFilter(logging.Filter):
    """Inject the context-bound tenant_id onto every LogRecord (TRD-F4 §5).

    Attach once to the root logger at startup. Records get a ``tenant_id``
    attribute (the bound value, or None outside a request) so the Cloud Logging
    structured formatter can emit it as a label on every line.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.tenant_id = _tenant_ctx.get()
        return True


def install_tenant_log_filter() -> None:
    """Idempotently attach TenantLogFilter to the root logger."""
    root = logging.getLogger()
    if not any(isinstance(f, TenantLogFilter) for f in root.filters):
        root.addFilter(TenantLogFilter())

_SEVERITY_ORDER = ["DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]

# Patterns that may indicate embedded secrets/credentials in log messages.
_SECRET_PATTERNS = [
    re.compile(r'postgres(?:ql)?://\S+', re.IGNORECASE),
    re.compile(r'Bearer\s+\S+', re.IGNORECASE),
    re.compile(r'AIza[0-9A-Za-z_\-]{20,}'),
    re.compile(r'key=\S+', re.IGNORECASE),
    # long base64 or hex secrets (32+ chars of base64url or hex)
    re.compile(r'[A-Za-z0-9+/\-_]{32,}={0,2}(?=\s|$|["\'])'),
]


def _redact_message(message: str) -> str:
    """Replace patterns that look like embedded secrets with '***'."""
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("***", message)
    return message


def _gcp_project() -> str:
    proj = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
    if proj:
        return proj
    try:
        import google.auth  # noqa: PLC0415
        _, proj = google.auth.default()
        if proj:
            return proj
    except Exception:
        pass
    raise RuntimeError("Cannot determine GCP project; set GOOGLE_CLOUD_PROJECT env var")


def recent_errors(
    hours: int = 24,
    severity: str = "ERROR",
    limit: int = 100,
) -> list[dict]:
    """Return recent log entries at >= severity from Cloud Run services/jobs.

    Each entry is a dict with keys:
      timestamp, severity, resource (service/job name), message, log_name

    Raises RuntimeError if the Cloud Logging library is not installed or ADC
    is not configured — the route converts this to a 503.
    """
    try:
        from google.cloud import logging_v2  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-logging is not installed. "
            "Add it to app/requirements.txt."
        ) from exc

    try:
        project = _gcp_project()
    except RuntimeError:
        raise

    # Build the log filter.
    sev_upper = severity.upper()
    if sev_upper not in _SEVERITY_ORDER:
        sev_upper = "ERROR"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    timestamp_filter = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Cloud Run services land in run.googleapis.com/requests + stderr logs;
    # Cloud Run jobs land in run.googleapis.com/jobs. We query both.
    log_filter = (
        f'resource.type=("cloud_run_revision" OR "cloud_run_job") '
        f'severity>={sev_upper} '
        f'timestamp>="{timestamp_filter}"'
    )

    try:
        client = logging_v2.Client(project=project)
    except Exception as exc:
        raise RuntimeError(f"Failed to create Cloud Logging client: {exc}") from exc

    entries: list[dict] = []
    try:
        for entry in client.list_entries(
            filter_=log_filter,
            order_by=logging_v2.DESCENDING,
            max_results=limit,
            projects=[project],
        ):
            # entry.timestamp is a datetime (UTC-aware)
            ts = entry.timestamp
            timestamp_iso = ts.isoformat() if ts else None

            # Resource label: prefer service_name, then job_name, then type
            resource_labels = entry.resource.labels if entry.resource else {}
            resource_name = (
                resource_labels.get("service_name")
                or resource_labels.get("job_name")
                or (entry.resource.type if entry.resource else None)
                or "unknown"
            )

            # Payload: structured or text
            payload = entry.payload
            if isinstance(payload, dict):
                message = payload.get("message") or str(payload)
            elif payload is not None:
                message = str(payload)
            else:
                message = ""

            entries.append({
                "timestamp": timestamp_iso,
                "severity": entry.severity or sev_upper,
                "resource": resource_name,
                "message": _redact_message(message),
                "log_name": entry.log_name or "",
            })
    except Exception as exc:
        raise RuntimeError(f"Cloud Logging query failed: {exc}") from exc

    return entries
