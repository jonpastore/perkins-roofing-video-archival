# TRD: Verify-then-vault prompted credentials

Status: **implemented-local**

## Interfaces
- `core.verified_secret.prompt_username_password` / `can_prompt` / `prompt_and_update`
- `update_after_verify(secret_id, blob, verify=, save=)` — JSON login
- `update_text_after_verify(secret_id, text, verify=, save=)` — raw secret
- Knowify: `core.knowify.playwright_relogin.relogin_or_prompt`
  CLI `python -m jobs.knowify_relogin [--prompt] [--headed]`
- WordPress: `core.wordpress_creds.verify_app_password` / `vault_after_verify`
  CLI `python -m jobs.wordpress_vault --prompt`
- YouTube: `core.youtube_creds` + `core.youtube_playwright.relogin_or_prompt`
  CLI `python -m jobs.youtube_relogin [--prompt|--api-key] [--headed]`
- `POST /connections/wordpress/secret` and `PUT /config/secrets` for
  `wordpress-app-password` call `_require_wordpress_verified` before SM write.
- `POST /connections/youtube_api_key/secret` and `PUT /config/secrets` for
  `youtube-api-key` verify the Perkins channel id first.
- `POST /connections/youtube_reply/secret` and `/oauth/youtube/callback` write
  `youtube-oauth-refresh-token` only after `channels?mine=true` is Perkins.
- `core.connection_status.mark_healthy` runs after a verified persist so the
  Data sources badge clears immediately (`knowify`, `youtube_reply`).

## Data model
- GSM `knowify-login` JSON `{"username","password"}` (`email` alias on read).
- GSM `wordpress-app-password` plain text (spaces stripped).
- Failed verify leaves `:latest` unchanged.

## Test requirements (TDD)
- `tests/core/test_verified_secret.py` — fail does not save; success saves; prompt; GSM mock.
- `tests/core/test_wordpress_creds.py` — empty/401/network false; 200 vaults stripped password.
- `tests/core/test_knowify_playwright_relogin.py` — persist after OAuth; `--prompt` fallback.
- `tests/api/test_connections.py` — WP 400 on verify fail, no `add_secret_version`.
