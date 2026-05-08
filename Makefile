.PHONY: up down logs shell-be shell-fe test-be test-fe build lint tunnel schema-export schema-types schema

# ---------- Local dev (docker-compose) ----------

# `make up` boots the full stack including the ngrok tunnel (so AC-00-10 and
# any TradingView webhook test can hit the local backend). Equivalent to:
#   docker compose --profile tunnel up -d
# Add `--build` if you want to force-rebuild images:
#   docker compose --profile tunnel up --build
up:
	docker compose --profile tunnel up -d

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
