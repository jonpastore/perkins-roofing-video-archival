# PRD: Verify-then-vault prompted credentials

Status: **implemented-local**

## Requirements
- An operator can type a username/password on a TTY to repair Knowify, WordPress,
  or YouTube (Google account that owns the Perkins channel).
- The pair is stored only after a live check succeeds.
- A typo must not replace the previous Secret Manager version.
- The wp-admin password is not this flow.

## Acceptance
- Knowify: OAuth tokens written and `knowify-login` updated only after a code exchange.
- WordPress: REST 200 on `/users/me` then `wordpress-app-password` new version.
- YouTube: Perkins `channels?mine=true` then `youtube-oauth-refresh-token`.
  API key: `channels.list` for the Perkins id then `youtube-api-key`.
- Verify false → RuntimeError / HTTP 400 and zero SM writes.
