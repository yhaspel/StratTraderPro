# Runbook — bootstrapping a fresh production environment on Railway

**Severity:** N/A (greenfield setup)
**Audience:** you, running your own instance
**Last reviewed:** 2026-05-02
**Last executed:** 2026-05-02 (initial prod bootstrap, alongside M02)

This runbook captures the steps that turned an empty Railway environment
into a fully-isolated production mirror of staging. Re-execute when
spinning up a new env (DR drill, new region, separate tenant), or when
recovering from a destructive incident.

## Pre-conditions

- Staging environment is healthy and considered the source of truth.
- You have admin access to the Railway project, Grafana Cloud workspace,
  and Sentry project.
- You can run Python locally (for secret generation).
- You have a password manager open to store the new secrets.

## Outcome

- Production environment with 7 services (backend, frontend,
  celery-worker, celery-beat, Postgres, Redis, grafana-agent),
  all online with fresh empty Postgres + Redis volumes.
- Three secrets unique to prod and never reused from staging:
  `SECRET_KEY`, `JWT_SIGNING_KEY` (defaults from SECRET_KEY), `FERNET_KEK`.
- Backend reachable at `https://backend-production-<hash>.example.com/`.
- Frontend reachable at `https://frontend-production-<hash>.example.com/`,
  proxying `/api/v1/*` to the prod backend (same-origin, no CORS surface).
- Metrics flowing to Grafana Cloud tagged `env=production`.
- Sentry events tagged `environment=production`.

## Procedure

### Step 0 — archive any pre-existing empty env

