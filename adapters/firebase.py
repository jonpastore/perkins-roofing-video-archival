"""Firebase Auth token verification (I/O — coverage-omitted). Verifies a Google-sign-in
ID token and returns the uid/email plus the `role` custom claim (admin|sales) that
core.authz uses. Requires `firebase-admin` + application-default credentials in prod."""

_app = None


def _ensure():
    global _app
    if _app is None:
        import firebase_admin
        _app = firebase_admin.initialize_app()  # uses GOOGLE_APPLICATION_CREDENTIALS / project default
    return _app


def verify_token(id_token):
    """Verify a Firebase ID token → {uid, email, role}. Raises on invalid/expired tokens."""
    _ensure()
    from firebase_admin import auth
    decoded = auth.verify_id_token(id_token, check_revoked=True)
    return {
        "uid": decoded.get("uid"),
        "email": decoded.get("email"),
        "email_verified": bool(decoded.get("email_verified", False)),
        "role": decoded.get("role", ""),
    }
