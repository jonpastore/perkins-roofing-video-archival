"""Pure role→action authorization matrix. Verified server-side in the FastAPI auth
dependency (adapters/firebase verifies the token; this decides what the role may do)."""

_MATRIX = {
    "admin": {"*"},  # admin can do everything
    "sales": {
        "search", "ask",
        "email_compose", "email_proof", "email_send",
        "article_read",
    },
}


def can(role, action):
    """True if ``role`` is permitted ``action``. Unknown roles are denied everything."""
    perms = _MATRIX.get(role, set())
    return "*" in perms or action in perms


def effective_role(email, role, default_admins):
    """Resolve the caller's effective role. Emails in ``default_admins`` are admin by
    default — no per-user grant needed — so the core team is admin the instant they
    sign in. Everyone else falls back to their assigned custom-claim ``role``."""
    if email and email.lower() in default_admins:
        return "admin"
    return role
