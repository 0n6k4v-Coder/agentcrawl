# ══════════════════════════════════════════════════════════════
# AgentCrawl — Makefile
# AI-Ready Web Crawler & Scraper
# ══════════════════════════════════════════════════════════════

.DEFAULT_GOAL := help
SHELL := /bin/bash

# ──────────────────────────────────────────────────────────────
# Variables
# ──────────────────────────────────────────────────────────────

PYTHON          ?= python3
PIP             ?= pip
PROJECT_NAME    := agentcrawl
VERSION         := $(shell $(PYTHON) -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null || echo "0.0.0")
SERVER_PORT     ?= 8000
SERVER_HOST     ?= 0.0.0.0
REDIS_URL       ?= redis://localhost:6379
WORKERS         ?= 4
DOCKER_IMAGE    := agentcrawl
DOCKER_TAG      := $(VERSION)
COMPOSE_FILE    := docker-compose.yml

# Colors
CYAN  := \033[0;36m
GREEN := \033[0;32m
YELLOW:= \033[0;33m
RED   := \033[0;31m
NC    := \033[0m

# ──────────────────────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help message
	@echo ""
	@echo -e "$(CYAN)╔══════════════════════════════════════════════════╗$(NC)"
	@echo -e "$(CYAN)║       🕷️  AgentCrawl — Development Commands      ║$(NC)"
	@echo -e "$(CYAN)║       Version: $(VERSION)$(NC)"
	@echo -e "$(CYAN)╚══════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-22s$(NC) %s\n", $$1, $$2}'
	@echo ""

# ══════════════════════════════════════════════════════════════
# SETUP & INSTALLATION
# ══════════════════════════════════════════════════════════════

.PHONY: install
install: ## Install core package in editable mode
	@echo -e "$(CYAN)→ Installing $(PROJECT_NAME) (core)...$(NC)"
	$(PIP) install -e .
	@echo -e "$(GREEN)✓ Core package installed$(NC)"

.PHONY: install-all
install-all: ## Install package with ALL optional dependencies
	@echo -e "$(CYAN)→ Installing $(PROJECT_NAME) with all extras...$(NC)"
	$(PIP) install -e ".[all]"
	@echo -e "$(GREEN)✓ Full package installed$(NC)"

.PHONY: install-dev
install-dev: ## Install package with dev dependencies (linting, testing, docs)
	@echo -e "$(CYAN)→ Installing $(PROJECT_NAME) with dev tools...$(NC)"
	$(PIP) install -e ".[dev]"
	@echo -e "$(GREEN)✓ Dev environment ready$(NC)"

.PHONY: install-server
install-server: ## Install package with server dependencies only
	@echo -e "$(CYAN)→ Installing $(PROJECT_NAME) with server extras...$(NC)"
	$(PIP) install -e ".[server,redis]"
	@echo -e "$(GREEN)✓ Server dependencies installed$(NC)"

.PHONY: install-browsers
install-browsers: ## Install Playwright browsers (Chromium, Firefox, WebKit)
	@echo -e "$(CYAN)→ Installing Playwright browsers...$(NC)"
	$(PYTHON) -m playwright install --with-deps chromium
	@echo -e "$(GREEN)✓ Chromium installed$(NC)"

.PHONY: install-browsers-all
install-browsers-all: ## Install ALL Playwright browsers
	@echo -e "$(CYAN)→ Installing all Playwright browsers...$(NC)"
	$(PYTHON) -m playwright install --with-deps
	@echo -e "$(GREEN)✓ All browsers installed$(NC)"

.PHONY: setup
setup: install-dev install-browsers ## Full dev setup (deps + browsers)
	@echo -e "$(GREEN)✓ Full development environment ready$(NC)"

.PHONY: setup-minimal
setup-minimal: install install-browsers ## Minimal setup (core + chromium)
	@echo -e "$(GREEN)✓ Minimal environment ready$(NC)"

# ══════════════════════════════════════════════════════════════
# CODE QUALITY
# ══════════════════════════════════════════════════════════════

.PHONY: lint
lint: ## Run Ruff linter (check only)
	@echo -e "$(CYAN)→ Running Ruff linter...$(NC)"
	$(PYTHON) -m ruff check agentcrawl/ server/ agent/ tests/ examples/
	@echo -e "$(GREEN)✓ Lint passed$(NC)"

.PHONY: lint-fix
lint-fix: ## Run Ruff linter with auto-fix
	@echo -e "$(CYAN)→ Running Ruff linter (auto-fix)...$(NC)"
	$(PYTHON) -m ruff check --fix agentcrawl/ server/ agent/ tests/ examples/
	@echo -e "$(GREEN)✓ Lint fixed$(NC)"

.PHONY: format
format: ## Format code with Ruff
	@echo -e "$(CYAN)→ Formatting code...$(NC)"
	$(PYTHON) -m ruff format agentcrawl/ server/ agent/ tests/ examples/
	@echo -e "$(GREEN)✓ Code formatted$(NC)"

.PHONY: format-check
format-check: ## Check formatting without modifying files
	@echo -e "$(CYAN)→ Checking code formatting...$(NC)"
	$(PYTHON) -m ruff format --check agentcrawl/ server/ agent/ tests/ examples/
	@echo -e "$(GREEN)✓ Formatting OK$(NC)"

.PHONY: typecheck
typecheck: ## Run Mypy type checker
	@echo -e "$(CYAN)→ Running Mypy type checker...$(NC)"
	$(PYTHON) -m mypy agentcrawl/ server/ agent/
	@echo -e "$(GREEN)✓ Type check passed$(NC)"

.PHONY: check
check: lint format-check typecheck ## Run all quality checks (lint + format + types)
	@echo -e "$(GREEN)✓ All checks passed$(NC)"

.PHONY: fix
fix: lint-fix format ## Auto-fix lint issues and format code
	@echo -e "$(GREEN)✓ All fixes applied$(NC)"

# ══════════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════════

.PHONY: test
test: ## Run all tests
	@echo -e "$(CYAN)→ Running all tests...$(NC)"
	$(PYTHON) -m pytest tests/ -v --timeout=60
	@echo -e "$(GREEN)✓ All tests passed$(NC)"

.PHONY: test-unit
test-unit: ## Run unit tests only (no network, no browser)
	@echo -e "$(CYAN)→ Running unit tests...$(NC)"
	$(PYTHON) -m pytest tests/unit/ -v -m "unit" --timeout=30
	@echo -e "$(GREEN)✓ Unit tests passed$(NC)"

.PHONY: test-integration
test-integration: ## Run integration tests (requires network/browser)
	@echo -e "$(CYAN)→ Running integration tests...$(NC)"
	$(PYTHON) -m pytest tests/integration/ -v -m "integration" --timeout=120
	@echo -e "$(GREEN)✓ Integration tests passed$(NC)"

.PHONY: test-server
test-server: ## Run server mode tests
	@echo -e "$(CYAN)→ Running server tests...$(NC)"
	$(PYTHON) -m pytest tests/integration/ -v -m "server" --timeout=60
	@echo -e "$(GREEN)✓ Server tests passed$(NC)"

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	@echo -e "$(CYAN)→ Running tests with coverage...$(NC)"
	$(PYTHON) -m pytest tests/ -v --cov=agentcrawl --cov=server --cov=agent \
		--cov-report=term-missing --cov-report=html --cov-fail-under=80
	@echo -e "$(GREEN)✓ Coverage report generated → htmlcov/index.html$(NC)"

.PHONY: test-fast
test-fast: ## Run tests in parallel (fastest)
	@echo -e "$(CYAN)→ Running tests in parallel...$(NC)"
	$(PYTHON) -m pytest tests/ -v -n auto --timeout=60 -x
	@echo -e "$(GREEN)✓ All tests passed$(NC)"

.PHONY: test-watch
test-watch: ## Run tests in watch mode (re-run on file change)
	@echo -e "$(CYAN)→ Watching for changes... (Ctrl+C to stop)$(NC)"
	$(PYTHON) -m pytest tests/unit/ -v -f --timeout=30

# ══════════════════════════════════════════════════════════════
# SERVER MODE
# ══════════════════════════════════════════════════════════════

.PHONY: serve
serve: ## Run API server (dev mode, auto-reload)
	@echo -e "$(CYAN)→ Starting AgentCrawl server on $(SERVER_HOST):$(SERVER_PORT)...$(NC)"
	$(PYTHON) -m uvicorn server.main:app \
		--host $(SERVER_HOST) \
		--port $(SERVER_PORT) \
		--reload \
		--log-level info

.PHONY: serve-prod
serve-prod: ## Run API server (production, multi-worker)
	@echo -e "$(CYAN)→ Starting AgentCrawl server (production, $(WORKERS) workers)...$(NC)"
	$(PYTHON) -m gunicorn server.main:app \
		--worker-class uvicorn.workers.UvicornWorker \
		--bind $(SERVER_HOST):$(SERVER_PORT) \
		--workers $(WORKERS) \
		--timeout 120 \
		--access-logfile - \
		--error-logfile -

.PHONY: serve-redis
serve-redis: ## Run API server with Redis queue
	@echo -e "$(CYAN)→ Starting AgentCrawl server with Redis queue...$(NC)"
	AGENTCRAWL_QUEUE_BACKEND=redis \
	AGENTCRAWL_REDIS_URL=$(REDIS_URL) \
	AGENTCRAWL_AUTH_ENABLED=true \
	$(PYTHON) -m uvicorn server.main:app \
		--host $(SERVER_HOST) \
		--port $(SERVER_PORT) \
		--reload

# ══════════════════════════════════════════════════════════════
# DOCKER
# ══════════════════════════════════════════════════════════════

.PHONY: docker-build
docker-build: ## Build Docker image
	@echo -e "$(CYAN)→ Building Docker image $(DOCKER_IMAGE):$(DOCKER_TAG)...$(NC)"
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) -t $(DOCKER_IMAGE):latest .
	@echo -e "$(GREEN)✓ Docker image built$(NC)"

.PHONY: docker-run
docker-run: ## Run Docker container (single container, no Redis)
	@echo -e "$(CYAN)→ Running Docker container...$(NC)"
	docker run --rm -it \
		-p $(SERVER_PORT):8000 \
		--shm-size=1g \
		-e AGENTCRAWL_AUTH_ENABLED=false \
		$(DOCKER_IMAGE):latest

.PHONY: docker-up
docker-up: ## Start all services with Docker Compose
	@echo -e "$(CYAN)→ Starting Docker Compose services...$(NC)"
	docker compose -f $(COMPOSE_FILE) up -d --build
	@echo -e "$(GREEN)✓ Services started on port $(SERVER_PORT)$(NC)"

.PHONY: docker-down
docker-down: ## Stop all Docker Compose services
	@echo -e "$(CYAN)→ Stopping Docker Compose services...$(NC)"
	docker compose -f $(COMPOSE_FILE) down
	@echo -e "$(GREEN)✓ Services stopped$(NC)"

.PHONY: docker-logs
docker-logs: ## Tail Docker Compose logs
	docker compose -f $(COMPOSE_FILE) logs -f agentcrawl

.PHONY: docker-clean
docker-clean: ## Remove Docker images and volumes
	@echo -e "$(CYAN)→ Cleaning Docker resources...$(NC)"
	docker compose -f $(COMPOSE_FILE) down -v --rmi local
	docker rmi $(DOCKER_IMAGE):$(DOCKER_TAG) $(DOCKER_IMAGE):latest 2>/dev/null || true
	@echo -e "$(GREEN)✓ Docker resources cleaned$(NC)"

.PHONY: docker-push
docker-push: ## Push Docker image to registry
	@echo -e "$(CYAN)→ Pushing Docker image...$(NC)"
	docker push $(DOCKER_IMAGE):$(DOCKER_TAG)
	docker push $(DOCKER_IMAGE):latest
	@echo -e "$(GREEN)✓ Docker image pushed$(NC)"

# ══════════════════════════════════════════════════════════════
# BUILD & PACKAGE
# ══════════════════════════════════════════════════════════════

.PHONY: build
build: clean-dist ## Build wheel and sdist packages
	@echo -e "$(CYAN)→ Building package v$(VERSION)...$(NC)"
	$(PYTHON) -m build
	@echo -e "$(GREEN)✓ Package built → dist/$(NC)"
	@ls -lh dist/

.PHONY: publish
publish: build ## Publish package to PyPI
	@echo -e "$(CYAN)→ Publishing $(PROJECT_NAME) v$(VERSION) to PyPI...$(NC)"
	$(PYTHON) -m twine upload dist/*
	@echo -e "$(GREEN)✓ Published to PyPI$(NC)"

.PHONY: publish-test
publish-test: build ## Publish package to TestPyPI
	@echo -e "$(CYAN)→ Publishing to TestPyPI...$(NC)"
	$(PYTHON) -m twine upload --repository testpypi dist/*
	@echo -e "$(GREEN)✓ Published to TestPyPI$(NC)"

# ══════════════════════════════════════════════════════════════
# DOCUMENTATION
# ══════════════════════════════════════════════════════════════

.PHONY: docs-serve
docs-serve: ## Serve documentation locally (live reload)
	@echo -e "$(CYAN)→ Serving docs at http://127.0.0.1:8001...$(NC)"
	$(PYTHON) -m mkdocs serve -a 127.0.0.1:8001

.PHONY: docs-build
docs-build: ## Build documentation for production
	@echo -e "$(CYAN)→ Building documentation...$(NC)"
	$(PYTHON) -m mkdocs build
	@echo -e "$(GREEN)✓ Docs built → site/$(NC)"

.PHONY: docs-deploy
docs-deploy: ## Deploy documentation to GitHub Pages
	@echo -e "$(CYAN)→ Deploying docs to GitHub Pages...$(NC)"
	$(PYTHON) -m mkdocs gh-deploy --force
	@echo -e "$(GREEN)✓ Docs deployed$(NC)"

# ══════════════════════════════════════════════════════════════
# BENCHMARK & PROFILING
# ══════════════════════════════════════════════════════════════

.PHONY: benchmark
benchmark: ## Run performance benchmark
	@echo -e "$(CYAN)→ Running benchmark...$(NC)"
	$(PYTHON) scripts/benchmark.py
	@echo -e "$(GREEN)✓ Benchmark complete$(NC)"

.PHONY: profile
profile: ## Profile a scrape operation
	@echo -e "$(CYAN)→ Profiling scrape operation...$(NC)"
	$(PYTHON) -m cProfile -o profile.prof -m agentcrawl.core.engine
	$(PYTHON) -m pstats profile.prof
	@echo -e "$(GREEN)✓ Profile saved → profile.prof$(NC)"

# ══════════════════════════════════════════════════════════════
# CLEANUP
# ══════════════════════════════════════════════════════════════

.PHONY: clean
clean: clean-dist clean-cache clean-test clean-docs ## Clean all generated files
	@echo -e "$(GREEN)✓ All cleaned$(NC)"

.PHONY: clean-dist
clean-dist: ## Remove build artifacts
	@echo -e "$(CYAN)→ Cleaning dist/...$(NC)"
	rm -rf dist/ build/ *.egg-info .eggs/
	rm -rf agentcrawl/*.egg-info server/*.egg-info agent/*.egg-info

.PHONY: clean-cache
clean-cache: ## Remove Python cache files
	@echo -e "$(CYAN)→ Cleaning caches...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true

.PHONY: clean-test
clean-test: ## Remove test artifacts
	@echo -e "$(CYAN)→ Cleaning test artifacts...$(NC)"
	rm -rf htmlcov/ .coverage coverage.xml profile.prof

.PHONY: clean-docs
clean-docs: ## Remove built documentation
	@echo -e "$(CYAN)→ Cleaning docs...$(NC)"
	rm -rf site/

# ══════════════════════════════════════════════════════════════
# DEVELOPMENT UTILITIES
# ══════════════════════════════════════════════════════════════

.PHONY: pre-commit
pre-commit: ## Install and run pre-commit hooks
	@echo -e "$(CYAN)→ Setting up pre-commit hooks...$(NC)"
	$(PYTHON) -m pre_commit install
	$(PYTHON) -m pre_commit run --all-files
	@echo -e "$(GREEN)✓ Pre-commit hooks ready$(NC)"

.PHONY: openapi
openapi: ## Generate OpenAPI spec from FastAPI app
	@echo -e "$(CYAN)→ Generating OpenAPI spec...$(NC)"
	$(PYTHON) scripts/generate_openapi.py
	@echo -e "$(GREEN)✓ OpenAPI spec → openapi.json$(NC)"

.PHONY: version
version: ## Show current package version
	@echo "$(PROJECT_NAME) v$(VERSION)"

.PHONY: deps-tree
deps-tree: ## Show dependency tree
	@echo -e "$(CYAN)→ Dependency tree:$(NC)"
	$(PIP) install pipdeptree -q
	$(PYTHON) -m pipdeptree -p $(PROJECT_NAME)

.PHONY: outdated
outdated: ## Check for outdated dependencies
	@echo -e "$(CYAN)→ Checking outdated packages...$(NC)"
	$(PIP) list --outdated

.PHONY: security
security: ## Run security audit on dependencies
	@echo -e "$(CYAN)→ Running security audit...$(NC)"
	$(PIP) install pip-audit -q
	$(PYTHON) -m pip_audit

# ══════════════════════════════════════════════════════════════
# CI/CD PIPELINE
# ══════════════════════════════════════════════════════════════

.PHONY: ci
ci: check test-unit build ## Full CI pipeline (lint + typecheck + test + build)
	@echo -e "$(GREEN)╔══════════════════════════════════════╗$(NC)"
	@echo -e "$(GREEN)║   ✓ CI Pipeline Complete             ║$(NC)"
	@echo -e "$(GREEN)╚══════════════════════════════════════╝$(NC)"

.PHONY: ci-full
ci-full: check test build docker-build ## Full CI + Docker build
	@echo -e "$(GREEN)╔══════════════════════════════════════╗$(NC)"
	@echo -e "$(GREEN)║   ✓ Full CI Pipeline Complete        ║$(NC)"
	@echo -e "$(GREEN)╚══════════════════════════════════════╝$(NC)"

# ══════════════════════════════════════════════════════════════
# EXAMPLES
# ══════════════════════════════════════════════════════════════

.PHONY: example-basic
example-basic: ## Run basic scrape example
	$(PYTHON) examples/package_mode/basic_scrape.py

.PHONY: example-crawl
example-crawl: ## Run deep crawl example
	$(PYTHON) examples/package_mode/deep_crawl.py

.PHONY: example-llm
example-llm: ## Run LLM extraction example
	$(PYTHON) examples/package_mode/llm_extraction.py

.PHONY: example-rag
example-rag: ## Run RAG chunking example
	$(PYTHON) examples/package_mode/rag_chunking.py

.PHONY: example-search
example-search: ## Run search + scrape example
	$(PYTHON) examples/package_mode/search_and_scrape.py

.PHONY: example-server
example-server: ## Run server mode client example
	$(PYTHON) examples/server_mode/api_client.py

.PHONY: example-agent
example-agent: ## Run AI agent integration example
	$(PYTHON) examples/agent_integration/langchain_tool.py