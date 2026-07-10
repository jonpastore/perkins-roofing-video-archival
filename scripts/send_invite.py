#!/usr/bin/env python3
"""Send a branded platform-invitation email via Resend (CLI / one-off resend).

Uses the SAME code path as the /admin/users/invite endpoint:
core.invite_email.build_invite_email + adapters.resend.send. Does NOT create or
modify the Firebase user — this only (re)sends the notification email, so use it
to resend an invite to someone already authorized in the Users panel.

Requires RESEND_API_KEY in the environment. Sign-in URL comes from PUBLIC_APP_URL
(default https://app.perkinsroofing.net).

    RESEND_API_KEY=... python scripts/send_invite.py \
        --to burademirung@gmail.com --role admin --name Vlad \
        --inviter "Jon Pastore" --reply-to jon@perkinsroofing.net \
        --bcc jon@perkinsroofing.net
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import resend  # noqa: E402
from core.invite_email import build_invite_email  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--to", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--inviter", default=None)
    p.add_argument("--reply-to", default="info@perkinsroofing.net")
    p.add_argument("--bcc", action="append", default=[])
    args = p.parse_args()

    sign_in_url = os.environ.get("PUBLIC_APP_URL", "https://app.perkinsroofing.net")
    subject, html = build_invite_email(
        recipient_name=args.name,
        role=args.role,
        sign_in_url=sign_in_url,
        inviter_name=args.inviter,
    )
    msg_id = resend.send(
        from_name="Perkins Roofing",
        reply_to=args.reply_to,
        to=args.to,
        subject=subject,
        html=html,
        bcc=args.bcc or None,
    )
    print(f"sent to {args.to} (bcc={args.bcc or 'none'}) — resend id {msg_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
