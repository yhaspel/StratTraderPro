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

# 3. Start the full stack
make up

# 4. Verify
curl http://localhost:8000/healthz          # Backend health
open http://localhost:4200                   # Frontend landing page

# 5. Run tests
make test-be    # Backend (pytest)
make test-fe    # Frontend (karma)

# 6. View logs
make logs

# 7. Stop everything
make down
```

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
