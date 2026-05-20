# Staging Deploy Runbook

## Live URLs (staging)

| Service | URL |
|---|---|
| Frontend (Angular SPA, nginx) | https://frontend-staging-9011.up.railway.app |
| Backend (Django, gunicorn + uvicorn) | https://backend-staging-4b6d.up.railway.app |
| Backend healthz | https://backend-staging-4b6d.up.railway.app/healthz |
| Backend `/api/schema/` (proxied via frontend) | https://frontend-staging-9011.up.railway.app/api/schema/ |
| Postgres (managed) | internal only — `${{Postgres.DATABASE_URL}}` |
| Grafana Agent | internal only — pushes to `prometheus-prod-58-prod-eu-central-0.grafana.net` |
| Grafana Cloud Explore | https://yuval3000.grafana.net/explore (datasource `grafanacloud-yuval3000-prom`) |
| Railway project | https://railway.com/project/17060567-b194-4926-a7c0-7f339e306bdf (env: `staging`) |

## Architecture (4 services, 1 environment)

`backend` ← Postgres (DATABASE_URL) ← `grafana-agent` (scrapes `backend.railway.internal:8000/metrics`) ← `frontend` (nginx, proxies `/api/*` to backend public domain via `${BACKEND_URL}`).

All services are on `main` branch, auto-deploy on push.

## Automatic Deploy

Pushes to `main` trigger the `deploy-staging.yml` GitHub Actions workflow, which:

1. Installs Railway CLI.
2. Deploys the `backend` service.
3. Deploys the `frontend` service.
4. Runs a smoke test against `/healthz`.

> **Note (2026-05-01):** Railway is currently auto-deploying directly from GitHub on push (configured per service in Railway → Source). The GitHub Actions workflow above is redundant unless you need to inject CI gates. The `RAILWAY_TOKEN` secret has not been issued — issue one before relying on the workflow.

## Manual Deploy

**Prefer pushing to `main`** — Railway auto-deploys from GitHub, and that path injects `RAILWAY_GIT_COMMIT_SHA` so `/healthz` reports the real commit. `railway up` CLI deploys do NOT inject `RAILWAY_GIT_COMMIT_SHA`, so `/healthz` ends up reporting `"version": "unknown"` until the next git-based deploy.

If the automatic pipeline fails or you need to deploy from local files (e.g., for an emergency patch you don't want to commit yet):

```bash
# Install Railway CLI
npm install -g @railway/cli

# Authenticate
railway login

# Link to the staging project
railway link

# Deploy backend
railway up --service backend --environment staging

# Deploy frontend
railway up --service frontend --environment staging

# Verify
curl https://<staging-backend-url>/healthz
curl https://<staging-frontend-url>/
```

After the situation stabilises, push the same change via git and let Railway redeploy from GitHub so `/healthz` reports a real SHA again. To force a redeploy of the latest `main` without a code change, push an empty commit:

```bash
git commit --allow-empty -m "chore: trigger staging redeploy"
git push origin main
```

## Rollback

Railway supports one-click rollback in the dashboard:

1. Go to https://railway.app → StratTraderPro Staging.
2. Click the service that needs rollback.
3. Go to Deployments → click the three dots on the previous healthy deploy → "Rollback".

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| 502 on `/healthz` | Container crashed on boot | Check Railway logs; likely a missing env var |
| 400 on any endpoint | `ALLOWED_HOSTS` missing the Railway domain | Add to env var |
| CORS error in browser | `CORS_ALLOWED_ORIGINS` missing frontend URL | Add to env var |
| Migrations failed | DB connection issue | Check `DATABASE_URL` env var |
| 500 on every request, log says `AttributeError: 'coroutine' object has no attribute 'headers'` in `allauth.account.middleware._should_check_dangling_login` | `sentry-sdk` 1.x's `SentryASGIMixin` wraps the ASGI app; allauth's *sync* `AccountMiddleware` then reads `.headers` on the unawaited coroutine. The pre-existing `/metrics` `before_send` filter only suppresses the Sentry *event*, not the 500. | Backend currently runs WSGI (`config.wsgi:application` + `gthread` workers) per the 2026-05-20 hotfix specifically to sidestep this. Don't switch back to ASGI/UvicornWorker until `sentry-sdk` is upgraded to `>=2.0` (async-aware DjangoIntegration). |
| `/healthz` returns `{"version": "unknown"}` | Deploy was triggered via `railway up` CLI, which does NOT inject `RAILWAY_GIT_COMMIT_SHA`. `base.py` falls back to `"unknown"` when neither `GIT_SHA` nor `RAILWAY_GIT_COMMIT_SHA` is set. | Redeploy via a `git push origin main` (or via the Railway dashboard's GitHub deploy trigger). See "Manual Deploy" section for the tradeoff. |
| `up{service="backend"} == 0` in Grafana | Agent's scrape gets 400 from Django because `backend.railway.internal` not in `ALLOWED_HOSTS` | Add `backend.railway.internal` to backend service's `ALLOWED_HOSTS` env var (already present in current config — see `backend` service Variables) |
| frontend `/api/healthz` returns 404 | Django's healthz is at `/healthz`, not `/api/healthz`; nginx proxy passes the path through unchanged | Use `/healthz` directly on the backend domain, or `/api/schema/` to test the proxy |
| nginx 502 to `/api/*` | `BACKEND_URL` env var missing or pointing at `*.railway.internal` (private DNS doesn't resolve from nginx) | Set `BACKEND_URL=https://${{backend.RAILWAY_PUBLIC_DOMAIN}}` on the frontend service |
| Redirect loop on staging URL | `SECURE_SSL_REDIRECT=True` in `prod.py` (Railway terminates TLS at the edge — Django sees HTTP and redirects again) | Keep `SECURE_SSL_REDIRECT=False` (controlled by env var of same name; defaults to False) |
