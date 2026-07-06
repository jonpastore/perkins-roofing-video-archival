"""Admin user-management routes — list Firebase users and set/clear roles.

Export ``router`` only; mount onto the main app in api/app.py.

Role requirements (all endpoints): manage_users (admin only).

NOTE: setting custom claims requires the runtime Service Account to have the
Firebase Authentication Admin role (roles/firebaseauth.admin) in IAM. The
endpoint is written correctly; the parent must grant that IAM binding.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.auth import require_role
from app.config import settings

router = APIRouter(prefix="/admin/users", tags=["users"])

_VALID_ROLES = {"admin", "web_admin", "sales"}


class RoleAssignment(BaseModel):
    email: str
    role: Optional[str] = None  # "admin" | "web_admin" | "sales" | null/empty → clear


class InviteRequest(BaseModel):
    email: str
    role: str  # required for invite
    display_name: Optional[str] = None


class DeleteRequest(BaseModel):
    email: str


def _firebase_auth():
    """Return firebase_admin.auth, initialising the app if needed."""
    import firebase_admin
    from firebase_admin import auth
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return auth


@router.get("")
def list_users(claims=Depends(require_role("manage_users"))):
    """List up to 200 Firebase users with their current role claim and display name.

    - Filters out rows with a blank/missing email (anonymous or phone-only accounts).
    - Merges DEFAULT_ADMINS: any admin email not present in Firebase gets a synthetic
      entry (uid="default:<email>", role="admin") so the UI always shows all admins.
    """
    auth = _firebase_auth()
    results = []
    seen_emails: set[str] = set()

    page = auth.list_users(max_results=200)
    for user in page.iterate_all():
        email = (user.email or "").strip()
        if not email:
            # Skip blank/anonymous accounts — they produce empty rows in the UI.
            continue
        role = (user.custom_claims or {}).get("role") or None
        results.append({
            "uid": user.uid,
            "email": email,
            "display_name": user.display_name or None,
            "role": role,
        })
        seen_emails.add(email.lower())

    # Ensure all DEFAULT_ADMINS appear even if they have never signed in.
    for admin_email in sorted(settings.DEFAULT_ADMINS):
        if admin_email.lower() not in seen_emails:
            results.append({
                "uid": f"default:{admin_email}",
                "email": admin_email,
                "display_name": None,
                "role": "admin",
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


@router.post("/invite")
def invite_user(body: InviteRequest, claims=Depends(require_role("manage_users"))):
    """Pre-authorize a user by email + role before their first sign-in.

    Creates a Firebase user record if none exists, then sets the role custom claim.
    Idempotent: if the user already exists, the existing record is used.
    Returns {uid, email, display_name, role}.

    Note: Google Workspace org-directory autocomplete requires domain-wide delegation
    and admin consent — that integration is out of scope. Use this email-invite form
    to pre-authorize any email address (internal or external).
    """
    if body.role not in _VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(_VALID_ROLES)}")

    auth = _firebase_auth()

    # Get existing user or create a new record.
    try:
        user = auth.get_user_by_email(body.email)
    except Exception:
        # User doesn't exist — create a passwordless record so the role claim
        # is waiting when they sign in via Google/SSO for the first time.
        kwargs: dict = {"email": body.email}
        if body.display_name:
            kwargs["display_name"] = body.display_name
        user = auth.create_user(**kwargs)

    existing_claims = dict(user.custom_claims or {})
    existing_claims["role"] = body.role
    auth.set_custom_user_claims(user.uid, existing_claims)

    return {
        "uid": user.uid,
        "email": body.email,
        "display_name": getattr(user, "display_name", None) or body.display_name or None,
        "role": body.role,
    }


@router.delete("")
def delete_user(body: DeleteRequest, claims=Depends(require_role("manage_users"))):
    """Revoke and delete a user: revoke their refresh tokens (kills active sessions) then
    delete the Firebase record. 404 if no such user.

    A DEFAULT_ADMINS email cannot be deleted here — they are admin-by-policy and would be
    re-admitted on next sign-in, so deletion would be misleading. Change the DEFAULT_ADMINS
    env to remove a default admin.
    """
    if body.email.strip().lower() in settings.DEFAULT_ADMINS:
        raise HTTPException(
            status_code=400,
            detail="cannot delete a default admin — change the DEFAULT_ADMINS env instead",
        )
    auth = _firebase_auth()
    try:
        user = auth.get_user_by_email(body.email)
    except Exception:
        raise HTTPException(status_code=404, detail="user not found")

    auth.revoke_refresh_tokens(user.uid)
    auth.delete_user(user.uid)
    return {"deleted": body.email}


@router.get("/directory")
def directory_users(claims=Depends(require_role("manage_users"))):
    """List Google Workspace users in the org domain, to populate the invite dropdown.

    Requires a service account with domain-wide delegation authorized in the Workspace admin
    console for scope ``admin.directory.user.readonly``, impersonating a Workspace admin.
    Config via env:
      - WORKSPACE_ADMIN_SUBJECT: a Workspace admin email to impersonate (REQUIRED to enable)
      - WORKSPACE_DOMAIN:        domain to list (default perkinsroofing.net)
      - WORKSPACE_SA_KEY:        path to a delegated SA JSON key (else falls back to ADC)

    Degrades gracefully: returns {users: [], configured: false, reason: ...} when not set up,
    so the free-text email invite keeps working. Never raises — a 200 with configured=false.
    """
    import json
    import os
    import urllib.parse
    import urllib.request

    domain = os.getenv("WORKSPACE_DOMAIN", "perkinsroofing.net")
    subject = os.getenv("WORKSPACE_ADMIN_SUBJECT", "")
    key_file = os.getenv("WORKSPACE_SA_KEY", "")
    if not subject:
        return {
            "users": [],
            "configured": False,
            "reason": "GSuite directory not configured — set WORKSPACE_ADMIN_SUBJECT and grant "
            "the service account domain-wide delegation (scope admin.directory.user.readonly)",
        }

    scope = "https://www.googleapis.com/auth/admin.directory.user.readonly"
    try:
        import google.auth
        from google.auth.transport.requests import Request as GRequest
        if key_file:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                key_file, scopes=[scope], subject=subject
            )
        else:
            creds, _ = google.auth.default(scopes=[scope])
            creds = creds.with_subject(subject)  # delegation-capable SA required
        creds.refresh(GRequest())
        token = creds.token

        out, page = [], None
        while True:
            params = {
                "domain": domain,
                "maxResults": "200",
                "orderBy": "email",
                "projection": "basic",
                "viewType": "domain_public",
            }
            if page:
                params["pageToken"] = page
            url = "https://admin.googleapis.com/admin/directory/v1/users?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — fixed google URL
                data = json.loads(r.read().decode())
            for u in data.get("users", []):
                out.append({
                    "email": u.get("primaryEmail"),
                    "display_name": (u.get("name") or {}).get("fullName"),
                })
            page = data.get("nextPageToken")
            if not page:
                break
        return {"users": out, "configured": True}
    except Exception as e:  # noqa: BLE001 — directory is best-effort; invite-by-email still works
        return {"users": [], "configured": False, "reason": str(e)[:300]}
