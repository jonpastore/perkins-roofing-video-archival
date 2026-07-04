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
