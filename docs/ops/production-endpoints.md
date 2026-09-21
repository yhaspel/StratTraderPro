# Production endpoints (canonical)

The public hostnames for production. This file exists because the frontend's public
Railway domain changed during the 2026-07-15 OSS pivot and the correct value was only
recoverable by cross-referencing two ADR-109 operator-session reports — the same
undocumented-drift trap the daily silent-failure audit exists to catch. It cost that
audit a false FAIL for weeks (see [BUG-012](../../bugs/BUG-012-silent-failure-audit-prompt-reverted.md)).

**If you change a public domain, update this file in the same PR.**

## Current

| Service | URL | Notes |
|---|---|---|
| Frontend (SPA) | `https://strattraderpro.up.railway.app` | Runtime config at `/config.js`; `release` is the deployed commit SHA |
| Backend (API) | `https://backend-production-f3e8.up.railway.app` | Also the `backendUrl` served in `/config.js` |
| Grafana Cloud | `https://yuval3000.grafana.net` | Alerting + dashboards; `grafanacloud-prom` / `grafanacloud-usage` datasources |
| Sentry | `o4511716412489728.ingest.us.sentry.io` | project `4511716419305472`, environment `production` |

Verified live 2026-09-21 by reading `https://strattraderpro.up.railway.app/config.js`.

## Retired — do not use

| URL | Retired | Current behaviour |
|---|---|---|
| `https://frontend-production-c977f.up.railway.app` | 2026-07-15 (OSS pivot renamed the frontend service) | Railway **edge-level** 404: `{"status":"error","code":404,"message":"Application not found"}` — nothing is bound to the hostname |

That edge 404 is *not* an application 404. It means the platform has no service for
that host, which looks far more alarming than the nginx/envsubst failure mode
([BUG-003](../../bugs/BUG-003-healthz-reports-stale-git-sha.md) /
[BUG-004](../../bugs/BUG-004-nginx-envsubst-filter-too-narrow.md)) that a `/config.js`
check is designed to catch. Distinguish the two before escalating.

## Re-deriving the frontend URL

If this file is ever stale, the authoritative answer is the Railway service's public
domain. A quick sanity check without the Railway console:

```sh
curl -sS https://strattraderpro.up.railway.app/config.js
# expect: window.STP_CONFIG = { ... release: '<40-char sha>' };
# expect: no literal ${ } placeholders
```

`release` should match a commit on `main` that has been deployed.
