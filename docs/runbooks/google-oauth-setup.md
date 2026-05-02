# Runbook — Google OAuth setup (reproducible)

**Severity:** N/A (greenfield setup)
**Audience:** SRE / platform team
**Last reviewed:** 2026-05-02
**Last executed:** 2026-05-02 (M2.5 bootstrap)

This runbook captures the manual GCP setup that's required for Google
sign-in to work. Re-execute when adding a new environment, rotating the
OAuth credentials, or recovering from a compromised Client Secret.

## Pre-conditions

- Google account with access to the StratTraderPro Google Cloud project
  (existing project ID: `strattraderpro`).
- Backend deploys whose redirect URIs you want to register. Default for
  StratTraderPro:
  - `http://localhost:8777/api/v1/auth/oauth/google/callback/` (dev)
  - `https://backend-staging-4b6d.up.railway.app/api/v1/auth/oauth/google/callback/`
  - `https://backend-production-f3e8.up.railway.app/api/v1/auth/oauth/google/callback/`

## Outcome

- An OAuth 2.0 Web client in `strattraderpro` GCP project named
  "StratTraderPro Web" with Client ID + Client Secret.
- Backend env vars `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`
  populated in staging + prod Railway envs.
- App in "Testing" mode with a small list of test users for development,
  OR published to "In Production" mode for unrestricted sign-up.

## Procedure

### Step 1 — OAuth consent screen (one-time per project)

If the project has never had OAuth configured before (Google Auth Platform
section is empty):

1. Open `https://console.cloud.google.com/auth/branding?project=strattraderpro`
2. Click **Get started**.
3. **App Information**: Name = "StratTraderPro", User support email =
   your project owner's email.
4. **Audience**: Select **External** (only choice for personal Google
   accounts; `Internal` requires a Workspace org).
5. **Contact Information**: developer email = same as above.
6. **Finish**: Tick the User Data Policy checkbox, click **Continue**, then
   **Create**.

The app starts in Testing mode (capped at 100 test users, none of whom
can sign in until added in Step 4).

### Step 2 — Create the OAuth Web client

1. Open `https://console.cloud.google.com/auth/clients?project=strattraderpro`
2. Click **+ Create client**.
3. **Application type**: Web application.
4. **Name**: "StratTraderPro Web".
5. **Authorized JavaScript origins**: leave empty (we use server-side flow
   only — no `gapi.auth2` or Google Identity Services on the frontend).
6. **Authorized redirect URIs**: add all three from the pre-conditions
   list. Order doesn't matter; all three must be present so the same
   Client ID can be used by every environment.
7. Click **Create**.

A modal shows the new Client ID. **Important**: the Client Secret is
shown ONCE during creation. If you missed copying it, click "+ Add
secret" on the credential detail page later and copy the new one
immediately. Per Google's policy, the existing secret value can NEVER be
re-revealed.

### Step 3 — Save credentials

Save both values to your password manager (label them
`StratTraderPro · Google OAuth Client ID` and `StratTraderPro · Google
OAuth Client Secret`). Never commit them to git, never paste them into
chat tools, never share them in tickets.

### Step 4 — Add yourself as a test user (Testing-mode apps only)

While the app is in Testing mode, only listed test users can sign in:

1. Open `https://console.cloud.google.com/auth/audience?project=strattraderpro`
2. Scroll to the **Test users** section, click **+ Add users**.
3. Enter the Google email of every developer who needs to sign in for
   testing. Up to 100 users, counted over the lifetime of the app.

### Step 5 — Set the env vars on Railway

For each environment (staging, prod):

1. Open Railway → backend service → Variables tab.
2. Click **+ New Variable**, add:
   - `GOOGLE_OAUTH_CLIENT_ID` = the Client ID from Step 3
   - `GOOGLE_OAUTH_CLIENT_SECRET` = the Client Secret from Step 3
3. Railway auto-redeploys.

Wait for the deploy to go ACTIVE. Verify by hitting
`https://<backend>/api/v1/auth/oauth/google/start/` — it should return
JSON with an `authorize_url` containing your Client ID. If it returns a
503 with `FEATURE_DISABLED`, the env vars didn't get set (or
`GOOGLE_OAUTH_ENABLED` was set to false).

### Step 6 — Smoke test

1. Open the frontend (`https://frontend-{env}-...up.railway.app/login`).
2. Click **Continue with Google**.
3. Complete the Google consent screen.
4. Land on `/dashboard` (no MFA case) or `/login/mfa` (MFA case).
5. Check `/admin/users/authevent/?event_type=oauth_login_ok` for the
   audit row.

### Step 7 — Publish to production (when ready for real users)

While in Testing mode, only listed test users can sign in. To open
sign-up to anyone with a Google account:

1. Open `https://console.cloud.google.com/auth/audience?project=strattraderpro`
2. Click **Publish app** under Publishing status.
3. Confirm.

For our scopes (`email`, `profile`, `openid`), no Google verification is
required — publishing is instant. If you ever add a restricted scope
(e.g. Drive, Gmail, Calendar), Google will require app verification
which can take weeks.

## Failure modes

- **`/start/` returns 503 `FEATURE_DISABLED`** — `GOOGLE_OAUTH_CLIENT_ID`
  is empty in the backend env. Check Railway env vars for the relevant
  service.
- **Google shows "Access blocked: StratTraderPro has not completed
  Google verification"** — the user trying to sign in isn't on the test
  user list (and the app is still in Testing mode). Add them, OR publish
  the app per Step 7.
- **Google shows "Error 400: redirect_uri_mismatch"** — the redirect URI
  the backend constructed doesn't match any of the three registered URIs.
  Check `Authorized redirect URIs` in the GCP credential detail page,
  ensure the exact `https://backend-{env}-{hash}.up.railway.app/api/v1/auth/oauth/google/callback/`
  is present (note trailing slash matters).
- **Backend returns `EXCHANGE_INVALID` on every callback** — the
  exchange code is being consumed by an interceptor before reaching the
  exchange view (e.g. service worker, browser-extension). Check the
  network panel.

## Rotating the Client Secret

If the Client Secret is suspected leaked:

1. Open the credential detail page.
2. Click **+ Add secret**, copy the new one immediately.
3. Update `GOOGLE_OAUTH_CLIENT_SECRET` in Railway (staging + prod).
4. After deploy goes green and a smoke test passes, return to GCP and
   delete the old secret row.

The Client ID does not need rotating (it's quasi-public).

## Rollback

To temporarily disable Google sign-in across the platform:

```
GOOGLE_OAUTH_ENABLED=false
```

in Railway env. Backend redeploy → all OAuth endpoints return 503
`FEATURE_DISABLED`. The frontend's "Continue with Google" button still
shows but clicking it surfaces the disabled message. Users can sign in
with email + password as normal.
