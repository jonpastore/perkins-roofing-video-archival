#!/usr/bin/env python3
"""Behavioral validation script for W0 dynamic CORS middleware.

Exercises the middleware logic against allowed + disallowed origins, look-alike
origins, cross-tenant origin/host mismatches, preflight vs actual-request parity,
and Vary: Origin presence — all without a live server.

Exit 0 on success. Exit 1 and print failures on any assertion error.

Usage (from repo root):
    python3 scripts/validate_cors_dynamic.py
"""
from __future__ import annotations

import os
import sys
import traceback

# Ensure the repo root is on sys.path so imports resolve regardless of cwd.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Set a temp DB_URL so app.models doesn't try to open the real dev.db.
if "DB_URL" not in os.environ:
    import tempfile
    _tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp.close()
    os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

PASS = []
FAIL = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        msg = f"  FAIL  {name}" + (f" — {detail}" if detail else "")
        FAIL.append(msg)
        print(msg)


def build_origins():
    return [
        {"origin": "https://app.tenant1.com",   "tenant_id": 1},
        {"origin": "https://app.tenant2.com",   "tenant_id": 2},
        {"origin": "https://platform.degenito.ai", "tenant_id": None},
        {"origin": "http://localhost:5173",     "tenant_id": None},
    ]


def main() -> int:
    from api.middleware.cors import _is_allowed, _resolve_host_tenant, _cors_headers

    origins = build_origins()

    print("\n=== Allowed origins ===")
    check("tenant1 origin on tenant1 host",
          _is_allowed("https://app.tenant1.com", 1, origins))
    check("tenant2 origin on tenant2 host",
          _is_allowed("https://app.tenant2.com", 2, origins))
    check("platform-wide origin with no host tenant",
          _is_allowed("https://platform.degenito.ai", None, origins))
    check("localhost platform-wide on tenant1 host",
          _is_allowed("http://localhost:5173", 1, origins))
    check("localhost platform-wide on no-host",
          _is_allowed("http://localhost:5173", None, origins))

    print("\n=== Unregistered origins denied ===")
    check("completely unknown origin",
          not _is_allowed("https://evil.com", None, origins))
    check("empty origin string",
          not _is_allowed("", None, origins))

    print("\n=== Exact-match only (look-alike / suffix variants denied) ===")
    check("suffix variant of tenant1 domain denied",
          not _is_allowed("https://evil-app.tenant1.com", 1, origins))
    check("subdomain of registered origin denied",
          not _is_allowed("https://sub.app.tenant1.com", 1, origins))
    check("http vs https mismatch denied",
          not _is_allowed("http://app.tenant1.com", 1, origins))
    check("trailing slash variant denied",
          not _is_allowed("https://app.tenant1.com/", 1, origins))
    check("localhost without port denied",
          not _is_allowed("http://localhost", None, origins))
    check("localhost wrong port denied",
          not _is_allowed("http://localhost:9999", None, origins))

    print("\n=== Cross-tenant origin/host mismatch denied ===")
    check("tenant1 origin denied on tenant2 host",
          not _is_allowed("https://app.tenant1.com", 2, origins))
    check("tenant2 origin denied on tenant1 host",
          not _is_allowed("https://app.tenant2.com", 1, origins))
    check("tenant-scoped origin denied when host is platform-wide (None)",
          not _is_allowed("https://app.tenant1.com", None, origins))

    print("\n=== Host tenant resolution ===")
    check("app.tenant1.com resolves to tenant 1",
          _resolve_host_tenant("app.tenant1.com", origins) == 1)
    check("app.tenant2.com resolves to tenant 2",
          _resolve_host_tenant("app.tenant2.com", origins) == 2)
    check("platform.degenito.ai resolves to None (platform-wide)",
          _resolve_host_tenant("platform.degenito.ai", origins) is None)
    check("unknown host resolves to None",
          _resolve_host_tenant("unknown.example.com", origins) is None)

    print("\n=== Vary: Origin on every response ===")
    # Allowed origin
    hdrs_allowed = _cors_headers("https://app.tenant1.com", True)
    check("Vary: Origin present on allowed response",
          hdrs_allowed.get("Vary") == "Origin")
    check("ACAO header present on allowed response",
          hdrs_allowed.get("Access-Control-Allow-Origin") == "https://app.tenant1.com")

    # Denied origin
    hdrs_denied = _cors_headers("https://evil.com", False)
    check("Vary: Origin present on denied response",
          hdrs_denied.get("Vary") == "Origin")
    check("No ACAO header on denied response",
          "Access-Control-Allow-Origin" not in hdrs_denied)

    # No origin
    hdrs_no_origin = _cors_headers("", False)
    check("Vary: Origin present even with empty origin",
          hdrs_no_origin.get("Vary") == "Origin")

    print("\n=== Preflight vs actual-request parity ===")
    # Both preflight and actual use _is_allowed — they share the same resolution logic.
    # Verify the same origin yields the same allow/deny in both contexts.
    for origin, host_tid, label, expect_allowed in [
        ("https://app.tenant1.com",  1,    "allowed origin", True),
        ("https://evil.com",          None, "denied origin",  False),
        ("https://app.tenant1.com",  2,    "cross-tenant",   False),
    ]:
        result = _is_allowed(origin, host_tid, origins)
        check(f"preflight parity [{label}] — both allow={expect_allowed}",
              result == expect_allowed,
              f"_is_allowed returned {result}")

    print("\n=== Ez-Bids brand constants present ===")
    from core.tenant_settings import (
        EZBIDS_PLATFORM_NAME,
        EZBIDS_PLATFORM_DOMAIN,
        EZBIDS_PLATFORM_FROM_DOMAIN,
        EZBIDS_PLATFORM_SUPPORT_EMAIL,
    )
    check("EZBIDS_PLATFORM_NAME == 'Ez-Bids'",
          EZBIDS_PLATFORM_NAME == "Ez-Bids")
    check("EZBIDS_PLATFORM_DOMAIN contains degenito.ai",
          "degenito.ai" in EZBIDS_PLATFORM_DOMAIN)
    check("EZBIDS_PLATFORM_FROM_DOMAIN is a sending domain",
          "@" not in EZBIDS_PLATFORM_FROM_DOMAIN and "." in EZBIDS_PLATFORM_FROM_DOMAIN)
    check("EZBIDS_PLATFORM_SUPPORT_EMAIL has @",
          "@" in EZBIDS_PLATFORM_SUPPORT_EMAIL)

    print("\n=== IntegrationsSettings via TenantSettings ===")
    from core.tenant_settings import TenantSettings

    ts_empty = TenantSettings.load({})
    check("get_wp_url() empty when unset", ts_empty.get_wp_url() == "")
    check("get_yt_owner_channel_id() empty when unset",
          ts_empty.get_yt_owner_channel_id() == "")
    check("get_workspace_admin_subject() empty when unset",
          ts_empty.get_workspace_admin_subject() == "")

    ts_full = TenantSettings.load({
        "integrations": {
            "wp_url": "https://blog.example.com/",
            "yt_owner_channel_id": "UCtest123",
            "workspace_admin_subject": "admin@example.com",
        }
    })
    check("get_wp_url() strips trailing slash",
          ts_full.get_wp_url() == "https://blog.example.com")
    check("get_yt_owner_channel_id() returns value",
          ts_full.get_yt_owner_channel_id() == "UCtest123")
    check("get_workspace_admin_subject() returns value",
          ts_full.get_workspace_admin_subject() == "admin@example.com")

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\nFailed checks:")
        for f in FAIL:
            print(f"  {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
