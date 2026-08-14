"""verify_token is the only untested link in the admin-elevation security chain: it must
surface email_verified (defaulting False when absent) so core.authz can't be tricked into
elevating an unverified email. See docs/reviews/2026-07-07-deep-review.md."""
import firebase_admin.auth as fa_auth

import adapters.firebase as FB


def test_maps_claims_including_email_verified(monkeypatch):
    monkeypatch.setattr(FB, "_ensure", lambda: None)
    monkeypatch.setattr(fa_auth, "verify_id_token",
                        lambda tok, check_revoked=True: {
                            "uid": "u1", "email": "a@b.com",
                            "email_verified": True, "role": "admin"})
    out = FB.verify_token("tok")
    assert out == {"uid": "u1", "email": "a@b.com", "email_verified": True,
                   "role": "admin", "firebase": {}}


def test_email_verified_defaults_false_when_absent(monkeypatch):
    monkeypatch.setattr(FB, "_ensure", lambda: None)
    monkeypatch.setattr(fa_auth, "verify_id_token",
                        lambda tok, check_revoked=True: {"uid": "u2", "email": "x@y.com"})
    out = FB.verify_token("tok")
    assert out["email_verified"] is False    # missing claim → False (fail closed)
    assert out["role"] == ""
    assert out["firebase"] == {}


def test_passes_firebase_tenant_through(monkeypatch):
    """Without this, _resolve_tenant never sees a GCIP tenant and every user
    lands on tenant 1 — including tenant 2."""
    monkeypatch.setattr(FB, "_ensure", lambda: None)
    monkeypatch.setattr(fa_auth, "verify_id_token",
                        lambda tok, check_revoked=True: {
                            "uid": "u3", "email": "t2@x.com", "email_verified": True,
                            "firebase": {"tenant": "gcip-tenant-2",
                                         "sign_in_provider": "google.com"}})
    out = FB.verify_token("tok")
    assert out["firebase"]["tenant"] == "gcip-tenant-2"
