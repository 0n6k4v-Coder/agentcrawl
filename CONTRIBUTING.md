# Contributing to AgentCrawl

Thank you for your interest in contributing to AgentCrawl! This document provides guidelines and information for contributors.

## Development Setup

### Prerequisites

- Python 3.10+
- Docker (optional, for local CI)
- Go 1.21+ (optional, for gacils)

### Installation

```bash
# Fork and clone the repository
git clone https://github.com/YOUR-USERNAME/agentcrawl.git
cd agentcrawl

# Install dependencies
make setup

# Install pre-commit hooks (recommended)
make pre-commit-setup

# Verify installation
make test
```

## Coding Standards

### Python Style

- **Formatter:** Ruff (configured in `pyproject.toml`)
- **Linter:** Ruff + mypy
- **Type hints:** Required for all public APIs
- **Docstrings:** Required for all public functions/classes

### Code Quality

Before committing:

```bash
make quick-lint  # Check lint + format
```

Pre-commit hooks will auto-check on every commit (if installed).

## Testing

### Running Tests

```bash
# Unit tests (fast, no browser needed)
make test

# All tests (unit + integration, needs Playwright)
make test-all

# Full CI simulation (Docker required)
make pre-push
```

### Writing Tests

- **Unit tests:** `tests/unit/` — test individual functions/classes
- **Integration tests:** `tests/integration/` — test full workflows

**Guidelines:**
- Write tests for all new features
- Maintain or improve test coverage
- Use descriptive test names

## Pull Request Process

1. **Fork and branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make changes:**
   - Follow coding standards
   - Add tests for new features
   - Update documentation if needed

3. **Verify locally:**
   ```bash
   make quick-lint  # Lint + format
   make test        # Unit tests
   make pre-push    # Full CI (optional)
   ```

4. **Commit:**
   - Use conventional commits (feat, fix, refactor, test, docs, style, chore)
   - Pre-commit hooks will auto-check

5. **Push:**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Open a PR:**
   - Fill out the PR template
   - Describe what the PR does
   - Explain how you tested it

## Conventional Commits

```
<type>(<scope>): <description>

Types:
  feat:     New feature
  fix:      Bug fix
  refactor: Code refactoring
  test:     Adding tests
  docs:     Documentation
  style:    Formatting, no code change
  chore:    Maintenance tasks

Examples:
  feat(extraction): add CSS selector support
  fix(server): resolve health check timeout
  test(integration): add search API tests
```

## Getting Help

- **Issues:** https://github.com/0n6k4v-Coder/agentcrawl/issues
- **Discussions:** https://github.com/0n6k4v-Coder/agentcrawl/discussions

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
