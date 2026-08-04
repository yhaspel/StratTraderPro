# Local Development Setup

## Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose)
- Node.js 20+ with pnpm (`corepack enable`)
- Python 3.12+ (only needed for running without Docker)
- Git

## Option A: Docker (recommended)

```bash
git clone https://github.com/yhaspel/StratTraderPro.git
cd strattraderpro
cp backend/.env.example backend/.env
make up
```

This starts: Postgres 16, Redis 7, Django backend (port 8777), Celery worker, Celery beat, Angular frontend (port 4444).

Verify: `curl http://localhost:8777/healthz`

### Useful commands

```bash
make logs           # Tail all service logs
make shell-be       # Shell into the backend container
make shell-fe       # Shell into the frontend container
make test-be        # Run backend tests
make test-fe        # Run frontend tests
make migrate        # Run Django migrations
make down           # Stop all services
```

### ngrok tunnel (optional)

To expose your local backend for TradingView webhook testing:

```bash
# Set your ngrok auth token in backend/.env:
# NGROK_AUTHTOKEN=your_token_here

make tunnel
# Visit http://localhost:4040 to see the tunnel URL
```

## Option B: Without Docker

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env  # Edit DATABASE_URL and REDIS_URL for local Postgres/Redis
DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py runserver 8777
```

### Frontend

```bash
cd frontend
corepack enable
pnpm install
pnpm start   # http://localhost:4444
```

## i18n

- **Frontend:** Add keys to `src/assets/i18n/en.json`. Use `{{ 'key.path' | translate }}` in templates.
- **Backend:** Wrap strings with `_()` from `django.utils.translation`. Extract with:
  ```bash
  python manage.py makemessages -l en -a
  ```
- We use `ngx-translate` JSON (not Angular XLIFF / `ng extract-i18n`).
