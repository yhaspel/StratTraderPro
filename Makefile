.PHONY: setup up down logs shell-be shell-fe test-be test-fe build lint tunnel schema-export schema-types schema prod-shell promote-owner

# ---------- First-time setup ----------

# `make setup` generates a SECRET_KEY + FERNET_KEK and writes backend/.env.
# Idempotent: if backend/.env already exists it is left untouched (delete it to
# regenerate). Run this once, then `docker compose up -d --build`.
setup:
	@if [ -f backend/.env ]; then \
		echo "backend/.env already exists — leaving it untouched. Delete it to regenerate secrets."; \
	else \
		eval "$$(bash scripts/gen-secrets.sh)"; \
		sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$$SECRET_KEY|" \
		    -e "s|^FERNET_KEK=.*|FERNET_KEK=$$FERNET_KEK|" \
		    backend/.env.example > backend/.env; \
		echo "✓ Wrote backend/.env with a fresh SECRET_KEY + FERNET_KEK."; \
		echo "  Next: docker compose up -d --build"; \
	fi

# ---------- Local dev (docker-compose) ----------

# `make up` boots the full stack (postgres + redis + backend + worker + beat +
# frontend). The ngrok tunnel is NOT included — it needs NGROK_AUTHTOKEN and is
# only for TradingView webhook testing. Bring it up separately with `make tunnel`.
# First run: `docker compose up -d --build` to build images.
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

# ---------- Shell access ----------

shell-be:
	docker compose exec backend bash

shell-fe:
	docker compose exec frontend sh

# ---------- Tests ----------

test-be:
	docker compose exec backend python -m pytest -v

test-fe:
	docker compose exec frontend npm test -- --no-watch --browsers=ChromeHeadless

# ---------- Linting ----------

lint:
	docker compose exec backend ruff check .
	docker compose exec frontend npm run lint

# ---------- Migrations ----------

migrate:
	docker compose exec backend python manage.py migrate

makemigrations:
	docker compose exec backend python manage.py makemigrations

# ---------- OpenAPI schema + type generation ----------

schema-export:
	docker compose exec backend python manage.py spectacular --file /app/openapi.json
	docker compose cp backend:/app/openapi.json docs/openapi/openapi.json

schema-types:
	cd frontend && npm run schema:types

schema: schema-export schema-types

# ---------- ngrok tunnel ----------

tunnel:
	docker compose --profile tunnel up -d ngrok
	@echo "ngrok UI: http://localhost:4040"

# ---------- Production (Railway) ----------

# Prod ops run INSIDE the deployed backend container — the house pattern for
# production ops (see docs/runbooks/*). One-time setup:
#   npm i -g @railway/cli && railway login && railway link   # link to production
# If your Railway CLI can't pass a command to `ssh`, run `railway ssh --service
# backend` and type the `python manage.py ...` part inside the container.

# Interactive Django shell against the PRODUCTION database.
prod-shell:
	railway ssh --service backend python manage.py shell

# Promote the owner to staff + superuser (idempotent, non-destructive). Bootstraps
# admin on a fresh instance — the M10 admin portal is is_staff-gated, so there is
# otherwise no way to grant the first staff account through the UI.
#   make promote-owner EMAIL=you@example.com
EMAIL ?= owner@example.com
promote-owner:
	railway ssh --service backend python manage.py promote_user $(EMAIL) --staff --superuser
