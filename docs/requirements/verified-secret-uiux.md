# UI/UX: Verify-then-vault prompted credentials

Status: **implemented-local**

## Surfaces
- CLI TTY: `jobs.knowify_relogin --prompt`, `jobs.wordpress_vault --prompt`,
  `jobs.youtube_relogin --prompt` / `--api-key`. Username hint, password via
  `getpass` (no echo). YouTube `--headed` when Google blocks headless.
- Dashboard Connections / Config: pasting `wordpress-app-password` or
  `youtube-api-key` / `youtube_reply` runs the same live check. 400 copy:
  “credentials did not verify — secret not updated”.
- Data sources “Log in” for YouTube is Google OAuth; the callback vaults the
  refresh token only if the account owns the Perkins channel.
- No password is logged or returned in API bodies.

## Non-surfaces
- Data sources “Log in” is OAuth in the browser, not a password form.
