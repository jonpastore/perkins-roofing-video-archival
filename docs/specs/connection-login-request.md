# Spec: Connection login-request emails

Status: **implemented-local** (API + DataSources uncommitted; CompanyCam excluded)

## Why
Knowify / YouTube / WordPress logins cannot be completed by the SA. Operators need a
one-click email from the dashboard.

## What
`POST /connections/{integration}/request-login` emails jon@perkinsroofing.net and
jon@degenito.ai via Resend, gated by `email_gate`. CompanyCam returns 400 — it uses an
Application Key.

## Non-goals
- Completing OAuth in the email.
- CompanyCam login (removed).
