.PHONY: setup up down logs shell-be shell-fe test-be test-fe build lint tunnel schema-export schema-types schema

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
