.PHONY: install install-server serve test test-all lint docker-up docker-down clean help

# Default target
help:
	@echo "AgentCrawl — Development Commands"
	@echo ""
	@echo "  make install         Install core package in editable mode"
	@echo "  make install-server  Install with server dependencies"
	@echo "  make serve           Run server from source (port 8000)"
	@echo "  make test            Run unit tests only"
	@echo "  make test-all        Run all tests (unit + integration)"
	@echo "  make lint            Run ruff + mypy on source"
	@echo "  make docker-up       Start Docker Compose (build + up)"
	@echo "  make docker-down     Stop Docker Compose"
	@echo "  make clean           Remove build artifacts"

# Install core package
install:
	pip install -e ".[dev]"

# Install with server dependencies
install-server:
	pip install -e ".[server,dev]"

# Run server from source
serve:
	python -m server --port 8000

# Run unit tests only
test:
	pytest tests/unit/ -v

# Run all tests
test-all:
	pytest tests/ -v

# Run linting and type checking
lint:
	ruff check agentcrawl/ agent/ server/
	mypy agentcrawl/

# Docker
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info/
	rm -rf agentcrawl/__pycache__/ server/__pycache__/ agent/__pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete