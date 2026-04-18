# Staging Deploy Runbook

## Automatic Deploy

Pushes to `main` trigger the `deploy-staging.yml` GitHub Actions workflow, which:

1. Installs Railway CLI.
2. Deploys the `backend` service.
3. Deploys the `frontend` service.
4. Runs a smoke test against `/healthz`.

## Manual Deploy

If the automatic pipeline fails or you need to deploy manually:

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
