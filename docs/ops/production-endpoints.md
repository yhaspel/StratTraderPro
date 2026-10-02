# Production endpoints

**There is no hosted production instance.** The Railway `production` environment was retired
on 2026-10-02: the project was deleted and every service stopped. StratTraderPro now runs
locally (`make up` — see the README's Quick Start). Railway is still a workable self-hosting
target; nothing in the table below is live.

This file used to hold the canonical public hostnames, because the frontend's Railway domain
changed during the 2026-07-15 OSS pivot and the correct value was only recoverable from two
operator reports ([BUG-012](../../bugs/BUG-012-silent-failure-audit-prompt-reverted.md)). It now
records what was retired, so nobody re-adds a dead URL to docs, alerts or TradingView webhooks.

## Retired — do not use

| URL | Retired | What it was |
|---|---|---|
| `https://strattraderpro.up.railway.app` | 2026-10-02 | Frontend (SPA) |
| `https://backend-production-f3e8.up.railway.app` | 2026-10-02 | Backend API, also the TradingView webhook target |
| `https://ws-production-9464.up.railway.app` | 2026-10-02 | WebSocket service (daphne) |
| `https://frontend-production-c977f.up.railway.app` | 2026-07-15 | Frontend before the OSS pivot renamed the service |

Railway can hand a released `*.up.railway.app` name to another project, so treat these as
someone else's hosts from now on: don't link to them and don't point webhooks at them.

## Related cleanup (2026-10-02)

- **Grafana Cloud:** the StratTraderPro alert rules (all 11), their folders, the three
  dashboards and the Telegram contact point were deleted from the stack. The source copies
  stay in `infra/grafana/` for anyone self-hosting.
- **Daily silent-failure audit:** disabled — see `infra/scheduled-tasks/README.md`.