If a `production` environment already exists from a prior false start
and is NOT what you want, **rename** it (don't delete) so we keep an
audit trail:

1. Project Settings → Environments → `⋮` next to the old `production`
   → Rename → `production-archive-YYYY-MM`.

### Step 1 — duplicate staging into production

1. Project Settings → Environments → **+ New Environment**.
2. Name: `production`.
3. Choice: **Duplicate Environment** → source: `staging`.
4. Click **Create Environment**.

What this does: creates copies of all 7 services in the new env. Each
service gets fresh resources (new Postgres / Redis volumes, new public
URLs). Service references like `${{Postgres.DATABASE_URL}}` rebind
automatically to the prod copies, so connection strings auto-resolve
without manual editing.

What this does NOT do: data does not transfer (Postgres/Redis start
empty, which is what we want for prod).

Wait for all 7 services to go from "Building" to "Online" — typically
~60-90 seconds.

### Step 2 — generate prod-grade secrets locally

Run these in a terminal you trust. **Do NOT paste the output into chat,
issue trackers, or any shared surface.**

```bash
# Django SECRET_KEY (also used as JWT signing key by default).
python3 -c "import secrets; print(secrets.token_urlsafe(64))"

# Fernet KEK for MFA secret-at-rest. 32 random bytes, url-safe-base64.
python3 -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Store both in your password manager. The KEK in particular: lose it and
you lose the ability to decrypt every MFA secret in prod (see
`docs/runbooks/mfa-kek-rotation.md`).

### Step 3 — override the cloned secrets

In Railway → production env → backend service → Variables tab:

1. Click `⋮` next to **`SECRET_KEY`** → Edit → paste the SECRET_KEY value
   from Step 2 → Tab to commit. The field will mask the value.
2. Click `⋮` next to **`FERNET_KEK`** → Edit → paste the FERNET_KEK value
   from Step 2 → Tab to commit.
3. Click the purple **Deploy** banner that appears at the top of the
   Variables panel. Backend redeploys (~30-60s).

### Step 4 — verify URL-bound vars auto-resolved

Most URL/CORS vars use Railway service refs and auto-resolved correctly,
but verify by clicking the eye (👁) icon on each:

| Variable | Expected resolved value |
|---|---|
| `ALLOWED_HOSTS` | `backend-production-<hash>.example.com,backend.railway.internal,frontend-production-<hash>.example.com` |
| `CSRF_TRUSTED_ORIGINS` | similar with `https://` prefix |
| `FRONTEND_BASE_URL` | `https://frontend-production-<hash>.example.com` |
| `CORS_ALLOWED_ORIGINS` | empty is fine — frontend proxies same-origin |

If any value still references `staging`, replace the literal with
`${{frontend.RAILWAY_PUBLIC_DOMAIN}}` (or similar) so future env clones
auto-rebind.

### Step 5 — verify the backend

```bash
curl https://backend-production-<hash>.example.com/healthz
# expect: {"status":"ok","version":"<git-sha>"}

curl https://backend-production-<hash>.example.com/readyz
# expect: {"status":"ok","checks":{"db":"ok","redis":"ok"}}
```

If `db: error` appears, the backend service didn't pick up
`DATABASE_URL` — re-check that the env var is set as a Railway service
ref (`${{Postgres.DATABASE_URL}}`).

### Step 6 — verify the frontend → backend wiring

Open `https://frontend-production-<hash>.example.com/login` in a
browser and submit any garbage credentials. You should see a clean
"Invalid email or password" message (or, today, the existing
`auth.login.error.UNKNOWN` message — known frontend bug, see backlog).
Either way it proves the request reaches the backend.

For deeper proof, paste this into the browser DevTools console:

```js
fetch('/api/v1/auth/login/', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({email: 'x@x.com', password: 'wrong'}),
}).then(r => r.json()).then(console.log)
// expect: { error: { code: 'INVALID_CREDENTIALS', message: '...' } }
```

### Step 7 — verify the MFA KEK is loadable

Sign in with a real account, navigate to Settings → Security, click
**Set up 2FA**. If a QR code renders, the KEK successfully wrapped a
fresh TOTP secret. If you see a 500, the KEK is malformed (regenerate
and re-set, then redeploy).

### Step 8 — observability

Grafana metrics: zero work. The grafana-agent in the duplicated env
auto-tags metrics with `env=production` because `agent.yaml` reads
`${RAILWAY_ENVIRONMENT_NAME}` (Railway-injected). Open the System Health
dashboard (`/d/stp-system-health`) and switch the **Env** dropdown to
`production` — panels should populate within 5 minutes. (The Auth Health
dashboard this step used to name was retired by ADR-109.)

Sentry environment: with `prod.py` reading
`SENTRY_ENVIRONMENT` (defaulting to `RAILWAY_ENVIRONMENT_NAME`), prod
events tag `environment=production` automatically. To verify: trigger a
test 500 (e.g. visit a non-existent admin URL) and confirm it appears
under the `production` env in the Sentry UI within ~30s.

### Step 9 — record the URLs

Update `project-plan/plan-progress-tracker.md` with the resolved
backend/frontend prod URLs (the `<hash>` portion is set by Railway).
Add the URLs to your team's runbook index.

## Failure modes

- **Backend boots then immediately 500s on every request** — likely a
  malformed `FERNET_KEK` (must be exactly 32-byte url-safe base64).
  Regenerate with the Step 2 command and re-edit the var.
- **Frontend loads but every API call returns 500 / CORS error** — the
  frontend's `BACKEND_URL` is empty or wrong. Check
  `frontend/Variables` for `BACKEND_URL`; should be the prod backend's
  public URL.
- **Postgres has data in it** — the env duplicate must have inadvertently
  reused a volume. Stop, file an incident, do NOT proceed; data
  isolation is non-negotiable for prod.
- **`/readyz` returns `redis: error`** — the prod Redis service didn't
  finish provisioning. Wait 30s and retry. If still failing, check the
  Redis service logs for OOM / boot errors.

## Rollback

To unwind a botched bootstrap:

1. Delete the new `production` environment from Project Settings → Environments → `⋮` → Delete.
2. (Optional) rename the archive back to `production` if you want to restore the prior empty state.

The staging environment is unaffected by anything in this runbook.
