"""Email a human when a data source needs a dashboard login."""
from __future__ import annotations

from core.email_template import wrap_email

DASHBOARD_URL = "https://video-archival-and-content-gen.web.app/"
RECIPIENTS = (
    "jon@perkinsroofing.net",
    "jon@degenito.ai",
)

LOGIN_COPY = {
    "knowify": (
        "Knowify",
        "The Knowify MCP token is expired. Open Status → Data sources → Knowify → Log in.",
    ),
    "youtube": (
        "YouTube",
        "Comment-reply OAuth does not authorize the Perkins channel. "
        "Open Status → Data sources → YouTube → Log in as the channel owner.",
    ),
    "youtube_reply": (
        "YouTube",
        "Comment-reply OAuth does not authorize the Perkins channel. "
        "Open Status → Data sources → YouTube → Log in as the channel owner.",
    ),
    "wordpress": (
        "WordPress",
        "Staging (1251216) has a vaulted Application Password for user jon. "
        "If REST 401s again, Wendy spun a new host without the feature, or the key was rotated. "
        "Mint a new Application Password on the current staging profile and vault it.",
    ),
}


def login_email_html(integration: str) -> tuple[str, str]:
    label, body = LOGIN_COPY.get(integration, (
        integration,
        f"{integration} needs attention on the Status data-sources card.",
    ))
    subject = f"Perkins: please log in to {label}"
    html = wrap_email(
        f"<p>{body}</p>"
        f"<p><a href=\"{DASHBOARD_URL}\">Open the dashboard</a></p>"
    )
    return subject, html


def send_login_request(integration: str, *, tenant_id: int | None = None) -> list[str]:
    import adapters.resend as resend  # noqa: PLC0415
    from core.email_gate import decide  # noqa: PLC0415

    subject, html = login_email_html(integration)
    ids: list[str] = []
    for to in RECIPIENTS:
        if not decide(to).allowed:
            continue
        ids.append(resend.send(
            reply_to=to,
            to=to,
            subject=subject,
            html=html,
            tenant_id=tenant_id,
            send_type="login_request",
            metadata={"integration": integration},
        ))
    return ids
