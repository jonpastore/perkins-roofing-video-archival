"""Best-effort GCP project spend for the weekly digest.

Needs roles/billing.viewer on the billing account.
The Cloud Run API SA does not have that today — we return an explicit miss
instead of inventing a number.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BILLING_ACCOUNT = os.getenv("GCP_BILLING_ACCOUNT", "01549D-4220C6-D775AD")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen")


def _adc_token() -> str:
    import google.auth  # noqa: PLC0415
    import google.auth.transport.requests  # noqa: PLC0415

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-billing.readonly"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def fetch_cloud_spend() -> dict[str, Any]:
    """Return current-month budget snapshot, or an error payload."""
    try:
        token = _adc_token()
    except ImportError:
        return {"ok": False, "error": "google-auth not installed"}
    except Exception as exc:  # noqa: BLE001 — digest must still send
        return {"ok": False, "error": f"adc: {exc}"}

    url = (
        f"https://billingbudgets.googleapis.com/v1/billingAccounts/"
        f"{BILLING_ACCOUNT}/budgets"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "error": f"HTTP {exc.code}",
            "hint": "Grant roles/billing.viewer on the billing account to the API SA",
            "billing_account": BILLING_ACCOUNT,
            "project": PROJECT_ID,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    budgets = body.get("budgets") or []
    if not budgets:
        return {
            "ok": True,
            "amount": None,
            "note": "no budgets configured",
            "billing_account": BILLING_ACCOUNT,
            "project": PROJECT_ID,
        }
    first = budgets[0]
    amount = ((first.get("amount") or {}).get("specifiedAmount") or {})
    units = amount.get("units") or "0"
    try:
        dollars = float(units)
    except (TypeError, ValueError):
        dollars = None
    return {
        "ok": True,
        "amount": dollars,
        "currency": amount.get("currencyCode") or "USD",
        "display_name": first.get("displayName") or "budget",
        "billing_account": BILLING_ACCOUNT,
        "project": PROJECT_ID,
    }
