"""OAuth capture-flow state signing (plan 2026-07-17 Phase 1.5). Pure — no I/O.

The OAuth callback is an UNAUTHENTICATED browser GET (this app is bearer-token,
not cookie-session), so the signed state is the ENTIRE tenant binding for the
credential write. Design (consensus-reviewed, Architect H3 / pre-mortem 2):

  state = b64url(payload) . b64url(HMAC-SHA256(key, payload))
  payload = compact JSON {"t": tenant_id, "p": platform, "n": nonce, "e": exp}

- Key material is passed IN (callers load it from Secret Manager); ``verify_state``
  accepts a list of keys so a two-key rotation window works: sign with keys[0],
  verify against any.
- ``verify_state`` NEVER raises on hostile input — any malformed, tampered,
  wrong-key, or expired state returns None (fail closed).
- The nonce's single-use burn (DELETE ... RETURNING on oauth_state_nonces) and
  the platform-registry / redirect-uri checks live at the route layer; this
  module only owns the cryptographic binding + expiry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

# State lifetime: consent + redirect round-trip. Generous but bounded.
DEFAULT_STATE_TTL_SECONDS = 600


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _mac(key: bytes, payload: bytes) -> bytes:
    return hmac.new(key, payload, hashlib.sha256).digest()


def sign_state(*, tenant_id: int, platform: str, nonce: str, exp: int, key: bytes) -> str:
    """Mint a signed state token binding {tenant, platform, nonce} until ``exp``.

    Args:
        tenant_id: Verified caller tenant (from require_role_db claims at /start).
        platform:  Provider key from the fixed platform registry.
        nonce:     Random single-use value persisted server-side at /start.
        exp:       Unix-seconds expiry (now + DEFAULT_STATE_TTL_SECONDS typically).
        key:       Current HMAC key (Secret Manager ``oauth-state-hmac``).

    Raises:
        ValueError: on empty key/nonce/platform or non-positive tenant_id/exp —
        minting is a trusted-path operation; garbage in is a programming error.
    """
    if not key:
        raise ValueError("signing key must be non-empty")
    if not nonce or not platform:
        raise ValueError("nonce and platform must be non-empty")
    if tenant_id <= 0 or exp <= 0:
        raise ValueError("tenant_id and exp must be positive")
    payload = json.dumps(
        {"t": tenant_id, "p": platform, "n": nonce, "e": exp},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return f"{_b64e(payload)}.{_b64e(_mac(key, payload))}"


def verify_state(state: str, keys: list[bytes], *, now: int) -> dict | None:
    """Verify a state token → {"tenant_id", "platform", "nonce"} or None.

    Checks, in order: structural shape → signature against ANY of ``keys``
    (constant-time compare; two-key rotation window) → expiry (``e`` strictly
    greater than ``now``). Returns None on ANY failure — hostile input must
    never raise (the callback is internet-facing and unauthenticated).
    """
    if not state or not keys or "." not in state:
        return None
    try:
        payload_b64, mac_b64 = state.split(".", 1)
        payload = _b64d(payload_b64)
        mac = _b64d(mac_b64)
    except Exception:  # noqa: BLE001 — malformed base64 from the open internet
        return None

    if not any(hmac.compare_digest(_mac(k, payload), mac) for k in keys if k):
        return None

    try:
        obj = json.loads(payload)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(obj, dict):
        return None

    tenant_id = obj.get("t")
    platform = obj.get("p")
    nonce = obj.get("n")
    exp = obj.get("e")
    if not isinstance(tenant_id, int) or not isinstance(exp, int):
        return None
    if not isinstance(platform, str) or not platform or not isinstance(nonce, str) or not nonce:
        return None
    if exp <= now:
        return None

    return {"tenant_id": tenant_id, "platform": platform, "nonce": nonce}
