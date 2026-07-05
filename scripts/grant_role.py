"""Assign / list / revoke platform roles via Firebase custom claims.

This is the role-assignment mechanism for the platform. Auth model: users sign in with Google
(Firebase Auth); the SPA sends the ID token; the API verifies it and reads the `role` custom
claim (admin | sales). core.authz is deny-by-default, so a signed-in user with NO role can do
nothing — granting a role here IS the allowlist. Only run this as a project admin.

Usage:
    .venv/bin/python scripts/grant_role.py grant  <email> admin|sales
    .venv/bin/python scripts/grant_role.py revoke <email>
    .venv/bin/python scripts/grant_role.py list
    .venv/bin/python scripts/grant_role.py whoami <email>

Requires firebase-admin + application-default credentials (owner/admin) and
GOOGLE_CLOUD_PROJECT set. The user must have signed in at least once (so the Firebase
user record exists) before a role can be granted.
"""
from __future__ import annotations

import sys

VALID_ROLES = {"admin", "sales"}


def _auth():
    import firebase_admin
    from firebase_admin import auth
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return auth


def grant(email: str, role: str) -> None:
    if role not in VALID_ROLES:
        raise SystemExit(f"role must be one of {sorted(VALID_ROLES)}, got {role!r}")
    auth = _auth()
    user = auth.get_user_by_email(email)
    claims = dict(user.custom_claims or {})
    claims["role"] = role
    auth.set_custom_user_claims(user.uid, claims)
    print(f"granted role={role} to {email} (uid={user.uid}). They must re-login to refresh the token.")


def revoke(email: str) -> None:
    auth = _auth()
    user = auth.get_user_by_email(email)
    claims = dict(user.custom_claims or {})
    claims.pop("role", None)
    auth.set_custom_user_claims(user.uid, claims)
    auth.revoke_refresh_tokens(user.uid)  # force existing sessions to re-auth (now role-less)
    print(f"revoked role from {email} (uid={user.uid}); refresh tokens invalidated.")


def whoami(email: str) -> None:
    auth = _auth()
    user = auth.get_user_by_email(email)
    print(f"{email}: uid={user.uid} role={(user.custom_claims or {}).get('role', '(none)')}")


def list_users() -> None:
    auth = _auth()
    for u in auth.list_users().iterate_all():
        role = (u.custom_claims or {}).get("role")
        if role:
            print(f"  {u.email or u.uid}: {role}")


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    cmd, *rest = argv
    if cmd == "grant" and len(rest) == 2:
        grant(rest[0], rest[1])
    elif cmd == "revoke" and len(rest) == 1:
        revoke(rest[0])
    elif cmd == "whoami" and len(rest) == 1:
        whoami(rest[0])
    elif cmd == "list":
        list_users()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
