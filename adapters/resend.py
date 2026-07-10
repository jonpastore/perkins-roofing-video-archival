"""Resend email-send adapter (I/O — coverage-omitted). POSTs to the Resend API using
the RESEND_API_KEY env var. The verified sending domain is perkinsroofing.net.
reply_to routes replies to the authenticated user's own inbox."""
import json
import os
import urllib.request

_DEFAULT_FROM_EMAIL = "noreply@perkinsroofing.net"
_DEFAULT_FROM_NAME = "Perkins Roofing"


def send(
    *,
    from_name: str = _DEFAULT_FROM_NAME,
    from_email: str = _DEFAULT_FROM_EMAIL,
    reply_to: str,
    to: str,
    subject: str,
    html: str,
    bcc: list[str] | str | None = None,
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
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY environment variable is not set")

    payload = {
        "from": f"{from_name} <{from_email}>",
        "reply_to": reply_to,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if bcc:
        payload["bcc"] = [bcc] if isinstance(bcc, str) else list(bcc)
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
        raise RuntimeError(f"Resend API error {exc.code}: {raw}") from exc

    msg_id = body.get("id")
    if not msg_id:
        raise RuntimeError(f"Resend response missing 'id': {body}")
    return msg_id
