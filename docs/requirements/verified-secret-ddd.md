# DDD: Verify-then-vault prompted credentials

Status: **implemented-local**

## Domain
A **verified secret** is a credential that has already proven it works against the
provider. The vault (`:latest`) may only move to a verified secret.

## Context
- Knowify website login is input to Playwright; MCP OAuth tokens are the session.
- WordPress Application Password is input to REST Basic auth; `WP_USER` stays env.
- YouTube reply OAuth is a refresh token that must authorize the Perkins channel.
  The Google login pair is only input to Playwright. The Data API key is a
  separate read-only secret.
- CompanyCam is an application key, not a login — outside this context.
