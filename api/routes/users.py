"""Admin user-management routes — list Firebase users and set/clear roles.

Export ``router`` only; mount onto the main app in api/app.py.

Role requirements (all endpoints): manage_users (admin only).

NOTE: setting custom claims requires the runtime Service Account to have the
Firebase Authentication Admin role (roles/firebaseauth.admin) in IAM. The
endpoint is written correctly; the parent must grant that IAM binding.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import current_claims, get_db_session, require_role
from app.config import settings
from app.models import UserSetting
from app.observability import log

router = APIRouter(prefix="/admin/users", tags=["users"])
me_router = APIRouter(prefix="/me", tags=["me"])

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


class SignatureRequest(BaseModel):
    signature: Optional[str] = None


class AdminSignatureRequest(BaseModel):
    email: str
    signature: Optional[str] = None


def _firebase_auth():
    """Return firebase_admin.auth, initialising the app if needed."""
    import firebase_admin
    from firebase_admin import auth
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return auth


@router.get("")
def list_users(
    claims=Depends(require_role("manage_users")),
    db: Session = Depends(get_db_session),
):
    """List up to 200 Firebase users with their current role claim and display name.

    - Filters out rows with a blank/missing email (anonymous or phone-only accounts).
    - Merges DEFAULT_ADMINS: any admin email not present in Firebase gets a synthetic
      entry (uid="default:<email>", role="admin") so the UI always shows all admins.
    """
    auth = _firebase_auth()
    results = []
    seen_emails: set[str] = set()

    # Load all signatures in one query for efficiency.
    # User-management always operates in the caller's own verified tenant context —
    # sourced from the verified token claim, never a hardcoded literal (TRD-F4 §4.2:
    # a token with no GCIP claim resolves to tenant 1, but that value comes from
    # claim resolution, not a constant).
    sigs = {r.email.lower(): r.signature for r in db.query(UserSetting).all()}

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
            "signature": sigs.get(email.lower()),
            # Default admins are protected from deletion (the delete endpoint 403s them). Flag it
            # so the UI hides the trash for a signed-in default admin too — not just synthetic ones.
            "is_default_admin": email.lower() in settings.DEFAULT_ADMINS,
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
                "signature": sigs.get(admin_email.lower()),
                "is_default_admin": True,
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

    # Send the branded invitation email. Best-effort: the role claim is already set
    # (the user is authorized regardless), so a mail failure must not 500 the invite —
    # it is reported back in the response for the UI to surface.
    display_name = getattr(user, "display_name", None) or body.display_name or None
    email_sent, email_error = _send_invite_email(
        to_email=body.email,
        recipient_name=display_name,
        role=body.role,
        inviter_claims=claims,
    )

    return {
        "uid": user.uid,
        "email": body.email,
        "display_name": display_name,
        "role": body.role,
        "email_sent": email_sent,
        "email_error": email_error,
    }


def _send_invite_email(
    *, to_email: str, recipient_name: Optional[str], role: str, inviter_claims: dict
) -> tuple[bool, Optional[str]]:
    """Compose + send the invitation email. Returns (sent, error_message)."""
    from adapters import resend
    from core.invite_email import build_invite_email

    inviter_email = (inviter_claims or {}).get("email")
    sign_in_url = os.environ.get("PUBLIC_APP_URL", "https://app.perkinsroofing.net")
    subject, html = build_invite_email(
        recipient_name=recipient_name,
        role=role,
        sign_in_url=sign_in_url,
        inviter_name=(inviter_claims or {}).get("name"),
    )
    try:
        msg_id = resend.send(
            from_name="Perkins Roofing",
            reply_to=inviter_email or "info@perkinsroofing.net",
            to=to_email,
            subject=subject,
            html=html,
            tenant_id=(inviter_claims or {}).get("tenant_id") or (inviter_claims or {}).get("tenantId"),
            send_type="user_invite",
            metadata={"role": role},
        )
        return (not resend.is_blocked_message_id(msg_id)), (
            "blocked by outbound email gate" if resend.is_blocked_message_id(msg_id) else None
        )
    except Exception as exc:  # noqa: BLE001 — mail is best-effort; pre-auth already succeeded
        log("invite_email_failed", email=to_email, error=str(exc))
        return False, str(exc)


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


@router.put("/signature")
def set_user_signature_admin(
    body: AdminSignatureRequest,
    claims=Depends(require_role("manage_users")),
    db: Session = Depends(get_db_session),
):
    """Set or clear the email signature for any user (admin only)."""
    row = db.get(UserSetting, body.email.lower())
    if row is None:
        row = UserSetting(
            email=body.email.lower(),
            signature=body.signature or None,
            tenant_id=db.info["tenant_id"],
        )
        db.add(row)
    else:
        row.signature = body.signature or None
    db.flush()
    return {"email": body.email, "signature": body.signature or None}


# ---------------------------------------------------------------------------
# /me/signature — current user's own signature
# ---------------------------------------------------------------------------

@me_router.get("/signature")
def get_my_signature(
    claims=Depends(current_claims),
    db: Session = Depends(get_db_session),
):
    email = (claims.get("email") or "").lower()
    row = db.get(UserSetting, email)
    return {"email": email, "signature": row.signature if row else None}


@me_router.put("/signature")
def set_my_signature(
    body: SignatureRequest,
    claims=Depends(current_claims),
    db: Session = Depends(get_db_session),
):
    email = (claims.get("email") or "").lower()
    row = db.get(UserSetting, email)
    if row is None:
        row = UserSetting(
            email=email,
            signature=body.signature or None,
            tenant_id=db.info["tenant_id"],
        )
        db.add(row)
    else:
        row.signature = body.signature or None
    db.flush()
    return {"email": email, "signature": body.signature or None}


def _directory_access_token(subject: str, scope: str, key_file: str) -> str:
    """Mint an access token for the Workspace Directory API, impersonating ``subject`` via
    domain-wide delegation.

    KEYLESS by default: Cloud Run compute credentials do NOT support ``.with_subject``, so we
    build a delegated JWT (iss=run SA, sub=subject) and sign it with the IAM Credentials
    ``signJwt`` API — the run SA already holds ``roles/iam.serviceAccountTokenCreator`` on itself
    — then exchange it at the OAuth token endpoint. No downloaded key. A delegated SA JSON key is
    used instead only when ``key_file`` is set.
    """
    import json
    import time
    import urllib.parse
    import urllib.request

    import google.auth
    from google.auth.transport.requests import Request as GRequest

    if key_file:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            key_file, scopes=[scope], subject=subject
        )
        creds.refresh(GRequest())
        return creds.token

    # Keyless domain-wide delegation via IAM signJwt.
    adc, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    adc.refresh(GRequest())
    sa_email = getattr(adc, "service_account_email", "") or ""
    if not sa_email or sa_email == "default":
        meta = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(meta, timeout=5) as r:  # noqa: S310 — fixed metadata URL
            sa_email = r.read().decode()

    now = int(time.time())
    claims = {
        "iss": sa_email, "sub": subject, "scope": scope,
        "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600,
    }
    sign_url = (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{sa_email}:signJwt"
    )
    sign_req = urllib.request.Request(
        sign_url, method="POST",
        data=json.dumps({"payload": json.dumps(claims)}).encode(),
        headers={"Authorization": f"Bearer {adc.token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(sign_req, timeout=10) as r:  # noqa: S310 — fixed google URL
        signed_jwt = json.loads(r.read().decode())["signedJwt"]

    token_req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", method="POST",
        data=urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": signed_jwt,
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(token_req, timeout=10) as r:  # noqa: S310 — fixed google URL
        return json.loads(r.read().decode())["access_token"]


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
        token = _directory_access_token(subject, scope, key_file)

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
        log("directory_lookup", configured=True, count=len(out), domain=domain)
        return {"users": out, "configured": True}
    except Exception as e:  # noqa: BLE001 — directory is best-effort; invite-by-email still works
        log("directory_lookup", configured=False, reason=str(e)[:300])
        return {"users": [], "configured": False, "reason": str(e)[:300]}
