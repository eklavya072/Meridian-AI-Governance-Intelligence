# Meridian — single entry point.
#
# Every instruction in the README is a target here. If a step needs a
# paragraph of shell to explain, it belongs in this file instead.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND      := backend
COMPOSE      := docker compose
IMAGE        ?= ghcr.io/eklavya072/meridian
TAG          ?= latest
# Set from the measured suite, not aspirationally. See docs/MEASUREMENTS.md.
COV_MIN      ?= 58

# uv runs everything Python. It resolves from uv.lock, so a target behaves
# the same here as it does in CI and in the image.
UV           := uv
RUN          := $(UV) run --project $(BACKEND)

.PHONY: help setup up down logs test test-container lint format typecheck \
        check build build-prod bench deploy destroy clean measure ps shell

help: ## Show the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── Local development ────────────────────────────────────────────────────

setup: ## Install the locked dependency set (backend) and frontend packages
	$(UV) sync --project $(BACKEND) --frozen
	cd frontend && npm ci
	@test -f .env || (cp .env.example .env && echo "Created .env — add your GEMINI_API_KEY")

up: ## Bring up the whole stack (API, Postgres, frontend)
	$(COMPOSE) up --build -d
	@echo "API      http://localhost:8000  (docs at /docs)"
	@echo "Frontend http://localhost:3000"
	@echo "Readiness: make ready"

down: ## Stop the stack, keeping volumes
	$(COMPOSE) down

logs: ## Follow the API logs
	$(COMPOSE) logs -f api

ps: ## Show stack status
	$(COMPOSE) ps

ready: ## Poll /readyz until the API reports ready
	@for i in $$(seq 1 60); do \
		if curl -fsS http://localhost:8000/readyz >/dev/null 2>&1; then \
			curl -s http://localhost:8000/readyz; echo; exit 0; \
		fi; sleep 2; \
	done; \
	echo "not ready after 120s — last response:"; \
	curl -s http://localhost:8000/readyz || true; exit 1

shell: ## Open a shell in the running API container
	$(COMPOSE) exec api /bin/bash

# ── Quality gates — the same commands CI runs ────────────────────────────

lint: ## ruff check + format check
	$(RUN) ruff check $(BACKEND)
	$(RUN) ruff format --check $(BACKEND)

format: ## Apply ruff fixes and formatting
	$(RUN) ruff check --fix $(BACKEND)
	$(RUN) ruff format $(BACKEND)

typecheck: ## mypy over the modules in scope (see pyproject.toml)
	cd $(BACKEND) && $(UV) run mypy

test: ## Run the suite with the coverage gate
	cd $(BACKEND) && $(UV) run pytest -q --cov --cov-report=term-missing \
		--cov-fail-under=$(COV_MIN)

test-container: ## Run the suite INSIDE the built image, as CI does
	docker build --target test -t meridian-test:local $(BACKEND)
	docker run --rm meridian-test:local pytest -q

check: lint typecheck test ## Everything CI runs, in CI's order

# ── Build and release ────────────────────────────────────────────────────

build: ## Build the prod image locally
	docker build --target prod -t $(IMAGE):$(TAG) $(BACKEND)

build-prod: build ## Alias for build

bench: ## Re-measure what docs/MEASUREMENTS.md reports (no Gemini calls)
	cd $(BACKEND) && $(UV) run python scripts_measure_verification.py

measure: bench ## Alias for bench

# ── Deployment ───────────────────────────────────────────────────────────

deploy: ## Bring up the production stack (needs .env.prod — see LAUNCH.md)
	@test -f .env.prod || (echo "Missing .env.prod — see LAUNCH.md"; exit 1)
	$(COMPOSE) -f docker-compose.prod.yml up -d --build
	$(MAKE) ready

destroy: ## Tear down the production stack AND its volumes (destructive)
	@echo "This deletes the Postgres data and the Chroma index. Ctrl-C to abort."
	@sleep 5
	$(COMPOSE) -f docker-compose.prod.yml down -v

clean: ## Remove local caches and build output
	find $(BACKEND) -name __pycache__ -type d -not -path "*/.venv/*" -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache \
	       $(BACKEND)/.coverage $(BACKEND)/htmlcov frontend/.next
