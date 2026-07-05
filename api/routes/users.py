"""Admin user-management routes — list Firebase users and set/clear roles.

Export ``router`` only; mount onto the main app in api/app.py.

Role requirements (all endpoints): manage_templates (admin only).

NOTE: setting custom claims requires the runtime Service Account to have the
Firebase Authentication Admin role (roles/firebaseauth.admin) in IAM. The
endpoint is written correctly; the parent must grant that IAM binding.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.auth import require_role

router = APIRouter(prefix="/admin/users", tags=["users"])

_VALID_ROLES = {"admin", "sales"}


class RoleAssignment(BaseModel):
    email: str
    role: Optional[str] = None  # "admin" | "sales" | null/empty → clear


def _firebase_auth():
    """Return firebase_admin.auth, initialising the app if needed."""
    import firebase_admin
    from firebase_admin import auth
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return auth


@router.get("")
def list_users(claims=Depends(require_role("manage_users"))):
    """List up to 200 Firebase users with their current role claim."""
    auth = _firebase_auth()
    results = []
    page = auth.list_users(max_results=200)
    for user in page.iterate_all():
        role = (user.custom_claims or {}).get("role") or None
        results.append({
            "uid": user.uid,
            "email": user.email or "",
            "role": role,
        })
    return results


@router.post("/role")
def set_user_role(body: RoleAssignment, claims=Depends(require_role("manage_users"))):
    """Assign or clear the role custom claim for a Firebase user identified by email.

    Pass role=null or role="" to clear. Returns {uid, email, role}.
    404 if the email has no Firebase user record.
    """
    auth = _firebase_auth()
    try:
        user = auth.get_user_by_email(body.email)
    except Exception:
        raise HTTPException(status_code=404, detail="user not found")

    role = body.role or None
    if role and role not in _VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(_VALID_ROLES)}")

    existing_claims = dict(user.custom_claims or {})
    if role:
        existing_claims["role"] = role
    else:
        existing_claims.pop("role", None)

    auth.set_custom_user_claims(user.uid, existing_claims)
    return {"uid": user.uid, "email": body.email, "role": role}
