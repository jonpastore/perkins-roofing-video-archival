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
        "quoting_manage_templates", "quoting_manage_settings",
        "admin_users",
        # Sales console read-only billing view (Wave 2): list/detail invoices + payments.
        "billing_view",
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
        # Sales console read-only billing view (Wave 2): list/detail invoices + payments.
        # Does NOT grant billing_manage (create invoice / record payment — admin only).
        "billing_view",
    },
    # knowify_admin — trigger sync + reconnect OAuth. Admin-only (admin has "*").
    # Do NOT grant to web_admin/sales/content roles (least privilege).
    # Read routes (/status, /customers, /invoices, /payments, /raw/*) use billing_manage.
    "knowify_admin": set(),  # no standalone grants; admin satisfies via "*"
    # platform_admin — cross-tenant management only; no wildcard, no operational actions.
    # Session/impersonation mechanics defined in TRD-F4.
    "platform_admin": {
        "admin_tenants",
        "admin_users",
        "provision_tenant",
        "view_all_tenants",
        "manage_platform_config",
        "impersonate_tenant",
    },
}
# Admin-only actions (granted only via admin's "*"): manage_users, manage_config,
# marketing_email, admin_config.
# manage_archive: backfill channel, poll KPIs — admin + web_admin.


def can(role, action):
    """True if ``role`` is permitted ``action``. Unknown roles are denied everything."""
    perms = _MATRIX.get(role, set())
    return "*" in perms or action in perms


def effective_role(email, role, tenant_id=1, db_session=None, email_verified=False):
    """Resolve the caller's effective role.

    F4 version: checks ``tenant_default_admins`` table via ``db_session`` for the given
    ``tenant_id``. Falls back to ``app.config.settings.DEFAULT_ADMINS`` frozenset when
    ``db_session`` is None (SQLite dev path) or a frozenset is passed as ``tenant_id``
    (backward-compat for pre-F4 callers that pass DEFAULT_ADMINS as the third arg).

    SECURITY: email-based elevation requires a VERIFIED email. ``verify_id_token`` proves
    the token was minted by our Firebase project but NOT that the email is verified.
    An explicit custom-claim ``role`` is a trusted server-side grant and is always honored.

    Backward-compatibility: pre-F4 callers pass (email, role, default_admins_frozenset,
    email_verified). We detect that via isinstance on the third arg and fall back to the
    frozenset path so no existing call sites break.
    """
    if not email_verified or not email:
        return role

    email_lower = email.lower()

    # Backward-compat: third positional arg was a frozenset (pre-F4 callers)
    if isinstance(tenant_id, (frozenset, set)):
        legacy_set = tenant_id
        if email_lower in legacy_set:
            return "admin"
        return role

    # DB path (F4): query tenant_default_admins
    if db_session is not None:
        try:
            from sqlalchemy import text
            row = db_session.execute(
                text("SELECT 1 FROM tenant_default_admins WHERE tenant_id=:t AND email=:e"),
                {"t": tenant_id, "e": email_lower},
            ).fetchone()
            if row is not None:
                return "admin"
        except Exception:
            # Table may not exist yet (migrations pending); fall through to config fallback
            pass
    else:
        # Fallback: config frozenset (dev/SQLite/no session available)
        from app.config import settings
        if email_lower in settings.DEFAULT_ADMINS:
            return "admin"

    return role
