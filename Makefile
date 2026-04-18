.PHONY: up down logs shell-be shell-fe test-be test-fe build lint tunnel

# ---------- Local dev (docker-compose) ----------

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

# ---------- ngrok tunnel ----------

tunnel:
	docker compose --profile tunnel up -d ngrok
	@echo "ngrok UI: http://localhost:4040"
