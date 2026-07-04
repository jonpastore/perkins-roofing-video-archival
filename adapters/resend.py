"""Resend email-send adapter (I/O — coverage-omitted). POSTs to the Resend API using
the RESEND_API_KEY env var. The 'from' address is always noreply@perkinsroofing.net;
reply_to routes replies to the authenticated user's own inbox."""
import json
import os
import urllib.request


def send(*, from_name: str, reply_to: str, to: str, subject: str, html: str) -> str:
    """Send an email via Resend and return the Resend message id.

    Args:
        from_name: Display name for the sender (e.g. "Perkins Roofing").
        reply_to:  Reply-to address — should be the authenticated user's email.
        to:        Recipient email address.
        subject:   Email subject line.
        html:      HTML body of the email.

    Returns:
        The Resend ``id`` string for the sent message.

    Raises:
        RuntimeError: If the API key is missing or Resend returns a non-2xx status.
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY environment variable is not set")

    payload = {
        "from": f"{from_name} <noreply@perkinsroofing.net>",
        "reply_to": reply_to,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
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
