# Code Style Guide

This document describes code style and API design for AgentCrawl, based on the
patterns adopted during the Phase 3–4 refactor (public read-only properties,
shared fixtures, proper typing, and `cast()` with runtime validation).

## Table of Contents

1. [Public vs Private API](#public-vs-private-api)
2. [Type Annotations](#type-annotations)
3. [Protocol Usage](#protocol-usage)
4. [Optional Dependencies](#optional-dependencies)
5. [Cast Usage](#cast-usage)
6. [Naming Conventions](#naming-conventions)
7. [Linting](#linting)

## Public vs Private API

### Public API

- **Naming:** No leading underscore
- **Documentation:** Required docstring
- **Stability:** Maintain backward compatibility
- **Testing:** Test through the public API (never reach into `_private` attrs)

The canonical example is `CrawlEngine` (`agentcrawl/core/engine.py`). Internal
state is stored on `_is_started` (private), but tests and consumers read it
through the public `is_started` property added in commit `73b4921`:

```python
class CrawlEngine:
    def __init__(self, browser_config: BrowserConfig | None = None,
                 settings: Settings | None = None) -> None:
        self._is_started = False  # Private backing field

    @property
    def is_started(self) -> bool:
        """Return whether the engine has been started."""
        return self._is_started

    async def startup(self) -> None:
        """Start the engine (initialize browser, cache, etc.)."""
        if self._is_started:
            return
        # ... initialize browser, cache ...
        self._is_started = True
```

### Private API

- **Naming:** Leading underscore (`_method`, `_attribute`)
- **Documentation:** Optional (but encouraged)
- **Stability:** May change without notice
- **Testing:** Tests must not assert on private attributes directly

**Audit evidence:** See `references/private_attribute_access_audit_report.md`
for the full list of private attribute accesses that were converted to public
property reads during Phase 4.

## Type Annotations

### Required

All public functions must have type annotations:

```python
# Good
def scrape(url: str, depth: int = 1) -> CrawlResult:
    ...

# Bad
def scrape(url, depth=1):
    ...
```

### Complex Types

```python
from typing import Any, Callable, Optional, Union
from collections.abc import Awaitable

# Optional
def find_user(id: str) -> Optional[User]: ...

# Union (Python 3.10+ syntax preferred)
def process(input: str | bytes) -> str: ...

# Callable
def retry(fn: Callable[[], Awaitable[Any]], times: int) -> Any: ...
```

### Generic helpers

Use `TypeVar` bound to the module's generic interface when a helper returns
the same type it receives, e.g. the `BaseCacheManager` / cache backend interface
in `agentcrawl/cache/`.

## Protocol Usage

Use `Protocol` for duck typing instead of forced inheritance when a class
happens to satisfy an interface. Always pair with `@runtime_checkable` when
you need `isinstance` checks.

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol for cache backends."""

    async def get(self, key: str) -> Optional[str]: ...
    async def set(self, key: str, value: str) -> None: ...


class RedisCache:
    async def get(self, key: str) -> Optional[str]: ...
    async def set(self, key: str, value: str) -> None: ...


# Works without explicit inheritance
cache: CacheBackend = RedisCache()
```

AgentCrawl applies this pattern to its pluggable cache backends
(`MemoryCache`, `RedisCache`, `DiskCache`) in `agentcrawl/cache/`.

## Optional Dependencies

Use `try/except ImportError` for optional dependencies (langchain, crewai,
weasyprint, markdown, etc.). Define the public function at module level — never
inside the `except` block — and raise a helpful, actionable error there.

```python
try:
    from langchain.tools import BaseTool

    class AgentCrawlTool(BaseTool):
        name: str = "agentcrawl"
        ...

    def get_langchain_tools(toolkit: AgentCrawlToolkit | None = None) -> list[Any]:
        """Get LangChain tools."""
        tk = toolkit or AgentCrawlToolkit()
        return [
            AgentCrawlTool(toolkit=tk),
            AgentCrawlSearchTool(toolkit=tk),
        ]

except ImportError:
    # Stubs that raise helpful errors at call time
    AgentCrawlTool = None  # type: ignore[assignment,misc]
    AgentCrawlSearchTool = None  # type: ignore[assignment,misc]

    def get_langchain_tools(toolkit: AgentCrawlToolkit | None = None) -> list[Any]:
        """Get LangChain tools (requires langchain)."""
        raise ImportError(
            "LangChain is required. Install with: pip install langchain"
        ) from None
```

**Key points:**

- Functions live at module level (consistent import path for callers).
- The `except` block assigns `None` stubs plus a function that raises — so a
  missing optional dependency fails fast with a clear message instead of an
  `AttributeError` later.
- Use `raise ... from None` to suppress the original `ImportError` chain.

## Cast Usage

`cast()` is permitted **only** when paired with runtime validation that makes
the cast safe. The canonical example is `normalize_unicode` in
`agentcrawl/utils/text.py`:

```python
_VALID_NORMALIZE_FORMS = ("NFC", "NFD", "NFKC", "NFKD")


def normalize_unicode(text: str, form: str = "NFC") -> str:
    """Normalize Unicode text to the specified form."""
    # Runtime validation ensures form is valid before cast
    if form not in _VALID_NORMALIZE_FORMS:
        raise ValueError(
            f"Invalid normalization form: {form!r}. "
            f"Must be one of: {_VALID_NORMALIZE_FORMS}"
        )

    # cast is safe because the check above guarantees form is a valid Literal
    typed_form = cast("Literal['NFC', 'NFD', 'NFKC', 'NFKD']", form)
    return unicodedata.normalize(typed_form, text)
```

**Rule:** If you need `cast()`, add runtime validation first. A bare
`cast(str, data)` with no validation is a suppression smell — see
[Suppression Policy](SUPPRESSION_POLICY.md).

## Naming Conventions

### Files
- `snake_case.py` for modules
- `test_*.py` for test files

### Classes
- `PascalCase` for class names
- `Test*` prefix for test classes

### Functions / Methods
- `snake_case` for regular functions
- `_leading_underscore` for private methods
- `__dunder__` for special methods

### Constants
- `UPPER_SNAKE_CASE` for module-level constants (e.g. `_VALID_NORMALIZE_FORMS`
  is intentionally private; exported constants are uppercase without underscore).

### Type Variables
- `T`, `U`, `V` for generic types
- `_T` for module-level type variables not part of the public API

## Linting

We use **Ruff** for linting and formatting, and **mypy** for type checking.

```bash
# Check
ruff check agentcrawl/ server/ tests/

# Format
ruff format agentcrawl/ server/ tests/

# Type check
mypy agentcrawl/ server/

# Auto-fix
ruff check --fix agentcrawl/
```

Pre-commit hooks run these automatically (see `.pre-commit-config.yaml` and
`Makefile` targets `quick-lint`, `test`, `pre-push`).

## References

- [PEP 8](https://peps.python.org/pep-0008/)
- [PEP 257](https://peps.python.org/pep-0257/) (docstrings)
- [PEP 484](https://peps.python.org/pep-0484/) (type hints)
- [Suppression Policy](SUPPRESSION_POLICY.md)
- Audit reports: `references/heavy_mocking_audit_report.md`,
  `references/private_attribute_access_audit_report.md`
