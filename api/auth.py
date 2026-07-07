"""FastAPI auth dependencies: verify the Firebase ID token, then enforce the role→action
matrix from core.authz. 401 for a missing/invalid token, 403 for an insufficient role.
`set_verifier` allows injecting a fake verifier in tests (no live Firebase needed)."""
from fastapi import Header, HTTPException

from app.config import settings
from core.authz import can, effective_role

_verifier = None


def set_verifier(fn):
    """Override the token verifier (tests inject a fake; prod defaults to adapters.firebase)."""
    global _verifier
    _verifier = fn


def _get_verifier():
    global _verifier
    if _verifier is None:
        from adapters.firebase import verify_token
        _verifier = verify_token
    return _verifier


def _verify(authorization):
    """Verify the bearer token → claims dict with the effective role (default-admins applied).
    Raises 401 on a missing/invalid token."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = dict(_get_verifier()(authorization[7:]))
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    claims["role"] = effective_role(claims.get("email"), claims.get("role", ""),
                                    settings.DEFAULT_ADMINS, claims.get("email_verified", False))
    return claims


def current_claims(authorization: str = Header(default="")):
    """Any authenticated user — no role gate. Returns claims + effective role. Use for /me."""
    return _verify(authorization)


def require_role(action):
    """FastAPI dependency factory — allow the request only if the caller's role `can(action)`."""
    def dep(authorization: str = Header(default="")):
        claims = _verify(authorization)
        if not can(claims["role"], action):
            raise HTTPException(status_code=403, detail="forbidden")
        return claims
    return dep
