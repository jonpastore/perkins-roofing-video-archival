# Spec: WordPress staging Application Password (1251216)

Status: **done** (2026-08-18)

Wendy’s new staging `https://1251216.us6.myftpupload.com` is a prod clone. The vaulted
password was for dead host `1228404` and 401’d. Application Passwords was already on
Jon’s profile; we minted `perkins-platform-staging-2026-08-18` from the Chrome admin
session and vaulted it.

## Vault
- GCP Secret Manager `wordpress-app-password` **version 6** (`:latest`). Cloud Run
  `WP_APP_PWD` remounted on revision `api-00285-74d`.
- 1Password item `WordPress - PerkinsRoofing.net` (Private): **new field**
  `Application password`. The existing `password` field is the wp-admin login — do not
  overwrite it.
- `PlatformConfig.WP_URL` and `infra/deploy.config.env` → `https://1251216.us6.myftpupload.com`.

## Verified
REST `GET /wp-json/wp/v2/users/me?context=edit` 200, slug `jon`, role `administrator`.

## Still open
473 DB articles still carry stale `1228404` `wp_post_id`s. Republish requires NULL then
`publish()`, not `update()`. Not done in this change.
