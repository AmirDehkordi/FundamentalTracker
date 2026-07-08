# Local/macOS developer entrypoints. CI calls the underlying tools directly (see .github/workflows).
.DEFAULT_GOAL := help
.PHONY: help setup db-up db-down init-db ingest ingest-cache run test test-all verify \
        evals seed-dump fresh-check

# Coverage gate, per CLAUDE.md. Restored to 80 in P2 now that ingestion carries real logic.
COV_FAIL_UNDER := 80

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

verify: ## Format check + lint + types + unit tests with coverage gate
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy backend/src
	uv run pytest -m "not integration" --cov=tracker --cov-report=term-missing \
		--cov-fail-under=$(COV_FAIL_UNDER)

evals: ## Run the eval question set against /api/ask (P9 — not yet implemented)
	uv run python -m evals.runner

seed-dump: ## Dump the current DB to seed/init (P3 — not yet implemented)
	@echo "seed-dump lands in P3"

fresh-check: ## Fresh-clone rehearsal (P10 — not yet implemented)
	@echo "fresh-check lands in P10"
