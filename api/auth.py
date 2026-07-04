"""FastAPI auth dependency: verify the Firebase ID token, then enforce the role→action
matrix from core.authz. 401 for a missing/invalid token, 403 for an insufficient role.
`set_verifier` allows injecting a fake verifier in tests (no live Firebase needed)."""
from fastapi import Header, HTTPException

from core.authz import can

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


def require_role(action):
    """FastAPI dependency factory — allow the request only if the caller's role `can(action)`."""
    def dep(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        try:
            claims = _get_verifier()(authorization[7:])
        except Exception:
            raise HTTPException(status_code=401, detail="invalid token")
        if not can(claims.get("role", ""), action):
            raise HTTPException(status_code=403, detail="forbidden")
        return claims
    return dep
