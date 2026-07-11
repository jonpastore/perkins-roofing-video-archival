"""Pure builder for the user-invitation email (no I/O, 100% coverage required).

Composes a branded, email-safe HTML invitation from server-derived values and
wraps it with the shared :func:`core.email_template.wrap_email` shell so the
styling matches every other platform email. All caller-supplied strings
(recipient/inviter names) are HTML-escaped — the send path passes user input
straight through, so escaping happens here at the composition boundary.
"""

from __future__ import annotations

import html as _html

from core.email_template import wrap_email

_ROLE_LABELS = {
    "admin": "Administrator",
    "web_admin": "Web Administrator",
    "sales": "Sales",
}

_BRAND_NAVY = "#1b2a52"
# Hosted on the app's Firebase Hosting (web/public/perkins-logo.png). Dark navy
# wordmark on transparent, so it renders on a white header band, not the navy one.
_DEFAULT_LOGO_URL = "https://app.perkinsroofing.net/perkins-logo.png"


def _role_label(role: str) -> str:
    """Friendly display label for a role claim (falls back to Title Case)."""
    return _ROLE_LABELS.get(role, role.replace("_", " ").title())


def build_invite_email(
    *,
    recipient_name: str | None,
    role: str,
    sign_in_url: str,
    company_name: str = "Perkins Roofing",
    inviter_name: str | None = None,
    logo_url: str = _DEFAULT_LOGO_URL,
) -> tuple[str, str]:
    """Return ``(subject, html)`` for a user-invitation email.

    Args:
        recipient_name: Invitee display name for the greeting; ``None`` → generic.
        role:           Role claim being granted (``admin``/``web_admin``/``sales``…).
        sign_in_url:    Server-derived sign-in URL (trusted; used in the CTA href).
        company_name:   Tenant/company display name.
        inviter_name:   Optional name of the admin who sent the invite.
        logo_url:       Absolute https logo URL rendered in the (white) header band.
    """
    role_label = _role_label(role)
    greeting = f"Hi {_html.escape(recipient_name)}," if recipient_name else "Hello,"
    added = (
        f"{_html.escape(inviter_name)} has added you"
        if inviter_name
        else "You've been added"
    )
    company = _html.escape(company_name)
    url = sign_in_url

    body = (
        f'<p style="margin:0 0 16px;">{greeting}</p>'
        f'<p style="margin:0 0 16px;">{added} to the {company} platform as '
        f"<strong>{role_label}</strong>.</p>"
        '<p style="margin:0 0 24px;">Sign in with your Google account to get started:</p>'
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">'
        f'<tr><td style="border-radius:6px; background-color:{_BRAND_NAVY};">'
        f'<a href="{url}" style="display:inline-block; padding:12px 28px; font-size:15px;'
        ' font-weight:600; color:#ffffff; text-decoration:none; border-radius:6px;">'
        f"Sign In to {company}</a></td></tr></table>"
        '<p style="margin:0 0 8px; font-size:13px; color:#667085;">'
        "Or paste this link into your browser:<br>"
        f'<a href="{url}" style="color:{_BRAND_NAVY};">{_html.escape(url)}</a></p>'
        '<p style="margin:16px 0 0; font-size:13px; color:#667085;">'
        "If you weren&rsquo;t expecting this invitation, you can safely ignore this email.</p>"
    )

    header_html = (
        f'<img src="{logo_url}" alt="{company}" width="180" '
        'style="display:block; border:0; max-width:180px; height:auto;">'
    )
    subject = f"You've been invited to the {company_name} platform"
    return subject, wrap_email(
        body_html=body,
        header_html=header_html,
        company_name=company_name,
        header_bg="#ffffff",
    )
