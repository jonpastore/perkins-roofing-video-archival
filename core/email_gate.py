"""Outbound email gate — the single safety valve for all Resend sends.

WHY: real client emails went out. Until sending is reviewed and re-enabled, the
platform must default to NOT contacting clients. This module is a pure, fully
unit-testable decision function; the DB write / Resend call lives in
``adapters.resend.send`` which consults ``decide()`` before doing any I/O.

Modes (env ``EMAIL_SEND_MODE``):
  - ``disabled`` — block EVERY recipient (hard lockdown; nothing leaves).
  - ``test``     — block every recipient EXCEPT those on the test allowlist
                   (``EMAIL_TEST_RECIPIENT_ALLOWLIST``). This is the SAFE DEFAULT.
  - ``live``     — send to everyone (normal operation; only after review).

Default is ``test`` with the allowlist defaulting to ``jon@degenito.ai`` so the
only address that can receive mail out of the box is Jon's test inbox.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_MODE = "test"
_DEFAULT_TEST_ALLOWLIST = "jon@degenito.ai"
_VALID_MODES = frozenset({"disabled", "test", "live"})


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    mode: str
    reason: str


def _mode() -> str:
    raw = (os.getenv("EMAIL_SEND_MODE") or _DEFAULT_MODE).strip().lower()
    return raw if raw in _VALID_MODES else _DEFAULT_MODE


def _allowlist() -> frozenset[str]:
    raw = os.getenv("EMAIL_TEST_RECIPIENT_ALLOWLIST", _DEFAULT_TEST_ALLOWLIST)
    return frozenset(
        e.strip().lower() for e in raw.split(",") if e.strip()
    )


def _allowlist_matches(recipient: str, allowlist: frozenset[str]) -> bool:
    """Exact-recipient allowlist, with explicit @domain opt-in only.

    Bare domains are intentionally NOT accepted; "only email me" means a typo like
    ``degenito.ai`` must not broaden the gate to every mailbox at that domain.
    Operators who really want a domain can use ``@example.com``.
    """
    if recipient in allowlist:
        return True
    domain = recipient.split("@")[-1] if "@" in recipient else ""
    return bool(domain and f"@{domain}" in allowlist)


def current_mode() -> str:
    """Public accessor for the effective mode (for status/introspection)."""
    return _mode()


def decide(to_email: str) -> GateDecision:
    """Decide whether an email to ``to_email`` may be sent.

    Pure function of the environment + argument — no I/O. Safe default: when the
    mode env is unset the mode is ``test`` and only the allowlist may receive.
    """
    mode = _mode()
    recipient = (to_email or "").strip().lower()

    if not recipient:
        return GateDecision(allowed=False, mode=mode, reason="empty_recipient")

    if mode == "live":
        return GateDecision(allowed=True, mode=mode, reason="live_mode")

    if mode == "disabled":
        return GateDecision(allowed=False, mode=mode, reason="sending_disabled")

    # test mode
    allow = _allowlist()
    if _allowlist_matches(recipient, allow):
        return GateDecision(allowed=True, mode=mode, reason="test_allowlisted")
    return GateDecision(allowed=False, mode=mode, reason="not_test_allowlisted")
