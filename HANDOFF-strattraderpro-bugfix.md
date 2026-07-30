# One-shot handoff — StratTraderPro bug-fix run (branch `bugfix/ux-guides-timezone-health-ws`)

Paste everything below the line into Claude Code (`claude`) from the repo root
`~/Documents/Claude/Projects/StratTraderPro`. It is self-contained: it applies the
branch, re-runs every gate locally, and then walks the two deploy-side fixes that
could not be done from a sandbox.

---

You are working in the StratTraderPro monorepo at
`~/Documents/Claude/Projects/StratTraderPro`. A bug-fix branch was prepared in a cloud
sandbox and delivered as a git bundle. Your job is to land it locally, verify it, and
complete the two fixes that require Railway access.

Work autonomously. Do not ask me questions unless a step fails in a way that needs a
decision. Report at the end with a short pass/fail table.

## 0. Preconditions

The bundle file is at `./strattraderpro-bugfix-ux-guides.bundle` (repo root). It was cut
against `origin/main` at commit `90169be` — confirm `git rev-parse main` is `90169be`
before applying. The working tree must be clean.

There is a stray `_to_delete/` directory at the repo root containing a stale
`.git/index.lock` that the sandbox could not remove (the device mount blocks `rm`).
Delete it: `rm -rf _to_delete`.

## 1. Apply the branch

```bash
cd ~/Documents/Claude/Projects/StratTraderPro
rm -rf _to_delete
git status --porcelain            # must be empty
git rev-parse main                # must be 90169be...
git bundle verify strattraderpro-bugfix-ux-guides.bundle
git fetch strattraderpro-bugfix-ux-guides.bundle \
    'refs/heads/bugfix/ux-guides-timezone-health-ws:refs/heads/bugfix/ux-guides-timezone-health-ws'
git checkout bugfix/ux-guides-timezone-health-ws
git log --oneline -1              # expect 0436ad7 fix(ux): guides tab, admin health payload drift, ...
rm -f strattraderpro-bugfix-ux-guides.bundle
```

## 2. Re-run the full local CI-parity gauntlet

All of these passed in the sandbox; re-run them here because the sandbox could not use
the repo's own venvs. Do NOT declare anything ready until every one is green.

```bash
# Guards
python3 scripts/check_envsubst_filter.py
python3 scripts/check_guides_catalog.py

# Backend
cd backend
../.venv/bin/ruff check . || ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python -m pytest --tb=short -q
cd ..

# Frontend
cd frontend
pnpm install --frozen-lockfile
pnpm exec ngc --noEmit -p tsconfig.app.json     # NG5002/NG9 template errors tsc does not catch
pnpm test:ci                                    # expect 169 passing
pnpm build
pnpm exec playwright test e2e/a11y              # expect 8 passing
cd ..
```

If `ruff`/`bandit`/`pytest` are not on PATH, use the repo venv
(`backend/.venv/bin/...` or `.venv/bin/...`) — whichever this machine actually uses.

## 3. Deploy fix A — the WebSocket path (makes the header stop saying "Offline")

The branch adds a `location /ws/` block to `docker/nginx.conf.template` proxying to
`${WS_URL}`, plus `WS_URL` in the envsubst allowlist with a compose default of
`http://ws:8788`. Two things still have to happen on Railway.

**A1. Confirm whether a `ws` service exists in the production environment.**

```bash
railway status
railway service           # list services; look for one running SERVICE_ROLE=ws
```

**A2. If it does not exist, create it.** It runs the same backend image as `backend`, only
with a different role:

- New service from the same repo/Dockerfile as `backend` (`docker/backend.Dockerfile`).
- Env vars: copy the backend service's whole set (`DATABASE_URL`, `REDIS_URL`,
  `SECRET_KEY`, `FERNET_KEK`, `DJANGO_SETTINGS_MODULE=config.settings.prod`, …) and then
  set `SERVICE_ROLE=ws`.
  - `FERNET_KEK` is required by every Django service — without it the process
    crash-loops while `/healthz` stays green on the others.
- Leave the start command blank; the image entrypoint dispatches on `SERVICE_ROLE` and
  will run `daphne -b 0.0.0.0 -p $PORT config.asgi:application`.
- Generate a public domain for it.

**A3. Point the frontend at it.** On the **frontend** service set:

```
WS_URL=https://<the-ws-service-public-domain>
```

Use the PUBLIC domain, not `*.railway.internal` — private DNS is unreliable from nginx
(same reason `BACKEND_URL` uses the public URL). Redeploy the frontend so envsubst re-renders
the template.

**A4. Verify, do not assume.** From a browser signed in to the app, in the devtools console:

```js
// Before the fix this returned 200 text/html (the SPA index) — that was the bug.
await fetch('/ws/dashboard/').then(r => [r.status, r.headers.get('content-type')]);
```

Then reload the dashboard and confirm the header dot reads **Live**. If it still reads
Offline, check in this order: `WS_URL` set on the frontend service → ws service deployed and
not crash-looping (look for a missing `FERNET_KEK`) → daphne bound to `$PORT`.

## 4. Deploy fix B — Market Regime has no data

Not a code bug. `apps/regime/tasks.py::compute_features_daily` returns
`{"skipped": "no_market_data_source_configured"}` unless **both** `FMP_API_KEY` and
`FRED_API_KEY` are set, so no `RegimeObservation` is ever written and the dashboard card is
empty forever. Verified live on 2026-07-29: `/api/v1/regime/current/` → `{"data": null}`,
`/api/v1/regime/history/` → `{"data": []}`, `/api/v1/regime/model/` →
`{"active": null, "degraded": true}`.

The branch makes the product say so (`source_configured` on `/regime/model/`,
`regime_source_configured` on `/admin/health/`, an honest empty state on the card, and a new
`market-regime-setup` guide). To actually get data:

1. Get a free FRED API key (https://fred.stlouisfed.org/docs/api/api_key.html) and an FMP
   key (https://site.financialmodelingprep.com/developer/docs).
2. Set `FMP_API_KEY` and `FRED_API_KEY` on **every** service that runs Django code —
   `backend`, `celery-worker` AND `celery-beat`. Setting them only on `backend` is the
   trap: the task runs on the worker, so the web tier would report "configured" while
   nothing ever gets written.
3. Redeploy those services.
4. Verify at **Admin → Health → Regime data source** (should read *Configured*).
5. Kick one run instead of waiting for 22:30 UTC:

```bash
railway ssh --service backend python manage.py shell -c \
  "from apps.regime.tasks import run_daily_feature_pipeline; print(run_daily_feature_pipeline())"
```

   Expect a dict with `snapshot`, `observation` and `degraded` keys. Then reload the
   dashboard: the card should show a regime label with a **degraded** chip (rule-based only
   until ~120 daily snapshots accumulate and the nightly HMM retrain can fit a model).

## 5. Land it

```bash
git push -u origin bugfix/ux-guides-timezone-health-ws
gh pr create --fill --base main
```

Note for the PR body: fork-PR approval is "all external contributors" since the OSS pivot,
and branch protection on `main` is saved-but-not-enforced on the free tier — so CI is the
only gate that actually runs.

## 6. Report

Give me a table: each of steps 2–4, pass/fail, and the actual observed evidence (test
counts, the `fetch('/ws/dashboard/')` status, the regime pipeline return value). If
something failed, say what and stop rather than working around it.
