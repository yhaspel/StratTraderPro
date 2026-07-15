# StratTraderPro

Self-hosted, webhook-driven algorithmic trading software. You run it. You own the keys.

Regime- and sentiment-aware order sizing with risk management and kill switches, driven by
TradingView-style webhooks and executed against **your own** broker account.

**Stack:** Django 5 + DRF (backend) · Angular 19 + Signals (frontend) · Postgres 16 · Redis 7 · Celery + Redbeat

## Quick Start (local dev)

```bash
# 1. Clone the repo
git clone https://github.com/yhaspel/StratTraderPro.git
cd StratTraderPro

# 2. Generate secrets + write backend/.env (idempotent — skips if .env already exists)
make setup

# 3. Start the full stack (postgres + redis + backend + worker + beat + frontend)
docker compose up -d --build
# After the first build you can just use: make up

# 4. Verify
curl http://localhost:8777/healthz          # Backend health → {"status":"ok",...}
curl http://localhost:8777/readyz           # DB + Redis connectivity → {"status":"ok","checks":{"db":"ok","redis":"ok"}}
open http://localhost:4444                   # Frontend landing page

# 5. Run tests
make test-be    # Backend (pytest)
make test-fe    # Frontend (karma)

# 6. View logs
make logs

# 7. Stop everything
make down
```

> **Public webhook tunnel (optional):** TradingView webhook testing needs the local backend
> reachable on a public HTTPS URL. `make tunnel` brings up an [ngrok](https://ngrok.com) container
> alongside the stack — set `NGROK_AUTHTOKEN` in a repo-root `.env` first (see `.env.example`).
> The default `make up` / `docker compose up -d` does **not** start ngrok.

## First run

The app runs entirely on your machine; there is no hosted service and no shared account.

1. **Create your account** at `http://localhost:4444` → **Create account**.
2. **Find the verification link in the logs.** Local dev uses the console email backend, so the
   signup verification link is **printed to the backend logs**, not emailed:
   ```bash
   docker compose logs backend | grep -i verify
   ```
   Open that link to verify your address.
3. **Enrol two-factor auth.** Every data endpoint returns `403` until MFA is enrolled — this is
   intentional. Until then the dashboard panels honestly say *"Enable two-factor authentication to
   use this"* rather than showing empty data.
4. **Connect your Alpaca account** (paper to start), **add a strategy** with its webhook, and watch
   your first paper fill land on the dashboard.
5. **Help** lives at `/help`; inline **?** links next to jargon deep-link to the matching article.

> **Live trading ships disabled.** Enabling it (`ENABLE_LIVE_TRADING` plus an admin flag) is your
> choice, on your instance, with your money, at your own risk. See `## Disclaimer`.

## Architecture

```
Angular 19 (Signals, 3-layer)  →  Django REST Framework  →  Postgres + Redis
                                     ↓
                               Celery Workers (tasks, sentiment, regime)
                                     ↓
                               Broker Adapters (Alpaca · TradeStation behind a flag)
```

See `docs/adr/` for architecture decision records.

## Project Structure

```
├── backend/         # Django 5 + DRF API
│   ├── apps/        # Domain apps (users, strategies, webhooks, etc.)
│   ├── config/      # Settings, URLs, WSGI/ASGI, Celery
│   └── requirements/
├── frontend/        # Angular 19 standalone SPA
│   └── src/app/
│       ├── core/          # Services, store, guards, interceptors
│       ├── abstraction/   # Facades (bridge core ↔ presentation)
│       └── features/      # Routed feature components
├── docker/          # Dockerfiles + nginx config
├── docs/            # ADRs, runbooks, dev guides
├── project-plan/    # Milestone specs + progress tracker
└── docker-compose.yml
```

## Self-hosting

You bring your own everything. StratTraderPro holds no keys but the ones you give your own instance.

- **Broker:** bring your own [Alpaca](https://alpaca.markets) API keys (paper or live). TradeStation
  support exists behind a flag.
- **Secrets:** `make setup` generates a `SECRET_KEY` and a `FERNET_KEK` (used to encrypt stored
  broker credentials at rest) into `backend/.env`. Both are **mandatory** for a production
  (`config.settings.prod`) deployment. Regenerate with `scripts/gen-secrets.sh`.
- **Optional integrations — all off by default:** Sentry (error tracking), Grafana / Grafana Agent
  (metrics), Resend (transactional email), Google OAuth (social login). The app runs fully without
  any of them; local dev uses a console email backend and no-op observability.
- **GDPR/terms features** ship inert. They are useful only if *you* choose to run a multi-user
  instance, and are disabled by default.

## Disclaimer

**This is not financial advice.** StratTraderPro is software, provided under the Apache-2.0 licence
**with no warranty** (see `LICENSE`).

- **Trading loses money.** Automated trading can lose money rapidly and without supervision.
- **You are the operator.** You deploy it, you hold the keys, you flip the switches. Everything the
  software does on your instance is **your** responsibility.
- **Live trading is your decision.** It ships disabled. If you enable it, you trade your own money at
  your own risk.
- **Past performance does not predict future results.** Backtests and simulated results are
  hypothetical.

## i18n

- **Frontend:** keys in `frontend/src/assets/i18n/en.json` — never hard-code strings.
- **Backend:** wrap with `_()` from `django.utils.translation`.
- **Extract:** documented in `docs/dev/local-setup.md`.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](./LICENSE) for the full text and [NOTICE](./NOTICE) for third-party
attributions — including [vectorbt](https://github.com/polakowo/vectorbt), a hard dependency
distributed under Apache-2.0 **with the Commons Clause** (a non-OSI condition that forbids selling
the software or paid hosting/support whose value derives substantially from it).
