# GSuite directory dropdown — one-time setup

The invite form's Workspace-user dropdown (`GET /admin/users/directory`) reads the
`perkinsroofing.net` directory via the **Admin SDK Directory API**. Google requires a
service account with **domain-wide delegation (DWD)** authorized by a Workspace super-admin.
Until this is done the dropdown is empty and invite-by-email still works (no errors).

Read-only scope: `https://www.googleapis.com/auth/admin.directory.user.readonly`.

## 1. Create a dedicated read-only service account (GCP console)

Project: `video-archival-and-content-gen`.

- IAM & Admin → Service Accounts → **Create** → name `workspace-directory-reader`.
- Grant it **no project roles** — the only power it needs comes from the Workspace
  delegation below, so keep it least-privilege.
- Open the new SA → **note its "Unique ID"** (a ~21-digit number, aka OAuth2 Client ID).
  You need this in step 3.

> You *can* reuse the existing `api-run-sa@…` instead, but a dedicated SA keeps the
> directory-read power isolated from the rest of the API's permissions.

## 2. Enable the Admin SDK API

GCP console → APIs & Services → Library → search **"Admin SDK API"** → **Enable**
(in project `video-archival-and-content-gen`).

## 3. Authorize domain-wide delegation (Workspace Admin console — super-admin only)

At <https://admin.google.com> signed in as a **Perkins Workspace super-admin**:

- **Security → Access and data control → API controls → Domain-wide delegation**
  → **Manage domain-wide delegation** → **Add new**.
- **Client ID:** the SA Unique ID from step 1.
- **OAuth scopes:** `https://www.googleapis.com/auth/admin.directory.user.readonly`
- **Authorize.**

## 4. Give the SA key to the API (Secret Manager → Cloud Run)

The Cloud Run runtime credential (metadata-based) can't impersonate a subject, so the
directory call uses a **service-account key** mounted from Secret Manager.

```bash
PROJECT=video-archival-and-content-gen
SA=workspace-directory-reader@$PROJECT.iam.gserviceaccount.com

# Create a key (JSON) and store it as a secret — never commit the file.
gcloud iam service-accounts keys create /tmp/wsdir.json --iam-account="$SA" --project="$PROJECT"
gcloud secrets create workspace-directory-sa-key --data-file=/tmp/wsdir.json --project="$PROJECT"
rm -f /tmp/wsdir.json

# Let the API runtime SA read the secret.
gcloud secrets add-iam-policy-binding workspace-directory-sa-key \
  --member="serviceAccount:api-run-sa@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project="$PROJECT"
```

## 5. Set the env on the Cloud Run API service

Mount the key file and point the app at it. In `scripts/deploy.sh` (where the API service
env is assembled) add to the API deploy:

```
--set-secrets=/secrets/workspace-directory-sa-key=workspace-directory-sa-key:latest
--set-env-vars=WORKSPACE_SA_KEY=/secrets/workspace-directory-sa-key,WORKSPACE_ADMIN_SUBJECT=<an-admin@perkinsroofing.net>,WORKSPACE_DOMAIN=perkinsroofing.net
```

- `WORKSPACE_ADMIN_SUBJECT` — a real Workspace admin mailbox with directory read (the SA
  impersonates this user). `WORKSPACE_DOMAIN` defaults to `perkinsroofing.net` if omitted.
- To keep everything IaC (R3), add the `workspace-directory-sa-key` secret container to the
  `secret_ids` set in `infra/main.tf` and the two env/secret lines above to the API deploy.

## 6. Verify

```bash
# As an admin-role user (needs manage_users):
curl -s -H "Authorization: Bearer <firebase-id-token>" \
  https://<api-uri>/admin/users/directory | jq '.configured, (.users | length)'
```

`configured: true` with a user count → the dropdown populates in **User Management → Invite**.
If `configured: false`, the `reason` field says what's missing (usually the DWD scope
authorization in step 3 or a bad `WORKSPACE_ADMIN_SUBJECT`).

## Keyless alternative (optional, later)

To avoid a downloaded key, the runtime SA can mint a delegated token via the IAM Credentials
`signJwt` API (`sub` = admin, directory scope) and exchange it at the OAuth token endpoint —
but that needs a small code change in `directory_users()`. The key-file path above matches the
current implementation. If you'd rather go keyless, say so and I'll add the signJwt flow.
