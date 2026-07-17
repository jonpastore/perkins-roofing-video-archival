"""Resend email-send adapter.

This is the canonical outbound-email choke point. It gates every attempted send
through ``core.email_gate`` BEFORE contacting Resend and writes an ``email_logs``
row for sent/blocked/failed attempts when the application DB is available.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import urllib.request
import uuid
from typing import Any

from core.email_gate import decide

log = logging.getLogger(__name__)
_DEFAULT_FROM_EMAIL = "noreply@perkinsroofing.net"
_DEFAULT_FROM_NAME = "Perkins Roofing"


def _bcc_list(bcc: list[str] | str | None) -> list[str]:
    if not bcc:
        return []
    return [bcc] if isinstance(bcc, str) else list(bcc)


def _infer_send_type() -> str:
    """Best-effort type label for legacy callers that don't pass send_type."""
    for frame in inspect.stack()[2:8]:
        path = frame.filename.replace("\\", "/")
        fn = frame.function
        if path.endswith("/api/routes/proposals.py") and "_send_accept_link_email" in fn:
            return "proposal_accept_link"
        if path.endswith("/jobs/proposal_reminders.py"):
            return "proposal_reminder"
        if path.endswith("/api/routes/email.py"):
            return "email_compose"
        if path.endswith("/api/routes/users.py"):
            return "user_invite"
    return "resend"


def _log_email_attempt(
    *,
    tenant_id: int | None,
    provider: str,
    send_type: str,
    from_email: str,
    to_email: str,
    subject: str,
    status: str,
    provider_message_id: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort DB audit insert.

    Email blocking must never fail open because logging failed. Conversely, a
    missing migration/table in a dev DB must not mask the gate decision.
    """
    try:
        from app.models import EmailLog, SessionLocal  # noqa: PLC0415

        with SessionLocal() as db:
            db.info["tenant_id"] = int(tenant_id or os.getenv("DEFAULT_TENANT_ID", "1"))
            db.add(EmailLog(
                tenant_id=db.info["tenant_id"],
                provider=provider,
                send_type=send_type,
                from_email=from_email,
                to_email=to_email,
                subject=subject,
                status=status,
                provider_message_id=provider_message_id,
                error=error,
                email_metadata=metadata or {},
            ))
            db.commit()
    except Exception as exc:  # noqa: BLE001 — never let audit failure change send decision
        log.warning("email log write failed: %s", exc)


def is_blocked_message_id(message_id: str | None) -> bool:
    return bool(message_id and str(message_id).startswith("blocked_"))


def send(
    *,
    from_name: str = _DEFAULT_FROM_NAME,
    from_email: str = _DEFAULT_FROM_EMAIL,
    reply_to: str,
    to: str,
    subject: str,
    html: str,
    bcc: list[str] | str | None = None,
    tenant_id: int | None = None,
    send_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Send an email via Resend and return the Resend message id.

    Args:
        from_name:  Display name for the sender (e.g. "Jane Smith").
                    Defaults to "Perkins Roofing".
        from_email: Sending address — must be on the verified perkinsroofing.net
                    domain. Defaults to noreply@perkinsroofing.net. NEVER accept
                    this value from client-supplied input; always derive it from
                    verified server-side claims.
        reply_to:   Reply-to address — the authenticated user's email so that
                    client replies land in their own inbox.
        to:         Recipient email address.
        subject:    Email subject line.
        html:       HTML body of the email.
        bcc:        Optional blind-copy recipient(s). Server-derived only —
                    never client-supplied.

    Returns:
        The Resend ``id`` string for the sent message.

    Raises:
        RuntimeError: If the API key is missing or Resend returns a non-2xx status.
    """
    send_type = send_type or _infer_send_type()
    bcc_recipients = _bcc_list(bcc)
    recipients = [to, *bcc_recipients]
    base_metadata: dict[str, Any] = {
        "gate_checked_recipients": len(recipients),
        **(metadata or {}),
    }

    for recipient in recipients:
        decision = decide(recipient)
        if not decision.allowed:
            blocked_id = f"blocked_{uuid.uuid4().hex}"
            _log_email_attempt(
                tenant_id=tenant_id,
                provider="resend",
                send_type=send_type,
                from_email=from_email,
                to_email=recipient,
                subject=subject,
                status="blocked",
                provider_message_id=blocked_id,
                error=decision.reason,
                metadata={**base_metadata, "mode": decision.mode, "blocked_recipient": recipient},
            )
            log.warning(
                "blocked outbound email send_type=%s to=%s mode=%s reason=%s",
                send_type,
                recipient,
                decision.mode,
                decision.reason,
            )
            return blocked_id

    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        _log_email_attempt(
            tenant_id=tenant_id,
            provider="resend",
            send_type=send_type,
            from_email=from_email,
            to_email=to,
            subject=subject,
            status="failed",
            error="RESEND_API_KEY environment variable is not set",
            metadata=base_metadata,
        )
        raise RuntimeError("RESEND_API_KEY environment variable is not set")

    payload = {
        "from": f"{from_name} <{from_email}>",
        "reply_to": reply_to,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if bcc_recipients:
        payload["bcc"] = bcc_recipients
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Explicit UA: Cloudflare in front of api.resend.com returns 1010 (bot
            # block) for the default Python-urllib signature from non-Google egress
            # (dev boxes, scripts). Works in prod either way; this makes it universal.
            "User-Agent": "PerkinsRoofingPlatform/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        _log_email_attempt(
            tenant_id=tenant_id,
            provider="resend",
            send_type=send_type,
            from_email=from_email,
            to_email=to,
            subject=subject,
            status="failed",
            error=f"Resend API error {exc.code}: {raw}",
            metadata=base_metadata,
        )
        raise RuntimeError(f"Resend API error {exc.code}: {raw}") from exc

    msg_id = body.get("id")
    if not msg_id:
        _log_email_attempt(
            tenant_id=tenant_id,
            provider="resend",
            send_type=send_type,
            from_email=from_email,
            to_email=to,
            subject=subject,
            status="failed",
            error=f"Resend response missing 'id': {body}",
            metadata=base_metadata,
        )
        raise RuntimeError(f"Resend response missing 'id': {body}")
    _log_email_attempt(
        tenant_id=tenant_id,
        provider="resend",
        send_type=send_type,
        from_email=from_email,
        to_email=to,
        subject=subject,
        status="sent",
        provider_message_id=msg_id,
        metadata=base_metadata,
    )
    return msg_id
