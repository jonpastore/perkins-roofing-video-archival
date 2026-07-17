"""Liveness probes for shared platform integrations (plan Phase 1.3, I/O — coverage-omitted).

READS ONLY — NEVER a refresh attempt. Some providers' refresh tokens are single-use
(Knowify: core/knowify/tokens.py:11) — a probe that force-refreshed "to check" would burn
or rotate a live credential just to observe it. Each probe below does the cheapest
authenticated GET that proves the credential still works, and maps the result onto
core.integration_health.ProbeResult:
  - 401 / invalid_grant / 403-revoked -> hard_auth_failure=True (credential is provably
    dead; per Principle 5 this alarms on the very first probe cycle).
  - network error / 5xx / other non-2xx -> ok=False, transient (alarms only after
    TRANSIENT_FAILURE_THRESHOLD consecutive failures).
  - unset/missing configuration -> None (distinct from "configured but dead" — the job
    maps this to status='unconfigured', not 'broken').

probe_youtube_reply() is the one exception to "never refresh": Google's refresh tokens are
explicitly multi-use (plan Principle 2 / pre-mortem 4), and the only cheap liveness check
available is exchanging the stored refresh token for an access token (adapters.youtube_
comments._owner_access_token) — that exchange does not rotate or invalidate anything.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import requests

import adapters.wordpress as wordpress
import adapters.youtube_comments as youtube_comments
from core.integration_health import ProbeResult

_RESEND_UA = "PerkinsRoofingPlatform/1.0"  # Cloudflare 1010-blocks default urllib UA (see adapters/resend.py)


def probe_wordpress() -> ProbeResult | None:
    """GET /wp-json/wp/v2/users/me with the app-password basic auth."""
    if not (os.environ.get("WP_URL") and os.environ.get("WP_USER") and os.environ.get("WP_APP_PWD")):
        return None
    url = wordpress._wp_api_url("/wp-json/wp/v2/users/me")
    try:
        resp = requests.get(url, auth=wordpress._auth(), timeout=10)
    except requests.RequestException as exc:
        return ProbeResult(ok=False, error=str(exc))
    if resp.status_code in (401, 403):
        return ProbeResult(ok=False, hard_auth_failure=True, error=f"WP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        return ProbeResult(ok=False, error=f"WP {resp.status_code}: {resp.text[:200]}")
    return ProbeResult(ok=True)


def probe_resend() -> ProbeResult | None:
    """Coarse liveness for Resend via GET /domains.

    LIMITATION (deliberate): Resend has no read endpoint a SEND-scoped key can call —
    /domains returns 401/403 for a perfectly valid sending key, indistinguishable
    from a revoked one, and the only true send test is POST /emails (which actually
    sends). So we treat any HTTP response (incl. 401/403) as healthy: it proves
    Resend is up AND the key is present. A genuinely dead Resend (network failure or
    5xx) still trips the transient path; real send failures surface via email_logs.
    This avoids a false "broken" alarm on every cycle for a working sending key.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return None
    req = urllib.request.Request(
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": _RESEND_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return ProbeResult(ok=True)
    except urllib.error.HTTPError as exc:
        # 401/403 == reachable + key present (sending-scoped keys always 401 here).
        if exc.code in (401, 403):
            return ProbeResult(ok=True)
        # 5xx / 429 == Resend itself degraded → transient (N=3 before broken).
        return ProbeResult(ok=False, error=f"Resend HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return ProbeResult(ok=False, error=str(exc.reason))


def probe_knowify() -> ProbeResult | None:
    """Reuse core.knowify.tokens.is_valid() against the current stored token. Never refresh."""
    from core.knowify.tokens import is_valid, load_tokens  # noqa: PLC0415

    try:
        tok = load_tokens()
    except Exception as exc:  # noqa: BLE001 — Secret Manager access failure, not a code bug
        return ProbeResult(ok=False, error=str(exc))
    if not isinstance(tok, dict) or not tok.get("access_token"):
        # Placeholder / not-yet-configured token blob (no access_token) — treat as
        # unconfigured, not broken: this integration was never set up, so it should
        # not raise an outage alarm.
        return None
    try:
        ok = is_valid(tok)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return ProbeResult(ok=False, hard_auth_failure=True, error=f"Knowify HTTP {exc.code}")
        return ProbeResult(ok=False, error=f"Knowify HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return ProbeResult(ok=False, error=str(exc.reason))
    except (KeyError, TypeError, ValueError) as exc:
        # Malformed token shape — unusable but not a network/auth signal.
        return ProbeResult(ok=False, error=f"Knowify token malformed: {exc}")
    if not ok:
        return ProbeResult(ok=False, hard_auth_failure=True, error="Knowify token invalid (401 at /valid)")
    return ProbeResult(ok=True)


def probe_youtube_reply() -> ProbeResult | None:
    """Exchange the stored owner refresh token for an access token.

    Google refresh tokens are multi-use (plan Principle 2 / pre-mortem 4) — this exchange
    is the cheapest liveness check available and does not rotate or burn the credential,
    unlike Knowify's single-use refresh tokens.
    """
    if not youtube_comments.reply_oauth_configured():
        return None
    try:
        youtube_comments._owner_access_token()
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            body = ""
            try:
                body = json.loads(exc.read().decode())
            except Exception:  # noqa: BLE001 — best-effort error detail only
                pass
            return ProbeResult(ok=False, hard_auth_failure=True, error=f"YouTube reply HTTP {exc.code} {body}")
        return ProbeResult(ok=False, error=f"YouTube reply HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return ProbeResult(ok=False, error=str(exc.reason))
    except RuntimeError as exc:
        # _owner_access_token() raises RuntimeError on a response with no access_token —
        # a live-looking exchange that returned garbage is as good as a dead credential.
        return ProbeResult(ok=False, hard_auth_failure=True, error=str(exc))
    return ProbeResult(ok=True)
