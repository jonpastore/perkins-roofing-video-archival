"""Pure role→action authorization matrix. Verified server-side in the FastAPI auth
dependency (adapters/firebase verifies the token; this decides what the role may do)."""

_MATRIX = {
    # admin — everything, including user + platform config management.
    "admin": {"*"},
    # web_admin — manages site content (articles, FAQ, scheduling, video, search), sees the
    # dashboard, but NOT email, users, or platform config (those stay admin-only).
    "web_admin": {
        # existing actions (unchanged — existing endpoints keep these checks)
        "search", "ask",
        "article_read", "manage_articles",
        "manage_scheduling", "approve_video",
        "manage_archive",
        "view_status",
        "manage_estimates",
        # F1 section-scoped actions (per TRD-F1 §11 — gate new F2/F3 endpoints)
        "kb_search", "kb_ask",
        "kb_faq_read", "kb_faq_manage",
        "kb_archive_read", "kb_archive_manage",
        "kb_contract_faq_read",
        "marketing_opportunities", "marketing_articles",
        "marketing_schedule", "marketing_clips",
        "marketing_comments", "marketing_video_approval",
        "marketing_status",
        "estimating_view", "estimating_manage",
        "quoting_view", "quoting_create", "quoting_send",
        "admin_users",
    },
    # sales — search/ask, email tools + email templates, bid estimator.
    "sales": {
        # existing actions (unchanged)
        "search", "ask",
        "email_compose", "email_proof", "email_send",
        "manage_templates", "article_read",
        "manage_estimates",
        # F1 section-scoped actions (per TRD-F1 §11)
        "kb_search", "kb_ask",
        "estimating_view",
        "quoting_view", "quoting_create", "quoting_send",
    },
    # platform_admin — cross-tenant management only; no wildcard, no operational actions.
    # Session/impersonation mechanics defined in TRD-F4.
    "platform_admin": {
        "admin_tenants",
        "admin_users",
    },
}
# Admin-only actions (granted only via admin's "*"): manage_users, manage_config,
# marketing_email, quoting_manage_templates, admin_config.
# manage_archive: backfill channel, poll KPIs — admin + web_admin.


def can(role, action):
    """True if ``role`` is permitted ``action``. Unknown roles are denied everything."""
    perms = _MATRIX.get(role, set())
    return "*" in perms or action in perms


def effective_role(email, role, default_admins, email_verified=False):
    """Resolve the caller's effective role. Emails in ``default_admins`` are admin by
    default — no per-user grant needed — so the core team is admin the instant they
    sign in. Everyone else falls back to their assigned custom-claim ``role``.

    SECURITY: email-based elevation requires a VERIFIED email. `verify_id_token` proves the
    token was minted by our Firebase project but NOT that the email is verified, so without
    this gate anyone who could self-register a `*@perkinsroofing.net` address (if a
    password/email-link provider were enabled) would be promoted to admin. An explicit
    custom-claim ``role`` is a trusted server-side grant and is always honored."""
    if email_verified and email and email.lower() in default_admins:
        return "admin"
    return role
