# Suppression Policy

This document describes our policy for type/lint suppressions
(`# type: ignore[...]`, `# noqa`, `# ruff: noqa`).

## Core Principle

> **No suppression without root cause fix.**

We prefer fixing the underlying issue over suppressing the warning. Every
suppression must be justified and use a specific error code — never a bare
`# type: ignore`.

## Acceptable Suppressions

The following suppressions are acceptable when documented with a comment
explaining why the root cause cannot be fixed in-tree.

### 1. Third-Party Libraries Without Stubs

When a library does not ship with `py.typed` (e.g. `markdown`, `weasyprint`),
prefer a scoped override in `pyproject.toml`:

```toml
# In pyproject.toml (PREFERRED)
[[tool.mypy.overrides]]
module = "markdown.*"
ignore_missing_imports = true
```

An inline suppression is acceptable only if `pyproject.toml` is not suitable:

```python
# Acceptable: weasyprint does not ship py.typed
import weasyprint  # type: ignore[import-untyped]
```

### 2. Optional Dependencies

For `try/except ImportError` patterns, the `None` stub assignment needs a
suppression because `None` is not a valid type for the symbol:

```python
try:
    from langchain.tools import BaseTool

    class AgentCrawlTool(BaseTool):
        ...

except ImportError:
    AgentCrawlTool = None  # type: ignore[assignment,misc]
```

**Requirements:**

- Must be inside the `except` block (not a module-level `import`).
- Must be a `None` assignment.
- Must carry `# type: ignore[assignment,misc]`.

See the full pattern in [Code Style Guide — Optional Dependencies](CODE_STYLE.md#optional-dependencies).

### 3. Decorator Metadata

When a decorator attaches metadata to a function object:

```python
def my_hook(fn):
    fn._hook_metadata = {...}  # type: ignore[attr-defined]
    return fn
```

### 4. Cast with Runtime Validation

`cast()` itself is not a suppression, but it is only allowed when preceded by
runtime validation:

```python
if form not in valid_forms:
    raise ValueError(f"Invalid form: {form}")

# Runtime check above guarantees form is a Literal member
typed_form = cast(Literal["NFC", "NFD", "NFKC", "NFKD"], form)
```

**Requirements:**

- A runtime validation check must precede the `cast`.
- A comment must explain why the cast is safe.

### 5. Test-Only Intentional Violations

When a test deliberately passes an invalid value to exercise a validation
path, use a targeted suppression on the offending argument:

```python
def test_invalid_input():
    # Deliberately pass None to test validation
    result = converter.convert(None)  # type: ignore[arg-type]
    assert result == ""
```

## Unacceptable Suppressions

The following are **not** acceptable and must be removed or replaced.

### 1. Hiding Bugs

```python
# BAD: hiding a type error instead of fixing it
result = process(data)  # type: ignore
```

**Fix:** Determine the correct type and annotate properly.

### 2. Duck Typing Instead of isinstance

```python
# BAD: cast after hasattr instead of an isinstance check
if hasattr(obj, "method"):
    return cast(MyClass, obj)
```

**Fix:** Use an explicit `isinstance` check:

```python
if isinstance(obj, MyClass):
    return obj
```

### 3. Empty Except Blocks

```python
# BAD: silent failure
try:
    risky_operation()
except Exception:
    pass  # Silent failure
```

**Fix:** Log the error:

```python
import logging

logger = logging.getLogger(__name__)

try:
    risky_operation()
except Exception as e:
    logger.debug("Operation failed: %s", e)
```

### 4. Private API Workarounds

```python
# BAD: reaching into private constructor params
settings = Settings(_env_prefix="CUSTOM_")  # type: ignore[call-arg]
```

**Fix:** Use the public API or a dynamic subclass pattern.

### 5. Bare Type Ignores

```python
# BAD: no error code specified
result = function(None)  # type: ignore
```

**Fix:** Specify the error code:

```python
result = function(None)  # type: ignore[arg-type]
```

## How to Justify Suppressions

Every suppression must have a justification in one of these forms:

### Comment Justification

Inline comment naming the third party or the reason:

```python
# Acceptable: pydantic v1 does not ship py.typed on some platforms
import pydantic  # type: ignore[import-untyped]
```

### Docstring Explanation

A note in the function docstring explaining the suppression context:

```python
def from_env(cls, prefix: str):
    """Create settings with a custom prefix.

    Note: Uses a dynamic subclass to override ``env_prefix`` because
    Pydantic v2 SettingsConfigDict does not expose a runtime ``_env_prefix``
    setter on the instance.
    """
    ...
```

### Commit Message

For suppressions added in a commit, explain in the commit message why the
root cause could not be fixed and what alternatives were considered.

## Review Process

### Adding New Suppressions

1. **Attempt a root cause fix first.**
2. **If not possible, document why** in a comment.
3. **Use a specific error code** (e.g. `# type: ignore[attr-defined]`), never
   a bare `# type: ignore`.
4. **Mention it in the PR description** when adding a new suppression.

### Reviewing Suppressions

When reviewing code with suppressions:

1. **Is there a root cause fix?** Try to find one.
2. **Is the suppression necessary?** Verify the underlying warning is real.
3. **Is it documented?** Check for a comment or docstring.
4. **Is it specific?** Must carry an error code, not a bare ignore.

### Audit Schedule

We audit suppressions quarterly. Script:

```bash
# 1. Count total suppressions
grep -r "type: ignore" agentcrawl/ | wc -l

# 2. Classify (manual pass against this policy)
grep -r "type: ignore" agentcrawl/ server/

# 3. Remove unacceptable / add comments for questionable ones
```

Audit findings are recorded in:

- `references/heavy_mocking_audit_report.md`
- `references/private_attribute_access_audit_report.md`

## Statistics Tracking

Track these metrics (current baseline after Phase 4):

- **Total `# type: ignore` suppressions:** see audit scripts above
  (baseline audited in Phase 4; acceptable ones are in `try/except ImportError`
  blocks and third-party `import-untyped` sites).
- **Bare `# type: ignore` (no code):** 0 — enforced by Ruff rule `PGH003`
  in `pyproject.toml`.
- **New suppressions per PR:** should be minimal (0 preferred).

## References

- [mypy error codes](https://mypy.readthedocs.io/en/stable/error_code_list.html)
- [Ruff rules](https://docs.astral.sh/ruff/rules/)
- Audit reports: `references/heavy_mocking_audit_report.md`,
  `references/private_attribute_access_audit_report.md`
- [Code Style Guide](CODE_STYLE.md)
