# BankOps AI Command Center — Makefile
# SYNTHETIC DEMO ONLY. Common development and verification tasks.

.PHONY: help install-backend install-frontend migrate seed reset-demo \
        run-backend run-frontend run-all \
        test-backend test-frontend test-e2e test-all \
        lint lint-backend lint-frontend typecheck \
        check-deps check-deps-backend check-deps-frontend \
        docker-build docker-up docker-down docker-logs \
        clean

PYTHON ?= python
VENV ?= backend/.venv
VENV_PY := $(VENV)/Scripts/python
ifeq ($(wildcard $(VENV)/Scripts/python),)
VENV_PY := $(VENV)/bin/python
endif

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---- installation ----

install-backend: ## Create venv and install backend dependencies
	cd backend && $(PYTHON) -m venv .venv && \
	  $(VENV_PY) -m pip install --upgrade pip && \
	  $(VENV_PY) -m pip install -r requirements-dev.txt

install-frontend: ## Install frontend dependencies
	cd frontend && npm ci

install: install-backend install-frontend ## Install everything

# ---- database ----

migrate: ## Run Alembic migrations
	cd backend && $(VENV_PY) -m alembic upgrade head

seed: migrate ## Seed synthetic demo data
	cd backend && $(VENV_PY) -m app.cli seed

reset-demo: ## Reset demo to seeded baseline (admin only)
	cd backend && $(VENV_PY) -m app.cli reset-demo

# ---- run ----

run-backend: ## Start the backend dev server (port 8000)
	cd backend && $(VENV_PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

run-frontend: ## Start the frontend dev server (port 5173)
	cd frontend && npm run dev

run-all: ## Start both backend and frontend (use two terminals in practice)
	@echo "Run 'make run-backend' and 'make run-frontend' in separate terminals."

# ---- tests ----

test-backend: ## Run backend tests
	cd backend && $(VENV_PY) -m pytest

test-frontend: ## Run frontend unit tests
	cd frontend && npm run test

test-e2e: ## Run Playwright E2E tests (requires backend + frontend running)
	cd frontend && npx playwright test

test-all: test-backend test-frontend ## Run all tests

# ---- linting & type checking ----

lint-backend: ## Lint backend with ruff
	cd backend && $(VENV_PY) -m ruff check app tests

lint-frontend: ## Lint frontend with eslint
	cd frontend && npm run lint

lint: lint-backend lint-frontend ## Lint everything

typecheck: ## Type-check frontend with tsc
	cd frontend && npm run typecheck

# ---- supply chain ----

check-deps-backend: ## Check backend dependency ages (>= 7 days)
	cd backend && $(VENV_PY) scripts/check_dependency_age.py

check-deps-frontend: ## Check frontend dependency ages (>= 7 days)
	cd frontend && node scripts/check_npm_dependency_age.mjs

check-deps: check-deps-backend check-deps-frontend ## Check all dependency ages

# ---- docker ----

docker-build: ## Build Docker images
	docker compose -f docker/docker-compose.yml build

docker-up: ## Start Docker Compose stack (PostgreSQL + backend + frontend)
	docker compose -f docker/docker-compose.yml up -d

docker-down: ## Stop Docker Compose stack
	docker compose -f docker/docker-compose.yml down

docker-logs: ## Tail Docker Compose logs
	docker compose -f docker/docker-compose.yml logs -f

# ---- cleanup ----

clean: ## Remove build artifacts
	rm -rf frontend/dist frontend/node_modules/.vite
	rm -rf backend/data/*.db backend/data/*.db-journal
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
