"""$2,500 profit floor is advisory: warn, email, digest. Do not rewrite the quote."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Tim, Marco, Jon — the people who should see a quote that landed under the minimum.
PROFIT_FLOOR_NOTIFY = (
    "tim@perkinsroofing.net",
    "marco@perkinsroofing.net",
    "jon@perkinsroofing.net",
    "jon@degenito.ai",  # test-mode allowlist default; Tim/Marco wait for EMAIL_SEND_MODE=live
)

WARNING_PREFIX = "profit_below_minimum"


def has_profit_below_minimum(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    for w in result.get("warnings") or []:
        if str(w).startswith(WARNING_PREFIX):
            return True
    for w in result.get("margin_warnings") or []:
        if str(w).startswith(WARNING_PREFIX):
            return True
    return False


def notify_profit_below_minimum(
    *,
    result: dict[str, Any],
    actor: str,
    tenant_id: int | None = None,
) -> list[str]:
    """Email each recipient. Failures must not break the quote. Returns message ids."""
    profit = float(result.get("profit_dollars") or 0)
    floor = float((result.get("floors") or {}).get("min_profit_dollars") or 2500)
    if profit + 1e-6 >= floor and not has_profit_below_minimum(result):
        return []
    if profit + 1e-6 >= floor:
        return []
    total = float(result.get("project_total") or 0)
    est_id = result.get("estimate_id") or result.get("estimate_ids") or "?"
    roof = result.get("roof_type") or "?"
    sq = result.get("total_squares") or result.get("num_squares") or "?"
    subject = f"Profit under $2,500 — estimate {est_id}"
    html = (
        f"<p>A quote landed under the $2,500 profit minimum. It was <b>not blocked</b>.</p>"
        f"<ul>"
        f"<li>Estimate: {est_id}</li>"
        f"<li>By: {actor}</li>"
        f"<li>Roof: {roof} · {sq} sq</li>"
        f"<li>Profit: ${profit:,.2f}</li>"
        f"<li>Total: ${total:,.2f}</li>"
        f"</ul>"
        f"<p>This also appears in the weekly digest.</p>"
    )
    ids: list[str] = []
    try:
        from core.email_gate import decide  # noqa: PLC0415
        import adapters.resend as resend  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        log.warning("profit-floor notify: resend import failed: %s", exc)
        return []
    for to in PROFIT_FLOOR_NOTIFY:
        if not decide(to).allowed:
            continue
        try:
            ids.append(resend.send(
                reply_to=to,
                to=to,
                subject=subject,
                html=html,
                tenant_id=tenant_id,
                send_type="profit_below_minimum",
                metadata={"estimate_id": est_id, "profit": profit},
            ))
        except Exception as exc:  # noqa: BLE001
            log.warning("profit-floor notify to %s failed: %s", to, exc)
    return ids
