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
    assert out == {"uid": "u1", "email": "a@b.com", "email_verified": True, "role": "admin"}


def test_email_verified_defaults_false_when_absent(monkeypatch):
    monkeypatch.setattr(FB, "_ensure", lambda: None)
    monkeypatch.setattr(fa_auth, "verify_id_token",
                        lambda tok, check_revoked=True: {"uid": "u2", "email": "x@y.com"})
    out = FB.verify_token("tok")
    assert out["email_verified"] is False    # missing claim → False (fail closed)
    assert out["role"] == ""
