.DEFAULT_GOAL := help

COMPOSE     := docker compose
DEV_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.dev.yml
API_DIR     := apps/api
WEB_DIR     := apps/web

.PHONY: help dev up down restart logs ps build migrate revision \
        test lint format typecheck check import-data \
        shell-api psql redis-cli clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- stack -------------------------------------------------------------------

dev: ## Run the full stack with hot reload (foreground)
	$(DEV_COMPOSE) up --build

up: ## Start the production-shaped stack in the background
	$(COMPOSE) up -d --build

down: ## Stop the stack
	$(DEV_COMPOSE) down

restart: down dev ## Restart the development stack

logs: ## Follow logs (make logs s=api)
	$(DEV_COMPOSE) logs -f $(s)

ps: ## Show service status
	$(DEV_COMPOSE) ps

build: ## Build all images
	$(DEV_COMPOSE) build

# --- database ----------------------------------------------------------------

migrate: ## Apply database migrations
	$(DEV_COMPOSE) run --rm api alembic upgrade head

revision: ## Create a migration (make revision m="add trips")
	$(DEV_COMPOSE) run --rm api alembic revision --autogenerate -m "$(m)"

import-data: ## Import the static GTFS feed
	@echo "Not implemented yet - arrives with the GTFS importer in Phase 2."

# --- quality -----------------------------------------------------------------

test: ## Run backend tests
	cd $(API_DIR) && uv run pytest

lint: ## Lint backend and frontend
	cd $(API_DIR) && uv run ruff check .
	cd $(WEB_DIR) && npm run lint

format: ## Format backend code
	cd $(API_DIR) && uv run ruff format .
	cd $(API_DIR) && uv run ruff check --fix .

typecheck: ## Type-check backend and frontend
	cd $(API_DIR) && uv run mypy app
	cd $(WEB_DIR) && npm run typecheck

check: lint typecheck test ## Run every quality gate

# --- shells ------------------------------------------------------------------

shell-api: ## Shell into the api container
	$(DEV_COMPOSE) exec api bash

psql: ## Open a psql session
	$(DEV_COMPOSE) exec postgres psql -U $${POSTGRES_USER:-zug} -d $${POSTGRES_DB:-zug}

redis-cli: ## Open a redis-cli session
	$(DEV_COMPOSE) exec redis redis-cli

clean: ## Stop the stack and delete its volumes (destroys the database)
	$(DEV_COMPOSE) down -v
