# Local/macOS developer entrypoints. CI calls the underlying tools directly (see .github/workflows).
.DEFAULT_GOAL := help
.PHONY: help setup db-up db-down init-db ingest ingest-cache run test test-all verify \
        evals seed-dump fresh-check web-setup web-verify

# Backend gate restored to 80 (metrics engine + ingestion carry real logic), per CLAUDE.md and
# PLAN.md §11. Services carry a tighter 90 gate — that is where correctness lives.
COV_FAIL_UNDER := 80
SERVICES_COV_FAIL_UNDER := 90

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install deps into the uv-managed venv
	uv sync

db-up: ## Start the Postgres 16 dev database (compose)
	docker compose up -d db

db-down: ## Stop the dev database
	docker compose down

init-db: ## Create all tables against DATABASE_URL (idempotent)
	uv run python scripts/init_db.py

ingest: ## Ingest live data (P2/P3 — not yet implemented)
	uv run python -m tracker.ingestion

ingest-cache: ## Replay ingestion from bronze cache, offline (P2/P3)
	uv run python -m tracker.ingestion --from-cache

run: ## Serve the API with reload
	uv run uvicorn tracker.api.app:create_app --factory --reload

test: ## Unit tests only (no postgres)
	uv run pytest -m "not integration"

test-all: ## Full suite incl. integration (needs postgres)
	uv run pytest

verify: ## Backend format+lint+types+coverage gates, then the frontend typecheck+build gate
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy backend/src evals
	uv run pytest -m "not integration" --cov=tracker --cov-report=term-missing \
		--cov-fail-under=$(COV_FAIL_UNDER)
	uv run pytest -m "not integration" --cov=tracker.services --cov-report=term-missing \
		--cov-fail-under=$(SERVICES_COV_FAIL_UNDER)
	$(MAKE) web-verify

web-setup: ## Install frontend deps from the lockfile (needs Node 20)
	cd frontend && npm ci

web-verify: ## Frontend: typecheck + lint + format check + production build (needs Node 20)
	cd frontend && npm run typecheck && npm run lint && npm run format:check && npm run build

evals: ## Run the eval question set against a running /api/ask (needs a live LLM key)
	uv run python -m evals.run

seed-dump: ## Dump the dev DB to seed/init/01_seed.sql.gz (auto-restored on a fresh clone)
	bash scripts/make_seed.sh

fresh-check: ## Fresh-clone rehearsal (P10 — not yet implemented)
	@echo "fresh-check lands in P10"
