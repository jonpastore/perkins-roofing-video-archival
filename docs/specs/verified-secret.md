# Spec: Verify-then-vault prompted credentials

Status: **implemented-local** (2026-08-18)

## Why
Broken logins get a human username/password. Writing that pair to Secret Manager
before proving it works overwrites `:latest` with a typo and takes down the
previous still-useful version.

## What
One helper (`core/verified_secret.py`): prompt → verify callback → write.
- Knowify: Playwright OAuth success, then `knowify-login`.
- WordPress: `GET /wp-json/wp/v2/users/me`, then `wordpress-app-password`.
  Dashboard / Config paste of that secret uses the same verify.
- YouTube: Playwright Google OAuth + `channels?mine=true` must be Perkins
  (`UChJZpBYXOuR0j1EHJugv5hg`), then `youtube-oauth-refresh-token` + `youtube-login`.
  API key: `channels.list` for that id, then `youtube-api-key`.
- Failed verify does not write.
- A successful persist flips `integration_status` to healthy so Data sources
  drops "Needs login" without waiting for the next probe. YouTube reads
  `youtube_reply` and GSM `:latest` so a remount is not required.

## Non-goals
- Vaulting the WordPress wp-admin login password.
- Prompting for API keys (CompanyCam Application Key is rotate-only).
- Completing OAuth inside an email.
