# StratTraderPro

Regime-aware algorithmic trading platform — webhook-driven, multi-broker, with sentiment analysis and risk management.

**Stack:** Django 5 + DRF (backend) · Angular 19 + Signals (frontend) · Postgres 16 · Redis 7 · Celery + Redbeat · Railway (hosting)

## Quick Start (local dev)

```bash
# 1. Clone the repo
git clone https://github.com/yuval3000/strattraderpro.git
cd strattraderpro

# 2. Copy environment files
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 3. Start the full stack (postgres + redis + backend + worker + beat + frontend + ngrok)
make up
# Equivalent to: docker compose --profile tunnel up -d
# First run only — force-rebuild images: docker compose --profile tunnel up --build

# 4. Verify
curl http://localhost:8777/healthz          # Backend health → {"status":"ok",...}
curl http://localhost:8777/readyz           # DB + Redis connectivity → {"status":"ok","checks":{"db":"ok","redis":"ok"}}
open http://localhost:4444                   # Frontend landing page
open http://localhost:4040                   # ngrok web UI (public tunnel URL → backend:8777)

# 5. Run tests
make test-be    # Backend (pytest)
make test-fe    # Frontend (karma)

# 6. View logs
make logs

# 7. Stop everything
make down
```

> **Note:** `make up` includes the ngrok tunnel by default so the local backend is reachable on a public HTTPS URL (needed for TradingView webhook testing and AC-00-10). To start without the tunnel, use `docker compose up -d` directly. To bring just ngrok up alongside an existing stack, use `make tunnel`.

## Architecture

```
Angular 19 (Signals, 3-layer)  →  Django REST Framework  →  Postgres + Redis
                                     ↓
                               Celery Workers (tasks, sentiment, regime)
                                     ↓
                               Broker Adapters (IBKR CPAPI, TradeStation)
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

## Staging

- **Backend:** `https://<TBD>.up.railway.app`
- **Frontend:** `https://<TBD>.up.railway.app`
- **Health:** `GET /healthz` · **Readiness:** `GET /readyz` · **Schema:** `GET /api/schema/`

## i18n

- **Frontend:** keys in `frontend/src/assets/i18n/en.json` — never hard-code strings.
- **Backend:** wrap with `_()` from `django.utils.translation`.
- **Extract:** documented in `docs/dev/local-setup.md`.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

Proprietary — all rights reserved.
